import httpx2
import pytest

import pyqbot


async def test_bot_builds_its_client_from_the_same_arguments() -> None:
    async with pyqbot.Bot(
        102000000, "app-secret", base_url="http://127.0.0.1:8080", timeout=5
    ) as bot:
        assert isinstance(bot.client, pyqbot.Client)
        assert bot.client.config == pyqbot.Config(
            app_id="102000000",
            app_secret="app-secret",
            base_url="http://127.0.0.1:8080",
            timeout=5,
        )


def test_invalid_configuration_fails_at_construction() -> None:
    with pytest.raises(ValueError, match="app_id 不能为空"):
        pyqbot.Bot("", "app-secret")


async def test_bot_closes_its_client_on_exit() -> None:
    async with pyqbot.Bot("app-id", "app-secret") as bot:
        assert not bot.client.is_closed

    assert bot.client.is_closed
    assert bot.client.http_client.is_closed


async def test_injected_http_client_is_passed_through_and_left_open() -> None:
    transport = httpx2.MockTransport(lambda request: httpx2.Response(204))

    async with httpx2.AsyncClient(transport=transport) as http_client:
        async with pyqbot.Bot("app-id", "app-secret", http_client=http_client) as bot:
            assert bot.client.http_client is http_client

        assert bot.client.is_closed
        assert not http_client.is_closed


async def test_close_is_idempotent_and_final() -> None:
    bot = pyqbot.Bot("app-id", "app-secret")

    await bot.close()
    await bot.close()

    with pytest.raises(RuntimeError, match="机器人已关闭"):
        await bot.__aenter__()
