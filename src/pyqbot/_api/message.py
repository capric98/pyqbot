"""单聊与群聊共用的发消息实现：两者的请求体与响应相同，只有路径不同。"""

from .._http import HTTP
from .._models.event import ReceivedMessage, next_msg_seq
from .._models.message import MessageType, SentMessage


async def send_message(
    http: HTTP,
    path: str,
    content: str,
    *,
    reply_to: ReceivedMessage | None,
) -> SentMessage:
    """发送纯文本消息；`reply_to` 不为 `None` 时是被动回复。"""
    body: dict[str, object] = {"msg_type": MessageType.TEXT, "content": content}
    if reply_to is not None:
        body["msg_id"] = reply_to.id
        body["msg_seq"] = next_msg_seq(reply_to)
    return await http.request("POST", path, type_=SentMessage, json=body)
