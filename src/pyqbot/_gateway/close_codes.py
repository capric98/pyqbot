"""网关关闭码的分类（`dev-prepare/error-trace/websocket.md`）。

| 关闭码 | 处理 | 依据 |
| --- | --- | --- |
| 4008、4009 | Resume | 表格两列都「是」，优先保住会话与遗漏事件 |
| 4006、4007、4900~4913 | Identify | 表格只有 Identify 列「是」 |
| 4001、4002、4010~4014、4914、4915 | 放弃 | 表格两列都「否」；同样的参数重连只会再被关，还消耗每日连接次数 |
| 其它 4000~4999 | Identify | 表下「其他错误，请重新发起 identify」 |
| 无关闭帧、1000 等标准码 | Resume | 文档「断开之后短时间内重连」；会话已失效时网关会再告知 |

表格与表下简化说明的冲突见 `docs/errata.md`。重试上限、退避、OpCode 7 / 9 的处理由网关模块决定。
"""

import enum
from dataclasses import dataclass


class CloseAction(enum.Enum):
    """连接被关闭后应该怎么做。

    Attributes:
        RESUME: 重连后发 Resume；还没收到过 READY 时由网关模块退化为 Identify。
        IDENTIFY: 重连后发 Identify 建立新会话。
        GIVE_UP: 重连也不会成功：停止重连，把错误报给用户。
    """

    RESUME = "resume"
    IDENTIFY = "identify"
    GIVE_UP = "give_up"


@dataclass(frozen=True, slots=True)
class CloseCodeInfo:
    """一个关闭码的分类结果。

    Attributes:
        code: 关闭码；没有收到关闭帧时为 `None`。
        action: 应该怎么做。
        reason: 中文说明，可直接用于日志和异常文案。
    """

    code: int | None
    action: CloseAction
    reason: str


_RESUME = CloseAction.RESUME
_IDENTIFY = CloseAction.IDENTIFY
_GIVE_UP = CloseAction.GIVE_UP

_KNOWN_CODES: dict[int, tuple[CloseAction, str]] = {
    4001: (_GIVE_UP, "无效的 opcode"),
    4002: (_GIVE_UP, "无效的 payload"),
    4006: (_IDENTIFY, "无效的 session id，无法继续 resume"),
    4007: (_IDENTIFY, "seq 错误"),
    4008: (_RESUME, "发送 payload 过快"),
    4009: (_RESUME, "连接过期"),
    4010: (_GIVE_UP, "无效的 shard"),
    4011: (_GIVE_UP, "连接需要处理的 guild 过多，请进行合理的分片"),
    4012: (_GIVE_UP, "无效的 version"),
    4013: (_GIVE_UP, "无效的 intent"),
    4014: (_GIVE_UP, "intent 无权限"),
    4914: (_GIVE_UP, "机器人已下架，只允许连接沙箱环境"),
    4915: (_GIVE_UP, "机器人已封禁，不允许连接"),
}

_INTERNAL_ERROR_CODES = range(4900, 4914)
_APPLICATION_CODES = range(4000, 5000)  # WebSocket 留给应用自定义的区间


def classify_close_code(code: int | None) -> CloseCodeInfo:
    """判断网关连接被关闭后应该 Resume、Identify 还是放弃，规则见模块说明。

    Args:
        code: 关闭帧里的关闭码；没有收到关闭帧时传 `None`。
    """
    if code is None:
        return CloseCodeInfo(code, _RESUME, "连接断开，未收到关闭码")
    if (known := _KNOWN_CODES.get(code)) is not None:
        action, reason = known
        return CloseCodeInfo(code, action, reason)
    if code in _INTERNAL_ERROR_CODES:
        return CloseCodeInfo(code, _IDENTIFY, "平台内部错误")
    if code in _APPLICATION_CODES:
        return CloseCodeInfo(code, _IDENTIFY, "未知的网关错误")
    return CloseCodeInfo(code, _RESUME, "连接被关闭")
