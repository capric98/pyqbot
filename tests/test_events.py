"""事件模型：基类的绑定与 `msg_seq`，单聊、群聊消息的解码与 `reply()`。"""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx2
import msgspec
import pytest

import pyqbot
from pyqbot._errors import PayloadError
from pyqbot._gateway.payload import GatewayPayload, decode_payload
from pyqbot._models.event import (
    Event,
    ReceivedMessage,
    bind_client,
    bind_event_id,
    next_msg_seq,
)
from pyqbot._models.message import MessageScene

SENT = {"id": "ROBOT1.0_sent", "timestamp": "2026-07-21T10:30:00+08:00"}
UTC8 = timezone(timedelta(hours=8))

# autogen/event/group_at_message_create.md 的示例 1～3。
GROUP_TEXT = {
    "id": "ROBOT1.0_x",
    "author": {
        "id": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
        "member_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
        "member_role": "member",
        "username": "小明",
        "bot": False,
    },
    "content": " /今日天气 ",
    "group_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
    "message_type": 0,
    "timestamp": "2026-07-21T10:00:00+08:00",
    "message_scene": {
        "source": "default",
        "ext": [
            "msg_idx=REFIDX_xxxxxxxxxxxxxxx==",
            "auth_token=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        ],
    },
}
GROUP_IMAGE = {
    **GROUP_TEXT,
    "content": " 看看这张风景照 ",
    "attachments": [
        {
            "content_type": "image/jpeg",
            "filename": "photo.jpg",
            "url": "https://multimedia.nt.qq.com.cn/download?appid=xxx&fileid=xxx&rkey=xxx&spec=0",
            "width": 1920,
            "height": 1080,
            "size": 256000,
        }
    ],
}
GROUP_QUOTE = {
    **GROUP_TEXT,
    "content": " ",
    "message_type": 103,
    "msg_elements": [{"content": "=== 消息 1 ===\n[消息内容] 今天的学习计划已完成"}],
}


def dispatch_of(event_name: str, data: object) -> GatewayPayload:
    return decode_payload(json.dumps({"op": 0, "s": 1, "t": event_name, "d": data}))


def c2c_sample() -> GatewayPayload:
    path = Path(__file__).parent / "fixtures" / "gateway_c2c_message_create.json"
    return decode_payload(path.read_bytes())


class Ping(Event):
    content: str = ""

    def client(self) -> pyqbot.Client:
        return self._bound_client()


class Platform:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.fail = False

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": "t", "expires_in": "7200"})
        self.requests.append((request.url.path, json.loads(request.content)))
        if self.fail:
            return httpx2.Response(400, json={"err_code": 40034128, "message": "次数超限"})
        return httpx2.Response(200, json=SENT)

    def replies(self) -> list[tuple[object, object]]:
        return [(body.get("msg_id"), body.get("msg_seq")) for _, body in self.requests]


@asynccontextmanager
async def client_for(platform: Platform) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client("app-id", "app-secret", http_client=http_client) as client,
    ):
        yield client


def c2c(message_id: str = "m", openid: str = "u") -> pyqbot.C2CMessage:
    return pyqbot.C2CMessage(id=message_id, author=pyqbot.C2CUser(user_openid=openid))


# 仅测试用的可回复事件：真正的 FRIEND_ADD、GROUP_ADD_ROBOT 等由各自的模块实现。
class FriendAdded(pyqbot.C2CReplyTarget):
    openid: str = ""


class RobotAdded(pyqbot.GroupReplyTarget):
    group_openid: str = ""


class Clicked(pyqbot.C2CReplyTarget, pyqbot.GroupReplyTarget):
    """INTERACTION_CREATE 那样单聊、群聊都会发生的事件。"""


def with_event_id[E: Event](event: E, event_id: str | None) -> E:
    bind_event_id(event, event_id)
    return event


# ---- 基类 ----


async def test_reply_to_fills_msg_id_and_increments_msg_seq() -> None:
    platform = Platform()
    first, second = (
        c2c("m-1"),
        pyqbot.GroupAtMessage(
            id="m-2", group_openid="g", author=pyqbot.GroupMessageAuthor(member_openid="member")
        ),
    )

    async with client_for(platform) as client:
        await client.users.send_message("u", "a", reply_to=first)
        await client.users.send_message("u", "b", reply_to=first)
        await client.groups.send_message("g", "c", reply_to=second)
        await client.users.send_message("u", "d", reply_to=first)
        await client.users.send_message("u", "主动消息")

    assert platform.replies() == [("m-1", 1), ("m-1", 2), ("m-2", 1), ("m-1", 3), (None, None)]
    assert platform.requests[0][1] == {"msg_type": 0, "content": "a", "msg_id": "m-1", "msg_seq": 1}


async def test_failed_reply_still_uses_up_its_msg_seq() -> None:
    platform = Platform()
    message = c2c()

    async with client_for(platform) as client:
        platform.fail = True
        with pytest.raises(pyqbot.APIError):
            await client.users.send_message("u", "a", reply_to=message)
        platform.fail = False
        await client.users.send_message("u", "b", reply_to=message)

    assert platform.replies() == [("m", 1), ("m", 2)]


async def test_events_reply_with_their_event_id_and_count_msg_seq_per_object() -> None:
    platform = Platform()
    friend = with_event_id(FriendAdded(openid="u"), "FRIEND_ADD:1")
    robot = with_event_id(RobotAdded(group_openid="g"), "GROUP_ADD_ROBOT:2")
    clicked = with_event_id(Clicked(), "INTERACTION_CREATE:3")

    async with client_for(platform) as client:
        await client.users.send_message("u", "a", reply_to=friend)
        await client.users.send_message("u", "b", reply_to=friend)
        await client.groups.send_message("g", "c", reply_to=robot)
        await client.users.send_message("u", "d", reply_to=clicked)
        await client.groups.send_message("g", "e", reply_to=clicked)

    assert [(body.get("event_id"), body.get("msg_seq")) for _, body in platform.requests] == [
        ("FRIEND_ADD:1", 1),
        ("FRIEND_ADD:1", 2),
        ("GROUP_ADD_ROBOT:2", 1),
        ("INTERACTION_CREATE:3", 1),
        ("INTERACTION_CREATE:3", 2),
    ]
    assert all("msg_id" not in body for _, body in platform.requests)


async def test_failed_event_reply_still_uses_up_its_msg_seq() -> None:
    platform = Platform()
    friend = with_event_id(FriendAdded(), "FRIEND_ADD:1")

    async with client_for(platform) as client:
        platform.fail = True
        with pytest.raises(pyqbot.APIError):
            await client.users.send_message("u", "a", reply_to=friend)
        platform.fail = False
        await client.users.send_message("u", "b", reply_to=friend)

    assert [body["msg_seq"] for _, body in platform.requests] == [1, 2]


async def test_event_without_an_event_id_cannot_be_replied_to() -> None:
    platform = Platform()
    friend = FriendAdded()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match="FriendAdded 没有事件 ID"):
            await client.users.send_message("u", "a", reply_to=friend)
        bind_event_id(friend, "FRIEND_ADD:1")
        await client.users.send_message("u", "b", reply_to=friend)

    # 没发出去的那次不占用 msg_seq。
    assert platform.requests[0][1]["msg_seq"] == 1


def test_event_id_is_hidden_from_the_fields() -> None:
    event = Ping(content="hi")
    assert event.event_id is None

    bind_event_id(event, "PING:1")

    assert event.event_id == "PING:1"
    assert event == Ping(content="hi")
    assert event.to_dict() == {"content": "hi"}
    assert "PING:1" not in repr(event)


def test_reply_targets_say_which_scene_they_belong_to() -> None:
    assert isinstance(c2c(), pyqbot.C2CReplyTarget)
    assert not isinstance(c2c(), pyqbot.GroupReplyTarget)
    message = pyqbot.GroupAtMessage(
        id="m", group_openid="g", author=pyqbot.GroupMessageAuthor(member_openid="member")
    )
    assert isinstance(message, pyqbot.GroupReplyTarget)
    assert not isinstance(message, pyqbot.C2CReplyTarget)


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


# ---- 解码 ----


def test_message_events_declare_their_name_and_intent() -> None:
    assert (pyqbot.C2CMessage.event_name, pyqbot.C2CMessage.intent) == (
        "C2C_MESSAGE_CREATE",
        pyqbot.Intents.GROUP_AND_C2C_EVENT,
    )
    assert (pyqbot.GroupAtMessage.event_name, pyqbot.GroupAtMessage.intent) == (
        "GROUP_AT_MESSAGE_CREATE",
        pyqbot.Intents.GROUP_AND_C2C_EVENT,
    )
    assert "event_name" not in pyqbot.C2CMessage.__struct_fields__


def test_real_c2c_message_decodes() -> None:
    message = c2c_sample().decode_data(pyqbot.C2CMessage)

    assert message.id == "ROBOT1.0_fake-message-id"
    assert message.content == "你好"
    assert message.user_openid == "0123456789ABCDEF0123456789ABCDEF"
    assert message.author == pyqbot.C2CUser(
        id="0123456789ABCDEF0123456789ABCDEF",
        user_openid="0123456789ABCDEF0123456789ABCDEF",
        username="测试用户",
        bot=False,
        union_openid="",
        avatar="https://example.invalid/avatar.png",
    )
    assert message.timestamp is not None
    assert message.timestamp.utcoffset() == timedelta(hours=8)
    assert message.timestamp == datetime(2026, 11, 16, 11, 55, 42, tzinfo=UTC8)
    assert message.message_type == pyqbot.ReceivedMessageType.TEXT
    assert message.message_scene is not None
    assert message.message_scene.ext == ("msg_idx=REFIDX_fake",)
    assert (message.attachments, message.msg_elements, message.ark_data) == ((), (), None)


def test_group_message_from_the_official_examples_decodes() -> None:
    text = dispatch_of("GROUP_AT_MESSAGE_CREATE", GROUP_TEXT).decode_data(pyqbot.GroupAtMessage)
    image = dispatch_of("GROUP_AT_MESSAGE_CREATE", GROUP_IMAGE).decode_data(pyqbot.GroupAtMessage)
    quote = dispatch_of("GROUP_AT_MESSAGE_CREATE", GROUP_QUOTE).decode_data(pyqbot.GroupAtMessage)

    assert text.group_openid == "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5"
    assert text.member_openid == "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4"
    assert (text.author.username, text.author.member_role) == ("小明", "member")
    assert text.content == " /今日天气 "  # 原样保留，不替用户 strip
    assert text.timestamp == datetime(2026, 7, 21, 10, 0, tzinfo=UTC8)
    assert text.mentions == ()
    assert image.attachments == (
        pyqbot.MessageAttachment(
            content_type="image/jpeg",
            filename="photo.jpg",
            url="https://multimedia.nt.qq.com.cn/download?appid=xxx&fileid=xxx&rkey=xxx&spec=0",
            width=1920,
            height=1080,
            size=256000,
        ),
    )
    assert quote.message_type == pyqbot.ReceivedMessageType.QUOTE
    assert quote.msg_elements[0].content == "=== 消息 1 ===\n[消息内容] 今天的学习计划已完成"


def test_msg_idx_is_read_from_the_message_scene() -> None:
    group = dispatch_of("GROUP_AT_MESSAGE_CREATE", GROUP_TEXT).decode_data(pyqbot.GroupAtMessage)

    assert c2c_sample().decode_data(pyqbot.C2CMessage).msg_idx == "REFIDX_fake"
    assert group.msg_idx == "REFIDX_xxxxxxxxxxxxxxx=="
    assert c2c().msg_idx is None
    scene = pyqbot.C2CMessage(
        id="m",
        author=pyqbot.C2CUser(user_openid="u"),
        message_scene=MessageScene(ext=("msg_idx", "ref_msg_idx=REFIDX_old", "msg_idx=a=b")),
    )
    assert scene.msg_idx == "a=b"
    no_index = pyqbot.C2CMessage(
        id="m",
        author=pyqbot.C2CUser(user_openid="u"),
        message_scene=MessageScene(ext=("ref_msg_idx=REFIDX_old",)),
    )
    assert no_index.msg_idx is None


def test_c2c_ark_and_quote_examples_decode() -> None:
    # autogen/event/c2c_message_create.md 的示例 2、3（节选）。
    ark = {
        "id": "m",
        "author": {"id": "B", "user_openid": "B"},
        "message_type": 3,
        "ark_data": {"ark_type": "miniapp", "fields": {"title": "打卡", "tags": ["a"]}},
        "msg_elements": [
            {
                "msg_idx": "REFIDX_a",
                "message_type": 103,
                "author": {"user_openid": "B"},
                "msg_elements": [{"content": "更早的消息"}],
            }
        ],
    }
    message = dispatch_of("C2C_MESSAGE_CREATE", ark).decode_data(pyqbot.C2CMessage)

    assert message.message_type == pyqbot.ReceivedMessageType.ARK
    assert message.ark_data is not None
    assert message.ark_data.fields == {"title": "打卡", "tags": ["a"]}
    assert message.content == ""
    element = message.msg_elements[0]
    assert element.author is not None
    assert element.author.user_openid == "B"
    assert element.msg_elements[0].content == "更早的消息"


def test_secondary_fields_of_the_wrong_type_fall_back_to_defaults() -> None:
    data = {
        **GROUP_TEXT,
        "content": 42,
        "timestamp": 1700000000,
        "message_type": "text",
        "message_scene": {"source": 1, "ext": "msg_idx=1"},
        "attachments": [{"url": 1, "size": "大"}],
        "mentions": "nobody",
    }
    message = dispatch_of("GROUP_AT_MESSAGE_CREATE", data).decode_data(pyqbot.GroupAtMessage)

    assert message.id == "ROBOT1.0_x"
    assert message.group_openid == GROUP_TEXT["group_openid"]
    assert message.member_openid == "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4"
    assert (message.content, message.timestamp, message.message_type) == ("", None, None)
    # 元组里的模型逐个清理：附件只丢掉坏字段；mentions 本身不是列表，退回默认值。
    assert message.attachments == (pyqbot.MessageAttachment(),)
    assert message.mentions == ()
    assert message.message_scene is not None
    assert (message.message_scene.source, message.message_scene.ext) == (None, ())


def test_bad_fields_inside_attachments_and_elements_drop_only_themselves() -> None:
    # 评审给出的例子：坏的只有 width 与 author.username。
    data = {
        "id": "m",
        "author": {"user_openid": "u"},
        "attachments": [
            {"url": "https://example.invalid/1", "width": "bad"},
            {"url": "https://example.invalid/2"},
        ],
        "msg_elements": [{"content": "有效引用正文", "author": {"username": 42}}],
    }
    message = dispatch_of("C2C_MESSAGE_CREATE", data).decode_data(pyqbot.C2CMessage)

    assert message.attachments == (
        pyqbot.MessageAttachment(url="https://example.invalid/1"),
        pyqbot.MessageAttachment(url="https://example.invalid/2"),
    )
    [element] = message.msg_elements
    assert element.content == "有效引用正文"
    assert element.author is not None
    assert element.author.username is None


def test_unknown_message_type_and_fields_are_tolerated() -> None:
    data = {"id": "m", "author": {"user_openid": "u", "new": 1}, "message_type": 999, "new": {}}
    message = dispatch_of("C2C_MESSAGE_CREATE", data).decode_data(pyqbot.C2CMessage)

    assert message.message_type == 999
    assert message.message_type is not None
    assert message.message_type.name == "UNKNOWN"


@pytest.mark.parametrize(
    ("event_type", "data"),
    [
        (pyqbot.C2CMessage, {"id": "m", "content": "没有发送者，无法回复"}),
        (pyqbot.C2CMessage, {"id": "m", "author": {"id": "u"}}),
        (pyqbot.C2CMessage, {"author": {"user_openid": "u"}}),
        (pyqbot.GroupAtMessage, {"id": "m", "author": {"member_openid": "u"}}),
        # 与单聊一样，发送者是必填的：没有它就不知道是谁发的
        (pyqbot.GroupAtMessage, {"id": "m", "group_openid": "g", "author": "不是对象"}),
        (pyqbot.GroupAtMessage, {"id": "m", "group_openid": "g", "author": {"id": "x"}}),
    ],
)
def test_message_without_what_reply_needs_is_rejected(
    event_type: type[pyqbot.C2CMessage | pyqbot.GroupAtMessage], data: object
) -> None:
    with pytest.raises(PayloadError):
        dispatch_of(event_type.event_name, data).decode_data(event_type)


# ---- reply() ----


async def test_c2c_reply_answers_the_sender_with_increasing_msg_seq() -> None:
    platform = Platform()
    message = c2c_sample().decode_data(pyqbot.C2CMessage)

    async with client_for(platform) as client:
        bind_client(message, client)
        sent = await message.reply("一")
        await message.reply("二")

    assert sent.id == "ROBOT1.0_sent"
    assert platform.requests == [
        (
            "/v2/users/0123456789ABCDEF0123456789ABCDEF/messages",
            {"msg_type": 0, "content": "一", "msg_id": "ROBOT1.0_fake-message-id", "msg_seq": 1},
        ),
        (
            "/v2/users/0123456789ABCDEF0123456789ABCDEF/messages",
            {"msg_type": 0, "content": "二", "msg_id": "ROBOT1.0_fake-message-id", "msg_seq": 2},
        ),
    ]


async def test_group_reply_answers_the_group() -> None:
    platform = Platform()
    message = dispatch_of("GROUP_AT_MESSAGE_CREATE", GROUP_TEXT).decode_data(pyqbot.GroupAtMessage)

    async with client_for(platform) as client:
        bind_client(message, client)
        await message.reply("晴")
        await message.reply("多云")

    assert platform.requests == [
        (
            "/v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages",
            {"msg_type": 0, "content": "晴", "msg_id": "ROBOT1.0_x", "msg_seq": 1},
        ),
        (
            "/v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages",
            {"msg_type": 0, "content": "多云", "msg_id": "ROBOT1.0_x", "msg_seq": 2},
        ),
    ]


async def test_reply_accepts_the_same_content_as_send_message() -> None:
    platform = Platform()
    private = c2c_sample().decode_data(pyqbot.C2CMessage)
    group = dispatch_of("GROUP_AT_MESSAGE_CREATE", GROUP_TEXT).decode_data(pyqbot.GroupAtMessage)
    keyboard = pyqbot.Keyboard(id="kb")
    card = pyqbot.Card(title="t", description="d", url="https://a", pic_url="https://b")

    async with client_for(platform) as client:
        bind_client(private, client)
        bind_client(group, client)
        await private.reply(markdown="**hi**", keyboard=keyboard, quote=private)
        await private.reply("图", media=pyqbot.Media(file_info="F"))
        await group.reply(card=card, quote=group)

    assert [body for _, body in platform.requests] == [
        {
            "msg_type": 2,
            "markdown": {"content": "**hi**"},
            "keyboard": {"id": "kb"},
            "message_reference": {"message_id": "REFIDX_fake"},
            "msg_id": "ROBOT1.0_fake-message-id",
            "msg_seq": 1,
        },
        {
            "msg_type": 7,
            "content": "图",
            "media": {"file_info": "F"},
            "msg_id": "ROBOT1.0_fake-message-id",
            "msg_seq": 2,
        },
        {
            "msg_type": 8,
            "card": {"type": "tuwen", "content": card.to_dict()},
            "message_reference": {"message_id": "REFIDX_xxxxxxxxxxxxxxx=="},
            "msg_id": "ROBOT1.0_x",
            "msg_seq": 1,
        },
    ]


async def test_send_typing_on_a_message_is_a_passive_reply() -> None:
    platform = Platform()
    message = c2c("m", "u")

    async with client_for(platform) as client:
        bind_client(message, client)
        await message.send_typing(seconds=5)
        await message.reply("好了")

    assert platform.requests[0] == (
        "/v2/users/u/messages",
        {
            "msg_type": 6,
            "input_notify": {"input_type": 1, "input_second": 5},
            "msg_id": "m",
            "msg_seq": 1,
        },
    )
    assert platform.replies()[1] == ("m", 2)


@pytest.mark.parametrize(
    "message",
    [
        c2c(),
        pyqbot.GroupAtMessage(
            id="m", group_openid="g", author=pyqbot.GroupMessageAuthor(member_openid="member")
        ),
    ],
    ids=["c2c", "group"],
)
async def test_reply_on_an_unbound_message_raises(
    message: pyqbot.C2CMessage | pyqbot.GroupAtMessage,
) -> None:
    with pytest.raises(RuntimeError, match="没有绑定 Client"):
        await message.reply("收到")
