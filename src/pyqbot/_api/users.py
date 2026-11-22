"""单聊接口。"""

import os

from .._http import HTTP, path_segment
from .._models.event import C2CReplyTarget
from .._models.message import C2CMessage, SentMessage
from .._models.send import Card, Keyboard, Markdown, Media
from .._models.stream import StreamContentType
from .._models.upload import FileType
from .message import message_body, message_path, send_message, send_reply, typing_body
from .stream import StreamMessage
from .upload import upload_media


class Users:
    """单聊（QQ 用户）相关的接口，经 `client.users` 使用。"""

    def __init__(self, http: HTTP) -> None:
        self._http = http

    async def send_message(
        self,
        user_openid: str,
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
            user_openid: 用户的 openid。
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
            ValueError: `user_openid` 为空；没有内容，或 `markdown`、`media`、`card` 传了不止一个，
                或 `markdown` 与 `content` 同时传，或 `keyboard` 没有随 `markdown`；
                `quote` 没有引用索引；`reply_to` 是没有事件 ID 的事件；`wakeup` 与 `reply_to` 同时使用。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.users.send_message(user_openid, "你好")
            await client.users.send_message(user_openid, markdown="**你好**", keyboard=keyboard)
            ```
        """
        path = f"/v2/users/{path_segment(user_openid, 'user_openid')}/messages"
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
        user_openid: str,
        *,
        seconds: int = 60,
        reply_to: C2CReplyTarget | None = None,
    ) -> None:
        """让用户看到机器人「正在输入」，持续 `seconds` 秒或直到机器人发出消息。只有单聊支持。

        官方示例是被动回复，所以通常传入要回复的消息；它也占用这条消息的一个 `msg_seq`。

        对应官方接口 `POST /v2/users/{user_openid}/messages`（`msg_type=6`）。

        Args:
            user_openid: 用户的 openid。
            seconds: 持续时间，1～60 秒。
            reply_to: 被动回复的对象，同 `send_message()`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `user_openid` 为空，`seconds` 不是 1～60 之间的整数，或 `reply_to` 是没有事件 ID 的事件。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.users.send_typing(user_openid, seconds=30, reply_to=message)
            ```
        """
        path = f"/v2/users/{path_segment(user_openid, 'user_openid')}/messages"
        body = typing_body(seconds)
        # 文档没有给出响应体，不解码。
        await send_reply(
            reply_to,
            lambda fields: self._http.request("POST", path, type_=None, json=body | fields),
        )

    async def recall_message(self, user_openid: str, message: str | SentMessage) -> None:
        """撤回机器人发给用户的一条消息。发出超过 2 分钟的消息不能撤回。

        流式消息撤回不了：传 `stream_msg_id` 平台报 40061001，传 `ref_idx` 报 40011002（`docs/errata.md`）。

        对应官方接口 `DELETE /v2/users/{user_openid}/messages/{message_id}`。

        Args:
            user_openid: 用户的 openid。
            message: 要撤回的消息：`send_message()` 的返回值或它的 `id`。

        Raises:
            APIError: 平台拒绝，例如已超过撤回时限（`err_code` 为 40064004）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `user_openid` 或消息 ID 为空。
            RuntimeError: 客户端已关闭。
        """
        base = f"/v2/users/{path_segment(user_openid, 'user_openid')}/messages"
        await self._http.request("DELETE", message_path(base, message), type_=None)

    def stream_message(
        self,
        user_openid: str,
        *,
        reply_to: C2CReplyTarget,
        markdown: bool = True,
        coalesce: bool = True,
    ) -> StreamMessage:
        """开始一条流式消息：内容分多次发出，用户看到的是同一条消息逐渐变长。只有单聊支持。

        流式消息只能是被动回复。这里不发请求，第一次 `append()` 时才发出第一个分片；
        `index`、`stream_msg_id`、`msg_id` / `event_id` 与 `msg_seq` 都由 SDK 填写。

        对应官方接口 `POST /v2/users/{user_openid}/stream_messages`。

        Args:
            user_openid: 用户的 openid。
            reply_to: 被动回复的对象，要用收到的消息：用互动等事件时平台拒绝第一个分片（`err_code` 40111003
                「参数msg_id不能为空」）。整条流式消息只占用它的一个 `msg_seq`。
            markdown: 内容按 Markdown 渲染；为 `False` 时按纯文本。
            coalesce: 上一片还在发送时把之后的内容攒成一片（默认）；为 `False` 时每次调用发一片，见 `StreamMessage`。

        Raises:
            ValueError: `user_openid` 为空。

        Example:
            ```python
            async with client.users.stream_message(user_openid, reply_to=message) as stream:
                async for piece in llm():
                    await stream.append(piece)
            ```
        """
        path = f"/v2/users/{path_segment(user_openid, 'user_openid')}/stream_messages"
        content_type = StreamContentType.MARKDOWN if markdown else StreamContentType.TEXT
        return StreamMessage(self._http, path, reply_to, content_type, coalesce=coalesce)

    async def upload(
        self,
        user_openid: str,
        *,
        path: str | os.PathLike[str] | None = None,
        url: str | None = None,
        data: bytes | None = None,
        file_name: str | None = None,
        file_type: FileType | None = None,
        send: bool = False,
    ) -> Media:
        """上传图片、视频、语音或文件，返回的 `Media` 传给 `send_message(media=...)` 发送。

        单聊上传的文件只能发到单聊。`path`、`url`、`data` 三选一：`url` 由平台下载；
        本地文件与 `data` 不超过 3 MiB 时随请求内联上传，更大的由 SDK 自动分片上传（并发、重试按平台下发的配置）。

        对应官方接口 `POST /v2/users/{user_openid}/files`；分片上传另用
        `POST /v2/users/{user_id}/upload_prepare` 与 `POST /v2/users/{user_id}/upload_part_finish`。

        Args:
            user_openid: 用户的 openid。
            path: 本地文件的路径。
            url: 公网可访问的 http(s) 地址。
            data: 文件内容，此时必须给出 `file_name`。
            file_name: 上报给平台的文件名，默认取 `path` 的文件名；不能与 `url` 同时传。
            file_type: 文件类型。不传时按扩展名推断（不区分大小写）：png、jpg、jpeg、gif、webp、bmp
                为图片，mp4 为视频，silk、slk、mp3、wav、ogg 为语音；其它扩展名要显式传入，
                任意文件都可以传 `FileType.FILE`。
            send: 上传后直接作为主动消息发给用户，返回的 `Media.id` 是那条消息的 ID。
                占用主动消息额度。

        Raises:
            APIError: 平台拒绝，例如格式不支持（`err_code` 850019）、超过大小上限（850031）。
            NetworkError: 没有拿到平台或对象存储的响应（分片会先按平台的配置重试）。
            ValueError: `user_openid` 为空，`path`、`url`、`data` 不是恰好传了一个，`data` 没有 `file_name`，
                `url` 带了 `file_name`，文件为空，或推断不出 `file_type`。
            OSError: 读取文件失败。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            media = await client.users.upload(user_openid, path="photo.png")
            await message.reply("图来了", media=media)
            ```
        """
        base = f"/v2/users/{path_segment(user_openid, 'user_openid')}"
        return await upload_media(
            self._http,
            base,
            path=path,
            url=url,
            data=data,
            file_name=file_name,
            file_type=file_type,
            send=send,
        )
