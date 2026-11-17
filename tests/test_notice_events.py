# pyright: reportUnnecessaryTypeIgnoreComment=true
# 打开上面这条，下面「pyright 拒绝」的那几行若不再报错，pyright 就会报「多余的 ignore」。
"""单聊、群聊的通知类事件与全量群消息：解码、被动回复与注册。"""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx2
import pytest

import pyqbot
from pyqbot._errors import PayloadError
from pyqbot._gateway.payload import GatewayPayload, decode_payload
from pyqbot._models.event import Event, bind_client, bind_event_id

UTC8 = timezone(timedelta(hours=8))
HANG_GUARD = 5  # 秒：并发测试回归时应失败而不是挂起
OPENID = "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4"
GROUP = "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5"
MEMBER = "C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5F6"

# 以下取自 autogen/event/ 下各页的事件示例。
FRIEND_ADD = {
    "openid": OPENID,
    "timestamp": 1784570600,
    "scene": 2003,
    "scene_param": "callback_abc123",
    "author": {"union_openid": "DB85A74E07BA08B5B44CD9ED332FCBD2"},
}
FRIEND_DEL = {"openid": OPENID, "timestamp": 1784570524}
GROUP_ROBOT = {"group_openid": GROUP, "op_member_openid": MEMBER, "timestamp": 1784570534}
GROUP_MEMBER_REMOVE = {
    "timestamp": 1784276759,
    "group_openid": GROUP,
    "member_openid": MEMBER,
    "user_openid": MEMBER,
}
JOIN_SELF = {
    "group_openid": "30584554AA2BF4E72BD3B8F27A70339D",
    "join_request_id": "AVKiFWpdy0",
    "member_openid": "FE003FAF76C4817251FDC128A16753BB",
    "username": "痞孓小光光╮hw灰",
    "apply_at": "2026-08-05T16:21:40+08:00",
    "apply_source": "self_apply",
    "verify_info": {"method": "verify_message", "verify_message": "就快乐了"},
}
JOIN_INVITED = {
    "group_openid": "30584554AA2BF4E72BD3B8F27A70339D",
    "join_request_id": "AZj4L11PQ3",
    "member_openid": "DE538D0B23260BFEC30EA4A17C3A71B1",
    "username": "吓唬",
    "apply_at": "2026-08-05T16:36:32+08:00",
    "apply_source": "invited",
    "invited_by": "FE003FAF76C4817251FDC128A16753BB",
}
JOIN_AUTO = {**JOIN_SELF, "auto_approved": {"strategy_id": "st_7c0b77d442"}}
SUBSCRIBE = {
    "openid": OPENID,
    "result": [
        {
            "template_id": 10001,
            "custom_template_id": "tpl_abc123",
            "op": 1,
            "subscribe_id": "sub_def456",
            "subscribe_ts": 1784276820,
            "update_ts": 1784276820,
        },
        {"template_id": 10002, "op": 2, "subscribe_id": "sub_ghi012"},
    ],
}
GROUP_ANY = {
    "id": "ROBOT1.0_any",
    "author": {"id": MEMBER, "member_openid": MEMBER, "member_role": "member", "username": "小明"},
    "content": f"<@{MEMBER}> 早上好 <@all>",
    "group_openid": GROUP,
    "message_type": 0,
    "timestamp": "2026-07-21T08:00:00+08:00",
    "mentions": [{"member_openid": MEMBER}],
    "message_scene": {"source": "default", "ext": ["msg_idx=REFIDX_any=="]},
}


def dispatch_of(event_name: str, data: object, event_id: str | None = None) -> GatewayPayload:
    frame = {"op": 0, "s": 1, "t": event_name, "d": data} | ({"id": event_id} if event_id else {})
    return decode_payload(json.dumps(frame))


def decoded[E: Event](event_type: type[E], data: object, event_id: str | None = None) -> E:
    event = dispatch_of(event_type.event_name, data).decode_data(event_type)
    bind_event_id(event, event_id)
    return event


class Platform:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": "t", "expires_in": "7200"})
        self.requests.append((request.url.path, json.loads(request.content)))
        return httpx2.Response(200, json={"id": "ROBOT1.0_sent"})


@asynccontextmanager
async def client_for(platform: Platform) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client("app-id", "app-secret", http_client=http_client) as client,
    ):
        yield client


# ---- 事件名与 Intent ----


@pytest.mark.parametrize(
    ("event_type", "event_name", "intent"),
    [
        (pyqbot.FriendAdd, "FRIEND_ADD", pyqbot.Intents.GROUP_AND_C2C_EVENT),
        (pyqbot.FriendDel, "FRIEND_DEL", pyqbot.Intents.GROUP_AND_C2C_EVENT),
        (pyqbot.C2CMsgReject, "C2C_MSG_REJECT", pyqbot.Intents.GROUP_AND_C2C_EVENT),
        (pyqbot.C2CMsgReceive, "C2C_MSG_RECEIVE", pyqbot.Intents.GROUP_AND_C2C_EVENT),
        (pyqbot.GroupAddRobot, "GROUP_ADD_ROBOT", pyqbot.Intents.GROUP_AND_C2C_EVENT),
        (pyqbot.GroupDelRobot, "GROUP_DEL_ROBOT", pyqbot.Intents.GROUP_AND_C2C_EVENT),
        (pyqbot.GroupMsgReject, "GROUP_MSG_REJECT", pyqbot.Intents.GROUP_AND_C2C_EVENT),
        (pyqbot.GroupMsgReceive, "GROUP_MSG_RECEIVE", pyqbot.Intents.GROUP_AND_C2C_EVENT),
        (pyqbot.GroupMemberAdd, "GROUP_MEMBER_ADD", pyqbot.Intents.GROUP_MEMBER_EVENT),
        (pyqbot.GroupMemberRemove, "GROUP_MEMBER_REMOVE", pyqbot.Intents.GROUP_MEMBER_EVENT),
        (pyqbot.GroupJoinRequest, "GROUP_JOIN_REQUEST", pyqbot.Intents.GROUP_MEMBER_EVENT),
        (pyqbot.GroupMessage, "GROUP_MESSAGE_CREATE", pyqbot.Intents.GROUP_AND_C2C_EVENT),
        (
            pyqbot.SubscribeMessageStatus,
            "SUBSCRIBE_MESSAGE_STATUS",
            pyqbot.Intents.GROUP_AND_C2C_EVENT,
        ),
    ],
)
def test_events_declare_their_name_and_intent(
    event_type: type[Event], event_name: str, intent: pyqbot.Intents
) -> None:
    assert (event_type.event_name, event_type.intent) == (event_name, intent)


def test_only_events_the_send_api_lists_can_be_replied_to_with_event_id() -> None:
    # 发消息接口页 event_id 一行列出的事件。
    c2c = {pyqbot.FriendAdd, pyqbot.C2CMsgReceive}
    group = {pyqbot.GroupAddRobot, pyqbot.GroupMsgReceive}
    others = {
        pyqbot.FriendDel,
        pyqbot.C2CMsgReject,
        pyqbot.GroupDelRobot,
        pyqbot.GroupMsgReject,
        pyqbot.GroupMemberAdd,
        pyqbot.GroupMemberRemove,
        pyqbot.GroupJoinRequest,
        pyqbot.SubscribeMessageStatus,
    }

    assert all(issubclass(t, pyqbot.C2CReplyTarget) for t in c2c)
    assert all(issubclass(t, pyqbot.GroupReplyTarget) for t in group)
    assert not any(issubclass(t, pyqbot.GroupReplyTarget) for t in c2c)
    assert not any(issubclass(t, pyqbot.C2CReplyTarget) for t in group)
    assert not any(issubclass(t, (pyqbot.C2CReplyTarget, pyqbot.GroupReplyTarget)) for t in others)


# ---- 解码 ----


def test_friend_events_decode() -> None:
    added = decoded(pyqbot.FriendAdd, FRIEND_ADD)
    removed = decoded(pyqbot.FriendDel, FRIEND_DEL)

    assert added.openid == OPENID
    assert added.timestamp == 1784570600
    assert added.scene == pyqbot.FriendAddScene.LINK_INSIDE
    assert added.scene_param == "callback_abc123"
    assert added.author.union_openid == "DB85A74E07BA08B5B44CD9ED332FCBD2"
    assert added.short_code is None
    assert added.to_dict() == {**FRIEND_ADD, "short_code": None}
    # FRIEND_DEL 的示例没有 author：照样能用，各字段为 None。
    assert (removed.openid, removed.timestamp, removed.author.union_openid) == (
        OPENID,
        1784570524,
        None,
    )


def test_friend_add_scene_tolerates_unknown_values_and_bad_types() -> None:
    unknown = decoded(pyqbot.FriendAdd, {**FRIEND_ADD, "scene": 3001, "short_code": "abc"})
    bad = decoded(pyqbot.FriendAdd, {"openid": OPENID, "scene": "1001", "scene_param": None})

    assert unknown.scene == 3001
    assert unknown.scene is not None
    assert unknown.scene.name == "UNKNOWN"
    assert unknown.short_code == "abc"
    assert (bad.scene, bad.scene_param, bad.timestamp) == (None, "", None)


def test_c2c_switch_events_decode() -> None:
    data = {"openid": OPENID, "timestamp": 1784570599}

    assert decoded(pyqbot.C2CMsgReject, data) == pyqbot.C2CMsgReject(
        openid=OPENID, timestamp=1784570599
    )
    assert decoded(pyqbot.C2CMsgReceive, data).openid == OPENID


@pytest.mark.parametrize(
    "event_type",
    [pyqbot.GroupAddRobot, pyqbot.GroupDelRobot, pyqbot.GroupMsgReject, pyqbot.GroupMsgReceive],
)
def test_group_robot_events_decode(
    event_type: type[
        pyqbot.GroupAddRobot | pyqbot.GroupDelRobot | pyqbot.GroupMsgReject | pyqbot.GroupMsgReceive
    ],
) -> None:
    event = decoded(event_type, GROUP_ROBOT)

    assert (event.group_openid, event.op_member_openid, event.timestamp) == (
        GROUP,
        MEMBER,
        1784570534,
    )


def test_group_member_events_decode() -> None:
    added = decoded(pyqbot.GroupMemberAdd, {**GROUP_MEMBER_REMOVE, "user_openid": None})
    removed = decoded(pyqbot.GroupMemberRemove, GROUP_MEMBER_REMOVE)
    anonymous = decoded(pyqbot.GroupMemberRemove, {"group_openid": GROUP, "member_openid": MEMBER})

    assert (added.group_openid, added.member_openid, added.timestamp) == (
        GROUP,
        MEMBER,
        1784276759,
    )
    assert removed.user_openid == MEMBER
    assert anonymous.user_openid is None


def test_join_request_examples_decode() -> None:
    applied = decoded(pyqbot.GroupJoinRequest, JOIN_SELF)
    invited = decoded(pyqbot.GroupJoinRequest, JOIN_INVITED)
    approved = decoded(pyqbot.GroupJoinRequest, JOIN_AUTO)

    assert applied.join_request_id == "AVKiFWpdy0"
    assert applied.apply_at == datetime(2026, 8, 5, 16, 21, 40, tzinfo=UTC8)
    assert applied.apply_source == "self_apply"
    assert applied.verify_info is not None
    assert (applied.verify_info.method, applied.verify_info.verify_message) == (
        "verify_message",
        "就快乐了",
    )
    assert applied.auto_approved is None
    assert (invited.apply_source, invited.invited_by) == (
        "invited",
        "FE003FAF76C4817251FDC128A16753BB",
    )
    assert invited.verify_info is None
    assert approved.auto_approved is not None
    assert approved.auto_approved.strategy_id == "st_7c0b77d442"


def test_join_request_event_is_the_listed_request_plus_the_group() -> None:
    event = decoded(pyqbot.GroupJoinRequest, JOIN_SELF)
    listed = pyqbot.GroupJoinRequestInfo(join_request_id="r", member_openid="m")

    assert isinstance(event, pyqbot.GroupJoinRequestInfo)
    assert set(event.to_dict()) == set(listed.to_dict()) | {"group_openid", "auto_approved"}


def test_join_request_string_values_decode_to_enums() -> None:
    applied = decoded(pyqbot.GroupJoinRequest, JOIN_SELF)
    invited = decoded(pyqbot.GroupJoinRequest, JOIN_INVITED)
    unknown = decoded(
        pyqbot.GroupJoinRequest,
        {**JOIN_SELF, "apply_source": "scan", "verify_info": {"method": "captcha"}},
    )
    wrong = decoded(
        pyqbot.GroupJoinRequest, {**JOIN_SELF, "apply_source": 1, "verify_info": {"method": 2}}
    )

    assert applied.apply_source == pyqbot.JoinRequestSource.SELF_APPLY
    assert invited.apply_source == pyqbot.JoinRequestSource.INVITED
    assert applied.verify_info is not None
    assert applied.verify_info.method == pyqbot.JoinRequestVerifyMethod.VERIFY_MESSAGE
    assert unknown.apply_source == "scan"
    assert unknown.apply_source is not None
    assert unknown.apply_source.name == "UNKNOWN"
    assert unknown.verify_info is not None
    assert unknown.verify_info.method == "captcha"
    assert wrong.apply_source is None
    assert wrong.verify_info is not None
    assert wrong.verify_info.method is None


def test_member_role_decodes_to_an_enum() -> None:
    quote = {
        "msg_elements": [{"author": {"member_openid": MEMBER, "member_role": "owner"}}],
    }
    known = decoded(pyqbot.GroupMessage, {**GROUP_ANY, **quote})
    unknown = decoded(
        pyqbot.GroupMessage,
        {**GROUP_ANY, "author": {"member_openid": MEMBER, "member_role": "guest"}},
    )
    wrong = decoded(
        pyqbot.GroupMessage, {**GROUP_ANY, "author": {"member_openid": MEMBER, "member_role": 1}}
    )

    assert known.author.member_role == pyqbot.GroupMemberRole.MEMBER
    assert known.author.member_role == "member"  # StrEnum：与原字符串比较照样成立
    element_author = known.msg_elements[0].author
    assert element_author is not None
    assert element_author.member_role == pyqbot.GroupMemberRole.OWNER
    assert unknown.author.member_role == "guest"
    assert unknown.author.member_role is not None
    assert unknown.author.member_role.name == "UNKNOWN"
    assert wrong.author.member_role is None


def test_join_request_qa_list_decodes_and_bad_fields_drop_alone() -> None:
    data = {
        **JOIN_SELF,
        "apply_at": 1754382100,  # 不是 RFC3339：退回默认值，不让整条丢掉
        "bot": False,
        "verify_info": {
            "method": "admin_review_qa",
            "review_qa_list": [{"question": "暗号？", "answer": "芝麻开门"}, {"question": 1}],
        },
    }
    request = decoded(pyqbot.GroupJoinRequest, data)

    assert request.apply_at is None
    assert request.bot is False
    assert request.verify_info is not None
    assert [(qa.question, qa.answer) for qa in request.verify_info.review_qa_list] == [
        ("暗号？", "芝麻开门"),
        ("", ""),
    ]


def test_subscribe_status_decodes() -> None:
    status = decoded(pyqbot.SubscribeMessageStatus, SUBSCRIBE)
    empty = decoded(pyqbot.SubscribeMessageStatus, {"group_openid": GROUP})

    assert (status.openid, status.group_openid) == (OPENID, None)
    first, second = status.result
    assert first == pyqbot.SubscribeResult(
        template_id=10001,
        custom_template_id="tpl_abc123",
        op=pyqbot.SubscribeOp.ACCEPT,
        subscribe_id="sub_def456",
        subscribe_ts=1784276820,
        update_ts=1784276820,
    )
    assert second.op == pyqbot.SubscribeOp.REJECT
    assert (empty.openid, empty.group_openid, empty.result) == (None, GROUP, ())


@pytest.mark.parametrize(
    ("event_type", "data"),
    [
        (pyqbot.FriendAdd, {"timestamp": 1}),
        (pyqbot.C2CMsgReceive, {"openid": 1}),
        (pyqbot.GroupAddRobot, {"op_member_openid": MEMBER}),
        (pyqbot.GroupMemberAdd, {"group_openid": GROUP}),
        (pyqbot.GroupJoinRequest, {"group_openid": GROUP}),
        (pyqbot.GroupJoinRequest, {"group_openid": GROUP, "join_request_id": "r"}),
        (pyqbot.GroupMessage, {"id": "m"}),
    ],
)
def test_events_without_what_the_sdk_needs_are_rejected(
    event_type: type[Event], data: object
) -> None:
    with pytest.raises(PayloadError):
        dispatch_of(event_type.event_name, data).decode_data(event_type)


def test_group_any_message_keeps_mentions_in_the_content() -> None:
    message = decoded(pyqbot.GroupMessage, GROUP_ANY)

    assert message.content == f"<@{MEMBER}> 早上好 <@all>"
    assert message.member_openid == MEMBER
    assert message.mentions[0].member_openid == MEMBER
    assert message.msg_idx == "REFIDX_any=="
    assert message.timestamp == datetime(2026, 7, 21, 8, 0, tzinfo=UTC8)
    # 与 @机器人 的消息字段相同，但不是它。
    assert not isinstance(message, pyqbot.GroupAtMessage)
    at = pyqbot.GroupAtMessage(
        id="m", group_openid="g", author=pyqbot.GroupMessageAuthor(member_openid="member")
    )
    assert isinstance(at, pyqbot.GroupMessage)


# ---- 被动回复 ----


async def test_c2c_events_reply_to_the_user_with_their_event_id() -> None:
    platform = Platform()
    added = decoded(pyqbot.FriendAdd, FRIEND_ADD, "FRIEND_ADD:1")
    opened = decoded(pyqbot.C2CMsgReceive, {"openid": "u2"}, "C2C_MSG_RECEIVE:2")

    async with client_for(platform) as client:
        bind_client(added, client)
        bind_client(opened, client)
        sent = await added.reply("欢迎")
        await added.reply(markdown="**再次欢迎**")
        await opened.reply("谢谢打开")

    assert sent.id == "ROBOT1.0_sent"
    assert platform.requests == [
        (
            f"/v2/users/{OPENID}/messages",
            {"msg_type": 0, "content": "欢迎", "event_id": "FRIEND_ADD:1", "msg_seq": 1},
        ),
        (
            f"/v2/users/{OPENID}/messages",
            {
                "msg_type": 2,
                "markdown": {"content": "**再次欢迎**"},
                "event_id": "FRIEND_ADD:1",
                "msg_seq": 2,
            },
        ),
        (
            "/v2/users/u2/messages",
            {"msg_type": 0, "content": "谢谢打开", "event_id": "C2C_MSG_RECEIVE:2", "msg_seq": 1},
        ),
    ]


async def test_group_events_reply_to_the_group_with_their_event_id() -> None:
    platform = Platform()
    joined = decoded(pyqbot.GroupAddRobot, GROUP_ROBOT, "GROUP_ADD_ROBOT:1")
    opened = decoded(pyqbot.GroupMsgReceive, GROUP_ROBOT, "GROUP_MSG_RECEIVE:2")

    async with client_for(platform) as client:
        bind_client(joined, client)
        bind_client(opened, client)
        await joined.reply("大家好")
        await opened.reply("通知已打开", quote="REFIDX_q")

    assert platform.requests == [
        (
            f"/v2/groups/{GROUP}/messages",
            {"msg_type": 0, "content": "大家好", "event_id": "GROUP_ADD_ROBOT:1", "msg_seq": 1},
        ),
        (
            f"/v2/groups/{GROUP}/messages",
            {
                "msg_type": 0,
                "content": "通知已打开",
                "message_reference": {"message_id": "REFIDX_q"},
                "event_id": "GROUP_MSG_RECEIVE:2",
                "msg_seq": 1,
            },
        ),
    ]


async def test_reply_without_an_event_id_is_rejected_before_sending() -> None:
    platform = Platform()
    added = decoded(pyqbot.FriendAdd, FRIEND_ADD)
    joined = decoded(pyqbot.GroupAddRobot, GROUP_ROBOT)

    async with client_for(platform) as client:
        bind_client(added, client)
        bind_client(joined, client)
        with pytest.raises(ValueError, match="FriendAdd 没有事件 ID"):
            await added.reply("欢迎")
        with pytest.raises(ValueError, match="GroupAddRobot 没有事件 ID"):
            await joined.reply("大家好")

    assert platform.requests == []


@pytest.mark.parametrize(
    "event",
    [
        pyqbot.FriendAdd(openid="u"),
        pyqbot.C2CMsgReceive(openid="u"),
        pyqbot.GroupAddRobot(group_openid="g"),
        pyqbot.GroupMsgReceive(group_openid="g"),
    ],
    ids=["friend_add", "c2c_msg_receive", "group_add_robot", "group_msg_receive"],
)
async def test_reply_on_an_unbound_event_raises(
    event: pyqbot.FriendAdd | pyqbot.C2CMsgReceive | pyqbot.GroupAddRobot | pyqbot.GroupMsgReceive,
) -> None:
    with pytest.raises(RuntimeError, match="没有绑定 Client"):
        await event.reply("收到")


async def test_group_any_message_replies_and_quotes_like_a_group_message() -> None:
    platform = Platform()
    message = decoded(pyqbot.GroupMessage, GROUP_ANY)

    async with client_for(platform) as client:
        bind_client(message, client)
        await message.reply("早", quote=message)
        await client.groups.send_message(GROUP, "引用", quote=message)

    assert platform.requests == [
        (
            f"/v2/groups/{GROUP}/messages",
            {
                "msg_type": 0,
                "content": "早",
                "message_reference": {"message_id": "REFIDX_any=="},
                "msg_id": "ROBOT1.0_any",
                "msg_seq": 1,
            },
        ),
        (
            f"/v2/groups/{GROUP}/messages",
            {"msg_type": 0, "content": "引用", "message_reference": {"message_id": "REFIDX_any=="}},
        ),
    ]


async def test_group_any_message_can_be_recalled() -> None:
    paths: list[tuple[str, str]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": "t", "expires_in": "7200"})
        paths.append((request.method, request.url.path))
        return httpx2.Response(200)

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(handle)) as http_client,
        pyqbot.Client("app-id", "app-secret", http_client=http_client) as client,
    ):
        await client.groups.recall_message(GROUP, decoded(pyqbot.GroupMessage, GROUP_ANY))

    assert paths == [("DELETE", f"/v2/groups/{GROUP}/messages/ROBOT1.0_any")]


async def wrong_scene_is_rejected_by_pyright(client: pyqbot.Client) -> None:
    """不运行，只给 pyright 看：事件只能回复到它所属的场景，不能回复的事件不能作为 `reply_to`。"""
    added = pyqbot.FriendAdd(openid="u")
    joined = pyqbot.GroupAddRobot(group_openid="g")
    await client.groups.send_message("g", "x", reply_to=added)  # pyright: ignore[reportArgumentType]
    await client.users.send_message("u", "x", reply_to=joined)  # pyright: ignore[reportArgumentType]
    await client.users.send_message("u", "x", reply_to=pyqbot.FriendDel(openid="u"))  # pyright: ignore[reportArgumentType]
    group = pyqbot.GroupMessage(
        id="m", group_openid="g", author=pyqbot.GroupMessageAuthor(member_openid="member")
    )
    await added.reply("x", quote=group)  # pyright: ignore[reportArgumentType]


# ---- 注册与分发 ----


async def test_each_event_has_a_decorator_that_derives_its_intent() -> None:
    async def on_friend_add(event: pyqbot.FriendAdd) -> None: ...
    async def on_friend_del(event: pyqbot.FriendDel) -> None: ...
    async def on_c2c_reject(event: pyqbot.C2CMsgReject) -> None: ...
    async def on_c2c_receive(event: pyqbot.C2CMsgReceive) -> None: ...
    async def on_robot_add(event: pyqbot.GroupAddRobot) -> None: ...
    async def on_robot_del(event: pyqbot.GroupDelRobot) -> None: ...
    async def on_group_reject(event: pyqbot.GroupMsgReject) -> None: ...
    async def on_group_receive(event: pyqbot.GroupMsgReceive) -> None: ...
    async def on_member_add(event: pyqbot.GroupMemberAdd) -> None: ...
    async def on_member_remove(event: pyqbot.GroupMemberRemove) -> None: ...
    async def on_join(event: pyqbot.GroupJoinRequest) -> None: ...
    async def on_any(event: pyqbot.GroupMessage) -> None: ...
    async def on_subscribe(event: pyqbot.SubscribeMessageStatus) -> None: ...

    async with pyqbot.Bot("app-id", "app-secret") as bot:
        assert bot.on_friend_add(on_friend_add) is on_friend_add
        assert bot.on_friend_del(on_friend_del) is on_friend_del
        assert bot.on_c2c_msg_reject(on_c2c_reject) is on_c2c_reject
        assert bot.on_c2c_msg_receive(on_c2c_receive) is on_c2c_receive
        assert bot.on_group_add_robot(on_robot_add) is on_robot_add
        assert bot.on_group_del_robot(on_robot_del) is on_robot_del
        assert bot.on_group_msg_reject(on_group_reject) is on_group_reject
        assert bot.on_group_msg_receive(on_group_receive) is on_group_receive
        assert bot.on_group_message(on_any) is on_any
        assert bot.on_subscribe_message_status(on_subscribe) is on_subscribe
        assert bot._resolve_intents() == pyqbot.Intents.GROUP_AND_C2C_EVENT  # pyright: ignore[reportPrivateUsage]

        assert bot.on_group_member_add(on_member_add) is on_member_add
        assert bot.on_group_member_remove(on_member_remove) is on_member_remove
        assert bot.on_group_join_request(on_join) is on_join
        assert bot._resolve_intents() == (  # pyright: ignore[reportPrivateUsage]
            pyqbot.Intents.GROUP_AND_C2C_EVENT | pyqbot.Intents.GROUP_MEMBER_EVENT
        )


async def test_handlers_for_the_wrong_event_are_type_errors() -> None:
    async with pyqbot.Bot("app-id", "app-secret") as bot:

        async def on_at(message: pyqbot.GroupAtMessage) -> None: ...

        async def on_any(message: pyqbot.GroupMessage) -> None: ...

        # 只收 @ 消息的处理函数不能接全量消息；收全量消息的可以两处都注册。
        bot.on_group_message(on_at)  # pyright: ignore[reportArgumentType]
        bot.on_group_at_message(on_any)
        bot.on_friend_add(on_any)  # pyright: ignore[reportArgumentType]


async def test_group_messages_go_only_to_the_decorator_of_their_event_name() -> None:
    seen: list[tuple[str, str]] = []
    done = asyncio.Event()

    def record(decorator: str, message: pyqbot.GroupMessage) -> None:
        seen.append((decorator, type(message).__name__))
        if len(seen) == 2:
            done.set()

    async with pyqbot.Bot("app-id", "app-secret") as bot:

        @bot.on_group_at_message
        async def at(message: pyqbot.GroupAtMessage) -> None:
            record("at", message)

        @bot.on_group_message
        async def every(message: pyqbot.GroupMessage) -> None:
            record("any", message)

        dispatcher = bot._dispatcher  # pyright: ignore[reportPrivateUsage]  代替 Bot.start()
        dispatcher.dispatch(dispatch_of("GROUP_MESSAGE_CREATE", GROUP_ANY), bot)
        dispatcher.dispatch(dispatch_of("GROUP_AT_MESSAGE_CREATE", GROUP_ANY), bot)
        async with asyncio.timeout(HANG_GUARD):
            await done.wait()

    assert sorted(seen) == [("any", "GroupMessage"), ("at", "GroupAtMessage")]


async def test_dispatched_friend_add_replies_with_the_outer_payload_id() -> None:
    platform = Platform()
    replied = asyncio.Event()

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Bot("app-id", "app-secret", http_client=http_client) as bot,
    ):

        @bot.on_friend_add
        async def welcome(event: pyqbot.FriendAdd) -> None:
            await event.reply("欢迎")
            replied.set()

        payload = dispatch_of("FRIEND_ADD", FRIEND_ADD, "FRIEND_ADD:outer")
        bot._dispatcher.dispatch(payload, bot)  # pyright: ignore[reportPrivateUsage]  代替 Bot.start()
        async with asyncio.timeout(HANG_GUARD):
            await replied.wait()

    assert platform.requests[0][1]["event_id"] == "FRIEND_ADD:outer"
