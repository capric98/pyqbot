"""频道与子频道管理接口专用的模型；频道、子频道、成员、身份组本身见 `guild.py`。

官方文档：`server-inter/channel/role-group/`、`role/member/`、`api_permissions/`、`speak/`。
"""

import enum
from typing import TYPE_CHECKING, Annotated, ClassVar

import msgspec

from .._model import Model, OpenIntEnum
from .guild import Channel, Guild, GuildMember, GuildRole

if TYPE_CHECKING:
    type _Flag = bool
else:
    # 表格说是字符串、示例是布尔（docs/errata.md），两种都收，由 MessageSetting 统一成布尔。
    _Flag = bool | str


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


class RecallDays(OpenIntEnum):
    """移出频道成员时，同时撤回该成员多少天内的消息。

    Attributes:
        NONE: 不撤回。
        DAYS_3: 3 天内。
        DAYS_7: 7 天内。
        DAYS_15: 15 天内。
        DAYS_30: 30 天内。
        ALL: 全部消息。
    """

    NONE = 0
    DAYS_3 = 3
    DAYS_7 = 7
    DAYS_15 = 15
    DAYS_30 = 30
    ALL = -1


class GuildRoles(Model):
    """频道的身份组列表，由 `client.guilds.list_roles()` 返回。

    Attributes:
        guild_id: 频道 ID。
        roles: 身份组，含系统默认的（见 `DefaultRoleId`）。
        role_num_limit: 可创建的身份组数量上限，十进制数字的字符串。
    """

    guild_id: str | None = None
    roles: tuple[GuildRole, ...] = ()
    role_num_limit: str | None = None


class APIIdentify(Model):
    """频道接口的标识：路径模板与请求方法。

    Attributes:
        path: 路径模板，如 `/guilds/{guild_id}/members/{user_id}`。
        method: 请求方法，如 `GET`。
    """

    path: str = ""
    method: str = ""


class APIPermission(APIIdentify):
    """机器人在某个频道里的一项接口权限。

    Attributes:
        path: 路径模板，如 `/guilds/{guild_id}/members/{user_id}`。
        method: 请求方法，如 `GET`。
        desc: 接口的名称，如「获取当前频道成员信息」。
        auth_status: 授权状态，1 为已授权；用 `authorized` 判断即可。
    """

    desc: str = ""
    auth_status: int | None = None

    @property
    def authorized(self) -> bool:
        """是否已经授权。"""
        return self.auth_status == 1


class APIPermissionDemand(Model):
    """发出的接口授权链接，由 `client.guilds.request_api_permission()` 返回。

    Attributes:
        guild_id: 频道 ID。
        channel_id: 授权链接发到的子频道 ID。
        api_identify: 申请的接口。
        title: 授权链接里的接口权限说明。
        desc: 授权链接里的功能说明。
    """

    guild_id: str | None = None
    channel_id: str | None = None
    api_identify: APIIdentify | None = None
    title: str = ""
    desc: str = ""


class MessageSetting(Model):
    """机器人在频道里的消息频率设置，由 `client.guilds.get_message_setting()` 返回。

    两个开关的说明是「是否允许」，字段名却是 `disable_*`，以平台的实际行为为准（见 `docs/errata.md`）。

    Attributes:
        disable_create_dm: 是否禁止创建私信；认不出的取值为 `None`。
        disable_push_msg: 是否禁止发主动消息；同上。
        channel_ids: 子频道 ID。
        channel_push_max_num: 每个子频道允许主动推送的最大消息条数（周期未说明）。
    """

    _flag_fields: ClassVar[tuple[str, ...]] = ("disable_create_dm", "disable_push_msg")

    disable_create_dm: _Flag | None = None
    disable_push_msg: _Flag | None = None
    channel_ids: tuple[str, ...] = ()
    channel_push_max_num: int | None = None

    def __post_init__(self) -> None:
        for name in self._flag_fields:
            value: object = getattr(self, name)
            if isinstance(value, str):
                flag = _FLAG_STRINGS.get(value.strip().lower())
                object.__setattr__(self, name, flag)  # 模型不可变，只能绕过 __setattr__


_FLAG_STRINGS = {"true": True, "1": True, "false": False, "0": False}


# ---- 只在 SDK 内部解码用的响应 ----


class GuildList(Model):
    """`GET /users/@me/guilds` 的响应，裸数组由接口方法包成这个形式。"""

    guilds: tuple[Guild, ...] = ()


class ChannelList(Model):
    """`GET /guilds/{guild_id}/channels` 的响应，同上。"""

    channels: tuple[Channel, ...] = ()


class MemberList(Model):
    """`GET /guilds/{guild_id}/members` 的响应，同上。"""

    members: tuple[GuildMember, ...] = ()


class IdAnchor(Model):
    """列表里一条记录的非空 `id`，用作翻页锚点；缺了时解码失败。"""

    id: Annotated[str, msgspec.Meta(min_length=1)]


class MemberAnchor(Model):
    """成员列表里一条成员的 `user.id`：翻页锚点与去重依据，同上。"""

    user: IdAnchor


class RoleMemberPage(Model):
    """`GET /guilds/{guild_id}/roles/{role_id}/members` 的一页。"""

    data: tuple[GuildMember, ...] = ()
    next: str | None = None


class RoleResponse(Model):
    """创建、修改身份组的响应。"""

    role: GuildRole


class MuteResult(Model):
    """批量禁言的响应：设置成功的成员。"""

    user_ids: tuple[str, ...] = ()


class APIPermissionList(Model):
    """`GET /guilds/{guild_id}/api_permission` 的响应。"""

    apis: tuple[APIPermission, ...] = ()


class OnlineNums(Model):
    """`GET /channels/{channel_id}/online_nums` 的响应。"""

    # 文档说成功返回空对象，示例却有 online_nums；推测是 0 被省略了（docs/errata.md）。
    online_nums: int = 0


class PermissionsResponse(Model):
    """子频道用户、身份组权限的响应；`permissions` 是十进制数字的字符串。"""

    permissions: Annotated[str, msgspec.Meta(pattern=r"^[0-9]+$")]
