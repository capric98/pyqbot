# pyright: reportUnnecessaryTypeIgnoreComment=true
# 上面这行让本文件里的 ignore 都必须真的有错可压：装饰器的类型变宽时，类型检查测试会失败。

import asyncio
import contextlib
import functools
import json
import logging
from collections.abc import Coroutine
from pathlib import Path

import httpx2
import pytest

import pyqbot
from pyqbot._gateway.payload import decode_payload

HANG_GUARD = 5  # 秒：并发测试回归时应失败而不是挂起
C2C_SAMPLE = Path(__file__).parent / "fixtures" / "gateway_c2c_message_create.json"


async def test_bot_is_a_client_built_from_the_same_arguments() -> None:
    async with pyqbot.Bot(
        102000000, "app-secret", base_url="http://127.0.0.1:8080", timeout=5
    ) as bot:
        assert isinstance(bot, pyqbot.Client)
        assert bot.config == pyqbot.Config(
            app_id="102000000",
            app_secret="app-secret",
            base_url="http://127.0.0.1:8080",
            timeout=5,
        )


def test_invalid_configuration_fails_at_construction() -> None:
    with pytest.raises(ValueError, match="app_id 不能为空"):
        pyqbot.Bot("", "app-secret")


async def test_bot_closes_its_own_http_client_on_exit() -> None:
    async with pyqbot.Bot("app-id", "app-secret") as bot:
        assert not bot.is_closed

    assert bot.is_closed
    assert bot.http_client.is_closed


async def test_injected_http_client_is_used_and_left_open() -> None:
    transport = httpx2.MockTransport(lambda request: httpx2.Response(204))

    async with httpx2.AsyncClient(transport=transport) as http_client:
        async with pyqbot.Bot("app-id", "app-secret", http_client=http_client) as bot:
            assert bot.http_client is http_client

        assert bot.is_closed
        assert not http_client.is_closed


async def test_close_is_idempotent_and_final() -> None:
    bot = pyqbot.Bot("app-id", "app-secret")

    await bot.close()
    await bot.close()

    with pytest.raises(RuntimeError, match="Bot 已关闭"):
        await bot.__aenter__()


# ---- 事件注册 ----


async def test_decorators_return_the_handler_unchanged() -> None:
    async with pyqbot.Bot("app-id", "app-secret") as bot:

        async def on_c2c(message: pyqbot.C2CMessage) -> None: ...

        async def on_group(message: pyqbot.GroupMessage) -> None: ...

        assert bot.on_c2c_message(on_c2c) is on_c2c
        assert bot.on_group_at_message(on_group) is on_group
        assert bot.on_c2c_message(on_c2c) is on_c2c  # 同一事件可以注册多个，包括同一个函数


async def test_sync_handler_is_rejected_at_registration() -> None:
    async with pyqbot.Bot("app-id", "app-secret") as bot:

        def on_c2c(message: pyqbot.C2CMessage) -> None: ...

        async def handle(message: pyqbot.GroupMessage) -> None: ...

        def on_group(message: pyqbot.GroupMessage) -> Coroutine[None, None, None]:
            return handle(message)  # 类型检查放行，但不是 async def

        with pytest.raises(TypeError, match="async def"):
            bot.on_c2c_message(on_c2c)  # pyright: ignore[reportArgumentType]  验证运行期检查
        with pytest.raises(TypeError, match="on_group"):
            bot.on_group_at_message(on_group)

        assert bot._resolve_intents() == pyqbot.Intents(0)  # pyright: ignore[reportPrivateUsage]


async def test_handler_for_the_wrong_event_type_is_a_type_error() -> None:
    async with pyqbot.Bot("app-id", "app-secret") as bot:

        async def on_group(message: pyqbot.GroupMessage) -> None: ...

        # 本文件开启了 reportUnnecessaryTypeIgnoreComment：pyright 不再报错时这里会失败。
        bot.on_c2c_message(on_group)  # pyright: ignore[reportArgumentType]


async def test_intents_follow_the_registered_handlers_unless_given() -> None:
    async def on_c2c(message: pyqbot.C2CMessage) -> None: ...

    async with (
        pyqbot.Bot("app-id", "app-secret") as derived,
        pyqbot.Bot("app-id", "app-secret", intents=pyqbot.Intents.GUILDS) as given,
        pyqbot.Bot("app-id", "app-secret", intents=pyqbot.Intents(0)) as empty,
    ):
        assert derived._resolve_intents() == pyqbot.Intents(0)  # pyright: ignore[reportPrivateUsage]
        for bot in (derived, given, empty):
            bot.on_c2c_message(on_c2c)

        assert derived._resolve_intents() == pyqbot.Intents.GROUP_AND_C2C_EVENT  # pyright: ignore[reportPrivateUsage]
        assert given._resolve_intents() == pyqbot.Intents.GUILDS  # pyright: ignore[reportPrivateUsage]
        assert empty._resolve_intents() == pyqbot.Intents(0)  # pyright: ignore[reportPrivateUsage]


async def test_close_cancels_running_handlers() -> None:
    started, cancelled = asyncio.Event(), asyncio.Event()
    bot = pyqbot.Bot("app-id", "app-secret")

    @bot.on_c2c_message
    async def stuck(message: pyqbot.C2CMessage) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    bot._dispatcher.dispatch(decode_payload(C2C_SAMPLE.read_bytes()), bot)  # pyright: ignore[reportPrivateUsage]  代替 Bot.start()
    async with asyncio.timeout(HANG_GUARD):
        await started.wait()
        await bot.close()

    assert cancelled.is_set()
    assert bot.is_closed


async def test_real_c2c_message_is_dispatched_and_replied_to() -> None:
    requests: list[tuple[str, object]] = []
    replied = asyncio.Event()

    def platform(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": "t", "expires_in": "7200"})
        requests.append((request.url.path, json.loads(request.content)))
        return httpx2.Response(200, json={"id": "ROBOT1.0_sent"})

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform)) as http_client,
        pyqbot.Bot("app-id", "app-secret", http_client=http_client) as bot,
    ):

        @bot.on_c2c_message
        async def reply(message: pyqbot.C2CMessage) -> None:
            sent = await message.reply("收到")
            assert sent.id == "ROBOT1.0_sent"
            replied.set()

        # 网关接入前，由测试代替 Bot.start() 把 Dispatch 交给分发器。
        bot._dispatcher.dispatch(decode_payload(C2C_SAMPLE.read_bytes()), bot)  # pyright: ignore[reportPrivateUsage]
        async with asyncio.timeout(HANG_GUARD):
            await replied.wait()

    assert requests == [
        (
            "/v2/users/0123456789ABCDEF0123456789ABCDEF/messages",
            {"msg_type": 0, "content": "收到", "msg_id": "ROBOT1.0_fake-message-id", "msg_seq": 1},
        )
    ]


# ---- 关闭与日志脱敏 ----

TOKEN = "token-value-never-logged"


def feed(bot: pyqbot.Bot) -> None:
    """不连网关，直接把真实的单聊样本交给分发器。"""
    bot._dispatcher.dispatch(decode_payload(C2C_SAMPLE.read_bytes()), bot)  # pyright: ignore[reportPrivateUsage]


async def test_handlers_closing_the_bot_from_cleanup_do_not_wait_for_each_other() -> None:
    first_started, first_cleaned, second_closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    bot = pyqbot.Bot("app-id", "app-secret")

    @bot.on_c2c_message
    async def first(message: pyqbot.C2CMessage) -> None:
        first_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await bot.close()
            first_cleaned.set()

    @bot.on_c2c_message
    async def second(message: pyqbot.C2CMessage) -> None:
        await first_started.wait()
        await bot.close()
        second_closed.set()

    feed(bot)
    async with asyncio.timeout(HANG_GUARD):
        await asyncio.gather(first_cleaned.wait(), second_closed.wait())
        await bot.close()

    assert bot.is_closed


async def test_concurrent_close_lets_handlers_finish_their_cleanup() -> None:
    started, cleaning = asyncio.Event(), asyncio.Event()
    release, cleaned = asyncio.Event(), asyncio.Event()
    bot = pyqbot.Bot("app-id", "app-secret")

    @bot.on_c2c_message
    async def careful(message: pyqbot.C2CMessage) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            cleaned.set()

    feed(bot)
    async with asyncio.timeout(HANG_GUARD):
        await started.wait()
        first = asyncio.create_task(bot.close())
        await cleaning.wait()
        # eager_start：第二次 close() 同步跑到挂起为止，该发的取消（如果有）此时已经发出。
        second = asyncio.create_task(bot.close(), eager_start=True)
        release.set()
        await asyncio.gather(first, second)

    assert cleaned.is_set()
    assert bot.is_closed


async def test_close_returns_even_if_a_handler_swallows_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, release = asyncio.Event(), asyncio.Event()
    bot = pyqbot.Bot("app-id", "app-secret")
    dispatcher = bot._dispatcher  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(
        dispatcher, "aclose", functools.partial(dispatcher.aclose, grace_period=0.01)
    )
    finished: list[asyncio.Task[object]] = []

    @bot.on_c2c_message
    async def stubborn(message: pyqbot.C2CMessage) -> None:
        task = asyncio.current_task()
        assert task is not None
        finished.append(task)
        started.set()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.Event().wait()
        await release.wait()

    feed(bot)
    async with asyncio.timeout(HANG_GUARD):
        await started.wait()
        await bot.close()
        assert bot.is_closed
        release.set()
        await asyncio.wait(finished)


async def test_handler_errors_echoing_credentials_are_redacted_in_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failed = asyncio.Event()

    def platform(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform)) as http_client,
        pyqbot.Bot("app-id", "app-secret", http_client=http_client) as bot,
    ):

        @bot.on_c2c_message
        async def leaky(message: pyqbot.C2CMessage) -> None:
            token = await bot.get_access_token()
            failed.set()
            try:
                raise ValueError("app-secret 被回显了")
            except ValueError as exc:
                raise httpx2.ConnectError(f"连接失败：Authorization: QQBot {token}") from exc

        with caplog.at_level(logging.ERROR, logger="pyqbot"):
            feed(bot)
            async with asyncio.timeout(HANG_GUARD):
                await failed.wait()
            await bot.close()  # 等处理函数的日志写完

    assert "ConnectError" in caplog.text
    assert TOKEN not in caplog.text
    assert "app-secret" not in caplog.text
    assert "QQBot ***" in caplog.text
