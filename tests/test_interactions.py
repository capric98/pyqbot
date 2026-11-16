"""互动事件：解码、`ack()` 与 `client.interactions.ack()`、按场景分派的 `reply()`。"""

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx2
import pytest

import pyqbot
from pyqbot._errors import PayloadError
from pyqbot._gateway.payload import decode_payload
from pyqbot._models.event import bind_client, bind_event_id

APP_SECRET = "secret-value-never-shown"
UTC8 = timezone(timedelta(hours=8))
HANG_GUARD = 5  # 秒：并发测试回归时应失败而不是挂起

# autogen/event/interaction_create.md 的示例 1～3。
C2C_CLICK = {
    "application_id": "1904842048",
    "chat_type": 2,
    "data": {"resolved": {"button_data": "confirm:once", "button_id": "allow-once"}, "type": 11},
    "id": "1b13d569-4610-4ab9-bc51-feecc5def6d4",
    "scene": "c2c",
    "timestamp": "2026-07-20T21:53:54+08:00",
    "type": 11,
    "user_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "version": 1,
}
GROUP_CLICK = {
    "application_id": "101984245",
    "chat_type": 1,
    "data": {"resolved": {"button_data": "eyJjb21tYW5kIjogInNhbXBsZSJ9"}, "type": 11},
    "group_member_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "group_openid": "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
    "id": "06915133-7aef-46ed-94f7-c50939e285ae",
    "scene": "group",
    "timestamp": "2026-07-20T21:53:54+08:00",
    "type": 11,
    "version": 1,
}
AUTHORIZE = {
    "application_id": "102057050",
    "data": {"resolved": {"authorize_data": {"opt_scene": "setting", "scope": "c2c_push"}}},
    "id": "c30c003e-9454-4450-8e5e-665267c088c4",
    "scene": "c2c",
    "timestamp": "2026-07-20T21:54:38+08:00",
    "type": 18,
    "user_openid": "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
    "version": 1,
}


def interaction(
    data: object, event_id: str | None = "INTERACTION_CREATE:outer"
) -> pyqbot.Interaction:
    frame = {"op": 0, "s": 1, "t": "INTERACTION_CREATE", "id": event_id, "d": data}
    event = decode_payload(json.dumps(frame)).decode_data(pyqbot.Interaction)
    bind_event_id(event, event_id)
    return event


class Platform:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, object]] = []
        self.response = httpx2.Response(200, json={})

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": "t", "expires_in": "7200"})
        body: object = None
        if request.headers.get("content-type", "").startswith("multipart/"):
            body = request.content  # 本地图片：multipart 原样记下
        elif request.content:
            body = json.loads(request.content)
        self.requests.append((request.method, request.url.raw_path.decode(), body))
        if request.method == "POST" and request.url.path.startswith("/channels/"):
            return httpx2.Response(200, json={"id": "sent", "channel_id": "c", "guild_id": "g"})
        if request.method == "POST":
            return httpx2.Response(200, json={"id": "ROBOT1.0_sent"})
        return self.response


@asynccontextmanager
async def client_for(platform: Platform) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client("app-id", APP_SECRET, http_client=http_client) as client,
    ):
        yield client


# ---- 解码 ----


def test_interaction_declares_its_name_and_intent_and_both_scenes() -> None:
    assert (pyqbot.Interaction.event_name, pyqbot.Interaction.intent) == (
        "INTERACTION_CREATE",
        pyqbot.Intents.INTERACTION,
    )
    assert issubclass(pyqbot.Interaction, pyqbot.C2CReplyTarget)
    assert issubclass(pyqbot.Interaction, pyqbot.GroupReplyTarget)


def test_official_examples_decode() -> None:
    c2c = interaction(C2C_CLICK)
    group = interaction(GROUP_CLICK)
    authorize = interaction(AUTHORIZE)

    assert c2c.id == "1b13d569-4610-4ab9-bc51-feecc5def6d4"
    assert c2c.event_id == "INTERACTION_CREATE:outer"
    assert (c2c.type, c2c.chat_type, c2c.scene) == (
        pyqbot.InteractionType.INLINE_KEYBOARD,
        pyqbot.ChatType.C2C,
        "c2c",
    )
    assert c2c.timestamp == datetime(2026, 7, 20, 21, 53, 54, tzinfo=UTC8)
    assert (c2c.button_data, c2c.button_id) == ("confirm:once", "allow-once")
    assert c2c.data.type == pyqbot.InteractionType.INLINE_KEYBOARD
    assert (c2c.version, c2c.application_id) == (1, "1904842048")
    assert c2c.to_dict()["data"]["resolved"]["button_id"] == "allow-once"

    assert group.chat_type == pyqbot.ChatType.GROUP
    assert (group.group_openid, group.group_member_openid, group.user_openid) == (
        "B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5",
        "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
        None,
    )
    assert group.button_id is None

    # 示例 3 没有 chat_type 与 data.type。
    assert (authorize.type, authorize.chat_type, authorize.data.type) == (
        pyqbot.InteractionType.USER_AUTHORIZE,
        None,
        None,
    )
    authorize_data = authorize.data.resolved.authorize_data
    assert authorize_data is not None
    assert (authorize_data.opt_scene, authorize_data.scope) == ("setting", "c2c_push")
    assert authorize.button_data is None


def test_unknown_types_and_bad_fields_are_tolerated() -> None:
    event = interaction(
        {"id": "i", "type": 21, "chat_type": 9, "data": "bad", "timestamp": 1784570523}
    )

    assert event.type == 21
    assert event.type is not None
    assert event.type.name == "UNKNOWN"
    assert event.chat_type == 9
    assert event.data == pyqbot.Interaction(id="x").data
    assert event.timestamp is None


def test_listed_string_values_decode_to_enums() -> None:
    feedback = interaction(
        {"id": "i", "type": 13, "data": {"resolved": {"feedback_opt": "LIKE", "checked": 1}}}
    )
    authorize = interaction(AUTHORIZE).data.resolved.authorize_data

    assert interaction(GROUP_CLICK).scene == pyqbot.InteractionScene.GROUP
    assert feedback.data.resolved.feedback_opt == pyqbot.FeedbackOption.LIKE
    assert authorize is not None
    assert authorize.opt_scene == pyqbot.AuthorizeOptScene.SETTING
    assert authorize.scope == pyqbot.AuthorizeScope.C2C_PUSH
    # StrEnum：与原字符串比较照样成立。
    assert authorize.scope == "c2c_push"


def test_unknown_string_values_are_kept_and_wrong_types_fall_back() -> None:
    unknown = interaction(
        {
            "id": "i",
            "scene": "channel",
            "data": {
                "resolved": {
                    "feedback_opt": "LOVE",
                    "authorize_data": {"opt_scene": "qrcode", "scope": "guild_push"},
                }
            },
        }
    )
    wrong = interaction(
        {
            "id": "i",
            "scene": 1,
            "data": {"resolved": {"feedback_opt": True, "authorize_data": {"scope": 2}}},
        }
    )

    assert unknown.scene == "channel"
    assert unknown.scene is not None
    assert unknown.scene.name == "UNKNOWN"
    resolved = unknown.data.resolved
    assert resolved.feedback_opt is not None
    assert resolved.feedback_opt.name == "UNKNOWN"
    assert resolved.authorize_data is not None
    assert (resolved.authorize_data.opt_scene, resolved.authorize_data.scope) == (
        "qrcode",
        "guild_push",
    )
    assert unknown.to_dict()["scene"] == "channel"
    assert (wrong.scene, wrong.data.resolved.feedback_opt) == (None, None)
    assert (
        wrong.data.resolved.authorize_data
        == interaction(
            {"id": "i", "data": {"resolved": {"authorize_data": {}}}}
        ).data.resolved.authorize_data
    )


def test_interaction_without_an_id_is_rejected() -> None:
    frame = {"op": 0, "s": 1, "t": "INTERACTION_CREATE", "d": {"type": 11}}
    with pytest.raises(PayloadError, match="无法解码为 Interaction"):
        decode_payload(json.dumps(frame)).decode_data(pyqbot.Interaction)


# ---- ack ----


async def test_ack_puts_the_result_code_to_the_interaction_id() -> None:
    platform = Platform()
    event = interaction(C2C_CLICK)

    async with client_for(platform) as client:
        bind_client(event, client)
        await event.ack()
        await event.ack(code=pyqbot.InteractionResult.NO_PERMISSION)
        await client.interactions.ack("a/b", code=pyqbot.InteractionResult.ADMIN_ONLY)

    # 用的是事件体的 id，不是外层的 event_id。
    assert platform.requests == [
        ("PUT", "/interactions/1b13d569-4610-4ab9-bc51-feecc5def6d4", {"code": 0}),
        ("PUT", "/interactions/1b13d569-4610-4ab9-bc51-feecc5def6d4", {"code": 4}),
        ("PUT", "/interactions/a%2Fb", {"code": 5}),
    ]


async def test_ack_accepts_an_empty_response_body() -> None:
    platform = Platform()
    platform.response = httpx2.Response(204)

    async with client_for(platform) as client:
        await client.interactions.ack("i")

    assert platform.requests == [("PUT", "/interactions/i", {"code": 0})]


async def test_ack_rejects_an_empty_id() -> None:
    async with client_for(Platform()) as client:
        with pytest.raises(ValueError, match="interaction_id 不合法"):
            await client.interactions.ack("")


async def test_ack_failure_is_an_api_error_without_credentials() -> None:
    platform = Platform()
    platform.response = httpx2.Response(
        400, json={"err_code": 630003, "message": f"appid invalid {APP_SECRET} t"}
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.interactions.ack("i")

    assert caught.value.err_code == 630003
    assert "PUT /interactions/i 失败" in str(caught.value)
    assert APP_SECRET not in str(caught.value)


async def test_ack_on_an_unbound_interaction_raises() -> None:
    with pytest.raises(RuntimeError, match="没有绑定 Client"):
        await pyqbot.Interaction(id="i").ack()


# ---- reply ----


async def test_reply_goes_to_the_user_or_the_group_with_the_event_id() -> None:
    platform = Platform()
    private = interaction(C2C_CLICK, "INTERACTION_CREATE:c2c")
    group = interaction(GROUP_CLICK, "INTERACTION_CREATE:group")
    # 没有 chat_type 时按 scene 判断。
    authorize = interaction(AUTHORIZE, "INTERACTION_CREATE:auth")

    async with client_for(platform) as client:
        for event in (private, group, authorize):
            bind_client(event, client)
        sent = await private.reply("好的")
        await private.reply(markdown="**再说一句**")
        await group.reply("收到", quote="REFIDX_q")
        await authorize.reply("谢谢授权")

    assert sent.id == "ROBOT1.0_sent"
    assert platform.requests == [
        (
            "POST",
            "/v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages",
            {"msg_type": 0, "content": "好的", "event_id": "INTERACTION_CREATE:c2c", "msg_seq": 1},
        ),
        (
            "POST",
            "/v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages",
            {
                "msg_type": 2,
                "markdown": {"content": "**再说一句**"},
                "event_id": "INTERACTION_CREATE:c2c",
                "msg_seq": 2,
            },
        ),
        (
            "POST",
            "/v2/groups/B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4E5/messages",
            {
                "msg_type": 0,
                "content": "收到",
                "message_reference": {"message_id": "REFIDX_q"},
                "event_id": "INTERACTION_CREATE:group",
                "msg_seq": 1,
            },
        ),
        (
            "POST",
            "/v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages",
            {
                "msg_type": 0,
                "content": "谢谢授权",
                "event_id": "INTERACTION_CREATE:auth",
                "msg_seq": 1,
            },
        ),
    ]


async def test_guild_interaction_reply_goes_to_its_channel_without_msg_seq() -> None:
    platform = Platform()
    guild = interaction({"id": "i", "chat_type": 0, "guild_id": "g", "channel_id": "c"}, "E1")
    by_scene = interaction({"id": "i", "scene": "guild", "channel_id": "c"}, "E2")

    async with client_for(platform) as client:
        bind_client(guild, client)
        bind_client(by_scene, client)
        sent = await guild.reply("收到", quote="m")
        await by_scene.reply(markdown="**好**", keyboard=pyqbot.Keyboard(id="k"))

    assert isinstance(sent, pyqbot.GuildMessage)
    assert sent.channel_id == "c"
    assert platform.requests == [
        (
            "POST",
            "/channels/c/messages",
            {"content": "收到", "message_reference": {"message_id": "m"}, "event_id": "E1"},
        ),
        (
            "POST",
            "/channels/c/messages",
            {"markdown": {"content": "**好**"}, "keyboard": {"id": "k"}, "event_id": "E2"},
        ),
    ]


async def test_guild_interaction_reply_sends_channel_only_content() -> None:
    platform = Platform()
    event = interaction({"id": "i", "chat_type": 0, "channel_id": "c"}, "E1")
    quoted = pyqbot.GuildMessage(id="m1", channel_id="c", guild_id="g")

    async with client_for(platform) as client:
        bind_client(event, client)
        await event.reply(
            embed=pyqbot.Embed(title="标题"),
            ark=pyqbot.Ark(template_id=23),
            image="https://example.com/a.png",
            quote=quoted,
        )

    assert platform.requests == [
        (
            "POST",
            "/channels/c/messages",
            {
                "embed": {"title": "标题"},
                "ark": {"template_id": 23},
                "image": "https://example.com/a.png",
                "message_reference": {"message_id": "m1"},
                "event_id": "E1",
            },
        )
    ]


async def test_guild_interaction_reply_uploads_a_local_image(tmp_path: Path) -> None:
    platform = Platform()
    event = interaction({"id": "i", "chat_type": 0, "channel_id": "c"}, "E1")
    path = tmp_path / "cat.png"
    path.write_bytes(b"png")

    async with client_for(platform) as client:
        bind_client(event, client)
        await event.reply("看图", image_path=path)

    [(method, target, body)] = platform.requests
    assert (method, target) == ("POST", "/channels/c/messages")
    assert isinstance(body, bytes)
    assert b'name="file_image"; filename="cat.png"' in body
    assert b"E1" in body


@pytest.mark.parametrize(
    "arguments",
    [
        {"embed": pyqbot.Embed(title="t")},
        {"ark": pyqbot.Ark(template_id=23)},
        {"image": "https://example.com/a.png"},
        {"image_path": "cat.png"},
        {"image_data": b"png"},
        {"quote": pyqbot.GuildMessage(id="m", channel_id="c", guild_id="g")},
    ],
    ids=["embed", "ark", "image", "image-path", "image-data", "guild-message-quote"],
)
@pytest.mark.parametrize("data", [C2C_CLICK, GROUP_CLICK], ids=["c2c", "group"])
async def test_chat_interaction_reply_rejects_what_only_channels_send(
    data: object, arguments: dict[str, object]
) -> None:
    platform = Platform()
    event = interaction(data)

    async with client_for(platform) as client:
        bind_client(event, client)
        with pytest.raises(ValueError, match="单聊、群聊消息不支持"):
            await event.reply("x", **arguments)  # pyright: ignore[reportArgumentType]

    assert platform.requests == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"media": pyqbot.Media(file_info="f")},
        {"card": pyqbot.Card(title="t", description="d", url="https://a", pic_url="https://b")},
        {"quote": pyqbot.SentMessage(id="s")},
    ],
    ids=["media", "card", "sent-message-quote"],
)
async def test_guild_interaction_reply_rejects_what_channels_cannot_send(
    arguments: dict[str, object],
) -> None:
    platform = Platform()
    event = interaction({"id": "i", "chat_type": 0, "channel_id": "c"})

    async with client_for(platform) as client:
        bind_client(event, client)
        with pytest.raises(ValueError, match="频道消息不支持"):
            await event.reply("x", **arguments)  # pyright: ignore[reportArgumentType]

    assert platform.requests == []


@pytest.mark.parametrize(
    "data",
    [
        {"id": "i"},
        {"id": "i", "scene": "unknown"},
        {"id": "i", "chat_type": 9, "user_openid": "u"},
        {"id": "i", "chat_type": 2, "group_openid": "g"},
        {"id": "i", "chat_type": 1, "user_openid": "u"},
        {"id": "i", "chat_type": 0, "guild_id": "g"},
    ],
    ids=[
        "no-scene",
        "unknown-scene",
        "unknown-chat-type",
        "c2c-no-user",
        "group-no-group",
        "guild-no-channel",
    ],
)
async def test_reply_without_a_usable_scene_raises_before_sending(data: object) -> None:
    platform = Platform()
    event = interaction(data)

    async with client_for(platform) as client:
        bind_client(event, client)
        with pytest.raises(ValueError, match="无法回复这次互动"):
            await event.reply("收到")

    assert platform.requests == []


async def test_unusable_scene_error_does_not_echo_platform_text() -> None:
    event = interaction({"id": "i", "scene": f"leak {APP_SECRET}"})

    async with client_for(Platform()) as client:
        bind_client(event, client)
        with pytest.raises(ValueError, match="无法回复这次互动") as caught:
            await event.reply("收到")

    assert APP_SECRET not in str(caught.value)
    assert "chat_type=None" in str(caught.value)


async def test_reply_on_an_unbound_interaction_raises() -> None:
    with pytest.raises(RuntimeError, match="没有绑定 Client"):
        await pyqbot.Interaction(id="i", chat_type=pyqbot.ChatType.C2C, user_openid="u").reply("x")


async def test_dispatched_interaction_is_acked_and_replied_to() -> None:
    platform = Platform()
    done = asyncio.Event()

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Bot("app-id", APP_SECRET, http_client=http_client) as bot,
    ):

        @bot.on_interaction
        async def clicked(event: pyqbot.Interaction) -> None:
            await event.ack()
            await event.reply(f"你点了 {event.button_data}")
            done.set()

        assert bot._resolve_intents() == pyqbot.Intents.INTERACTION  # pyright: ignore[reportPrivateUsage]
        frame = {
            "op": 0,
            "s": 1,
            "t": "INTERACTION_CREATE",
            "id": "INTERACTION_CREATE:o",
            "d": C2C_CLICK,
        }
        bot._dispatcher.dispatch(decode_payload(json.dumps(frame)), bot)  # pyright: ignore[reportPrivateUsage]  代替 Bot.start()
        async with asyncio.timeout(HANG_GUARD):
            await done.wait()

    assert platform.requests == [
        ("PUT", "/interactions/1b13d569-4610-4ab9-bc51-feecc5def6d4", {"code": 0}),
        (
            "POST",
            "/v2/users/A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4/messages",
            {
                "msg_type": 0,
                "content": "你点了 confirm:once",
                "event_id": "INTERACTION_CREATE:o",
                "msg_seq": 1,
            },
        ),
    ]
