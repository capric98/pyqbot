"""单聊接口。"""

from .._http import HTTP, path_segment
from .._models.event import C2CReplyTarget, reply_fields
from .._models.message import C2CMessage, SentMessage
from .._models.send import Card, Keyboard, Markdown, Media
from .message import message_body, message_path, send_message, typing_body


class Users:
    """单聊（QQ 用户）相关的接口，经 `client.users` 使用。"""

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
        quote: str | SentMessage | C2CMessage | None = None,
        reply_to: C2CReplyTarget | None = None,
        wakeup: bool = False,
    ) -> SentMessage:
        """向用户发送一条消息，`msg_type` 由 SDK 按传了哪些内容推断。

        不传 `reply_to` 是主动消息，受每日条数等限制，用户也可以关闭接收；
        传入收到的单聊消息或可回复的事件则是被动回复，`msg_id` / `event_id` 与 `msg_seq` 由 SDK 填写。

        对应官方接口 `POST /v2/users/{user_openid}/messages`。

        Args:
            openid: 用户的 `user_openid`。
            content: 文本内容；与 `media`、`card` 同时传时一起发送。
            markdown: Markdown 正文，或 `Markdown` 对象（模板、图片校验等）。不能与 `content` 同时传。
            keyboard: 消息下方的按钮，只能随 `markdown` 发送。
            media: 上传好的图片、视频、语音或文件。
            card: 图文卡片。
            quote: 要引用的消息：发出的消息、收到的消息，或引用索引（`REFIDX_` 开头）。
            reply_to: 被动回复的对象：收到的消息，或可以回复的事件（须是 `Bot` 分发来的，带事件 ID）。
            wakeup: 作为互动召回消息发送（用户与机器人对话后 30 天内的几个周期里各可发一条）。
                不能与 `reply_to` 同时使用。

        Raises:
            APIError: 平台拒绝发送，例如被动回复已过期（`err_code` 见官方接口文档）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `openid` 为空；没有内容，或 `markdown`、`media`、`card` 传了不止一个，
                或 `markdown` 与 `content` 同时传，或 `keyboard` 没有随 `markdown`；
                `quote` 没有引用索引；`reply_to` 是没有事件 ID 的事件；`wakeup` 与 `reply_to` 同时使用。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.users.send_message(openid, "你好")
            await client.users.send_message(openid, markdown="**你好**", keyboard=keyboard)
            ```
        """
        path = f"/v2/users/{path_segment(openid, 'openid')}/messages"
        body = message_body(
            content, markdown=markdown, keyboard=keyboard, media=media, card=card, quote=quote
        )
        if wakeup:
            if reply_to is not None:
                raise ValueError("wakeup 不能与 reply_to 同时使用：召回消息是主动消息")
            body["is_wakeup"] = True
        return await send_message(self._http, path, body, reply_to=reply_to)

    async def send_typing(
        self,
        openid: str,
        *,
        seconds: int = 60,
        reply_to: C2CReplyTarget | None = None,
    ) -> None:
        """让用户看到机器人「正在输入」，持续 `seconds` 秒或直到机器人发出消息。只有单聊支持。

        官方示例是被动回复，所以通常传入要回复的消息；它也占用这条消息的一个 `msg_seq`。

        对应官方接口 `POST /v2/users/{user_openid}/messages`（`msg_type=6`）。

        Args:
            openid: 用户的 `user_openid`。
            seconds: 持续时间，1～60 秒。
            reply_to: 被动回复的对象，同 `send_message()`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `openid` 为空，`seconds` 不是 1～60 之间的整数，或 `reply_to` 是没有事件 ID 的事件。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.users.send_typing(openid, seconds=30, reply_to=message)
            ```
        """
        path = f"/v2/users/{path_segment(openid, 'openid')}/messages"
        body = typing_body(seconds)
        if reply_to is not None:
            body |= reply_fields(reply_to)
        # 文档没有给出响应体，不解码。
        await self._http.request("POST", path, type_=None, json=body)

    async def recall_message(self, openid: str, message: str | SentMessage) -> None:
        """撤回机器人发给用户的一条消息。发出超过 2 分钟的消息不能撤回。

        对应官方接口 `DELETE /v2/users/{user_openid}/messages/{message_id}`。

        Args:
            openid: 用户的 `user_openid`。
            message: 要撤回的消息：`send_message()` 的返回值或它的 `id`。

        Raises:
            APIError: 平台拒绝，例如已超过撤回时限（`err_code` 为 40064004）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `openid` 或消息 ID 为空。
            RuntimeError: 客户端已关闭。
        """
        base = f"/v2/users/{path_segment(openid, 'openid')}/messages"
        await self._http.request("DELETE", message_path(base, message), type_=None)
