import asyncio
import json
import traceback
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx2
import pytest

import pyqbot
from pyqbot._credentials import _TokenResponse  # pyright: ignore[reportPrivateUsage]  检查 repr
from pyqbot._gateway.payload import (
    _IdentifyData,  # pyright: ignore[reportPrivateUsage]  检查 repr
    _ResumeData,  # pyright: ignore[reportPrivateUsage]  检查 repr
)
from pyqbot._model import Model

APP_ID = "102000000"
APP_SECRET = "secret-value-never-shown"
TOKEN_URL = "https://api.bot.qq.com/app/getAppAccessToken"
HANG_GUARD = 5  # 秒：并发测试回归时应失败而不是挂起

type Handler = Callable[[httpx2.Request], Awaitable[httpx2.Response]]


class FakeClock:
    """替换凭证模块读取的两个时钟，可以分别拨动。

    不要替换 `time.monotonic`：事件循环也在用它。
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monotonic = 1_000.0
        self.wall = 1_800_000_000.0
        monkeypatch.setattr("pyqbot._credentials.monotonic", lambda: self.monotonic)
        monkeypatch.setattr("pyqbot._credentials.wall_time", lambda: self.wall)

    def advance(self, seconds: float) -> None:
        self.monotonic += seconds
        self.wall += seconds

    def sleep_machine(self, seconds: float) -> None:
        """模拟机器睡眠：单调时钟停走，只有墙上时钟前进。"""
        self.wall += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return FakeClock(monkeypatch)


class TokenServer:
    """扮演获取 token 的接口：默认每次签发一个新 token，有效期 7200 秒（与文档示例一样是字符串）。"""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.expires_in: object = "7200"
        self.respond: Handler | None = None

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.respond is not None:
            return await self.respond(request)
        return token_response(f"token-{len(self.requests)}", self.expires_in)


def token_response(token: str, expires_in: object = "7200") -> httpx2.Response:
    return httpx2.Response(200, json={"access_token": token, "expires_in": expires_in})


def responding(response: httpx2.Response) -> Handler:
    async def respond(request: httpx2.Request) -> httpx2.Response:
        return response

    return respond


def raising(error: Exception) -> Handler:
    async def respond(request: httpx2.Request) -> httpx2.Response:
        raise error

    return respond


@asynccontextmanager
async def client_for(
    server: TokenServer, *, base_url: str = "https://api.bot.qq.com", request_timeout: float = 30
) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(server.handle)) as http_client,
        pyqbot.Client(
            APP_ID, APP_SECRET, base_url=base_url, timeout=request_timeout, http_client=http_client
        ) as client,
    ):
        yield client


async def test_first_call_fetches_token_from_the_documented_endpoint() -> None:
    server = TokenServer()

    async with client_for(server, request_timeout=7) as client:
        token = await client.get_access_token()

    assert token == "token-1"
    [request] = server.requests
    assert (request.method, str(request.url)) == ("POST", TOKEN_URL)
    assert json.loads(request.content) == {"appId": APP_ID, "clientSecret": APP_SECRET}
    assert request.extensions["timeout"]["read"] == 7


async def test_custom_base_url_is_used_for_the_token_endpoint() -> None:
    server = TokenServer()

    async with client_for(server, base_url="http://127.0.0.1:8080/") as client:
        await client.get_access_token()

    assert str(server.requests[0].url) == "http://127.0.0.1:8080/app/getAppAccessToken"


@pytest.mark.parametrize("expires_in", ["7200", 7200, 7200.0])
async def test_expires_in_is_accepted_as_string_or_number(
    clock: FakeClock, expires_in: object
) -> None:
    server = TokenServer()
    server.expires_in = expires_in

    async with client_for(server) as client:
        await client.get_access_token()
        clock.advance(7100)
        assert await client.get_access_token() == "token-1"

    assert len(server.requests) == 1


async def test_token_is_refreshed_inside_the_last_minute_before_expiry(clock: FakeClock) -> None:
    server = TokenServer()

    async with client_for(server) as client:
        await client.get_access_token()
        clock.advance(7200 - 50 - 0.001)
        assert await client.get_access_token() == "token-1"
        clock.advance(0.001)
        assert await client.get_access_token() == "token-2"
        assert await client.get_access_token() == "token-2"

    assert len(server.requests) == 2


async def test_lifetime_is_counted_from_before_the_request(clock: FakeClock) -> None:
    server = TokenServer()

    async def slow_first(request: httpx2.Request) -> httpx2.Response:
        if len(server.requests) == 1:
            clock.advance(100)  # 请求在途 100 秒
        return token_response(f"token-{len(server.requests)}")

    server.respond = slow_first

    async with client_for(server) as client:
        assert await client.get_access_token() == "token-1"
        clock.advance(7200 - 50 - 100)
        assert await client.get_access_token() == "token-2"


async def test_short_lived_token_is_refreshed_at_half_life_instead_of_every_call(
    clock: FakeClock,
) -> None:
    # 拿到一个只剩 40 秒的 token 时，提前 50 秒刷新意味着每次调用都要请求；改为过半再刷新。
    server = TokenServer()
    server.expires_in = 40

    async with client_for(server) as client:
        await client.get_access_token()
        clock.advance(19.9)
        assert await client.get_access_token() == "token-1"
        clock.advance(0.1)
        assert await client.get_access_token() == "token-2"

    assert len(server.requests) == 2


async def test_machine_sleep_is_noticed_through_the_wall_clock(clock: FakeClock) -> None:
    server = TokenServer()

    async with client_for(server) as client:
        await client.get_access_token()
        clock.sleep_machine(3 * 3600)
        assert await client.get_access_token() == "token-2"


async def test_wall_clock_set_backwards_does_not_delay_refresh(clock: FakeClock) -> None:
    server = TokenServer()

    async with client_for(server) as client:
        await client.get_access_token()
        clock.advance(7200)
        clock.wall -= 3 * 3600
        assert await client.get_access_token() == "token-2"


async def test_concurrent_calls_share_a_single_request() -> None:
    server = TokenServer()
    release = asyncio.Event()

    async def slow(request: httpx2.Request) -> httpx2.Response:
        await release.wait()
        return token_response("shared")

    server.respond = slow

    async with (
        asyncio.timeout(HANG_GUARD),
        client_for(server) as client,
        asyncio.TaskGroup() as group,
    ):
        tasks = [group.create_task(client.get_access_token()) for _ in range(10)]
        await asyncio.sleep(0)
        release.set()

    assert [task.result() for task in tasks] == ["shared"] * 10
    assert len(server.requests) == 1


async def test_concurrent_callers_share_the_failure_too() -> None:
    server = TokenServer()
    release = asyncio.Event()

    async def slow_failure(request: httpx2.Request) -> httpx2.Response:
        await release.wait()
        return httpx2.Response(200, json={"code": 100016, "message": "invalid appid or secret"})

    server.respond = slow_failure

    async with asyncio.timeout(HANG_GUARD), client_for(server) as client:
        calls = [asyncio.create_task(client.get_access_token()) for _ in range(5)]
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.gather(*calls, return_exceptions=True)

    assert all(isinstance(result, pyqbot.APIError) for result in results)
    assert {result.err_code for result in results if isinstance(result, pyqbot.APIError)} == {
        100016
    }
    assert len(server.requests) == 1


async def test_waiters_take_over_when_the_fetching_call_is_cancelled() -> None:
    server = TokenServer()
    first_request_started = asyncio.Event()

    async def hang_first_then_answer(request: httpx2.Request) -> httpx2.Response:
        if len(server.requests) == 1:
            first_request_started.set()
            await asyncio.Event().wait()  # 一直挂起，直到被取消
        return token_response("after-cancel")

    server.respond = hang_first_then_answer

    async with asyncio.timeout(HANG_GUARD), client_for(server) as client:
        leader = asyncio.create_task(client.get_access_token())
        await first_request_started.wait()
        waiter = asyncio.create_task(client.get_access_token())
        await asyncio.sleep(0)
        leader.cancel()

        assert await waiter == "after-cancel"
        with pytest.raises(asyncio.CancelledError):
            await leader

    assert len(server.requests) == 2


async def test_cancelling_a_waiter_does_not_disturb_the_fetch() -> None:
    server = TokenServer()
    release = asyncio.Event()

    async def slow(request: httpx2.Request) -> httpx2.Response:
        await release.wait()
        return token_response("kept")

    server.respond = slow

    async with asyncio.timeout(HANG_GUARD), client_for(server) as client:
        leader = asyncio.create_task(client.get_access_token())
        await asyncio.sleep(0)
        waiter = asyncio.create_task(client.get_access_token())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        release.set()
        assert await leader == "kept"

    assert len(server.requests) == 1


async def test_business_error_with_http_200_raises_api_error() -> None:
    server = TokenServer()
    server.respond = responding(
        httpx2.Response(
            200,
            json={"code": 100016, "message": "invalid appid or secret"},
            headers={"X-Tps-trace-ID": "trace-from-header"},
        )
    )

    async with client_for(server) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.get_access_token()

    error = caught.value
    assert (error.status_code, error.err_code, error.trace_id) == (
        200,
        100016,
        "trace-from-header",
    )
    assert "invalid appid or secret" in error.message


async def test_generic_error_body_with_err_code_is_understood() -> None:
    server = TokenServer()
    server.respond = responding(
        httpx2.Response(500, json={"err_code": 500000, "message": "处理失败", "trace_id": "t-1"})
    )

    async with client_for(server) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.get_access_token()

    assert (caught.value.status_code, caught.value.err_code, caught.value.trace_id) == (
        500,
        500000,
        "t-1",
    )


@pytest.mark.parametrize(("code", "err_code"), [("100007", 100007), ("not-a-number", None)])
async def test_string_error_codes_still_fail(code: str, err_code: int | None) -> None:
    server = TokenServer()
    server.respond = responding(
        httpx2.Response(200, json={"code": code, "access_token": "x", "expires_in": 7200})
    )

    async with client_for(server) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.get_access_token()

    assert caught.value.err_code == err_code


async def test_zero_code_alongside_a_token_means_success() -> None:
    server = TokenServer()
    server.respond = responding(
        httpx2.Response(200, json={"code": 0, "access_token": "ok", "expires_in": "7200"})
    )

    async with client_for(server) as client:
        assert await client.get_access_token() == "ok"


async def test_http_error_without_body_raises_api_error_with_status() -> None:
    server = TokenServer()
    server.respond = responding(httpx2.Response(502, text="<html>Bad Gateway</html>"))

    async with client_for(server) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.get_access_token()

    assert (caught.value.status_code, caught.value.err_code) == (502, None)
    assert caught.value.__cause__ is not None


async def test_http_error_with_empty_json_reports_the_status() -> None:
    server = TokenServer()
    server.respond = responding(httpx2.Response(429, json={}))

    async with client_for(server) as client:
        with pytest.raises(pyqbot.APIError, match="HTTP 429"):
            await client.get_access_token()


@pytest.mark.parametrize(
    "body",
    [
        {"expires_in": 7200},
        {"access_token": "", "expires_in": 7200},
        {"access_token": "x"},
        {"access_token": "x", "expires_in": "soon"},
        {"access_token": "x", "expires_in": 0},
        {"access_token": "x", "expires_in": -1},
        {"access_token": "x", "expires_in": "inf"},
    ],
)
async def test_success_response_without_usable_token_raises_api_error(body: object) -> None:
    server = TokenServer()
    server.respond = responding(httpx2.Response(200, json=body))

    async with client_for(server) as client:
        with pytest.raises(pyqbot.APIError, match="缺少有效的 access_token"):
            await client.get_access_token()


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (httpx2.ConnectError("connection refused"), "connection refused"),
        (httpx2.ReadTimeout("timed out"), "请求超时"),
        (httpx2.RemoteProtocolError(""), "RemoteProtocolError"),
    ],
)
async def test_transport_failures_raise_network_error(error: Exception, message: str) -> None:
    server = TokenServer()
    server.respond = raising(error)

    async with client_for(server) as client:
        with pytest.raises(pyqbot.NetworkError, match=message) as caught:
            await client.get_access_token()

    assert caught.value.__cause__ is error


async def test_failed_refresh_falls_back_to_the_unexpired_old_token(clock: FakeClock) -> None:
    server = TokenServer()

    async with client_for(server) as client:
        await client.get_access_token()
        clock.advance(7200 - 30)
        server.respond = raising(httpx2.ConnectError("down"))
        assert await client.get_access_token() == "token-1"
        assert await client.get_access_token() == "token-1"  # 没有冷却：每次都重试
        assert len(server.requests) == 3

        clock.advance(30)
        with pytest.raises(pyqbot.NetworkError):
            await client.get_access_token()


async def test_unexpected_errors_are_not_masked_by_the_old_token(clock: FakeClock) -> None:
    server = TokenServer()

    async with client_for(server) as client:
        await client.get_access_token()
        clock.advance(7200 - 30)
        server.respond = raising(LookupError("bug"))
        with pytest.raises(LookupError):
            await client.get_access_token()


async def test_token_that_expired_while_in_flight_is_not_returned(clock: FakeClock) -> None:
    server = TokenServer()

    async def sleep_during_request(request: httpx2.Request) -> httpx2.Response:
        clock.sleep_machine(7200)
        return token_response("stale-on-arrival")

    server.respond = sleep_during_request

    async with client_for(server) as client:
        with pytest.raises(pyqbot.NetworkError, match="有效期"):
            await client.get_access_token()


async def test_minor_fields_of_the_wrong_type_do_not_hide_the_error_code() -> None:
    server = TokenServer()
    server.respond = responding(
        httpx2.Response(200, json={"code": 100016, "message": {"zh": "错误"}, "trace_id": 42})
    )

    async with client_for(server) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.get_access_token()

    assert (caught.value.err_code, caught.value.trace_id) == (100016, None)


async def test_deeply_nested_response_is_an_api_error() -> None:
    server = TokenServer()
    server.respond = responding(
        httpx2.Response(200, content=b'{"message": ' + b"[" * 100_000 + b"]" * 100_000 + b"}")
    )

    async with client_for(server) as client:
        with pytest.raises(pyqbot.APIError, match="无法解析"):
            await client.get_access_token()


async def test_failures_are_not_cached() -> None:
    server = TokenServer()
    server.respond = raising(httpx2.ConnectError("down"))

    async with client_for(server) as client:
        with pytest.raises(pyqbot.NetworkError):
            await client.get_access_token()
        server.respond = None
        assert await client.get_access_token() == "token-2"


def assert_hidden(error: BaseException, *secrets: str) -> None:
    shown = "".join(traceback.format_exception(error))  # 日志里打印的就是它，含异常链
    for secret in secrets:
        assert secret not in str(error)
        assert secret not in repr(error)
        assert secret not in shown
    assert "***" in str(error)


async def test_secret_echoed_by_the_platform_is_redacted() -> None:
    server = TokenServer()
    server.respond = responding(
        httpx2.Response(200, json={"code": 100016, "message": f"bad secret {APP_SECRET}"})
    )

    async with client_for(server) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.get_access_token()

    assert_hidden(caught.value, APP_SECRET)
    assert caught.value.err_code == 100016


async def test_secret_in_transport_error_text_is_redacted() -> None:
    server = TokenServer()
    server.respond = raising(httpx2.ConnectError(f"proxy said: {APP_SECRET}"))

    async with client_for(server) as client:
        with pytest.raises(pyqbot.NetworkError) as caught:
            await client.get_access_token()

    assert_hidden(caught.value, APP_SECRET)


async def test_known_tokens_echoed_by_the_platform_are_redacted(clock: FakeClock) -> None:
    server = TokenServer()

    async with client_for(server) as client:
        await client.get_access_token()
        clock.advance(7200)  # token-1 已过期，刷新失败时不能再退回它
        server.respond = responding(
            httpx2.Response(
                200,
                json={"code": 1, "message": "old token-1, new token-9", "access_token": "token-9"},
            )
        )
        with pytest.raises(pyqbot.APIError) as caught:
            await client.get_access_token()

    assert_hidden(caught.value, "token-1", "token-9")


async def test_token_replaced_by_a_refresh_is_still_redacted(clock: FakeClock) -> None:
    server = TokenServer()

    async with client_for(server) as client:
        await client.get_access_token()  # token-1
        clock.advance(7200)
        await client.get_access_token()  # 换成了 token-2，token-1 平台还会再认 60 秒
        clock.advance(7200)
        server.respond = responding(
            httpx2.Response(200, json={"code": 1, "message": "prior token-1, current token-2"})
        )
        with pytest.raises(pyqbot.APIError) as caught:
            await client.get_access_token()

    assert_hidden(caught.value, "token-1", "token-2")


@pytest.mark.parametrize("where", ["header", "body"])
async def test_secret_echoed_in_the_trace_id_is_redacted(where: str) -> None:
    echoed = f"trace-{APP_SECRET}"
    body = {"code": 100016, "message": "bad secret"}
    headers: dict[str, str] = {}
    if where == "header":
        headers["X-Tps-trace-ID"] = echoed
    else:
        body["trace_id"] = echoed
    server = TokenServer()
    server.respond = responding(httpx2.Response(200, json=body, headers=headers))

    async with client_for(server) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.get_access_token()

    assert caught.value.trace_id == "trace-***"
    assert APP_SECRET not in "".join(traceback.format_exception(caught.value))


async def test_error_code_of_an_unexpected_type_still_means_failure() -> None:
    server = TokenServer()
    server.respond = responding(
        httpx2.Response(200, json={"code": True, "access_token": "token-9", "expires_in": "7200"})
    )

    async with client_for(server) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.get_access_token()

    assert caught.value.err_code is None


def test_token_holding_structures_hide_the_token() -> None:
    token = "tok-abcdef"
    structures: list[Model] = [
        _TokenResponse(access_token=token, expires_in=7200),
        _IdentifyData(token=token, intents=1, shard=(0, 1), properties={}),
        _ResumeData(token=token, session_id="s", seq=1),
    ]

    for structure in structures:
        assert token not in repr(structure)
        assert token not in repr(list(structure.__rich_repr__()))


async def test_closed_client_refuses_to_fetch() -> None:
    server = TokenServer()

    async with client_for(server) as client:
        pass

    with pytest.raises(RuntimeError, match="Client 已关闭"):
        await client.get_access_token()
    assert server.requests == []


async def test_bot_reaches_the_token_through_its_client() -> None:
    server = TokenServer()

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(server.handle)) as http_client,
        pyqbot.Bot(APP_ID, APP_SECRET, http_client=http_client) as bot,
    ):
        assert await bot.get_access_token() == "token-1"
