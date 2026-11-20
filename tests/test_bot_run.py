"""`Bot.start()` / `run()`：网关连接、分发器与请求层接在一起之后的端到端行为。"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator, MutableMapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
from httpx2.websockets import ASGIWebSocketTransport

import pyqbot
from pyqbot import GatewayState

HANG_GUARD = 5  # 秒：回归时应失败而不是挂起
FIXTURES = Path(__file__).parent / "fixtures"
TOKEN = "token-value-never-shown"
OPENID = "0123456789ABCDEF0123456789ABCDEF"  # 样本里发送者的 user_openid

# ASGI 消息是结构随 type 变化的字典，标准里没有更精确的类型。
type ASGIMessage = MutableMapping[str, Any]
type Receive = Callable[[], Awaitable[ASGIMessage]]
type Send = Callable[[ASGIMessage], Awaitable[None]]


def sample(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class Platform:
    """扮演开放平台：HTTP 接口与网关。网关在 READY 之后推送一条真实样本里的单聊消息。"""

    def __init__(self, *, close_code: int | None = None) -> None:
        self.close_code = close_code
        self.identifies: list[dict[str, Any]] = []
        self.sent: list[dict[str, object]] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})
        if path == "/gateway":
            return httpx2.Response(200, json={"url": "wss://gateway.test/websocket"})
        self.sent.append({"path": path, **json.loads(request.content)})
        return httpx2.Response(200, json={"id": "ROBOT1.0_sent"})

    async def gateway(self, scope: ASGIMessage, receive: Receive, send: Send) -> None:
        async def push(text: str) -> None:
            await send({"type": "websocket.send", "text": text})

        await receive()  # websocket.connect
        await send({"type": "websocket.accept"})
        await push('{"op": 10, "d": {"heartbeat_interval": 60000}}')
        self.identifies.append(json.loads((await receive())["text"]))
        if self.close_code is not None:
            await send({"type": "websocket.close", "code": self.close_code, "reason": ""})
            return
        await push(sample("gateway_ready.json"))
        await push(sample("gateway_c2c_message_create.json"))
        while (message := await receive())["type"] != "websocket.disconnect":
            if json.loads(message["text"])["op"] == 1:
                await push('{"op": 11}')


class FlakyPlatform(Platform):
    """网关等 `let_in` 才完成握手，推送消息后等 `cut` 再以可恢复的关闭码（4009）断开，之后的重连一律拒绝。"""

    def __init__(self) -> None:
        super().__init__()
        self.knocked, self.let_in, self.cut = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gateway(self, scope: ASGIMessage, receive: Receive, send: Send) -> None:
        await receive()  # websocket.connect
        if self.knocked.is_set():
            # 拒绝而不是挂起：客户端在握手中途放弃时，传输层不保证告诉网关这一侧。
            await send({"type": "websocket.http.response.start", "status": 503, "headers": []})
            await send({"type": "websocket.http.response.body", "body": b""})
            return
        self.knocked.set()
        await self.let_in.wait()
        await send({"type": "websocket.accept"})
        await send(
            {"type": "websocket.send", "text": '{"op": 10, "d": {"heartbeat_interval": 60000}}'}
        )
        await receive()  # Identify
        await send({"type": "websocket.send", "text": sample("gateway_ready.json")})
        await send({"type": "websocket.send", "text": sample("gateway_c2c_message_create.json")})
        await self.cut.wait()
        await send({"type": "websocket.close", "code": 4009, "reason": ""})


class Clock:
    """替换 SDK 读的系统时钟与单调时钟，两者可以分别拨动。"""

    def __init__(self) -> None:
        self.wall = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
        self.mono = 1000.0

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr("pyqbot._api.params.utc_now", lambda: clock.wall)
    monkeypatch.setattr("pyqbot._bot.monotonic", lambda: clock.mono)
    return clock


class LogWaiter(logging.Handler):
    """`pyqbot` 的日志里出现某段文字时置位 `seen`。"""

    def __init__(self, fragment: str) -> None:
        super().__init__()
        self._fragment = fragment
        self.seen = asyncio.Event()

    def emit(self, record: logging.LogRecord) -> None:
        if self._fragment in record.getMessage():
            self.seen.set()


@pytest.fixture
def reconnect_logged() -> Iterator[LogWaiter]:
    waiter = LogWaiter("秒后重连")  # 断开、记下状态之后，退避等待之前
    logger = logging.getLogger("pyqbot")
    logger.addHandler(waiter)
    previous = logger.level
    logger.setLevel(logging.WARNING)
    yield waiter
    logger.setLevel(previous)
    logger.removeHandler(waiter)


def status_of(bot: pyqbot.Bot) -> tuple[GatewayState, datetime, timedelta]:
    status = bot.gateway_status
    return status.state, status.since, status.elapsed


@asynccontextmanager
async def bot_on(platform: Platform) -> AsyncGenerator[pyqbot.Bot]:
    # 只能在测试函数体内用 async with 进入，原因见 docs/design.md「测试约定」。
    async with (
        httpx2.AsyncClient(
            transport=httpx2.MockTransport(platform.handle),
            mounts={"wss://": ASGIWebSocketTransport(platform.gateway)},
        ) as http_client,
        pyqbot.Bot("app-id", "app-secret", http_client=http_client) as bot,
    ):
        yield bot


async def ignore(message: pyqbot.C2CMessage) -> None:
    pass


async def test_message_from_the_gateway_reaches_the_handler_and_is_replied_to() -> None:
    platform = Platform()
    replied = asyncio.Event()

    async with asyncio.timeout(HANG_GUARD), bot_on(platform) as bot:

        @bot.on_c2c_message
        async def reply(message: pyqbot.C2CMessage) -> None:
            await message.reply(f"收到：{message.content}")
            replied.set()

        running = asyncio.create_task(bot.start())
        await replied.wait()
        await bot.close()
        await running  # close() 让 start() 正常返回

    identify = platform.identifies[0]["d"]
    assert identify["token"] == f"QQBot {TOKEN}"
    assert identify["intents"] == int(pyqbot.Intents.GROUP_AND_C2C_EVENT)
    assert platform.sent == [
        {
            "path": f"/v2/users/{OPENID}/messages",
            "msg_type": 0,
            "content": "收到：你好",
            "msg_id": "ROBOT1.0_fake-message-id",
            "msg_seq": 1,
        }
    ]
    assert asyncio.all_tasks() == {asyncio.current_task()}


async def test_handler_can_shut_the_bot_down() -> None:
    platform = Platform()

    async with asyncio.timeout(HANG_GUARD), bot_on(platform) as bot:

        @bot.on_c2c_message
        async def shut_down(message: pyqbot.C2CMessage) -> None:
            await bot.close()

        await bot.start()

    assert bot.is_closed
    assert asyncio.all_tasks() == {asyncio.current_task()}


async def test_stop_lets_running_handlers_finish_and_keeps_http_usable() -> None:
    platform = Platform()
    received, release = asyncio.Event(), asyncio.Event()

    async with asyncio.timeout(HANG_GUARD), bot_on(platform) as bot:

        @bot.on_c2c_message
        async def slow(message: pyqbot.C2CMessage) -> None:
            received.set()
            await release.wait()
            await message.reply("答完了")  # 网关已经断开，接口照常可用

        running = asyncio.create_task(bot.start())
        await received.wait()
        stopping = asyncio.create_task(bot.stop())
        await running  # 网关断开后 start() 正常返回
        assert not stopping.done()  # 还在等处理函数，没有取消它
        release.set()
        await stopping
        assert not bot.is_closed
        assert [sent["content"] for sent in platform.sent] == ["答完了"]
        with pytest.raises(RuntimeError, match="只能调用一次"):
            await bot.start()

    assert asyncio.all_tasks() == {asyncio.current_task()}


async def test_handler_can_stop_the_bot_without_waiting_for_itself() -> None:
    platform = Platform()

    async with asyncio.timeout(HANG_GUARD), bot_on(platform) as bot:

        @bot.on_c2c_message
        async def last_words(message: pyqbot.C2CMessage) -> None:
            await bot.stop()
            await message.reply("最后一条")

        await bot.start()
        await bot.stop()  # 可以重复调用；在外面调用时等处理函数做完

        assert [sent["content"] for sent in platform.sent] == ["最后一条"]


async def test_start_after_stop_is_rejected() -> None:
    async with pyqbot.Bot("app-id", "app-secret") as bot:
        bot.on_c2c_message(ignore)
        await bot.stop()  # 还没启动：没有网关要断开
        with pytest.raises(RuntimeError, match="已停止"):
            await bot.start()


async def test_unrecoverable_close_code_ends_start_with_gateway_error() -> None:
    platform = Platform(close_code=4915)

    async with asyncio.timeout(HANG_GUARD), bot_on(platform) as bot:
        bot.on_c2c_message(ignore)
        with pytest.raises(pyqbot.GatewayError) as caught:
            await bot.start()

    assert caught.value.err_code == 4915


async def test_start_without_anything_to_subscribe_is_rejected() -> None:
    async with pyqbot.Bot("app-id", "app-secret") as bot:
        with pytest.raises(RuntimeError, match="没有要订阅的事件"):
            await bot.start()


async def test_start_can_only_be_called_once() -> None:
    platform = Platform()

    async with asyncio.timeout(HANG_GUARD), bot_on(platform) as bot:
        bot.on_c2c_message(ignore)
        running = asyncio.create_task(bot.start())
        await asyncio.sleep(0)  # 让第一次 start() 先跑到它的第一个等待点
        with pytest.raises(RuntimeError, match="只能调用一次"):
            await bot.start()
        await bot.close()
        await running


async def test_start_after_close_is_rejected() -> None:
    bot = pyqbot.Bot("app-id", "app-secret")
    bot.on_c2c_message(ignore)
    await bot.close()

    with pytest.raises(RuntimeError, match="已关闭"):
        await bot.start()


def test_run_starts_the_bot_and_exits_cleanly_on_ctrl_c(monkeypatch: pytest.MonkeyPatch) -> None:
    closed_when_started: list[bool] = []

    async def interrupted(self: pyqbot.Bot) -> None:
        closed_when_started.append(self.is_closed)
        raise KeyboardInterrupt

    monkeypatch.setattr(pyqbot.Bot, "start", interrupted)
    bot = pyqbot.Bot("app-id", "app-secret")

    bot.run()

    assert closed_when_started == [False]
    assert bot.is_closed


def test_run_closes_the_bot_and_lets_errors_through(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing(self: pyqbot.Bot) -> None:
        raise pyqbot.GatewayError("机器人已封禁", err_code=4915)

    monkeypatch.setattr(pyqbot.Bot, "start", failing)
    bot = pyqbot.Bot("app-id", "app-secret")

    with pytest.raises(pyqbot.GatewayError):
        bot.run()

    assert bot.is_closed


async def test_gateway_status_follows_the_connection_until_stopped(
    clock: Clock, reconnect_logged: LogWaiter
) -> None:
    platform = FlakyPlatform()
    received = asyncio.Event()
    minute = timedelta(minutes=1)

    async with asyncio.timeout(HANG_GUARD), bot_on(platform) as bot:

        @bot.on_c2c_message
        async def got(message: pyqbot.C2CMessage) -> None:
            received.set()

        constructed = clock.wall
        clock.advance(60)
        assert status_of(bot) == (GatewayState.NOT_STARTED, constructed, minute)

        running = asyncio.create_task(bot.start())
        await platform.knocked.wait()
        started = clock.wall
        clock.advance(60)
        # 首次连上之前也算断开，从 start() 起算。
        assert status_of(bot) == (GatewayState.DISCONNECTED, started, minute)

        clock.advance(60)
        platform.let_in.set()
        await received.wait()
        connected = clock.wall
        clock.advance(60)
        assert status_of(bot) == (GatewayState.CONNECTED, connected, minute)

        platform.cut.set()
        await reconnect_logged.seen.wait()
        lost = clock.wall
        clock.advance(600)
        assert status_of(bot) == (GatewayState.DISCONNECTED, lost, 10 * minute)

        stopping = clock.wall
        await bot.stop()
        await running
        clock.advance(60)
        await bot.close()  # STOPPED 是终态，再关闭也不改起始时刻
        assert status_of(bot) == (GatewayState.STOPPED, stopping, minute)

    assert asyncio.all_tasks() == {asyncio.current_task()}


@pytest.mark.parametrize("ending", ["stop", "close"])
async def test_disconnecting_while_stopping_does_not_overwrite_stopped(
    clock: Clock, ending: str
) -> None:
    platform = Platform()
    received, release = asyncio.Event(), asyncio.Event()

    async with asyncio.timeout(HANG_GUARD), bot_on(platform) as bot:

        @bot.on_c2c_message
        async def busy(message: pyqbot.C2CMessage) -> None:
            received.set()
            await release.wait()

        running = asyncio.create_task(bot.start())
        await received.wait()
        stopped = clock.wall
        ending_task = asyncio.create_task(bot.stop() if ending == "stop" else bot.close())
        await asyncio.sleep(0)  # 先让它记下 STOPPED，连接随后才断开
        clock.advance(60)
        await running  # 连接已经报告了断开；stop() 还在等处理函数
        assert status_of(bot) == (GatewayState.STOPPED, stopped, timedelta(minutes=1))
        release.set()
        await ending_task
        assert status_of(bot) == (GatewayState.STOPPED, stopped, timedelta(minutes=1))


async def test_gateway_status_is_stopped_once_start_is_cancelled(clock: Clock) -> None:
    platform = Platform()
    received = asyncio.Event()

    async with asyncio.timeout(HANG_GUARD), bot_on(platform) as bot:

        @bot.on_c2c_message
        async def got(message: pyqbot.C2CMessage) -> None:
            received.set()

        running = asyncio.create_task(bot.start())
        await received.wait()
        clock.advance(5)
        running.cancel()  # run() 里按 Ctrl+C 走的也是这条路
        with pytest.raises(asyncio.CancelledError):
            await running
        assert status_of(bot) == (GatewayState.STOPPED, clock.wall, timedelta())


async def test_gateway_status_is_stopped_once_start_raises(clock: Clock) -> None:
    platform = Platform(close_code=4915)

    async with asyncio.timeout(HANG_GUARD), bot_on(platform) as bot:
        bot.on_c2c_message(ignore)
        clock.advance(5)
        with pytest.raises(pyqbot.GatewayError):
            await bot.start()
        assert status_of(bot) == (GatewayState.STOPPED, clock.wall, timedelta())


async def test_rejected_start_leaves_gateway_status_unchanged(clock: Clock) -> None:
    async with pyqbot.Bot("app-id", "app-secret") as bot:
        constructed = clock.wall
        clock.advance(5)
        with pytest.raises(RuntimeError, match="没有要订阅的事件"):
            await bot.start()
        assert status_of(bot) == (GatewayState.NOT_STARTED, constructed, timedelta(seconds=5))


@pytest.mark.parametrize("ending", ["stop", "close"])
async def test_gateway_status_is_stopped_without_ever_starting(clock: Clock, ending: str) -> None:
    bot = pyqbot.Bot("app-id", "app-secret")
    clock.advance(5)
    ended = clock.wall
    await (bot.stop() if ending == "stop" else bot.close())
    clock.advance(5)
    await bot.close()

    assert status_of(bot) == (GatewayState.STOPPED, ended, timedelta(seconds=5))


@pytest.mark.parametrize("wall_seconds", [-3600, 7200], ids=["set-back", "set-forward"])
async def test_gateway_status_elapsed_ignores_system_clock_changes(
    clock: Clock, wall_seconds: float
) -> None:
    async with pyqbot.Bot("app-id", "app-secret") as bot:
        constructed = clock.wall
        clock.wall += timedelta(seconds=wall_seconds)
        clock.mono += 30

        assert status_of(bot) == (GatewayState.NOT_STARTED, constructed, timedelta(seconds=30))
