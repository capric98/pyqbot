"""单聊的流式消息：一条消息分多个分片发出。分片的填法与异常时的行为见 `docs/design.md`。"""

import asyncio
import logging
from types import TracebackType
from typing import Self

from .._errors import QQBotError
from .._http import HTTP
from .._models.event import C2CReplyTarget, reply_fields
from .._models.stream import SentStreamChunk, StreamContentType, StreamInputMode, StreamInputState

_logger = logging.getLogger("pyqbot")


class StreamMessage:
    """一条正在发送的流式消息，由 `client.users.stream_message()` 或 `message.reply_stream()` 创建。

    推荐用 `async with`：正常退出时发出结束分片；体内抛出异常时也会尽量发出结束分片，
    免得用户那边一直显示「生成中」，然后原样抛出该异常（被取消时不发）。
    不用 `async with` 时，发完后自己调用 `finish()`。

    默认合并分片（`coalesce=True`）：每个分片要等上一个的响应（约一次网络往返）才能发，所以上一片还在
    发送时，之后 `append()` / `replace()` 的内容先攒着，等它回来再合成一片发出，同时只有一个请求在路上。
    这时 `append()` / `replace()` 不等发送就返回；分片发送失败（包括客户端已关闭）在下一次 `append()` /
    `replace()` / `finish()`（含正常退出 `async with`）时抛出。`coalesce=False` 时每次调用发出一个分片、
    等它发完才返回，失败当场抛出。两种方式下分片都按调用顺序发出。

    分片发送失败（抛 `APIError` / `NetworkError`）后，平台那边的状态无从得知，这条流式消息就此终止：
    失败抛出过一次之后，`append()` / `replace()` 抛 `RuntimeError`，退出 `async with` 时也不再发结束分片。

    Example:
        ```python
        async with message.reply_stream() as stream:
            async for piece in llm():
                await stream.append(piece)
        ```
    """

    def __init__(
        self,
        http: HTTP,
        path: str,
        reply_to: C2CReplyTarget,
        content_type: StreamContentType,
        *,
        coalesce: bool = True,
    ) -> None:
        self._http = http
        self._path = path
        self._reply_to = reply_to
        self._content_type = content_type
        self._reply: dict[str, object] | None = None
        self._index = 0
        self._stream_msg_id: str | None = None
        self._last_sent: SentStreamChunk | None = None
        self._finished = False
        self._failed = False
        self._lock = asyncio.Lock()
        self._coalesce = coalesce
        self._pending: tuple[StreamInputMode, str] | None = None  # 合并模式下还没发出的内容
        self._sender: asyncio.Task[None] | None = None
        self._error: Exception | None = None  # 合并模式下发送失败、还没抛给调用方的异常

    @property
    def stream_msg_id(self) -> str | None:
        """这条流式消息的 ID，第一个分片发出之前为 `None`。"""
        return self._stream_msg_id

    @property
    def last_sent(self) -> SentStreamChunk | None:
        """最近一个分片的发送结果（含 `remain_msg_len`），还没发过时为 `None`。"""
        return self._last_sent

    @property
    def finished(self) -> bool:
        """是否已经结束（发过结束分片、调用过 `finish()`，或分片发送失败）。"""
        return self._finished or self._failed

    async def append(self, text: str) -> None:
        """把 `text` 接在已发内容的后面。`text` 为空串时什么也不发。

        Raises:
            APIError: 平台拒绝分片，如超出频率限制（`err_code` 50002）；合并模式下是之前某一片的失败。
            NetworkError: 没有拿到平台的响应；合并模式下同上。
            ValueError: 被动回复的对象是没有事件 ID 的事件。
            RuntimeError: 已经结束，或客户端已关闭。
        """
        self._check_open()
        if text:
            await self._submit(StreamInputMode.APPEND, text)

    async def replace(self, text: str) -> None:
        """把正文整体换成 `text`：`text` 是到目前为止的全文，必须以用户已经看到的内容开头。

        适合手里只有全文、没有增量的场景；可以与 `append()` 混用。

        Raises:
            APIError: 平台拒绝分片，如改动了已下发的开头（`err_code` 40007）；合并模式下也可能是之前某一片的失败。
            NetworkError: 没有拿到平台的响应；合并模式下同上。
            ValueError: 被动回复的对象是没有事件 ID 的事件。
            RuntimeError: 已经结束，或客户端已关闭。
        """
        self._check_open()
        await self._submit(StreamInputMode.REPLACE, text)

    async def finish(self) -> None:
        """等攒着的内容发完，再发出结束分片，之后不能再追加内容。可以重复调用；一个分片也没发过时不发请求。

        Raises:
            APIError: 平台拒绝结束分片，或合并模式下之前某一片发送失败。
            NetworkError: 没有拿到平台的响应。
            RuntimeError: 客户端已关闭。
        """
        if self._sender is not None:
            # shield：调用方被取消时，正在发的分片照常发完，不把这条流打成「失败」。
            await asyncio.shield(self._sender)
        self._raise_unreported()
        await self._send(StreamInputMode.APPEND, "", StreamInputState.DONE)

    async def __aenter__(self) -> Self:
        """进入 `async with`。

        Raises:
            RuntimeError: 已经结束。
        """
        self._check_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_value is None:
            await self.finish()
        elif isinstance(exc_value, Exception):
            # 取消等 BaseException 不发：此时再等一次网络请求会拖住取消。攒着的内容由发送任务照常发完。
            try:
                await self.finish()
            except (QQBotError, RuntimeError) as exc:  # 不能盖过体内的异常；文案已脱敏
                _logger.warning("流式消息没有正常结束：%s", exc)

    def _check_open(self) -> None:
        self._raise_unreported()
        if self._failed:
            raise RuntimeError("流式消息的分片发送失败，已经终止，不能再追加内容")
        if self._finished:
            raise RuntimeError("流式消息已经结束，不能再追加内容")

    def _raise_unreported(self) -> None:
        """合并模式下发送失败的异常只抛一次，之后按「已终止」处理。"""
        if self._error is not None:
            error, self._error = self._error, None
            raise error

    async def _submit(self, mode: StreamInputMode, text: str) -> None:
        if not self._coalesce:
            await self._send(mode, text, StreamInputState.GENERATING)
            return
        if self._reply is None:
            self._reply = reply_fields(self._reply_to)  # 用法错误当场抛，不留到发送任务里
        pending = self._pending
        if mode == StreamInputMode.REPLACE or pending is None:
            self._pending = (mode, text)
        else:  # 接在攒着的内容后面；攒着的是 replace 时，合起来仍是一次 replace
            self._pending = (pending[0], pending[1] + text)
        if self._sender is None or self._sender.done():
            self._sender = asyncio.create_task(self._send_pending(), name="pyqbot:stream")

    async def _send_pending(self) -> None:
        while self._pending is not None:
            mode, text = self._pending
            self._pending = None
            try:
                await self._send(mode, text, StreamInputState.GENERATING)
            except Exception as exc:  # noqa: BLE001  留给下一次调用抛出，见类的 docstring
                self._error = exc
                self._pending = None
                return

    async def _send(self, mode: StreamInputMode, text: str, state: StreamInputState) -> None:
        async with self._lock:
            if state == StreamInputState.DONE:
                if self.finished:
                    return
                if self._index == 0:
                    self._finished = True
                    return
            # 排队等锁期间，别的调用可能已经结束了这条消息。
            self._check_open()
            if self._reply is None:
                # 各分片共用同一组 msg_id / event_id 与 msg_seq，只在第一个分片时取一次。
                self._reply = reply_fields(self._reply_to)
            body: dict[str, object] = {
                "input_mode": mode,
                "input_state": state,
                "index": self._index,
                "content_type": self._content_type,
                "content_raw": text,
                **self._reply,
            }
            if self._stream_msg_id is not None:
                body["stream_msg_id"] = self._stream_msg_id
            self._index += 1
            if state == StreamInputState.DONE:
                self._finished = True
            try:
                sent = await self._http.request(
                    "POST", self._path, type_=SentStreamChunk, json=body
                )
            except BaseException:
                self._failed = True
                raise
            if self._stream_msg_id is None:
                self._stream_msg_id = sent.id
            self._last_sent = sent
