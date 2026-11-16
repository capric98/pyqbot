"""频道级的管理接口：频道、子频道列表、成员、身份组、禁言、接口权限。分组边界见 `docs/design.md`。"""

from collections.abc import AsyncIterator, Callable, Iterable
from datetime import datetime, timedelta
from typing import cast

import msgspec

from .._http import HTTP, DecodedResponse, path_segment
from .._model import decode
from .._models.guild import (
    Channel,
    ChannelSubType,
    ChannelType,
    Guild,
    GuildMember,
    GuildRole,
    PrivateType,
    SpeakPermission,
)
from .._models.guild_manage import (
    APIPermission,
    APIPermissionDemand,
    APIPermissionList,
    ChannelList,
    GuildList,
    GuildRoles,
    IdAnchor,
    MemberAnchor,
    MemberList,
    MessageSetting,
    MuteResult,
    RecallDays,
    RoleMemberPage,
    RoleResponse,
)
from .paging import Page, paginate
from .params import str_list, unix_seconds

# 解除禁言：文档说两个字段任一传 "0" 即可，都传上，免得平台只认其中一个。
_UNMUTE = {"mute_end_timestamp": "0", "mute_seconds": "0"}


class Guilds:
    """频道相关的接口，经 `client.guilds` 使用；子频道自身的操作在 `client.channels`。

    标明「私域」的接口只有私域机器人可用；标明「管理员」的要求机器人在该频道是管理员。
    """

    def __init__(self, http: HTTP) -> None:
        self._http = http

    # ---- 频道 ----

    def iter_guilds(self, *, after: str | None = None, limit: int = 100) -> AsyncIterator[Guild]:
        """逐个产出机器人加入的频道，翻页由 SDK 完成。

        对应官方接口 `GET /users/@me/guilds`。

        Args:
            after: 从这个频道 ID 之后开始，不传则从头开始。
            limit: 每页条数，最多 100。

        Raises:
            APIError: 平台拒绝，或响应无法识别（含某页最后一个频道没有 ID，无法继续翻页）。
            NetworkError: 没有拿到平台的响应。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            async for guild in client.guilds.iter_guilds():
                print(guild.id, guild.name)
            ```
        """

        async def fetch(cursor: str | None) -> Page[Guild, str]:
            params: dict[str, str | int] = {"limit": limit}
            if anchor := cursor or after:
                params["after"] = anchor
            response = await self._http.request_decoded(
                "GET", "/users/@me/guilds", type_=object, params=params
            )
            items = _list_items(response, "guilds")
            guilds = decode(msgspec.json.encode({"guilds": items}), GuildList).guilds
            return Page(guilds, _anchor(response, items, IdAnchor, lambda guild: guild.id))

        return paginate(fetch)

    async def get(self, guild_id: str) -> Guild:
        """取频道的详情。

        对应官方接口 `GET /guilds/{guild_id}`。

        Raises:
            APIError: 平台拒绝，例如机器人不在这个频道。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        return await self._http.request("GET", _guild_path(guild_id), type_=Guild)

    # ---- 子频道 ----

    async def list_channels(self, guild_id: str) -> tuple[Channel, ...]:
        """列出频道下的所有子频道。

        对应官方接口 `GET /guilds/{guild_id}/channels`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_guild_path(guild_id)}/channels"
        response = await self._http.request_decoded("GET", path, type_=object)
        items = _list_items(response, "channels")
        return decode(msgspec.json.encode({"channels": items}), ChannelList).channels

    async def create_channel(
        self,
        guild_id: str,
        name: str,
        *,
        type: ChannelType = ChannelType.TEXT,
        sub_type: ChannelSubType | None = None,
        position: int | None = None,
        parent_id: str | None = None,
        private_type: PrivateType | None = None,
        private_user_ids: str | Iterable[str] = (),
        speak_permission: SpeakPermission | None = None,
        application_id: str | None = None,
    ) -> Channel:
        """创建子频道。私域；管理员。

        成功后平台推送 `CHANNEL_CREATE` 事件。

        对应官方接口 `POST /guilds/{guild_id}/channels`。

        Args:
            guild_id: 频道 ID。
            name: 子频道名称。
            type: 子频道类型。
            sub_type: 子类型，只对文字子频道有效。
            position: 排序值，从 1 开始；分组（`ChannelType.CATEGORY`）从 2 开始。
                填已有的值会插到它前面，不传则排在所属分组的最后。
            parent_id: 所属分组的 ID。
            private_type: 对谁可见。
            private_user_ids: `PrivateType.ADMINS_AND_MEMBERS` 时可见的成员的用户 ID。
            speak_permission: 谁能发言。
            application_id: 应用子频道的应用类型，见 `Channel.application_id`。

        Raises:
            APIError: 平台拒绝，例如不是私域机器人或机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 为空。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            channel = await client.guilds.create_channel(
                guild_id, "公告区", sub_type=pyqbot.ChannelSubType.ANNOUNCEMENT
            )
            ```
        """
        body = _present(
            name=name,
            type=type,
            sub_type=sub_type,
            position=position,
            parent_id=parent_id,
            private_type=private_type,
            private_user_ids=str_list(private_user_ids) or None,
            speak_permission=speak_permission,
            application_id=application_id,
        )
        path = f"{_guild_path(guild_id)}/channels"
        return await self._http.request("POST", path, type_=Channel, json=body)

    # ---- 成员 ----

    def iter_members(self, guild_id: str, *, limit: int = 400) -> AsyncIterator[GuildMember]:
        """逐个产出频道成员，翻页由 SDK 完成。私域。

        平台翻页时可能重复返回上一页的成员，SDK 已按用户 ID 去掉这些重复；没有用户 ID 的条目被跳过。

        对应官方接口 `GET /guilds/{guild_id}/members`。

        Args:
            guild_id: 频道 ID。
            limit: 每页条数，1～400；成员多的频道用大一些的值以减少请求。

        Raises:
            APIError: 平台拒绝，例如不是私域机器人；或响应无法识别、某页最后一个成员没有用户 ID
                （无法继续翻页）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 为空。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            async for member in client.guilds.iter_members(guild_id):
                print(member.user.id if member.user else None, member.nick)
            ```
        """
        path = f"{_guild_path(guild_id)}/members"
        # 文档说重复的是上一次请求返回过的，所以只记上一页，内存不随频道人数增长。
        # 没有 user.id 的条目没法去重，也不能做锚点，跳过。
        previous: set[str] = set()

        async def fetch(cursor: str | None) -> Page[GuildMember, str]:
            nonlocal previous
            params: dict[str, str | int] = {"limit": limit}
            if cursor:
                params["after"] = cursor
            response = await self._http.request_decoded("GET", path, type_=object, params=params)
            items = _list_items(response, "members")
            decoded = decode(msgspec.json.encode({"members": items}), MemberList).members
            members = [(user_id, m) for m in decoded if (user_id := _user_id(m))]
            fresh = [m for user_id, m in members if user_id not in previous]
            previous = {user_id for user_id, _ in members}
            return Page(fresh, _anchor(response, items, MemberAnchor, lambda m: m.user.id))

        return paginate(fetch)

    async def get_member(self, guild_id: str, user_id: str) -> GuildMember:
        """取频道成员的详情。

        对应官方接口 `GET /guilds/{guild_id}/members/{user_id}`。

        Raises:
            APIError: 平台拒绝，例如用户不在频道里。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 或 `user_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        return await self._http.request("GET", _member_path(guild_id, user_id), type_=GuildMember)

    async def remove_member(
        self,
        guild_id: str,
        user_id: str,
        *,
        add_blacklist: bool = False,
        recall: RecallDays = RecallDays.NONE,
    ) -> None:
        """把成员移出频道。私域；管理员。不能移出管理员。

        成功后平台推送 `GUILD_MEMBER_REMOVE` 事件。私域权限开通后，要把机器人移出频道再重新添加才生效。

        对应官方接口 `DELETE /guilds/{guild_id}/members/{user_id}`。

        Args:
            guild_id: 频道 ID。
            user_id: 要移出的用户 ID。
            add_blacklist: 同时把该用户加入频道黑名单。
            recall: 同时撤回该成员多少天内的消息。

        Raises:
            APIError: 平台拒绝，例如对方是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 或 `user_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        body = {"add_blacklist": add_blacklist, "delete_history_msg_days": recall}
        await self._http.request("DELETE", _member_path(guild_id, user_id), type_=None, json=body)

    def iter_role_members(
        self, guild_id: str, role_id: str, *, limit: int = 400
    ) -> AsyncIterator[GuildMember]:
        """逐个产出身份组里的成员，翻页由 SDK 完成。私域。

        对应官方接口 `GET /guilds/{guild_id}/roles/{role_id}/members`。

        Args:
            guild_id: 频道 ID。
            role_id: 身份组 ID，系统默认的见 `DefaultRoleId`。
            limit: 每页条数，1～400。

        Raises:
            APIError: 平台拒绝，例如不是私域机器人。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 或 `role_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_role_path(guild_id, role_id)}/members"

        async def fetch(cursor: str | None) -> Page[GuildMember, str]:
            params: dict[str, str | int] = {"limit": limit}
            if cursor:
                params["start_index"] = cursor
            page = await self._http.request("GET", path, type_=RoleMemberPage, params=params)
            # "0" 是第一页的起点，再从它开始会从头重来，所以当作结束（docs/errata.md）。
            end = not page.data or page.next == "0"
            return Page(page.data, None if end else page.next)

        return paginate(fetch)

    # ---- 身份组 ----

    async def list_roles(self, guild_id: str) -> GuildRoles:
        """列出频道的身份组，含数量上限。

        对应官方接口 `GET /guilds/{guild_id}/roles`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_guild_path(guild_id)}/roles"
        return await self._http.request("GET", path, type_=GuildRoles)

    async def create_role(
        self,
        guild_id: str,
        *,
        name: str | None = None,
        color: int | None = None,
        hoist: bool | None = None,
    ) -> GuildRole:
        """创建身份组。管理员。

        对应官方接口 `POST /guilds/{guild_id}/roles`。

        Args:
            guild_id: 频道 ID。
            name: 名称。
            color: ARGB 颜色值，如 `0xFFFF0000`（红色）。
            hoist: 是否在成员列表中单独展示。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员或身份组已达上限。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 为空，或三个参数一个都没传。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            role = await client.guilds.create_role(guild_id, name="活跃成员", hoist=True)
            ```
        """
        body = _role_body(name, color, hoist)
        path = f"{_guild_path(guild_id)}/roles"
        created = await self._http.request("POST", path, type_=RoleResponse, json=body)
        return created.role

    async def update_role(
        self,
        guild_id: str,
        role_id: str,
        *,
        name: str | None = None,
        color: int | None = None,
        hoist: bool | None = None,
    ) -> GuildRole:
        """修改身份组，只改传了的字段；返回修改后的身份组。管理员。

        对应官方接口 `PATCH /guilds/{guild_id}/roles/{role_id}`。

        Args:
            guild_id: 频道 ID。
            role_id: 身份组 ID。
            name: 名称。
            color: ARGB 颜色值。
            hoist: 是否在成员列表中单独展示。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 或 `role_id` 为空，或三个参数一个都没传。
            RuntimeError: 客户端已关闭。
        """
        body = _role_body(name, color, hoist)
        path = _role_path(guild_id, role_id)
        updated = await self._http.request("PATCH", path, type_=RoleResponse, json=body)
        return updated.role

    async def delete_role(self, guild_id: str, role_id: str) -> None:
        """删除身份组。管理员。

        对应官方接口 `DELETE /guilds/{guild_id}/roles/{role_id}`。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 或 `role_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        await self._http.request("DELETE", _role_path(guild_id, role_id), type_=None)

    async def add_member_role(
        self, guild_id: str, user_id: str, role_id: str, *, channel_id: str | None = None
    ) -> None:
        """把成员加入身份组。管理员。

        对应官方接口 `PUT /guilds/{guild_id}/members/{user_id}/roles/{role_id}`。

        Args:
            guild_id: 频道 ID。
            user_id: 用户 ID。
            role_id: 身份组 ID。
            channel_id: 身份组是 `DefaultRoleId.CHANNEL_ADMIN`（子频道管理员）时必须给出，指定是哪个子频道。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id`、`user_id` 或 `role_id` 为空。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.guilds.add_member_role(
                guild_id, user_id, pyqbot.DefaultRoleId.CHANNEL_ADMIN, channel_id=channel_id
            )
            ```
        """
        path = _member_role_path(guild_id, user_id, role_id)
        await self._http.request("PUT", path, type_=None, json=_channel_body(channel_id))

    async def remove_member_role(
        self, guild_id: str, user_id: str, role_id: str, *, channel_id: str | None = None
    ) -> None:
        """把成员移出身份组。管理员。

        对应官方接口 `DELETE /guilds/{guild_id}/members/{user_id}/roles/{role_id}`。

        Args:
            guild_id: 频道 ID。
            user_id: 用户 ID。
            role_id: 身份组 ID。
            channel_id: 同 `add_member_role()`。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id`、`user_id` 或 `role_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = _member_role_path(guild_id, user_id, role_id)
        await self._http.request("DELETE", path, type_=None, json=_channel_body(channel_id))

    # ---- 禁言 ----

    async def mute_all(self, guild_id: str, until: datetime | timedelta) -> None:
        """全员禁言（管理员不受影响）。管理员。

        对应官方接口 `PATCH /guilds/{guild_id}/mute`。

        Args:
            guild_id: 频道 ID。
            until: 禁言到什么时候：带时区的 `datetime`，或从现在起算的 `timedelta`。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 为空，`until` 是没有时区的 `datetime` 或不是正数的 `timedelta`。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.guilds.mute_all(guild_id, timedelta(minutes=10))
            ```
        """
        body = {"mute_end_timestamp": unix_seconds(until, "until")}
        await self._http.request("PATCH", _mute_path(guild_id), type_=None, json=body)

    async def unmute_all(self, guild_id: str) -> None:
        """解除全员禁言。管理员。

        对应官方接口 `PATCH /guilds/{guild_id}/mute`。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        await self._http.request("PATCH", _mute_path(guild_id), type_=None, json=_UNMUTE)

    async def mute_members(
        self, guild_id: str, user_ids: str | Iterable[str], until: datetime | timedelta
    ) -> tuple[str, ...]:
        """批量禁言成员（不能禁言管理员），返回设置成功的用户 ID。管理员。

        对应官方接口 `PATCH /guilds/{guild_id}/mute`（带 `user_ids`）。

        Args:
            guild_id: 频道 ID。
            user_ids: 一个或多个用户 ID。
            until: 同 `mute_all()`。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: 同 `mute_all()`。
            RuntimeError: 客户端已关闭。
        """
        body = {"mute_end_timestamp": unix_seconds(until, "until"), "user_ids": str_list(user_ids)}
        result = await self._http.request(
            "PATCH", _mute_path(guild_id), type_=MuteResult, json=body
        )
        return result.user_ids

    async def unmute_members(self, guild_id: str, user_ids: str | Iterable[str]) -> tuple[str, ...]:
        """批量解除成员的禁言，返回设置成功的用户 ID。管理员。

        对应官方接口 `PATCH /guilds/{guild_id}/mute`（带 `user_ids`）。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        body = {**_UNMUTE, "user_ids": str_list(user_ids)}
        result = await self._http.request(
            "PATCH", _mute_path(guild_id), type_=MuteResult, json=body
        )
        return result.user_ids

    async def mute_member(self, guild_id: str, user_id: str, until: datetime | timedelta) -> None:
        """禁言一个成员。管理员。

        对应官方接口 `PATCH /guilds/{guild_id}/members/{user_id}/mute`。

        Args:
            guild_id: 频道 ID。
            user_id: 用户 ID。
            until: 同 `mute_all()`。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 或 `user_id` 为空，`until` 不合法（同 `mute_all()`）。
            RuntimeError: 客户端已关闭。
        """
        body = {"mute_end_timestamp": unix_seconds(until, "until")}
        path = f"{_member_path(guild_id, user_id)}/mute"
        await self._http.request("PATCH", path, type_=None, json=body)

    async def unmute_member(self, guild_id: str, user_id: str) -> None:
        """解除一个成员的禁言。管理员。

        对应官方接口 `PATCH /guilds/{guild_id}/members/{user_id}/mute`。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 或 `user_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_member_path(guild_id, user_id)}/mute"
        await self._http.request("PATCH", path, type_=None, json=_UNMUTE)

    # ---- 接口权限与消息设置 ----

    async def list_api_permissions(self, guild_id: str) -> tuple[APIPermission, ...]:
        """列出机器人在频道里的接口权限及其授权状态。

        对应官方接口 `GET /guilds/{guild_id}/api_permission`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_guild_path(guild_id)}/api_permission"
        result = await self._http.request("GET", path, type_=APIPermissionList)
        return result.apis

    async def request_api_permission(
        self,
        guild_id: str,
        channel_id: str,
        *,
        method: str,
        path: str,
        desc: str | None = None,
    ) -> APIPermissionDemand:
        """向频道发一条接口授权链接，由频道管理员点击授权。每个频道每天最多 3 条。

        对应官方接口 `POST /guilds/{guild_id}/api_permission/demand`。

        Args:
            guild_id: 频道 ID。
            channel_id: 授权链接发到哪个子频道。
            method: 要申请的接口的请求方法，如 `GET`。
            path: 要申请的接口的路径模板，如 `/guilds/{guild_id}`，同 `APIPermission.path`。
            desc: 授权后机器人能提供的功能，显示在授权链接里。

        Raises:
            APIError: 平台拒绝，例如超过每天的条数。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 为空。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.guilds.request_api_permission(
                guild_id, channel_id, method="GET", path="/guilds/{guild_id}", desc="显示频道信息"
            )
            ```
        """
        body = _present(
            channel_id=channel_id, api_identify={"path": path, "method": method}, desc=desc
        )
        url = f"{_guild_path(guild_id)}/api_permission/demand"
        return await self._http.request("POST", url, type_=APIPermissionDemand, json=body)

    async def get_message_setting(self, guild_id: str) -> MessageSetting:
        """取机器人在频道里的消息频率设置。

        对应官方接口 `GET /guilds/{guild_id}/message/setting`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `guild_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_guild_path(guild_id)}/message/setting"
        return await self._http.request("GET", path, type_=MessageSetting)


def _list_items(response: DecodedResponse[object], key: str) -> object:
    """列表接口的表格是 `{key: [...]}`、示例是裸数组（docs/errata.md），取出其中的条目。

    `key` 的值类型不对时原样返回，由解码按字段级的宽容规则退回空列表。

    Raises:
        APIError: 响应既不是数组也不是对象。
    """
    data = response.data
    if isinstance(data, list):
        return cast(list[object], data)
    if isinstance(data, dict):
        return cast(dict[str, object], data).get(key, ())
    raise response.failure(f"响应无法识别（HTTP {response.status_code}）")


def _anchor[T](
    response: DecodedResponse[object], items: object, type_: type[T], get_id: Callable[[T], str]
) -> str | None:
    """下一页的锚点：本页最后一条的 ID；本页为空时为 `None`（结束）。

    最后一条解不出 ID 时抛 `APIError`：退回前一条会重复取，当作结束则漏掉后面的条目。
    """
    if not isinstance(items, list) or not items:
        return None
    last = cast(list[object], items)[-1]
    try:
        return get_id(decode(msgspec.json.encode(last), type_))
    except msgspec.DecodeError:
        raise response.failure("本页最后一条没有 ID，无法继续翻页") from None


def _present(**fields: object) -> dict[str, object]:
    """去掉值为 `None` 的字段：没传的可选参数不发出去。"""
    return {name: value for name, value in fields.items() if value is not None}


def _role_body(name: str | None, color: int | None, hoist: bool | None) -> dict[str, object]:
    body = _present(name=name, color=color, hoist=None if hoist is None else int(hoist))
    if not body:
        raise ValueError("name、color、hoist 至少要传一个")
    return body


def _channel_body(channel_id: str | None) -> dict[str, object] | None:
    return None if channel_id is None else {"channel": {"id": channel_id}}


def _user_id(member: GuildMember) -> str | None:
    return member.user.id if member.user else None


def _guild_path(guild_id: str) -> str:
    return f"/guilds/{path_segment(guild_id, 'guild_id')}"


def _member_path(guild_id: str, user_id: str) -> str:
    return f"{_guild_path(guild_id)}/members/{path_segment(user_id, 'user_id')}"


def _role_path(guild_id: str, role_id: str) -> str:
    return f"{_guild_path(guild_id)}/roles/{path_segment(role_id, 'role_id')}"


def _member_role_path(guild_id: str, user_id: str, role_id: str) -> str:
    return f"{_member_path(guild_id, user_id)}/roles/{path_segment(role_id, 'role_id')}"


def _mute_path(guild_id: str) -> str:
    return f"{_guild_path(guild_id)}/mute"
