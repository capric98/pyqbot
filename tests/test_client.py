import httpx2
import pytest

import pyqbot


def mock_http_client() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(lambda request: httpx2.Response(204)))


async def test_minimal_construction_uses_official_defaults() -> None:
    async with pyqbot.Client("app-id", "app-secret") as client:
        assert client.config == pyqbot.Config(app_id="app-id", app_secret="app-secret")


async def test_base_url_and_timeout_can_be_overridden() -> None:
    async with pyqbot.Client(
        "app-id", "app-secret", base_url="http://127.0.0.1:8080/", timeout=5
    ) as client:
        assert client.config.base_url == "http://127.0.0.1:8080"
        assert client.config.timeout == 5


async def test_numeric_app_id_is_accepted() -> None:
    async with pyqbot.Client(102000000, "app-secret") as client:
        assert client.config.app_id == "102000000"


def test_invalid_configuration_fails_at_construction() -> None:
    with pytest.raises(ValueError, match="app_secret 不能为空"):
        pyqbot.Client("app-id", "")


async def test_own_http_client_is_closed_on_exit() -> None:
    async with pyqbot.Client("app-id", "app-secret") as client:
        assert not client.is_closed
        assert not client.http_client.is_closed

    assert client.is_closed
    assert client.http_client.is_closed


async def test_injected_http_client_is_used_and_left_open() -> None:
    async with mock_http_client() as http_client:
        async with pyqbot.Client("app-id", "app-secret", http_client=http_client) as client:
            assert client.http_client is http_client

        assert client.is_closed
        assert not http_client.is_closed


async def test_client_is_closed_when_the_block_raises() -> None:
    client = pyqbot.Client("app-id", "app-secret")

    with pytest.raises(LookupError):
        async with client:
            raise LookupError

    assert client.http_client.is_closed


async def test_close_works_without_async_with_and_is_idempotent() -> None:
    client = pyqbot.Client("app-id", "app-secret")

    await client.close()
    await client.close()

    assert client.is_closed
    assert client.http_client.is_closed


async def test_closed_client_cannot_be_entered_again() -> None:
    client = pyqbot.Client("app-id", "app-secret")
    await client.close()

    with pytest.raises(RuntimeError, match="客户端已关闭"):
        await client.__aenter__()
