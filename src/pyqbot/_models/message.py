"""消息相关的模型（`autogen/api/v2_users_user_openid_messages.post.md` 等）。"""

from datetime import datetime

from .._model import Model, OpenIntEnum


class MessageType(OpenIntEnum):
    """发消息请求体的 `msg_type`。"""

    TEXT = 0
    MARKDOWN = 2
    INPUT_NOTIFY = 6  # 只有单聊支持
    MEDIA = 7
    CARD = 8


class MessageExtInfo(Model):
    """`SentMessage.ext_info`。

    Attributes:
        ref_idx: 引用这条消息时要用的索引。
    """

    ref_idx: str | None = None


class SentMessage(Model):
    """发送消息的结果。

    Attributes:
        id: 消息 ID，撤回时要用。
        timestamp: 发送时间，带时区。
        ext_info: 扩展信息。
    """

    id: str | None = None
    timestamp: datetime | None = None
    ext_info: MessageExtInfo | None = None
