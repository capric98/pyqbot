"""API 客户端。"""

from types import TracebackType
from typing import Self

import httpx2

from ._api.groups import Groups
from ._api.images import Images
from ._api.interactions import Interactions
from ._api.users import Users
from ._config import DEFAULT_BASE_URL, DEFAULT_TIMEOUT, Config
from ._credentials import AccessTokenManager
from ._http import HTTP
from ._models.gateway import Gateway
from ._redact import redact


class Client:
    """QQ 机器人 API 客户端，可以脱离 `Bot` 单独使用。

    推荐用 `async with` 管理生命周期，也可以直接构造、用完后调用 `close()`。构造时不发请求。

    Args:
        app_id: 机器人的 AppID，在开放平台管理端获得。
        app_secret: 机器人的 AppSecret，在开放平台管理端获得。
        timeout: 单次请求的超时时间，单位秒。
        http_client: 自备的 `httpx2.AsyncClient`，用于配置代理、证书、连接池等，由调用方负责关闭；
            它自身的 `base_url` 和 `timeout` 不会被使用。不传则由客户端自建并负责关闭。

    Attributes:
        users: 单聊接口，如 `client.users.send_message(...)`。
        groups: 群聊接口，如 `client.groups.send_message(...)`。
        images: 素材库（Markdown 里引用的图片），如 `client.images.upload(path=...)`。
        interactions: 互动事件接口，如 `client.interactions.ack(...)`。

    Raises:
        ValueError: 凭证为空、`base_url` 不是完整的 http(s) 地址，或 `timeout` 不是正数。

    Example:
        ```python
        async with pyqbot.Client("APP_ID", "APP_SECRET") as client:
            await client.users.send_message(openid, "你好")
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
        self._config = Config(
            app_id=str(app_id) if isinstance(app_id, int) else app_id,
            app_secret=app_secret,
            base_url=base_url,
            timeout=timeout,
        )
        self._owns_http_client = http_client is None
        self._http_client = httpx2.AsyncClient() if http_client is None else http_client
        self._access_token = AccessTokenManager(self._config, self._http_client)
        self._closed = False
        self._http = HTTP(
            self._config,
            self._http_client,
            self.get_access_token,
            self._access_token.known_secrets,
        )
        self.users = Users(self._http)
        self.groups = Groups(self._http)
        self.images = Images(self._http)
        self.interactions = Interactions(self._http)

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
        """是否已关闭。"""
        return self._closed

    async def get_access_token(self) -> str:
        """返回当前有效的 access_token，不含 `QQBot ` 前缀。

        首次调用时向平台获取，之后复用缓存、临近过期时换新，并发调用只发一次请求。
        只有调用尚未封装的接口或自行连接网关时才需要它；每次要用时调用即可，不要自己长期保存。

        对应官方接口 `POST /app/getAppAccessToken`。

        Raises:
            APIError: 平台拒绝签发（例如 AppID 或 AppSecret 不正确）或返回了无法识别的响应。
            NetworkError: 没有拿到平台的响应：连接失败、超时等。
            RuntimeError: 已关闭。

        Example:
            ```python
            token = await client.get_access_token()
            response = await client.http_client.get(
                f"{client.config.base_url}/users/@me",
                headers={"Authorization": f"QQBot {token}"},
            )
            ```
        """
        if self._closed:
            raise RuntimeError(f"{type(self).__name__} 已关闭，不能再发请求")
        return await self._access_token.get()

    def _redact_secrets(self, text: str) -> str:
        """把 `text` 里的 `app_secret` 与已知的 access_token 换成 `***`，写日志前用。"""
        return redact(text, *self._access_token.known_secrets())

    async def _get_gateway_url(self) -> str:
        """返回网关的 WebSocket 地址，对应 `GET /gateway`；与 API 不是同一个域名。"""
        gateway = await self._http.request("GET", "/gateway", type_=Gateway)
        return gateway.url

    async def close(self) -> None:
        """关闭并释放连接，可以重复调用。构造时传入的 `http_client` 不会被关闭。"""
        if self._closed:
            return
        self._closed = True
        if self._owns_http_client:
            await self._http_client.aclose()

    async def __aenter__(self) -> Self:
        """进入 `async with`。

        Raises:
            RuntimeError: 已经关闭，不能再次使用。
        """
        if self._closed:
            name = type(self).__name__
            raise RuntimeError(f"{name} 已关闭，不能再次使用，请新建一个 {name}")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()
