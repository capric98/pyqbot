"""事件分发器：按事件名分发、异常隔离、不阻塞、关闭。"""

import asyncio
import functools
import json
import logging
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
    decoded: int = 0

    def decode_data[T](self, type_: type[T]) -> T:
        self.decoded += 1
        raise AssertionError("不应解码")


def frame(t: str, data: object) -> GatewayPayload:
    return decode_payload(json.dumps({"op": 0, "s": 1, "t": t, "d": data}))


def handler_tasks() -> list[asyncio.Task[object]]:
    """分发器建的、还没结束的任务。"""
    return [task for task in asyncio.all_tasks() if task.get_name().startswith("pyqbot:")]


@pytest.fixture
async def client() -> AsyncGenerator[pyqbot.Client]:
    async with pyqbot.Client("app-id", "app-secret") as client:
        yield client


async def test_events_are_routed_by_name_and_bound_to_the_client(client: pyqbot.Client) -> None:
    dispatcher = Dispatcher()
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


async def test_every_handler_of_an_event_is_called(client: pyqbot.Client) -> None:
    dispatcher = Dispatcher()
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
    dispatcher = Dispatcher()
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
    assert "PING" in record.getMessage()
    assert "broken" in record.getMessage()
    assert record.exc_info is not None
    assert record.exc_info[0] is ValueError


async def test_handler_without_a_qualname_is_logged_by_its_repr(
    client: pyqbot.Client, caplog: pytest.LogCaptureFixture
) -> None:
    dispatcher = Dispatcher()
    failed = asyncio.Event()

    async def fail(reason: str, event: Ping) -> None:
        failed.set()
        raise RuntimeError(reason)

    dispatcher.add_handler(Ping, functools.partial(fail, "原因"))
    with caplog.at_level(logging.ERROR, logger="pyqbot"):
        dispatcher.dispatch(frame("PING", {"n": 1}), client)
        async with asyncio.timeout(HANG_GUARD):
            await failed.wait()

    [record] = caplog.records
    assert "functools.partial" in record.getMessage()


@pytest.mark.parametrize("t", ["PONG", "SOMETHING_NEW", None])
async def test_events_without_handlers_are_ignored_without_decoding(
    client: pyqbot.Client, caplog: pytest.LogCaptureFixture, t: str | None
) -> None:
    dispatcher = Dispatcher()

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
    dispatcher = Dispatcher()
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
    dispatcher = Dispatcher()
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
    dispatcher = Dispatcher()
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


async def test_aclose_from_inside_a_handler_does_not_cancel_the_caller(
    client: pyqbot.Client,
) -> None:
    dispatcher = Dispatcher()
    closed = asyncio.Event()
    other_cancelled = asyncio.Event()

    async def shutdown(event: Ping) -> None:
        await dispatcher.aclose()
        closed.set()

    async def other(event: Ping) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            other_cancelled.set()
            raise

    dispatcher.add_handler(Ping, other)
    dispatcher.add_handler(Ping, shutdown)
    dispatcher.dispatch(frame("PING", {"n": 1}), client)
    async with asyncio.timeout(HANG_GUARD):
        await closed.wait()

    assert other_cancelled.is_set()
    assert handler_tasks() == []


def test_intents_are_derived_from_the_registered_handlers() -> None:
    dispatcher = Dispatcher()
    assert dispatcher.intents == pyqbot.Intents(0)

    async def on_ping(event: Ping) -> None: ...

    async def on_pong(event: Pong) -> None: ...

    dispatcher.add_handler(Ping, on_ping)
    dispatcher.add_handler(Ping, on_ping)
    assert dispatcher.intents == pyqbot.Intents.GUILDS

    dispatcher.add_handler(Pong, on_pong)
    assert dispatcher.intents == pyqbot.Intents.GUILDS | pyqbot.Intents.INTERACTION


def test_sync_handler_is_rejected_with_a_hint() -> None:
    dispatcher = Dispatcher()

    def on_ping(event: Ping) -> None: ...

    with pytest.raises(TypeError, match=r"必须用 async def 定义.*on_ping"):
        dispatcher.add_handler(Ping, on_ping)  # pyright: ignore[reportArgumentType]  验证运行期检查
    assert dispatcher.intents == pyqbot.Intents(0)
