"""事件模型的基类。绑定的 `Client` 与回复计数存在实例的 `__dict__` 里，不是字段（见 `docs/design.md`）。"""

from typing import TYPE_CHECKING

from .._model import Model

if TYPE_CHECKING:
    from .._client import Client

# 不在类体里声明这两个名字：带标注的名字会被 msgspec 当成字段。
_CLIENT_KEY = "_client"
_MSG_SEQ_KEY = "_msg_seq"


class Event(Model, dict=True):
    """平台推送的事件。`repr()`、`to_dict()` 与相等性只看字段。"""

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


class ReceivedMessage(Event):
    """收到的消息，可以作为被动回复的对象（`send_message(..., reply_to=message)`）。

    Attributes:
        id: 消息 ID，被动回复时作为 `msg_id`。
    """

    id: str


def next_msg_seq(message: ReceivedMessage) -> int:
    """返回回复 `message` 时要用的下一个 `msg_seq`：从 1 开始，每调用一次加 1。"""
    # 发送失败也不回退：平台可能已经收到，重用同一个 msg_seq 会被当成重复而拒绝。
    seq: int = message.__dict__.get(_MSG_SEQ_KEY, 0) + 1
    object.__setattr__(message, _MSG_SEQ_KEY, seq)
    return seq
