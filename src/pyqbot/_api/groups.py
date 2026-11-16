"""群聊接口。"""

import os
from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timedelta

from .._http import HTTP, path_segment
from .._models.event import GroupReplyTarget
from .._models.group import (
    AddDel,
    BlacklistedUser,
    BlacklistPage,
    BlacklistResult,
    GroupBotState,
    GroupInfo,
    GroupMember,
    GroupMuteSettings,
    JoinRequestOp,
    JoinRequestPage,
    MemberPage,
    MuteOp,
    RemoveMembersResult,
)
from .._models.message import GroupMessage, SentMessage
from .._models.notice import GroupJoinRequestInfo
from .._models.send import Card, Keyboard, Markdown, Media
from .._models.upload import FileType
from .message import message_body, message_path, send_message
from .paging import Page, paginate
from .params import rfc3339, str_list
from .upload import upload_media

# 文档给出的单页上限；取最大值，少发请求。
_BLACKLIST_PAGE_LIMIT = 100
_JOIN_REQUEST_PAGE_LIMIT = 50


class Groups:
    """群聊相关的接口，经 `client.groups` 使用。"""

    def __init__(self, http: HTTP) -> None:
        self._http = http

    async def send_message(
        self,
        group_openid: str,
        content: str | None = None,
        *,
        markdown: str | Markdown | None = None,
        keyboard: Keyboard | None = None,
        media: Media | None = None,
        card: Card | None = None,
        quote: str | SentMessage | GroupMessage | None = None,
        reply_to: GroupReplyTarget | None = None,
    ) -> SentMessage:
        """向群发送一条消息，`msg_type` 由 SDK 按传了哪些内容推断。

        不传 `reply_to` 是主动消息，受每日条数等限制；
        传入收到的群消息或可回复的事件则是被动回复，`msg_id` / `event_id` 与 `msg_seq` 由 SDK 填写。
        群聊没有互动召回消息。

        对应官方接口 `POST /v2/groups/{group_openid}/messages`。

        Args:
            group_openid: 群的 openid。
            content: 文本内容；各内容参数的组合规则同 `client.users.send_message()`。
            markdown: Markdown 正文或 `Markdown` 对象。
            keyboard: 消息下方的按钮。
            media: 在群聊上传的富媒体（与单聊上传的不互通）。
            card: 图文卡片。
            quote: 要引用的消息。
            reply_to: 被动回复的对象：收到的群消息，或可以回复的事件（须是 `Bot` 分发来的，带事件 ID）。

        Raises:
            APIError: 平台拒绝发送，例如被动回复已过期（`err_code` 见官方接口文档）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 为空，内容参数的组合不合法（同单聊），`quote` 没有引用索引，
                或 `reply_to` 是没有事件 ID 的事件。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.groups.send_message(group_openid, "大家好")
            ```
        """
        path = f"/v2/groups/{path_segment(group_openid, 'group_openid')}/messages"
        body = message_body(
            content, markdown=markdown, keyboard=keyboard, media=media, card=card, quote=quote
        )
        return await send_message(self._http, path, body, reply_to=reply_to)

    async def recall_message(
        self, group_openid: str, message: str | SentMessage | GroupMessage
    ) -> None:
        """撤回群里的一条消息。发出超过 2 分钟的消息不能撤回。

        机器人只能撤回自己的消息；是群管理员时还能撤回普通成员的消息（传入收到的群消息）。

        对应官方接口 `DELETE /v2/groups/{group_openid}/messages/{message_id}`。

        Args:
            group_openid: 群的 openid。
            message: 要撤回的消息：`send_message()` 的返回值、收到的群消息，或消息 ID。

        Raises:
            APIError: 平台拒绝，例如已超过撤回时限（`err_code` 为 40064004）或没有权限。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 或消息 ID 为空。
            RuntimeError: 客户端已关闭。
        """
        base = f"/v2/groups/{path_segment(group_openid, 'group_openid')}/messages"
        await self._http.request("DELETE", message_path(base, message), type_=None)

    async def upload(
        self,
        group_openid: str,
        *,
        path: str | os.PathLike[str] | None = None,
        url: str | None = None,
        data: bytes | None = None,
        file_name: str | None = None,
        file_type: FileType | None = None,
        send: bool = False,
    ) -> Media:
        """上传图片、视频、语音或文件，返回的 `Media` 传给 `send_message(media=...)` 发送。

        群聊上传的文件只能发到群聊。参数与上传方式的选择同 `client.users.upload()`。

        对应官方接口 `POST /v2/groups/{group_openid}/files`；分片上传另用
        `POST /v2/groups/{group_id}/upload_prepare` 与 `POST /v2/groups/{group_id}/upload_part_finish`。

        Args:
            group_openid: 群的 openid。
            path: 本地文件的路径。
            url: 公网可访问的 http(s) 地址。
            data: 文件内容，此时必须给出 `file_name`。
            file_name: 上报给平台的文件名，默认取 `path` 的文件名；不能与 `url` 同时传。
            file_type: 文件类型，不传时按扩展名推断，规则同单聊。
            send: 上传后直接作为主动消息发到群里，返回的 `Media.id` 是那条消息的 ID。
                占用主动消息额度。

        Raises:
            APIError: 平台拒绝，例如机器人被禁言（`err_code` 850018）、格式不支持（850019）。
            NetworkError: 没有拿到平台或对象存储的响应。
            ValueError: 同 `client.users.upload()`。
            OSError: 读取文件失败。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            media = await client.groups.upload(
                group_openid, url="https://example.com/a.mp4", file_type=pyqbot.FileType.VIDEO
            )
            ```
        """
        base = f"/v2/groups/{path_segment(group_openid, 'group_openid')}"
        return await upload_media(
            self._http,
            base,
            path=path,
            url=url,
            data=data,
            file_name=file_name,
            file_type=file_type,
            send=send,
        )

    # ---- 群管理 ----

    async def get(self, group_openid: str) -> GroupInfo:
        """获取群的基本信息：名称、简介、分类、标签、人数。

        仅白名单机器人可用，否则平台以 `err_code` 11253 拒绝。

        对应官方接口 `GET /v2/groups/{group_openid}/info`。

        Raises:
            APIError: 平台拒绝，例如没有接口权限（11253）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 为空。
            RuntimeError: 客户端已关闭。
        """
        return await self._http.request("GET", f"{_group_path(group_openid)}/info", type_=GroupInfo)

    async def get_bot_state(self, group_openid: str) -> GroupBotState:
        """获取机器人在群里的状态：群内角色、入群时间、接收哪些消息等。

        仅白名单机器人可用，否则平台以 `err_code` 11253 拒绝。

        对应官方接口 `GET /v2/groups/{group_openid}/bot_state`。

        Raises:
            APIError: 平台拒绝，例如没有接口权限（11253）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_group_path(group_openid)}/bot_state"
        return await self._http.request("GET", path, type_=GroupBotState)

    def iter_members(self, group_openid: str) -> AsyncIterator[GroupMember]:
        """依次列出群成员。

        内邀能力，且仅白名单机器人可用，否则平台以 `err_code` 11253 拒绝。

        对应官方接口 `GET /v2/groups/{group_openid}/members`。

        Raises:
            APIError: 平台拒绝，例如没有接口权限（11253）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 为空。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            async for member in client.groups.iter_members(group_openid):
                print(member.member_openid, member.username, member.member_role)
            ```
        """
        path = f"{_group_path(group_openid)}/members"

        async def fetch(cursor: str | None) -> Page[GroupMember, str]:
            params = {"cursor": cursor} if cursor else None
            page = await self._http.request("GET", path, type_=MemberPage, params=params)
            return Page(page.members, page.next_cursor)

        return paginate(fetch)

    async def get_member(self, group_openid: str, member_openid: str) -> GroupMember:
        """获取一个群成员的信息。

        内邀能力，且仅白名单机器人可用，否则平台以 `err_code` 11253 拒绝。

        对应官方接口 `GET /v2/groups/{group_openid}/members/{member_openid}`。

        Raises:
            APIError: 平台拒绝，例如没有接口权限（11253）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 或 `member_openid` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_group_path(group_openid)}/members/{path_segment(member_openid, 'member_openid')}"
        return await self._http.request("GET", path, type_=GroupMember)

    async def remove_members(
        self,
        group_openid: str,
        member_openids: str | Iterable[str],
        *,
        add_to_blacklist: bool = False,
    ) -> None:
        """把成员移出群，可以同时拉进群黑名单。

        内邀能力，且仅白名单机器人可用，否则平台以 `err_code` 11253 拒绝。

        对应官方接口 `POST /v2/groups/{group_openid}/batch_remove_members`。

        Args:
            group_openid: 群的 openid。
            member_openids: 一个或多个成员的 `member_openid`，单次最多 20 个（超出由平台拒绝）。
            add_to_blacklist: 同时加入群黑名单。

        Raises:
            PartialFailureError: 成员已移出，但有的没能加入黑名单（`failed_ids`）。
            APIError: 平台拒绝，例如没有接口权限（11253），或 `remove_members_result` 不是 `success`。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 为空。
            RuntimeError: 客户端已关闭。
        """
        response = await self._http.request_decoded(
            "POST",
            f"{_group_path(group_openid)}/batch_remove_members",
            type_=RemoveMembersResult,
            json={
                "member_openids": str_list(member_openids),
                "add_to_member_blacklist": add_to_blacklist,
            },
        )
        result = response.data
        # 文档只说成功时是 success；不是它就不能当作已移出（docs/errata.md）。
        if result.removal_failed:
            raise response.failure(f"remove_members_result 为 {result.remove_members_result!r}")
        if failed := result.blacklist_failed:
            reason = f"成员已移出，但 {len(failed)} 个未能加入黑名单：{'、'.join(failed)}"
            raise response.partial_failure(reason, failed)

    def iter_blacklist(self, group_openid: str) -> AsyncIterator[BlacklistedUser]:
        """依次列出群黑名单里的用户。

        内邀能力，且仅白名单机器人可用，否则平台以 `err_code` 11253 拒绝。

        对应官方接口 `GET /v2/groups/{group_openid}/member_blacklist`。

        Raises:
            APIError: 平台拒绝，例如没有接口权限（11253）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_group_path(group_openid)}/member_blacklist"

        async def fetch(cursor: str | None) -> Page[BlacklistedUser, str]:
            params = {"limit": _BLACKLIST_PAGE_LIMIT} | ({"cursor": cursor} if cursor else {})
            page = await self._http.request("GET", path, type_=BlacklistPage, params=params)
            return Page(page.users, page.next_cursor)

        return paginate(fetch)

    async def add_to_blacklist(
        self, group_openid: str, member_openids: str | Iterable[str]
    ) -> None:
        """把用户加入群黑名单。只对已不在群里的用户有效，在群里的先用 `remove_members()`。

        内邀能力，且仅白名单机器人可用，否则平台以 `err_code` 11253 拒绝。

        对应官方接口 `POST /v2/groups/{group_openid}/member_blacklist`（`op` 为 `add`）。

        Args:
            group_openid: 群的 openid。
            member_openids: 一个或多个用户的 `member_openid`，单次最多 20 个（超出由平台拒绝）。

        Raises:
            PartialFailureError: 有的用户没能加入（`failed_ids`），例如他还在群里；其余已加入。
            APIError: 平台拒绝，例如没有接口权限（11253）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 为空。
            RuntimeError: 客户端已关闭。
        """
        await self._edit_blacklist(group_openid, AddDel.ADD, member_openids)

    async def remove_from_blacklist(
        self, group_openid: str, member_openids: str | Iterable[str]
    ) -> None:
        """把用户移出群黑名单。

        内邀能力，且仅白名单机器人可用，否则平台以 `err_code` 11253 拒绝。

        对应官方接口 `POST /v2/groups/{group_openid}/member_blacklist`（`op` 为 `del`）。

        Args:
            group_openid: 群的 openid。
            member_openids: 一个或多个用户的 `member_openid`，单次最多 20 个（超出由平台拒绝）。

        Raises:
            PartialFailureError: 有的用户没能移出（`failed_ids`），其余已移出。
            APIError: 平台拒绝，例如没有接口权限（11253）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 为空。
            RuntimeError: 客户端已关闭。
        """
        await self._edit_blacklist(group_openid, AddDel.DEL, member_openids)

    async def _edit_blacklist(
        self, group_openid: str, op: AddDel, member_openids: str | Iterable[str]
    ) -> None:
        response = await self._http.request_decoded(
            "POST",
            f"{_group_path(group_openid)}/member_blacklist",
            type_=BlacklistResult,
            json={"op": op, "member_openids": str_list(member_openids)},
        )
        if failed := response.data.failed:
            step = "加入" if op == AddDel.ADD else "移出"
            reason = f"{len(failed)} 个未能{step}黑名单：{'、'.join(failed)}"
            raise response.partial_failure(reason, failed)

    async def get_mute_settings(self, group_openid: str) -> GroupMuteSettings:
        """查询群的禁言状态：全员禁言的设置，以及正在禁言中的成员。

        机器人须是群管理员。全员禁言只能查询，没有设置它的接口。

        对应官方接口 `GET /v2/groups/{group_openid}/restrict_chat_setting`。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_group_path(group_openid)}/restrict_chat_setting"
        return await self._http.request("GET", path, type_=GroupMuteSettings)

    async def mute_members(
        self, group_openid: str, member_openids: str | Iterable[str], until: datetime | timedelta
    ) -> None:
        """禁言群成员，最长 30 天（超出由平台拒绝）。已在禁言中的成员要改到期时间用 `update_member_mutes()`。

        机器人须是群管理员；只能禁言普通成员，不能禁言群主、管理员和机器人。
        对已在禁言中的成员再调用 `mute_members()`（即再发一次 `add`）是否等同于 `update_member_mutes()`，尚待实测。

        对应官方接口 `POST /v2/groups/{group_openid}/restrict_chat_setting`（`op` 为 `add`）。

        Args:
            group_openid: 群的 openid。
            member_openids: 一个或多个成员的 `member_openid`，单次最多 20 个（超出由平台拒绝）。
            until: 禁言到什么时候：带时区的 `datetime`，或从现在起算的 `timedelta`。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员，或对方是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 为空，`until` 是没有时区的 `datetime` 或不是正数的 `timedelta`。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.groups.mute_members(group_openid, member_openid, timedelta(minutes=10))
            ```
        """
        expire_at = rfc3339(until, "until")
        await self._set_mute(group_openid, MuteOp.ADD, member_openids, expire_at)

    async def update_member_mutes(
        self, group_openid: str, member_openids: str | Iterable[str], until: datetime | timedelta
    ) -> None:
        """修改正在禁言中的成员的到期时间，可以延长也可以缩短；没在禁言中的成员用 `mute_members()`。

        机器人须是群管理员；只能操作普通成员。

        对应官方接口 `POST /v2/groups/{group_openid}/restrict_chat_setting`（`op` 为 `update`）。

        Args:
            group_openid: 群的 openid。
            member_openids: 一个或多个成员的 `member_openid`，单次最多 20 个（超出由平台拒绝）。
            until: 新的到期时间，写法同 `mute_members()`。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员，或成员没在禁言中（是否如此尚待实测）。
            NetworkError: 没有拿到平台的响应。
            ValueError: 同 `mute_members()`。
            RuntimeError: 客户端已关闭。
        """
        expire_at = rfc3339(until, "until")
        await self._set_mute(group_openid, MuteOp.UPDATE, member_openids, expire_at)

    async def unmute_members(self, group_openid: str, member_openids: str | Iterable[str]) -> None:
        """立即解除群成员的禁言。

        机器人须是群管理员。

        对应官方接口 `POST /v2/groups/{group_openid}/restrict_chat_setting`（`op` 为 `del`）。

        Args:
            group_openid: 群的 openid。
            member_openids: 一个或多个成员的 `member_openid`，单次最多 20 个（超出由平台拒绝）。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 为空。
            RuntimeError: 客户端已关闭。
        """
        # 文档：op=del 时 mute_expire_at 传空串表示立即解除。
        await self._set_mute(group_openid, MuteOp.DEL, member_openids, "")

    async def _set_mute(
        self, group_openid: str, op: MuteOp, member_openids: str | Iterable[str], expire_at: str
    ) -> None:
        members = [
            {"op": op, "member_openid": member_openid, "mute_expire_at": expire_at}
            for member_openid in str_list(member_openids)
        ]
        path = f"{_group_path(group_openid)}/restrict_chat_setting"
        await self._http.request("POST", path, type_=None, json={"members": members})

    def iter_join_requests(self, group_openid: str) -> AsyncIterator[GroupJoinRequestInfo]:
        """依次列出待审批的入群申请。

        机器人须是群管理员。

        对应官方接口 `GET /v2/groups/{group_openid}/join_request_list`。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 为空。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            async for request in client.groups.iter_join_requests(group_openid):
                await client.groups.approve_join_request(
                    group_openid, request.member_openid, join_request_id=request.join_request_id
                )
            ```
        """
        path = f"{_group_path(group_openid)}/join_request_list"

        async def fetch(cursor: str | None) -> Page[GroupJoinRequestInfo, str]:
            params = {"limit": _JOIN_REQUEST_PAGE_LIMIT} | ({"cursor": cursor} if cursor else {})
            page = await self._http.request("GET", path, type_=JoinRequestPage, params=params)
            return Page(page.requests, page.next_cursor)

        return paginate(fetch)

    async def approve_join_request(
        self, group_openid: str, member_openid: str, *, join_request_id: str | None = None
    ) -> None:
        """通过入群申请。收到事件时可以直接用 `GroupJoinRequest.approve()`。

        机器人须是群管理员。

        对应官方接口 `POST /v2/groups/{group_openid}/approval_join_request/{member_openid}`。

        Args:
            group_openid: 群的 openid。
            member_openid: 申请人的 `member_openid`。
            join_request_id: 申请 ID（事件或 `iter_join_requests()` 里有），文档标为可选。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员，或申请已处理。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 或 `member_openid` 为空。
            RuntimeError: 客户端已关闭。
        """
        body: dict[str, object] = {"op": JoinRequestOp.APPROVE}
        if join_request_id is not None:
            body["join_request_id"] = join_request_id
        await self._review_join_request(group_openid, member_openid, body)

    async def decline_join_request(
        self,
        group_openid: str,
        member_openid: str,
        *,
        join_request_id: str | None = None,
        reason: str | None = None,
        add_to_blacklist: bool = False,
    ) -> None:
        """拒绝入群申请，可以附上理由、同时拉进群黑名单。收到事件时可以直接用 `GroupJoinRequest.decline()`。

        机器人须是群管理员。

        对应官方接口 `POST /v2/groups/{group_openid}/approval_join_request/{member_openid}`。

        Args:
            group_openid: 群的 openid。
            member_openid: 申请人的 `member_openid`。
            join_request_id: 申请 ID（事件或 `iter_join_requests()` 里有），文档标为可选。
            reason: 拒绝理由。
            add_to_blacklist: 同时加入群黑名单。

        Raises:
            APIError: 平台拒绝，例如机器人不是管理员，或申请已处理。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openid` 或 `member_openid` 为空。
            RuntimeError: 客户端已关闭。
        """
        body: dict[str, object] = {"op": JoinRequestOp.DECLINE}
        if join_request_id is not None:
            body["join_request_id"] = join_request_id
        if reason is not None:
            body["reject_reason"] = reason
        body["add_to_member_blacklist"] = add_to_blacklist
        await self._review_join_request(group_openid, member_openid, body)

    async def _review_join_request(
        self, group_openid: str, member_openid: str, body: dict[str, object]
    ) -> None:
        member = path_segment(member_openid, "member_openid")
        path = f"{_group_path(group_openid)}/approval_join_request/{member}"
        await self._http.request("POST", path, type_=None, json=body)


def _group_path(group_openid: str) -> str:
    return f"/v2/groups/{path_segment(group_openid, 'group_openid')}"
