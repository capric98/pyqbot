"""事件模型基类：绑定 `Client`，以及被动回复时 `msg_id` / `msg_seq` 的填法。"""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx2
import msgspec
import pytest

import pyqbot
from pyqbot._models.event import Event, ReceivedMessage, bind_client, next_msg_seq

SENT = {"id": "ROBOT1.0_sent", "timestamp": "2026-07-21T10:30:00+08:00"}


class Ping(Event):
    content: str = ""

    def client(self) -> pyqbot.Client:
        return self._bound_client()


class Platform:
    def __init__(self) -> None:
        self.bodies: list[dict[str, object]] = []
        self.fail = False

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": "t", "expires_in": "7200"})
        self.bodies.append(json.loads(request.content))
        if self.fail:
            return httpx2.Response(400, json={"err_code": 40034128, "message": "次数超限"})
        return httpx2.Response(200, json=SENT)

    def replies(self) -> list[tuple[object, object]]:
        return [(body.get("msg_id"), body.get("msg_seq")) for body in self.bodies]


@asynccontextmanager
async def client_for(platform: Platform) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client("app-id", "app-secret", http_client=http_client) as client,
    ):
        yield client


async def test_reply_fills_msg_id_and_increments_msg_seq() -> None:
    platform = Platform()
    first, second = ReceivedMessage(id="m-1"), ReceivedMessage(id="m-2")

    async with client_for(platform) as client:
        await client.users.send_message("u", "a", reply_to=first)
        await client.users.send_message("u", "b", reply_to=first)
        await client.groups.send_message("g", "c", reply_to=second)
        await client.groups.send_message("g", "d", reply_to=first)
        await client.users.send_message("u", "主动消息")

    assert platform.replies() == [("m-1", 1), ("m-1", 2), ("m-2", 1), ("m-1", 3), (None, None)]
    assert platform.bodies[0] == {"msg_type": 0, "content": "a", "msg_id": "m-1", "msg_seq": 1}


async def test_failed_reply_still_uses_up_its_msg_seq() -> None:
    platform = Platform()
    message = ReceivedMessage(id="m")

    async with client_for(platform) as client:
        platform.fail = True
        with pytest.raises(pyqbot.APIError):
            await client.users.send_message("u", "a", reply_to=message)
        platform.fail = False
        await client.users.send_message("u", "b", reply_to=message)

    assert platform.replies() == [("m", 1), ("m", 2)]


def test_msg_seq_counter_is_not_a_field() -> None:
    message = ReceivedMessage(id="m")

    assert [next_msg_seq(message) for _ in range(3)] == [1, 2, 3]
    assert message == ReceivedMessage(id="m")
    assert message.to_dict() == {"id": "m"}
    assert repr(message) == "ReceivedMessage(id='m')"


def test_unbound_event_explains_why_it_cannot_call_the_api() -> None:
    with pytest.raises(RuntimeError, match="Ping 没有绑定 Client"):
        Ping(content="hi").client()


async def test_bound_client_is_returned_and_hidden_from_the_fields() -> None:
    event = Ping(content="hi")

    async with pyqbot.Client("app-id", "app-secret") as client:
        bind_client(event, client)

        assert event.client() is client
        assert event == Ping(content="hi")
        assert event.to_dict() == {"content": "hi"}
        assert msgspec.json.encode(event) == b'{"content":"hi"}'
        assert "Client" not in repr(event)
        with pytest.raises(AttributeError):
            event.content = "changed"  # pyright: ignore[reportAttributeAccessIssue]  验证不可变
