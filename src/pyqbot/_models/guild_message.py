"""频道消息：消息对象、子频道消息与私信的事件、消息删除、消息审核与表情表态。

官方文档：`server-inter/message/template/model.md`（Message、MessageDelete、MessageAudited）、
`server-inter/channel/message/event.md`、`server-inter/message/trans/emoji.md`、`openapi/reaction/model.md`、
`openapi/emoji/model.md`、`server-inter/channel/message/dms.md`。
"""

import os
from datetime import datetime

import msgspec

from .._gateway.intents import Intents
from .._model import Model, OpenIntEnum
from .event import ChannelReplyTarget, DirectMessageReplyTarget, Event, ReceivedMessage
from .guild import GuildMember, GuildUser
from .message import MessageAttachment
from .send import Ark, Embed, Keyboard, Markdown


class MessageEmbedThumbnail(Model):
    """`MessageEmbed.thumbnail`。"""

    url: str | None = None


class MessageEmbedField(Model):
    """`MessageEmbed.fields` 的一项。"""

    name: str = ""


class MessageEmbed(Model):
    """频道消息里的 embed，一种特殊的 ark。"""

    title: str = ""
    prompt: str | None = None
    thumbnail: MessageEmbedThumbnail | None = None
    fields: tuple[MessageEmbedField, ...] = ()


class MessageArkObjKv(Model):
    """`MessageArkObj.obj_kv` 的一项。"""

    key: str = ""
    value: str = ""


class MessageArkObj(Model):
    """`MessageArkKv.obj` 的一项。"""

    obj_kv: tuple[MessageArkObjKv, ...] = ()


class MessageArkKv(Model):
    """`MessageArk.kv` 的一项。"""

    key: str = ""
    value: str | None = None
    obj: tuple[MessageArkObj, ...] = ()


class MessageArk(Model):
    """频道消息里的 ark 卡片。"""

    template_id: int | None = None
    kv: tuple[MessageArkKv, ...] = ()


class MessageReference(Model):
    """频道消息引用的消息。"""

    message_id: str | None = None
    ignore_get_message_error: bool | None = None


class GuildMessage(ReceivedMessage):
    """频道里的一条消息（子频道消息或私信），即官方的 Message 对象，如 `MessageDelete.message`。

    收到消息的事件是它的子类：`ChannelAnyMessage`、`ChannelMessage`、`DirectMessage`。

    Attributes:
        id: 消息 ID。
        channel_id: 子频道 ID。
        guild_id: 频道 ID；私信里是私信会话的 ID，回复私信时要用。
        content: 文本内容，没有时为空串。@ 某人写作 `<@!用户 ID>`。
        timestamp: 发送时间，带时区。
        edited_timestamp: 编辑时间，带时区。
        mention_everyone: 是否 @全体成员。
        author: 发送者；缺失时各字段为默认值。
        member: 发送者在频道里的成员信息，不含 `user`。
        mentions: 消息里 @ 的用户。
        attachments: 附件。
        embeds: embed。
        ark: ark 卡片。
        seq: 子频道内的消息序号，已弃用，改用 `seq_in_channel`。
        seq_in_channel: 子频道内的消息序号（字符串），同一子频道内按先后递增，用于排序。
        message_reference: 引用的消息。
    """

    channel_id: str
    guild_id: str
    content: str = ""
    timestamp: datetime | None = None
    edited_timestamp: datetime | None = None
    mention_everyone: bool = False
    author: GuildUser = msgspec.field(default_factory=GuildUser)
    member: GuildMember | None = None
    mentions: tuple[GuildUser, ...] = ()
    attachments: tuple[MessageAttachment, ...] = ()
    embeds: tuple[MessageEmbed, ...] = ()
    ark: MessageArk | None = None
    seq: int | None = None
    seq_in_channel: str | None = None
    message_reference: MessageReference | None = None


class ChannelAnyMessage(GuildMessage, ChannelReplyTarget):
    """子频道里的任意一条消息（不限于 @机器人），对应事件 `MESSAGE_CREATE`；仅私域机器人可用。

    `ChannelMessage`（@机器人 的消息）是它的子类，所以标注为 `ChannelAnyMessage` 的处理函数可以同时注册到
    `@bot.on_channel_message` 与 `@bot.on_channel_at_message`。消息不保证严格有序，需要时按 `seq_in_channel` 排序。
    字段同 `GuildMessage`。
    """

    event_name = "MESSAGE_CREATE"
    intent = Intents.GUILD_MESSAGES

    async def reply(
        self,
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
    ) -> GuildMessage:
        """被动回复这条消息，发到它所在的子频道，`msg_id` 由 SDK 填写；参数同 `client.channels.send_message()`。

        对应官方接口 `POST /channels/{channel_id}/messages`。

        Raises:
            AuditPendingError: 消息要等人工审核，审核结果由事件推送。
            APIError: 平台拒绝发送，例如回复已过期。
            NetworkError: 没有拿到平台的响应。
            ValueError: 内容参数的组合不合法。
            OSError: 读取 `image_path` 失败。
            RuntimeError: 消息不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。
        """
        client = self._bound_client()
        return await client.channels.send_message(
            self.channel_id,
            content,
            markdown=markdown,
            keyboard=keyboard,
            embed=embed,
            ark=ark,
            image=image,
            image_path=image_path,
            image_data=image_data,
            quote=quote,
            reply_to=self,
        )


class ChannelMessage(ChannelAnyMessage):
    """子频道里 @机器人 或回复机器人的消息，对应事件 `AT_MESSAGE_CREATE`。字段同 `GuildMessage`。

    Example:
        ```python
        @bot.on_channel_at_message
        async def pong(message: pyqbot.ChannelMessage) -> None:
            if "/ping" in message.content:
                ...
        ```
    """

    event_name = "AT_MESSAGE_CREATE"
    intent = Intents.PUBLIC_GUILD_MESSAGES


class DirectMessage(GuildMessage, DirectMessageReplyTarget):
    """用户通过频道私信发给机器人的消息，对应事件 `DIRECT_MESSAGE_CREATE`。

    字段同 `GuildMessage`；`guild_id` 是私信会话的 ID，回复私信时用它，不是用户所在频道的 ID。
    私信不支持沙箱频道，调试时用用户 ID 白名单。
    """

    event_name = "DIRECT_MESSAGE_CREATE"
    intent = Intents.DIRECT_MESSAGE

    async def reply(
        self,
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
    ) -> GuildMessage:
        """被动回复这条私信，`msg_id` 由 SDK 填写；参数同 `client.dms.send_message()`。

        对应官方接口 `POST /dms/{guild_id}/messages`。

        Raises:
            AuditPendingError: 消息要等人工审核，审核结果由事件推送。
            APIError: 平台拒绝发送，例如回复已过期。
            NetworkError: 没有拿到平台的响应。
            ValueError: 内容参数的组合不合法。
            OSError: 读取 `image_path` 失败。
            RuntimeError: 消息不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。
        """
        client = self._bound_client()
        return await client.dms.send_message(
            self.guild_id,
            content,
            markdown=markdown,
            keyboard=keyboard,
            embed=embed,
            ark=ark,
            image=image,
            image_path=image_path,
            image_data=image_data,
            quote=quote,
            reply_to=self,
        )


# ---- 消息删除 ----


class _MessageDeleteEvent(Event):
    message: GuildMessage
    op_user: GuildUser = msgspec.field(default_factory=GuildUser)


class MessageDelete(_MessageDeleteEvent):
    """子频道里的消息被删除（撤回），对应事件 `MESSAGE_DELETE`；仅私域机器人可用。

    `PublicMessageDelete` 是它的子类，所以标注为 `MessageDelete` 的处理函数可以两处都注册。

    Attributes:
        message: 被删除的消息。
        op_user: 执行删除的用户。
    """

    event_name = "MESSAGE_DELETE"
    intent = Intents.GUILD_MESSAGES


class PublicMessageDelete(MessageDelete):
    """子频道里的消息被删除（公域），对应事件 `PUBLIC_MESSAGE_DELETE`；字段同 `MessageDelete`。"""

    event_name = "PUBLIC_MESSAGE_DELETE"
    intent = Intents.PUBLIC_GUILD_MESSAGES


class DirectMessageDelete(_MessageDeleteEvent):
    """频道私信被删除（撤回），对应事件 `DIRECT_MESSAGE_DELETE`；字段同 `MessageDelete`。"""

    event_name = "DIRECT_MESSAGE_DELETE"
    intent = Intents.DIRECT_MESSAGE


# ---- 消息审核 ----


class _MessageAuditEvent(Event):
    audit_id: str
    message_id: str | None = None
    guild_id: str | None = None
    channel_id: str | None = None
    audit_time: datetime | None = None
    create_time: datetime | None = None
    seq_in_channel: str | None = None


class MessageAuditPass(_MessageAuditEvent):
    """机器人发出的消息通过了审核，对应事件 `MESSAGE_AUDIT_PASS`。

    Attributes:
        audit_id: 审核 ID，与发消息时平台返回的审核 ID 对应。
        message_id: 消息 ID，审核通过才有。
        guild_id: 频道 ID。
        channel_id: 子频道 ID。
        audit_time: 审核时间，带时区。
        create_time: 消息创建时间，带时区。
        seq_in_channel: 子频道内的消息序号。
    """

    event_name = "MESSAGE_AUDIT_PASS"
    intent = Intents.MESSAGE_AUDIT


class MessageAuditReject(_MessageAuditEvent):
    """机器人发出的消息没有通过审核，对应事件 `MESSAGE_AUDIT_REJECT`；字段同 `MessageAuditPass`。"""

    event_name = "MESSAGE_AUDIT_REJECT"
    intent = Intents.MESSAGE_AUDIT


# ---- 表情表态 ----


class EmojiType(OpenIntEnum):
    """表情的类型（`Emoji.type`）。

    Attributes:
        SYSTEM: QQ 系统表情，ID 是数字的字符串，如 `"4"`。
        EMOJI: emoji，ID 是它的码点的十进制字符串，如 `"128077"`。
    """

    SYSTEM = 1
    EMOJI = 2


class Emoji(Model):
    """表情。可以自己构造，如 `Emoji(id="4", type=EmojiType.SYSTEM)`。

    Attributes:
        id: 表情 ID，见官方文档的 Emoji 列表。
        type: 表情类型。
    """

    id: str
    type: EmojiType


class ReactionTargetType(OpenIntEnum):
    """表态的对象是什么（`ReactionTarget.type`）。"""

    MESSAGE = 0
    THREAD = 1
    POST = 2
    REPLY = 3


class ReactionTarget(Model):
    """表态的对象。

    Attributes:
        id: 对象的 ID，如消息 ID。
        type: 对象的类型。
    """

    id: str
    type: ReactionTargetType | None = None


class _MessageReactionEvent(ChannelReplyTarget):
    channel_id: str
    guild_id: str | None = None
    user_id: str | None = None
    target: ReactionTarget
    emoji: Emoji

    async def reply(
        self,
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
    ) -> GuildMessage:
        """用事件 ID 被动回复，发到表态所在的子频道，`event_id` 由 SDK 填写；参数同 `client.channels.send_message()`。

        对应官方接口 `POST /channels/{channel_id}/messages`。

        Raises:
            AuditPendingError: 消息要等人工审核，审核结果由事件推送。
            APIError: 平台拒绝发送，例如回复已过期。
            NetworkError: 没有拿到平台的响应。
            ValueError: 内容参数的组合不合法；事件没有事件 ID。
            OSError: 读取 `image_path` 失败。
            RuntimeError: 事件不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。
        """
        client = self._bound_client()
        return await client.channels.send_message(
            self.channel_id,
            content,
            markdown=markdown,
            keyboard=keyboard,
            embed=embed,
            ark=ark,
            image=image,
            image_path=image_path,
            image_data=image_data,
            quote=quote,
            reply_to=self,
        )


class MessageReactionAdd(_MessageReactionEvent):
    """用户对频道里的消息等添加了表情表态，对应事件 `MESSAGE_REACTION_ADD`。可以用事件 ID 被动回复到子频道。

    Attributes:
        user_id: 表态的用户 ID。
        guild_id: 频道 ID。
        channel_id: 子频道 ID。
        target: 表态的对象。
        emoji: 所用的表情。
    """

    event_name = "MESSAGE_REACTION_ADD"
    intent = Intents.GUILD_MESSAGE_REACTIONS


class MessageReactionRemove(_MessageReactionEvent):
    """用户取消了表情表态，对应事件 `MESSAGE_REACTION_REMOVE`；字段同 `MessageReactionAdd`。"""

    event_name = "MESSAGE_REACTION_REMOVE"
    intent = Intents.GUILD_MESSAGE_REACTIONS


# ---- 接口的响应 ----


class ReactionUserPage(Model):
    """表态用户列表的一页（`GET /channels/{channel_id}/messages/{message_id}/reactions/{type}/{id}`）。"""

    users: tuple[GuildUser, ...] = ()
    cookie: str | None = None
    is_end: bool = False


class DirectMessageSession(Model):
    """私信会话，由 `client.dms.create_session()` 返回。

    Attributes:
        guild_id: 私信会话的 ID，发私信、撤回私信都用它；不是用户所在频道的 ID。
        channel_id: 私信会话关联的子频道 ID。
        create_time: 创建时间，Unix 秒的字符串。
    """

    guild_id: str
    channel_id: str | None = None
    create_time: str | None = None
