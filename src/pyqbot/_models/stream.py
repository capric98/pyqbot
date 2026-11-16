"""流式消息（`autogen/api/v2_users_user_openid_stream_messages.post.md`）。分片的填法见 `docs/design.md`。"""

from .._model import OpenIntEnum, OpenStrEnum
from .message import SentMessage


class StreamContentType(OpenStrEnum):
    """分片的 `content_type`。"""

    TEXT = "text"
    MARKDOWN = "markdown"


class StreamInputMode(OpenStrEnum):
    """分片的 `input_mode`：`APPEND` 把内容接在后面，`REPLACE` 给出到目前为止的全文。"""

    APPEND = "append"
    REPLACE = "replace"


class StreamInputState(OpenIntEnum):
    """分片的 `input_state`。"""

    GENERATING = 1
    DONE = 10


class SentStreamChunk(SentMessage):
    """流式消息一个分片的发送结果；也是 `SentMessage`，可以传给 `quote=`。

    Attributes:
        id: 这条流式消息的 ID（`stream_msg_id`），各分片相同。
        remain_msg_len: 流式消息的剩余长度（字符数），含义以平台为准。
    """

    remain_msg_len: int | None = None
