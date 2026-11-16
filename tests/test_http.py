"""请求层：地址与鉴权头、解码、失败映射、脱敏。经 `client.users.send_message` 等公共入口驱动。"""

import json
import traceback
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx2
import pytest

import pyqbot
from pyqbot._http import HTTP

APP_SECRET = "secret-value-never-shown"
TOKEN = "token-value-never-shown"
OPENID = "0123456789ABCDEF0123456789ABCDEF"
SENT = {
    "id": "ROBOT1.0_sent",
    "timestamp": "2026-07-21T10:30:00+08:00",
    "ext_info": {"ref_idx": "REFIDX_abc=="},
}

type Respond = Callable[[httpx2.Request], httpx2.Response]


class Platform:
    """扮演开放平台：签发固定的 token，其余请求记下来并交给 `respond`。"""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.respond: Respond = lambda request: httpx2.Response(200, json=SENT)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})
        self.requests.append(request)
        return self.respond(request)


def responding(response: httpx2.Response) -> Respond:
    return lambda request: response


def raising(error: Exception) -> Respond:
    def respond(request: httpx2.Request) -> httpx2.Response:
        raise error

    return respond


@asynccontextmanager
async def client_for(
    platform: Platform, *, base_url: str = "https://api.bot.qq.com", request_timeout: float = 30
) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client(
            "app-id",
            APP_SECRET,
            base_url=base_url,
            timeout=request_timeout,
            http_client=http_client,
        ) as client,
    ):
        yield client


async def send(platform: Platform) -> pyqbot.SentMessage:
    async with client_for(platform) as client:
        return await client.users.send_message(OPENID, "你好")


async def test_user_message_is_posted_with_auth_header_and_timeout() -> None:
    platform = Platform()

    async with client_for(platform, request_timeout=7) as client:
        await client.users.send_message(OPENID, "你好")

    [request] = platform.requests
    assert (request.method, str(request.url)) == (
        "POST",
        f"https://api.bot.qq.com/v2/users/{OPENID}/messages",
    )
    assert request.headers["Authorization"] == f"QQBot {TOKEN}"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == {"msg_type": 0, "content": "你好"}
    assert request.extensions["timeout"]["read"] == 7


async def test_group_message_goes_to_the_group_endpoint() -> None:
    platform = Platform()

    async with client_for(platform, base_url="http://127.0.0.1:8080/") as client:
        await client.groups.send_message("GROUP", "大家好")

    [request] = platform.requests
    assert str(request.url) == "http://127.0.0.1:8080/v2/groups/GROUP/messages"
    assert json.loads(request.content) == {"msg_type": 0, "content": "大家好"}


async def test_successful_response_is_decoded_into_a_sent_message() -> None:
    sent = await send(Platform())

    assert isinstance(sent, pyqbot.SentMessage)
    assert sent.id == "ROBOT1.0_sent"
    assert sent.timestamp == datetime(2026, 7, 21, 10, 30, tzinfo=timezone(timedelta(hours=8)))
    assert sent.ext_info is not None
    assert sent.ext_info.ref_idx == "REFIDX_abc=="
    assert sent.to_dict() == SENT


async def test_unexpected_success_fields_do_not_fail_the_call() -> None:
    platform = Platform()
    platform.respond = responding(
        httpx2.Response(200, json={"id": "m", "timestamp": "yesterday", "err_code": 0, "new": 1})
    )

    sent = await send(platform)

    assert (sent.id, sent.timestamp, sent.ext_info) == ("m", None, None)


async def test_path_parameters_are_escaped() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        await client.users.send_message("a/../b?c", "x")

    assert platform.requests[0].url.raw_path == b"/v2/users/a%2F..%2Fb%3Fc/messages"


@pytest.mark.parametrize("openid", ["", ".", ".."])
async def test_unusable_openid_is_rejected_before_sending(openid: str) -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match="openid 不合法"):
            await client.groups.send_message(openid, "x")

    assert platform.requests == []


async def test_gateway_url_is_fetched_with_auth() -> None:
    platform = Platform()
    platform.respond = responding(httpx2.Response(200, json={"url": "wss://gateway.test/ws"}))

    async with client_for(platform) as client:
        url = await client._get_gateway_url()  # pyright: ignore[reportPrivateUsage]  供 Bot 使用

    assert url == "wss://gateway.test/ws"
    [request] = platform.requests
    assert (request.method, str(request.url)) == ("GET", "https://api.bot.qq.com/gateway")
    assert request.headers["Authorization"] == f"QQBot {TOKEN}"


async def test_gateway_response_without_url_is_an_api_error() -> None:
    platform = Platform()
    platform.respond = responding(httpx2.Response(200, json={}))

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="响应无法识别"):
            await client._get_gateway_url()  # pyright: ignore[reportPrivateUsage]  供 Bot 使用


async def test_closed_client_refuses_to_send() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        pass

    with pytest.raises(RuntimeError, match="已关闭"):
        await client.users.send_message(OPENID, "x")
    assert platform.requests == []


async def test_token_failure_is_raised_without_calling_the_api() -> None:
    paths: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        return httpx2.Response(200, json={"code": 100016, "message": "invalid appid or secret"})

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(handle)) as http_client,
        pyqbot.Client("app-id", APP_SECRET, http_client=http_client) as client,
    ):
        with pytest.raises(pyqbot.APIError) as caught:
            await client.users.send_message(OPENID, "x")

    assert caught.value.err_code == 100016
    assert paths == ["/app/getAppAccessToken"]


@pytest.mark.parametrize("field", ["err_code", "code"])
@pytest.mark.parametrize(
    ("code", "err_code"),
    [(40034005.0, 40034005), (1.5, None), (True, None), ({"n": 1}, None), ([1], None)],
)
async def test_error_code_of_an_unexpected_type_still_means_failure(
    field: str, code: object, err_code: int | None
) -> None:
    platform = Platform()
    platform.respond = responding(httpx2.Response(200, json={field: code, "message": "rejected"}))

    with pytest.raises(pyqbot.APIError, match="rejected") as caught:
        await send(platform)

    assert caught.value.err_code == err_code


@pytest.mark.parametrize("where", ["header", "body"])
async def test_credentials_echoed_in_the_trace_id_are_redacted(where: str) -> None:
    echoed = f"trace-{TOKEN}-{APP_SECRET}"
    body = {"err_code": 11243, "message": "denied"}
    headers: dict[str, str] = {}
    if where == "header":
        headers["X-Tps-trace-ID"] = echoed
    else:
        body["trace_id"] = echoed
    platform = Platform()
    platform.respond = responding(httpx2.Response(401, json=body, headers=headers))

    with pytest.raises(pyqbot.APIError) as caught:
        await send(platform)

    shown = "".join(traceback.format_exception(caught.value))
    assert TOKEN not in shown
    assert APP_SECRET not in shown
    assert caught.value.trace_id == "trace-***-***"


# 失败映射：(响应, 状态码, err_code, trace_id, 文案片段)
FAILURES = {
    "4xx-with-error-body": (
        httpx2.Response(
            400, json={"err_code": 40034005, "message": "回复消息msg_id已过期", "trace_id": "t-1"}
        ),
        400,
        40034005,
        "t-1",
        "回复消息msg_id已过期",
    ),
    "2xx-with-err_code": (
        httpx2.Response(200, json={"err_code": "40054005", "message": "消息被去重"}),
        200,
        40054005,
        None,
        "消息被去重",
    ),
    "202-async-with-error-body": (
        httpx2.Response(202, json={"code": 304023, "message": "push message is waiting for audit"}),
        202,
        304023,
        None,
        "waiting for audit",
    ),
    "2xx-with-unparseable-code": (
        httpx2.Response(200, json={"err_code": "oops", "id": "m"}),
        200,
        None,
        None,
        "HTTP 200",
    ),
    "5xx-without-json": (
        httpx2.Response(502, text="<html>Bad Gateway</html>"),
        502,
        None,
        None,
        "无法解析响应（HTTP 502）",
    ),
    "5xx-empty-body": (httpx2.Response(504), 504, None, None, "HTTP 504"),
    "4xx-empty-object": (httpx2.Response(429, json={}), 429, None, None, "HTTP 429"),
    "4xx-json-array": (httpx2.Response(404, json=[]), 404, None, None, "HTTP 404"),
    "2xx-without-json": (
        httpx2.Response(200, text="ok"),
        200,
        None,
        None,
        "无法解析响应（HTTP 200）",
    ),
    "2xx-wrong-shape": (httpx2.Response(200, json=[SENT]), 200, None, None, "响应无法识别"),
    "2xx-empty-body": (httpx2.Response(204), 204, None, None, "响应无法识别"),
    "2xx-deeply-nested": (
        httpx2.Response(200, content=b'{"message": ' + b"[" * 100_000 + b"]" * 100_000 + b"}"),
        200,
        None,
        None,
        "无法解析",
    ),
}


@pytest.mark.parametrize(
    ("response", "status_code", "err_code", "trace_id", "message"),
    FAILURES.values(),
    ids=FAILURES.keys(),
)
async def test_failures_become_api_errors(
    response: httpx2.Response,
    status_code: int,
    err_code: int | None,
    trace_id: str | None,
    message: str,
) -> None:
    platform = Platform()
    platform.respond = responding(response)

    with pytest.raises(pyqbot.APIError) as caught:
        await send(platform)

    error = caught.value
    assert (error.status_code, error.err_code, error.trace_id) == (status_code, err_code, trace_id)
    assert message in error.message
    assert f"POST /v2/users/{OPENID}/messages" in error.message


async def test_trace_id_header_wins_over_body() -> None:
    platform = Platform()
    platform.respond = responding(
        httpx2.Response(
            500,
            json={"err_code": 500000, "trace_id": "from-body"},
            headers={"X-Tps-trace-ID": "from-header"},
        )
    )

    with pytest.raises(pyqbot.APIError) as caught:
        await send(platform)

    assert caught.value.trace_id == "from-header"


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (httpx2.ConnectError("connection refused"), "connection refused"),
        (httpx2.ReadTimeout("timed out"), "请求超时"),
        (httpx2.RemoteProtocolError(""), "RemoteProtocolError"),
    ],
)
async def test_transport_failures_become_network_errors(error: Exception, message: str) -> None:
    platform = Platform()
    platform.respond = raising(error)

    with pytest.raises(pyqbot.NetworkError, match=message) as caught:
        await send(platform)

    assert caught.value.__cause__ is error


def assert_hidden(error: BaseException, *secrets: str) -> None:
    shown = "".join(traceback.format_exception(error))  # 日志里打印的就是它，含异常链
    for secret in secrets:
        assert secret not in str(error)
        assert secret not in repr(error)
        assert secret not in shown
    assert "***" in str(error)


@pytest.mark.parametrize("status_code", [200, 401])
async def test_credentials_echoed_by_the_platform_are_redacted(status_code: int) -> None:
    platform = Platform()
    platform.respond = responding(
        httpx2.Response(
            status_code,
            json={"err_code": 11243, "message": f"bad token {TOKEN}, secret {APP_SECRET}"},
        )
    )

    with pytest.raises(pyqbot.APIError) as caught:
        await send(platform)

    assert_hidden(caught.value, TOKEN, APP_SECRET)
    assert caught.value.err_code == 11243


async def test_credentials_in_transport_error_text_are_redacted() -> None:
    platform = Platform()
    platform.respond = raising(httpx2.ConnectError(f"proxy said: QQBot {TOKEN}"))

    with pytest.raises(pyqbot.NetworkError) as caught:
        await send(platform)

    assert_hidden(caught.value, TOKEN)


async def test_requests_without_body_and_responses_without_content() -> None:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(204)

    async def get_token() -> str:
        return TOKEN

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handle)) as http_client:
        http = HTTP(pyqbot.Config(app_id="a", app_secret="s"), http_client, get_token, tuple)
        result = await http.request("DELETE", "/x", type_=None, params={"page": 2})

    assert result is None
    [request] = seen
    assert str(request.url) == "https://api.bot.qq.com/x?page=2"
    assert request.content == b""
    assert "Content-Type" not in request.headers


@pytest.mark.parametrize(
    ("response", "failure"),
    [
        (httpx2.Response(200, json={}), None),
        (httpx2.Response(200, json={"err_code": 0}), None),
        (httpx2.Response(200, json={"err_code": 1}), "HTTP 200"),
        (httpx2.Response(404), "HTTP 404"),
    ],
)
async def test_responses_without_a_type_only_check_for_failure(
    response: httpx2.Response, failure: str | None
) -> None:
    async def get_token() -> str:
        return TOKEN

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _: response)) as client:
        http = HTTP(pyqbot.Config(app_id="a", app_secret="s"), client, get_token, tuple)
        if failure is None:
            assert await http.request("DELETE", "/x", type_=None) is None
        else:
            with pytest.raises(pyqbot.APIError, match=failure):
                await http.request("DELETE", "/x", type_=None)


async def test_token_replaced_before_this_request_is_still_redacted() -> None:
    # 网关还在用的旧 token 被平台回显时，它不是本次请求用的那个，但同样不能进入异常。
    def handle(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(403, json={"err_code": 11243, "message": "bad token-old"})

    async def get_token() -> str:
        return "token-new"

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handle)) as http_client:
        http = HTTP(
            pyqbot.Config(app_id="a", app_secret="s"),
            http_client,
            get_token,
            lambda: (APP_SECRET, "token-new", "token-old"),
        )
        with pytest.raises(pyqbot.APIError) as caught:
            await http.request("GET", "/gateway", type_=None)

    assert "token-old" not in "".join(traceback.format_exception(caught.value))
    assert "bad ***" in str(caught.value)
