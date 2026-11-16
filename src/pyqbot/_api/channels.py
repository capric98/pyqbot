"""子频道接口：子频道管理与权限、消息、表情表态、精华消息、日程、论坛与音频。分组边界见 `docs/design.md`。"""

import os
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

from .._http import HTTP, path_segment
from .._models.audio import AudioStatus
from .._models.event import ChannelReplyTarget
from .._models.forum import (
    ForumPublishTask,
    ForumThread,
    ForumThreadFormat,
    ForumThreadList,
    ThreadResponse,
)
from .._models.guild import Channel, ChannelPermission, GuildUser, PrivateType, SpeakPermission
from .._models.guild_content import PinnedMessages, RemindType, Schedule
from .._models.guild_manage import OnlineNums, PermissionsResponse
from .._models.guild_message import Emoji, GuildMessage, ReactionUserPage
from .._models.send import Ark, Embed, Keyboard, Markdown
from .guild_message import (
    guild_message_request,
    message_id_of,
    message_path,
    recall_params,
    send_guild_message,
)
from .paging import Page, paginate
from .params import unix_millis

_ALL = "all"  # 精华消息接口里表示「全部」的 message_id


def _channel_path(channel_id: str) -> str:
    return f"/channels/{path_segment(channel_id, 'channel_id')}"


def _member_path(channel_id: str, user_id: str) -> str:
    return f"{_channel_path(channel_id)}/members/{path_segment(user_id, 'user_id')}/permissions"


def _role_path(channel_id: str, role_id: str) -> str:
    return f"{_channel_path(channel_id)}/roles/{path_segment(role_id, 'role_id')}/permissions"


def _reaction_path(channel_id: str, message: str | GuildMessage, emoji: Emoji) -> str:
    base = message_path(f"{_channel_path(channel_id)}/messages", message)
    return f"{base}/reactions/{int(emoji.type)}/{path_segment(emoji.id, 'emoji.id')}"


def _schedule_body(
    name: str,
    start: datetime | timedelta,
    end: datetime | timedelta,
    description: str | None,
    jump_channel_id: str | None,
    remind_type: RemindType,
) -> dict[str, object]:
    # 时间字段是毫秒时间戳的字符串（schedule/model.md）。
    schedule: dict[str, object] = {
        "name": name,
        "start_timestamp": unix_millis(start, "start"),
        "end_timestamp": unix_millis(end, "end"),
        "remind_type": remind_type,
    }
    if description is not None:
        schedule["description"] = description
    if jump_channel_id is not None:
        schedule["jump_channel_id"] = jump_channel_id
    return {"schedule": schedule}


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

    # ---- 消息 ----

    async def send_message(
        self,
        channel_id: str,
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
        reply_to: ChannelReplyTarget | None = None,
    ) -> GuildMessage:
        """向子频道发送一条消息。

        不传 `reply_to` 是主动消息，受每个子频道每天 20 条等限制，还可能要人工审核；
        传入收到的子频道消息或可回复的事件（表态、论坛、频道成员、互动）则是被动回复，有效期 5 分钟，
        `msg_id` / `event_id` 由 SDK 填写。机器人须在线（已连接网关）。
        本地图片（`image_path`、`image_data`）以 `multipart/form-data` 上传。

        对应官方接口 `POST /channels/{channel_id}/messages`。

        Args:
            channel_id: 子频道 ID。
            content: 文本内容，支持 `<@用户 ID>`、`<#子频道 ID>`、`<emoji:表情 ID>` 等内嵌格式。
            markdown: Markdown 正文，或 `Markdown` 对象；频道需要内邀开通。
            keyboard: 消息下方的按钮，只能随 `markdown` 发送。
            embed: Embed 消息。
            ark: Ark 消息，需要申请权限。
            image: 图片的公网地址，由平台转存。
            image_path: 本地图片的路径。
            image_data: 图片的内容。
            quote: 要引用的消息：消息 ID 或消息对象。
            reply_to: 被动回复的对象（须是 `Bot` 分发来的，事件要带事件 ID）。

        Raises:
            AuditPendingError: 平台已受理，但要等人工审核（`err_code` 304023、304024）；
                审核结果由 `MESSAGE_AUDIT_PASS` / `MESSAGE_AUDIT_REJECT` 事件推送。
            APIError: 平台拒绝发送，例如被动回复已过期（`err_code` 304027）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空；没有内容；`image`、`image_path`、`image_data` 传了不止一个；
                `keyboard` 没有随 `markdown`；`quote` 是空的消息 ID；`reply_to` 是没有事件 ID 的事件。
            OSError: 读取 `image_path` 失败。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.channels.send_message(channel_id, "你好")
            await client.channels.send_message(channel_id, "看图", image_path="cat.png")
            ```
        """
        path = f"{_channel_path(channel_id)}/messages"
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
        return await send_guild_message(self._http, path, body, file_image, reply_to=reply_to)

    async def recall_message(
        self, channel_id: str, message: str | GuildMessage, *, hidetip: bool = False
    ) -> None:
        """撤回子频道里的一条消息。仅私域机器人可用；撤回别人的消息要是管理员或频道主。

        对应官方接口 `DELETE /channels/{channel_id}/messages/{message_id}`。

        Args:
            channel_id: 子频道 ID。
            message: 要撤回的消息或它的 ID。
            hidetip: 隐藏「撤回了一条消息」的提示小灰条。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 或消息 ID 为空。
            RuntimeError: 客户端已关闭。
        """
        path = message_path(f"{_channel_path(channel_id)}/messages", message)
        await self._http.request("DELETE", path, type_=None, params=recall_params(hidetip))

    # ---- 表情表态 ----

    async def add_reaction(
        self, channel_id: str, message: str | GuildMessage, emoji: Emoji
    ) -> None:
        """机器人对一条消息发表表情表态。

        对应官方接口 `PUT /channels/{channel_id}/messages/{message_id}/reactions/{type}/{id}`。

        Args:
            channel_id: 子频道 ID。
            message: 消息或它的 ID。
            emoji: 表情，如 `Emoji(id="4", type=EmojiType.SYSTEM)`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id`、消息 ID 或表情 ID 为空。
            RuntimeError: 客户端已关闭。
        """
        path = _reaction_path(channel_id, message, emoji)
        await self._http.request("PUT", path, type_=None)

    async def remove_reaction(
        self, channel_id: str, message: str | GuildMessage, emoji: Emoji
    ) -> None:
        """删除机器人自己对一条消息的表情表态；参数同 `add_reaction()`。

        对应官方接口 `DELETE /channels/{channel_id}/messages/{message_id}/reactions/{type}/{id}`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id`、消息 ID 或表情 ID 为空。
            RuntimeError: 客户端已关闭。
        """
        path = _reaction_path(channel_id, message, emoji)
        await self._http.request("DELETE", path, type_=None)

    def iter_reaction_users(
        self,
        channel_id: str,
        message: str | GuildMessage,
        emoji: Emoji,
        *,
        limit: int = 20,
    ) -> AsyncIterator[GuildUser]:
        """列出对一条消息发表了某个表情表态的用户，只有 `id`、`username`、`avatar`。

        对应官方接口 `GET /channels/{channel_id}/messages/{message_id}/reactions/{type}/{id}`。

        Args:
            channel_id: 子频道 ID。
            message: 消息或它的 ID。
            emoji: 表情。
            limit: 每页的数量，最多 50（由平台检查）。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id`、消息 ID 或表情 ID 为空（开始迭代时抛出）。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            async for user in client.channels.iter_reaction_users(channel_id, message_id, emoji):
                print(user.id, user.username)
            ```
        """

        async def fetch(cookie: str | None) -> Page[GuildUser, str]:
            path = _reaction_path(channel_id, message, emoji)
            # limit 只在第一页有效，之后靠 cookie 续上（emoji.md）。
            params: dict[str, str | int] = (
                {"limit": limit} if cookie is None else {"cookie": cookie}
            )
            page = await self._http.request("GET", path, type_=ReactionUserPage, params=params)
            return Page(page.users, None if page.is_end else page.cookie)

        return paginate(fetch)

    # ---- 精华消息 ----

    async def get_pins(self, channel_id: str) -> PinnedMessages:
        """取子频道的精华消息。

        对应官方接口 `GET /channels/{channel_id}/pins`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_channel_path(channel_id)}/pins"
        return await self._http.request("GET", path, type_=PinnedMessages)

    async def add_pin(self, channel_id: str, message: str | GuildMessage) -> PinnedMessages:
        """把一条消息设为精华消息，返回设置后子频道的全部精华消息。每个子频道最多 20 条。

        对应官方接口 `PUT /channels/{channel_id}/pins/{message_id}`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 或消息 ID 为空。
            RuntimeError: 客户端已关闭。
        """
        path = message_path(f"{_channel_path(channel_id)}/pins", message)
        return await self._http.request("PUT", path, type_=PinnedMessages)

    async def remove_pin(self, channel_id: str, message: str | GuildMessage) -> None:
        """取消一条精华消息；要全部取消用 `remove_all_pins()`。

        对应官方接口 `DELETE /channels/{channel_id}/pins/{message_id}`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 或消息 ID 为空，或消息 ID 是 `"all"`。
            RuntimeError: 客户端已关闭。
        """
        if message_id_of(message) == _ALL:
            raise ValueError('消息 ID 不能是 "all"：要取消全部精华消息请用 remove_all_pins()')
        path = message_path(f"{_channel_path(channel_id)}/pins", message)
        await self._http.request("DELETE", path, type_=None)

    async def remove_all_pins(self, channel_id: str) -> None:
        """取消子频道的全部精华消息。

        对应官方接口 `DELETE /channels/{channel_id}/pins/all`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        await self._http.request("DELETE", f"{_channel_path(channel_id)}/pins/{_ALL}", type_=None)

    # ---- 日程 ----

    async def list_schedules(
        self, channel_id: str, *, since: datetime | None = None
    ) -> tuple[Schedule, ...]:
        """列出日程子频道里的日程：默认是当天的，传 `since` 则是结束时间在它之后的。

        对应官方接口 `GET /channels/{channel_id}/schedules`。

        Args:
            channel_id: 日程子频道的 ID。
            since: 带时区的时间。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空，或 `since` 没有时区。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_channel_path(channel_id)}/schedules"
        # 文档把 since 写成 GET 的 JSON 请求体，这里放进查询参数（docs/errata.md）。
        params = None if since is None else {"since": unix_millis(since, "since")}
        return await self._http.request("GET", path, type_=tuple[Schedule, ...], params=params)

    async def get_schedule(self, channel_id: str, schedule_id: str) -> Schedule:
        """取一个日程的详情。

        对应官方接口 `GET /channels/{channel_id}/schedules/{schedule_id}`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 或 `schedule_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_channel_path(channel_id)}/schedules/{path_segment(schedule_id, 'schedule_id')}"
        return await self._http.request("GET", path, type_=Schedule)

    async def create_schedule(
        self,
        channel_id: str,
        name: str,
        start: datetime | timedelta,
        end: datetime | timedelta,
        *,
        description: str | None = None,
        jump_channel_id: str | None = None,
        remind_type: RemindType = RemindType.NONE,
    ) -> Schedule:
        """在日程子频道里创建一个日程。机器人须是管理员；每个管理员每天 10 次，每个频道每天 100 次。

        对应官方接口 `POST /channels/{channel_id}/schedules`。

        Args:
            channel_id: 日程子频道的 ID。
            name: 名称。
            start: 开始时间：带时区的时刻，或从现在起算的正时长；不能早于现在。
            end: 结束时间，形式同 `start`；不能早于开始时间，持续不超过 7 天（由平台检查）。
            description: 描述。
            jump_channel_id: 日程开始时跳转到的子频道 ID。
            remind_type: 提醒方式。

        Raises:
            APIError: 平台拒绝，例如时间不合法（`err_code` 302014～302016）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空，时间没有时区，或时长不是正数。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_channel_path(channel_id)}/schedules"
        body = _schedule_body(name, start, end, description, jump_channel_id, remind_type)
        return await self._http.request("POST", path, type_=Schedule, json=body)

    async def update_schedule(
        self,
        channel_id: str,
        schedule: str | Schedule,
        name: str,
        start: datetime | timedelta,
        end: datetime | timedelta,
        *,
        description: str | None = None,
        jump_channel_id: str | None = None,
        remind_type: RemindType = RemindType.NONE,
    ) -> Schedule:
        """修改一个日程，参数同 `create_schedule()`。机器人须是管理员。

        文档没有说明没传的字段是保留还是清空，所以名称与时间必填，其余字段也请按需要的结果给全。

        对应官方接口 `PATCH /channels/{channel_id}/schedules/{schedule_id}`。

        Args:
            channel_id: 日程子频道的 ID。
            schedule: 日程或它的 ID。
            name: 名称。
            start: 开始时间：带时区的时刻，或从现在起算的正时长。
            end: 结束时间，形式同 `start`。
            description: 描述。
            jump_channel_id: 日程开始时跳转到的子频道 ID。
            remind_type: 提醒方式。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 或日程 ID 为空，时间没有时区，或时长不是正数。
            RuntimeError: 客户端已关闭。
        """
        schedule_id = schedule if isinstance(schedule, str) else schedule.id
        path = f"{_channel_path(channel_id)}/schedules/{path_segment(schedule_id, 'schedule_id')}"
        body = _schedule_body(name, start, end, description, jump_channel_id, remind_type)
        return await self._http.request("PATCH", path, type_=Schedule, json=body)

    async def delete_schedule(self, channel_id: str, schedule: str | Schedule) -> None:
        """删除一个日程。机器人须是管理员。

        对应官方接口 `DELETE /channels/{channel_id}/schedules/{schedule_id}`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 或日程 ID 为空。
            RuntimeError: 客户端已关闭。
        """
        schedule_id = schedule if isinstance(schedule, str) else schedule.id
        path = f"{_channel_path(channel_id)}/schedules/{path_segment(schedule_id, 'schedule_id')}"
        await self._http.request("DELETE", path, type_=None)

    # ---- 论坛 ----

    async def list_threads(self, channel_id: str) -> ForumThreadList:
        """列出论坛子频道里的主帖。仅私域机器人可用。

        文档没有翻页参数，`finished` 为 `False` 时也取不到后面的帖子。

        对应官方接口 `GET /channels/{channel_id}/threads`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_channel_path(channel_id)}/threads"
        return await self._http.request("GET", path, type_=ForumThreadList)

    async def get_thread(self, channel_id: str, thread_id: str) -> ForumThread:
        """取一个主帖的详情。仅私域机器人可用。

        对应官方接口 `GET /channels/{channel_id}/threads/{thread_id}`。

        Raises:
            APIError: 平台拒绝，例如帖子不存在（`err_code` 503012）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 或 `thread_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_channel_path(channel_id)}/threads/{path_segment(thread_id, 'thread_id')}"
        response = await self._http.request("GET", path, type_=ThreadResponse)
        return response.thread

    async def publish_thread(
        self,
        channel_id: str,
        title: str,
        content: str,
        *,
        format: ForumThreadFormat = ForumThreadFormat.TEXT,
    ) -> ForumPublishTask:
        """在论坛子频道发表主帖。仅私域机器人可用。

        发帖要审核：这里只返回任务，结果由 `FORUM_PUBLISH_AUDIT_RESULT` 事件推送。

        对应官方接口 `PUT /channels/{channel_id}/threads`。

        Args:
            channel_id: 论坛子频道的 ID。
            title: 标题。
            content: 内容，格式由 `format` 指定。
            format: 内容的格式；`JSON` 时 `content` 是 `ForumRichText` 结构的 JSON 字符串。

        Raises:
            APIError: 平台拒绝，例如超出发帖频次（`err_code` 503004）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_channel_path(channel_id)}/threads"
        body = {"title": title, "content": content, "format": format}
        return await self._http.request("PUT", path, type_=ForumPublishTask, json=body)

    async def delete_thread(self, channel_id: str, thread: str | ForumThread) -> None:
        """删除一个主帖。仅私域机器人可用。

        对应官方接口 `DELETE /channels/{channel_id}/threads/{thread_id}`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 或 `thread_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        thread_id = thread if isinstance(thread, str) else thread.thread_info.thread_id
        path = f"{_channel_path(channel_id)}/threads/{path_segment(thread_id, 'thread_id')}"
        await self._http.request("DELETE", path, type_=None)

    # ---- 音频 ----

    async def control_audio(
        self,
        channel_id: str,
        status: AudioStatus,
        *,
        audio_url: str | None = None,
        text: str | None = None,
    ) -> None:
        """控制音频子频道的播放：开始（要给 `audio_url`）、暂停、继续、停止。只有音频机器人可用。

        对应官方接口 `POST /channels/{channel_id}/audio`。

        Args:
            channel_id: 音频子频道的 ID。
            status: 播放操作。
            audio_url: 音频地址，只在 `START` 时传。
            text: 状态文本，如歌名，只在 `START` 时传。

        Raises:
            APIError: 平台拒绝，例如机器人没有音频权限。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空；`START` 没有 `audio_url`，或其它操作传了 `audio_url`、`text`。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.channels.control_audio(
                channel_id, pyqbot.AudioStatus.START, audio_url="https://...", text="简单爱"
            )
            ```
        """
        if status == AudioStatus.START:
            if audio_url is None:
                raise ValueError("开始播放（AudioStatus.START）要给出 audio_url")
        elif audio_url is not None or text is not None:
            raise ValueError("audio_url、text 只在开始播放（AudioStatus.START）时传")
        body: dict[str, object] = {"status": status}
        if audio_url is not None:
            body["audio_url"] = audio_url
        if text is not None:
            body["text"] = text
        await self._http.request(
            "POST", f"{_channel_path(channel_id)}/audio", type_=None, json=body
        )

    async def join_mic(self, channel_id: str) -> None:
        """机器人在语音子频道上麦。只有音频机器人可用。

        对应官方接口 `PUT /channels/{channel_id}/mic`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        await self._http.request("PUT", f"{_channel_path(channel_id)}/mic", type_=None)

    async def leave_mic(self, channel_id: str) -> None:
        """机器人在语音子频道下麦。只有音频机器人可用。

        对应官方接口 `DELETE /channels/{channel_id}/mic`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `channel_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        await self._http.request("DELETE", f"{_channel_path(channel_id)}/mic", type_=None)
