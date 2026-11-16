"""网关连接：建连、Identify / Resume、心跳、断线重连。

断开后怎么办、心跳、退避等规则见 `docs/design.md`「网关连接」，这里只实现，不重复。
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Never, cast

import httpx2
from httpx2.websockets import (
    AsyncWebSocketSession,
    HTTPXWSException,
    WebSocketDisconnect,
    WebSocketInvalidTypeReceived,
)

from .._errors import GatewayError, NetworkError, PayloadError
from .._redact import redact, safe_cause
from .close_codes import CloseAction, classify_close_code
from .intents import Intents
from .payload import (
    READY_EVENT,
    RESUMED_EVENT,
    GatewayPayload,
    Hello,
    OpCode,
    Ready,
    decode_payload,
    encode_heartbeat,
    encode_identify,
    encode_resume,
)

logger = logging.getLogger("pyqbot")

_MAX_MESSAGE_BYTES = 1 << 20  # httpx2 默认 64 KiB，带附件的事件可能超过
_MAX_INVALID_SESSIONS = 3


class _DisconnectError(Exception):
    """结束当前连接：`action` 决定下一次连接怎么做，`code` 是关闭码（有的话）。"""

    def __init__(
        self,
        action: CloseAction,
        reason: str,
        *,
        code: int | None = None,
        invalid_session: bool = False,
    ) -> None:
        super().__init__(reason)
        self.action = action
        self.reason = reason
        self.code = code
        self.invalid_session = invalid_session


class _Heartbeat:
    """一条连接上的心跳：到下一次该发时上一次还没有应答，就判定连接已死。"""

    def __init__(self, interval: float, beat: Callable[[], Awaitable[None]]) -> None:
        self.interval = interval
        self.acked = True
        self._beat = beat

    async def run(self) -> Never:
        while True:
            if not self.acked:
                raise _DisconnectError(CloseAction.RESUME, "心跳没有应答")
            self.acked = False
            await self._beat()
            await asyncio.sleep(self.interval)


class GatewayConnection:
    """一条网关连接，供 `Bot.start()` 使用；参数与行为见 `docs/design.md`「网关连接」。时间单位都是秒。"""

    def __init__(
        self,
        *,
        http_client: httpx2.AsyncClient,
        get_url: Callable[[], Awaitable[str]],
        get_token: Callable[[], Awaitable[str]],
        intents: Intents,
        on_dispatch: Callable[[GatewayPayload], None],
        shard: tuple[int, int] = (0, 1),
        connect_timeout: float = 30.0,
        handshake_timeout: float = 30.0,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0,
        identify_interval: float = 5.0,
    ) -> None:
        self._http_client = http_client
        self._get_url = get_url
        self._get_token = get_token
        self._intents = intents
        self._on_dispatch = on_dispatch
        self._shard = shard
        self._connect_timeout = connect_timeout
        self._handshake_timeout = handshake_timeout
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._identify_interval = identify_interval

        self._session_id: str | None = None
        self._seq: int | None = None
        self._token: str | None = None  # 只用于脱敏
        self._last_identify: float | None = None
        self._delay = 0.0  # 不含抖动的退避间隔
        self._invalid_sessions = 0
        self._closed = False
        self._worker: asyncio.Task[Never] | None = None

    async def run(self) -> None:
        """一直运行到 `close()`（正常返回）或连接无法恢复；`close()` 之后调用立即返回。

        Raises:
            GatewayError: 连接无法恢复。
            QQBotError: `get_url` / `get_token` 抛出的 `NetworkError` 以外的异常，原样抛出。
            RuntimeError: 重复调用。
        """
        if self._closed:
            return
        if self._worker is not None:
            raise RuntimeError("GatewayConnection.run() 只能调用一次")
        # 真正的工作放进独立的任务：close() 只取消它，不碰调用 run() 的任务。
        self._worker = worker = asyncio.create_task(self._run_forever())
        try:
            await worker
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if self._closed and task is not None and not task.cancelling():
                return
            raise

    async def close(self) -> None:
        """断开连接并等 `run()` 收尾。可重复调用，`run()` 之前调用也安全。"""
        self._closed = True
        worker = self._worker
        if worker is not None and not worker.done():
            worker.cancel()
            await asyncio.wait([worker])

    async def _run_forever(self) -> Never:
        delay = 0.0
        while True:
            await asyncio.sleep(delay)
            outcome = await self._connect()
            self._settle(outcome)
            self._delay = (
                min(self._max_reconnect_delay, self._delay * 2)
                if self._delay
                else self._reconnect_delay
            )
            delay = max(self._delay * random.uniform(0.5, 1.0), self._identify_wait())
            logger.warning("网关连接断开：%s；%.3f 秒后重连", outcome.reason, delay)

    def _settle(self, outcome: _DisconnectError) -> None:
        """按断开原因更新会话状态；不可恢复时抛 `GatewayError`。"""
        if outcome.action is CloseAction.GIVE_UP:
            raise self._gateway_error(f"网关连接无法恢复：{outcome.reason}", outcome)
        if outcome.invalid_session:
            self._invalid_sessions += 1
            if self._invalid_sessions >= _MAX_INVALID_SESSIONS:
                message = f"连续 {self._invalid_sessions} 次会话无效（OpCode 9），放弃重连"
                raise self._gateway_error(message, outcome)
        if outcome.action is CloseAction.IDENTIFY:
            self._session_id = None
            self._seq = None

    def _identify_wait(self) -> float:
        if self._session_id is not None or self._last_identify is None:
            return 0.0
        elapsed = asyncio.get_running_loop().time() - self._last_identify
        return max(0.0, self._identify_interval - elapsed)

    async def _connect(self) -> _DisconnectError:
        """建一次连接并服务到它断开，返回断开原因。"""
        try:
            url = await self._get_url()
            self._token = token = await self._get_token()
        except NetworkError as exc:
            return self._outcome_of(exc)
        try:
            async with self._http_client.websocket(
                url,
                max_message_size_bytes=_MAX_MESSAGE_BYTES,
                # 存活由 OpCode 1 心跳判断；文档没说网关回不回 WebSocket Ping。
                keepalive_ping_interval_seconds=None,
                timeout=self._connect_timeout,
            ) as ws:
                return await self._serve(ws, token)
        except (httpx2.HTTPError, HTTPXWSException) as exc:
            return self._outcome_of(exc)

    async def _serve(self, ws: AsyncWebSocketSession, token: str) -> _DisconnectError:
        try:
            async with asyncio.TaskGroup() as tg:
                await self._read(ws, token, tg)
        except* _DisconnectError as group:
            # TaskGroup 的异常组不嵌套；读循环与心跳同时结束时取第一个。
            outcome = cast(_DisconnectError, group.exceptions[0])
        return outcome

    async def _read(self, ws: AsyncWebSocketSession, token: str, tg: asyncio.TaskGroup) -> Never:
        """读循环；认证成功后在 `tg` 里启动心跳，任何一方抛 `_DisconnectError` 都结束这条连接。"""
        try:
            async with asyncio.timeout(self._handshake_timeout):
                interval = await self._receive_hello(ws)
        except TimeoutError as exc:
            raise _DisconnectError(CloseAction.RESUME, "等待 Hello 超时") from exc

        async def beat() -> None:
            await self._send(ws, encode_heartbeat(self._seq))

        heartbeat = _Heartbeat(interval, beat)
        await self._send(ws, self._login(token))
        try:
            async with asyncio.timeout(self._handshake_timeout) as deadline:
                while True:
                    payload = await self._receive(ws)
                    if payload is None:
                        continue
                    match payload.op:
                        case OpCode.DISPATCH:
                            self._dispatch(payload)
                            if deadline.when() is not None:  # 本连接第一条 Dispatch：认证成功
                                deadline.reschedule(None)
                                tg.create_task(heartbeat.run())
                        case OpCode.HEARTBEAT_ACK:
                            heartbeat.acked = True
                        case OpCode.HEARTBEAT:
                            await beat()
                        case OpCode.RECONNECT:
                            raise _DisconnectError(CloseAction.RESUME, "网关要求重连（OpCode 7）")
                        case OpCode.INVALID_SESSION:
                            raise _DisconnectError(
                                CloseAction.IDENTIFY,
                                "会话无效（OpCode 9）",
                                invalid_session=True,
                            )
                        case _:
                            logger.warning("跳过意料之外的 OpCode %d", payload.op)
        except TimeoutError as exc:
            raise _DisconnectError(CloseAction.RESUME, "等待认证结果超时") from exc

    async def _receive_hello(self, ws: AsyncWebSocketSession) -> float:
        while True:
            payload = await self._receive(ws)
            if payload is None:
                continue
            if payload.op != OpCode.HELLO:
                logger.warning("Hello 之前收到 OpCode %d，跳过", payload.op)
                continue
            try:
                return payload.decode_data(Hello).heartbeat_interval_seconds
            except PayloadError as exc:
                logger.warning("跳过无法解码的 Hello：%s", self._redact(str(exc)))

    async def _receive(self, ws: AsyncWebSocketSession) -> GatewayPayload | None:
        """收一帧；连接断开时抛 `_DisconnectError`，坏帧记日志后返回 `None`。"""
        try:
            frame = await ws.receive_text()
        except WebSocketInvalidTypeReceived:
            logger.warning("跳过非文本帧")
            return None
        except HTTPXWSException as exc:
            raise self._outcome_of(exc) from exc
        try:
            return decode_payload(frame)
        except PayloadError as exc:
            logger.warning("跳过无法解码的帧：%s", self._redact(str(exc)))
            return None

    async def _send(self, ws: AsyncWebSocketSession, frame: str) -> None:
        try:
            await ws.send_text(frame)
        except Exception as exc:  # noqa: BLE001 —— 断开时 wsproto、anyio 的各种异常都可能出现
            # 断开原因由读循环收到，收不到时心跳没有应答也会兜底；wsproto 的文案含整帧，不记。
            logger.debug("发送失败（%s），等待读循环得知断开原因", type(exc).__name__)

    def _login(self, token: str) -> str:
        if self._session_id is None:
            self._last_identify = asyncio.get_running_loop().time()
            logger.info("发送 Identify")
            return encode_identify(token, self._intents, shard=self._shard)
        logger.info("发送 Resume（seq=%s）", self._seq)
        return encode_resume(token, self._session_id, self._seq or 0)

    def _dispatch(self, payload: GatewayPayload) -> None:
        if payload.t == READY_EVENT:
            self._session_id = self._session_of(payload)
        if payload.t in (READY_EVENT, RESUMED_EVENT):
            logger.info("网关连接已就绪（%s）", payload.t)
            self._delay = 0.0
            self._invalid_sessions = 0
        try:
            self._on_dispatch(payload)
        except Exception as exc:
            logger.error(
                "on_dispatch 处理 %s 时出错：%s",
                payload.t,
                self._redact(repr(exc)),
                exc_info=safe_cause(exc, self._token),
            )
        if payload.s is not None:
            self._seq = payload.s

    def _session_of(self, payload: GatewayPayload) -> str | None:
        try:
            return payload.decode_data(Ready).session_id
        except PayloadError as exc:
            logger.warning("READY 无法解码，断开后只能重新 Identify：%s", self._redact(str(exc)))
            return None

    def _outcome_of(self, exc: Exception) -> _DisconnectError:
        if isinstance(exc, WebSocketDisconnect):
            info = classify_close_code(exc.code)
            reason = f"关闭码 {exc.code}，{info.reason}"
            if exc.reason:
                reason += f"（{self._redact(exc.reason)}）"
            outcome = _DisconnectError(info.action, reason, code=exc.code)
        else:
            detail = self._redact(str(exc))
            reason = f"{type(exc).__name__}：{detail}" if detail else type(exc).__name__
            outcome = _DisconnectError(CloseAction.RESUME, reason)
        outcome.__cause__ = exc
        return outcome

    def _gateway_error(self, message: str, outcome: _DisconnectError) -> GatewayError:
        error = GatewayError(message, err_code=outcome.code)
        cause = outcome.__cause__
        error.__cause__ = None if cause is None else safe_cause(cause, self._token)
        return error

    def _redact(self, text: str) -> str:
        return redact(text, self._token)
