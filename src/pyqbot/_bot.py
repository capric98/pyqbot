"""事件驱动的机器人。"""

from ._client import Client


class Bot(Client):
    """事件驱动的机器人。构造参数、生命周期与接口都继承自 `Client`。

    Example:
        ```python
        async with pyqbot.Bot("APP_ID", "APP_SECRET") as bot:
            token = await bot.get_access_token()
        ```
    """
