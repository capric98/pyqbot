"""代理：校验、经过代理的请求（接口、网关、其它下载）、账号密码的脱敏。"""

import asyncio
import logging
from base64 import b64encode
from collections.abc import Callable

import httpcore2
import httpx2
import pytest

import pyqbot

HANG_GUARD = 5  # 秒：回归时应失败而不是挂起
PASSWORD = "hunter2-proxy-password"
PROXY = f"socks5h://alice:{PASSWORD}@proxy.test:1080"
BASIC = b64encode(f"alice:{PASSWORD}".encode()).decode()  # Proxy-Authorization: Basic …
TOKEN = "token-value-never-shown"


class Transports:
    """记下每个 `AsyncHTTPTransport` 构造时的代理，以及每个请求经哪个代理发出。

    本地不能监听端口，所以在传输层的入口记录，再由 `respond` 扮演代理之后的平台。
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.proxies: dict[int, httpx2.Proxy | None] = {}
        self.routes: list[tuple[str, str | None]] = []  # （请求地址，代理的主机）
        self.respond: Callable[[httpx2.Request], httpx2.Response] = self.platform
        real_init: Callable[..., None] = httpx2.AsyncHTTPTransport.__init__
        transports = self

        def init(
            self: httpx2.AsyncHTTPTransport,
            *args: object,
            proxy: httpx2.Proxy | None = None,
            **kwargs: object,
        ) -> None:
            real_init(self, *args, proxy=proxy, **kwargs)  # socks5h 没装 socksio 时这里就报错
            transports.proxies[id(self)] = proxy

        async def handle(
            self: httpx2.AsyncHTTPTransport, request: httpx2.Request
        ) -> httpx2.Response:
            proxy = transports.proxies[id(self)]
            url = str(request.url.copy_with(query=None))
            transports.routes.append((url, None if proxy is None else proxy.url.host))
            return transports.respond(request)

        monkeypatch.setattr(httpx2.AsyncHTTPTransport, "__init__", init)
        monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", handle)

    @staticmethod
    def platform(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})
        if request.url.path == "/gateway":
            return httpx2.Response(200, json={"url": "wss://gateway.test/websocket"})
        if request.url.path == "/users/@me":
            return httpx2.Response(200, json={"id": "bot", "username": "测试机器人"})
        return httpx2.Response(200, content=b"attachment")


def assert_hidden(text: str) -> None:
    assert PASSWORD not in text
    assert "alice" not in text


@pytest.mark.parametrize(
    "proxy",
    ["http://127.0.0.1:7890", "https://proxy.test", "socks5://proxy.test:1080", PROXY],
)
def test_supported_proxies_are_accepted(proxy: str) -> None:
    config = pyqbot.Config(app_id="app-id", app_secret="app-secret", proxy=proxy)

    assert config.proxy == proxy
    assert_hidden(repr(config))


@pytest.mark.parametrize(
    "proxy",
    [
        f"ftp://alice:{PASSWORD}@proxy.test",
        f"alice:{PASSWORD}@proxy.test:1080",
        "socks5://",
        f"http://alice:{PASSWORD}@[::1",
    ],
)
def test_unsupported_proxies_are_rejected_without_echoing_them(proxy: str) -> None:
    with pytest.raises(ValueError, match="proxy 必须是完整的") as caught:
        pyqbot.Client("app-id", "app-secret", proxy=proxy)

    assert_hidden(str(caught.value))


async def test_proxy_and_http_client_are_mutually_exclusive() -> None:
    async with httpx2.AsyncClient() as http_client:
        with pytest.raises(ValueError, match="只能传一个") as caught:
            pyqbot.Bot("app-id", "app-secret", proxy=PROXY, http_client=http_client)

    assert_hidden(str(caught.value))


async def test_api_requests_and_other_downloads_go_through_the_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transports = Transports(monkeypatch)

    async with pyqbot.Client("app-id", "app-secret", proxy=PROXY) as client:
        await client.get_me()
        await client.http_client.get("https://multimedia.nt.qq.com.cn/download?fileid=x")
        assert_hidden(repr(client.config))

    assert transports.routes == [
        ("https://api.bot.qq.com/app/getAppAccessToken", "proxy.test"),
        ("https://api.bot.qq.com/users/@me", "proxy.test"),
        ("https://multimedia.nt.qq.com.cn/download", "proxy.test"),
    ]


async def test_without_a_proxy_requests_go_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "all_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    transports = Transports(monkeypatch)

    async with pyqbot.Client("app-id", "app-secret") as client:
        await client.get_me()

    assert {proxy for _, proxy in transports.routes} == {None}


def raise_with_password(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError(f"SOCKS5 认证失败：{PROXY}")


async def test_proxy_credentials_in_transport_errors_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transports = Transports(monkeypatch)
    transports.respond = raise_with_password

    async with pyqbot.Client("app-id", "app-secret", proxy=PROXY) as client:
        with pytest.raises(pyqbot.NetworkError) as caught:
            await client.get_me()

    assert_hidden(str(caught.value))
    assert caught.value.__cause__ is None  # 异常链里有密码，整条丢掉


@pytest.mark.parametrize(
    ("proxy", "echoed", "secrets"),
    [
        # 只有账号时它多半是令牌
        ("http://tok-123456@proxy.test:7890", "tok-123456", ["tok-123456"]),
        # 拒绝 CONNECT 时只回显账号
        (PROXY, "alice 认证失败", ["alice"]),
        # 有要转义的字符：转义前后两种写法都要藏
        (
            "http://al%40ce:p%40ss%3Aword@proxy.test",
            "al%40ce / al@ce / p%40ss%3Aword / p@ss:word",
            ["al%40ce", "al@ce", "p%40ss", "p@ss"],
        ),
        # 回显的是 HTTP 代理的鉴权头
        (PROXY, f"{BASIC} 无效", [BASIC]),
    ],
)
async def test_every_spelling_of_proxy_credentials_is_redacted(
    monkeypatch: pytest.MonkeyPatch, proxy: str, echoed: str, secrets: list[str]
) -> None:
    transports = Transports(monkeypatch)

    def echo(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError(f"代理回显：{echoed}")

    transports.respond = echo

    async with pyqbot.Client("app-id", "app-secret", proxy=proxy) as client:
        with pytest.raises(pyqbot.NetworkError) as caught:
            await client.get_me()

    for secret in secrets:
        assert secret not in str(caught.value)
    assert "代理回显：***" in str(caught.value)


class Disconnected(logging.Handler):
    """网关记下「连接断开」时置位，免得轮询日志。"""

    def __init__(self) -> None:
        super().__init__()
        self.seen = asyncio.Event()

    def emit(self, record: logging.LogRecord) -> None:
        if "网关连接断开" in record.getMessage():
            self.seen.set()


async def test_gateway_goes_through_the_proxy_and_its_logs_are_redacted(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    transports = Transports(monkeypatch)
    platform = transports.respond

    def gateway_refused(request: httpx2.Request) -> httpx2.Response:
        if request.url.scheme == "wss":
            raise_with_password(request)
        return platform(request)

    transports.respond = gateway_refused
    caplog.set_level(logging.WARNING, logger="pyqbot")
    disconnected = Disconnected()
    logging.getLogger("pyqbot").addHandler(disconnected)

    try:
        async with (
            asyncio.timeout(HANG_GUARD),
            pyqbot.Bot("app-id", "app-secret", proxy=PROXY) as bot,
        ):

            @bot.on_c2c_message
            async def ignore(message: pyqbot.C2CMessage) -> None:
                pass

            running = asyncio.create_task(bot.start())
            await disconnected.seen.wait()
            await bot.close()
            await running
    finally:
        logging.getLogger("pyqbot").removeHandler(disconnected)

    assert ("wss://gateway.test/websocket", "proxy.test") in transports.routes
    assert {proxy for _, proxy in transports.routes} == {"proxy.test"}
    assert_hidden(caplog.text)
    assert "SOCKS5 认证失败" in caplog.text


async def test_socks_credentials_stay_out_of_httpcore2_debug_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    socks_logger = logging.getLogger("httpcore2.socks")
    monkeypatch.setattr(socks_logger, "filters", [])  # 前面的用例可能已经挂上了
    caplog.set_level(logging.DEBUG, logger="httpcore2.socks")
    for _ in range(2):
        async with pyqbot.Client("app-id", "app-secret", proxy=PROXY):
            pass
    assert len(socks_logger.filters) == 1

    # httpcore2 真实的 SOCKS5 握手、替身网络：它的日志格式变了时这里会失败
    network = httpcore2.AsyncMockBackend(
        [
            b"\x05\x02",  # 选用账号密码认证
            b"\x01\x00",  # 认证通过
            b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x50",  # 已连上目标
            b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n",
        ]
    )
    async with httpcore2.AsyncSOCKSProxy(
        proxy_url="socks5://proxy.test:1080",
        proxy_auth=("alice", PASSWORD),
        network_backend=network,
    ) as proxy:
        await proxy.request("GET", "http://api.test/")

    assert "setup_socks5_connection.started" in caplog.text
    assert "auth=***" in caplog.text
    assert_hidden(caplog.text)
