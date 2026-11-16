"""请求层：所有 OpenAPI 请求都经这里发出（`dev-prepare/api-call-guide.md`），失败映射见 `docs/design.md`。"""

import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import overload
from urllib.parse import parse_qsl, quote, urlsplit

import httpx2
import msgspec

from ._config import Config
from ._credentials import TRACE_ID_HEADER, find_error_code
from ._errors import APIError, NetworkError, PartialFailureError
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
        response, secrets = await self._send(method, path, params, json)
        action = f"{method} {path}"
        trace_id = _check_response(response, action, secrets)
        if type_ is None:
            return None
        return _decode_response(response, type_, action, secrets, trace_id)

    async def request_decoded[T](
        self,
        method: str,
        path: str,
        *,
        type_: type[T],
        params: QueryParams | None = None,
        json: object = None,
    ) -> DecodedResponse[T]:
        """同 `request()`，另带上状态码与 trace_id，供接口方法从成功的响应里构造异常（如部分失败）。"""
        response, secrets = await self._send(method, path, params, json)
        action = f"{method} {path}"
        trace_id = _check_response(response, action, secrets)
        data = _decode_response(response, type_, action, secrets, trace_id)
        return DecodedResponse(data, response.status_code, trace_id, action, secrets)

    async def _send(
        self, method: str, path: str, params: QueryParams | None, json: object
    ) -> tuple[httpx2.Response, tuple[str | None, ...]]:
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
                auth=None,  # 注入的客户端若配了 auth，会覆盖上面的 QQBot 鉴权头
            )
        except httpx2.RequestError as exc:
            raise _network_error(f"{method} {path}", exc, secrets) from safe_cause(exc, *secrets)
        return response, secrets

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


@dataclass(frozen=True, slots=True)
class DecodedResponse[T]:
    """`HTTP.request_decoded()` 的结果：已判定为成功的响应。"""

    data: T
    status_code: int
    trace_id: str | None = field(repr=False)  # 未脱敏，构造异常时才脱敏
    action: str
    secrets: tuple[str | None, ...] = field(repr=False)

    def partial_failure(self, reason: str, failed_ids: tuple[str, ...]) -> PartialFailureError:
        """平台报告部分对象失败时抛出的异常，文案为 `{action} 部分失败：{reason}`。"""
        return PartialFailureError(
            f"{self.action} 部分失败：{redact(reason, *self.secrets)}",
            failed_ids=failed_ids,
            status_code=self.status_code,
            trace_id=redact_optional(self.trace_id, *self.secrets),
        )

    def failure(self, reason: str) -> APIError:
        """响应没有错误码、内容却表明失败时抛出的异常，文案同其它失败。"""
        return _api_error(self.action, self.status_code, self.trace_id, self.secrets, reason)


def _api_error(
    action: str,
    status_code: int,
    trace_id: str | None,
    secrets: tuple[str | None, ...],
    reason: str,
    err_code: int | None = None,
) -> APIError:
    return APIError(
        f"{action} 失败：{redact(reason, *secrets)}",
        status_code=status_code,
        err_code=err_code,
        trace_id=redact_optional(trace_id, *secrets),
    )


def _check_response(
    response: httpx2.Response, action: str, secrets: tuple[str | None, ...]
) -> str | None:
    """响应表示失败时抛 `APIError`；成功时返回 trace_id（未脱敏）。"""
    status_code = response.status_code
    trace_id = response.headers.get(TRACE_ID_HEADER)
    content = response.content

    if content.strip():
        try:
            body = decode(content, _ErrorBody)
        except msgspec.ValidationError:
            body = _ErrorBody()  # 合法的 JSON 但不是对象（如数组），不可能是失败结构
        except (msgspec.DecodeError, RecursionError) as exc:
            reason = f"无法解析响应（HTTP {status_code}）"
            raise _api_error(action, status_code, trace_id, secrets, reason) from safe_cause(
                exc, *secrets
            )
        trace_id = trace_id or body.trace_id
        # 201、202 也是 2xx，但文档说它们带失败结构，靠错误码识别。
        failed, err_code = find_error_code(body.err_code, body.code)
        if failed or not response.is_success:
            reason = body.message or f"HTTP {status_code}"
            raise _api_error(action, status_code, trace_id, secrets, reason, err_code)
    elif not response.is_success:
        raise _api_error(action, status_code, trace_id, secrets, f"HTTP {status_code}")
    return trace_id


def _decode_response[T](
    response: httpx2.Response,
    type_: type[T],
    action: str,
    secrets: tuple[str | None, ...],
    trace_id: str | None,
) -> T:
    try:
        return decode(response.content, type_)
    except (msgspec.DecodeError, RecursionError) as exc:
        reason = f"响应无法识别（HTTP {response.status_code}）"
        raise _api_error(action, response.status_code, trace_id, secrets, reason) from safe_cause(
            exc, *secrets
        )
