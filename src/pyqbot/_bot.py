"""事件驱动的机器人。"""

from types import TracebackType
from typing import Self

import httpx2

from ._client import Client
from ._config import DEFAULT_BASE_URL, DEFAULT_TIMEOUT


class Bot:
    """事件驱动的机器人，建立在 `Client` 之上。

    构造参数与 `Client` 相同；`Bot` 会创建并持有一个 `Client`，通过 `client` 属性调用接口。

    Example:
        ```python
        async with pyqbot.Bot("APP_ID", "APP_SECRET") as bot:
            client = bot.client
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
        """创建机器人。

        Args:
            app_id: 机器人的 AppID，在开放平台管理端获得。
            app_secret: 机器人的 AppSecret，在开放平台管理端获得。
            base_url: API 地址，默认是官方地址 `https://api.bot.qq.com`。
            timeout: 单次请求的超时时间，单位秒。
            http_client: 自备的 `httpx2.AsyncClient`，含义与 `Client` 的同名参数相同。

        Raises:
            ValueError: 凭证为空、`base_url` 不是完整的 http(s) 地址，或 `timeout` 不是正数。
        """
        self._client = Client(
            app_id,
            app_secret,
            base_url=base_url,
            timeout=timeout,
            http_client=http_client,
        )

    @property
    def client(self) -> Client:
        """本机器人使用的 API 客户端，生命周期由机器人管理。"""
        return self._client

    async def close(self) -> None:
        """关闭机器人及其 API 客户端，可以重复调用。"""
        await self._client.close()

    async def __aenter__(self) -> Self:
        """进入 `async with`。

        Raises:
            RuntimeError: 机器人已经关闭。
        """
        if self._client.is_closed:
            raise RuntimeError("机器人已关闭，不能再次使用，请新建一个 Bot")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """退出 `async with` 时关闭机器人。"""
        await self.close()
