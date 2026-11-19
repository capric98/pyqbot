"""消息相关的模型：发消息的结果，以及收到的单聊、群聊消息事件。

官方文档：`autogen/api/v2_users_user_openid_messages.post.md`、`autogen/event/c2c_message_create.md`、
`autogen/event/group_at_message_create.md`、`autogen/event/group_message_create.md`。
"""

import os
from datetime import datetime
from typing import TYPE_CHECKING

from .._gateway.intents import Intents
from .._model import Model, OpenIntEnum, OpenStrEnum
from .event import C2CReplyTarget, GroupReplyTarget, ReceivedMessage
from .send import Card, Keyboard, Markdown, Media
from .upload import FileType

if TYPE_CHECKING:
    from .._api.stream import StreamMessage


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

    id: str
    timestamp: datetime | None = None
    ext_info: MessageExtInfo | None = None


class ReceivedMessageType(OpenIntEnum):
    """收到的消息的内容类型（`message_type`），与发消息的 `msg_type` 不是同一套取值。

    Attributes:
        TEXT: 普通文本。
        ARK: 结构化卡片，内容在 `ark_data`。
        PARALLEL: 并行消息。
        CHAT_HISTORY: 聊天记录。
        QUOTE: 引用消息，被引用的内容在 `msg_elements`。
    """

    TEXT = 0
    ARK = 3
    PARALLEL = 101
    CHAT_HISTORY = 102
    QUOTE = 103


class GroupMemberRole(OpenStrEnum):
    """群成员在群里的角色（`member_role`）。"""

    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"


class _UserBase(Model):
    # 文档的 User 结构里各场景共有的部分；avatar 文档没写，见 docs/errata.md。
    id: str | None = None
    username: str | None = None
    bot: bool | None = None
    union_openid: str | None = None
    union_user_account: str | None = None
    avatar: str | None = None


class C2CUser(_UserBase):
    """单聊消息的发送者。

    Attributes:
        user_openid: 用户的 openid，主动给他发消息时传给 `client.users.send_message()`。
        username: 昵称，可能为空串。
        bot: 是否为机器人。
        union_openid: 跨应用统一的 openid，可能为空串。
    """

    user_openid: str


class GroupMessageAuthor(_UserBase):
    """群消息的发送者。

    Attributes:
        member_openid: 发送者在群里的 openid，与单聊的 `user_openid` 不是同一套取值。
        member_role: 群内角色。
        member_nickname: 群昵称（群名片）；文档没有列出，实测有。
        username: QQ 昵称，可能为空串。
        bot: 是否为机器人。
    """

    member_openid: str
    member_role: GroupMemberRole | None = None
    member_nickname: str | None = None


class GroupMessageMember(_UserBase):
    """群消息里被 @ 的成员（`GroupMessage.mentions`）。

    Attributes:
        member_openid: 群成员的 openid，与单聊的 `user_openid` 不是同一套取值。
        member_role: 群内角色。
        member_nickname: 群昵称（群名片）；文档没有列出，实测有。
        username: QQ 昵称，可能为空串。
        bot: 是否为机器人。
        is_you: 被 @ 的是不是本机器人；文档没有列出，实测只在 `mentions` 里有。
        scope: @ 的范围，实测单独 @ 某人时为 `"single"`；文档没有列出。
    """

    member_openid: str | None = None
    member_role: GroupMemberRole | None = None
    member_nickname: str | None = None
    is_you: bool | None = None
    scope: str | None = None


class MessageElementAuthor(_UserBase):
    """`MessageElement.author`：被引用消息的发送者，单聊与群聊都可能出现。"""

    user_openid: str | None = None
    member_openid: str | None = None
    member_role: GroupMemberRole | None = None


class MessageAttachment(Model):
    """消息附件：图片、语音、视频、文件等。

    Attributes:
        url: 下载地址。
        content_type: 如 `"image/jpeg"`、`"video/mp4"`，语音是 `"voice"`，群文件是 `"file"`。
        size: 文件大小，单位字节。
        width: 图片宽度，单位像素；非图片没有。
        height: 图片高度，单位像素；非图片没有。
        voice_wav_url: 语音转成 WAV 后的下载地址。
        asr_refer_text: 语音识别的参考结果。
    """

    url: str | None = None
    filename: str | None = None
    content_type: str | None = None
    size: int | None = None
    width: int | None = None
    height: int | None = None
    voice_wav_url: str | None = None
    asr_refer_text: str | None = None


class MessageScene(Model):
    """消息场景。`ext` 是 `key=value` 形式的字符串，如 `msg_idx=...`、`ref_msg_idx=...`。"""

    source: str | None = None
    ext: tuple[str, ...] = ()


class ArkData(Model):
    """结构化卡片的内容。`fields` 的键随卡片类型而变，见官方文档。"""

    prompt: str | None = None
    ark_type: str | None = None
    ark_name: str | None = None
    fields: dict[str, object] | None = None


class MessageElement(Model):
    """消息元素，如引用消息里被引用的内容；可以嵌套。

    Attributes:
        msg_idx: 这个元素对应的消息的引用索引。
    """

    msg_idx: str | None = None
    author: MessageElementAuthor | None = None
    message_type: ReceivedMessageType | None = None
    content: str | None = None
    attachments: tuple[MessageAttachment, ...] = ()
    ark_data: ArkData | None = None
    msg_elements: tuple[MessageElement, ...] = ()


class _ChatMessage(ReceivedMessage):
    # 单聊与群聊消息共有的字段。content 缺失时与空串没有区别，所以默认 ""，省得处处判断 None。
    content: str = ""
    timestamp: datetime | None = None
    message_type: ReceivedMessageType | None = None
    message_scene: MessageScene | None = None
    attachments: tuple[MessageAttachment, ...] = ()
    ark_data: ArkData | None = None
    msg_elements: tuple[MessageElement, ...] = ()

    @property
    def msg_idx(self) -> str | None:
        """这条消息的引用索引（`message_scene.ext` 里的 `msg_idx`），引用它时要用；没有时为 `None`。"""
        return self._scene_ext("msg_idx")

    @property
    def ref_msg_idx(self) -> str | None:
        """这条消息引用的那条消息的索引（`message_scene.ext` 里的 `ref_msg_idx`）；没有引用时为 `None`。

        引用的是机器人发的消息时，它对应发送结果的 `ext_info.ref_idx`。
        """
        return self._scene_ext("ref_msg_idx")

    def _scene_ext(self, name: str) -> str | None:
        if self.message_scene is not None:
            for item in self.message_scene.ext:
                key, sep, value = item.partition("=")
                if sep and key == name:
                    return value
        return None


class C2CMessage(_ChatMessage, C2CReplyTarget):
    """用户发给机器人的单聊消息，对应事件 `C2C_MESSAGE_CREATE`。

    平台可能重复推送同一条消息（`id` 相同），需要时自行去重。

    Attributes:
        id: 消息 ID。
        content: 文本内容；纯图片等消息为空串。
        author: 发送者。
        timestamp: 发送时间，带时区。
        message_type: 内容类型。
        attachments: 附件。
        msg_elements: 引用消息等的被引用内容。
        ark_data: 结构化卡片的内容。
        message_scene: 消息场景，含 `msg_idx` 等索引。

    Example:
        ```python
        @bot.on_c2c_message
        async def echo(message: pyqbot.C2CMessage) -> None:
            await message.reply(f"你说：{message.content}")
        ```
    """

    event_name = "C2C_MESSAGE_CREATE"
    intent = Intents.GROUP_AND_C2C_EVENT

    author: C2CUser

    @property
    def user_openid(self) -> str:
        """发送者的 openid，即 `author.user_openid`。"""
        return self.author.user_openid

    async def reply(
        self,
        content: str | None = None,
        *,
        markdown: str | Markdown | None = None,
        keyboard: Keyboard | None = None,
        media: Media | None = None,
        card: Card | None = None,
        quote: str | SentMessage | C2CMessage | None = None,
    ) -> SentMessage:
        """被动回复这条消息，`msg_id` 与 `msg_seq` 由 SDK 填写；参数同 `client.users.send_message()`。

        对应官方接口 `POST /v2/users/{user_openid}/messages`。

        Raises:
            APIError: 平台拒绝发送，例如回复已过期。
            NetworkError: 没有拿到平台的响应。
            ValueError: 内容参数的组合不合法。
            RuntimeError: 消息不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。
        """
        client = self._bound_client()
        return await client.users.send_message(
            self.user_openid,
            content,
            markdown=markdown,
            keyboard=keyboard,
            media=media,
            card=card,
            quote=quote,
            reply_to=self,
        )

    async def send_typing(self, *, seconds: int = 60) -> None:
        """向发送者显示「正在输入」，作为对这条消息的被动回复；参数同 `client.users.send_typing()`。

        对应官方接口 `POST /v2/users/{user_openid}/messages`（`msg_type=6`）。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `seconds` 不是 1～60 之间的整数。
            RuntimeError: 消息不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。
        """
        client = self._bound_client()
        await client.users.send_typing(self.user_openid, seconds=seconds, reply_to=self)

    def reply_stream(self, *, markdown: bool = True, coalesce: bool = True) -> StreamMessage:
        """以流式消息被动回复这条消息；参数同 `client.users.stream_message()`。

        对应官方接口 `POST /v2/users/{user_openid}/stream_messages`。

        Raises:
            RuntimeError: 消息不是 `Bot` 分发来的（没有绑定客户端）。

        Example:
            ```python
            async with message.reply_stream() as stream:
                async for piece in llm():
                    await stream.append(piece)
            ```
        """
        client = self._bound_client()
        return client.users.stream_message(
            self.user_openid, reply_to=self, markdown=markdown, coalesce=coalesce
        )

    async def upload(
        self,
        *,
        path: str | os.PathLike[str] | None = None,
        url: str | None = None,
        data: bytes | None = None,
        file_name: str | None = None,
        file_type: FileType | None = None,
        send: bool = False,
    ) -> Media:
        """上传要发给发送者的图片、视频、语音或文件；参数同 `client.users.upload()`，只是固定了用户。

        对应官方接口 `POST /v2/users/{user_openid}/files`（大文件另走分片上传）。

        Raises:
            APIError: 平台拒绝，例如格式不支持。
            NetworkError: 没有拿到平台或对象存储的响应。
            ValueError: 参数组合不合法，同 `client.users.upload()`。
            OSError: 读取文件失败。
            RuntimeError: 消息不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。

        Example:
            ```python
            await message.reply(media=await message.upload(path="cat.png"))
            ```
        """
        client = self._bound_client()
        return await client.users.upload(
            self.user_openid,
            path=path,
            url=url,
            data=data,
            file_name=file_name,
            file_type=file_type,
            send=send,
        )


class GroupMessage(_ChatMessage, GroupReplyTarget):
    """群里的任意一条消息（不限于 @机器人），对应事件 `GROUP_MESSAGE_CREATE`。

    群设置里把机器人可获取的消息设为「获取群内全部消息」才会收到；这时 @机器人 的消息也只推这个事件，
    不再推 `GROUP_AT_MESSAGE_CREATE`，`content` 带着 `<@机器人的 member_openid>` 前缀，用 `mentions_me` 判断
    （实测，见 `docs/errata.md`）。`GroupAtMessage`（@机器人 的消息）是它的子类，
    所以一个标注为 `GroupMessage` 的处理函数可以同时注册到 `@bot.on_group_message` 与
    `@bot.on_group_at_message`；反过来不行。平台可能重复推送同一条消息（`id` 相同），需要时自行去重。

    Attributes:
        group_openid: 群的 openid，主动往群里发消息时传给 `client.groups.send_message()`。
        author: 发送者。
        content: 文本内容。@ 某成员写作 `<@member_openid>`，@全体成员写作 `<@all>`。
        mentions: 消息里 @ 的成员。

    其余字段与 `C2CMessage` 相同。

    Example:
        ```python
        @bot.on_group_message
        async def watch(message: pyqbot.GroupMessage) -> None:
            if "<@all>" in message.content:
                await message.reply("收到通知")
        ```
    """

    event_name = "GROUP_MESSAGE_CREATE"
    intent = Intents.GROUP_AND_C2C_EVENT

    group_openid: str
    author: GroupMessageAuthor
    mentions: tuple[GroupMessageMember, ...] = ()

    @property
    def mentions_me(self) -> bool:
        """这条消息是否 @ 了本机器人（`mentions` 里有 `is_you` 为真的成员）。"""
        return any(member.is_you for member in self.mentions)

    @property
    def member_openid(self) -> str:
        """发送者的 openid，即 `author.member_openid`。"""
        return self.author.member_openid

    async def reply(
        self,
        content: str | None = None,
        *,
        markdown: str | Markdown | None = None,
        keyboard: Keyboard | None = None,
        media: Media | None = None,
        card: Card | None = None,
        quote: str | SentMessage | GroupMessage | None = None,
    ) -> SentMessage:
        """被动回复这条消息，`msg_id` 与 `msg_seq` 由 SDK 填写；参数同 `client.groups.send_message()`。

        对应官方接口 `POST /v2/groups/{group_openid}/messages`。

        Raises:
            APIError: 平台拒绝发送，例如回复已过期。
            NetworkError: 没有拿到平台的响应。
            ValueError: 内容参数的组合不合法。
            RuntimeError: 消息不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。
        """
        client = self._bound_client()
        return await client.groups.send_message(
            self.group_openid,
            content,
            markdown=markdown,
            keyboard=keyboard,
            media=media,
            card=card,
            quote=quote,
            reply_to=self,
        )

    async def upload(
        self,
        *,
        path: str | os.PathLike[str] | None = None,
        url: str | None = None,
        data: bytes | None = None,
        file_name: str | None = None,
        file_type: FileType | None = None,
        send: bool = False,
    ) -> Media:
        """上传要发到这个群的图片、视频、语音或文件；参数同 `client.groups.upload()`，只是固定了群。

        对应官方接口 `POST /v2/groups/{group_openid}/files`（大文件另走分片上传）。

        Raises:
            APIError: 平台拒绝，例如机器人被禁言、格式不支持。
            NetworkError: 没有拿到平台或对象存储的响应。
            ValueError: 参数组合不合法，同 `client.users.upload()`。
            OSError: 读取文件失败。
            RuntimeError: 消息不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。

        Example:
            ```python
            await message.reply(media=await message.upload(path="cat.png"))
            ```
        """
        client = self._bound_client()
        return await client.groups.upload(
            self.group_openid,
            path=path,
            url=url,
            data=data,
            file_name=file_name,
            file_type=file_type,
            send=send,
        )


class GroupAtMessage(GroupMessage):
    """群里 @机器人 的消息，对应事件 `GROUP_AT_MESSAGE_CREATE`。

    平台可能重复推送同一条消息（`id` 相同），需要时自行去重。

    Attributes:
        content: 文本内容，已去掉开头的 @机器人，但实测开头留着一个空格（如 `" /ping"`），需要时自行 `strip()`。
        mentions: 消息里 @ 的其他成员，不含机器人自己。

    其余字段与方法同 `GroupMessage`。

    Example:
        ```python
        @bot.on_group_at_message
        async def pong(message: pyqbot.GroupAtMessage) -> None:
            if message.content.strip() == "/ping":
                await message.reply("pong")
        ```
    """

    event_name = "GROUP_AT_MESSAGE_CREATE"

    @property
    def mentions_me(self) -> bool:
        """恒为 `True`：这个事件就是 @机器人 的消息（`mentions` 里不含机器人自己）。"""
        return True
