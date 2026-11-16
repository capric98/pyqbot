"""事件分发器，行为约定见 `docs/design.md`「事件」。"""

import asyncio
import functools
import inspect
import logging
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, cast

from .._errors import PayloadError
from .._gateway.intents import Intents
from .._models.event import Event, bind_client, bind_event_id

if TYPE_CHECKING:
    from .._client import Client

_logger = logging.getLogger("pyqbot")

CLOSE_GRACE_PERIOD = 5.0  # 秒：aclose() 等处理函数结束的默认期限
_UNNAMED_HANDLER = "<未命名的处理函数>"

type Handler[E: Event] = Callable[[E], Awaitable[object]]
"""事件处理函数：只收一个事件对象，必须是 `async def`。"""


class DispatchPayload(Protocol):
    """分发器用到的那部分 Dispatch payload，`GatewayPayload` 满足它。"""

    @property
    def t(self) -> str | None: ...

    @property
    def id(self) -> str | None: ...

    def decode_data[T](self, type_: type[T]) -> T: ...


@dataclass(slots=True)
class _Route[E: Event]:
    event_type: type[E]
    handlers: list[Handler[E]] = field(default_factory=list[Handler[E]])


class Dispatcher:
    """按事件名把 Dispatch 解成事件模型，交给注册的处理函数；`redact` 给写进日志的异常脱敏。"""

    def __init__(self, *, redact: Callable[[str], str]) -> None:
        # 各事件的模型类型不同，只能写 Any；同一个 _Route 里的类型由 add_handler 保证一致。
        self._routes: dict[str, _Route[Any]] = {}
        self._tasks: set[asyncio.Task[None]] = set()  # 强引用：事件循环只弱引用任务
        self._redact = redact
        self._closed = False

    @property
    def intents(self) -> Intents:
        """已注册的处理函数所需的 Intents。"""
        intents = Intents(0)
        for route in self._routes.values():
            intents |= route.event_type.intent
        return intents

    def add_handler[E: Event](self, event_type: type[E], handler: Handler[E]) -> None:
        """为 `event_type` 注册处理函数；同一事件可以注册多个，按注册顺序启动。

        Raises:
            TypeError: `handler` 不是 `async def` 定义的。
        """
        if not inspect.iscoroutinefunction(handler):
            raise TypeError(
                f"事件处理函数必须用 async def 定义，{_name_of(handler)} 不是："
                "请把 def 改成 async def，并在里面 await 需要等待的调用"
            )
        route = self._routes.setdefault(event_type.event_name, _Route(event_type))
        route.handlers.append(handler)

    def dispatch(self, payload: DispatchPayload, client: Client) -> None:
        """为每个处理函数启动一个任务后立刻返回；没有处理函数的事件不解码，解不开的记日志后丢弃。"""
        if self._closed or payload.t is None:
            return
        route = self._routes.get(payload.t)
        if route is None:
            return
        try:
            event = payload.decode_data(route.event_type)
        except PayloadError as exc:
            # 文案只有期望类型与 JSON 路径，不含消息内容。
            _logger.warning("丢弃无法解码的事件：%s", exc)
            return
        bind_client(event, client)
        bind_event_id(event, payload.id)
        for handler in route.handlers:
            task = asyncio.create_task(
                self._run(payload.t, handler, event),
                name=f"pyqbot:{payload.t}:{_name_of(handler)}",
                eager_start=False,
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def aclose(self, *, grace_period: float = CLOSE_GRACE_PERIOD) -> None:
        """不再分发，取消并等待处理函数，最多等 `grace_period` 秒；时序上的语义见 `docs/design.md`「事件」。"""
        current = asyncio.current_task()
        if not self._closed:  # 只取消一次：再次取消会打断处理函数正在做的清理
            self._closed = True
            for task in self._tasks:
                if task is not current:
                    task.cancel()
        if current in self._tasks:  # 在处理函数里：等别的处理函数可能形成互相等待
            return
        pending = set(self._tasks)
        if not pending:
            return
        _, pending = await asyncio.wait(pending, timeout=grace_period)
        if pending:
            _logger.warning(
                "关闭时有 %d 个处理函数在 %s 秒内没有结束（可能吞掉了取消），不再等待",
                len(pending),
                grace_period,
            )

    async def _run[E: Event](self, event_name: str, handler: Handler[E], event: E) -> None:
        try:
            await handler(event)
        except Exception as exc:  # noqa: BLE001  处理函数的任何异常都只记日志，不影响其它处理函数
            # 异常链可能带着凭证，先格式化、脱敏，不交给 logging 打印。
            detail = self._redact("".join(traceback.format_exception(exc)))
            _logger.error(
                "事件 %s 的处理函数 %s 抛出了异常：\n%s", event_name, _name_of(handler), detail
            )


def _name_of(handler: object) -> str:
    """处理函数的名字，不含 `partial` 绑定的参数（可能是凭证），取法见 `docs/design.md`「事件」。"""
    while isinstance(handler, functools.partial):
        handler = cast(functools.partial[object], handler).func
    for candidate in (handler, type(handler)):
        name = getattr(candidate, "__qualname__", None)
        if isinstance(name, str):
            return name
    return _UNNAMED_HANDLER
