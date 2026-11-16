"""access_token 的获取、缓存与刷新，对应 `POST /app/getAppAccessToken`（`dev-prepare/access-token.md`）。

- 何时刷新：平台只在旧 token 剩余不足 60 秒时才签发新 token，更早去取拿回的仍是旧的。
  所以提前 `REFRESH_MARGIN` 秒刷新，留 10 秒吸收请求耗时与秒级取整；有效期很短时改为过半即刷新，
  避免每次调用都发请求。有效期从发请求之前起算，估出的时刻只会偏早。
- 刷新失败：旧 token 还没真正过期就继续返回它（新 token 签发后旧的仍有效 60 秒）。
- 没有做：后台定时刷新（按需刷新已够用）；主动作废缓存（有效期内重复获取返回同一个 token）；
  失败后的冷却与退避。
"""

import asyncio
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from time import monotonic
from time import time as wall_time

import httpx2
import msgspec

from ._config import Config
from ._errors import APIError, NetworkError, QQBotError
from ._model import Model, decode
from ._redact import redact, safe_cause

TOKEN_PATH = "/app/getAppAccessToken"
REFRESH_MARGIN = 50.0
TRACE_ID_HEADER = "X-Tps-trace-ID"


class AccessTokenManager:
    """一个机器人的 access_token：按需获取并缓存，同一时刻只有一个获取在途。"""

    def __init__(self, config: Config, http_client: httpx2.AsyncClient) -> None:
        self._config = config
        self._http_client = http_client
        self._token: _CachedToken | None = None
        self._refreshing: asyncio.Future[str] | None = None

    async def get(self) -> str:
        """返回当前有效的 access_token（不含 `QQBot ` 前缀），必要时向平台获取。

        Raises:
            APIError: 平台拒绝签发或响应无法识别。
            NetworkError: 没有拿到平台的响应。
        """
        while True:
            token = self._token
            if token is not None and token.is_fresh():
                return token.value
            refreshing = self._refreshing
            if refreshing is None:
                return await self._refresh()
            try:
                # shield：等待者自己被取消时，不能连带取消别人发起的那次获取。
                return await asyncio.shield(refreshing)
            except asyncio.CancelledError:
                # 被取消的是发起获取的调用而不是自己：轮到自己发起。
                current = asyncio.current_task()
                if refreshing.cancelled() and current is not None and not current.cancelling():
                    continue
                raise

    async def _refresh(self) -> str:
        future = asyncio.get_running_loop().create_future()
        self._refreshing = future
        try:
            token = await self._fetch()
        except Exception as exc:
            stale = self._token
            if isinstance(exc, QQBotError) and stale is not None and not stale.is_expired():
                future.set_result(stale.value)
                return stale.value
            future.set_exception(exc)
            # 没有等待者时无人取走异常，asyncio 会报 "exception was never retrieved"；本调用已经抛出它。
            future.exception()
            raise
        except BaseException:
            future.cancel()
            raise
        else:
            self._token = token
            future.set_result(token.value)
            return token.value
        finally:
            self._refreshing = None

    async def _fetch(self) -> _CachedToken:
        config = self._config
        sent_monotonic, sent_wall = monotonic(), wall_time()
        try:
            response = await self._http_client.post(
                config.base_url + TOKEN_PATH,
                json={"appId": config.app_id, "clientSecret": config.app_secret},
                timeout=config.timeout,
            )
        except httpx2.RequestError as exc:
            secrets = self._known_secrets()
            reason = (
                "请求超时"
                if isinstance(exc, httpx2.TimeoutException)
                else redact(str(exc) or type(exc).__name__, *secrets)
            )
            error = NetworkError(f"获取 access_token 失败：{reason}")
            raise error from safe_cause(exc, *secrets)

        value, expires_in = _parse_response(response, self._known_secrets())
        token = _CachedToken(
            value=value,
            sent_monotonic=sent_monotonic,
            sent_wall=sent_wall,
            refresh_after=max(expires_in - REFRESH_MARGIN, expires_in / 2),
            expires_in=expires_in,
        )
        if token.is_expired():  # 例如请求在途时机器睡眠了
            raise NetworkError("获取 access_token 失败：耗时超过了 token 的有效期")
        return token

    def _known_secrets(self) -> tuple[str | None, ...]:
        return (self._config.app_secret, self._token.value if self._token else None)


@dataclass(frozen=True, slots=True, kw_only=True)
class _CachedToken:
    value: str = field(repr=False)
    sent_monotonic: float
    sent_wall: float
    refresh_after: float
    expires_in: float

    def _elapsed(self) -> float:
        # 两个时钟取大者：单调时钟在机器睡眠时不走（macOS、Linux 都是），墙上时钟可能被往回调。
        return max(monotonic() - self.sent_monotonic, wall_time() - self.sent_wall)

    def is_fresh(self) -> bool:
        return self._elapsed() < self.refresh_after

    def is_expired(self) -> bool:
        return self._elapsed() >= self.expires_in


class _TokenResponse(Model):
    # 成功与失败共用一个结构，按是否带错误码区分。
    _secret_fields = frozenset({"access_token"})

    access_token: str | None = None
    expires_in: float | str | None = None  # 文档出入，见 docs/errata.md
    code: int | str | None = None
    err_code: int | str | None = None
    message: str | None = None
    trace_id: str | None = None


def _parse_response(response: httpx2.Response, secrets: Iterable[str | None]) -> tuple[str, float]:
    status_code = response.status_code
    trace_id = response.headers.get(TRACE_ID_HEADER)
    try:
        body = decode(response.content, _TokenResponse)
    except (msgspec.DecodeError, RecursionError) as exc:
        raise APIError(
            f"获取 access_token 失败：无法解析响应（HTTP {status_code}）",
            status_code=status_code,
            trace_id=trace_id,
        ) from exc

    trace_id = trace_id or body.trace_id
    # 文档要求优先依据 code 判断：业务失败时 HTTP 状态码仍是 200。认不出的错误码也算失败。
    codes = [code for code in (body.code, body.err_code) if code not in _SUCCESS_CODES]
    err_code = next((parsed for code in codes if (parsed := _as_int(code)) is not None), None)
    if codes or not response.is_success:
        reason = body.message or f"HTTP {status_code}"
        raise APIError(
            f"获取 access_token 失败：{redact(reason, *secrets, body.access_token)}",
            status_code=status_code,
            err_code=err_code,
            trace_id=trace_id,
        )

    expires_in = _parse_expires_in(body.expires_in)
    if not body.access_token or expires_in is None:
        raise APIError(
            "获取 access_token 失败：响应缺少有效的 access_token 或 expires_in",
            status_code=status_code,
            trace_id=trace_id,
        )
    return body.access_token, expires_in


_SUCCESS_CODES = (None, 0, "0", "")


def _as_int(value: int | str | None) -> int | None:
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return value


def _parse_expires_in(value: float | str | None) -> float | None:
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if value is None or not math.isfinite(value) or value <= 0:
        return None
    return value
