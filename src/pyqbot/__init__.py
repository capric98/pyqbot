"""pyqbot：一个人类能使用的 QQ 机器人 Python SDK。"""

from importlib.metadata import version

from ._bot import Bot
from ._client import Client
from ._config import Config
from ._errors import APIError, GatewayError, NetworkError, QQBotError
from ._gateway.intents import Intents
from ._models.message import (
    C2CMessage,
    C2CUser,
    GroupMember,
    GroupMessage,
    MessageAttachment,
    ReceivedMessageType,
    SentMessage,
)

__version__ = version("pyqbot")

__all__ = [
    "APIError",
    "Bot",
    "C2CMessage",
    "C2CUser",
    "Client",
    "Config",
    "GatewayError",
    "GroupMember",
    "GroupMessage",
    "Intents",
    "MessageAttachment",
    "NetworkError",
    "QQBotError",
    "ReceivedMessageType",
    "SentMessage",
    "__version__",
]
