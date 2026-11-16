"""网关连接的状态机，对照 `docs/design.md`「网关连接」。

`FakeGateway` 用 `ASGIWebSocketTransport` 扮演网关：每次建连按顺序执行一段脚本，脚本驱动网关这一侧，
并记下客户端发来的帧。时间参数都设得很小；同步一律靠事件，`asyncio.timeout` 兜底。
"""

import asyncio
import contextlib
import itertools
import json
import logging
import math
import traceback
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator, MutableMapping
from contextlib import asynccontextmanager
from typing import Any, cast

import anyio  # 只用来构造传输层会抛的异常类型，SDK 自身不依赖它
import httpx2
import pytest
from httpx2.websockets import ASGIWebSocketTransport

import pyqbot
from pyqbot._gateway.connection import GatewayConnection
from pyqbot._gateway.payload import GatewayPayload

# ASGI 消息与 JSON 帧的结构随类型变化，标准里就没有更精确的类型。
type ASGIMessage = MutableMapping[str, Any]
type Receive = Callable[[], Awaitable[ASGIMessage]]
type Send = Callable[[ASGIMessage], Awaitable[None]]
type Frame = dict[str, Any]
type Script = Callable[[GatewaySide], Awaitable[None]]

GATEWAY_URL = "wss://gateway.test/websocket"
REFUSED_URL = "wss://refused.test/websocket"
SESSION_ID = "session-1"
QUIET = 60_000  # 毫秒：不想让心跳干扰的用例用这个周期
TIMEOUT = 5  # 秒：每个用例的兜底超时
INTENTS = pyqbot.Intents.GROUP_AND_C2C_EVENT
C2C = "C2C_MESSAGE_CREATE"


class ClientGoneError(Exception):
    """客户端断开了连接。"""


class GatewaySide:
    """网关这一侧的一条连接。"""

    def __init__(self, receive: Receive, send: Send) -> None:
        self._receive = receive
        self._send = send
        self._accepted = False
        self.frames: list[Frame] = []
        self.times: list[float] = []  # 每帧到达的时刻，与 frames 一一对应

    async def accept(self) -> None:
        if not self._accepted:
            self._accepted = True
            await self._send({"type": "websocket.accept"})

    async def send_text(self, text: str) -> None:
        await self.accept()
        await self._send({"type": "websocket.send", "text": text})

    async def send_bytes(self, data: bytes) -> None:
        await self.accept()
        await self._send({"type": "websocket.send", "bytes": data})

    async def send(
        self, op: int, d: object = None, *, s: int | None = None, t: str | None = None
    ) -> None:
        await self.send_text(json.dumps({"op": op, "d": d, "s": s, "t": t}))

    async def reject(self, status: int) -> None:
        """拒绝 WebSocket 握手，客户端收到 HTTP `status`。"""
        await self._send({"type": "websocket.http.response.start", "status": status, "headers": []})
        await self._send({"type": "websocket.http.response.body", "body": b"denied"})

    async def hello(self, interval_ms: int = QUIET) -> None:
        await self.send(10, {"heartbeat_interval": interval_ms})

    async def dispatch(self, t: str, d: object, s: int) -> None:
        await self.send(0, d, s=s, t=t)

    async def ready(self, s: int = 1) -> None:
        user = {"id": "1", "username": "bot", "bot": True, "status": 1}
        await self.dispatch("READY", {"version": 1, "session_id": SESSION_ID, "user": user}, s)

    async def close(self, code: int, reason: str = "") -> None:
        """发送关闭帧；还没 accept 时客户端在握手阶段就会收到它。"""
        await self._send({"type": "websocket.close", "code": code, "reason": reason})

    def drop(self) -> None:
        """不发关闭帧就断开，客户端读到的是网络错误。"""
        # 借用 ASGIWebSocketTransport 的内部结构：send 是下行队列的方法，关掉发送端客户端就读到流结束。
        cast(Any, self._send).__self__.send_stream.close()

    async def receive(self) -> Frame:
        message = await self._receive()
        if message["type"] == "websocket.disconnect":
            raise ClientGoneError
        frame: Frame = json.loads(message["text"])
        self.frames.append(frame)
        self.times.append(asyncio.get_running_loop().time())
        return frame

    async def expect(self, op: int) -> Frame:
        """等下一条 `op` 帧；途中的心跳跳过，其它帧都算错误。"""
        while True:
            frame = await self.receive()
            if frame["op"] == op:
                return frame
            assert frame["op"] == 1, f"期望 OpCode {op}，收到 {frame}"

    async def login(self) -> Frame:
        """等 Identify 或 Resume。"""
        frame = await self.receive()
        assert frame["op"] in (2, 6), frame
        return frame

    async def serve(self, *, ack: bool = True) -> None:
        """一直收帧（按需应答心跳），直到客户端断开。"""
        while True:
            frame = await self.receive()
            if ack and frame["op"] == 1:
                await self.send(11)

    def logins(self) -> list[Frame]:
        return [frame for frame in self.frames if frame["op"] in (2, 6)]

    def heartbeats(self) -> list[Frame]:
        return [frame for frame in self.frames if frame["op"] == 1]


class FakeGateway:
    """按顺序为每次建连执行一段脚本。脚本里的断言失败会记下来，由 `open_client` 退出时抛出。"""

    def __init__(self, *scripts: Script) -> None:
        self._scripts = scripts
        self.sides: list[GatewaySide] = []
        self.errors: list[Exception] = []
        self.done = asyncio.Event()

    def finish(self) -> None:
        self.done.set()

    async def __call__(self, scope: ASGIMessage, receive: Receive, send: Send) -> None:
        await receive()  # websocket.connect
        side = GatewaySide(receive, send)
        self.sides.append(side)
        index = len(self.sides) - 1
        try:
            if index >= len(self._scripts):
                raise AssertionError(f"意外的第 {index + 1} 次连接")
            await self._scripts[index](side)
        except ClientGoneError:
            pass
        except Exception as exc:  # noqa: BLE001 —— 记下来交给测试本身抛出
            self.errors.append(exc)
            self.finish()


class Injected:
    """注入给 `GatewayConnection` 的依赖，记录它们被怎样调用。"""

    def __init__(self, gateway: FakeGateway, *, finish_on: str | None = None) -> None:
        self._gateway = gateway
        self._finish_on = finish_on
        self.urls: list[str | Exception] = []  # 依次返回或抛出，用完后返回 GATEWAY_URL
        self.token_errors: list[Exception] = []  # 依次抛出，用完后签发新 token
        self.url_calls = 0
        self.tokens: list[str] = []
        self.dispatched: list[GatewayPayload] = []
        self.fail_on: set[int] = set()  # 这些 s 的事件让 on_dispatch 抛异常
        self.peek_seq: Callable[[], object] = lambda: None
        self.seq_during_dispatch: list[object] = []  # 每次回调执行时连接记着的 seq

    async def get_url(self) -> str:
        self.url_calls += 1
        if self.urls:
            item = self.urls.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return GATEWAY_URL

    async def get_token(self) -> str:
        if self.token_errors:
            raise self.token_errors.pop(0)
        token = f"t0ken-{len(self.tokens) + 1}-s3cr3t"
        self.tokens.append(token)
        return token

    def on_dispatch(self, payload: GatewayPayload) -> None:
        self.dispatched.append(payload)
        self.seq_during_dispatch.append(self.peek_seq())
        if payload.s in self.fail_on:
            raise RuntimeError(f"处理失败，当时的 token 是 {self.tokens[-1]}")
        if payload.t == self._finish_on:
            self._gateway.finish()

    def events(self) -> list[str | None]:
        return [payload.t for payload in self.dispatched]


class RefusingTransport(httpx2.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("连接被拒绝", request=request)


class BuggyTransport(httpx2.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        raise RuntimeError("传输层自身的 bug")


class OSErrorTransport(httpx2.AsyncBaseTransport):
    """直接漏出 OSError，没有被 httpx2 包装。"""

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        raise ConnectionResetError("连接被重置")


_TEXT_FRAME = 0x1
_CLOSE_FRAME = 0x8


class StreamFault:
    """注入到某一条连接底层流上的故障：卡住写入、读或关闭流时出错。"""

    def __init__(
        self,
        *,
        block_text_from: int | None = None,
        block_close: bool = False,
        read_error: Exception | None = None,
        aclose_error: Exception | None = None,
    ) -> None:
        self.block_text_from = block_text_from  # 从客户端发的第几个文本帧（从 1 数）起卡住
        self.block_close = block_close  # 卡住客户端的关闭帧
        self.read_error = read_error  # fail_reads 置位之后，下一次读抛出它
        self.fail_reads = asyncio.Event()
        self.aclose_error = aclose_error
        self.blocked = asyncio.Event()  # 有一次写入被卡住了
        self.release = asyncio.Event()  # 放行被卡住的写入
        self.aclosed = False
        self._texts = 0

    def blocks(self, frame: bytes) -> bool:
        opcode = frame[0] & 0x0F  # WebSocket 帧头第一个字节的低 4 位
        if opcode == _TEXT_FRAME:
            self._texts += 1
            return self.block_text_from is not None and self._texts >= self.block_text_from
        return opcode == _CLOSE_FRAME and self.block_close


class FaultyStream:
    """包在 httpx2 网络流外面，按 `StreamFault` 注入故障，其余原样转发。"""

    def __init__(self, inner: Any, fault: StreamFault) -> None:
        self._inner = inner
        self._fault = fault

    # 签名要与 httpx2 的网络流一致，所以保留 timeout 参数。
    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:  # noqa: ASYNC109
        if self._fault.read_error is not None and self._fault.fail_reads.is_set():
            raise self._fault.read_error
        return await self._inner.read(max_bytes, timeout)

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:  # noqa: ASYNC109
        if self._fault.blocks(buffer):
            self._fault.blocked.set()
            await self._fault.release.wait()
        await self._inner.write(buffer, timeout)

    async def aclose(self) -> None:
        self._fault.aclosed = True
        await self._inner.aclose()
        if self._fault.aclose_error is not None:
            raise self._fault.aclose_error


class FaultyTransport(ASGIWebSocketTransport):
    """给第 n 次建连（从 0 数）的网络流注入故障。"""

    def __init__(self, app: FakeGateway, faults: dict[int, StreamFault]) -> None:
        super().__init__(app)
        self._faults = faults
        self._connections = 0

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        response = await super().handle_async_request(request)
        fault = self._faults.get(self._connections)
        self._connections += 1
        if fault is not None:
            # httpx2 的会话从响应扩展里的 network_stream 读写，这是唯一能插进去的地方。
            stream = response.extensions["network_stream"]
            response.extensions["network_stream"] = FaultyStream(stream, fault)
        return response


@asynccontextmanager
async def open_client(
    gateway: FakeGateway, faults: dict[int, StreamFault] | None = None
) -> AsyncGenerator[httpx2.AsyncClient]:
    """打开挂着假网关的客户端；必须在测试函数体内使用，见 `docs/design.md`「测试约定」。"""
    mounts: dict[str, httpx2.AsyncBaseTransport] = {
        "wss://gateway.test": FaultyTransport(gateway, faults or {}),
        "wss://refused.test": RefusingTransport(),
        "wss://buggy.test": BuggyTransport(),
        "wss://oserror.test": OSErrorTransport(),
    }
    async with httpx2.AsyncClient(mounts=mounts) as client:
        yield client
    if gateway.errors:
        raise gateway.errors[0]


def make_connection(
    client: httpx2.AsyncClient,
    injected: Injected,
    *,
    get_token: Callable[[], Awaitable[str]] | None = None,
    handshake_timeout: float = 10.0,
    send_timeout: float = 10.0,
    close_timeout: float = 10.0,
    reconnect_delay: float = 0.0,
    max_reconnect_delay: float = 0.0,
    identify_interval: float = 0.0,
) -> GatewayConnection:
    connection = GatewayConnection(
        http_client=client,
        get_url=injected.get_url,
        get_token=get_token or injected.get_token,
        intents=INTENTS,
        on_dispatch=injected.on_dispatch,
        handshake_timeout=handshake_timeout,
        send_timeout=send_timeout,
        close_timeout=close_timeout,
        reconnect_delay=reconnect_delay,
        max_reconnect_delay=max_reconnect_delay,
        identify_interval=identify_interval,
    )
    # 只为断言回调执行期间 seq 还没推进；对外没有读 seq 的接口，也不该为测试加。
    injected.peek_seq = lambda: vars(connection)["_seq"]
    return connection


async def run_until_done(connection: GatewayConnection, gateway: FakeGateway) -> None:
    async with asyncio.TaskGroup() as tg:
        tg.create_task(connection.run())
        await gateway.done.wait()
        await connection.close()


async def start_session(side: GatewaySide, *, s: int = 1, interval_ms: int = QUIET) -> Frame:
    await side.hello(interval_ms)
    identify = await side.expect(2)
    await side.ready(s)
    return identify


async def resume_session(side: GatewaySide, *, s: int) -> Frame:
    await side.hello()
    resume = await side.expect(6)
    await side.dispatch("RESUMED", "", s)
    return resume


class LogWaiter(logging.Handler):
    """记录里出现某段文字时置位事件，用来等状态机走到某一步。"""

    def __init__(self, fragment: str) -> None:
        super().__init__()
        self._fragment = fragment
        self.seen = asyncio.Event()

    def emit(self, record: logging.LogRecord) -> None:
        if self._fragment in record.getMessage():
            self.seen.set()


@pytest.fixture
def reconnect_logged() -> Iterator[LogWaiter]:
    waiter = LogWaiter("秒后重连")
    logger = logging.getLogger("pyqbot")
    logger.addHandler(waiter)
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    yield waiter
    logger.setLevel(previous)
    logger.removeHandler(waiter)


def reconnect_delays(caplog: pytest.LogCaptureFixture) -> list[float]:
    records = [record for record in caplog.records if "秒后重连" in record.msg]
    return [cast(float, cast(tuple[object, ...], record.args)[-1]) for record in records]


# 会话：首次 Identify，断开后 Resume


async def test_identifies_first_then_resumes_with_latest_seq_and_fresh_token() -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side, s=1)
        await side.dispatch(C2C, {"id": "m1"}, 2)
        await side.dispatch(C2C, {"id": "m2"}, 3)
        await side.close(4009)

    async def second(side: GatewaySide) -> None:
        await resume_session(side, s=4)
        await side.serve()

    gateway = FakeGateway(first, second)
    injected = Injected(gateway, finish_on="RESUMED")
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, injected), gateway)

    identify, resume = gateway.sides[0].logins()[0], gateway.sides[1].logins()[0]
    assert identify == {
        "op": 2,
        "d": {
            "token": f"QQBot {injected.tokens[0]}",
            "intents": int(INTENTS),
            "shard": [0, 1],
            "properties": identify["d"]["properties"],
        },
    }
    assert resume == {
        "op": 6,
        "d": {"token": f"QQBot {injected.tokens[1]}", "session_id": SESSION_ID, "seq": 3},
    }
    assert injected.events() == ["READY", C2C, C2C, "RESUMED"]
    assert injected.url_calls == 2
    assert len(injected.tokens) == 2


# 断开后怎么办：收到关闭码


@pytest.mark.parametrize(
    ("code", "login_op"),
    [(4009, 6), (4008, 6), (1000, 6), (4006, 2), (4007, 2), (4900, 2), (4999, 2)],
)
async def test_close_code_decides_between_resume_and_identify(code: int, login_op: int) -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side)
        await side.close(code)

    async def second(side: GatewaySide) -> None:
        await side.hello()
        await side.login()
        gateway.finish()
        await side.serve()

    gateway = FakeGateway(first, second)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, Injected(gateway)), gateway)

    assert gateway.sides[1].logins()[0]["op"] == login_op


@pytest.mark.parametrize("code", [4001, 4002, 4010, 4013, 4014, 4914, 4915])
async def test_close_code_that_cannot_recover_raises_gateway_error(code: int) -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side)
        await side.close(code, "bye")

    gateway = FakeGateway(first)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        connection = make_connection(client, Injected(gateway))
        with pytest.raises(pyqbot.GatewayError) as caught:
            await connection.run()

    assert caught.value.err_code == code
    assert f"关闭码 {code}" in caught.value.message
    assert len(gateway.sides) == 1


async def test_close_code_during_websocket_handshake_is_handled_the_same_way() -> None:
    async def rejected(side: GatewaySide) -> None:
        await side.close(4914)  # 还没 accept

    gateway = FakeGateway(rejected)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        with pytest.raises(pyqbot.GatewayError) as caught:
            await make_connection(client, Injected(gateway)).run()

    assert caught.value.err_code == 4914


# 断开后怎么办：网络错误、没有关闭帧、心跳没有应答、OpCode 7


async def drop_without_close_frame(side: GatewaySide) -> None:
    side.drop()
    await side.serve()


async def ask_to_reconnect(side: GatewaySide) -> None:
    await side.send(7)
    await side.serve()


async def leave_heartbeat_unanswered(side: GatewaySide) -> None:
    await side.expect(1)
    await side.serve(ack=False)


@pytest.mark.parametrize(
    ("interval_ms", "breaker"),
    [
        (QUIET, drop_without_close_frame),
        (QUIET, ask_to_reconnect),
        (10, leave_heartbeat_unanswered),
    ],
)
async def test_lost_connection_reconnects_and_resumes(interval_ms: int, breaker: Script) -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side, s=7, interval_ms=interval_ms)
        await breaker(side)

    async def second(side: GatewaySide) -> None:
        await resume_session(side, s=8)
        await side.serve()

    gateway = FakeGateway(first, second)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        connection = make_connection(client, Injected(gateway, finish_on="RESUMED"))
        await run_until_done(connection, gateway)

    assert gateway.sides[1].logins()[0]["d"]["seq"] == 7


@pytest.mark.parametrize("failure", ["refused", "upgrade_rejected"])
async def test_failed_connection_attempt_is_retried(failure: str) -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side, s=3)
        await side.close(4009)

    async def rejected(side: GatewaySide) -> None:
        await side.reject(403)

    async def last(side: GatewaySide) -> None:
        await resume_session(side, s=4)
        await side.serve()

    scripts = (first, last) if failure == "refused" else (first, rejected, last)
    gateway = FakeGateway(*scripts)
    injected = Injected(gateway, finish_on="RESUMED")
    if failure == "refused":
        injected.urls = [GATEWAY_URL, REFUSED_URL]
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, injected), gateway)

    assert injected.url_calls == 3
    assert gateway.sides[-1].logins()[0]["d"]["seq"] == 3


# 断开后怎么办：OpCode 9


async def test_invalid_session_clears_the_session_and_identifies_again() -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side, s=5)
        await side.send(9, False)
        await side.serve()

    async def second(side: GatewaySide) -> None:
        await side.hello()
        await side.login()
        gateway.finish()
        await side.serve()

    gateway = FakeGateway(first, second)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, Injected(gateway)), gateway)

    assert gateway.sides[1].logins()[0]["op"] == 2


async def invalid_session(side: GatewaySide) -> None:
    await side.hello()
    await side.login()
    await side.send(9, False)
    await side.serve()


async def test_three_invalid_sessions_in_a_row_give_up() -> None:
    gateway = FakeGateway(invalid_session, invalid_session, invalid_session)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        with pytest.raises(pyqbot.GatewayError) as caught:
            await make_connection(client, Injected(gateway)).run()

    assert caught.value.err_code is None
    assert "OpCode 9" in caught.value.message
    assert len(gateway.sides) == 3


async def test_invalid_session_count_resets_after_a_successful_login() -> None:
    async def recovered(side: GatewaySide) -> None:
        await start_session(side)
        await side.close(4009)

    async def last(side: GatewaySide) -> None:
        await start_session(side)
        gateway.finish()
        await side.serve()

    gateway = FakeGateway(
        invalid_session, invalid_session, recovered, invalid_session, invalid_session, last
    )
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, Injected(gateway)), gateway)

    assert len(gateway.sides) == 6


# 断开后怎么办：Hello、READY、RESUMED 超时


async def test_hello_timeout_is_handled_as_a_network_error() -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side, s=2)
        await side.close(4009)

    async def silent(side: GatewaySide) -> None:
        await side.accept()
        await side.serve(ack=False)

    async def last(side: GatewaySide) -> None:
        await side.hello()
        await side.login()
        gateway.finish()
        await side.serve()

    gateway = FakeGateway(first, silent, last)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        connection = make_connection(client, Injected(gateway), handshake_timeout=0.1)
        await run_until_done(connection, gateway)

    assert gateway.sides[2].logins()[0]["op"] == 6


async def test_ready_timeout_is_handled_as_a_network_error() -> None:
    async def no_ready(side: GatewaySide) -> None:
        await side.hello()
        await side.expect(2)
        await side.serve(ack=False)

    async def last(side: GatewaySide) -> None:
        await side.hello()
        await side.login()
        gateway.finish()
        await side.serve()

    gateway = FakeGateway(no_ready, last)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        connection = make_connection(client, Injected(gateway), handshake_timeout=0.1)
        await run_until_done(connection, gateway)

    assert gateway.sides[1].logins()[0]["op"] == 2  # 没有会话可恢复


async def test_resumed_timeout_is_handled_as_a_network_error() -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side, s=4)
        await side.close(4009)

    async def no_resumed(side: GatewaySide) -> None:
        await side.hello()
        await side.expect(6)
        await side.serve(ack=False)

    async def last(side: GatewaySide) -> None:
        await side.hello()
        await side.login()
        gateway.finish()
        await side.serve()

    gateway = FakeGateway(first, no_resumed, last)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        connection = make_connection(client, Injected(gateway), handshake_timeout=0.1)
        await run_until_done(connection, gateway)

    resume = gateway.sides[2].logins()[0]
    assert (resume["op"], resume["d"]["seq"]) == (6, 4)


# 心跳


async def test_heartbeat_is_sent_every_interval_with_current_seq() -> None:
    interval = 0.05

    async def script(side: GatewaySide) -> None:
        await start_session(side, s=1, interval_ms=int(interval * 1000))
        await side.expect(1)
        await side.send(11)
        await side.dispatch(C2C, {"id": "m1"}, 5)
        for _ in range(2):
            await side.expect(1)
            await side.send(11)
        gateway.finish()
        await side.serve()

    gateway = FakeGateway(script)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, Injected(gateway)), gateway)

    side = gateway.sides[0]
    beats = [
        (time, frame)
        for time, frame in zip(side.times, side.frames, strict=True)
        if frame["op"] == 1
    ]
    assert [frame["d"] for _, frame in beats[:3]] == [1, 5, 5]
    gaps = [later[0] - earlier[0] for earlier, later in itertools.pairwise(beats[:3])]
    assert all(gap >= interval * 0.5 for gap in gaps), gaps


async def test_server_heartbeat_request_is_answered_at_once() -> None:
    async def script(side: GatewaySide) -> None:
        await start_session(side, s=3)
        await side.expect(1)  # 认证成功后的第一次心跳
        await side.send(11)
        await side.send(1)
        await side.expect(1)  # 周期是 60 秒，这一次只能是应答
        gateway.finish()
        await side.serve()

    gateway = FakeGateway(script)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, Injected(gateway)), gateway)

    assert [frame["d"] for frame in gateway.sides[0].heartbeats()] == [3, 3]


# 退避


async def test_backoff_doubles_up_to_the_limit_and_resets_after_login(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="pyqbot")

    async def refuse(side: GatewaySide) -> None:
        await side.close(4009)

    async def resumed_then_closed(side: GatewaySide) -> None:
        await resume_session(side, s=2)
        await side.close(4009)

    async def last(side: GatewaySide) -> None:
        await resume_session(side, s=3)
        gateway.finish()
        await side.serve()

    async def first(side: GatewaySide) -> None:
        await start_session(side)
        await side.close(4009)

    gateway = FakeGateway(first, refuse, refuse, refuse, resumed_then_closed, last)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        connection = make_connection(
            client, Injected(gateway), reconnect_delay=0.01, max_reconnect_delay=0.03
        )
        await run_until_done(connection, gateway)

    # 每次加 [0.5, 1] 倍的随机抖动。
    expected = [0.01, 0.02, 0.03, 0.03, 0.01]
    delays = reconnect_delays(caplog)
    assert len(delays) == len(expected)
    for delay, base in zip(delays, expected, strict=True):
        assert base * 0.5 <= delay <= base, delays


async def test_identify_waits_for_the_minimum_interval() -> None:
    interval = 0.1

    async def first(side: GatewaySide) -> None:
        await side.hello()
        await side.expect(2)
        await side.send(9, False)
        await side.serve()

    async def second(side: GatewaySide) -> None:
        await side.hello()
        await side.expect(2)
        gateway.finish()
        await side.serve()

    gateway = FakeGateway(first, second)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        connection = make_connection(client, Injected(gateway), identify_interval=interval)
        await run_until_done(connection, gateway)

    first_at, second_at = gateway.sides[0].times[0], gateway.sides[1].times[0]
    # 记录的是到达时刻，比发送时刻略晚，留一点余量。
    assert second_at - first_at >= interval * 0.8


# 坏帧、未知 OpCode、on_dispatch 出错


async def test_bad_frames_and_unknown_opcodes_are_skipped(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="pyqbot")

    async def first(side: GatewaySide) -> None:
        await side.send(11)  # Hello 之前的其它帧
        await side.send_text("not json")
        await side.send(10, {"heartbeat_interval": "soon"})
        await side.hello()
        await side.expect(2)
        await side.send_text('{"d": {}}')  # 缺 op
        await side.send_bytes(b'{"op": 11}')  # 二进制帧
        await side.send(99, {"x": 1})  # 未知 OpCode
        await side.send(13)  # 只用于 Webhook
        await side.ready(1)
        await side.dispatch(C2C, {"id": "m1"}, 2)
        await side.send(0, {}, t="NO_SEQ")  # 没有 s 的 Dispatch 不改 seq
        await side.close(4009)

    async def second(side: GatewaySide) -> None:
        await resume_session(side, s=3)
        await side.serve()

    gateway = FakeGateway(first, second)
    injected = Injected(gateway, finish_on="RESUMED")
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, injected), gateway)

    assert injected.events() == ["READY", C2C, "NO_SEQ", "RESUMED"]
    assert gateway.sides[1].logins()[0]["d"]["seq"] == 2
    skipped = [record.getMessage() for record in caplog.records if "跳过" in record.msg]
    assert len(skipped) == 7, skipped


async def test_on_dispatch_error_does_not_break_the_connection() -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side)
        await side.dispatch(C2C, {"id": "m1"}, 2)
        await side.dispatch(C2C, {"id": "m2"}, 3)
        await side.close(4009)

    async def second(side: GatewaySide) -> None:
        await resume_session(side, s=4)
        await side.serve()

    gateway = FakeGateway(first, second)
    injected = Injected(gateway, finish_on="RESUMED")
    injected.fail_on = {2}
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, injected), gateway)

    assert injected.events() == ["READY", C2C, C2C, "RESUMED"]
    assert gateway.sides[1].logins()[0]["d"]["seq"] == 3


async def test_seq_counts_an_event_once_handed_to_on_dispatch_even_if_it_fails() -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side, s=1)
        await side.dispatch(C2C, {"id": "m1"}, 2)  # 断开前的最后一条，回调会抛异常
        await side.close(4009)

    async def second(side: GatewaySide) -> None:
        await resume_session(side, s=3)
        await side.serve()

    gateway = FakeGateway(first, second)
    injected = Injected(gateway, finish_on="RESUMED")
    injected.fail_on = {2}
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, injected), gateway)

    assert gateway.sides[1].logins()[0]["d"]["seq"] == 2
    # 回调执行时 seq 还是上一条的：交给回调之后才记。
    assert injected.seq_during_dispatch == [None, 1, 2]


async def test_undecodable_ready_leaves_no_session_to_resume() -> None:
    async def first(side: GatewaySide) -> None:
        await side.hello()
        await side.expect(2)
        await side.dispatch("READY", {"version": 1}, 1)  # 没有 session_id
        await side.close(4009)

    async def second(side: GatewaySide) -> None:
        await side.hello()
        await side.login()
        gateway.finish()
        await side.serve()

    gateway = FakeGateway(first, second)
    injected = Injected(gateway)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, injected), gateway)

    assert injected.events() == ["READY"]
    assert gateway.sides[1].logins()[0]["op"] == 2


async def test_large_event_fits_in_one_frame() -> None:
    async def script(side: GatewaySide) -> None:
        await start_session(side)
        await side.dispatch(C2C, {"content": "x" * 200_000}, 2)  # 超过 httpx2 默认的 64 KiB
        await side.serve()

    gateway = FakeGateway(script)
    injected = Injected(gateway, finish_on=C2C)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, injected), gateway)

    assert len(gateway.sides) == 1
    assert injected.events() == ["READY", C2C]


# get_url / get_token


async def test_url_and_token_are_fetched_again_and_network_errors_are_retried() -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side)
        await side.close(4009)

    async def second(side: GatewaySide) -> None:
        await resume_session(side, s=2)
        await side.serve()

    gateway = FakeGateway(first, second)
    injected = Injected(gateway, finish_on="RESUMED")
    injected.urls = [pyqbot.NetworkError("取网关地址超时")]
    injected.token_errors = [pyqbot.NetworkError("取 token 超时")]
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, injected), gateway)

    assert injected.url_calls == 4
    assert [side.logins()[0]["d"]["token"] for side in gateway.sides] == [
        f"QQBot {token}" for token in injected.tokens
    ]


@pytest.mark.parametrize("failing", ["url", "token"])
async def test_api_error_from_url_or_token_is_raised(failing: str) -> None:
    gateway = FakeGateway()
    injected = Injected(gateway)
    error = pyqbot.APIError("invalid appid or secret", status_code=200, err_code=100016)
    if failing == "url":
        injected.urls = [error]
    else:
        injected.token_errors = [error]
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await make_connection(client, injected).run()

    assert caught.value is error
    assert gateway.sides == []


# close() 与取消


async def test_close_before_run_makes_run_return_at_once() -> None:
    gateway = FakeGateway()
    injected = Injected(gateway)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        connection = make_connection(client, injected)
        await connection.close()
        await connection.close()
        await connection.run()

    assert injected.url_calls == 0


async def test_close_stops_run_and_leaves_no_task_behind() -> None:
    async def script(side: GatewaySide) -> None:
        await start_session(side)
        await side.serve()

    gateway = FakeGateway(script)
    injected = Injected(gateway, finish_on="READY")
    async with asyncio.timeout(TIMEOUT):
        async with open_client(gateway) as client:
            connection = make_connection(client, injected)
            await run_until_done(connection, gateway)
            await connection.close()  # 可重复调用

        assert asyncio.all_tasks() == {asyncio.current_task()}


async def test_close_interrupts_the_backoff_wait(reconnect_logged: LogWaiter) -> None:
    async def script(side: GatewaySide) -> None:
        await start_session(side)
        await side.close(4009)

    gateway = FakeGateway(script)
    async with asyncio.timeout(TIMEOUT):
        async with open_client(gateway) as client:
            connection = make_connection(
                client, Injected(gateway), reconnect_delay=3600, max_reconnect_delay=3600
            )
            async with asyncio.TaskGroup() as tg:
                tg.create_task(connection.run())
                await reconnect_logged.seen.wait()
                await connection.close()

        assert asyncio.all_tasks() == {asyncio.current_task()}


async def test_cancelling_run_propagates_and_leaves_no_task_behind() -> None:
    async def script(side: GatewaySide) -> None:
        await start_session(side)
        await side.serve()

    gateway = FakeGateway(script)
    async with asyncio.timeout(TIMEOUT):
        async with open_client(gateway) as client:
            connection = make_connection(client, Injected(gateway, finish_on="READY"))
            runner = asyncio.create_task(connection.run())
            await gateway.done.wait()
            runner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await runner

        assert asyncio.all_tasks() == {asyncio.current_task()}


async def test_run_can_only_be_called_once() -> None:
    async def script(side: GatewaySide) -> None:
        await start_session(side)
        await side.serve()

    gateway = FakeGateway(script)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        connection = make_connection(client, Injected(gateway, finish_on="READY"))
        async with asyncio.TaskGroup() as tg:
            tg.create_task(connection.run())
            await gateway.done.wait()
            with pytest.raises(RuntimeError, match="只能调用一次"):
                await connection.run()
            await connection.close()


# 凭证不落日志


async def test_tokens_never_reach_logs_or_errors(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="pyqbot")

    async def first(side: GatewaySide) -> None:
        await start_session(side)
        # 事件名和 on_dispatch 抛出的异常文案里都带 token。
        await side.dispatch(f"EVENT_{injected.tokens[0]}", {"id": "m1"}, 2)
        await side.close(4009, f"token {injected.tokens[0]} expired")

    async def second(side: GatewaySide) -> None:
        await side.hello()
        await side.login()
        # token 已经换过，平台回显的却是换之前的。
        await side.close(4914, f"QQBot {injected.tokens[0]} banned, now {injected.tokens[1]}")

    gateway = FakeGateway(first, second)
    injected = Injected(gateway)
    injected.fail_on = {2}
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        with pytest.raises(pyqbot.GatewayError) as caught:
            await make_connection(client, injected).run()

    assert len(injected.tokens) == 2
    shown = "".join(traceback.format_exception(caught.value))
    for token in injected.tokens:
        assert token not in caplog.text
        assert token not in shown
    assert caught.value.__cause__ is None  # 异常链里有 token，整条丢掉
    assert "EVENT_***" in caplog.text
    assert "***" in str(caught.value)


# 关闭的收尾：并发、再次取消、期限


async def serve_after_login(side: GatewaySide) -> None:
    await start_session(side)
    await side.serve()


async def test_concurrent_close_waits_for_the_same_cleanup() -> None:
    gateway = FakeGateway(serve_after_login)
    fault = StreamFault(block_close=True)
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: fault}) as client:
        connection = make_connection(client, Injected(gateway, finish_on="READY"))
        runner = asyncio.create_task(connection.run())
        await gateway.done.wait()
        first = asyncio.create_task(connection.close())
        await fault.blocked.wait()  # 第一次 close() 已经在写关闭帧
        second = asyncio.create_task(connection.close())
        # call_soon 按先后执行：second 先跑到它的等待点，然后才放行写入。
        asyncio.get_running_loop().call_soon(fault.release.set)
        await first
        await second
        await runner

    assert fault.aclosed  # 没被第二次 close() 打断


async def test_cancelling_run_again_does_not_interrupt_the_cleanup() -> None:
    gateway = FakeGateway(serve_after_login)
    fault = StreamFault(block_close=True)
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: fault}) as client:
        connection = make_connection(client, Injected(gateway, finish_on="READY"))
        runner = asyncio.create_task(connection.run())
        await gateway.done.wait()
        runner.cancel()
        await fault.blocked.wait()
        runner.cancel()
        asyncio.get_running_loop().call_soon(fault.release.set)
        with pytest.raises(asyncio.CancelledError):
            await runner

    assert fault.aclosed


async def test_close_gives_up_waiting_after_close_timeout() -> None:
    gateway = FakeGateway(serve_after_login)
    fault = StreamFault(block_close=True)  # 关闭帧永远写不出去
    async with asyncio.timeout(TIMEOUT):
        async with open_client(gateway, {0: fault}) as client:
            connection = make_connection(
                client, Injected(gateway, finish_on="READY"), close_timeout=0.05
            )
            runner = asyncio.create_task(connection.run())
            await gateway.done.wait()
            await connection.close()
            assert await runner is None

        assert asyncio.all_tasks() == {asyncio.current_task()}

    assert not fault.aclosed  # 强制结束：底层流没能优雅关闭


# 发送超时


async def test_blocked_heartbeat_write_counts_as_missing_ack() -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side, s=4, interval_ms=20)
        await side.serve(ack=False)

    async def second(side: GatewaySide) -> None:
        await resume_session(side, s=5)
        await side.serve()

    gateway = FakeGateway(first, second)
    fault = StreamFault(block_text_from=2)  # 第 1 帧是 Identify，第 2 帧起是心跳
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: fault}) as client:
        connection = make_connection(client, Injected(gateway, finish_on="RESUMED"))
        await run_until_done(connection, gateway)

    assert fault.blocked.is_set()
    assert gateway.sides[1].logins()[0]["d"]["seq"] == 4


async def test_blocked_login_write_times_out_and_reconnects() -> None:
    async def first(side: GatewaySide) -> None:
        await side.hello()
        await side.serve(ack=False)  # Identify 永远到不了

    async def second(side: GatewaySide) -> None:
        await side.hello()
        await side.login()
        gateway.finish()
        await side.serve()

    gateway = FakeGateway(first, second)
    fault = StreamFault(block_text_from=1)
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: fault}) as client:
        connection = make_connection(client, Injected(gateway), send_timeout=0.05)
        await run_until_done(connection, gateway)

    assert gateway.sides[0].logins() == []
    assert gateway.sides[1].logins()[0]["op"] == 2


async def test_closing_a_dead_connection_is_bounded_before_reconnecting() -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side, s=4, interval_ms=20)
        await side.serve(ack=False)

    async def second(side: GatewaySide) -> None:
        await resume_session(side, s=5)
        await side.serve()

    gateway = FakeGateway(first, second)
    fault = StreamFault(block_text_from=2, block_close=True)  # 心跳和关闭帧都写不出去
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: fault}) as client:
        connection = make_connection(
            client, Injected(gateway, finish_on="RESUMED"), close_timeout=0.05
        )
        await run_until_done(connection, gateway)

    assert gateway.sides[1].logins()[0]["d"]["seq"] == 4


# WebSocket 上下文抛出的异常


def broken_close() -> StreamFault:
    # anyio 的 TLS 流关闭握手失败时抛的就是它；httpx2 会把它包进异常组。
    return StreamFault(aclose_error=anyio.BrokenResourceError("TLS close broke"))


async def test_cleanup_error_does_not_hide_a_resumable_close_code() -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side, s=6)
        await side.close(4009)

    async def second(side: GatewaySide) -> None:
        await resume_session(side, s=7)
        await side.serve()

    async def same_token() -> str:
        return "same-token"  # 两次取到同一个 token 也没关系

    gateway = FakeGateway(first, second)
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: broken_close()}) as client:
        connection = make_connection(
            client, Injected(gateway, finish_on="RESUMED"), get_token=same_token
        )
        await run_until_done(connection, gateway)

    assert gateway.sides[1].logins()[0]["d"]["seq"] == 6


async def test_cleanup_error_does_not_hide_an_unrecoverable_close_code() -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side)
        await side.close(4914)

    gateway = FakeGateway(first)
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: broken_close()}) as client:
        with pytest.raises(pyqbot.GatewayError) as caught:
            await make_connection(client, Injected(gateway)).run()

    assert caught.value.err_code == 4914


async def test_cleanup_error_after_close_does_not_reconnect() -> None:
    gateway = FakeGateway(serve_after_login)
    fault = broken_close()
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: fault}) as client:
        connection = make_connection(client, Injected(gateway, finish_on="READY"))
        await run_until_done(connection, gateway)

    assert fault.aclosed
    assert len(gateway.sides) == 1


async def test_programming_error_is_raised_as_is_not_in_a_group() -> None:
    async def empty_token() -> str:
        return ""  # 违反 get_token 的约定：encode_identify 会抛 ValueError

    async def script(side: GatewaySide) -> None:
        await side.hello()
        await side.serve()

    gateway = FakeGateway(script)
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: broken_close()}) as client:
        connection = make_connection(client, Injected(gateway), get_token=empty_token)
        with pytest.raises(ValueError, match="access_token 不能为空"):
            await connection.run()


async def test_unexpected_error_while_connecting_is_raised_as_is() -> None:
    gateway = FakeGateway()
    injected = Injected(gateway)
    injected.urls = ["wss://buggy.test/websocket"]
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        with pytest.raises(RuntimeError, match="传输层自身的 bug"):
            await make_connection(client, injected).run()

    assert injected.url_calls == 1  # 不当作网络错误重试


async def test_worker_cancelled_by_someone_else_cancels_run() -> None:
    # 例如事件循环关闭时取消所有任务；这时 run() 不能当作 close() 正常返回。
    gateway = FakeGateway(serve_after_login)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        connection = make_connection(client, Injected(gateway, finish_on="READY"))
        runner = asyncio.create_task(connection.run())
        await gateway.done.wait()
        cast(asyncio.Task[None], vars(connection)["_worker"]).cancel()
        with pytest.raises(asyncio.CancelledError):
            await runner


# 异常分类：传输错误重连，其它都是编程错误


def defined_in(package: str) -> Exception:
    """异常类定义在 `package` 里的异常；只伪造模块名，不必真的导入那个包。"""
    cls = cast(type[Exception], type("SomeError", (Exception,), {"__module__": f"{package}._x"}))
    return cls("出错了")


def broken_read_after_login(fault: StreamFault, *, s: int = 2) -> Script:
    async def script(side: GatewaySide) -> None:
        await start_session(side, s=s)
        fault.fail_reads.set()
        await side.send(11)  # 唤醒正在等的读，下一次读就出错
        await side.serve()

    return script


@pytest.mark.parametrize(
    "error",
    [
        anyio.BrokenResourceError("network broke"),
        ConnectionResetError("reset"),
        TimeoutError(),
        EOFError(),
        *(defined_in(package) for package in ("anyio", "wsproto", "h11", "httpcore2", "httpx2")),
    ],
    ids=lambda error: f"{type(error).__module__}.{type(error).__name__}",
)
async def test_transport_error_from_the_background_reader_reconnects(error: Exception) -> None:
    async def second(side: GatewaySide) -> None:
        await resume_session(side, s=4)
        await side.serve()

    fault = StreamFault(read_error=error)
    gateway = FakeGateway(broken_read_after_login(fault), second)
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: fault}) as client:
        connection = make_connection(client, Injected(gateway, finish_on="RESUMED"))
        await run_until_done(connection, gateway)

    assert gateway.sides[1].logins()[0]["d"]["seq"] == 2


async def test_programming_error_from_the_background_reader_ends_run() -> None:
    error = RuntimeError("reader bug")
    fault = StreamFault(read_error=error)
    gateway = FakeGateway(broken_read_after_login(fault))
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: fault}) as client:
        with pytest.raises(RuntimeError) as caught:
            await make_connection(client, Injected(gateway)).run()

    assert caught.value is error
    assert len(gateway.sides) == 1


async def test_one_programming_error_among_transport_errors_ends_run() -> None:
    # 读和关闭流各出一个错，httpx2 把它们放进同一个异常组；编程错误不在第一个位置。
    bug = RuntimeError("aclose bug")
    fault = StreamFault(read_error=anyio.BrokenResourceError("network broke"), aclose_error=bug)
    gateway = FakeGateway(broken_read_after_login(fault))
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: fault}) as client:
        with pytest.raises(RuntimeError) as caught:
            await make_connection(client, Injected(gateway)).run()

    assert caught.value is bug


async def test_os_error_while_connecting_is_retried() -> None:
    gateway = FakeGateway(serve_after_login)
    injected = Injected(gateway, finish_on="READY")
    injected.urls = ["wss://oserror.test/websocket"]
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        await run_until_done(make_connection(client, injected), gateway)

    assert injected.url_calls == 2


# 连接自己正在关闭时的收尾


async def let_close_reach_its_wait() -> None:
    # close() 和它创建的收尾任务各走到自己的等待点；asyncio 按先后执行，几次让出就够。
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.mark.parametrize("ending", ["reconnect", "banned"])
async def test_close_lets_a_connection_already_closing_finish(ending: str) -> None:
    async def first(side: GatewaySide) -> None:
        await start_session(side)
        if ending == "reconnect":
            await side.send(7)
        else:
            await side.close(4914)
        await side.serve()

    gateway = FakeGateway(first)
    fault = StreamFault(block_close=True)
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: fault}) as client:
        connection = make_connection(client, Injected(gateway))
        runner = asyncio.create_task(connection.run())
        await fault.blocked.wait()  # 已拿到断开原因，正在写关闭帧
        closer = asyncio.create_task(connection.close())
        await let_close_reach_its_wait()
        fault.release.set()
        await closer
        result = (await asyncio.gather(runner, return_exceptions=True))[0]

    assert fault.aclosed
    assert len(gateway.sides) == 1  # 关完不再重连
    if ending == "reconnect":
        assert result is None
    else:
        assert isinstance(result, pyqbot.GatewayError)
        assert result.err_code == 4914


async def test_cancelling_run_does_not_cancel_a_worker_already_being_cancelled() -> None:
    gateway = FakeGateway(serve_after_login)
    fault = StreamFault(block_close=True)
    async with asyncio.timeout(TIMEOUT), open_client(gateway, {0: fault}) as client:
        connection = make_connection(client, Injected(gateway, finish_on="READY"))
        runner = asyncio.create_task(connection.run())
        await gateway.done.wait()
        # 像 asyncio.run() 收尾那样，worker 先被取消，然后才轮到 run()。
        cast(asyncio.Task[None], vars(connection)["_worker"]).cancel()
        await fault.blocked.wait()
        runner.cancel()
        await let_close_reach_its_wait()
        fault.release.set()
        with pytest.raises(asyncio.CancelledError):
            await runner

    assert fault.aclosed


async def test_leftover_cancellation_of_the_caller_is_not_taken_as_cancelling_run() -> None:
    gateway = FakeGateway(serve_after_login)
    async with asyncio.timeout(TIMEOUT), open_client(gateway) as client:
        connection = make_connection(client, Injected(gateway, finish_on="READY"))

        async def caller() -> None:
            cast(asyncio.Task[None], asyncio.current_task()).cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(0)
            # 捕获了取消却没有 uncancel()，cancelling() 仍然是 1。
            await connection.run()

        runner = asyncio.create_task(caller())
        await gateway.done.wait()
        await connection.close()
        assert await runner is None


# 构造时校验


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"shard": (1, 1)}, "shard"),
        ({"shard": (-1, 2)}, "shard"),
        ({"connect_timeout": 0}, "connect_timeout"),
        ({"handshake_timeout": -1}, "handshake_timeout"),
        ({"send_timeout": float("nan")}, "send_timeout"),
        ({"close_timeout": 0}, "close_timeout"),
        ({"connect_timeout": math.inf}, "connect_timeout"),
        ({"handshake_timeout": math.inf}, "handshake_timeout"),
        ({"send_timeout": math.inf}, "send_timeout"),
        ({"close_timeout": math.inf}, "close_timeout"),
        ({"reconnect_delay": -1}, "reconnect_delay"),
        ({"identify_interval": -0.1}, "identify_interval"),
        ({"reconnect_delay": 2, "max_reconnect_delay": 1}, "max_reconnect_delay"),
    ],
)
async def test_invalid_configuration_fails_at_construction(
    overrides: dict[str, Any], message: str
) -> None:
    async def never() -> str:
        raise AssertionError("不应被调用")

    with pytest.raises(ValueError, match=message):
        GatewayConnection(
            http_client=cast(httpx2.AsyncClient, None),  # 校验在用到它之前
            get_url=never,
            get_token=never,
            intents=INTENTS,
            on_dispatch=lambda payload: None,
            **overrides,
        )
