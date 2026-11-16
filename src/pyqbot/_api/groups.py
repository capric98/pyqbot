"""群聊接口。"""

from .._http import HTTP, path_segment
from .._models.message import GroupMessage, SentMessage
from .message import send_message


class Groups:
    """群聊相关的接口，经 `client.groups` 使用。"""

    def __init__(self, http: HTTP) -> None:
        self._http = http

    async def send_message(
        self,
        openid: str,
        content: str,
        *,
        reply_to: GroupMessage | None = None,
    ) -> SentMessage:
        """向群发送一条文本消息。

        不传 `reply_to` 是主动消息，受每日条数等限制；
        传入收到的群消息则是被动回复，`msg_id` 与 `msg_seq` 由 SDK 填写。

        对应官方接口 `POST /v2/groups/{group_openid}/messages`。

        Args:
            openid: 群的 `group_openid`。
            content: 文本内容。
            reply_to: 要回复的那条收到的消息。

        Raises:
            APIError: 平台拒绝发送，例如被动回复已过期（`err_code` 见官方接口文档）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `openid` 为空。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.groups.send_message(group_openid, "大家好")
            ```
        """
        path = f"/v2/groups/{path_segment(openid, 'openid')}/messages"
        return await send_message(self._http, path, content, reply_to=reply_to)
