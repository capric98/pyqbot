import httpx2
import pytest


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """兜底：忘记注入替身的测试会在这里立刻失败，而不是把请求发到真实网络。"""

    async def refuse(self: httpx2.AsyncHTTPTransport, request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"本地测试不得访问真实网络：{request.method} {request.url}")

    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", refuse)
