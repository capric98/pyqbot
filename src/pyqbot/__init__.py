"""pyqbot：一个人类能使用的 QQ 机器人 Python SDK。"""

from importlib.metadata import version

from ._bot import Bot
from ._client import Client
from ._config import Config
from ._errors import APIError, NetworkError, QQBotError

__version__ = version("pyqbot")

__all__ = [
    "APIError",
    "Bot",
    "Client",
    "Config",
    "NetworkError",
    "QQBotError",
    "__version__",
]
