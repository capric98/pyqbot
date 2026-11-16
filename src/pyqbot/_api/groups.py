"""群聊接口。"""

import os

from .._http import HTTP, path_segment
from .._models.event import GroupReplyTarget
from .._models.message import GroupAnyMessage, SentMessage
from .._models.send import Card, Keyboard, Markdown, Media
from .._models.upload import FileType
from .message import message_body, message_path, send_message
from .upload import upload_media


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

    async def upload(
        self,
        openid: str,
        *,
        path: str | os.PathLike[str] | None = None,
        url: str | None = None,
        data: bytes | None = None,
        file_name: str | None = None,
        file_type: FileType | None = None,
        send: bool = False,
    ) -> Media:
        """上传图片、视频、语音或文件，返回的 `Media` 传给 `send_message(media=...)` 发送。

        群聊上传的文件只能发到群聊。参数与上传方式的选择同 `client.users.upload()`。

        对应官方接口 `POST /v2/groups/{group_openid}/files`；分片上传另用
        `POST /v2/groups/{group_id}/upload_prepare` 与 `POST /v2/groups/{group_id}/upload_part_finish`。

        Args:
            openid: 群的 `group_openid`。
            path: 本地文件的路径。
            url: 公网可访问的 http(s) 地址。
            data: 文件内容，此时必须给出 `file_name`。
            file_name: 上报给平台的文件名，默认取 `path` 的文件名；不能与 `url` 同时传。
            file_type: 文件类型，不传时按扩展名推断，规则同单聊。
            send: 上传后直接作为主动消息发到群里，返回的 `Media.id` 是那条消息的 ID。
                占用主动消息额度。

        Raises:
            APIError: 平台拒绝，例如机器人被禁言（`err_code` 850018）、格式不支持（850019）。
            NetworkError: 没有拿到平台或对象存储的响应。
            ValueError: 同 `client.users.upload()`。
            OSError: 读取文件失败。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            media = await client.groups.upload(
                group_openid, url="https://example.com/a.mp4", file_type=pyqbot.FileType.VIDEO
            )
            ```
        """
        base = f"/v2/groups/{path_segment(openid, 'openid')}"
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
