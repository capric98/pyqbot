"""单聊与群聊的通知类事件：好友增删、主动消息开关、机器人进出群、群成员变动、入群申请、订阅消息授权。

官方文档在 `autogen/event/` 下，文件名即事件名的小写。整数秒的 `timestamp` 保持 `int`，理由见 `docs/design.md`「事件」。
"""

from datetime import datetime

import msgspec

from .._gateway.intents import Intents
from .._model import Model, OpenIntEnum, OpenStrEnum
from .event import C2CReplyTarget, Event, GroupReplyTarget
from .message import C2CMessage, GroupAnyMessage, SentMessage
from .send import Card, Keyboard, Markdown, Media

# ---- 单聊 ----


class FriendAddScene(OpenIntEnum):
    """用户添加机器人为好友的来源（`FriendAdd.scene`）。

    Attributes:
        DEFAULT: 缺省。
        SEARCH_ALL: 网络搜索的「全部」页。
        SEARCH_BOT: 网络搜索的「机器人」页。
        GROUP: 群。
        QZONE: QQ 空间。
        PROFILE_SHARE_INSIDE: 在 QQ 内分享的资料页。
        PROFILE_SHARE_OUTSIDE: 在 QQ 外分享的资料页。
        LINK_INSIDE: 开发者生成的分享链接，在 QQ 内打开；`scene_param` 是链接的 `callback_data`。
        LINK_OUTSIDE: 开发者生成的分享链接，在 QQ 外打开；同上。
    """

    DEFAULT = 1000
    SEARCH_ALL = 1001
    SEARCH_BOT = 1002
    GROUP = 1003
    QZONE = 1004
    PROFILE_SHARE_INSIDE = 2001
    PROFILE_SHARE_OUTSIDE = 2002
    LINK_INSIDE = 2003
    LINK_OUTSIDE = 2004


class FriendAuthor(Model):
    """好友事件里的用户信息。"""

    union_openid: str | None = None


class _UserNotice(Event):
    # 单聊通知共有的字段；timestamp 是 Unix 秒。
    timestamp: int | None = None
    openid: str


class _C2CReplyNotice(_UserNotice, C2CReplyTarget):
    async def reply(
        self,
        content: str | None = None,
        *,
        markdown: str | Markdown | None = None,
        keyboard: Keyboard | None = None,
        media: Media | None = None,
        card: Card | None = None,
        quote: str | SentMessage | C2CMessage | None = None,
    ) -> SentMessage:
        """用事件 ID 被动回复这个用户，`event_id` 与 `msg_seq` 由 SDK 填写；参数同 `client.users.send_message()`。

        对应官方接口 `POST /v2/users/{user_openid}/messages`。

        Raises:
            APIError: 平台拒绝发送，例如事件 ID 已过期（`err_code` 为 40034026）。
            NetworkError: 没有拿到平台的响应。
            ValueError: 内容参数的组合不合法，或事件没有事件 ID。
            RuntimeError: 事件不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。
        """
        client = self._bound_client()
        return await client.users.send_message(
            self.openid,
            content,
            markdown=markdown,
            keyboard=keyboard,
            media=media,
            card=card,
            quote=quote,
            reply_to=self,
        )


class FriendAdd(_C2CReplyNotice):
    """用户添加机器人为好友，对应事件 `FRIEND_ADD`。可以用 `reply()` 被动回复。

    Attributes:
        openid: 用户的 openid，即单聊的 `user_openid`。
        timestamp: 添加时间，Unix 秒。
        scene: 从哪里添加的。
        scene_param: 开发者分享链接里的 `callback_data`，用来区分来源；没有时为空串。
        short_code: 机器人分享链接的短链 code。
        author: 用户信息，含 `union_openid`。

    Example:
        ```python
        @bot.on_friend_add
        async def welcome(event: pyqbot.FriendAdd) -> None:
            await event.reply("欢迎")
        ```
    """

    event_name = "FRIEND_ADD"
    intent = Intents.GROUP_AND_C2C_EVENT

    scene: FriendAddScene | None = None
    scene_param: str = ""
    short_code: str | None = None
    author: FriendAuthor = msgspec.field(default_factory=FriendAuthor)


class FriendDel(_UserNotice):
    """用户删除机器人好友，对应事件 `FRIEND_DEL`。

    Attributes:
        openid: 用户的 openid。
        timestamp: 删除时间，Unix 秒。
        author: 用户信息，含 `union_openid`；官方示例里没有。
    """

    event_name = "FRIEND_DEL"
    intent = Intents.GROUP_AND_C2C_EVENT

    author: FriendAuthor = msgspec.field(default_factory=FriendAuthor)


class C2CMsgReject(_UserNotice):
    """用户在机器人资料卡关闭了主动消息，对应事件 `C2C_MSG_REJECT`。之后不能再向他发主动消息。

    Attributes:
        openid: 用户的 openid。
        timestamp: 操作时间，Unix 秒。
    """

    event_name = "C2C_MSG_REJECT"
    intent = Intents.GROUP_AND_C2C_EVENT


class C2CMsgReceive(_C2CReplyNotice):
    """用户在机器人资料卡打开了主动消息，对应事件 `C2C_MSG_RECEIVE`。可以用 `reply()` 被动回复。

    Attributes:
        openid: 用户的 openid。
        timestamp: 操作时间，Unix 秒。
    """

    event_name = "C2C_MSG_RECEIVE"
    intent = Intents.GROUP_AND_C2C_EVENT


# ---- 群：机器人进出、主动消息开关 ----


class _GroupNotice(Event):
    timestamp: int | None = None
    group_openid: str
    op_member_openid: str | None = None


class _GroupReplyNotice(_GroupNotice, GroupReplyTarget):
    async def reply(
        self,
        content: str | None = None,
        *,
        markdown: str | Markdown | None = None,
        keyboard: Keyboard | None = None,
        media: Media | None = None,
        card: Card | None = None,
        quote: str | SentMessage | GroupAnyMessage | None = None,
    ) -> SentMessage:
        """用事件 ID 被动回复这个群，`event_id` 与 `msg_seq` 由 SDK 填写；参数同 `client.groups.send_message()`。

        对应官方接口 `POST /v2/groups/{group_openid}/messages`。

        Raises:
            APIError: 平台拒绝发送，例如事件 ID 已过期（`err_code` 为 40034026）。
            NetworkError: 没有拿到平台的响应。
            ValueError: 内容参数的组合不合法，或事件没有事件 ID。
            RuntimeError: 事件不是 `Bot` 分发来的（没有绑定客户端），或客户端已关闭。
        """
        client = self._bound_client()
        return await client.groups.send_message(
            self.group_openid,
            content,
            markdown=markdown,
            keyboard=keyboard,
            media=media,
            card=card,
            quote=quote,
            reply_to=self,
        )


class GroupAddRobot(_GroupReplyNotice):
    """机器人被拉进群，对应事件 `GROUP_ADD_ROBOT`。可以用 `reply()` 被动回复。

    Attributes:
        group_openid: 群的 openid。
        op_member_openid: 拉机器人进群的成员。
        timestamp: 加入时间，Unix 秒。
    """

    event_name = "GROUP_ADD_ROBOT"
    intent = Intents.GROUP_AND_C2C_EVENT


class GroupDelRobot(_GroupNotice):
    """机器人被移出群，对应事件 `GROUP_DEL_ROBOT`。

    Attributes:
        group_openid: 群的 openid。
        op_member_openid: 移出机器人的成员。
        timestamp: 移出时间，Unix 秒。
    """

    event_name = "GROUP_DEL_ROBOT"
    intent = Intents.GROUP_AND_C2C_EVENT


class GroupMsgReject(_GroupNotice):
    """群管理员在机器人资料页关闭了主动消息，对应事件 `GROUP_MSG_REJECT`。

    Attributes:
        group_openid: 群的 openid。
        op_member_openid: 操作的管理员。
        timestamp: 操作时间，Unix 秒。
    """

    event_name = "GROUP_MSG_REJECT"
    intent = Intents.GROUP_AND_C2C_EVENT


class GroupMsgReceive(_GroupReplyNotice):
    """群管理员在机器人资料页打开了主动消息，对应事件 `GROUP_MSG_RECEIVE`。可以用 `reply()` 被动回复。

    Attributes:
        group_openid: 群的 openid。
        op_member_openid: 操作的管理员。
        timestamp: 操作时间，Unix 秒。
    """

    event_name = "GROUP_MSG_RECEIVE"
    intent = Intents.GROUP_AND_C2C_EVENT


# ---- 群成员 ----


class _GroupMemberNotice(Event):
    timestamp: int | None = None
    group_openid: str
    member_openid: str


class GroupMemberAdd(_GroupMemberNotice):
    """有新成员加入群，对应事件 `GROUP_MEMBER_ADD`。

    Attributes:
        group_openid: 群的 openid。
        member_openid: 新成员的 openid。
        timestamp: 加入时间，Unix 秒。
    """

    event_name = "GROUP_MEMBER_ADD"
    intent = Intents.GROUP_MEMBER_EVENT


class GroupMemberRemove(_GroupMemberNotice):
    """成员退出或被移出群，对应事件 `GROUP_MEMBER_REMOVE`。

    Attributes:
        group_openid: 群的 openid。
        member_openid: 离开的成员的 openid。
        user_openid: 他的单聊 openid，可能没有。
        timestamp: 离开时间，Unix 秒。
    """

    event_name = "GROUP_MEMBER_REMOVE"
    intent = Intents.GROUP_MEMBER_EVENT

    user_openid: str | None = None


class JoinRequestVerifyMethod(OpenStrEnum):
    """入群申请的验证方式（`JoinRequestVerifyInfo.method`）。

    Attributes:
        VERIFY_MESSAGE: 填写验证消息。
        ADMIN_REVIEW_QA: 回答问题，由管理员审核。
    """

    VERIFY_MESSAGE = "verify_message"
    ADMIN_REVIEW_QA = "admin_review_qa"


class JoinRequestSource(OpenStrEnum):
    """入群申请的来源（`GroupJoinRequest.apply_source`）。

    Attributes:
        SELF_APPLY: 主动申请。
        INVITED: 被邀请。
    """

    SELF_APPLY = "self_apply"
    INVITED = "invited"


class JoinRequestQA(Model):
    """入群申请里的一组问答。"""

    question: str = ""
    answer: str = ""


class JoinRequestVerifyInfo(Model):
    """入群申请的验证方式与申请人填写的内容。

    Attributes:
        method: 验证方式。
        verify_message: 验证消息，`method` 为 `VERIFY_MESSAGE` 时可能有。
        review_qa_list: 问答，`method` 为 `ADMIN_REVIEW_QA` 时可能有。
    """

    method: JoinRequestVerifyMethod | None = None
    verify_message: str | None = None
    review_qa_list: tuple[JoinRequestQA, ...] = ()


class JoinRequestAutoApproved(Model):
    """入群申请被自动通过时的信息。"""

    strategy_id: str | None = None


class GroupJoinRequest(Event):
    """有人申请加群，对应事件 `GROUP_JOIN_REQUEST`。只有机器人是群管理员时才会收到。

    Attributes:
        group_openid: 群的 openid。
        join_request_id: 申请 ID，审批时要用。
        member_openid: 申请人的 openid，审批接口要用。
        union_openid: 申请人跨应用统一的 openid（如有）。
        username: 申请人昵称。
        bot: 申请人是否为机器人。
        apply_at: 申请时间，带时区。
        apply_source: 主动申请还是被邀请。
        invited_by: 邀请人的 openid，被邀请时才有。
        risk_tips: 安全提示语。
        verify_info: 验证方式与申请人填写的内容。
        auto_approved: 已被自动通过时才有，含策略 ID。
    """

    event_name = "GROUP_JOIN_REQUEST"
    intent = Intents.GROUP_MEMBER_EVENT

    group_openid: str
    join_request_id: str
    member_openid: str
    union_openid: str | None = None
    username: str | None = None
    bot: bool | None = None
    apply_at: datetime | None = None
    apply_source: JoinRequestSource | None = None
    invited_by: str | None = None
    risk_tips: str | None = None
    verify_info: JoinRequestVerifyInfo | None = None
    auto_approved: JoinRequestAutoApproved | None = None


# ---- 订阅消息 ----


class SubscribeOp(OpenIntEnum):
    """用户对订阅消息模板的操作。"""

    ACCEPT = 1
    REJECT = 2


class SubscribeResult(Model):
    """一个订阅消息模板的授权结果。

    Attributes:
        template_id: 平台提供的模板 ID。
        custom_template_id: 自定义模板 ID。
        op: 允许还是拒绝。
        subscribe_id: 订阅 ID，发送订阅消息时要用。
        subscribe_ts: 订阅时间，Unix 秒。
        update_ts: 状态最后更新时间，Unix 秒。
    """

    template_id: int | None = None
    custom_template_id: str | None = None
    op: SubscribeOp | None = None
    subscribe_id: str | None = None
    subscribe_ts: int | None = None
    update_ts: int | None = None


class SubscribeMessageStatus(Event):
    """用户或群对订阅消息模板的授权状态变了，对应事件 `SUBSCRIBE_MESSAGE_STATUS`。

    Attributes:
        openid: 用户的 openid，个人订阅时才有。
        group_openid: 群的 openid，群订阅时才有。
        result: 各模板的授权结果。
    """

    event_name = "SUBSCRIBE_MESSAGE_STATUS"
    intent = Intents.GROUP_AND_C2C_EVENT

    openid: str | None = None
    group_openid: str | None = None
    result: tuple[SubscribeResult, ...] = ()
