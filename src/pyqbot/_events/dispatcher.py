"""事件分发器，行为约定见 `docs/design.md`「事件」。"""

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from .._errors import PayloadError
from .._gateway.intents import Intents
from .._models.event import Event, bind_client

if TYPE_CHECKING:
    from .._client import Client

_logger = logging.getLogger("pyqbot")

type Handler[E: Event] = Callable[[E], Awaitable[object]]
"""事件处理函数：只收一个事件对象，必须是 `async def`。"""


class DispatchPayload(Protocol):
    """分发器用到的那部分 Dispatch payload，`GatewayPayload` 满足它。"""

    @property
    def t(self) -> str | None: ...

    def decode_data[T](self, type_: type[T]) -> T: ...


@dataclass(slots=True)
class _Route[E: Event]:
    event_type: type[E]
    handlers: list[Handler[E]] = field(default_factory=list[Handler[E]])


class Dispatcher:
    """按事件名把 Dispatch 解成事件模型，交给注册的处理函数，每个处理函数在自己的任务里运行。"""

    def __init__(self) -> None:
        # 各事件的模型类型不同，只能写 Any；同一个 _Route 里的类型由 add_handler 保证一致。
        self._routes: dict[str, _Route[Any]] = {}
        self._tasks: set[asyncio.Task[None]] = set()  # 强引用：事件循环只弱引用任务
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
        for handler in route.handlers:
            task = asyncio.create_task(
                _run(payload.t, handler, event), name=f"pyqbot:{payload.t}:{_name_of(handler)}"
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def aclose(self) -> None:
        """不再接受分发，取消并等待还在运行的处理函数；可以重复调用。

        在处理函数里调用时不取消调用者自己，否则它会在等待中被取消、无法完成关闭。
        """
        self._closed = True
        current = asyncio.current_task()
        tasks = [task for task in self._tasks if task is not current]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _run[E: Event](event_name: str, handler: Handler[E], event: E) -> None:
    try:
        await handler(event)
    except Exception:
        _logger.exception("事件 %s 的处理函数 %s 抛出了异常", event_name, _name_of(handler))


def _name_of(handler: object) -> str:
    name = getattr(handler, "__qualname__", None)
    return name if isinstance(name, str) else repr(handler)
