"""群管理与入群自动审批策略的模型。

官方文档在 `autogen/api/` 下：`v2_groups_group_openid_*` 与 `v2_groups_join_approval_strategy*`。
"""

from datetime import datetime
from typing import cast

import msgspec

from .._model import Model, OpenStrEnum
from .message import MemberRole
from .notice import JoinRequestSource, JoinRequestVerifyInfo

# ---- 群信息与机器人状态 ----


class GroupInfo(Model):
    """群的基本信息。

    Attributes:
        group_openid: 群的 openid。
        group_name: 群名称。
        group_finger_memo: 群简介。
        group_class_text: 群分类。
        group_tags: 群标签。
        group_member_num: 群成员人数。
    """

    group_openid: str | None = None
    group_name: str | None = None
    group_finger_memo: str | None = None
    group_class_text: str | None = None
    group_tags: tuple[str, ...] = ()
    group_member_num: int | None = None


class RecvMsgSetting(OpenStrEnum):
    """机器人在群里接收哪些消息（`GroupBotState.recv_msg_setting`）。

    Attributes:
        ALL: 全部消息。
        ONLY_MENTION: 只有 @ 机器人的消息。
        MENTION_AND_CONTEXT: @ 机器人的消息及其上下文。
    """

    ALL = "all"
    ONLY_MENTION = "only_mention"
    MENTION_AND_CONTEXT = "mention_and_context"


class GroupBotState(Model):
    """机器人在群里的状态。

    Attributes:
        member_openid: 机器人在这个群里的 openid。
        joined_at: 入群时间，带时区。
        allow_proactive_msg: 是否接收主动推送。
        recv_msg_setting: 接收哪些消息。
        member_role: 机器人的群内角色；禁言、入群审批等接口要求是管理员。
    """

    member_openid: str | None = None
    joined_at: datetime | None = None
    allow_proactive_msg: bool | None = None
    recv_msg_setting: RecvMsgSetting | None = None
    member_role: MemberRole | None = None


# ---- 成员与黑名单 ----


class GroupMemberInfo(Model):
    """群成员的信息（成员列表与成员查询的结果）。

    Attributes:
        member_openid: 成员的 openid。
        username: 昵称。
        member_role: 群内角色。
        bot: 是否为机器人。
        joined_at: 入群时间，带时区。
        union_openid: 跨应用统一的 openid（如有）。
    """

    member_openid: str
    username: str | None = None
    member_role: MemberRole | None = None
    bot: bool | None = None
    joined_at: datetime | None = None
    union_openid: str | None = None


class MemberPage(Model):
    """群成员列表的一页。"""

    members: tuple[GroupMemberInfo, ...] = ()
    next_cursor: str | None = None


def _failed_openids(value: object, name: str) -> tuple[str, ...]:
    """失败清单：缺失或 `null` 是没有失败。

    Raises:
        ValueError: 不是字符串列表。宽容解码若退回默认值，已知的失败就成了全部成功，所以宁可让响应失败。
    """
    if value is None:
        return ()
    if isinstance(value, list):
        items = cast(list[object], value)
        if all(isinstance(item, str) for item in items):
            return tuple(cast(list[str], items))
    raise ValueError(f"{name} 不是字符串列表")


class RemoveMembersResult(Model):
    """批量移除成员的响应。两个字段都写成 `object` 并在解码时校验，理由见 `_failed_openids()`。"""

    remove_members_result: object = None
    add_to_member_blacklist_fail_openids: object = None

    def __post_init__(self) -> None:
        # 解码时就校验：不合法即「响应无法识别」。
        if not isinstance(self.remove_members_result, str | None):
            raise TypeError("remove_members_result 不是字符串")
        _failed_openids(
            self.add_to_member_blacklist_fail_openids, "add_to_member_blacklist_fail_openids"
        )

    @property
    def removal_failed(self) -> bool:
        """平台是否报告了移出失败：缺失或 `null` 算没有报告，其它不是 `success` 的字符串算失败。"""
        return self.remove_members_result not in (None, "success")

    @property
    def blacklist_failed(self) -> tuple[str, ...]:
        """未能加入黑名单的 openid。"""
        return _failed_openids(
            self.add_to_member_blacklist_fail_openids, "add_to_member_blacklist_fail_openids"
        )


class BlacklistedUser(Model):
    """群黑名单里的一个用户。

    Attributes:
        member_openid: 用户的 openid。
        username: 昵称。
        banned_at: 拉黑时间，带时区。
        bot: 是否为机器人。
        union_openid: 跨应用统一的 openid（如有）。
    """

    member_openid: str
    username: str | None = None
    banned_at: datetime | None = None
    bot: bool | None = None
    union_openid: str | None = None


class BlacklistPage(Model):
    """群黑名单的一页。"""

    users: tuple[BlacklistedUser, ...] = ()
    next_cursor: str | None = None


class BlacklistResult(Model):
    """增删群黑名单的响应。失败清单的处理同 `RemoveMembersResult`。"""

    fail_openids: object = None

    def __post_init__(self) -> None:
        _failed_openids(self.fail_openids, "fail_openids")

    @property
    def failed(self) -> tuple[str, ...]:
        """操作失败的 openid。"""
        return _failed_openids(self.fail_openids, "fail_openids")


# ---- 禁言 ----


class GroupMuteMode(OpenStrEnum):
    """全员禁言的模式（`GroupMuteRule.mode`）。

    Attributes:
        NONE: 未开启。
        ALWAYS: 始终禁言。
        SCHEDULE: 按定时或周期规则禁言。
    """

    NONE = "none"
    ALWAYS = "always"
    SCHEDULE = "schedule"


class MuteScheduleRule(Model):
    """一条定时禁言规则：在一段时间内全员禁言。

    Attributes:
        task_id: 规则 ID。
        start_at: 开始时间，带时区。
        end_at: 结束时间，带时区。
        enabled: 是否启用。
    """

    task_id: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    enabled: bool | None = None


class MuteRecurringRule(Model):
    """一条周期禁言规则：每周的某几天、在某个时段全员禁言。

    Attributes:
        task_id: 规则 ID。
        weekdays: 生效的星期，1 为周一、7 为周日（同 `date.isoweekday()`）。
        start_time: 时段开始，`HH:mm`，北京时间。
        end_time: 时段结束，`HH:mm`，北京时间；早于 `start_time` 表示跨到次日。
        enabled: 是否启用。
    """

    task_id: str | None = None
    weekdays: tuple[int, ...] = ()
    start_time: str | None = None
    end_time: str | None = None
    enabled: bool | None = None


class GroupMuteRule(Model):
    """全员禁言的设置。

    Attributes:
        mode: 模式。
        schedule_rules: 定时禁言规则。
        recurring_rules: 周期禁言规则。
    """

    mode: GroupMuteMode | None = None
    schedule_rules: tuple[MuteScheduleRule, ...] = ()
    recurring_rules: tuple[MuteRecurringRule, ...] = ()


class MutedMember(Model):
    """正在禁言中的一个成员。

    Attributes:
        member_openid: 成员的 openid。
        mute_expire_at: 禁言到期时间，带时区。
        username: 昵称。
        union_openid: 跨应用统一的 openid（如有）。
    """

    member_openid: str
    mute_expire_at: datetime | None = None
    username: str | None = None
    union_openid: str | None = None


class GroupMuteSettings(Model):
    """群的禁言状态。

    Attributes:
        global_rule: 全员禁言的设置；只能查询，不能经接口修改。
        members: 正在禁言中的成员，不含已到期的。
    """

    global_rule: GroupMuteRule = msgspec.field(default_factory=GroupMuteRule)
    members: tuple[MutedMember, ...] = ()


class MuteOp(OpenStrEnum):
    """设置成员禁言的 `op`。"""

    ADD = "add"
    UPDATE = "update"
    DEL = "del"


# ---- 入群申请 ----


class JoinRequest(Model):
    """待审批的一条入群申请（`iter_join_requests()` 的结果）。字段同事件 `GroupJoinRequest`。

    Attributes:
        join_request_id: 申请 ID，审批时要用。
        member_openid: 申请人的 openid，审批时要用。
        union_openid: 申请人跨应用统一的 openid（如有）。
        username: 申请人昵称。
        bot: 申请人是否为机器人。
        apply_at: 申请时间，带时区。
        apply_source: 主动申请还是被邀请。
        invited_by: 邀请人的 openid，被邀请时才有。
        risk_tips: 安全提示语。
        verify_info: 验证方式与申请人填写的内容。
    """

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


class JoinRequestPage(Model):
    """入群申请列表的一页。"""

    requests: tuple[JoinRequest, ...] = msgspec.field(default=(), name="list")
    next_cursor: str | None = None


class JoinRequestOp(OpenStrEnum):
    """入群申请审批的 `op`。"""

    APPROVE = "approve"
    DECLINE = "decline"


# ---- 入群自动审批策略 ----


class JoinStrategyStatus(OpenStrEnum):
    """入群自动审批策略是否启用（`JoinStrategy.is_enable`）；接口方法的参数用 `enabled: bool` 表达。

    Attributes:
        ON: 启用。
        OFF: 停用。
    """

    ON = "on"
    OFF = "off"


class AddDel(OpenStrEnum):
    """增删操作的 `op`：黑名单、策略的关联群与白名单号码。"""

    ADD = "add"
    DEL = "del"


class JoinStrategy(Model):
    """一个入群自动审批策略。

    Attributes:
        strategy_id: 策略 ID。
        enabled: 是否启用；平台没有给出时为 `None`。
        group_openids: 关联的群 openid，创建时用的是 `group_openids` 才有；只有列出策略时返回。
        group_ids: 关联的 QQ 群号，创建时用的是 `group_ids` 才有；只有列出策略时返回。
            文档写的是整数，示例却是打了码的字符串，所以两种都可能出现。
        whitelist_user_count: 白名单号码数（估算）；只有列出策略时返回。
        is_enable: 是否启用，接口原样的取值；判断时用 `enabled` 更方便。
        expire_at: 过期时间，带时区。
        created_at: 创建时间，带时区；只有列出策略时返回。
        updated_at: 最近更新时间，带时区；只有列出策略时返回。
        remark: 备注。
    """

    strategy_id: str
    group_openids: tuple[str, ...] = ()
    group_ids: tuple[int | str, ...] = ()
    whitelist_user_count: int | None = None
    is_enable: JoinStrategyStatus | None = None
    expire_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    remark: str | None = None

    @property
    def enabled(self) -> bool | None:
        """策略是否启用；平台没有给出或给了认不出的取值时为 `None`。"""
        match self.is_enable:
            case JoinStrategyStatus.ON:
                return True
            case JoinStrategyStatus.OFF:
                return False
            case _:
                return None


class JoinStrategyPage(Model):
    """策略列表的一页。"""

    strategies: tuple[JoinStrategy, ...] = ()
    next_cursor: str | None = None


class WhitelistUpdate(Model):
    """增删策略白名单号码的结果。

    Attributes:
        strategy_id: 策略 ID。
        whitelist_user_count: 操作后的白名单号码数（估算）。
        updated_at: 策略的更新时间，带时区。
    """

    strategy_id: str | None = None
    whitelist_user_count: int | None = None
    updated_at: datetime | None = None
