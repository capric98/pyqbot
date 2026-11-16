# pyright: reportUnnecessaryTypeIgnoreComment=true
# 打开上面这条，下面「pyright 拒绝」的那几行若不再报错，pyright 就会报「多余的 ignore」。
"""发消息：内容模型的编码、msg_type 推断、参数组合、引用、召回、正在输入与撤回。"""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx2
import pytest

import pyqbot
from pyqbot._model import decode
from pyqbot._models.event import next_msg_seq
from pyqbot._models.message import MessageScene

APP_SECRET = "secret-value-never-shown"
SENT = {"id": "ROBOT1.0_sent", "ext_info": {"ref_idx": "REFIDX_sent"}}
CARD = pyqbot.Card(title="标题", description="描述", url="https://a", pic_url="https://b/1.png")


class Platform:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, object] | None]] = []
        self.response = httpx2.Response(200, json=SENT)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": "t", "expires_in": "7200"})
        body: dict[str, object] | None = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.raw_path.decode(), body))
        return self.response

    def bodies(self) -> list[dict[str, object]]:
        return [body for _, _, body in self.requests if body is not None]


@asynccontextmanager
async def client_for(platform: Platform) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client("app-id", APP_SECRET, http_client=http_client) as client,
    ):
        yield client


def c2c(message_id: str = "m") -> pyqbot.C2CMessage:
    return pyqbot.C2CMessage(id=message_id, author=pyqbot.C2CUser(user_openid="u"))


# ---- msg_type 推断与请求体 ----


async def test_text_can_still_be_passed_positionally() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        sent = await client.users.send_message("u", "你好")

    assert sent.id == "ROBOT1.0_sent"
    assert platform.requests == [
        ("POST", "/v2/users/u/messages", {"msg_type": 0, "content": "你好"})
    ]


async def test_markdown_with_keyboard_is_sent_as_msg_type_2() -> None:
    platform = Platform()
    keyboard = pyqbot.Keyboard.from_rows(
        [pyqbot.Button.callback("赞", "like", id="1"), pyqbot.Button.link("主页", "https://x")],
        [pyqbot.Button.command("帮助", "/help", enter=True, style=pyqbot.ButtonStyle.BLUE_FILLED)],
    )

    async with client_for(platform) as client:
        await client.groups.send_message("g", markdown="**你好**", keyboard=keyboard)

    everyone = {"type": 2}
    assert platform.requests == [
        (
            "POST",
            "/v2/groups/g/messages",
            {
                "msg_type": 2,
                "markdown": {"content": "**你好**"},
                "keyboard": {
                    "content": {
                        "rows": [
                            {
                                "buttons": [
                                    {
                                        "render_data": {
                                            "label": "赞",
                                            "visited_label": "赞",
                                            "style": 0,
                                        },
                                        "action": {
                                            "type": 1,
                                            "data": "like",
                                            "permission": everyone,
                                        },
                                        "id": "1",
                                    },
                                    {
                                        "render_data": {
                                            "label": "主页",
                                            "visited_label": "主页",
                                            "style": 0,
                                        },
                                        "action": {
                                            "type": 0,
                                            "data": "https://x",
                                            "permission": everyone,
                                        },
                                    },
                                ]
                            },
                            {
                                "buttons": [
                                    {
                                        "render_data": {
                                            "label": "帮助",
                                            "visited_label": "帮助",
                                            "style": 4,
                                        },
                                        "action": {
                                            "type": 2,
                                            "data": "/help",
                                            "permission": everyone,
                                            "enter": True,
                                        },
                                    }
                                ]
                            },
                        ]
                    }
                },
            },
        )
    ]


async def test_markdown_object_media_and_card_pick_their_msg_type() -> None:
    platform = Platform()
    markdown = pyqbot.Markdown(content="![图](https://x)", force_verify_image_resource=True)
    media = decode(b'{"file_uuid": "u", "file_info": "F", "ttl": 300, "new": 1}', pyqbot.Media)

    async with client_for(platform) as client:
        await client.users.send_message("u", markdown=markdown)
        await client.users.send_message("u", media=media)
        await client.users.send_message("u", "看图", media=media)
        await client.groups.send_message("g", card=CARD)

    assert media == pyqbot.Media(file_uuid="u", file_info="F", ttl=300)
    assert platform.bodies() == [
        {
            "msg_type": 2,
            "markdown": {"content": "![图](https://x)", "force_verify_image_resource": True},
        },
        {"msg_type": 7, "media": {"file_info": "F"}},
        {"msg_type": 7, "content": "看图", "media": {"file_info": "F"}},
        {
            "msg_type": 8,
            "card": {
                "type": "tuwen",
                "content": {
                    "title": "标题",
                    "description": "描述",
                    "url": "https://a",
                    "pic_url": "https://b/1.png",
                },
            },
        },
    ]


async def test_markdown_template_is_encoded_with_its_params() -> None:
    platform = Platform()
    markdown = pyqbot.Markdown.from_template("tpl", params={"title": "标题", "items": ["a", "b"]})

    async with client_for(platform) as client:
        await client.users.send_message("u", markdown=markdown)

    assert platform.bodies() == [
        {
            "msg_type": 2,
            "markdown": {
                "custom_template_id": "tpl",
                "params": [
                    {"key": "title", "values": ["标题"]},
                    {"key": "items", "values": ["a", "b"]},
                ],
            },
        }
    ]
    assert pyqbot.Markdown.from_template("tpl") == pyqbot.Markdown(custom_template_id="tpl")


@pytest.mark.parametrize(
    ("arguments", "match"),
    [
        ({}, "没有要发送的内容"),
        ({"markdown": "a", "media": pyqbot.Media(file_info="F")}, "markdown、media 只能传一个"),
        ({"media": pyqbot.Media(file_info="F"), "card": CARD}, "media、card 只能传一个"),
        ({"content": "a", "markdown": "b"}, "不能再传 content"),
        ({"content": "a", "keyboard": pyqbot.Keyboard(id="k")}, "keyboard 只能随 markdown"),
        ({"content": "a", "quote": ""}, "quote 没有可用的引用索引"),
        ({"content": "a", "quote": pyqbot.SentMessage(id="s")}, r"引用索引（SentMessage）"),
        ({"content": "a", "quote": c2c()}, r"引用索引（C2CMessage）"),
        ({"content": "a", "reply_to": c2c(), "wakeup": True}, "wakeup 不能与 reply_to"),
    ],
)
async def test_invalid_combinations_are_rejected_before_sending(
    arguments: dict[str, object], match: str
) -> None:
    platform = Platform()
    reply_to = arguments.get("reply_to")

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match=match):
            await client.users.send_message("u", **arguments)  # pyright: ignore[reportArgumentType]

    assert platform.requests == []
    if isinstance(reply_to, pyqbot.C2CMessage):
        # 被拒绝的请求不占用 msg_seq。
        async with client_for(platform) as client:
            await client.users.send_message("u", "a", reply_to=reply_to)
        assert platform.bodies()[0] == {"msg_type": 0, "content": "a", "msg_id": "m", "msg_seq": 1}


async def test_quote_accepts_sent_and_received_messages_and_indexes() -> None:
    platform = Platform()
    received = pyqbot.GroupAtMessage(
        id="m", group_openid="g", message_scene=MessageScene(ext=("msg_idx=REFIDX_in",))
    )

    async with client_for(platform) as client:
        sent = await client.groups.send_message("g", "第一条")
        await client.groups.send_message("g", "引用发出的", quote=sent)
        await client.groups.send_message("g", "引用收到的", quote=received)
        await client.groups.send_message("g", "引用索引", quote="REFIDX_raw")

    assert [body.get("message_reference") for body in platform.bodies()] == [
        None,
        {"message_id": "REFIDX_sent"},
        {"message_id": "REFIDX_in"},
        {"message_id": "REFIDX_raw"},
    ]


async def test_wakeup_marks_an_active_c2c_message() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        await client.users.send_message("u", "好久不见", wakeup=True)

    assert platform.bodies() == [{"msg_type": 0, "content": "好久不见", "is_wakeup": True}]


# ---- 正在输入 ----


async def test_typing_is_sent_as_msg_type_6_and_its_response_is_not_decoded() -> None:
    platform = Platform()
    platform.response = httpx2.Response(200, json={"unexpected": True})

    async with client_for(platform) as client:
        assert await client.users.send_typing("u") is None

    assert platform.requests == [
        (
            "POST",
            "/v2/users/u/messages",
            {"msg_type": 6, "input_notify": {"input_type": 1, "input_second": 60}},
        )
    ]


@pytest.mark.parametrize("seconds", [0, 61, -1, True])
async def test_typing_duration_must_be_an_integer_between_1_and_60(seconds: int) -> None:
    platform = Platform()
    message = c2c()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match="seconds 必须是 1～60 之间的整数"):
            await client.users.send_typing("u", seconds=seconds, reply_to=message)

    assert platform.requests == []
    assert next_msg_seq(message) == 1  # 本地拒绝的请求不占用 msg_seq


# ---- 撤回 ----


async def test_recall_accepts_ids_and_messages() -> None:
    platform = Platform()
    platform.response = httpx2.Response(200, json={})

    async with client_for(platform) as client:
        await client.users.recall_message("u", "ROBOT1.0_a/b")
        await client.users.recall_message("u", pyqbot.SentMessage(id="s"))
        await client.groups.recall_message("g", pyqbot.GroupAtMessage(id="m", group_openid="g"))
        await client.groups.recall_message("g", pyqbot.SentMessage(id="s"))

    assert platform.requests == [
        ("DELETE", "/v2/users/u/messages/ROBOT1.0_a%2Fb", None),
        ("DELETE", "/v2/users/u/messages/s", None),
        ("DELETE", "/v2/groups/g/messages/m", None),
        ("DELETE", "/v2/groups/g/messages/s", None),
    ]


async def test_recall_rejects_an_empty_message_id() -> None:
    async with client_for(Platform()) as client:
        with pytest.raises(ValueError, match="message_id 不合法"):
            await client.users.recall_message("u", "")


async def test_recall_failure_hides_credentials_echoed_by_the_platform() -> None:
    platform = Platform()
    platform.response = httpx2.Response(
        400, json={"err_code": 40064004, "message": f"超出撤回时限 {APP_SECRET} t"}
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.groups.recall_message("g", "m")

    assert caught.value.err_code == 40064004
    assert APP_SECRET not in str(caught.value)
    assert "DELETE /v2/groups/g/messages/m 失败" in str(caught.value)


# ---- 内容模型 ----


@pytest.mark.parametrize(
    ("arguments", "match"),
    [
        ({}, "content 与 custom_template_id 必须二选一"),
        ({"content": "a", "custom_template_id": "t"}, "必须二选一"),
        ({"content": "a", "params": (pyqbot.MarkdownParam(key="k"),)}, "params 只能与"),
    ],
)
def test_markdown_needs_exactly_one_source(arguments: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        pyqbot.Markdown(**arguments)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    "arguments", [{}, {"id": "k", "content": pyqbot.KeyboardContent()}], ids=["none", "both"]
)
def test_keyboard_needs_either_a_template_or_rows(arguments: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="id 与 content 必须二选一"):
        pyqbot.Keyboard(**arguments)  # pyright: ignore[reportArgumentType]


def test_button_factories_fill_what_the_platform_expects() -> None:
    modal = pyqbot.ButtonModal(content="确定？", confirm_text="是")
    callback = pyqbot.Button.callback(
        "投票",
        "vote",
        visited_label="已投",
        group_id="g1",
        permission=pyqbot.ButtonPermission.users("A", "B"),
        modal=modal,
        unsupport_tips="请升级",
    )
    command = pyqbot.Button.command(
        "选图", "/pic", reply=True, permission=pyqbot.ButtonPermission.admins()
    )

    assert callback.to_dict() == {
        "render_data": {"label": "投票", "visited_label": "已投", "style": 0},
        "action": {
            "type": 1,
            "data": "vote",
            "permission": {"type": 0, "specify_user_ids": ["A", "B"]},
            "unsupport_tips": "请升级",
            "modal": {"content": "确定？", "confirm_text": "是"},
        },
        "group_id": "g1",
    }
    assert command.action.permission == pyqbot.ButtonPermission.admins()
    assert command.action.to_dict()["reply"] is True
    assert "enter" not in command.action.to_dict()
    assert pyqbot.ButtonPermission.roles("r").to_dict() == {"type": 3, "specify_role_ids": ["r"]}
    assert pyqbot.ButtonPermission.everyone().type == pyqbot.ButtonPermissionType.EVERYONE


def test_buttons_can_be_built_field_by_field() -> None:
    button = pyqbot.Button(
        render_data=pyqbot.ButtonRenderData(label="图"),
        action=pyqbot.ButtonAction(type=pyqbot.ButtonActionType.COMMAND, data="/pic", anchor=1),
    )

    assert button.to_dict() == {
        "render_data": {"label": "图"},
        "action": {"type": 2, "data": "/pic", "anchor": 1},
    }


# ---- 类型 ----


async def wrong_scene_is_rejected_by_pyright(client: pyqbot.Client) -> None:
    """不运行，只给 pyright 看：群聊的回复对象不能传给单聊接口，反之亦然。"""
    group = pyqbot.GroupAtMessage(id="m", group_openid="g")
    await client.users.send_message("u", "x", reply_to=group)  # pyright: ignore[reportArgumentType]
    await client.users.send_typing("u", reply_to=group)  # pyright: ignore[reportArgumentType]
    await client.users.send_message("u", "x", quote=group)  # pyright: ignore[reportArgumentType]
    await client.groups.send_message("g", "x", reply_to=c2c())  # pyright: ignore[reportArgumentType]
    await client.groups.recall_message("g", c2c())  # pyright: ignore[reportArgumentType]
