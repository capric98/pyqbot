"""消息相关的模型：发消息的结果，以及收到的单聊、群聊消息事件。

官方文档：`autogen/api/v2_users_user_openid_messages.post.md`、`autogen/event/c2c_message_create.md`、
`autogen/event/group_at_message_create.md`。
"""

from datetime import datetime

import msgspec

from .._gateway.intents import Intents
from .._model import Model, OpenIntEnum
from .event import ReceivedMessage


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


class GroupMember(_UserBase):
    """群消息的发送者或被 @ 的群成员。

    Attributes:
        member_openid: 群成员的 openid，与单聊的 `user_openid` 不是同一套取值。
        member_role: 群内角色：`"member"`、`"admin"` 或 `"owner"`。
        username: 昵称，可能为空串。
        bot: 是否为机器人。
    """

    member_openid: str | None = None
    member_role: str | None = None


class MessageElementAuthor(_UserBase):
    """`MessageElement.author`：被引用消息的发送者，单聊与群聊都可能出现。"""

    user_openid: str | None = None
    member_openid: str | None = None
    member_role: str | None = None


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
    """消息元素，如引用消息里被引用的内容；可以嵌套。"""

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


class C2CMessage(_ChatMessage):
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

    async def reply(self, content: str) -> SentMessage:
        """被动回复这条消息，`msg_id` 与 `msg_seq` 由 SDK 填写。

        对应官方接口 `POST /v2/users/{user_openid}/messages`。

        Raises:
            APIError: 平台拒绝发送，例如回复已过期。
            NetworkError: 没有拿到平台的响应。
            RuntimeError: 消息不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。
        """
        client = self._bound_client()
        return await client.users.send_message(self.user_openid, content, reply_to=self)


class GroupMessage(_ChatMessage):
    """群里 @机器人 的消息，对应事件 `GROUP_AT_MESSAGE_CREATE`。

    平台可能重复推送同一条消息（`id` 相同），需要时自行去重。

    Attributes:
        group_openid: 群的 openid，主动往群里发消息时传给 `client.groups.send_message()`。
        author: 发送者；缺失时各字段都是 `None`。
        content: 文本内容，已去掉开头的 @机器人；官方示例里带首尾空格，需要时自行 `strip()`。
        mentions: 消息里 @ 的其他成员，不含机器人自己。

    其余字段与 `C2CMessage` 相同。

    Example:
        ```python
        @bot.on_group_at_message
        async def pong(message: pyqbot.GroupMessage) -> None:
            if message.content.strip() == "/ping":
                await message.reply("pong")
        ```
    """

    event_name = "GROUP_AT_MESSAGE_CREATE"
    intent = Intents.GROUP_AND_C2C_EVENT

    group_openid: str
    author: GroupMember = msgspec.field(default_factory=GroupMember)
    mentions: tuple[GroupMember, ...] = ()

    @property
    def member_openid(self) -> str | None:
        """发送者的 openid，即 `author.member_openid`。"""
        return self.author.member_openid

    async def reply(self, content: str) -> SentMessage:
        """被动回复这条消息，`msg_id` 与 `msg_seq` 由 SDK 填写。

        对应官方接口 `POST /v2/groups/{group_openid}/messages`。

        Raises:
            APIError: 平台拒绝发送，例如回复已过期。
            NetworkError: 没有拿到平台的响应。
            RuntimeError: 消息不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。
        """
        client = self._bound_client()
        return await client.groups.send_message(self.group_openid, content, reply_to=self)
