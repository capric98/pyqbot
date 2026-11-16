"""互动事件 `INTERACTION_CREATE`（`autogen/event/interaction_create.md`）及回应它用的枚举。"""

import os
from datetime import datetime

import msgspec

from .._gateway.intents import Intents
from .._model import Model, OpenIntEnum, OpenStrEnum
from .event import C2CReplyTarget, ChannelReplyTarget, GroupReplyTarget
from .guild_message import GuildMessage
from .message import SentMessage
from .send import Ark, Card, Embed, Keyboard, Markdown, Media


class InteractionType(OpenIntEnum):
    """互动的类型（`Interaction.type` 与 `data.type`）。

    Attributes:
        INLINE_KEYBOARD: 点击消息里的回调按钮，需要 `ack()`。
        CALLBACK_COMMAND: 点击单聊的快捷菜单，需要 `ack()`。
        MESSAGE_FEEDBACK: 对智能体消息点赞或点踩。
        CLEAR_SESSION: 清空智能体会话。
        IN_OUT_STORY: 进入或退出故事集。
        SWITCH_MODEL: 切换智能体模型。
        USER_AUTHORIZE: 用户授权。
        GROUP_AUTHORIZE: 群授权。
        GROUP_AUTHORIZE_STATUS: 群授权状态变更（文档没有说明）。
    """

    INLINE_KEYBOARD = 11
    CALLBACK_COMMAND = 12
    MESSAGE_FEEDBACK = 13
    CLEAR_SESSION = 14
    IN_OUT_STORY = 15
    SWITCH_MODEL = 16
    USER_AUTHORIZE = 18
    GROUP_AUTHORIZE = 19
    GROUP_AUTHORIZE_STATUS = 20


class ChatType(OpenIntEnum):
    """互动发生在哪里（`Interaction.chat_type`）。"""

    GUILD = 0
    GROUP = 1
    C2C = 2


class InteractionScene(OpenStrEnum):
    """互动发生在哪里（`Interaction.scene`），与 `ChatType` 一一对应。"""

    C2C = "c2c"
    GROUP = "group"
    GUILD = "guild"


class AuthorizeOptScene(OpenStrEnum):
    """用户在哪里授权（`InteractionAuthorizeData.opt_scene`）。

    Attributes:
        SETTING: 资料页设置。
        DIALOG: 弹窗授权。
    """

    SETTING = "setting"
    DIALOG = "dialog"


class AuthorizeScope(OpenStrEnum):
    """授权的范围（`InteractionAuthorizeData.scope`）。

    Attributes:
        C2C_PUSH: 单聊主动消息。
        GROUP_PUSH: 群主动消息。
    """

    C2C_PUSH = "c2c_push"
    GROUP_PUSH = "group_push"


class FeedbackOption(OpenStrEnum):
    """消息反馈的选项（`InteractionResolved.feedback_opt`）。"""

    LIKE = "LIKE"
    UNLIKE = "UNLIKE"


class InteractionResult(OpenIntEnum):
    """回应互动时告诉平台的结果（`code`），见 `Interaction.ack()`。

    Attributes:
        SUCCESS: 成功。
        FAILED: 操作失败。
        TOO_FREQUENT: 操作过于频繁。
        DUPLICATE: 重复操作。
        NO_PERMISSION: 没有权限。
        ADMIN_ONLY: 仅管理员可以操作。
    """

    SUCCESS = 0
    FAILED = 1
    TOO_FREQUENT = 2
    DUPLICATE = 3
    NO_PERMISSION = 4
    ADMIN_ONLY = 5


class InteractionAuthorizeData(Model):
    """授权类互动的内容：在哪里授权、授权了什么。

    Attributes:
        opt_scene: 在哪里操作的。
        scope: 授权的范围。
        switch: 是否打开。文档没有这个字段；实测打开时为 `true`，关闭时平台不带它，所以缺省为 `False`。
    """

    opt_scene: AuthorizeOptScene | None = None
    scope: AuthorizeScope | None = None
    switch: bool = False


class InteractionMessageScene(Model):
    """消息反馈所在消息的场景；`ext` 是 `key=value` 形式的字符串。"""

    ext: tuple[str, ...] = ()


class InteractionResolved(Model):
    """互动的具体内容，各字段只在对应类型下有值。

    Attributes:
        button_data: 按钮的 `data`；消息反馈时是回调数据。
        button_id: 按钮的 `id`。
        user_id: 操作者（仅频道）。
        feature_id: 快捷菜单的功能 ID。
        message_id: 被操作的消息 ID。
        feedback_opt: 消息反馈的选项。
        checked: 消息反馈的选项是否选中。
        action: 故事集的 `"ENTER_STORY"` / `"QUIT_STORY"`，或切换模型的动作。
        message_scene: 消息反馈所在消息的场景。
        authorize_data: 授权类互动的内容。
    """

    button_data: str | None = None
    button_id: str | None = None
    user_id: str | None = None
    feature_id: str | None = None
    message_id: str | None = None
    feedback_opt: FeedbackOption | None = None
    checked: int | None = None
    action: str | None = None
    message_scene: InteractionMessageScene | None = None
    authorize_data: InteractionAuthorizeData | None = None


class InteractionData(Model):
    """`Interaction.data`。"""

    type: InteractionType | None = None
    resolved: InteractionResolved = msgspec.field(default_factory=InteractionResolved)


# 文档的示例 3 没有 chat_type，只有 scene，所以按 scene 补上。
_SCENES = {
    InteractionScene.C2C: ChatType.C2C,
    InteractionScene.GROUP: ChatType.GROUP,
    InteractionScene.GUILD: ChatType.GUILD,
}


class Interaction(C2CReplyTarget, GroupReplyTarget, ChannelReplyTarget):
    """用户与机器人的互动，如点击回调按钮、快捷菜单、授权，对应事件 `INTERACTION_CREATE`。

    回调按钮与快捷菜单（`type` 为 `INLINE_KEYBOARD`、`CALLBACK_COMMAND`）要在收到后约 1 秒内回应（实测，文档写
    3 秒），否则用户那边提示「请求第三方失败」。`Bot` 默认在调用处理函数前替你回应「成功」（`auto_ack`）；
    关掉后要自己尽快 `ack()`，耗时的处理放在回应之后。单聊、群聊和频道的互动都可以用 `reply()` 被动回复。

    Attributes:
        id: 互动 ID，`ack()` 用它；与被动回复用的 `event_id`（payload 外层的 `id`）不是一个值。
        type: 互动的类型。
        chat_type: 发生在单聊、群聊还是频道。
        scene: 同上的字符串形式。
        timestamp: 触发时间，带时区。
        user_openid: 操作者的 openid，仅单聊。
        group_openid: 群的 openid，仅群聊。
        group_member_openid: 操作者在群里的 openid，仅群聊。
        guild_id: 频道 ID，仅频道。
        channel_id: 子频道 ID，仅频道。
        data: 互动的具体内容；常用的按钮字段另有 `button_data`、`button_id` 属性。
        version: 版本号。
        application_id: 机器人的 AppID。

    Example:
        ```python
        @bot.on_interaction
        async def clicked(interaction: pyqbot.Interaction) -> None:
            await interaction.reply(f"你点了 {interaction.button_data}")  # 已由 SDK 回应
        ```
    """

    event_name = "INTERACTION_CREATE"
    intent = Intents.INTERACTION

    id: str
    type: InteractionType | None = None
    chat_type: ChatType | None = None
    scene: InteractionScene | None = None
    timestamp: datetime | None = None
    user_openid: str | None = None
    group_openid: str | None = None
    group_member_openid: str | None = None
    guild_id: str | None = None
    channel_id: str | None = None
    data: InteractionData = msgspec.field(default_factory=InteractionData)
    version: int | None = None
    application_id: str | None = None

    @property
    def button_data(self) -> str | None:
        """被点击按钮的 `data`，即 `data.resolved.button_data`。"""
        return self.data.resolved.button_data

    @property
    def button_id(self) -> str | None:
        """被点击按钮的 `id`，即 `data.resolved.button_id`。"""
        return self.data.resolved.button_id

    async def ack(self, *, code: InteractionResult = InteractionResult.SUCCESS) -> None:
        """回应这次互动，用户那边随之结束等待；参数同 `client.interactions.ack()`。

        只有回调按钮与快捷菜单需要回应，要在收到后约 1 秒内完成；晚了或重复回应，平台也不报错。

        对应官方接口 `PUT /interactions/{interaction_id}`。

        Raises:
            APIError: 平台拒绝，例如互动不存在（超时与重复回应实测都不报错）。
            NetworkError: 没有拿到平台的响应。
            RuntimeError: 事件不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。
        """
        await self._bound_client().interactions.ack(self, code=code)

    async def reply(
        self,
        content: str | None = None,
        *,
        markdown: str | Markdown | None = None,
        keyboard: Keyboard | None = None,
        media: Media | None = None,
        card: Card | None = None,
        embed: Embed | None = None,
        ark: Ark | None = None,
        image: str | None = None,
        image_path: str | os.PathLike[str] | None = None,
        image_data: bytes | None = None,
        quote: str | SentMessage | GuildMessage | None = None,
    ) -> SentMessage | GuildMessage:
        """用事件 ID 被动回复：单聊发给操作者，群聊发到群里，频道发到互动所在的子频道。

        `event_id` 与 `msg_seq`（频道不带）由 SDK 填写。单聊、群聊的参数同 `client.users.send_message()`，
        频道的同 `client.channels.send_message()`。只有一边支持的参数，在另一边传了就抛 `ValueError`：
        `media`、`card` 与 `SentMessage` 引用只用于单聊、群聊，`embed`、`ark`、图片与 `GuildMessage` 引用只用于频道。
        返回值在频道里是 `GuildMessage`，否则是 `SentMessage`。

        对应官方接口 `POST /v2/users/{user_openid}/messages`、`POST /v2/groups/{group_openid}/messages`
        或 `POST /channels/{channel_id}/messages`。

        Raises:
            AuditPendingError: 频道里的消息要等人工审核。
            APIError: 平台拒绝发送，例如事件 ID 已过期（`err_code` 为 40034026）。
            NetworkError: 没有拿到平台的响应。
            ValueError: 内容参数的组合不合法，或传了这个场景不支持的参数；事件没有事件 ID；
                认不出场景，或缺少该场景的 openid、子频道 ID。
            OSError: 读取 `image_path` 失败。
            RuntimeError: 事件不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。
        """
        client = self._bound_client()
        chat_type = self.chat_type
        if chat_type is None and self.scene is not None:
            chat_type = _SCENES.get(self.scene)
        match chat_type:
            case ChatType.C2C if self.user_openid is not None:
                return await client.users.send_message(
                    self.user_openid,
                    content,
                    markdown=markdown,
                    keyboard=keyboard,
                    media=media,
                    card=card,
                    quote=_chat_quote(quote, embed, ark, image, image_path, image_data),
                    reply_to=self,
                )
            case ChatType.GROUP if self.group_openid is not None:
                return await client.groups.send_message(
                    self.group_openid,
                    content,
                    markdown=markdown,
                    keyboard=keyboard,
                    media=media,
                    card=card,
                    quote=_chat_quote(quote, embed, ark, image, image_path, image_data),
                    reply_to=self,
                )
            case ChatType.GUILD if self.channel_id is not None:
                if media is not None or card is not None or isinstance(quote, SentMessage):
                    raise ValueError("频道消息不支持 media、card，quote 不能是 SentMessage")
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
            case _:
                # 不带 scene 原文：平台给的字符串进异常前要脱敏（约定 7），整数的 chat_type 不用。
                chat_type_value = None if self.chat_type is None else int(self.chat_type)
                raise ValueError(
                    f"无法回复这次互动（chat_type={chat_type_value}）：认不出场景，"
                    "或缺少该场景的 user_openid / group_openid / channel_id"
                )


def _chat_quote(
    quote: str | SentMessage | GuildMessage | None, *channel_only: object
) -> str | SentMessage | None:
    """单聊、群聊回复的 `quote`；传了只有频道支持的参数时抛 `ValueError`。"""
    if isinstance(quote, GuildMessage) or any(value is not None for value in channel_only):
        raise ValueError("单聊、群聊消息不支持 embed、ark 与图片，quote 不能是频道消息")
    return quote
