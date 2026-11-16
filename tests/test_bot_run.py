"""`Bot.start()` / `run()`：网关连接、分发器与请求层接在一起之后的端到端行为。"""

import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
import pytest
from httpx2.websockets import ASGIWebSocketTransport

import pyqbot

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
