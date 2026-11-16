"""pyqbot：一个人类能使用的 QQ 机器人 Python SDK。"""

from importlib.metadata import version

from ._bot import Bot
from ._client import Client
from ._config import Config
from ._errors import APIError, NetworkError, PayloadError, QQBotError
from ._gateway.intents import Intents
from ._models.message import SentMessage

__version__ = version("pyqbot")

__all__ = [
    "APIError",
    "Bot",
    "Client",
    "Config",
    "Intents",
    "NetworkError",
    "PayloadError",
    "QQBotError",
    "SentMessage",
    "__version__",
]
