"""子频道接口。分组边界见 `docs/design.md`。"""

from .._http import HTTP, path_segment
from .._models.guild import Channel, PrivateType, SpeakPermission
from .._models.guild_manage import ChannelPermission, OnlineNums, PermissionsResponse


class Channels:
    """子频道相关的接口，经 `client.channels` 使用；频道级的操作（列出、创建子频道等）在 `client.guilds`。

    标明「私域」的接口只有私域机器人可用；标明「管理员」的要求机器人在该频道是管理员。
    """

    def __init__(self, http: HTTP) -> None:
        self._http = http

    # ---- 子频道管理 ----

    async def get(self, channel_id: str) -> Channel:
        """取子频道的详情。

        对应官方接口 `GET /channels/{channel_id}`。

        Raises:
            APIError: 平台拒绝，例如子频道不存在。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        return await self._http.request("GET", _channel_path(channel_id), type_=Channel)

    async def update(
        self,
        channel_id: str,
        *,
        name: str | None = None,
        position: int | None = None,
        parent_id: str | None = None,
        private_type: PrivateType | None = None,
        speak_permission: SpeakPermission | None = None,
    ) -> Channel:
        """修改子频道，只改传了的字段；返回修改后的子频道。私域；管理员。

        成功后平台推送 `CHANNEL_UPDATE` 事件。

        对应官方接口 `PATCH /channels/{channel_id}`。

        Args:
            channel_id: 子频道 ID。
            name: 名称。
            position: 排序值，规则同 `client.guilds.create_channel()`。
            parent_id: 所属分组的 ID。
            private_type: 对谁可见；指定成员用 `update_member_permissions()`。
            speak_permission: 谁能发言；同上。

        Raises:
            APIError: 平台拒绝，例如不是私域机器人或机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空，或什么都没传。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.channels.update(channel_id, name="公告区（已改名）")
            ```
        """
        fields = {
            "name": name,
            "position": position,
            "parent_id": parent_id,
            "private_type": private_type,
            "speak_permission": speak_permission,
        }
        body = {key: value for key, value in fields.items() if value is not None}
        if not body:
            raise ValueError("至少要传一个要修改的字段")
        return await self._http.request(
            "PATCH", _channel_path(channel_id), type_=Channel, json=body
        )

    async def delete(self, channel_id: str) -> None:
        """删除子频道，删除后无法恢复。私域；管理员。

        成功后平台推送 `CHANNEL_DELETE` 事件。

        对应官方接口 `DELETE /channels/{channel_id}`。

        Raises:
            APIError: 平台拒绝，例如不是私域机器人或机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        await self._http.request("DELETE", _channel_path(channel_id), type_=None)

    async def get_online_nums(self, channel_id: str) -> int:
        """取音视频或直播子频道的在线人数。

        对应官方接口 `GET /channels/{channel_id}/online_nums`。

        Raises:
            APIError: 平台拒绝，例如不是音视频或直播子频道。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_channel_path(channel_id)}/online_nums"
        result = await self._http.request("GET", path, type_=OnlineNums)
        return result.online_nums

    # ---- 子频道权限 ----

    async def get_member_permissions(self, channel_id: str, user_id: str) -> ChannelPermission:
        """取用户在子频道的个人权限（不含身份组带来的权限）。管理员。

        对应官方接口 `GET /channels/{channel_id}/members/{user_id}/permissions`。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 或 `user_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        return await self._get_permissions(_member_path(channel_id, user_id))

    async def update_member_permissions(
        self,
        channel_id: str,
        user_id: str,
        *,
        add: ChannelPermission | None = None,
        remove: ChannelPermission | None = None,
    ) -> None:
        """给用户增减子频道的个人权限。管理员。

        同一位在 `add` 与 `remove` 里都有时按删除处理；`ChannelPermission.MANAGE` 不能通过接口修改。

        对应官方接口 `PUT /channels/{channel_id}/members/{user_id}/permissions`。

        Args:
            channel_id: 子频道 ID。
            user_id: 用户 ID。
            add: 要授予的权限。
            remove: 要收回的权限。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 或 `user_id` 为空。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.channels.update_member_permissions(
                channel_id, user_id, add=pyqbot.ChannelPermission.SPEAK
            )
            ```
        """
        await self._put_permissions(_member_path(channel_id, user_id), add, remove)

    async def get_role_permissions(self, channel_id: str, role_id: str) -> ChannelPermission:
        """取身份组在子频道的权限。管理员。

        对应官方接口 `GET /channels/{channel_id}/roles/{role_id}/permissions`。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 或 `role_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        return await self._get_permissions(_role_path(channel_id, role_id))

    async def update_role_permissions(
        self,
        channel_id: str,
        role_id: str,
        *,
        add: ChannelPermission | None = None,
        remove: ChannelPermission | None = None,
    ) -> None:
        """给身份组增减子频道的权限，规则同 `update_member_permissions()`。管理员。

        对应官方接口 `PUT /channels/{channel_id}/roles/{role_id}/permissions`。

        Args:
            channel_id: 子频道 ID。
            role_id: 身份组 ID。
            add: 要授予的权限。
            remove: 要收回的权限。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 或 `role_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        await self._put_permissions(_role_path(channel_id, role_id), add, remove)

    async def _get_permissions(self, path: str) -> ChannelPermission:
        response = await self._http.request_decoded("GET", path, type_=PermissionsResponse)
        try:
            return ChannelPermission(int(response.data.permissions))
        except ValueError:
            # 超过 int() 的位数上限（默认 4300 位，调用方还可以调低）时 int() 抛 ValueError。
            raise response.failure(f"响应无法识别（HTTP {response.status_code}）") from None

    async def _put_permissions(
        self, path: str, add: ChannelPermission | None, remove: ChannelPermission | None
    ) -> None:
        # 权限位在接口里是十进制数字的字符串，"0" 表示不增加或不删除。
        body = {"add": str(int(add or 0)), "remove": str(int(remove or 0))}
        await self._http.request("PUT", path, type_=None, json=body)


def _channel_path(channel_id: str) -> str:
    return f"/channels/{path_segment(channel_id, 'channel_id')}"


def _member_path(channel_id: str, user_id: str) -> str:
    return f"{_channel_path(channel_id)}/members/{path_segment(user_id, 'user_id')}/permissions"


def _role_path(channel_id: str, role_id: str) -> str:
    return f"{_channel_path(channel_id)}/roles/{path_segment(role_id, 'role_id')}/permissions"
