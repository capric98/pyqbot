"""频道私信接口。"""

import os

from .._http import HTTP, path_segment
from .._models.event import DirectMessageReplyTarget
from .._models.guild_message import DirectMessageSession, GuildMessage
from .._models.send import Ark, Embed, Keyboard, Markdown
from .guild_message import (
    guild_message_request,
    message_path,
    recall_params,
    send_guild_message,
)


def _messages_path(guild_id: str) -> str:
    return f"/dms/{path_segment(guild_id, 'guild_id')}/messages"


class DirectMessages:
    """频道私信相关的接口，经 `client.dms` 使用。

    私信接口里的 `guild_id` 都是私信会话的 ID：取自 `create_session()` 的返回值或收到的
    `DirectMessage.guild_id`，不是用户所在频道的 ID。
    """

    def __init__(self, http: HTTP) -> None:
        self._http = http

    async def create_session(self, recipient_id: str, source_guild_id: str) -> DirectMessageSession:
        """与频道成员创建私信会话，机器人与该用户要有共同的频道。

        对应官方接口 `POST /users/@me/dms`。

        Args:
            recipient_id: 用户 ID（`GuildUser.id`）。
            source_guild_id: 机器人与该用户共同所在的频道 ID。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            session = await client.dms.create_session(user_id, guild_id)
            await client.dms.send_message(session.guild_id, "你好")
            ```
        """
        body = {"recipient_id": recipient_id, "source_guild_id": source_guild_id}
        return await self._http.request(
            "POST", "/users/@me/dms", type_=DirectMessageSession, json=body
        )

    async def send_message(
        self,
        guild_id: str,
        content: str | None = None,
        *,
        markdown: str | Markdown | None = None,
        keyboard: Keyboard | None = None,
        embed: Embed | None = None,
        ark: Ark | None = None,
        image: str | None = None,
        image_path: str | os.PathLike[str] | None = None,
        image_data: bytes | None = None,
        quote: str | GuildMessage | None = None,
        reply_to: DirectMessageReplyTarget | None = None,
    ) -> GuildMessage:
        """发送一条私信，参数同 `client.channels.send_message()`。

        主动私信每天对每个用户 2 条、累计 200 条；被动回复不限条数，`msg_id` 由 SDK 填写。

        对应官方接口 `POST /dms/{guild_id}/messages`。

        Args:
            guild_id: 私信会话的 ID（不是用户所在频道的 ID）。
            content: 文本内容。
            markdown: Markdown 正文，或 `Markdown` 对象。
            keyboard: 消息下方的按钮，只能随 `markdown` 发送。
            embed: Embed 消息。
            ark: Ark 消息。
            image: 图片的公网地址。
            image_path: 本地图片的路径。
            image_data: 图片的内容。
            quote: 要引用的消息：消息 ID 或消息对象。
            reply_to: 被动回复的私信（须是 `Bot` 分发来的）。

        Raises:
            AuditPendingError: 平台已受理，但要等人工审核。
            APIError: 平台拒绝发送。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 为空，或内容参数的组合不合法（同 `client.channels.send_message()`）。
            OSError: 读取 `image_path` 失败。
            RuntimeError: 客户端已关闭。
        """
        body, file_image = await guild_message_request(
            content,
            markdown=markdown,
            keyboard=keyboard,
            embed=embed,
            ark=ark,
            image=image,
            image_path=image_path,
            image_data=image_data,
            quote=quote,
        )
        return await send_guild_message(
            self._http, _messages_path(guild_id), body, file_image, reply_to=reply_to
        )

    async def recall_message(
        self, guild_id: str, message: str | GuildMessage, *, hidetip: bool = False
    ) -> None:
        """撤回机器人自己发出的一条私信。仅私域机器人可用。

        对应官方接口 `DELETE /dms/{guild_id}/messages/{message_id}`。

        Args:
            guild_id: 私信会话的 ID。
            message: 要撤回的私信或它的 ID。
            hidetip: 隐藏「撤回了一条消息」的提示小灰条。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 或消息 ID 为空。
            RuntimeError: 客户端已关闭。
        """
        path = message_path(_messages_path(guild_id), message)
        await self._http.request("DELETE", path, type_=None, params=recall_params(hidetip))
