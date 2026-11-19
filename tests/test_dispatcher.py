"""事件分发器：按事件名分发、异常隔离、不阻塞、关闭。"""

import asyncio
import functools
import gc
import json
import logging
import weakref
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest

import pyqbot
from pyqbot._events.dispatcher import Dispatcher
from pyqbot._gateway.payload import GatewayPayload, decode_payload
from pyqbot._models.event import Event

HANG_GUARD = 5  # 秒：并发测试回归时应失败而不是挂起


class Ping(Event):
    event_name = "PING"
    intent = pyqbot.Intents.GUILDS

    n: int

    def client(self) -> pyqbot.Client:
        return self._bound_client()


class Pong(Event):
    event_name = "PONG"
    intent = pyqbot.Intents.INTERACTION


@dataclass
class CountingPayload:
    """记录是否被解码的 payload 替身。"""

    t: str | None
    id: str | None = None
    decoded: int = 0

    def decode_data[T](self, type_: type[T]) -> T:
        self.decoded += 1
        raise AssertionError("不应解码")


def frame(t: str, data: object, event_id: str | None = None) -> GatewayPayload:
    return decode_payload(json.dumps({"op": 0, "s": 1, "t": t, "d": data, "id": event_id}))


def new_dispatcher() -> Dispatcher:
    # 不脱敏：这里只测分发本身，脱敏由 Bot 注入，见 test_bot.py。
    return Dispatcher(redact=lambda text: text)


def handler_tasks() -> list[asyncio.Task[object]]:
    """分发器建的、还没结束的任务。"""
    return [task for task in asyncio.all_tasks() if task.get_name().startswith("pyqbot:")]


@pytest.fixture
async def client() -> AsyncGenerator[pyqbot.Client]:
    async with pyqbot.Client("app-id", "app-secret") as client:
        yield client


async def test_events_are_routed_by_name_and_bound_to_the_client(client: pyqbot.Client) -> None:
    dispatcher = new_dispatcher()
    got: list[Event] = []
    done = asyncio.Event()

    async def on_ping(event: Ping) -> None:
        got.append(event)
        done.set()

    async def on_pong(event: Pong) -> None:
        got.append(event)

    dispatcher.add_handler(Ping, on_ping)
    dispatcher.add_handler(Pong, on_pong)
    dispatcher.dispatch(frame("PING", {"n": 1}), client)
    async with asyncio.timeout(HANG_GUARD):
        await done.wait()
    await dispatcher.aclose()

    assert got == [Ping(n=1)]
    assert isinstance(got[0], Ping)
    assert got[0].client() is client


@pytest.mark.parametrize("event_id", ["PING:abc", None])
async def test_the_outer_event_id_is_bound_to_the_event(
    client: pyqbot.Client, event_id: str | None
) -> None:
    dispatcher = new_dispatcher()
    got: list[Ping] = []
    done = asyncio.Event()

    async def on_ping(event: Ping) -> None:
        got.append(event)
        done.set()

    dispatcher.add_handler(Ping, on_ping)
    dispatcher.dispatch(frame("PING", {"n": 1}, event_id), client)
    async with asyncio.timeout(HANG_GUARD):
        await done.wait()

    [event] = got
    assert event.event_id == event_id
    assert event == Ping(n=1)
    assert event.to_dict() == {"n": 1}
    assert "PING:abc" not in repr(event)


async def test_every_handler_of_an_event_is_called(client: pyqbot.Client) -> None:
    dispatcher = new_dispatcher()
    seen: list[str] = []
    first_done, second_done = asyncio.Event(), asyncio.Event()

    async def first(event: Ping) -> None:
        seen.append(f"first:{event.n}")
        first_done.set()

    async def second(event: Ping) -> None:
        seen.append(f"second:{event.n}")
        second_done.set()

    dispatcher.add_handler(Ping, first)
    dispatcher.add_handler(Ping, second)
    dispatcher.dispatch(frame("PING", {"n": 7}), client)
    async with asyncio.timeout(HANG_GUARD):
        await asyncio.gather(first_done.wait(), second_done.wait())

    assert sorted(seen) == ["first:7", "second:7"]


async def test_failing_handler_is_logged_and_does_not_affect_the_others(
    client: pyqbot.Client, caplog: pytest.LogCaptureFixture
) -> None:
    dispatcher = new_dispatcher()
    failed, succeeded = asyncio.Event(), asyncio.Event()

    async def broken(event: Ping) -> None:
        failed.set()
        raise ValueError("坏了")

    async def healthy(event: Ping) -> None:
        succeeded.set()

    dispatcher.add_handler(Ping, broken)
    dispatcher.add_handler(Ping, healthy)
    with caplog.at_level(logging.ERROR, logger="pyqbot"):
        dispatcher.dispatch(frame("PING", {"n": 1}), client)
        async with asyncio.timeout(HANG_GUARD):
            await asyncio.gather(failed.wait(), succeeded.wait())

    [record] = caplog.records
    assert record.name == "pyqbot"
    assert record.levelno == logging.ERROR
    message = record.getMessage()
    assert "PING" in message
    assert "broken" in message
    assert "ValueError: 坏了" in message  # traceback 已格式化进文案
    assert record.exc_info is None  # 不交给 logging 打印未脱敏的异常链


async def test_handler_exception_is_redacted_before_logging(
    client: pyqbot.Client, caplog: pytest.LogCaptureFixture
) -> None:
    dispatcher = Dispatcher(redact=lambda text: text.replace("SECRET", "***"))
    failed = asyncio.Event()

    async def leak(event: Ping) -> None:
        failed.set()
        try:
            raise KeyError("原因里有 SECRET")
        except KeyError as exc:
            raise RuntimeError("外层也有 SECRET") from exc

    dispatcher.add_handler(Ping, leak)
    with caplog.at_level(logging.ERROR, logger="pyqbot"):
        dispatcher.dispatch(frame("PING", {"n": 1}), client)
        async with asyncio.timeout(HANG_GUARD):
            await failed.wait()
        await dispatcher.aclose()

    assert "SECRET" not in caplog.text
    assert "原因里有 ***" in caplog.text  # 异常链整条都在、都脱敏了
    assert "外层也有 ***" in caplog.text


async def test_handler_names_never_include_bound_arguments(
    client: pyqbot.Client, caplog: pytest.LogCaptureFixture
) -> None:
    dispatcher = new_dispatcher()
    started, release = asyncio.Event(), asyncio.Event()

    async def fail(secret: str, label: str, event: Ping) -> None:
        started.set()
        await release.wait()
        raise RuntimeError("失败")

    handler = functools.partial(functools.partial(fail, "app-secret-value"), "x")
    dispatcher.add_handler(Ping, handler)
    with caplog.at_level(logging.ERROR, logger="pyqbot"):
        dispatcher.dispatch(frame("PING", {"n": 1}), client)
        async with asyncio.timeout(HANG_GUARD):
            await started.wait()
            [task] = handler_tasks()
            assert task.get_name() == f"pyqbot:PING:{fail.__qualname__}"
            release.set()
            await asyncio.wait([task])

    assert fail.__qualname__ in caplog.text
    assert "app-secret-value" not in caplog.text


class SyncCallable:
    def __init__(self, secret: str) -> None:
        self.secret = secret

    def __repr__(self) -> str:
        return f"SyncCallable({self.secret!r})"

    def __call__(self, event: Ping) -> None: ...


class _NamelessMeta(type):
    # 让类也取不到 __qualname__，走到占位名。
    def __getattribute__(cls, name: str) -> object:
        if name == "__qualname__":
            raise AttributeError(name)
        return super().__getattribute__(name)


class Nameless(SyncCallable, metaclass=_NamelessMeta):
    pass


def sync_with_secret(secret: str, event: Ping) -> None: ...


@pytest.mark.parametrize(
    ("handler", "name"),
    [
        (functools.partial(sync_with_secret, "app-secret-value"), "sync_with_secret"),
        (SyncCallable("app-secret-value"), "SyncCallable"),
        (Nameless("app-secret-value"), "<未命名的处理函数>"),
    ],
    ids=["partial", "callable-object", "nameless"],
)
def test_registration_error_names_the_handler_without_its_arguments(
    handler: object, name: str
) -> None:
    dispatcher = new_dispatcher()

    with pytest.raises(TypeError) as caught:
        dispatcher.add_handler(Ping, handler)  # pyright: ignore[reportArgumentType]  验证运行期检查

    assert name in str(caught.value)
    assert "app-secret-value" not in str(caught.value)


@pytest.mark.parametrize("t", ["PONG", "SOMETHING_NEW", None])
async def test_events_without_handlers_are_ignored_without_decoding(
    client: pyqbot.Client, caplog: pytest.LogCaptureFixture, t: str | None
) -> None:
    dispatcher = new_dispatcher()

    async def on_ping(event: Ping) -> None:
        raise AssertionError("不应被调用")

    dispatcher.add_handler(Ping, on_ping)
    payload = CountingPayload(t)
    with caplog.at_level(logging.DEBUG, logger="pyqbot"):
        dispatcher.dispatch(payload, client)

    assert payload.decoded == 0
    assert handler_tasks() == []
    assert caplog.records == []


async def test_undecodable_event_is_dropped_and_logged(
    client: pyqbot.Client, caplog: pytest.LogCaptureFixture
) -> None:
    dispatcher = new_dispatcher()
    got: list[Ping] = []
    done = asyncio.Event()

    async def on_ping(event: Ping) -> None:
        got.append(event)
        done.set()

    dispatcher.add_handler(Ping, on_ping)
    with caplog.at_level(logging.WARNING, logger="pyqbot"):
        dispatcher.dispatch(frame("PING", {"n": "不是整数"}), client)
        dispatcher.dispatch(frame("PING", ["不是对象"]), client)
    assert handler_tasks() == []

    dispatcher.dispatch(frame("PING", {"n": 2}), client)
    async with asyncio.timeout(HANG_GUARD):
        await done.wait()

    assert got == [Ping(n=2)]
    assert [record.levelno for record in caplog.records] == [logging.WARNING] * 2
    assert all("PING" in record.getMessage() for record in caplog.records)


async def test_dispatch_returns_at_once_while_handlers_are_stuck(client: pyqbot.Client) -> None:
    dispatcher = new_dispatcher()
    started, release, all_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    finished: list[int] = []

    async def slow(event: Ping) -> None:
        started.set()
        await release.wait()
        finished.append(event.n)
        if len(finished) == 2:
            all_finished.set()

    dispatcher.add_handler(Ping, slow)
    dispatcher.dispatch(frame("PING", {"n": 1}), client)
    assert not started.is_set()  # dispatch 只建任务，处理函数还没开始

    async with asyncio.timeout(HANG_GUARD):
        await started.wait()
        dispatcher.dispatch(frame("PING", {"n": 2}), client)  # 第一个卡住时照样立刻返回
        assert len(handler_tasks()) == 2
        release.set()
        await all_finished.wait()

    assert sorted(finished) == [1, 2]


async def test_aclose_cancels_running_handlers_and_leaves_no_tasks(client: pyqbot.Client) -> None:
    dispatcher = new_dispatcher()
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def stuck(event: Ping) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    dispatcher.add_handler(Ping, stuck)
    dispatcher.dispatch(frame("PING", {"n": 1}), client)
    async with asyncio.timeout(HANG_GUARD):
        await started.wait()
        await dispatcher.aclose()

    assert cancelled.is_set()
    assert handler_tasks() == []

    dispatcher.dispatch(frame("PING", {"n": 2}), client)  # 关闭后不再分发
    assert handler_tasks() == []
    await dispatcher.aclose()  # 可以重复调用


async def test_wait_idle_waits_without_cancelling_including_later_events(
    client: pyqbot.Client,
) -> None:
    dispatcher = new_dispatcher()
    started, release = asyncio.Event(), asyncio.Event()
    finished: list[int] = []

    async def slow(event: Ping) -> None:
        started.set()
        await release.wait()
        if event.n == 1:  # 等待期间又来了一条：它也要等
            dispatcher.dispatch(frame("PING", {"n": 2}), client)
        finished.append(event.n)

    dispatcher.add_handler(Ping, slow)
    dispatcher.dispatch(frame("PING", {"n": 1}), client)
    async with asyncio.timeout(HANG_GUARD):
        await started.wait()
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0):  # 限时只结束等待，不取消处理函数
                await dispatcher.wait_idle()
        assert len(handler_tasks()) == 1
        release.set()
        await dispatcher.wait_idle()

    assert finished == [1, 2]
    assert handler_tasks() == []


async def test_wait_idle_from_inside_a_handler_returns_at_once(client: pyqbot.Client) -> None:
    dispatcher = new_dispatcher()
    returned = asyncio.Event()

    async def waits_for_itself(event: Ping) -> None:
        await dispatcher.wait_idle()
        returned.set()

    dispatcher.add_handler(Ping, waits_for_itself)
    dispatcher.dispatch(frame("PING", {"n": 1}), client)
    async with asyncio.timeout(HANG_GUARD):
        await returned.wait()
        await dispatcher.wait_idle()

    assert handler_tasks() == []


async def test_aclose_from_inside_a_handler_only_requests_the_stop(
    client: pyqbot.Client,
) -> None:
    dispatcher = new_dispatcher()
    closed, other_cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def shutdown(event: Ping) -> None:
        await dispatcher.aclose()
        closed.set()

    async def other(event: Ping) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            other_cleaning.set()
            await release.wait()

    dispatcher.add_handler(Ping, other)
    dispatcher.add_handler(Ping, shutdown)
    dispatcher.dispatch(frame("PING", {"n": 1}), client)
    async with asyncio.timeout(HANG_GUARD):
        # other 还卡在清理里，shutdown 的 aclose() 已经返回：处理函数里不等别的处理函数。
        await asyncio.gather(closed.wait(), other_cleaning.wait())
        assert not release.is_set()
        release.set()
        await dispatcher.aclose()

    assert handler_tasks() == []


async def test_concurrent_aclose_waits_for_cleanup_without_cancelling_again(
    client: pyqbot.Client,
) -> None:
    dispatcher = new_dispatcher()
    started, cleaning = asyncio.Event(), asyncio.Event()
    release, cleaned = asyncio.Event(), asyncio.Event()

    async def careful(event: Ping) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()  # 第二次取消会打断这里
            cleaned.set()

    dispatcher.add_handler(Ping, careful)
    dispatcher.dispatch(frame("PING", {"n": 1}), client)
    async with asyncio.timeout(HANG_GUARD):
        await started.wait()  # 在处理函数开始之前取消，就走不到 finally
        first = asyncio.create_task(dispatcher.aclose())
        await cleaning.wait()
        # eager_start：第二次调用同步跑到它挂起为止，该发的取消（如果有）此时已经发出。
        second = asyncio.create_task(dispatcher.aclose(), eager_start=True)
        assert not second.done()
        release.set()
        await asyncio.gather(first, second)

    assert cleaned.is_set()
    assert handler_tasks() == []


async def test_aclose_gives_up_on_handlers_that_swallow_cancellation(
    client: pyqbot.Client, caplog: pytest.LogCaptureFixture
) -> None:
    dispatcher = new_dispatcher()
    started, swallowed, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def stubborn(event: Ping) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            swallowed.set()
            await release.wait()

    dispatcher.add_handler(Ping, stubborn)
    dispatcher.dispatch(frame("PING", {"n": 1}), client)
    async with asyncio.timeout(HANG_GUARD):
        await started.wait()
        with caplog.at_level(logging.WARNING, logger="pyqbot"):
            await dispatcher.aclose(grace_period=0.01)
        assert swallowed.is_set()
        [task] = handler_tasks()  # 关闭已经返回，处理函数还在
        release.set()
        await asyncio.wait([task])

    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert "1 个处理函数" in record.getMessage()


async def test_dispatch_does_not_run_handlers_even_with_an_eager_task_factory(
    client: pyqbot.Client,
) -> None:
    loop = asyncio.get_running_loop()
    loop.set_task_factory(asyncio.eager_task_factory)
    try:
        dispatcher = new_dispatcher()
        started = asyncio.Event()

        async def on_ping(event: Ping) -> None:
            started.set()

        dispatcher.add_handler(Ping, on_ping)
        dispatcher.dispatch(frame("PING", {"n": 1}), client)
        assert not started.is_set()
        async with asyncio.timeout(HANG_GUARD):
            await started.wait()
    finally:
        loop.set_task_factory(None)


async def test_finished_handler_tasks_are_released(client: pyqbot.Client) -> None:
    dispatcher = new_dispatcher()
    started, release = asyncio.Event(), asyncio.Event()

    async def on_ping(event: Ping) -> None:
        started.set()
        await release.wait()

    dispatcher.add_handler(Ping, on_ping)
    dispatcher.dispatch(frame("PING", {"n": 1}), client)
    async with asyncio.timeout(HANG_GUARD):
        await started.wait()
        [task] = handler_tasks()
        task_ref = weakref.ref(task)
        release.set()
        # wait() 的完成回调排在分发器的清理回调之后，返回时清理已经执行。
        await asyncio.wait([task])
    del task
    gc.collect()

    assert task_ref() is None


def test_intents_are_derived_from_the_registered_handlers() -> None:
    dispatcher = new_dispatcher()
    assert dispatcher.intents == pyqbot.Intents(0)

    async def on_ping(event: Ping) -> None: ...

    async def on_pong(event: Pong) -> None: ...

    dispatcher.add_handler(Ping, on_ping)
    dispatcher.add_handler(Ping, on_ping)
    assert dispatcher.intents == pyqbot.Intents.GUILDS

    dispatcher.add_handler(Pong, on_pong)
    assert dispatcher.intents == pyqbot.Intents.GUILDS | pyqbot.Intents.INTERACTION


def test_sync_handler_is_rejected_with_a_hint() -> None:
    dispatcher = new_dispatcher()

    def on_ping(event: Ping) -> None: ...

    with pytest.raises(TypeError, match=r"必须用 async def 定义.*on_ping"):
        dispatcher.add_handler(Ping, on_ping)  # pyright: ignore[reportArgumentType]  验证运行期检查
    assert dispatcher.intents == pyqbot.Intents(0)
