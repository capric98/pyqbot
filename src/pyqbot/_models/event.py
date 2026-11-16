"""事件模型的基类与被动回复的机制。绑定的 `Client`、事件 ID 与回复计数存在实例的 `__dict__` 里，不是字段。"""

from typing import TYPE_CHECKING, ClassVar

from .._gateway.intents import Intents
from .._model import Model

if TYPE_CHECKING:
    from .._client import Client

# 不在类体里声明这些名字：带标注的名字会被 msgspec 当成字段。
_CLIENT_KEY = "_client"
_EVENT_ID_KEY = "_event_id"
_MSG_SEQ_KEY = "_msg_seq"


class Event(Model, dict=True):
    """平台推送的事件。`repr()`、`to_dict()` 与相等性只看字段。

    能被分发的子类必须给出 `event_name`（Dispatch 的 `t`）与 `intent`（订阅它所需的类别）。
    """

    event_name: ClassVar[str]
    intent: ClassVar[Intents]

    @property
    def event_id(self) -> str | None:
        """事件 ID（网关 payload 外层的 `id`）；不是 `Bot` 分发来的事件，或平台没有给出时为 `None`。"""
        return self.__dict__.get(_EVENT_ID_KEY)

    def _bound_client(self) -> Client:
        """取回分发时绑定的 `Client`，没有绑定时抛 `RuntimeError`；供子类的快捷方法（如 `reply()`）使用。"""
        client: Client | None = self.__dict__.get(_CLIENT_KEY)
        if client is None:
            raise RuntimeError(
                f"{type(self).__name__} 没有绑定 Client：只有 Bot 分发给处理函数的事件才会绑定，"
                "自己构造的事件对象请改为直接调用 client 上的接口"
            )
        return client


def bind_client(event: Event, client: Client) -> None:
    """把 `client` 绑到 `event` 上，由分发器在调用处理函数之前调用。"""
    object.__setattr__(event, _CLIENT_KEY, client)  # 模型不可变，只能绕过 __setattr__


def bind_event_id(event: Event, event_id: str | None) -> None:
    """记下 `event` 的事件 ID，由分发器在调用处理函数之前调用。"""
    object.__setattr__(event, _EVENT_ID_KEY, event_id)


class ReplyTarget(Event):
    """可以被动回复的事件：收到的消息用 `msg_id` 回复，其余事件用 `event_id`。

    场景由子类继承 `C2CReplyTarget`、`GroupReplyTarget` 等标记类表明，发消息接口的 `reply_to` 按它限定类型。
    """


class C2CReplyTarget(ReplyTarget):
    """可以作为 `client.users.send_message(..., reply_to=...)` 的事件，如 `C2CMessage`。"""


class GroupReplyTarget(ReplyTarget):
    """可以作为 `client.groups.send_message(..., reply_to=...)` 的事件，如 `GroupMessage`。"""


class ChannelReplyTarget(ReplyTarget):
    """可以被动回复到子频道（`POST /channels/{channel_id}/messages`）的事件，如 `ChannelMessage`。"""


class DirectMessageReplyTarget(ReplyTarget):
    """可以被动回复到频道私信（`POST /dms/{guild_id}/messages`）的事件，即 `DirectMessage`。"""


class ReceivedMessage(ReplyTarget):
    """收到的消息，被动回复时用 `msg_id`。

    Attributes:
        id: 消息 ID，被动回复时作为 `msg_id`。
    """

    id: str


def reply_fields(target: ReplyTarget, *, seq: bool = True) -> dict[str, object]:
    """被动回复 `target` 时请求体要加的字段：`msg_id` 或 `event_id`，以及 `msg_seq`（`seq=False` 时不加、不占用）。

    Raises:
        ValueError: `target` 不是消息，又没有事件 ID。
    """
    if isinstance(target, ReceivedMessage):
        fields: dict[str, object] = {"msg_id": target.id}
    elif target.event_id is not None:
        fields = {"event_id": target.event_id}
    else:
        raise ValueError(
            f"{type(target).__name__} 没有事件 ID，不能用来被动回复：只有 Bot 分发来的事件才带事件 ID"
        )
    if seq:
        fields["msg_seq"] = next_msg_seq(target)
    return fields


def next_msg_seq(target: ReplyTarget) -> int:
    """返回回复 `target` 时要用的下一个 `msg_seq`：从 1 开始，每调用一次加 1。"""
    # 发送失败也不回退：平台可能已经收到，重用同一个 msg_seq 会被当成重复而拒绝。
    seq: int = target.__dict__.get(_MSG_SEQ_KEY, 0) + 1
    object.__setattr__(target, _MSG_SEQ_KEY, seq)
    return seq
