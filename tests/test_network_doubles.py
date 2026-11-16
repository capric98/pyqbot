"""本地替身的用法示范：HTTP 与 WebSocket 都经由公共入口的 `http_client` 注入。"""

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import httpx2
import pytest
from httpx2.websockets import ASGIWebSocketTransport

import pyqbot

# ASGI 消息是结构随 type 变化的字典，标准里就没有更精确的类型。
type ASGIMessage = MutableMapping[str, Any]


async def test_real_network_is_blocked_when_no_double_is_injected() -> None:
    async with pyqbot.Client("app-id", "app-secret") as client:
        with pytest.raises(AssertionError, match="不得访问真实网络"):
            await client.http_client.get(f"{client.config.base_url}/users/@me")


async def test_http_double_is_injected_through_http_client() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={"id": "bot"})

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client,
        pyqbot.Client("app-id", "app-secret", http_client=http_client) as client,
    ):
        response = await client.http_client.get(f"{client.config.base_url}/users/@me")

    assert response.json() == {"id": "bot"}
    assert [str(request.url) for request in seen] == ["https://api.bot.qq.com/users/@me"]


async def test_websocket_double_is_mounted_on_the_same_http_client() -> None:
    async def gateway(
        scope: ASGIMessage,
        receive: Callable[[], Awaitable[ASGIMessage]],
        send: Callable[[ASGIMessage], Awaitable[None]],
    ) -> None:
        await receive()  # websocket.connect
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.send", "text": '{"op": 10}'})
        frame = await receive()
        await send({"type": "websocket.send", "text": frame["text"]})
        await receive()  # websocket.disconnect

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"url": "wss://gateway.test/websocket"})

    # ASGIWebSocketTransport 在 __aenter__ 里才建好内部任务组：
    # 承载它的 AsyncClient 必须用 async with 打开，且要在测试函数体内（不能放进 yield fixture）。
    async with (
        httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler),
            mounts={"wss://": ASGIWebSocketTransport(gateway)},
        ) as http_client,
        pyqbot.Client("app-id", "app-secret", http_client=http_client) as client,
    ):
        response = await client.http_client.get(f"{client.config.base_url}/gateway")
        async with client.http_client.websocket(response.json()["url"]) as ws:
            hello = await ws.receive_json()
            await ws.send_json({"op": 1, "d": None})
            echoed = await ws.receive_json()

    assert hello == {"op": 10}
    assert echoed == {"op": 1, "d": None}
