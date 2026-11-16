"""pyqbot：一个人类能使用的 QQ 机器人 Python SDK。"""

from importlib.metadata import version

from ._bot import Bot
from ._client import Client
from ._config import Config
from ._errors import APIError, GatewayError, NetworkError, QQBotError
from ._gateway.intents import Intents
from ._models.event import C2CReplyTarget, GroupReplyTarget
from ._models.message import (
    C2CMessage,
    C2CUser,
    GroupMember,
    GroupMessage,
    MessageAttachment,
    ReceivedMessageType,
    SentMessage,
)
from ._models.send import (
    Button,
    ButtonAction,
    ButtonActionType,
    ButtonModal,
    ButtonPermission,
    ButtonPermissionType,
    ButtonRenderData,
    ButtonStyle,
    Card,
    Keyboard,
    KeyboardContent,
    KeyboardRow,
    Markdown,
    MarkdownParam,
    Media,
)

__version__ = version("pyqbot")

__all__ = [
    "APIError",
    "Bot",
    "Button",
    "ButtonAction",
    "ButtonActionType",
    "ButtonModal",
    "ButtonPermission",
    "ButtonPermissionType",
    "ButtonRenderData",
    "ButtonStyle",
    "C2CMessage",
    "C2CReplyTarget",
    "C2CUser",
    "Card",
    "Client",
    "Config",
    "GatewayError",
    "GroupMember",
    "GroupMessage",
    "GroupReplyTarget",
    "Intents",
    "Keyboard",
    "KeyboardContent",
    "KeyboardRow",
    "Markdown",
    "MarkdownParam",
    "Media",
    "MessageAttachment",
    "NetworkError",
    "QQBotError",
    "ReceivedMessageType",
    "SentMessage",
    "__version__",
]
