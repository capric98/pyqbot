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
from pyqbot._models.upload import UploadPrepared

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
