# pyright: reportUnnecessaryTypeIgnoreComment=true
# 打开上面这条，下面「pyright 拒绝」的那几行若不再报错，pyright 就会报「多余的 ignore」。
"""频道消息：子频道与私信的发送、multipart 图片、被动回复、待审核、撤回与各事件的 reply()。"""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from email.message import Message
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path

import httpx2
import pytest

import pyqbot
from pyqbot._models.event import bind_client, bind_event_id, next_msg_seq

APP_SECRET = "secret-value-never-shown"
TOKEN = "token-value-never-shown"
SENT: dict[str, object] = {
    "id": "sent",
    "channel_id": "c",
    "guild_id": "g",
    "content": "你好",
    "timestamp": "2021-05-13T14:45:45+08:00",
    "tts": False,
    "mention_everyone": False,
    "author": {"id": "bot", "username": "abc", "avatar": "", "bot": True},
    "embeds": [{}],
    "pinned": False,
    "type": 0,
    "flags": 0,
}


class Platform:
    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.response = httpx2.Response(200, json=SENT)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})
        self.requests.append(request)
        return self.response

    def calls(self) -> list[tuple[str, str, object]]:
        return [
            (
                request.method,
                request.url.raw_path.decode(),
                json.loads(request.content) if request.content else None,
            )
            for request in self.requests
        ]


@asynccontextmanager
async def client_for(platform: Platform) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client("app-id", APP_SECRET, http_client=http_client) as client,
    ):
        yield client


def multipart(request: httpx2.Request) -> dict[str, tuple[str | None, bytes]]:
    """把 multipart 请求体拆成 字段名 →（文件名, 内容）。"""
    head = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
    parsed: Message = BytesParser(policy=HTTP).parsebytes(head + request.content)
    parts: dict[str, tuple[str | None, bytes]] = {}
    for part in parsed.iter_parts():
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True)
        assert isinstance(name, str)
        assert isinstance(payload, bytes)
        parts[name] = (part.get_filename(), payload)
    return parts


def channel_message(event_id: str | None = None) -> pyqbot.ChannelAtMessage:
    message = pyqbot.ChannelAtMessage(id="m", channel_id="c", guild_id="g")
    bind_event_id(message, event_id)
    return message


def reaction(event_id: str | None = "REACTION:1") -> pyqbot.MessageReactionAdd:
    event = pyqbot.MessageReactionAdd(
        channel_id="c",
        target=pyqbot.ReactionTarget(id="m"),
        emoji=pyqbot.Emoji(id="4", type=pyqbot.EmojiType.SYSTEM),
    )
    bind_event_id(event, event_id)
    return event


# ---- 子频道发消息 ----


async def test_text_is_posted_as_json_and_the_message_is_decoded() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        sent = await client.channels.send_message("c/1", "你好")

    assert platform.calls() == [("POST", "/channels/c%2F1/messages", {"content": "你好"})]
    [request] = platform.requests
    assert request.headers["authorization"] == f"QQBot {TOKEN}"
    assert request.headers["content-type"] == "application/json"
    assert isinstance(sent, pyqbot.GuildMessage)
    assert (sent.id, sent.channel_id, sent.author.bot) == ("sent", "c", True)


async def test_every_content_kind_is_encoded_into_the_body() -> None:
    platform = Platform()
    embed = pyqbot.Embed.from_lines(
        "标题", "当前等级：黄金", "之前等级：白银", prompt="消息通知", thumbnail_url="https://t"
    )
    ark = pyqbot.Ark.from_template(
        23,
        {"#DESC#": "描述", "#LIST#": [{"desc": "已评审", "link": "https://q"}, {"desc": "请关注"}]},
    )
    quoted = pyqbot.GuildMessage(id="q", channel_id="c", guild_id="g")

    async with client_for(platform) as client:
        await client.channels.send_message(
            "c",
            "看",
            markdown="**粗**",
            keyboard=pyqbot.Keyboard(id="k"),
            embed=embed,
            ark=ark,
            image="https://img/1.png",
            quote=quoted,
        )
        await client.channels.send_message(
            "c", markdown=pyqbot.Markdown.from_template("t", params={"a": "b"}), quote="q2"
        )

    assert platform.calls() == [
        (
            "POST",
            "/channels/c/messages",
            {
                "content": "看",
                "markdown": {"content": "**粗**"},
                "keyboard": {"id": "k"},
                "embed": {
                    "title": "标题",
                    "prompt": "消息通知",
                    "thumbnail": {"url": "https://t"},
                    "fields": [{"name": "当前等级：黄金"}, {"name": "之前等级：白银"}],
                },
                "ark": {
                    "template_id": 23,
                    "kv": [
                        {"key": "#DESC#", "value": "描述"},
                        {
                            "key": "#LIST#",
                            "obj": [
                                {
                                    "obj_kv": [
                                        {"key": "desc", "value": "已评审"},
                                        {"key": "link", "value": "https://q"},
                                    ]
                                },
                                {"obj_kv": [{"key": "desc", "value": "请关注"}]},
                            ],
                        },
                    ],
                },
                "image": "https://img/1.png",
                "message_reference": {"message_id": "q"},
            },
        ),
        (
            "POST",
            "/channels/c/messages",
            {
                "markdown": {"custom_template_id": "t", "params": [{"key": "a", "values": ["b"]}]},
                "message_reference": {"message_id": "q2"},
            },
        ),
    ]


def test_embed_without_optional_parts_has_only_its_title() -> None:
    assert pyqbot.Embed.from_lines("只有标题").to_dict() == {"title": "只有标题"}


@pytest.mark.parametrize(
    ("arguments", "match"),
    [
        ({}, "没有要发送的内容"),
        (
            {"content": "x", "image": "https://a", "image_data": b"x"},
            "image、image_data 只能传一个",
        ),
        ({"image_path": "a.png", "image_data": b"x"}, "image_path、image_data 只能传一个"),
        ({"content": "x", "keyboard": pyqbot.Keyboard(id="k")}, "keyboard 只能随 markdown"),
        ({"content": "x", "quote": ""}, "quote 没有可用的消息 ID"),
    ],
)
async def test_invalid_combinations_are_rejected_before_sending(
    arguments: dict[str, object], match: str
) -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match=match):
            await client.channels.send_message("c", **arguments)  # pyright: ignore[reportArgumentType]
        with pytest.raises(ValueError, match=match):
            await client.dms.send_message("g", **arguments)  # pyright: ignore[reportArgumentType]

    assert platform.requests == []


async def test_empty_channel_id_is_rejected() -> None:
    async with client_for(Platform()) as client:
        with pytest.raises(ValueError, match="channel_id 不合法"):
            await client.channels.send_message("", "x")


# ---- multipart ----


async def test_local_image_is_uploaded_as_multipart_with_json_encoded_objects(
    tmp_path: Path,
) -> None:
    platform = Platform()
    image = tmp_path / "cat.png"
    image.write_bytes(b"\x89PNG-data")
    message = channel_message()

    async with client_for(platform) as client:
        await client.channels.send_message(
            "c",
            "看图",
            image_path=image,
            embed=pyqbot.Embed.from_lines("标题", "行"),
            quote="q",
            reply_to=message,
        )

    [request] = platform.requests
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert request.headers["authorization"] == f"QQBot {TOKEN}"
    parts = multipart(request)
    assert parts.pop("file_image") == ("cat.png", b"\x89PNG-data")
    assert {
        name: json.loads(value) if name in ("embed", "message_reference") else value.decode()
        for name, (_, value) in parts.items()
    } == {
        "content": "看图",
        "embed": {"title": "标题", "fields": [{"name": "行"}]},
        "message_reference": {"message_id": "q"},
        "msg_id": "m",
    }


@pytest.mark.parametrize("default", ["application/json", "text/plain"])
async def test_injected_default_content_type_does_not_mislabel_the_body(default: str) -> None:
    platform = Platform()
    async with (
        httpx2.AsyncClient(
            transport=httpx2.MockTransport(platform.handle),
            headers={"Content-Type": default},
        ) as http_client,
        pyqbot.Client("app-id", APP_SECRET, http_client=http_client) as client,
    ):
        await client.channels.send_message("c", "x", image_data=b"raw")
        await client.channels.send_message("c", "x")

    multipart_request, json_request = platform.requests
    assert multipart_request.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert multipart(multipart_request) == {
        "content": (None, b"x"),
        "file_image": ("image", b"raw"),
    }
    assert multipart_request.headers["content-length"] == str(len(multipart_request.content))
    assert json_request.headers["content-type"] == "application/json"


async def test_image_data_is_uploaded_under_a_placeholder_name() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        await client.dms.send_message("dm", image_data=b"raw")

    [request] = platform.requests
    assert request.url.raw_path == b"/dms/dm/messages"
    assert multipart(request) == {"file_image": ("image", b"raw")}


async def test_unreadable_image_path_raises_os_error(tmp_path: Path) -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(FileNotFoundError):
            await client.channels.send_message("c", image_path=tmp_path / "missing.png")

    assert platform.requests == []


async def test_multipart_failure_is_mapped_and_redacted() -> None:
    platform = Platform()
    platform.response = httpx2.Response(
        400, json={"code": 304020, "message": f"文件太大 {APP_SECRET} {TOKEN}"}
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.channels.send_message("c", image_data=b"x")

    assert caught.value.err_code == 304020
    assert APP_SECRET not in str(caught.value)
    assert TOKEN not in str(caught.value)
    assert "POST /channels/c/messages 失败" in str(caught.value)


# ---- 被动回复 ----


async def test_replies_use_msg_id_or_event_id_without_msg_seq() -> None:
    platform = Platform()
    message = channel_message()
    event = reaction()
    member = pyqbot.GuildMemberAdd(guild_id="g", user=pyqbot.GuildUser(id="u"))
    bind_event_id(member, "MEMBER:1")

    async with client_for(platform) as client:
        await client.channels.send_message("c", "1", reply_to=message)
        await client.channels.send_message("c", "2", reply_to=event)
        await client.channels.send_message("other", "欢迎", reply_to=member)

    assert platform.calls() == [
        ("POST", "/channels/c/messages", {"content": "1", "msg_id": "m"}),
        ("POST", "/channels/c/messages", {"content": "2", "event_id": "REACTION:1"}),
        ("POST", "/channels/other/messages", {"content": "欢迎", "event_id": "MEMBER:1"}),
    ]
    # 频道不占用 msg_seq：之后第一次取到的仍是 1。
    assert next_msg_seq(message) == 1


async def test_reply_to_an_event_without_event_id_is_rejected() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match="没有事件 ID"):
            await client.channels.send_message("c", "x", reply_to=reaction(None))

    assert platform.requests == []


async def test_event_shortcuts_reply_where_the_event_happened() -> None:
    platform = Platform()
    message = channel_message()
    any_message = pyqbot.ChannelMessage(id="a", channel_id="c2", guild_id="g")
    direct = pyqbot.DirectMessage(id="d", channel_id="dc", guild_id="dm")
    event = reaction()
    thread = pyqbot.ForumThreadCreate(
        channel_id="forum", thread_info=pyqbot.ForumThreadInfo(thread_id="t")
    )
    bind_event_id(thread, "FORUM:1")
    post = pyqbot.ForumPostCreate(channel_id="forum", post_info=pyqbot.ForumPostInfo(post_id="p"))
    bind_event_id(post, "FORUM:2")

    async with client_for(platform) as client:
        for target in (message, any_message, direct, event, thread, post):
            bind_client(target, client)
        sent = await message.reply("收到", embed=pyqbot.Embed.from_lines("t"))
        await any_message.reply(image="https://a", quote=message)
        await direct.reply("私信")
        await event.reply(markdown="**表态**", keyboard=pyqbot.Keyboard(id="k"))
        await thread.reply(ark=pyqbot.Ark(template_id=37))
        await post.reply("评论")

    assert sent.id == "sent"
    assert platform.calls() == [
        (
            "POST",
            "/channels/c/messages",
            {"content": "收到", "embed": {"title": "t"}, "msg_id": "m"},
        ),
        (
            "POST",
            "/channels/c2/messages",
            {"image": "https://a", "message_reference": {"message_id": "m"}, "msg_id": "a"},
        ),
        ("POST", "/dms/dm/messages", {"content": "私信", "msg_id": "d"}),
        (
            "POST",
            "/channels/c/messages",
            {
                "markdown": {"content": "**表态**"},
                "keyboard": {"id": "k"},
                "event_id": "REACTION:1",
            },
        ),
        ("POST", "/channels/forum/messages", {"ark": {"template_id": 37}, "event_id": "FORUM:1"}),
        ("POST", "/channels/forum/messages", {"content": "评论", "event_id": "FORUM:2"}),
    ]


async def test_shortcuts_on_unbound_events_raise() -> None:
    with pytest.raises(RuntimeError, match="没有绑定 Client"):
        await channel_message().reply("x")
    with pytest.raises(RuntimeError, match="没有绑定 Client"):
        await pyqbot.DirectMessage(id="d", channel_id="c", guild_id="g").reply("x")
    with pytest.raises(RuntimeError, match="没有绑定 Client"):
        await reaction().reply("x")


# ---- 待审核 ----


async def test_audit_pending_carries_the_audit_id() -> None:
    platform = Platform()
    platform.response = httpx2.Response(
        202,
        json={
            "code": 304023,
            "message": "push message is waiting for audit now",
            "data": {"message_audit": {"audit_id": "ab9bd72f"}},
        },
        headers={"X-Tps-trace-ID": "trace"},
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.AuditPendingError) as caught:
            await client.channels.send_message("c", "x")

    error = caught.value
    assert isinstance(error, pyqbot.APIError)
    assert (error.status_code, error.err_code, error.audit_id, error.trace_id) == (
        202,
        304023,
        "ab9bd72f",
        "trace",
    )
    assert str(error).startswith("POST /channels/c/messages 已受理，等待审核：push message")


async def test_audit_pending_without_data_and_with_echoed_credentials() -> None:
    platform = Platform()
    platform.response = httpx2.Response(
        202,
        json={
            "err_code": 304024,
            "message": f"回显 {APP_SECRET}",
            "data": {"message_audit": {"audit_id": f"id-{TOKEN}"}},
        },
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.AuditPendingError) as caught:
            await client.dms.send_message("g", "x")
        platform.response = httpx2.Response(202, json={"code": 304024, "data": "?"})
        with pytest.raises(pyqbot.AuditPendingError) as without_data:
            await client.dms.send_message("g", "x")

    assert APP_SECRET not in str(caught.value)
    assert caught.value.audit_id == "id-***"
    assert without_data.value.audit_id is None
    assert "等待审核：304024" in str(without_data.value)


@pytest.mark.parametrize(
    ("status_code", "code"), [(400, 304023), (202, 304025)], ids=["not-2xx", "other-code"]
)
async def test_other_failures_are_plain_api_errors(status_code: int, code: int) -> None:
    platform = Platform()
    platform.response = httpx2.Response(status_code, json={"code": code, "message": "m"})

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.channels.send_message("c", "x")

    assert not isinstance(caught.value, pyqbot.AuditPendingError)
    assert caught.value.err_code == code


# ---- 撤回 ----


async def test_recall_sends_hidetip_explicitly() -> None:
    platform = Platform()
    platform.response = httpx2.Response(200)

    async with client_for(platform) as client:
        await client.channels.recall_message("c", "m/1")
        await client.channels.recall_message("c", channel_message(), hidetip=True)
        await client.dms.recall_message("dm", "m")

    assert platform.calls() == [
        ("DELETE", "/channels/c/messages/m%2F1?hidetip=false", None),
        ("DELETE", "/channels/c/messages/m?hidetip=true", None),
        ("DELETE", "/dms/dm/messages/m?hidetip=false", None),
    ]


async def test_recall_rejects_an_empty_message_id() -> None:
    async with client_for(Platform()) as client:
        with pytest.raises(ValueError, match="message_id 不合法"):
            await client.dms.recall_message("dm", "")


# ---- 私信会话 ----


async def test_direct_message_session_is_created_and_used() -> None:
    platform = Platform()
    platform.response = httpx2.Response(
        200, json={"guild_id": "dm", "channel_id": "dc", "create_time": "1642545606"}
    )

    async with client_for(platform) as client:
        session = await client.dms.create_session("u", "g")

    assert session == pyqbot.DirectMessageSession(
        guild_id="dm", channel_id="dc", create_time="1642545606"
    )
    assert platform.calls() == [
        ("POST", "/users/@me/dms", {"recipient_id": "u", "source_guild_id": "g"})
    ]


# ---- 类型 ----


async def wrong_scene_is_rejected_by_pyright(client: pyqbot.Client) -> None:
    """不运行，只给 pyright 看：子频道与私信的回复对象不能互换，也不能传给单聊、群聊。"""
    direct = pyqbot.DirectMessage(id="d", channel_id="c", guild_id="g")
    await client.channels.send_message("c", "x", reply_to=direct)  # pyright: ignore[reportArgumentType]
    await client.dms.send_message("g", "x", reply_to=channel_message())  # pyright: ignore[reportArgumentType]
    await client.users.send_message("u", "x", reply_to=channel_message())  # pyright: ignore[reportArgumentType]
    sent = pyqbot.GuildMessage(id="s", channel_id="c", guild_id="g")
    await client.channels.send_message("c", "x", reply_to=sent)  # pyright: ignore[reportArgumentType]
