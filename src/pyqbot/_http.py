"""请求层：所有 OpenAPI 请求都经这里发出（`dev-prepare/api-call-guide.md`），失败映射见 `docs/design.md`。"""

from collections.abc import Awaitable, Callable, Mapping
from typing import overload
from urllib.parse import quote

import httpx2
import msgspec

from ._config import Config
from ._credentials import TRACE_ID_HEADER, find_error_code
from ._errors import APIError, NetworkError
from ._model import Model, decode
from ._redact import redact, safe_cause

type QueryParams = Mapping[str, str | int]


class HTTP:
    """带鉴权的请求，响应解码成模型，失败映射成 `APIError` / `NetworkError`。

    `get_token` 是 `Client.get_access_token`：客户端关闭后它抛 `RuntimeError`，请求也随之被拒。
    """

    def __init__(
        self,
        config: Config,
        http_client: httpx2.AsyncClient,
        get_token: Callable[[], Awaitable[str]],
    ) -> None:
        self._config = config
        self._http_client = http_client
        self._get_token = get_token

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
        secrets = (config.app_secret, token)
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
            reason = (
                "请求超时"
                if isinstance(exc, httpx2.TimeoutException)
                else redact(str(exc) or type(exc).__name__, *secrets)
            )
            raise NetworkError(f"{method} {path} 失败：{reason}") from safe_cause(exc, *secrets)

        return _parse_response(response, type_, f"{method} {path}", secrets)


def path_segment(value: str, name: str) -> str:
    """把路径参数转义成一段路径，防止 `/`、`..` 改变请求的接口。

    Raises:
        ValueError: `value` 为空，或是 `.`、`..`（转义不了，会被当成相对路径）。
    """
    if value in ("", ".", ".."):
        raise ValueError(f"{name} 不合法：{value!r}")
    return quote(value, safe="")


class _ErrorBody(Model):
    # 通用失败结构用 err_code；code 是获取 token 接口的写法，两个都认（docs/errata.md）。
    code: int | str | None = None
    err_code: int | str | None = None
    message: str | None = None
    trace_id: str | None = None


def _parse_response[T](
    response: httpx2.Response,
    type_: type[T] | None,
    action: str,
    secrets: tuple[str, ...],
) -> T | None:
    status_code = response.status_code
    trace_id = response.headers.get(TRACE_ID_HEADER)
    content = response.content

    def fail(reason: str, err_code: int | None = None) -> APIError:
        return APIError(
            f"{action} 失败：{redact(reason, *secrets)}",
            status_code=status_code,
            err_code=err_code,
            trace_id=trace_id,
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
        failed, err_code = find_error_code(body.code, body.err_code)
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
