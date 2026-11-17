# pyright: reportUnnecessaryTypeIgnoreComment=true
"""流式消息：分片的填法、结束分片、异常与取消时的行为。"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx2
import pytest

import pyqbot
from pyqbot._models.event import bind_client, bind_event_id

APP_SECRET = "secret-value-never-shown"
TOKEN = "access-token-value"
PATH = "/v2/users/u/stream_messages"
CHUNK = {
    "id": "stream-1",
    "timestamp": "2026-07-21T10:00:00+08:00",
    "ext_info": {"ref_idx": "REFIDX_1"},
    "remain_msg_len": 100,
}


class Platform:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, object]]] = []
        self.responses: list[httpx2.Response] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})
        self.requests.append(
            (request.method, request.url.raw_path.decode(), json.loads(request.content))
        )
        if self.responses:
            return self.responses.pop(0)
        return httpx2.Response(200, json=CHUNK)

    def bodies(self) -> list[dict[str, object]]:
        return [body for _, _, body in self.requests]


@asynccontextmanager
async def client_for(platform: Platform) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client("app-id", APP_SECRET, http_client=http_client) as client,
    ):
        yield client


def c2c(message_id: str = "m") -> pyqbot.C2CMessage:
    return pyqbot.C2CMessage(id=message_id, author=pyqbot.C2CUser(user_openid="u"))


class C2CEvent(pyqbot.C2CReplyTarget):
    """只能用 event_id 回复的单聊事件（如加好友）。"""


def chunk(index: int, state: int, raw: str, **extra: object) -> dict[str, object]:
    return {
        "input_mode": "append",
        "input_state": state,
        "index": index,
        "content_type": "markdown",
        "content_raw": raw,
        "msg_id": "m",
        "msg_seq": 1,
    } | extra


# ---- 分片的填法 ----


async def test_chunks_share_msg_seq_and_carry_the_stream_id_after_the_first() -> None:
    platform = Platform()
    message = c2c()

    async with client_for(platform) as client:
        async with client.users.stream_message("u", reply_to=message, coalesce=False) as stream:
            assert stream.stream_msg_id is None
            assert stream.last_sent is None
            await stream.append("你好")
            await stream.append("")  # 空串不发
            await stream.append("，世界")
        bind_client(message, client)
        await message.reply("之后的回复")

    assert stream.finished
    assert stream.stream_msg_id == "stream-1"
    assert stream.last_sent is not None
    assert stream.last_sent.remain_msg_len == 100
    assert isinstance(stream.last_sent, pyqbot.SentMessage)
    assert [path for _, path, _ in platform.requests] == [PATH] * 3 + ["/v2/users/u/messages"]
    assert platform.bodies() == [
        chunk(0, 1, "你好"),
        chunk(1, 1, "，世界", stream_msg_id="stream-1"),
        chunk(2, 10, "", stream_msg_id="stream-1"),
        {"msg_type": 0, "content": "之后的回复", "msg_id": "m", "msg_seq": 2},
    ]


async def test_replace_and_plain_text() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        stream = client.users.stream_message("u", reply_to=c2c(), markdown=False, coalesce=False)
        await stream.replace("正在生成")
        await stream.append("。")
        await stream.replace("正在生成。完成")
        await stream.finish()
        await stream.finish()  # 可以重复调用

    text = {"content_type": "text", "stream_msg_id": "stream-1"}
    assert platform.bodies() == [
        chunk(0, 1, "正在生成", input_mode="replace", content_type="text"),
        chunk(1, 1, "。", **text),
        chunk(2, 1, "正在生成。完成", input_mode="replace", **text),
        chunk(3, 10, "", **text),
    ]


async def test_reply_stream_on_a_dispatched_message() -> None:
    platform = Platform()
    message = c2c()

    async with client_for(platform) as client:
        bind_client(message, client)
        async with message.reply_stream(markdown=False) as stream:
            await stream.append("a")

    assert [path for _, path, _ in platform.requests] == [PATH, PATH]
    assert platform.bodies()[0]["content_type"] == "text"


def test_reply_stream_needs_a_bound_client() -> None:
    with pytest.raises(RuntimeError, match="没有绑定 Client"):
        c2c().reply_stream()


async def test_events_are_replied_to_with_event_id() -> None:
    platform = Platform()
    event = C2CEvent()
    bind_event_id(event, "FRIEND_ADD:1")

    async with (
        client_for(platform) as client,
        client.users.stream_message("u", reply_to=event) as stream,
    ):
        await stream.append("欢迎")

    first = platform.bodies()[0]
    assert first["event_id"] == "FRIEND_ADD:1"
    assert first["msg_seq"] == 1
    assert "msg_id" not in first


async def test_event_without_id_is_rejected_before_sending() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match="没有事件 ID"):
            async with client.users.stream_message("u", reply_to=C2CEvent()) as stream:
                await stream.append("a")

    assert platform.requests == []


async def test_nothing_is_sent_when_nothing_was_appended() -> None:
    platform = Platform()
    message = c2c()

    async with client_for(platform) as client:
        async with client.users.stream_message("u", reply_to=message):
            pass
        bind_client(message, client)
        await message.reply("a")

    assert platform.bodies() == [{"msg_type": 0, "content": "a", "msg_id": "m", "msg_seq": 1}]


def test_openid_must_not_be_empty() -> None:
    client = pyqbot.Client("app-id", APP_SECRET)
    with pytest.raises(ValueError, match="openid 不合法"):
        client.users.stream_message("", reply_to=c2c())


async def test_concurrent_appends_are_sent_one_by_one() -> None:  # 两种模式都一样
    first_arrived = asyncio.Event()
    release = asyncio.Event()
    bodies: list[dict[str, object]] = []

    async def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            first_arrived.set()
            await release.wait()
        return httpx2.Response(200, json=CHUNK)

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(handle)) as http_client,
        pyqbot.Client("app-id", APP_SECRET, http_client=http_client) as client,
        asyncio.timeout(5),
    ):
        stream = client.users.stream_message("u", reply_to=c2c())
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(stream.append("a"))
            await first_arrived.wait()
            tasks.create_task(stream.append("b"))
            await asyncio.sleep(0)
            assert len(bodies) == 1  # 第二个分片等第一个的 stream_msg_id
            release.set()

    assert [(b["index"], b.get("stream_msg_id")) for b in bodies] == [(0, None), (1, "stream-1")]


# ---- 结束之后 ----


async def test_append_after_finish_is_rejected() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        async with client.users.stream_message("u", reply_to=c2c()) as stream:
            await stream.append("a")
        with pytest.raises(RuntimeError, match="已经结束"):
            await stream.append("b")
        with pytest.raises(RuntimeError, match="已经结束"):
            await stream.replace("ab")
        with pytest.raises(RuntimeError, match="已经结束"):
            async with stream:
                pass

    assert len(platform.requests) == 2


# ---- 异常与取消 ----


async def append_then_fail(stream: pyqbot.StreamMessage) -> None:
    async with stream:
        await stream.append("a")
        raise LookupError("模型出错")


async def append_then_replace(stream: pyqbot.StreamMessage) -> None:
    async with stream:
        await stream.append("abc")
        await stream.replace("xyz")


async def test_body_error_still_sends_the_final_chunk() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(LookupError, match="模型出错"):
            await append_then_fail(client.users.stream_message("u", reply_to=c2c()))

    assert [body["input_state"] for body in platform.bodies()] == [1, 10]


async def test_failed_final_chunk_is_logged_without_hiding_the_body_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    platform = Platform()
    platform.responses = [
        httpx2.Response(200, json=CHUNK),
        httpx2.Response(500, json={"err_code": 50001, "message": f"内部错误 {APP_SECRET} {TOKEN}"}),
    ]

    async with client_for(platform) as client:
        with pytest.raises(LookupError), caplog.at_level(logging.WARNING, logger="pyqbot"):
            await append_then_fail(client.users.stream_message("u", reply_to=c2c()))

    assert "流式消息没有正常结束" in caplog.text
    assert "内部错误" in caplog.text
    assert APP_SECRET not in caplog.text
    assert TOKEN not in caplog.text


async def test_failed_chunk_ends_the_stream_without_a_final_chunk() -> None:
    platform = Platform()
    platform.responses = [
        httpx2.Response(200, json=CHUNK),
        httpx2.Response(400, json={"err_code": 40007, "message": "已下发内容前缀不可修改"}),
    ]

    async with client_for(platform) as client:
        stream = client.users.stream_message("u", reply_to=c2c())
        with pytest.raises(pyqbot.APIError) as caught:
            await append_then_replace(stream)
        assert caught.value.err_code == 40007
        assert stream.finished
        with pytest.raises(RuntimeError, match="分片发送失败"):
            await stream.append("d")
        await stream.finish()  # 什么也不做

    assert len(platform.requests) == 2


async def test_cancellation_does_not_send_the_final_chunk() -> None:
    platform = Platform()
    appended = asyncio.Event()

    async def body(client: pyqbot.Client) -> None:
        async with client.users.stream_message("u", reply_to=c2c()) as stream:
            await stream.append("a")
            appended.set()
            await asyncio.Event().wait()

    async with client_for(platform) as client:
        task = asyncio.create_task(body(client))
        async with asyncio.timeout(5):
            await appended.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            async with asyncio.timeout(5):
                await task

    assert len(platform.requests) == 1


class BlockingPlatform:
    """第 `block_at` 个分片请求（从 0 数）挂住，直到 `release` 被设置。"""

    def __init__(self, block_at: int) -> None:
        self.bodies: list[dict[str, object]] = []
        self.block_at = block_at
        self.arrived = asyncio.Event()
        self.release = asyncio.Event()

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})
        self.bodies.append(json.loads(request.content))
        if len(self.bodies) - 1 == self.block_at:
            self.arrived.set()
            await self.release.wait()
        return httpx2.Response(200, json=CHUNK)

    def chunks(self) -> list[tuple[object, object, object]]:
        return [(b["index"], b["input_state"], b.get("stream_msg_id")) for b in self.bodies]


@asynccontextmanager
async def blocking_client(platform: BlockingPlatform) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client("app-id", APP_SECRET, http_client=http_client) as client,
        asyncio.timeout(5),
    ):
        yield client


async def test_cancelling_a_chunk_in_flight_ends_the_stream() -> None:
    platform = BlockingPlatform(block_at=1)

    async def body(stream: pyqbot.StreamMessage) -> None:
        async with stream:
            await stream.append("a")
            await stream.append("b")  # 这个请求在途时被取消

    async with blocking_client(platform) as client:
        stream = client.users.stream_message("u", reply_to=c2c(), coalesce=False)
        task = asyncio.create_task(body(stream))
        await platform.arrived.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # 平台是否收到了这个分片无从得知，所以按发送失败处理：流在本地终止，锁已释放。
        assert stream.finished
        with pytest.raises(RuntimeError, match="分片发送失败"):
            await stream.append("c")
        await stream.finish()  # 拿得到锁才会返回；已终止，不发请求

    assert platform.chunks() == [(0, 1, None), (1, 1, "stream-1")]


async def test_cancelling_a_task_waiting_for_the_lock_leaves_the_stream_usable() -> None:
    platform = BlockingPlatform(block_at=0)

    async with blocking_client(platform) as client:
        stream = client.users.stream_message("u", reply_to=c2c(), coalesce=False)
        holder = asyncio.create_task(stream.append("a"))
        await platform.arrived.wait()
        waiter = asyncio.create_task(stream.append("b"))
        await asyncio.sleep(0)  # 让 waiter 跑到等锁的地方
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        # 等锁时被取消的调用什么也没发，不占用 index，也不终止这条流。
        assert not stream.finished
        assert len(platform.bodies) == 1
        platform.release.set()
        await holder
        await stream.append("c")
        await stream.finish()

    assert platform.chunks() == [(0, 1, None), (1, 1, "stream-1"), (2, 10, "stream-1")]
    assert [b["content_raw"] for b in platform.bodies] == ["a", "c", ""]


async def test_closed_client_ends_the_stream() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        stream = client.users.stream_message("u", reply_to=c2c(), coalesce=False)
    with pytest.raises(RuntimeError, match="已关闭"):
        await stream.append("a")

    assert stream.finished
    assert platform.requests == []


# ---- 合并分片（默认） ----


async def test_appends_during_a_chunk_in_flight_go_out_as_one_chunk() -> None:
    platform = BlockingPlatform(block_at=0)

    async with blocking_client(platform) as client:
        stream = client.users.stream_message("u", reply_to=c2c())
        await stream.append("你")  # 不等发送就返回
        await platform.arrived.wait()
        await stream.append("好")
        await stream.append("，世界")
        assert len(platform.bodies) == 1
        platform.release.set()
        await stream.finish()  # 等攒着的发完再发结束分片

    assert platform.chunks() == [(0, 1, None), (1, 1, "stream-1"), (2, 10, "stream-1")]
    assert [b["content_raw"] for b in platform.bodies] == ["你", "好，世界", ""]


async def test_replace_absorbs_the_pending_text() -> None:
    platform = BlockingPlatform(block_at=0)

    async with blocking_client(platform) as client:
        stream = client.users.stream_message("u", reply_to=c2c())
        await stream.append("草稿")
        await platform.arrived.wait()
        await stream.append("，继续")
        await stream.replace("定稿")
        await stream.append("！")
        platform.release.set()
        await stream.finish()

    assert [(b["input_mode"], b["content_raw"]) for b in platform.bodies] == [
        ("append", "草稿"),
        ("replace", "定稿！"),
        ("append", ""),
    ]


async def test_a_failed_chunk_is_raised_once_by_the_next_call() -> None:
    platform = Platform()
    platform.responses = [httpx2.Response(400, json={"err_code": 40007, "message": "前缀不可修改"})]

    async with client_for(platform) as client:
        stream = client.users.stream_message("u", reply_to=c2c())
        await stream.append("a")  # 失败发生在后台
        with pytest.raises(pyqbot.APIError) as caught:
            await stream.finish()
        assert caught.value.err_code == 40007
        assert stream.finished
        with pytest.raises(RuntimeError, match="分片发送失败"):
            await stream.append("b")
        await stream.finish()  # 已经抛过，什么也不做

    assert len(platform.requests) == 1


async def test_a_failed_chunk_is_raised_when_leaving_async_with() -> None:
    platform = Platform()
    platform.responses = [httpx2.Response(400, json={"err_code": 40007, "message": "前缀不可修改"})]

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError):
            async with client.users.stream_message("u", reply_to=c2c()) as stream:
                await stream.append("a")

    assert len(platform.requests) == 1  # 没有结束分片


async def test_closed_client_is_reported_by_the_next_call() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        stream = client.users.stream_message("u", reply_to=c2c())
    await stream.append("a")
    with pytest.raises(RuntimeError, match="已关闭"):
        await stream.finish()

    assert stream.finished
    assert platform.requests == []


async def test_cancelled_body_still_sends_the_pending_text_but_no_final_chunk() -> None:
    platform = BlockingPlatform(block_at=0)

    async def body(stream: pyqbot.StreamMessage) -> None:
        async with stream:
            await stream.append("a")
            await platform.arrived.wait()
            await stream.append("b")
            await asyncio.Event().wait()

    async with blocking_client(platform) as client:
        stream = client.users.stream_message("u", reply_to=c2c())
        task = asyncio.create_task(body(stream))
        await platform.arrived.wait()
        await asyncio.sleep(0)  # 让 body 攒下「b」
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        platform.release.set()
        sender = stream._sender  # pyright: ignore[reportPrivateUsage]  等后台发送任务结束
        assert sender is not None
        await sender

    assert [(b["content_raw"], b["input_state"]) for b in platform.bodies] == [("a", 1), ("b", 1)]


# ---- 类型 ----


async def wrong_scene_is_rejected_by_pyright(client: pyqbot.Client) -> None:
    """不运行，只给 pyright 看：群消息不能作为流式消息的回复对象。"""
    group = pyqbot.GroupAtMessage(
        id="m", group_openid="g", author=pyqbot.GroupMessageAuthor(member_openid="member")
    )
    client.users.stream_message("u", reply_to=group)  # pyright: ignore[reportArgumentType]
    client.users.stream_message("u")  # pyright: ignore[reportCallIssue]
