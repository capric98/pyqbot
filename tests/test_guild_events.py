"""频道（guild）的事件与共用模型：解码、场景标记、宽容解码与注册。"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

import pyqbot
from pyqbot._errors import PayloadError
from pyqbot._gateway.payload import GatewayPayload, decode_payload
from pyqbot._models.event import Event, bind_event_id, reply_fields

UTC8 = timezone(timedelta(hours=8))
HANG_GUARD = 5  # 秒：并发测试回归时应失败而不是挂起

# 以下取自官方文档各页的事件示例（`//` 注释、尾逗号等语法错误已去掉）。
GUILD = {
    "id": "123456789012345678",
    "name": "技术交流频道",
    "icon": "https://thirdqq.qlogo.cn/0",
    "owner_id": "123456789012345678",
    "member_count": 100,
    "max_members": 1000,
    "description": "专注于技术分享与交流的频道",
    "joined_at": "2026-01-01T00:00:00+08:00",
    "op_user_id": "123456789012345678",
}
GUILD_UPDATE = {
    "id": "123456789012345678",
    "name": "更新后的频道",
    "owner_id": "123456789012345678",
    "icon": "https://thirdqq.qlogo.cn/0",
    "member_count": 12,
    "max_members": 1000,
    "description": "更新后的描述",
}
CHANNEL = {
    "id": "123456",
    "guild_id": "123456789012345678",
    "name": "新子频道",
    "type": 0,
    "sub_type": 0,
    "position": 1,
    "owner_id": "123456789012345678",
}
MEMBER_ADD = {
    "guild_id": "200000000",
    "joined_at": "2021-10-21T11:20:18+08:00",
    "nick": "",
    "op_user_id": "100000000",
    "roles": ["1"],
    "user": {
        "avatar": "http://thirdqq.qlogo.cn/g?b=oidb&k=IU4JJatZtNXCVrf44eshNg&s=0&t=1638261405",
        "bot": True,
        "id": "8834102668809967837",
        "username": "b站机器人",
    },
}
MESSAGE = {
    "author": {
        "avatar": "http://thirdqq.qlogo.cn/0",
        "bot": False,
        "id": "1234",
        "username": "abc",
    },
    "channel_id": "100010",
    "content": "ndnnd",
    "guild_id": "18700000000001",
    "id": "0812345677890abcdef",
    "member": {"joined_at": "2021-04-12T16:34:42+08:00", "roles": ["1"]},
    "timestamp": "2021-05-20T15:14:58+08:00",
    "seq": 101,
}
AUDIT_REJECT = {
    "audit_id": "5f60b782-d134-4628-93b8-9baa4b182f48",
    "audit_time": "2022-01-04T18:05:42+08:00",
    "channel_id": "1699792",
    "create_time": "2022-01-04T18:05:42+08:00",
    "guild_id": "46646271634786417",
    "message_id": "10d0df671a12313434313135323138313831363239333834",
}
REACTION = {
    "user_id": "1111222233333",
    "emoji": {"id": "277", "type": 1},
    "channel_id": "12345",
    "guild_id": "11110011112222",
    "target": {"id": "2", "type": 0},
}
FORUM_THREAD = {
    "guild_id": 47129941624960822,
    "channel_id": 1661124,
    "author_id": 144115218182563108,
    "thread_info": {
        "thread_id": "B_7c02cb615f8904001441152181825631080X60",
        "title": [{"type": 1, "text_info": {"text": "Test"}}],
        "content": [
            {"type": 1, "text_info": {"text": "tencent "}},
            {"type": 5, "channel_info": {"channel_id": 1505272, "channel_name": "#隐私子频道"}},
            {"type": 1, "text_info": {"text": " "}},
            {"type": 3, "url_info": {"url": "https://apple.com", "display_text": "Apple"}},
            {"type": 1, "text_info": {"text": ""}},
        ],
        "date_time": "2021-12-30T15:17:34+08:00",
    },
}
FORUM_POST = {
    "guild_id": "47129941624960822",
    "channel_id": "1661124",
    "author_id": "144115218182563108",
    "post_info": {
        "thread_id": "B_6d02bb61e45b0d001441152181867088220X60",
        "post_id": "c_1500cb611f950a001441152181825631080X60",
        "content": [
            {"type": 1, "text_info": {"text": "test"}},
            {"type": 4, "emoji_info": {"id": 109, "type": "1"}},
        ],
        "date_time": "2021-12-30T15:17:34+08:00",
    },
}
FORUM_REPLY = {
    "guild_id": 47129941624960822,
    "channel_id": 1661124,
    "author_id": 144115218182563108,
    "reply_info": {
        "thread_id": "B_8914b26116bb03001441152181867088220X60",
        "post_id": "c_39bab261d2b907001441152181867088220X60",
        "reply_id": "r_e701cb6128dc0b001441152181825631080X60",
        "content": [{"type": 1, "text_info": {"text": "Apple"}}],
        "date_time": "2021-12-30T15:17:34+08:00",
    },
}
FORUM_AUDIT = {
    "guild_id": 47129941624960822,
    "channel_id": 1661124,
    "author_id": 144115218182563108,
    "type": 1,
    "result": 0,
    "err_msg": "",
    "thread_id": "B_8914b26116bb03001441152181867088220X60",
    "post_id": "c_39bab261d2b907001441152181867088220X60",
    "reply_id": "r_e701cb6128dc0b001441152181825631080X60",
}
OPEN_FORUM = {
    "guild_id": "47129941624960822",
    "channel_id": "1661124",
    "author_id": "144115218182563108",
}
LIVE_MEMBER = {
    "guild_id": "47129941624960822",
    "channel_id": "1661124",
    "channel_type": 2,
    "user_id": "144115218182563108",
}
# 获取帖子详情（get_thread.md）的示例里 content 字段的字符串。
RICH_TEXT_JSON = (
    '{"paragraphs":[{"elems":[{"text":{"text":"发送消息 | QQ机器人文档"},"type":1}],"props":{}},'
    '{"elems":[{"text":{"text":"• 主动消息"},"type":1}],"props":{}}]}'
)


def dispatch_of(event_name: str, data: object, event_id: str | None = None) -> GatewayPayload:
    frame = {"op": 0, "s": 1, "t": event_name, "d": data} | ({"id": event_id} if event_id else {})
    return decode_payload(json.dumps(frame))


def decoded[E: Event](event_type: type[E], data: object, event_id: str | None = None) -> E:
    event = dispatch_of(event_type.event_name, data).decode_data(event_type)
    bind_event_id(event, event_id)
    return event


NO_INTENT = pyqbot.Intents(0)
EVENTS: list[tuple[type[Event], str, pyqbot.Intents]] = [
    (pyqbot.GuildCreate, "GUILD_CREATE", pyqbot.Intents.GUILDS),
    (pyqbot.GuildUpdate, "GUILD_UPDATE", pyqbot.Intents.GUILDS),
    (pyqbot.GuildDelete, "GUILD_DELETE", pyqbot.Intents.GUILDS),
    (pyqbot.ChannelCreate, "CHANNEL_CREATE", pyqbot.Intents.GUILDS),
    (pyqbot.ChannelUpdate, "CHANNEL_UPDATE", pyqbot.Intents.GUILDS),
    (pyqbot.ChannelDelete, "CHANNEL_DELETE", pyqbot.Intents.GUILDS),
    (pyqbot.GuildMemberAdd, "GUILD_MEMBER_ADD", pyqbot.Intents.GUILD_MEMBERS),
    (pyqbot.GuildMemberUpdate, "GUILD_MEMBER_UPDATE", pyqbot.Intents.GUILD_MEMBERS),
    (pyqbot.GuildMemberRemove, "GUILD_MEMBER_REMOVE", pyqbot.Intents.GUILD_MEMBERS),
    (pyqbot.ChannelAnyMessage, "MESSAGE_CREATE", pyqbot.Intents.GUILD_MESSAGES),
    (pyqbot.MessageDelete, "MESSAGE_DELETE", pyqbot.Intents.GUILD_MESSAGES),
    (pyqbot.ChannelMessage, "AT_MESSAGE_CREATE", pyqbot.Intents.PUBLIC_GUILD_MESSAGES),
    (pyqbot.PublicMessageDelete, "PUBLIC_MESSAGE_DELETE", pyqbot.Intents.PUBLIC_GUILD_MESSAGES),
    (pyqbot.DirectMessage, "DIRECT_MESSAGE_CREATE", pyqbot.Intents.DIRECT_MESSAGE),
    (pyqbot.DirectMessageDelete, "DIRECT_MESSAGE_DELETE", pyqbot.Intents.DIRECT_MESSAGE),
    (pyqbot.MessageReactionAdd, "MESSAGE_REACTION_ADD", pyqbot.Intents.GUILD_MESSAGE_REACTIONS),
    (
        pyqbot.MessageReactionRemove,
        "MESSAGE_REACTION_REMOVE",
        pyqbot.Intents.GUILD_MESSAGE_REACTIONS,
    ),
    (pyqbot.MessageAuditPass, "MESSAGE_AUDIT_PASS", pyqbot.Intents.MESSAGE_AUDIT),
    (pyqbot.MessageAuditReject, "MESSAGE_AUDIT_REJECT", pyqbot.Intents.MESSAGE_AUDIT),
    (pyqbot.ForumThreadCreate, "FORUM_THREAD_CREATE", pyqbot.Intents.FORUMS_EVENT),
    (pyqbot.ForumThreadUpdate, "FORUM_THREAD_UPDATE", pyqbot.Intents.FORUMS_EVENT),
    (pyqbot.ForumThreadDelete, "FORUM_THREAD_DELETE", pyqbot.Intents.FORUMS_EVENT),
    (pyqbot.ForumPostCreate, "FORUM_POST_CREATE", pyqbot.Intents.FORUMS_EVENT),
    (pyqbot.ForumPostDelete, "FORUM_POST_DELETE", pyqbot.Intents.FORUMS_EVENT),
    (pyqbot.ForumReplyCreate, "FORUM_REPLY_CREATE", pyqbot.Intents.FORUMS_EVENT),
    (pyqbot.ForumReplyDelete, "FORUM_REPLY_DELETE", pyqbot.Intents.FORUMS_EVENT),
    (
        pyqbot.ForumPublishAuditResult,
        "FORUM_PUBLISH_AUDIT_RESULT",
        pyqbot.Intents.FORUMS_EVENT,
    ),
    (pyqbot.OpenForumThreadCreate, "OPEN_FORUM_THREAD_CREATE", NO_INTENT),
    (pyqbot.OpenForumThreadUpdate, "OPEN_FORUM_THREAD_UPDATE", NO_INTENT),
    (pyqbot.OpenForumThreadDelete, "OPEN_FORUM_THREAD_DELETE", NO_INTENT),
    (pyqbot.OpenForumPostCreate, "OPEN_FORUM_POST_CREATE", NO_INTENT),
    (pyqbot.OpenForumPostDelete, "OPEN_FORUM_POST_DELETE", NO_INTENT),
    (pyqbot.OpenForumReplyCreate, "OPEN_FORUM_REPLY_CREATE", NO_INTENT),
    (pyqbot.OpenForumReplyDelete, "OPEN_FORUM_REPLY_DELETE", NO_INTENT),
    (pyqbot.AudioStart, "AUDIO_START", pyqbot.Intents.AUDIO_ACTION),
    (pyqbot.AudioFinish, "AUDIO_FINISH", pyqbot.Intents.AUDIO_ACTION),
    (pyqbot.AudioOnMic, "AUDIO_ON_MIC", pyqbot.Intents.AUDIO_ACTION),
    (pyqbot.AudioOffMic, "AUDIO_OFF_MIC", pyqbot.Intents.AUDIO_ACTION),
    (pyqbot.AudioOrLiveChannelMemberEnter, "AUDIO_OR_LIVE_CHANNEL_MEMBER_ENTER", NO_INTENT),
    (pyqbot.AudioOrLiveChannelMemberExit, "AUDIO_OR_LIVE_CHANNEL_MEMBER_EXIT", NO_INTENT),
]


# ---- 事件名、Intent 与场景标记 ----


@pytest.mark.parametrize(("event_type", "event_name", "intent"), EVENTS)
def test_events_declare_their_name_and_intent(
    event_type: type[Event], event_name: str, intent: pyqbot.Intents
) -> None:
    assert (event_type.event_name, event_type.intent) == (event_name, intent)


def test_event_names_are_unique() -> None:
    names = [name for _, name, _ in EVENTS]

    assert len(names) == len(set(names))


def test_only_events_the_send_api_lists_can_be_replied_to() -> None:
    # 子频道消息用 msg_id；send.md 的 event_id 列表里有成员、表态与论坛的主题、评论、回复。
    channel = {
        pyqbot.ChannelAnyMessage,
        pyqbot.ChannelMessage,
        pyqbot.GuildMemberAdd,
        pyqbot.GuildMemberUpdate,
        pyqbot.GuildMemberRemove,
        pyqbot.MessageReactionAdd,
        pyqbot.MessageReactionRemove,
        pyqbot.ForumThreadCreate,
        pyqbot.ForumThreadUpdate,
        pyqbot.ForumThreadDelete,
        pyqbot.ForumPostCreate,
        pyqbot.ForumPostDelete,
        pyqbot.ForumReplyCreate,
        pyqbot.ForumReplyDelete,
    }
    direct = {pyqbot.DirectMessage}
    scenes = (
        pyqbot.C2CReplyTarget,
        pyqbot.GroupReplyTarget,
        pyqbot.ChannelReplyTarget,
        pyqbot.DirectMessageReplyTarget,
    )
    others = {event_type for event_type, _, _ in EVENTS} - channel - direct

    assert all(issubclass(t, pyqbot.ChannelReplyTarget) for t in channel)
    assert all(issubclass(t, pyqbot.DirectMessageReplyTarget) for t in direct)
    assert not any(issubclass(t, pyqbot.DirectMessageReplyTarget) for t in channel)
    assert not any(issubclass(t, pyqbot.ChannelReplyTarget) for t in direct)
    assert not any(issubclass(t, (pyqbot.C2CReplyTarget, pyqbot.GroupReplyTarget)) for t in channel)
    assert not any(issubclass(t, scenes) for t in others)
    assert not issubclass(pyqbot.GuildMessage, scenes)


def test_interaction_can_also_happen_in_a_channel() -> None:
    assert issubclass(pyqbot.Interaction, pyqbot.ChannelReplyTarget)
    assert not issubclass(pyqbot.Interaction, pyqbot.DirectMessageReplyTarget)


def test_messages_reply_with_msg_id_and_other_events_with_event_id() -> None:
    # WP7 的发送接口照单聊、群聊用 reply_fields() 填写被动回复的字段。
    message = decoded(pyqbot.ChannelMessage, MESSAGE, "AT_MESSAGE_CREATE:1")
    direct = decoded(pyqbot.DirectMessage, MESSAGE)
    reaction = decoded(pyqbot.MessageReactionAdd, REACTION, "MESSAGE_REACTION_ADD:2")

    assert reply_fields(message) == {"msg_id": "0812345677890abcdef", "msg_seq": 1}
    assert reply_fields(direct) == {"msg_id": "0812345677890abcdef", "msg_seq": 1}
    assert reply_fields(reaction) == {"event_id": "MESSAGE_REACTION_ADD:2", "msg_seq": 1}


# ---- 频道与子频道 ----


def test_guild_events_decode() -> None:
    created = decoded(pyqbot.GuildCreate, GUILD)
    updated = decoded(pyqbot.GuildUpdate, GUILD_UPDATE)

    assert isinstance(created, pyqbot.Guild)
    assert created.to_dict() == {**GUILD, "owner": None}
    assert created.joined_at == datetime(2026, 1, 1, tzinfo=UTC8)
    assert created.op_user_id == "123456789012345678"
    # GUILD_UPDATE 的示例没有 joined_at、op_user_id。
    assert (updated.name, updated.member_count, updated.joined_at, updated.op_user_id) == (
        "更新后的频道",
        12,
        None,
        None,
    )
    assert decoded(pyqbot.GuildDelete, {"id": "g"}) == pyqbot.GuildDelete(id="g")


def test_channel_events_decode_with_enums() -> None:
    created = decoded(pyqbot.ChannelCreate, CHANNEL)
    forum = decoded(pyqbot.ChannelUpdate, {**CHANNEL, "type": 10007, "private_type": 2})
    unknown = decoded(pyqbot.ChannelDelete, {**CHANNEL, "type": 1, "speak_permission": "1"})

    assert isinstance(created, pyqbot.Channel)
    assert created.type == pyqbot.ChannelType.TEXT
    assert created.sub_type == pyqbot.ChannelSubType.CHAT
    assert (created.position, created.op_user_id) == (1, None)
    assert forum.type == pyqbot.ChannelType.FORUM
    assert forum.private_type == pyqbot.PrivateType.ADMINS_AND_MEMBERS
    # 文档说会新增类型：未知取值保留原值；类型不符的可选字段退回默认值。
    assert unknown.type == 1
    assert unknown.type is not None
    assert unknown.type.name == "UNKNOWN"
    assert unknown.speak_permission is None


def test_channel_model_has_every_documented_field() -> None:
    channel = pyqbot.Channel(
        id="c",
        parent_id="p",
        speak_permission=pyqbot.SpeakPermission.EVERYONE,
        application_id="1000000",
        permissions="6",
    )

    assert channel.to_dict()["speak_permission"] == 1
    assert channel.guild_id is None


# ---- 频道成员与身份组 ----


@pytest.mark.parametrize(
    "event_type", [pyqbot.GuildMemberAdd, pyqbot.GuildMemberUpdate, pyqbot.GuildMemberRemove]
)
def test_guild_member_events_decode(
    event_type: type[pyqbot.GuildMemberAdd | pyqbot.GuildMemberUpdate | pyqbot.GuildMemberRemove],
) -> None:
    event = decoded(event_type, MEMBER_ADD)

    assert event.guild_id == "200000000"
    assert (event.user.id, event.user.username, event.user.bot) == (
        "8834102668809967837",
        "b站机器人",
        True,
    )
    assert event.roles == ("1",)
    assert pyqbot.DefaultRoleId.EVERYONE in event.roles
    assert event.joined_at == datetime(2021, 10, 21, 11, 20, 18, tzinfo=UTC8)
    assert (event.nick, event.op_user_id) == ("", "100000000")


def test_guild_member_event_fields_that_are_not_standardized_fall_back() -> None:
    # 文档说 joined_at、roles 尚未标准化：格式不对时退回默认值，不让整条事件丢掉。
    event = decoded(pyqbot.GuildMemberAdd, {**MEMBER_ADD, "joined_at": 1634786418, "roles": [1]})

    assert (event.joined_at, event.roles) == (None, ())


def test_role_and_member_models() -> None:
    role = pyqbot.GuildRole(id=pyqbot.DefaultRoleId.ADMIN, name="管理员", color=4278245297, hoist=1)
    member = pyqbot.GuildMember(roles=("4",))

    assert role.to_dict() == {
        "id": "2",
        "name": "管理员",
        "color": 4278245297,
        "hoist": 1,
        "number": None,
        "member_limit": None,
    }
    assert pyqbot.DefaultRoleId.OWNER in member.roles
    assert (member.user, member.nick, member.joined_at) == (None, "", None)


# ---- 频道消息 ----


@pytest.mark.parametrize(
    "event_type", [pyqbot.ChannelMessage, pyqbot.ChannelAnyMessage, pyqbot.DirectMessage]
)
def test_message_examples_decode(
    event_type: type[pyqbot.ChannelMessage | pyqbot.ChannelAnyMessage | pyqbot.DirectMessage],
) -> None:
    message = decoded(event_type, MESSAGE)

    assert isinstance(message, pyqbot.GuildMessage)
    assert (message.id, message.channel_id, message.guild_id) == (
        "0812345677890abcdef",
        "100010",
        "18700000000001",
    )
    assert message.content == "ndnnd"
    assert message.timestamp == datetime(2021, 5, 20, 15, 14, 58, tzinfo=UTC8)
    assert (message.author.id, message.author.username, message.author.bot) == (
        "1234",
        "abc",
        False,
    )
    assert message.member is not None
    assert message.member.user is None
    assert message.member.roles == ("1",)
    assert (message.seq, message.seq_in_channel, message.mention_everyone) == (101, None, False)


def test_message_decodes_every_documented_field() -> None:
    data = {
        **MESSAGE,
        "edited_timestamp": "2021-05-20T15:20:00+08:00",
        "mention_everyone": True,
        "mentions": [{"id": "5678", "username": "def", "bot": True}],
        "attachments": [{"url": "https://example.com/a.png", "content_type": "image/png"}],
        "embeds": [
            {
                "title": "标题",
                "prompt": "弹窗",
                "thumbnail": {"url": "https://example.com/t.png"},
                "fields": [{"name": "第一行"}, {"name": 2}],
            }
        ],
        "ark": {
            "template_id": 23,
            "kv": [
                {"key": "#DESC#", "value": "描述"},
                {"key": "#LIST#", "obj": [{"obj_kv": [{"key": "desc", "value": "一项"}]}]},
            ],
        },
        "seq_in_channel": "101",
        "message_reference": {"message_id": "0812345677890abcdee"},
    }
    message = decoded(pyqbot.ChannelMessage, data)

    assert message.edited_timestamp == datetime(2021, 5, 20, 15, 20, tzinfo=UTC8)
    assert message.mention_everyone is True
    assert [user.id for user in message.mentions] == ["5678"]
    assert message.attachments == (
        pyqbot.MessageAttachment(url="https://example.com/a.png", content_type="image/png"),
    )
    (embed,) = message.embeds
    assert (embed.title, embed.prompt) == ("标题", "弹窗")
    assert embed.thumbnail is not None
    assert embed.thumbnail.url == "https://example.com/t.png"
    assert [field.name for field in embed.fields] == ["第一行", ""]
    assert message.ark is not None
    assert message.ark.template_id == 23
    assert message.ark.kv[1].obj[0].obj_kv[0].value == "一项"
    assert message.seq_in_channel == "101"
    assert message.message_reference is not None
    assert message.message_reference.message_id == "0812345677890abcdee"


def test_channel_at_message_is_a_channel_any_message_but_not_the_other_way() -> None:
    message = decoded(pyqbot.ChannelAnyMessage, MESSAGE)

    assert not isinstance(message, pyqbot.ChannelMessage)
    assert isinstance(decoded(pyqbot.ChannelMessage, MESSAGE), pyqbot.ChannelAnyMessage)
    assert not isinstance(decoded(pyqbot.DirectMessage, MESSAGE), pyqbot.ChannelAnyMessage)


@pytest.mark.parametrize(
    ("event_type", "data"),
    [
        (pyqbot.ChannelMessage, {"id": "m", "guild_id": "g"}),
        (pyqbot.DirectMessage, {"id": "m", "channel_id": "c"}),
        (pyqbot.GuildCreate, {"name": "频道"}),
        (pyqbot.ChannelCreate, {"guild_id": "g"}),
        (pyqbot.GuildMemberAdd, {"guild_id": "g"}),
        (pyqbot.GuildMemberAdd, {"user": {"id": "u"}}),
        (pyqbot.MessageDelete, {"op_user": {"id": "u"}}),
        (pyqbot.MessageAuditPass, {"message_id": "m"}),
        (pyqbot.MessageReactionAdd, {**REACTION, "channel_id": None}),
        (pyqbot.MessageReactionAdd, {**REACTION, "emoji": {"id": "277"}}),
        (pyqbot.MessageReactionAdd, {**REACTION, "target": {"type": 0}}),
        (pyqbot.ForumThreadCreate, {**FORUM_THREAD, "channel_id": True}),
        (pyqbot.ForumThreadCreate, {**FORUM_THREAD, "thread_info": {"title": "t"}}),
        (pyqbot.ForumPostCreate, {**FORUM_POST, "post_info": {"thread_id": "t"}}),
        (pyqbot.ForumReplyCreate, {**FORUM_REPLY, "reply_info": {"post_id": "p"}}),
        (pyqbot.OpenForumThreadCreate, {"guild_id": "g"}),
        (pyqbot.AudioStart, {"guild_id": "g"}),
        (pyqbot.AudioOrLiveChannelMemberEnter, {"channel_id": "c"}),
    ],
)
def test_events_without_what_the_sdk_needs_are_rejected(
    event_type: type[Event], data: object
) -> None:
    with pytest.raises(PayloadError):
        dispatch_of(event_type.event_name, data).decode_data(event_type)


@pytest.mark.parametrize(
    "event_type", [pyqbot.MessageDelete, pyqbot.PublicMessageDelete, pyqbot.DirectMessageDelete]
)
def test_message_delete_events_decode(
    event_type: type[pyqbot.MessageDelete | pyqbot.DirectMessageDelete],
) -> None:
    # 文档没有给出这三个事件的示例，按 MessageDelete 对象构造。
    data = {
        "message": {"id": "m", "channel_id": "c", "guild_id": "g", "author": {"id": "u"}},
        "op_user": {"id": "admin"},
    }
    event = decoded(event_type, data)
    without_operator = decoded(event_type, {"message": data["message"]})

    assert (event.message.id, event.message.channel_id, event.message.author.id) == ("m", "c", "u")
    assert event.op_user.id == "admin"
    assert without_operator.op_user.id is None


def test_public_message_delete_is_a_message_delete() -> None:
    assert issubclass(pyqbot.PublicMessageDelete, pyqbot.MessageDelete)
    assert not issubclass(pyqbot.DirectMessageDelete, pyqbot.MessageDelete)


@pytest.mark.parametrize("event_type", [pyqbot.MessageAuditPass, pyqbot.MessageAuditReject])
def test_message_audit_events_decode(
    event_type: type[pyqbot.MessageAuditPass | pyqbot.MessageAuditReject],
) -> None:
    event = decoded(event_type, {**AUDIT_REJECT, "seq_in_channel": "7"})

    assert event.audit_id == "5f60b782-d134-4628-93b8-9baa4b182f48"
    assert event.message_id == "10d0df671a12313434313135323138313831363239333834"
    assert (event.guild_id, event.channel_id, event.seq_in_channel) == (
        "46646271634786417",
        "1699792",
        "7",
    )
    assert event.audit_time == event.create_time == datetime(2022, 1, 4, 18, 5, 42, tzinfo=UTC8)


# ---- 表情表态 ----


@pytest.mark.parametrize("event_type", [pyqbot.MessageReactionAdd, pyqbot.MessageReactionRemove])
def test_reaction_events_decode(
    event_type: type[pyqbot.MessageReactionAdd | pyqbot.MessageReactionRemove],
) -> None:
    event = decoded(event_type, REACTION)

    assert event.emoji == pyqbot.Emoji(id="277", type=pyqbot.EmojiType.SYSTEM)
    assert event.target == pyqbot.ReactionTarget(id="2", type=pyqbot.ReactionTargetType.MESSAGE)
    assert (event.user_id, event.guild_id, event.channel_id) == (
        "1111222233333",
        "11110011112222",
        "12345",
    )
    assert event.to_dict() == REACTION


def test_reaction_enums_tolerate_unknown_values() -> None:
    event = decoded(
        pyqbot.MessageReactionAdd,
        {**REACTION, "emoji": {"id": "😀", "type": 3}, "target": {"id": "t", "type": "1"}},
    )

    assert event.emoji.type == 3
    assert event.emoji.type.name == "UNKNOWN"
    assert event.target.type is None


# ---- 论坛 ----


def test_forum_thread_example_decodes_with_numeric_ids_as_strings() -> None:
    event = decoded(pyqbot.ForumThreadCreate, FORUM_THREAD)
    info = event.thread_info

    assert (event.guild_id, event.channel_id, event.author_id) == (
        "47129941624960822",
        "1661124",
        "144115218182563108",
    )
    assert info.thread_id == "B_7c02cb615f8904001441152181825631080X60"
    assert info.date_time == datetime(2021, 12, 30, 15, 17, 34, tzinfo=UTC8)
    assert not isinstance(info.title, str)
    assert info.title[0].type == pyqbot.ForumRichType.TEXT
    assert info.title[0].text_info is not None
    assert info.title[0].text_info.text == "Test"
    assert not isinstance(info.content, str)
    channel, url = info.content[1], info.content[3]
    assert channel.type == pyqbot.ForumRichType.CHANNEL
    assert channel.channel_info is not None
    assert (channel.channel_info.channel_id, channel.channel_info.channel_name) == (
        "1505272",
        "#隐私子频道",
    )
    assert url.url_info is not None
    assert (url.url_info.url, url.url_info.display_text) == ("https://apple.com", "Apple")
    # 数字 ID 统一成字符串之后，to_dict() 里也是字符串。
    assert event.to_dict()["channel_id"] == "1661124"


def test_forum_title_and_content_may_also_be_strings() -> None:
    # 模型说 title、content 是字符串；获取帖子详情的示例里 content 是 JSON 形式的 RichText。
    data = {**FORUM_THREAD, "thread_info": {"thread_id": "t", "title": "标题", "content": "正文"}}
    event = decoded(pyqbot.ForumThreadUpdate, data)
    broken = decoded(
        pyqbot.ForumThreadDelete, {**data, "thread_info": {"thread_id": "t", "title": 1}}
    )

    assert (event.thread_info.title, event.thread_info.content) == ("标题", "正文")
    assert broken.thread_info.title == ""


@pytest.mark.parametrize("event_type", [pyqbot.ForumPostCreate, pyqbot.ForumPostDelete])
def test_forum_post_example_decodes(
    event_type: type[pyqbot.ForumPostCreate | pyqbot.ForumPostDelete],
) -> None:
    event = decoded(event_type, FORUM_POST)
    info = event.post_info

    assert (info.thread_id, info.post_id) == (
        "B_6d02bb61e45b0d001441152181867088220X60",
        "c_1500cb611f950a001441152181825631080X60",
    )
    assert not isinstance(info.content, str)
    emoji = info.content[1]
    assert emoji.type == pyqbot.ForumRichType.EMOJI
    assert emoji.emoji_info is not None
    # 示例里 id 是数字、type 是字符串，与模型表格和表情表态都不一致。
    assert (emoji.emoji_info.id, emoji.emoji_info.type) == ("109", "1")


@pytest.mark.parametrize("event_type", [pyqbot.ForumReplyCreate, pyqbot.ForumReplyDelete])
def test_forum_reply_example_decodes(
    event_type: type[pyqbot.ForumReplyCreate | pyqbot.ForumReplyDelete],
) -> None:
    event = decoded(event_type, FORUM_REPLY)

    assert event.reply_info.reply_id == "r_e701cb6128dc0b001441152181825631080X60"
    assert event.reply_info.post_id == "c_39bab261d2b907001441152181867088220X60"
    assert event.channel_id == "1661124"


def test_forum_at_objects_decode() -> None:
    content = [
        {"type": 2, "at_info": {"type": 1, "user_info": {"id": "u", "nick": "小明"}}},
        {
            "type": 2,
            "at_info": {"type": 2, "role_info": {"role_id": 10, "name": "版主", "color": 1}},
        },
        {"type": 2, "at_info": {"type": 3, "guild_info": {"guild_id": "g", "guild_name": "频道"}}},
    ]
    data = {**FORUM_REPLY, "reply_info": {"reply_id": "r", "content": content}}
    info = decoded(pyqbot.ForumReplyCreate, data).reply_info

    assert not isinstance(info.content, str)
    user, role, guild = (obj.at_info for obj in info.content)
    assert user is not None
    assert user.type == pyqbot.ForumAtType.USER
    assert user.user_info is not None
    assert user.user_info.nick == "小明"
    assert role is not None
    assert role.role_info is not None
    assert (role.role_info.role_id, role.role_info.name) == ("10", "版主")
    assert guild is not None
    assert guild.type == pyqbot.ForumAtType.GUILD
    assert guild.guild_info is not None
    assert guild.guild_info.guild_name == "频道"


def test_forum_audit_result_decodes() -> None:
    event = decoded(pyqbot.ForumPublishAuditResult, FORUM_AUDIT)
    failed = decoded(
        pyqbot.ForumPublishAuditResult, {"type": 3, "result": 1, "err_msg": "含有违规内容"}
    )

    assert event.type == pyqbot.ForumAuditType.THREAD
    assert event.result == pyqbot.ForumAuditOutcome.SUCCESS
    assert (event.guild_id, event.err_msg) == ("47129941624960822", "")
    assert event.reply_id == "r_e701cb6128dc0b001441152181825631080X60"
    assert (failed.type, failed.result, failed.err_msg) == (
        pyqbot.ForumAuditType.REPLY,
        pyqbot.ForumAuditOutcome.FAILED,
        "含有违规内容",
    )
    assert failed.channel_id is None


def test_lenient_ids_reject_booleans() -> None:
    event = decoded(pyqbot.ForumPublishAuditResult, {**FORUM_AUDIT, "guild_id": True})

    assert event.guild_id is None


def test_rich_text_parses_the_content_string_of_a_thread() -> None:
    rich = pyqbot.ForumRichText.from_json(RICH_TEXT_JSON)

    first, second = rich.paragraphs
    (elem,) = first.elems
    assert elem.type == pyqbot.ForumElemType.TEXT
    assert elem.text is not None
    assert elem.text.text == "发送消息 | QQ机器人文档"
    assert first.props is not None
    assert first.props.alignment is None
    assert second.elems[0].text is not None
    assert second.elems[0].text.text == "• 主动消息"


def test_rich_text_decodes_every_element_kind() -> None:
    data: dict[str, object] = {
        "paragraphs": [
            {
                "elems": [
                    {"type": 1, "text": {"text": "粗", "props": {"font_bold": True}}},
                    {
                        "type": 2,
                        "image": {"third_url": "https://e.com/a.png", "width_percent": 0.5},
                    },
                    {"type": 3, "video": {"third_url": "https://e.com/a.mp4"}},
                    {"type": 4, "url": {"url": "https://e.com", "desc": "链接"}},
                ],
                "props": {"alignment": 1},
            },
            {"elems": []},
        ]
    }
    rich = pyqbot.ForumRichText.from_json(json.dumps(data).encode())

    text, image, video, url = rich.paragraphs[0].elems
    assert text.text is not None
    assert text.text.props is not None
    assert (text.text.props.font_bold, text.text.props.italic) == (True, None)
    assert image.image is not None
    assert image.image.width_percent == 0.5
    assert video.video is not None
    assert video.video.third_url == "https://e.com/a.mp4"
    assert url.url is not None
    assert (url.url.url, url.url.desc) == ("https://e.com", "链接")
    assert rich.paragraphs[0].props is not None
    assert rich.paragraphs[0].props.alignment == pyqbot.ForumAlignment.MIDDLE
    assert rich.paragraphs[1].elems == ()


@pytest.mark.parametrize("text", ["正文", "[1, 2]", '{"paragraphs": ', "[" * 100_000])
def test_rich_text_rejects_what_is_not_a_json_object(text: str) -> None:
    with pytest.raises(ValueError, match="无法解析论坛富文本"):
        pyqbot.ForumRichText.from_json(text)


@pytest.mark.parametrize(
    "event_type",
    [
        pyqbot.OpenForumThreadCreate,
        pyqbot.OpenForumThreadUpdate,
        pyqbot.OpenForumThreadDelete,
        pyqbot.OpenForumPostCreate,
        pyqbot.OpenForumPostDelete,
        pyqbot.OpenForumReplyCreate,
        pyqbot.OpenForumReplyDelete,
    ],
)
def test_open_forum_events_decode(event_type: type[pyqbot.OpenForumThreadCreate]) -> None:
    event = decoded(event_type, OPEN_FORUM)
    numeric = decoded(event_type, {"channel_id": 1661124, "author_id": 144115218182563108})

    assert event.to_dict() == OPEN_FORUM
    assert (numeric.guild_id, numeric.channel_id, numeric.author_id) == (
        None,
        "1661124",
        "144115218182563108",
    )


# ---- 音频 ----


@pytest.mark.parametrize(
    "event_type", [pyqbot.AudioStart, pyqbot.AudioFinish, pyqbot.AudioOnMic, pyqbot.AudioOffMic]
)
def test_audio_events_decode(event_type: type[pyqbot.AudioStart]) -> None:
    # 文档没有给出示例，按 AudioAction 对象构造。
    event = decoded(
        event_type,
        {"guild_id": "g", "channel_id": "c", "audio_url": "https://e.com/a.mp3", "text": "简单爱"},
    )

    assert (event.guild_id, event.channel_id, event.audio_url, event.text) == (
        "g",
        "c",
        "https://e.com/a.mp3",
        "简单爱",
    )
    assert decoded(event_type, {"channel_id": "c"}).text == ""


def test_audio_status_values() -> None:
    assert [s.value for s in pyqbot.AudioStatus] == [0, 1, 2, 3]


@pytest.mark.parametrize(
    "event_type", [pyqbot.AudioOrLiveChannelMemberEnter, pyqbot.AudioOrLiveChannelMemberExit]
)
def test_audio_or_live_channel_member_events_decode(
    event_type: type[pyqbot.AudioOrLiveChannelMemberEnter],
) -> None:
    audio = decoded(event_type, LIVE_MEMBER)
    live = decoded(event_type, {**LIVE_MEMBER, "channel_type": 5})
    live_by_channel_type = decoded(event_type, {**LIVE_MEMBER, "channel_type": 10005})

    assert (audio.channel_id, audio.user_id) == ("1661124", "144115218182563108")
    assert audio.channel_type == pyqbot.AudioOrLiveChannelType.AUDIO
    assert live.channel_type == pyqbot.AudioOrLiveChannelType.LIVE
    # 文档的取值与 ChannelType（直播是 10005）对不上：认不出的保留原值。
    assert live_by_channel_type.channel_type == 10005


# ---- 注册与分发 ----


async def test_each_event_has_a_decorator_that_derives_its_intent() -> None:
    async def handler(event: Event) -> None: ...

    async with pyqbot.Bot("app-id", "app-secret") as bot:
        decorators = [
            bot.on_guild_create,
            bot.on_guild_update,
            bot.on_guild_delete,
            bot.on_channel_create,
            bot.on_channel_update,
            bot.on_channel_delete,
            bot.on_guild_member_add,
            bot.on_guild_member_update,
            bot.on_guild_member_remove,
            bot.on_channel_message,
            bot.on_message_delete,
            bot.on_channel_at_message,
            bot.on_public_message_delete,
            bot.on_direct_message,
            bot.on_direct_message_delete,
            bot.on_message_reaction_add,
            bot.on_message_reaction_remove,
            bot.on_message_audit_pass,
            bot.on_message_audit_reject,
            bot.on_forum_thread_create,
            bot.on_forum_thread_update,
            bot.on_forum_thread_delete,
            bot.on_forum_post_create,
            bot.on_forum_post_delete,
            bot.on_forum_reply_create,
            bot.on_forum_reply_delete,
            bot.on_forum_publish_audit_result,
            bot.on_open_forum_thread_create,
            bot.on_open_forum_thread_update,
            bot.on_open_forum_thread_delete,
            bot.on_open_forum_post_create,
            bot.on_open_forum_post_delete,
            bot.on_open_forum_reply_create,
            bot.on_open_forum_reply_delete,
            bot.on_audio_start,
            bot.on_audio_finish,
            bot.on_audio_on_mic,
            bot.on_audio_off_mic,
            bot.on_audio_or_live_channel_member_enter,
            bot.on_audio_or_live_channel_member_exit,
        ]
        assert len(decorators) == len(EVENTS)
        for decorator in decorators:
            assert decorator(handler) is handler

        routes = bot._dispatcher._routes  # pyright: ignore[reportPrivateUsage]
        assert {name: route.event_type for name, route in routes.items()} == {
            name: event_type for event_type, name, _ in EVENTS
        }
        assert bot._resolve_intents() == (  # pyright: ignore[reportPrivateUsage]
            pyqbot.Intents.GUILDS
            | pyqbot.Intents.GUILD_MEMBERS
            | pyqbot.Intents.GUILD_MESSAGES
            | pyqbot.Intents.GUILD_MESSAGE_REACTIONS
            | pyqbot.Intents.DIRECT_MESSAGE
            | pyqbot.Intents.MESSAGE_AUDIT
            | pyqbot.Intents.FORUMS_EVENT
            | pyqbot.Intents.AUDIO_ACTION
            | pyqbot.Intents.PUBLIC_GUILD_MESSAGES
        )


async def test_events_without_an_intent_bit_need_explicit_intents() -> None:
    async def on_enter(event: pyqbot.AudioOrLiveChannelMemberEnter) -> None: ...

    async with pyqbot.Bot("app-id", "app-secret") as bot:
        bot.on_audio_or_live_channel_member_enter(on_enter)
        with pytest.raises(RuntimeError, match="没有要订阅的事件"):
            await bot.start()

    async def on_thread(event: pyqbot.OpenForumThreadCreate) -> None: ...

    explicit = pyqbot.Intents(1 << 31)  # 调用方向平台确认过的位，SDK 原样使用
    async with pyqbot.Bot("app-id", "app-secret", intents=explicit) as bot:
        bot.on_open_forum_thread_create(on_thread)
        assert bot._resolve_intents() == explicit  # pyright: ignore[reportPrivateUsage]


async def test_handlers_for_the_wrong_event_are_type_errors() -> None:
    async with pyqbot.Bot("app-id", "app-secret") as bot:

        async def on_at(message: pyqbot.ChannelMessage) -> None: ...

        async def on_any(message: pyqbot.ChannelAnyMessage) -> None: ...

        async def on_deleted(event: pyqbot.MessageDelete) -> None: ...

        # 只收 @ 消息的处理函数不能接全量消息；收全量消息的可以两处都注册。删除事件同理。
        bot.on_channel_message(on_at)  # pyright: ignore[reportArgumentType]
        bot.on_channel_at_message(on_any)
        bot.on_direct_message(on_any)  # pyright: ignore[reportArgumentType]
        bot.on_public_message_delete(on_deleted)
        bot.on_direct_message_delete(on_deleted)  # pyright: ignore[reportArgumentType]


async def test_channel_messages_go_only_to_the_decorator_of_their_event_name() -> None:
    seen: list[tuple[str, str, str | None]] = []
    done = asyncio.Event()

    def record(decorator: str, event: Event) -> None:
        seen.append((decorator, type(event).__name__, event.event_id))
        if len(seen) == 3:
            done.set()

    async with pyqbot.Bot("app-id", "app-secret") as bot:

        @bot.on_channel_at_message
        async def at(message: pyqbot.ChannelMessage) -> None:
            record("at", message)

        @bot.on_channel_message
        async def every(message: pyqbot.ChannelAnyMessage) -> None:
            record("any", message)

        @bot.on_audio_or_live_channel_member_exit
        async def left(event: pyqbot.AudioOrLiveChannelMemberExit) -> None:
            record("exit", event)

        dispatcher = bot._dispatcher  # pyright: ignore[reportPrivateUsage]  代替 Bot.start()
        dispatcher.dispatch(dispatch_of("MESSAGE_CREATE", MESSAGE, "MESSAGE_CREATE:1"), bot)
        dispatcher.dispatch(dispatch_of("AT_MESSAGE_CREATE", MESSAGE, "AT_MESSAGE_CREATE:2"), bot)
        dispatcher.dispatch(dispatch_of("DIRECT_MESSAGE_CREATE", MESSAGE), bot)
        dispatcher.dispatch(
            dispatch_of("AUDIO_OR_LIVE_CHANNEL_MEMBER_EXIT", LIVE_MEMBER, "EXIT:3"), bot
        )
        async with asyncio.timeout(HANG_GUARD):
            await done.wait()

    assert sorted(seen) == [
        ("any", "ChannelAnyMessage", "MESSAGE_CREATE:1"),
        ("at", "ChannelMessage", "AT_MESSAGE_CREATE:2"),
        ("exit", "AudioOrLiveChannelMemberExit", "EXIT:3"),
    ]
