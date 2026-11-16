"""群聊接口。"""

from .._http import HTTP, path_segment
from .._models.event import GroupReplyTarget
from .._models.message import GroupAnyMessage, SentMessage
from .._models.send import Card, Keyboard, Markdown, Media
from .message import message_body, message_path, send_message


class Groups:
    """群聊相关的接口，经 `client.groups` 使用。"""

    def __init__(self, http: HTTP) -> None:
        self._http = http

    async def send_message(
        self,
        openid: str,
        content: str | None = None,
        *,
        markdown: str | Markdown | None = None,
        keyboard: Keyboard | None = None,
        media: Media | None = None,
        card: Card | None = None,
        quote: str | SentMessage | GroupAnyMessage | None = None,
        reply_to: GroupReplyTarget | None = None,
    ) -> SentMessage:
        """向群发送一条消息，`msg_type` 由 SDK 按传了哪些内容推断。

        不传 `reply_to` 是主动消息，受每日条数等限制；
        传入收到的群消息或可回复的事件则是被动回复，`msg_id` / `event_id` 与 `msg_seq` 由 SDK 填写。
        群聊没有互动召回消息。

        对应官方接口 `POST /v2/groups/{group_openid}/messages`。

        Args:
            openid: 群的 `group_openid`。
            content: 同 `client.users.send_message()`，下同。
            markdown: Markdown 正文或 `Markdown` 对象。
            keyboard: 消息下方的按钮。
            media: 在群聊上传的富媒体（与单聊上传的不互通）。
            card: 图文卡片。
            quote: 要引用的消息。
            reply_to: 被动回复的对象：收到的群消息，或可以回复的事件（须是 `Bot` 分发来的，带事件 ID）。

        Raises:
            APIError: 平台拒绝发送，例如被动回复已过期（`err_code` 见官方接口文档）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `openid` 为空，内容参数的组合不合法（同单聊），`quote` 没有引用索引，
                或 `reply_to` 是没有事件 ID 的事件。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.groups.send_message(group_openid, "大家好")
            ```
        """
        path = f"/v2/groups/{path_segment(openid, 'openid')}/messages"
        body = message_body(
            content, markdown=markdown, keyboard=keyboard, media=media, card=card, quote=quote
        )
        return await send_message(self._http, path, body, reply_to=reply_to)

    async def recall_message(
        self, openid: str, message: str | SentMessage | GroupAnyMessage
    ) -> None:
        """撤回群里的一条消息。发出超过 2 分钟的消息不能撤回。

        机器人只能撤回自己的消息；是群管理员时还能撤回普通成员的消息（传入收到的群消息）。

        对应官方接口 `DELETE /v2/groups/{group_openid}/messages/{message_id}`。

        Args:
            openid: 群的 `group_openid`。
            message: 要撤回的消息：`send_message()` 的返回值、收到的群消息，或消息 ID。

        Raises:
            APIError: 平台拒绝，例如已超过撤回时限（`err_code` 为 40064004）或没有权限。
            NetworkError: 没有拿到平台的响应。
            ValueError: `openid` 或消息 ID 为空。
            RuntimeError: 客户端已关闭。
        """
        base = f"/v2/groups/{path_segment(openid, 'openid')}/messages"
        await self._http.request("DELETE", message_path(base, message), type_=None)
