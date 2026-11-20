"""网关连接状态的公共类型，由 `Bot.gateway_status` 返回。"""

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta


class GatewayState(enum.Enum):
    """网关连接所处的阶段。

    Attributes:
        NOT_STARTED: 还没调用 `Bot.start()`，或调用时当场被拒（如没有处理函数）。
        DISCONNECTED: `start()` 正在运行但没连上：首次连上之前，或断线之后、重新连上之前。
        CONNECTED: 当前这条连接已认证成功（Identify 或 Resume 后收到了第一条事件）。
        STOPPED: 已调用 `stop()` / `close()`（调用时就进入，不等收尾），或 `start()` 已结束（含抛出异常、
            被取消）。终态，不再变化。
    """

    NOT_STARTED = "not_started"
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True, kw_only=True)
class GatewayStatus:
    """网关连接状态的快照，由 `Bot.gateway_status` 返回。

    Attributes:
        state: 当前所处的阶段。
        since: 进入当前阶段的时刻，带时区的 UTC 时间（系统时钟）；`NOT_STARTED` 时是构造 `Bot` 的时刻。
        elapsed: 截至取得这个快照时处于当前阶段的时长，判断「断开多久」用它，不必自己拿 `since` 相减。
            按单调时钟计：不受系统时钟调整影响、不会倒退，但不含机器睡眠的时间。
    """

    state: GatewayState
    since: datetime
    elapsed: timedelta
