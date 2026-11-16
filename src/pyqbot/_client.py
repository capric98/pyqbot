"""API 客户端。"""

from types import TracebackType
from typing import Self

import httpx2

from ._config import DEFAULT_BASE_URL, DEFAULT_TIMEOUT, Config


class Client:
    """QQ 机器人 API 客户端，可以脱离 `Bot` 单独使用。

    推荐用 `async with` 管理生命周期；不方便时也可以直接构造，用完后调用 `close()`。
    构造时不产生任何网络请求。

    Example:
        ```python
        async with pyqbot.Client("APP_ID", "APP_SECRET") as client:
            ...
        ```
    """

    def __init__(
        self,
        app_id: str | int,
        app_secret: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        """创建客户端。

        Args:
            app_id: 机器人的 AppID，在开放平台管理端获得。
            app_secret: 机器人的 AppSecret，在开放平台管理端获得。
            base_url: API 地址，默认是官方地址 `https://api.bot.qq.com`。
            timeout: 单次请求的超时时间，单位秒。
            http_client: 自备的 `httpx2.AsyncClient`，用于配置代理、证书、连接池等。
                传入后由调用方负责关闭；它自身的 `base_url` 和 `timeout` 不会被使用，
                以这里的 `base_url` 和 `timeout` 为准。不传则由客户端自建并负责关闭。

        Raises:
            ValueError: 凭证为空、`base_url` 不是完整的 http(s) 地址，或 `timeout` 不是正数。
        """
        self._config = Config(
            app_id=str(app_id) if isinstance(app_id, int) else app_id,
            app_secret=app_secret,
            base_url=base_url,
            timeout=timeout,
        )
        self._owns_http_client = http_client is None
        self._http_client = httpx2.AsyncClient() if http_client is None else http_client
        self._closed = False

    @property
    def config(self) -> Config:
        """本客户端的只读配置。"""
        return self._config

    @property
    def http_client(self) -> httpx2.AsyncClient:
        """底层的 `httpx2.AsyncClient`：构造时传入的那个，或客户端自建的那个。"""
        return self._http_client

    @property
    def is_closed(self) -> bool:
        """客户端是否已关闭。"""
        return self._closed

    async def close(self) -> None:
        """关闭客户端并释放连接，可以重复调用。

        只会关闭客户端自建的 `httpx2.AsyncClient`；构造时传入的由调用方自己关闭。
        """
        if self._closed:
            return
        self._closed = True
        if self._owns_http_client:
            await self._http_client.aclose()

    async def __aenter__(self) -> Self:
        """进入 `async with`。

        Raises:
            RuntimeError: 客户端已经关闭。
        """
        if self._closed:
            raise RuntimeError("客户端已关闭，不能再次使用，请新建一个 Client")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """退出 `async with` 时关闭客户端。"""
        await self.close()
