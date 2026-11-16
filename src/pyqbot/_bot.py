"""事件驱动的机器人。"""

import asyncio
import contextlib

import httpx2

from ._client import Client
from ._config import DEFAULT_BASE_URL, DEFAULT_TIMEOUT
from ._events.dispatcher import Dispatcher, Handler
from ._gateway.connection import GatewayConnection
from ._gateway.intents import Intents
from ._models.message import C2CMessage, GroupMessage


class Bot(Client):
    """事件驱动的机器人：用装饰器注册事件处理函数，再用 `run()` 或 `start()` 连接网关。

    构造参数、生命周期与接口都同 `Client`，只多一个 `intents`。

    Args:
        intents: 要订阅的事件类别。默认按已注册的处理函数推导，一般不用传；传入则以它为准。

    Example:
        ```python
        bot = pyqbot.Bot("APP_ID", "APP_SECRET")


        @bot.on_c2c_message
        async def echo(message: pyqbot.C2CMessage) -> None:
            await message.reply(message.content)


        bot.run()
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
        intents: Intents | None = None,
    ) -> None:
        super().__init__(
            app_id, app_secret, base_url=base_url, timeout=timeout, http_client=http_client
        )
        self._intents = intents
        self._dispatcher = Dispatcher()
        self._connection: GatewayConnection | None = None

    def on_c2c_message[F: Handler[C2CMessage]](self, handler: F) -> F:
        """注册单聊消息（`C2C_MESSAGE_CREATE`）的处理函数，原样返回它。

        处理函数必须是 `async def`，只收一个 `C2CMessage`；同一事件可以注册多个。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(C2CMessage, handler)
        return handler

    def on_group_at_message[F: Handler[GroupMessage]](self, handler: F) -> F:
        """注册群里 @机器人 的消息（`GROUP_AT_MESSAGE_CREATE`）的处理函数，原样返回它。

        处理函数必须是 `async def`，只收一个 `GroupMessage`；同一事件可以注册多个。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GroupMessage, handler)
        return handler

    def _resolve_intents(self) -> Intents:
        """连接网关时要订阅的 Intents：构造时传入的，或按已注册的处理函数推导。"""
        return self._dispatcher.intents if self._intents is None else self._intents

    async def start(self) -> None:
        """连接网关，把事件分发给已注册的处理函数，直到 `close()` 被调用才返回。

        断线会自动重连并恢复会话。处理函数要在调用之前注册好；只能调用一次。

        Raises:
            GatewayError: 网关连接无法恢复，例如机器人被封禁，或没有所订阅事件的权限。
            APIError: 平台拒绝签发 access_token 或网关地址，例如 AppID、AppSecret 不正确。
            RuntimeError: 没有注册任何处理函数、重复调用，或已关闭。

        Example:
            ```python
            async with bot:
                await bot.start()
            ```
        """
        if self.is_closed:
            raise RuntimeError("Bot 已关闭，不能再启动，请新建一个 Bot")
        if self._connection is not None:
            raise RuntimeError("Bot.start() 只能调用一次")
        intents = self._resolve_intents()
        if not intents:
            raise RuntimeError(
                "没有要订阅的事件：先用 @bot.on_... 注册处理函数，或在构造时传入 intents"
            )
        self._connection = connection = GatewayConnection(
            http_client=self.http_client,
            get_url=self._get_gateway_url,
            get_token=self.get_access_token,
            intents=intents,
            on_dispatch=lambda payload: self._dispatcher.dispatch(payload, self),
            connect_timeout=self.config.timeout,
        )
        await connection.run()

    def run(self) -> None:
        """同步入口：连接网关并一直运行，按 Ctrl+C 退出。

        在脚本的最后调用，等价于 `asyncio.run` 里 `async with bot: await bot.start()`。
        已经在事件循环里时请改用 `start()`。可能抛出的异常同 `start()`。
        """

        async def main() -> None:
            async with self:
                await self.start()

        # Ctrl+C 时 asyncio.run 会先取消 main()、走完 async with 的清理，再抛 KeyboardInterrupt。
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(main())

    async def close(self) -> None:
        """断开网关，取消还在运行的处理函数，然后关闭连接；可以重复调用，`start()` 随之返回。

        构造时传入的 `http_client` 不会被关闭。
        """
        # 顺序不能换：先断开网关就不再有新事件，再取消处理函数，最后才能关 HTTP 连接。
        if self._connection is not None:
            await self._connection.close()
        await self._dispatcher.aclose()
        await super().close()
