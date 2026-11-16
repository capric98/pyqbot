"""单聊接口。"""

from .._http import HTTP, path_segment
from .._models.event import ReceivedMessage
from .._models.message import SentMessage
from .message import send_message


class Users:
    """单聊（QQ 用户）相关的接口，经 `client.users` 使用。"""

    def __init__(self, http: HTTP) -> None:
        self._http = http

    async def send_message(
        self,
        openid: str,
        content: str,
        *,
        reply_to: ReceivedMessage | None = None,
    ) -> SentMessage:
        """向用户发送一条文本消息。

        不传 `reply_to` 是主动消息，受每日条数等限制，用户也可以关闭接收；
        传入收到的单聊消息则是被动回复，`msg_id` 与 `msg_seq` 由 SDK 填写。

        对应官方接口 `POST /v2/users/{user_openid}/messages`。

        Args:
            openid: 用户的 `user_openid`。
            content: 文本内容。
            reply_to: 要回复的那条收到的消息。

        Raises:
            APIError: 平台拒绝发送，例如被动回复已过期（`err_code` 见官方接口文档）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `openid` 为空。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.users.send_message(openid, "你好")
            ```
        """
        path = f"/v2/users/{path_segment(openid, 'openid')}/messages"
        return await send_message(self._http, path, content, reply_to=reply_to)
