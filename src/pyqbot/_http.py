"""请求层：所有 OpenAPI 请求都经这里发出（`dev-prepare/api-call-guide.md`），失败映射见 `docs/design.md`。"""

import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import overload
from urllib.parse import parse_qsl, quote, urlsplit

import httpx2
import msgspec

from ._config import Config
from ._credentials import TRACE_ID_HEADER, find_error_code
from ._errors import APIError, NetworkError
from ._model import Model, decode
from ._redact import redact, redact_optional, safe_cause

type QueryParams = Mapping[str, str | int]


class HTTP:
    """带鉴权的请求，响应解码成模型，失败映射成 `APIError` / `NetworkError`。

    `get_token` 是 `Client.get_access_token`：客户端关闭后它抛 `RuntimeError`，请求也随之被拒。
    `known_secrets` 给出要脱敏的全部凭证：平台回显的可能是已经换掉的旧 token，不只是本次请求用的。
    """

    def __init__(
        self,
        config: Config,
        http_client: httpx2.AsyncClient,
        get_token: Callable[[], Awaitable[str]],
        known_secrets: Callable[[], Iterable[str | None]],
    ) -> None:
        self._config = config
        self._http_client = http_client
        self._get_token = get_token
        self._known_secrets = known_secrets

    @overload
    async def request[T](
        self,
        method: str,
        path: str,
        *,
        type_: type[T],
        params: QueryParams | None = None,
        json: object = None,
    ) -> T: ...

    @overload
    async def request(
        self,
        method: str,
        path: str,
        *,
        type_: None,
        params: QueryParams | None = None,
        json: object = None,
    ) -> None: ...

    async def request[T](
        self,
        method: str,
        path: str,
        *,
        type_: type[T] | None,
        params: QueryParams | None = None,
        json: object = None,
    ) -> T | None:
        """发请求并把响应体解码成 `type_`（`None` 则不解码）；`path` 里的路径参数先经 `path_segment()`。"""
        config = self._config
        token = await self._get_token()
        secrets = (*self._known_secrets(), token)
        headers = {"Authorization": f"QQBot {token}"}
        content = None
        if json is not None:
            content = msgspec.json.encode(json)
            headers["Content-Type"] = "application/json"
        try:
            response = await self._http_client.request(
                method,
                config.base_url + path,
                content=content,
                params=params,
                headers=headers,
                timeout=config.timeout,
            )
        except httpx2.RequestError as exc:
            raise _network_error(f"{method} {path}", exc, secrets) from safe_cause(exc, *secrets)

        return _parse_response(response, type_, f"{method} {path}", secrets)

    async def put_presigned(
        self, url: str, content: bytes, *, content_type: str | None = None
    ) -> httpx2.Response:
        """把 `content` PUT 到对象存储（COS）的预签名地址，返回 2xx 的响应；不加鉴权头，不解析响应体。

        失败同样抛 `NetworkError` / `APIError`，但文案只写主机与路径：查询串是临时签名，不进文案和异常链。
        """
        try:
            target = httpx2.URL(url)
        except httpx2.InvalidURL:
            # 底层文案可能带着地址，不保留异常链。
            raise NetworkError("PUT 预签名地址失败：地址不合法") from None
        action = f"PUT {target.copy_with(query=None)}"
        secrets = (*self._known_secrets(), *_signature_parts(url, target))
        headers = {} if content_type is None else {"Content-Type": content_type}
        # 自己构造 Request 再 send()：不合并客户端默认的 headers、cookies、params（params 会替换掉
        # 签名查询串），auth=None 关掉客户端的鉴权，也不跟随重定向，免得签名和数据被带到别处。
        request = httpx2.Request(
            "PUT",
            target,
            content=content,
            headers=headers,
            extensions={"timeout": httpx2.Timeout(self._config.timeout).as_dict()},
        )
        try:
            response = await self._http_client.send(request, auth=None, follow_redirects=False)
        except httpx2.RequestError as exc:
            raise _network_error(action, exc, secrets) from safe_cause(exc, *secrets)
        if not response.is_success:
            # COS 的失败响应是 XML，<Code> 是 SignatureDoesNotMatch 这类错误名，便于排查。
            code = _COS_ERROR_CODE.search(response.text)
            reason = f"HTTP {response.status_code}" + (f" {code[1]}" if code else "")
            raise APIError(
                f"{action} 失败：{redact(reason, *secrets)}", status_code=response.status_code
            )
        return response


def path_segment(value: str, name: str) -> str:
    """把路径参数转义成一段路径，防止 `/`、`..` 改变请求的接口。

    Raises:
        ValueError: `value` 为空，或是 `.`、`..`（转义不了，会被当成相对路径）。
    """
    if value in ("", ".", ".."):
        raise ValueError(f"{name} 不合法：{value!r}")
    return quote(value, safe="")


_COS_ERROR_CODE = re.compile(r"<Code>([^<]{1,64})</Code>")
_MIN_SIGNATURE_PART = 8


def _signature_parts(url: str, target: httpx2.URL) -> set[str]:
    """预签名地址里要隐藏的部分：整个地址与查询串，以及较长的参数值（编码前后两种写法）。"""
    queries = {urlsplit(url).query, target.query.decode("ascii", "replace")}
    parts = {url, str(target), *queries}
    for query in queries:
        parts.update(item.partition("=")[2] for item in query.split("&"))
        parts.update(value for _, value in parse_qsl(query))
    # 短的取值（如 partNumber=1）不是签名，替换掉反而会把文案里的数字都换成 ***。
    return {part for part in parts if len(part) >= _MIN_SIGNATURE_PART}


def _network_error(
    action: str, exc: httpx2.RequestError, secrets: Iterable[str | None]
) -> NetworkError:
    reason = (
        "请求超时"
        if isinstance(exc, httpx2.TimeoutException)
        else redact(str(exc) or type(exc).__name__, *secrets)
    )
    return NetworkError(f"{action} 失败：{reason}")


class _ErrorBody(Model):
    # 通用失败结构用 err_code；code 是获取 token 接口的写法，两个都认（docs/errata.md）。
    # 类型写成 object：写成 int | str 的话，类型不符的错误码会被宽容解码丢掉，失败就成了成功。
    code: object = None
    err_code: object = None
    message: str | None = None
    trace_id: str | None = None


def _parse_response[T](
    response: httpx2.Response,
    type_: type[T] | None,
    action: str,
    secrets: tuple[str | None, ...],
) -> T | None:
    status_code = response.status_code
    trace_id = response.headers.get(TRACE_ID_HEADER)
    content = response.content

    def fail(reason: str, err_code: int | None = None) -> APIError:
        return APIError(
            f"{action} 失败：{redact(reason, *secrets)}",
            status_code=status_code,
            err_code=err_code,
            trace_id=redact_optional(trace_id, *secrets),
        )

    if content.strip():
        try:
            body = decode(content, _ErrorBody)
        except msgspec.ValidationError:
            body = _ErrorBody()  # 合法的 JSON 但不是对象（如数组），不可能是失败结构
        except (msgspec.DecodeError, RecursionError) as exc:
            raise fail(f"无法解析响应（HTTP {status_code}）") from safe_cause(exc, *secrets)
        trace_id = trace_id or body.trace_id
        # 201、202 也是 2xx，但文档说它们带失败结构，靠错误码识别。
        failed, err_code = find_error_code(body.err_code, body.code)
        if failed or not response.is_success:
            raise fail(body.message or f"HTTP {status_code}", err_code)
    elif not response.is_success:
        raise fail(f"HTTP {status_code}")

    if type_ is None:
        return None
    try:
        return decode(content, type_)
    except (msgspec.DecodeError, RecursionError) as exc:
        raise fail(f"响应无法识别（HTTP {status_code}）") from safe_cause(exc, *secrets)
