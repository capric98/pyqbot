"""用实测得到的真实响应回归 SDK 的解析。样本脱敏后存在 `tests/fixtures/`，出处见 `docs/errata.md`。"""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx2
import pytest

import pyqbot
from pyqbot._gateway.payload import READY_EVENT, OpCode, Ready, decode_payload
from pyqbot._model import decode
from pyqbot._models.event import Event, bind_event_id, reply_fields
from pyqbot._models.upload import ImagePage, UploadPrepared

FIXTURES = Path(__file__).parent / "fixtures"


def sample(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


async def get_token_from(name: str) -> str:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=sample(name), headers={"X-Tps-trace-ID": "trace-1"})

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client,
        pyqbot.Client("app-id", "app-secret", http_client=http_client) as client,
    ):
        return await client.get_access_token()


@asynccontextmanager
async def client_answering_with(name: str) -> AsyncGenerator[pyqbot.Client]:
    """token 照常发；其它请求都回 `name` 这个样本。"""

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.startswith("/app/"):
            return httpx2.Response(200, content=sample("token_success.json"))
        return httpx2.Response(200, content=sample(name))

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client,
        pyqbot.Client("app-id", "app-secret", http_client=http_client) as client,
    ):
        yield client


async def test_sent_message_response_decodes() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        name = "token_success.json" if request.url.path.startswith("/app/") else "message_sent.json"
        return httpx2.Response(200, content=sample(name))

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client,
        pyqbot.Client("app-id", "app-secret", http_client=http_client) as client,
    ):
        sent = await client.users.send_message("0123456789ABCDEF0123456789ABCDEF", "你好")

    assert sent.id == "ROBOT1.0_fake-sent-message-id"
    assert sent.timestamp == datetime(2026, 11, 16, 12, 35, 16, tzinfo=timezone(timedelta(hours=8)))
    assert sent.ext_info is not None
    assert sent.ext_info.ref_idx == "REFIDX_fake"


async def test_expired_token_response_reports_the_err_code_not_the_legacy_code() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.startswith("/app/"):
            return httpx2.Response(200, content=sample("token_success.json"))
        return httpx2.Response(401, content=sample("api_token_expired.json"))

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client,
        pyqbot.Client("app-id", "app-secret", http_client=http_client) as client,
    ):
        with pytest.raises(pyqbot.APIError) as caught:
            await client.users.send_message("0123456789ABCDEF0123456789ABCDEF", "你好")

    error = caught.value
    assert (error.status_code, error.err_code) == (401, 40011027)
    assert error.trace_id == "0123456789abcdef0123456789abcdef"


async def test_token_response_with_string_expires_in_is_accepted() -> None:
    assert await get_token_from("token_success.json") == "fake-access-token"


async def test_wrong_secret_response_becomes_api_error_despite_http_200() -> None:
    with pytest.raises(pyqbot.APIError) as caught:
        await get_token_from("token_wrong_secret.json")

    error = caught.value
    assert (error.status_code, error.err_code, error.trace_id) == (200, 100016, "trace-1")
    assert "invalid appid or secret" in error.message


def test_ready_frame_decodes() -> None:
    payload = decode_payload(sample("gateway_ready.json"))
    ready = payload.decode_data(Ready)

    assert (payload.op, payload.t, payload.s) == (OpCode.DISPATCH, READY_EVENT, 1)
    assert ready.session_id == "00000000-0000-0000-0000-000000000000"
    assert ready.shard == (0, 1)
    assert ready.user is not None
    assert ready.user.id == "1234567890123456789"


def test_c2c_message_frame_keeps_its_data_for_the_event_layer() -> None:
    payload = decode_payload(sample("gateway_c2c_message_create.json"))
    data = json.loads(payload.data)

    assert (payload.op, payload.t, payload.s) == (OpCode.DISPATCH, "C2C_MESSAGE_CREATE", 2)
    assert data["author"]["user_openid"] == data["author"]["id"]
    assert data["timestamp"] == "2026-11-16T11:55:42+08:00"


async def test_bot_info_has_the_example_fields_not_the_table_ones() -> None:
    async with client_answering_with("bot_info.json") as client:
        me = await client.get_me()

    assert me.id == "1234567890123456789"
    assert me.share_url is not None
    assert me.share_url.startswith("https://qun.qq.com/")
    assert me.welcome_msg == ""
    assert (me.bot, me.union_openid, me.union_user_account) == (None, None, None)


async def test_share_link_response_with_retcode_decodes() -> None:
    async with client_answering_with("share_link.json") as client:
        url = await client.generate_share_link()

    assert url == "https://bot.q.qq.com/s/fakeLink"


async def test_unset_menu_is_an_empty_object_without_version() -> None:
    async with client_answering_with("menu_unset.json") as client:
        current = await client.menu.get()

    assert current.version is None
    assert current.items == ()


def test_upload_prepare_numbers_parts_from_one() -> None:
    prepared = decode(sample("upload_prepared.json"), UploadPrepared)

    assert (prepared.first_index, prepared.chunk_size, len(prepared.parts)) == (1, 3602158, 1)
    assert prepared.upload_config.retry_delay == 1


def event_from[E: Event](name: str, type_: type[E]) -> E:
    payload = decode_payload(sample(name))
    event = payload.decode_data(type_)
    bind_event_id(event, payload.id)
    return event


def test_friend_add_from_a_share_link_keeps_the_callback_data_with_default_scene() -> None:
    event = event_from("gateway_friend_add.json", pyqbot.FriendAdd)

    assert event.event_id == "FRIEND_ADD:00000000-0000-0000-0000-000000000001"
    assert (event.scene, event.scene_param) == (pyqbot.FriendAddScene.DEFAULT, "pyqbot-live")
    assert event.short_code == "fakeCode01"
    assert event.author.union_openid == ""
    assert reply_fields(event)["event_id"] == event.event_id


def test_friend_del_has_an_author_with_empty_union_openid() -> None:
    event = event_from("gateway_friend_del.json", pyqbot.FriendDel)

    assert event.event_id == "FRIEND_DEL:00000000-0000-0000-0000-000000000002"
    assert event.author.union_openid == ""


def test_authorize_interaction_has_no_chat_type_and_replies_with_the_outer_id() -> None:
    event = event_from("gateway_interaction_authorize.json", pyqbot.Interaction)

    assert event.type == pyqbot.InteractionType.USER_AUTHORIZE
    assert (event.chat_type, event.data.type) == (None, None)
    assert event.id == "00000000-0000-0000-0000-000000000003"
    authorize = event.data.resolved.authorize_data
    assert authorize is not None
    assert (authorize.opt_scene, authorize.scope) == (
        pyqbot.AuthorizeOptScene.SETTING,
        pyqbot.AuthorizeScope.C2C_PUSH,
    )
    assert reply_fields(event)["event_id"] == "INTERACTION_CREATE:" + event.id


def test_media_image_list_gives_times_as_digit_strings() -> None:
    [image] = decode(sample("media_images_list.json"), ImagePage).images

    assert image.created_at == 1794861718
    assert image.expires_at is not None
    assert image.expires_at - image.created_at == 90 * 24 * 3600  # 文档示例约 7 天，实测是 90 天


def test_group_add_robot_replies_with_the_outer_id() -> None:
    event = event_from("gateway_group_add_robot.json", pyqbot.GroupAddRobot)

    assert event.group_openid == "FEDCBA9876543210FEDCBA9876543210"
    assert reply_fields(event)["event_id"] == "GROUP_ADD_ROBOT:00000000-0000-0000-0000-000000000004"


def test_group_at_message_keeps_the_leading_space_and_the_group_nickname() -> None:
    message = event_from("gateway_group_at_message_create.json", pyqbot.GroupAtMessage)

    assert message.content == " /ping"
    assert message.author.member_nickname == "测试群名片"
    assert message.author.member_role == pyqbot.GroupMemberRole.ADMIN
    assert message.author.member_openid == "0123456789ABCDEF0123456789ABCDEF"
    assert reply_fields(message)["msg_id"] == "ROBOT1.0_fake-group-message-id"


def test_authorize_interaction_carries_switch_only_when_turned_on() -> None:
    off = event_from("gateway_interaction_authorize.json", pyqbot.Interaction)
    on = event_from("gateway_interaction_authorize_on.json", pyqbot.Interaction)

    assert off.data.resolved.authorize_data is not None
    assert on.data.resolved.authorize_data is not None
    assert (off.data.resolved.authorize_data.switch, on.data.resolved.authorize_data.switch) == (
        False,
        True,
    )


def test_group_member_events_carry_an_empty_union_openid() -> None:
    added = event_from("gateway_group_member_add.json", pyqbot.GroupMemberAdd)
    removed = event_from("gateway_group_member_remove.json", pyqbot.GroupMemberRemove)

    assert (added.union_openid, removed.union_openid) == ("", "")
    assert removed.user_openid is None
    assert added.event_id == "GROUP_MEMBER_ADD:00000000-0000-0000-0000-000000000006"


def test_all_mode_mention_arrives_as_a_plain_group_message() -> None:
    message = event_from("gateway_group_message_create_mention.json", pyqbot.GroupMessage)

    assert type(message) is pyqbot.GroupMessage  # 全量模式下 @ 消息不是 GroupAtMessage
    assert message.content == "<@B0B0B0B0B0B0B0B0B0B0B0B0B0B0B0B0> 测试一下at"
    assert message.mentions_me
    [mention] = message.mentions
    assert (mention.is_you, mention.bot, mention.scope) == (True, True, "single")
    assert reply_fields(message)["msg_id"] == "ROBOT1.0_fake-group-message-with-mention"


def test_mentions_me_is_false_without_is_you_and_always_true_for_at_messages() -> None:
    plain = pyqbot.GroupMessage(
        id="m",
        group_openid="g",
        mentions=(pyqbot.GroupMessageMember(member_openid="x"),),
        author=pyqbot.GroupMessageAuthor(member_openid="member"),
    )
    at = pyqbot.GroupAtMessage(
        id="m", group_openid="g", author=pyqbot.GroupMessageAuthor(member_openid="member")
    )

    assert (plain.mentions_me, at.mentions_me) == (False, True)
