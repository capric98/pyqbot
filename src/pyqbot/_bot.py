"""事件驱动的机器人。"""

import httpx2

from ._client import Client
from ._config import DEFAULT_BASE_URL, DEFAULT_TIMEOUT
from ._events.dispatcher import Dispatcher, Handler
from ._gateway.intents import Intents
from ._models.message import C2CMessage, GroupMessage


class Bot(Client):
    """事件驱动的机器人：用装饰器注册事件处理函数。

    构造参数、生命周期与接口都同 `Client`，只多一个 `intents`。

    Args:
        intents: 要订阅的事件类别。默认按已注册的处理函数推导，一般不用传；传入则以它为准。

    Example:
        ```python
        bot = pyqbot.Bot("APP_ID", "APP_SECRET")


        @bot.on_c2c_message
        async def echo(message: pyqbot.C2CMessage) -> None:
            await message.reply(message.content)
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

    async def close(self) -> None:
        """取消还在运行的处理函数，然后关闭连接；可以重复调用。构造时传入的 `http_client` 不会被关闭。"""
        await self._dispatcher.aclose()
        await super().close()
