"""频道（guild）的共用模型，以及频道、子频道、频道成员的事件。

官方文档：`server-inter/channel/manage/guild/model.md`、`manage/channel/model.md`、`manage/user/model.md`、
`role/member/model.md`、`role/member/role_model.md`、`role/guild_member.md`，事件在 `autogen/event/` 下。
频道、子频道、用户的 ID 都是只在机器人场景流通的字符串，与真实的 ID 无关。
"""

import enum
from datetime import datetime

from .._gateway.intents import Intents
from .._model import Model, OpenIntEnum, OpenStrEnum
from .event import ChannelReplyTarget, Event


class Guild(Model):
    """频道。

    Attributes:
        id: 频道 ID。
        name: 频道名称。
        icon: 头像地址。
        owner_id: 创建者的用户 ID。
        owner: 机器人是否为创建者。
        member_count: 成员数。
        max_members: 成员上限。
        description: 简介。
        joined_at: 机器人加入的时间，带时区。
    """

    id: str
    name: str = ""
    icon: str | None = None
    owner_id: str | None = None
    owner: bool | None = None
    member_count: int | None = None
    max_members: int | None = None
    description: str = ""
    joined_at: datetime | None = None


class ChannelType(OpenIntEnum):
    """子频道的类型（`Channel.type`）。上游会持续新增类型，未知取值原样保留。

    Attributes:
        TEXT: 文字子频道。
        VOICE: 语音子频道。
        CATEGORY: 子频道分组。
        LIVE: 直播子频道。
        APPLICATION: 应用子频道。
        FORUM: 论坛子频道。
    """

    TEXT = 0
    VOICE = 2
    CATEGORY = 4
    LIVE = 10005
    APPLICATION = 10006
    FORUM = 10007


class ChannelSubType(OpenIntEnum):
    """文字子频道的子类型（`Channel.sub_type`）。

    Attributes:
        CHAT: 闲聊。
        ANNOUNCEMENT: 公告。
        GUIDE: 攻略。
        GAMING: 开黑。
    """

    CHAT = 0
    ANNOUNCEMENT = 1
    GUIDE = 2
    GAMING = 3


class PrivateType(OpenIntEnum):
    """子频道对谁可见（`Channel.private_type`）。

    Attributes:
        PUBLIC: 所有人。
        ADMINS: 频道主与管理员。
        ADMINS_AND_MEMBERS: 频道主、管理员与指定成员。
    """

    PUBLIC = 0
    ADMINS = 1
    ADMINS_AND_MEMBERS = 2


class SpeakPermission(OpenIntEnum):
    """谁能在子频道发言（`Channel.speak_permission`）。

    Attributes:
        INVALID: 无效类型。
        EVERYONE: 所有人。
        ADMINS_AND_MEMBERS: 频道主、管理员与指定成员。
    """

    INVALID = 0
    EVERYONE = 1
    ADMINS_AND_MEMBERS = 2


class ChannelPermission(enum.IntFlag):
    """子频道权限位，多个权限用 `|` 组合；未列出的位（上游新增的权限）原样保留。

    Attributes:
        VIEW: 可查看子频道。
        MANAGE: 可管理子频道；创建者、管理员、子频道管理员都有，不能通过接口修改。
        SPEAK: 可在子频道发言。

    Example:
        ```python
        await client.channels.update_member_permissions(
            channel_id, user_id, add=pyqbot.ChannelPermission.VIEW | pyqbot.ChannelPermission.SPEAK
        )
        ```
    """

    VIEW = 1 << 0
    MANAGE = 1 << 1
    SPEAK = 1 << 2


class Channel(Model):
    """子频道。

    Attributes:
        id: 子频道 ID。
        guild_id: 所属频道的 ID。
        name: 名称。
        type: 类型。
        sub_type: 子类型，只有文字子频道有。
        position: 排序值，从 1 开始。
        parent_id: 所属分组的 ID。
        owner_id: 创建者的用户 ID。
        private_type: 对谁可见。
        speak_permission: 谁能发言。
        application_id: 应用子频道的应用类型，如 `"1000000"`（王者开黑大厅）。
        permissions: 机器人在这个子频道拥有的权限，是十进制数字的字符串；按位使用时取 `permission_flags`。
    """

    id: str
    guild_id: str | None = None
    name: str = ""
    type: ChannelType | None = None
    sub_type: ChannelSubType | None = None
    position: int | None = None
    parent_id: str | None = None
    owner_id: str | None = None
    private_type: PrivateType | None = None
    speak_permission: SpeakPermission | None = None
    application_id: str | None = None
    permissions: str | None = None

    @property
    def permission_flags(self) -> ChannelPermission | None:
        """`permissions` 换成的权限位；没有或认不出时为 `None`。"""
        value = self.permissions
        if value is None or not (value.isascii() and value.isdecimal()):
            return None
        try:
            return ChannelPermission(int(value))
        except ValueError:  # 位数超过整数转换的上限
            return None


class GuildUser(Model):
    """频道里的用户，如频道消息的发送者、频道成员。

    Attributes:
        id: 用户 ID，频道、子频道、私信的接口都用它。
        username: 用户名。
        avatar: 头像地址。
        bot: 是否为机器人。
        union_openid: 跨应用统一的 openid，需要申请；只有单独获取成员信息时才有。
        union_user_account: 互联应用的用户信息，同上。
    """

    id: str | None = None
    username: str = ""
    avatar: str | None = None
    bot: bool | None = None
    union_openid: str | None = None
    union_user_account: str | None = None


class GuildMember(Model):
    """频道成员，如频道消息的 `member`。

    Attributes:
        user: 用户信息；只有成员相关的接口与事件才有，消息里的 `member` 没有。
        nick: 在频道里的昵称，没有时为空串。
        roles: 身份组 ID，系统默认的取值见 `DefaultRoleId`。
        joined_at: 加入频道的时间，带时区。
    """

    user: GuildUser | None = None
    nick: str = ""
    roles: tuple[str, ...] = ()
    joined_at: datetime | None = None


class DefaultRoleId(OpenStrEnum):
    """系统默认的身份组 ID，可以直接与 `GuildMember.roles` 里的字符串比较。

    Attributes:
        EVERYONE: 全体成员。
        ADMIN: 管理员。
        OWNER: 频道主（创建者）。
        CHANNEL_ADMIN: 子频道管理员。

    Example:
        ```python
        if pyqbot.DefaultRoleId.ADMIN in member.roles:
            ...
        ```
    """

    EVERYONE = "1"
    ADMIN = "2"
    OWNER = "4"
    CHANNEL_ADMIN = "5"


class GuildRole(Model):
    """频道的身份组。

    Attributes:
        id: 身份组 ID，系统默认的取值见 `DefaultRoleId`。
        name: 名称。
        color: ARGB 颜色值，十进制整数。
        hoist: 是否在成员列表中单独展示：0 否，1 是。
        number: 人数。
        member_limit: 成员上限。
    """

    id: str
    name: str = ""
    color: int | None = None
    hoist: int | None = None
    number: int | None = None
    member_limit: int | None = None


# ---- 频道与子频道的事件 ----


class _GuildEvent(Guild, Event):
    op_user_id: str | None = None


class GuildCreate(_GuildEvent):
    """机器人加入了一个频道，对应事件 `GUILD_CREATE`。

    字段同 `Guild`，另有 `op_user_id`（操作人的用户 ID）。
    """

    event_name = "GUILD_CREATE"
    intent = Intents.GUILDS


class GuildUpdate(_GuildEvent):
    """频道资料变了，对应事件 `GUILD_UPDATE`；字段是变更后的数据，同 `GuildCreate`。"""

    event_name = "GUILD_UPDATE"
    intent = Intents.GUILDS


class GuildDelete(_GuildEvent):
    """频道被解散或机器人被移出，对应事件 `GUILD_DELETE`；字段是变更前的数据，同 `GuildCreate`。"""

    event_name = "GUILD_DELETE"
    intent = Intents.GUILDS


class _ChannelEvent(Channel, Event):
    op_user_id: str | None = None


class ChannelCreate(_ChannelEvent):
    """子频道被创建，对应事件 `CHANNEL_CREATE`。

    字段同 `Channel`，另有 `op_user_id`（操作人的用户 ID）。
    """

    event_name = "CHANNEL_CREATE"
    intent = Intents.GUILDS


class ChannelUpdate(_ChannelEvent):
    """子频道被更新，对应事件 `CHANNEL_UPDATE`；字段同 `ChannelCreate`。"""

    event_name = "CHANNEL_UPDATE"
    intent = Intents.GUILDS


class ChannelDelete(_ChannelEvent):
    """子频道被删除，对应事件 `CHANNEL_DELETE`；字段同 `ChannelCreate`。"""

    event_name = "CHANNEL_DELETE"
    intent = Intents.GUILDS


# ---- 频道成员的事件 ----


class _GuildMemberEvent(ChannelReplyTarget):
    # 与 GuildMember 同形但 user 必填，所以不继承它，见 docs/design.md「事件」。
    guild_id: str
    user: GuildUser
    nick: str = ""
    roles: tuple[str, ...] = ()
    joined_at: datetime | None = None
    op_user_id: str | None = None


class GuildMemberAdd(_GuildMemberEvent):
    """有用户加入频道，对应事件 `GUILD_MEMBER_ADD`。可以用事件 ID 被动回复到子频道。

    Attributes:
        guild_id: 频道 ID。
        user: 加入的用户。
        nick: 在频道里的昵称，没有时为空串。
        roles: 身份组 ID。
        joined_at: 加入时间，带时区。
        op_user_id: 操作人的用户 ID。
    """

    event_name = "GUILD_MEMBER_ADD"
    intent = Intents.GUILD_MEMBERS


class GuildMemberUpdate(_GuildMemberEvent):
    """频道成员的昵称、身份组等变了，对应事件 `GUILD_MEMBER_UPDATE`；字段同 `GuildMemberAdd`。"""

    event_name = "GUILD_MEMBER_UPDATE"
    intent = Intents.GUILD_MEMBERS


class GuildMemberRemove(_GuildMemberEvent):
    """用户离开频道，对应事件 `GUILD_MEMBER_REMOVE`；字段同 `GuildMemberAdd`。"""

    event_name = "GUILD_MEMBER_REMOVE"
    intent = Intents.GUILD_MEMBERS
