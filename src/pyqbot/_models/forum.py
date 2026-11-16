"""论坛：主题（帖子）、评论、回复的事件与富文本。

官方文档：`server-inter/channel/content/forum/forum.md`、`model.md`、`open_forum.md`，接口的响应见
`get_thread.md`、`get_threads_list.md`、`put_thread.md`。论坛里的「帖子」
（thread）是主帖，「评论」（post）是对主帖的评论，「回复」（reply）是对评论的回复。
富文本与 ID 类型的取舍见 `docs/design.md`「事件」。
"""

import os
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

import msgspec

from .._gateway.intents import Intents
from .._model import Model, OpenIntEnum, decode
from .event import ChannelReplyTarget, Event
from .send import Ark, Embed, Keyboard, Markdown

if TYPE_CHECKING:
    from .guild_message import GuildMessage

if TYPE_CHECKING:
    type _Id = str
else:
    # 示例里 ID 有时是数字：运行时也收整数，由 _IdNormalizer 转成字符串，见 docs/design.md「事件」。
    _Id = str | int


class _IdNormalizer(Model):
    # 子类把类型为 _Id 的字段名列在 _id_fields 里。
    _id_fields: ClassVar[tuple[str, ...]] = ()

    def __post_init__(self) -> None:
        for name in self._id_fields:
            value: object = getattr(self, name)
            if isinstance(value, int):
                object.__setattr__(self, name, str(value))  # 模型不可变，只能绕过 __setattr__


# ---- 富文本：事件里的 RichObject ----


class ForumRichType(OpenIntEnum):
    """富文本元素的类型（`ForumRichObject.type`），决定哪个 `*_info` 字段有值。"""

    TEXT = 1
    AT = 2
    URL = 3
    EMOJI = 4
    CHANNEL = 5
    VIDEO = 10
    IMAGE = 11


class ForumTextInfo(Model):
    """富文本里的普通文本。"""

    text: str = ""


class ForumAtType(OpenIntEnum):
    """富文本里 @ 的对象（`ForumAtInfo.type`）。

    Attributes:
        USER: 指定用户。
        ROLE: 某个身份组的所有人。
        GUILD: 频道里的所有人。
    """

    USER = 1
    ROLE = 2
    GUILD = 3


class ForumAtUserInfo(Model):
    """@ 的用户。"""

    id: str | None = None
    nick: str = ""


class ForumAtRoleInfo(_IdNormalizer):
    """@ 的身份组。"""

    _id_fields = ("role_id",)

    role_id: _Id | None = None
    name: str = ""
    color: int | None = None


class ForumAtGuildInfo(Model):
    """@ 的频道。"""

    guild_id: str | None = None
    guild_name: str = ""


class ForumAtInfo(Model):
    """富文本里的 @，按 `type` 取 `user_info`、`role_info` 或 `guild_info`。"""

    type: ForumAtType | None = None
    user_info: ForumAtUserInfo | None = None
    role_info: ForumAtRoleInfo | None = None
    guild_info: ForumAtGuildInfo | None = None


class ForumUrlInfo(Model):
    """富文本里的链接。"""

    url: str = ""
    display_text: str = ""


class ForumEmojiInfo(_IdNormalizer):
    """富文本里的表情。`type` 在文档里是字符串，与表情表态的 `EmojiType` 不同。"""

    _id_fields = ("id",)

    id: _Id | None = None
    type: str | None = None
    name: str = ""
    url: str | None = None


class ForumChannelInfo(_IdNormalizer):
    """富文本里提到的子频道。"""

    _id_fields = ("channel_id",)

    channel_id: _Id | None = None
    channel_name: str = ""


class ForumRichObject(Model):
    """论坛事件里的一段富文本，按 `type` 取对应的 `*_info` 字段。

    Example:
        ```python
        text = "".join(
            obj.text_info.text for obj in rich if obj.type == pyqbot.ForumRichType.TEXT and obj.text_info
        )
        ```
    """

    type: ForumRichType | None = None
    text_info: ForumTextInfo | None = None
    at_info: ForumAtInfo | None = None
    url_info: ForumUrlInfo | None = None
    emoji_info: ForumEmojiInfo | None = None
    channel_info: ForumChannelInfo | None = None


# ---- 富文本：帖子内容字符串里的 RichText ----


class ForumElemType(OpenIntEnum):
    """`ForumRichText` 里元素的类型（`ForumElem.type`），决定哪个字段有值。"""

    TEXT = 1
    IMAGE = 2
    VIDEO = 3
    URL = 4


class ForumAlignment(OpenIntEnum):
    """段落的对齐方向。"""

    LEFT = 0
    MIDDLE = 1
    RIGHT = 2


class ForumTextProps(Model):
    """文本的样式。"""

    font_bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None


class ForumTextElem(Model):
    """文本元素。"""

    text: str = ""
    props: ForumTextProps | None = None


class ForumImageElem(Model):
    """图片元素；`width_percent` 是在屏幕里显示的宽度比例。"""

    third_url: str | None = None
    width_percent: float | None = None


class ForumVideoElem(Model):
    """视频元素。"""

    third_url: str | None = None


class ForumUrlElem(Model):
    """链接元素。"""

    url: str = ""
    desc: str = ""


class ForumElem(Model):
    """段落里的一个元素，按 `type` 取 `text`、`image`、`video` 或 `url`。"""

    type: ForumElemType | None = None
    text: ForumTextElem | None = None
    image: ForumImageElem | None = None
    video: ForumVideoElem | None = None
    url: ForumUrlElem | None = None


class ForumParagraphProps(Model):
    """段落的属性。"""

    alignment: ForumAlignment | None = None


class ForumParagraph(Model):
    """一个段落，即一行；没有元素的是空行。"""

    elems: tuple[ForumElem, ...] = ()
    props: ForumParagraphProps | None = None


class ForumRichText(Model):
    """帖子的富文本内容（官方的 RichText），用 `from_json()` 从帖子的 `content` 字符串解析。

    Attributes:
        paragraphs: 段落，一段一行。
    """

    paragraphs: tuple[ForumParagraph, ...] = ()

    @classmethod
    def from_json(cls, text: str | bytes) -> ForumRichText:
        """解析 JSON 形式的富文本，如获取帖子详情时 `content` 字段的字符串。

        Raises:
            ValueError: 不是 JSON 对象。
        """
        try:
            # decode 是宽容的：结构不对的字段退回默认值，只有整体不是对象时才失败。
            return decode(text, cls)
        except (msgspec.DecodeError, RecursionError) as exc:
            raise ValueError(f"无法解析论坛富文本：{exc}") from exc


# ---- 论坛事件 ----


class ForumThreadInfo(Model):
    """主帖的内容。

    Attributes:
        thread_id: 主帖 ID。
        title: 标题：文档的模型说是字符串，事件示例里是 `ForumRichObject` 数组，两种都原样保留。
        content: 内容，形式同 `title`；是字符串时可能是 JSON 形式的富文本，可用 `ForumRichText.from_json()` 解析。
        date_time: 发表时间，带时区。
    """

    thread_id: str
    title: str | tuple[ForumRichObject, ...] = ""
    content: str | tuple[ForumRichObject, ...] = ""
    date_time: datetime | None = None


class ForumPostInfo(Model):
    """评论的内容。

    Attributes:
        thread_id: 所属主帖的 ID。
        post_id: 评论 ID。
        content: 内容，形式同 `ForumThreadInfo.content`。
        date_time: 评论时间，带时区。
    """

    thread_id: str | None = None
    post_id: str
    content: str | tuple[ForumRichObject, ...] = ""
    date_time: datetime | None = None


class ForumReplyInfo(Model):
    """回复的内容。

    Attributes:
        thread_id: 所属主帖的 ID。
        post_id: 所属评论的 ID。
        reply_id: 回复 ID。
        content: 内容，形式同 `ForumThreadInfo.content`。
        date_time: 回复时间，带时区。
    """

    thread_id: str | None = None
    post_id: str | None = None
    reply_id: str
    content: str | tuple[ForumRichObject, ...] = ""
    date_time: datetime | None = None


class _ForumEvent(_IdNormalizer, ChannelReplyTarget):
    _id_fields = ("guild_id", "channel_id", "author_id")

    guild_id: _Id | None = None
    channel_id: _Id
    author_id: _Id | None = None

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
        """用事件 ID 被动回复，发到论坛子频道，`event_id` 由 SDK 填写；参数同 `client.channels.send_message()`。

        对应官方接口 `POST /channels/{channel_id}/messages`。

        Raises:
            AuditPendingError: 消息要等人工审核，审核结果由事件推送。
            APIError: 平台拒绝发送，例如事件 ID 已过期。
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


class _ForumThreadEvent(_ForumEvent):
    thread_info: ForumThreadInfo


class ForumThreadCreate(_ForumThreadEvent):
    """用户在论坛子频道发表了主帖，对应事件 `FORUM_THREAD_CREATE`；仅私域机器人可用。

    可以用事件 ID 被动回复到子频道。

    Attributes:
        guild_id: 频道 ID。
        channel_id: 论坛子频道的 ID。
        author_id: 作者的用户 ID。
        thread_info: 主帖的内容。
    """

    event_name = "FORUM_THREAD_CREATE"
    intent = Intents.FORUMS_EVENT


class ForumThreadUpdate(_ForumThreadEvent):
    """用户更新了主帖，对应事件 `FORUM_THREAD_UPDATE`；字段同 `ForumThreadCreate`。"""

    event_name = "FORUM_THREAD_UPDATE"
    intent = Intents.FORUMS_EVENT


class ForumThreadDelete(_ForumThreadEvent):
    """用户删除了主帖，对应事件 `FORUM_THREAD_DELETE`；字段同 `ForumThreadCreate`。"""

    event_name = "FORUM_THREAD_DELETE"
    intent = Intents.FORUMS_EVENT


class _ForumPostEvent(_ForumEvent):
    post_info: ForumPostInfo


class ForumPostCreate(_ForumPostEvent):
    """用户评论了主帖，对应事件 `FORUM_POST_CREATE`；仅私域机器人可用。可以用事件 ID 被动回复到子频道。

    Attributes:
        guild_id: 频道 ID。
        channel_id: 论坛子频道的 ID。
        author_id: 作者的用户 ID。
        post_info: 评论的内容。
    """

    event_name = "FORUM_POST_CREATE"
    intent = Intents.FORUMS_EVENT


class ForumPostDelete(_ForumPostEvent):
    """用户删除了评论，对应事件 `FORUM_POST_DELETE`；字段同 `ForumPostCreate`。"""

    event_name = "FORUM_POST_DELETE"
    intent = Intents.FORUMS_EVENT


class _ForumReplyEvent(_ForumEvent):
    reply_info: ForumReplyInfo


class ForumReplyCreate(_ForumReplyEvent):
    """用户回复了评论，对应事件 `FORUM_REPLY_CREATE`；仅私域机器人可用。可以用事件 ID 被动回复到子频道。

    Attributes:
        guild_id: 频道 ID。
        channel_id: 论坛子频道的 ID。
        author_id: 作者的用户 ID。
        reply_info: 回复的内容。
    """

    event_name = "FORUM_REPLY_CREATE"
    intent = Intents.FORUMS_EVENT


class ForumReplyDelete(_ForumReplyEvent):
    """用户删除了回复，对应事件 `FORUM_REPLY_DELETE`；字段同 `ForumReplyCreate`。"""

    event_name = "FORUM_REPLY_DELETE"
    intent = Intents.FORUMS_EVENT


class ForumAuditType(OpenIntEnum):
    """审核的是什么（`ForumPublishAuditResult.type`）。"""

    THREAD = 1
    POST = 2
    REPLY = 3


class ForumAuditOutcome(OpenIntEnum):
    """审核结果（`ForumPublishAuditResult.result`）。"""

    SUCCESS = 0
    FAILED = 1


class ForumPublishAuditResult(_IdNormalizer, Event):
    """机器人发表的主帖、评论或回复的审核结果，对应事件 `FORUM_PUBLISH_AUDIT_RESULT`；仅私域机器人可用。

    Attributes:
        guild_id: 频道 ID。
        channel_id: 论坛子频道的 ID。
        author_id: 作者的用户 ID。
        type: 审核的是主帖、评论还是回复。
        result: 审核结果。
        err_msg: 审核不通过时的原因，没有时为空串。
        thread_id: 主帖 ID。
        post_id: 评论 ID。
        reply_id: 回复 ID。
    """

    event_name = "FORUM_PUBLISH_AUDIT_RESULT"
    intent = Intents.FORUMS_EVENT
    _id_fields = ("guild_id", "channel_id", "author_id")

    guild_id: _Id | None = None
    channel_id: _Id | None = None
    author_id: _Id | None = None
    type: ForumAuditType | None = None
    result: ForumAuditOutcome | None = None
    err_msg: str = ""
    thread_id: str | None = None
    post_id: str | None = None
    reply_id: str | None = None


# ---- 公域论坛 ----


class _OpenForumEvent(_IdNormalizer, Event):
    # 文档没有给出 Intent 位，见 docs/design.md「事件」。
    intent = Intents(0)
    _id_fields = ("guild_id", "channel_id", "author_id")

    guild_id: _Id | None = None
    channel_id: _Id
    author_id: _Id | None = None


class OpenForumThreadCreate(_OpenForumEvent):
    """公域论坛：用户发表了主帖，对应事件 `OPEN_FORUM_THREAD_CREATE`。

    文档只给出 `guild_id`、`channel_id`、`author_id` 三个字段，没有帖子内容。

    Attributes:
        guild_id: 频道 ID。
        channel_id: 论坛子频道的 ID。
        author_id: 作者的用户 ID。
    """

    event_name = "OPEN_FORUM_THREAD_CREATE"


class OpenForumThreadUpdate(_OpenForumEvent):
    """公域论坛：用户更新了主帖，对应事件 `OPEN_FORUM_THREAD_UPDATE`；字段同 `OpenForumThreadCreate`。"""

    event_name = "OPEN_FORUM_THREAD_UPDATE"


class OpenForumThreadDelete(_OpenForumEvent):
    """公域论坛：用户删除了主帖，对应事件 `OPEN_FORUM_THREAD_DELETE`；字段同 `OpenForumThreadCreate`。"""

    event_name = "OPEN_FORUM_THREAD_DELETE"


class OpenForumPostCreate(_OpenForumEvent):
    """公域论坛：用户评论了主帖，对应事件 `OPEN_FORUM_POST_CREATE`；字段同 `OpenForumThreadCreate`。"""

    event_name = "OPEN_FORUM_POST_CREATE"


class OpenForumPostDelete(_OpenForumEvent):
    """公域论坛：用户删除了评论，对应事件 `OPEN_FORUM_POST_DELETE`；字段同 `OpenForumThreadCreate`。"""

    event_name = "OPEN_FORUM_POST_DELETE"


class OpenForumReplyCreate(_OpenForumEvent):
    """公域论坛：用户回复了评论，对应事件 `OPEN_FORUM_REPLY_CREATE`；字段同 `OpenForumThreadCreate`。"""

    event_name = "OPEN_FORUM_REPLY_CREATE"


class OpenForumReplyDelete(_OpenForumEvent):
    """公域论坛：用户删除了回复，对应事件 `OPEN_FORUM_REPLY_DELETE`；字段同 `OpenForumThreadCreate`。"""

    event_name = "OPEN_FORUM_REPLY_DELETE"


# ---- 帖子接口 ----


class ForumThread(_IdNormalizer):
    """论坛子频道里的一个主帖，由帖子列表与详情接口返回。

    Attributes:
        guild_id: 频道 ID。
        channel_id: 论坛子频道的 ID。
        author_id: 作者的用户 ID。
        thread_info: 主帖的内容；接口返回的 `content` 是 JSON 形式的富文本字符串，
            可用 `ForumRichText.from_json()` 解析。
    """

    _id_fields = ("guild_id", "channel_id", "author_id")

    guild_id: _Id | None = None
    channel_id: _Id | None = None
    author_id: _Id | None = None
    thread_info: ForumThreadInfo


class ForumThreadList(Model):
    """帖子列表（`client.channels.list_threads()`）。

    Attributes:
        threads: 主帖。
        is_finish: 为 1 时已经全部取完，见 `finished`。
    """

    threads: tuple[ForumThread, ...] = ()
    is_finish: int | None = None

    @property
    def finished(self) -> bool:
        """是否已经全部取完（`is_finish` 为 1）。"""
        return self.is_finish == 1


class ThreadResponse(Model):
    """帖子详情接口的响应外壳。"""

    thread: ForumThread


class ForumThreadFormat(OpenIntEnum):
    """发帖时 `content` 的格式（`format`）。

    Attributes:
        TEXT: 普通文本。
        HTML: HTML。
        MARKDOWN: Markdown。
        JSON: JSON 形式的富文本，结构同 `ForumRichText`。
    """

    TEXT = 1
    HTML = 2
    MARKDOWN = 3
    JSON = 4


class ForumPublishTask(Model):
    """发帖任务：帖子要审核，结果由 `FORUM_PUBLISH_AUDIT_RESULT` 事件推送。

    Attributes:
        task_id: 任务 ID。
        create_time: 发帖时间，Unix 秒的字符串。
    """

    task_id: str
    create_time: str | None = None
