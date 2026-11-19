"""引用索引与流式消息的实测：要测试用户在单聊里引用机器人的消息，再由人确认客户端里的效果。

要回答的问题（结论记进 `docs/errata.md`）：

- 引用消息到达时 `message_type` 是不是 103；`message_scene.ext` 里的 `ref_msg_idx` 是否等于被引用消息的
  `msg_idx`（用户的消息）或发送结果的 `ext_info.ref_idx`（机器人的消息）；`msg_elements[].msg_idx` 给不给、
  与 `ref_msg_idx` 是否一致。
- 流式消息的哪些分片响应带 `ext_info.ref_idx`，引用流式消息时 `ref_msg_idx` 对应哪一个。
- 同一条用户消息能否先后被动回复两条流式消息；流式消息能否用 `stream_msg_id` 撤回，2 分钟的撤回时限从哪一片算起。

运行前提见 `AGENTS.md`「实测」：每次都要先取得用户同意；每个用例消耗一次网关连接，所以还要 `LIVE_GATEWAY=1`。
`LIVE_WAIT_SECONDS`（默认 600）是连上网关后等测试用户操作完的秒数。运行方式：
`LIVE_GATEWAY=1 uv run --env-file .env pytest -m live --no-cov tests/live/test_live_quote.py::<用例> -s --log-cli-level=WARNING`。

结论追加到 `.cache/live/quote.txt`，收到的引用消息（`to_dict()`，去掉 `auth_token`）存进 `.cache/live/raw/`；
两处都含 openid，已被 git 忽略、只留在本机。
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import pytest

import pyqbot

pytestmark = pytest.mark.live

OUTPUT = Path(__file__).parents[2] / ".cache" / "live" / "quote.txt"
RAW_DIR = OUTPUT.parent / "raw"
RECALL_WINDOW = 120  # 秒：文档说的撤回时限
_logger = logging.getLogger("pyqbot.live")


@pytest.fixture
def openid() -> str:
    value = os.environ.get("TEST_USER_OPENID")
    if not value:
        pytest.skip("缺少环境变量 TEST_USER_OPENID：用 uv run --env-file .env 运行")
    return value


@pytest.fixture
def wait_seconds() -> float:
    if os.environ.get("LIVE_GATEWAY") != "1":
        pytest.skip("需要显式设置 LIVE_GATEWAY=1：每个用例消耗一次网关连接")
    return float(os.environ.get("LIVE_WAIT_SECONDS", "600"))


def note(title: str, value: object) -> None:
    line = f"{title}: {json.dumps(value, ensure_ascii=False, default=str)}"
    _logger.warning("%s", line)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("a", encoding="utf-8") as report:
        report.write(line + "\n")


def keep_raw(name: str, message: pyqbot.C2CMessage) -> None:
    data = message.to_dict()
    if (scene := message.message_scene) is not None:  # auth_token 是鉴权令牌，不落盘
        ext = [item for item in scene.ext if not item.startswith("auth_token=")]
        data["message_scene"] = {"source": scene.source, "ext": ext}
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    (RAW_DIR / f"quote_{name}.json").write_text(text, encoding="utf-8")


def describe_quote(message: pyqbot.C2CMessage, known: dict[str, str]) -> dict[str, object]:
    """一条引用消息里与引用有关的字段，以及 `ref_msg_idx`、`msg_elements[].msg_idx` 对上的是哪条消息。"""
    elements = [
        {
            "msg_idx": element.msg_idx,
            "matches": known.get(element.msg_idx or ""),
            "message_type": element.message_type,
            "content": (element.content or "")[:40],
            "author_is_bot": element.author.bot if element.author else None,
        }
        for element in message.msg_elements
    ]
    return {
        "content": message.content,
        "message_type": message.message_type,
        "msg_idx": message.msg_idx,
        "ref_msg_idx": message.ref_msg_idx,
        "ref_matches": known.get(message.ref_msg_idx or ""),
        "msg_elements": elements,
    }


async def stream_with_indices(
    message: pyqbot.C2CMessage, label: str, pieces: tuple[str, ...]
) -> tuple[pyqbot.StreamMessage, list[dict[str, object]]]:
    """逐片发出（`coalesce=False`），记下每个分片响应的 `id` 与 `ext_info.ref_idx`。"""
    chunks: list[dict[str, object]] = []
    stream = message.reply_stream(coalesce=False)

    def record(index: int) -> None:
        sent = stream.last_sent
        if sent is not None:
            ref_idx = sent.ext_info.ref_idx if sent.ext_info else None
            chunks.append({"chunk": index, "id": sent.id, "ref_idx": ref_idx})

    async with stream:
        for index, piece in enumerate(pieces):
            await stream.append(piece)
            record(index)
            await asyncio.sleep(0.5)
    record(len(pieces))  # 结束分片
    note(
        f"{label}.stream",
        {
            "stream_msg_id": stream.stream_msg_id,
            "ref_idx": stream.ref_idx,
            "sent_text": stream.sent_text,
            "chunks": chunks,
        },
    )
    return stream, chunks


async def run_until_closed(
    bot: pyqbot.Bot, wait_seconds: float, outcome: dict[str, object]
) -> None:
    async with bot:
        try:
            async with asyncio.timeout(wait_seconds):
                await bot.start()
        except TimeoutError:
            outcome["timeout"] = f"{wait_seconds} 秒内没有等到测试用户操作完"


async def test_quote_indices_and_two_streams(
    app_id: str, app_secret: str, openid: str, wait_seconds: float
) -> None:
    """测试用户发「开始」，机器人被动回复普通消息 A、流式消息 B、第二条流式消息 C。

    然后测试用户依次引用 A、B、C 和自己发的「开始」，每次随便写一句；全部引用完发「结束」。
    机器人对每条引用回一句它对上了哪条，收到「结束」后用 `stream_msg_id` 撤回 C。
    应看到：A、B、C 三条都出现（C 被拒时错误码记进 `quote.txt`）；每条引用都以引用样式显示；最后 C 被撤回。
    """
    bot = pyqbot.Bot(app_id, app_secret)
    outcome: dict[str, object] = {}
    known: dict[str, str] = {}  # 引用索引 → 哪条消息
    streams: dict[str, pyqbot.StreamMessage] = {}
    quotes: list[dict[str, object]] = []

    @bot.on_c2c_message
    async def on_message(message: pyqbot.C2CMessage) -> None:
        if message.user_openid != openid:
            return
        text = message.content.strip()
        if text == "开始" and "A" not in outcome:
            await begin(message)
        elif text == "结束" and "A" in outcome:
            await finish(message)
        elif "A" in outcome:
            name = f"{len(quotes) + 1}"
            keep_raw(name, message)
            quote = describe_quote(message, known)
            quotes.append(quote)
            note(f"quote.{name}", quote)
            await message.reply(f"pyqbot：第 {name} 条引用，对上了 {quote['ref_matches']}")

    async def begin(message: pyqbot.C2CMessage) -> None:
        if message.msg_idx:
            known[message.msg_idx] = "「开始」"
        sent = await message.reply(
            "A：普通消息。请依次引用 A、B、C 和你发的「开始」，每次随便写一句；全部引用完发「结束」。"
        )
        ref_idx = sent.ext_info.ref_idx if sent.ext_info else None
        if ref_idx:
            known[ref_idx] = "A"
        outcome["A"] = {"id": sent.id, "ref_idx": ref_idx}
        note("A", outcome["A"])
        for label in ("B", "C"):
            pieces = (f"{label}：流式消息，", "分三片发出，", f"请引用我（{label}）。")
            try:
                stream, chunks = await stream_with_indices(message, label, pieces)
            except pyqbot.QQBotError as error:
                outcome[label] = {"err_code": error.err_code, "message": error.message}
                note(label, outcome[label])
                continue
            streams[label] = stream
            outcome[label] = stream.stream_msg_id
            for chunk in chunks:
                if isinstance(chunk["ref_idx"], str):
                    known.setdefault(chunk["ref_idx"], f"{label} 的第 {chunk['chunk']} 片")
            if stream.stream_msg_id:
                known.setdefault(stream.stream_msg_id, f"{label} 的 stream_msg_id")

    async def finish(message: pyqbot.C2CMessage) -> None:
        stream = streams.get("C")
        if stream is None or stream.stream_msg_id is None:
            outcome["recall"] = "没有 C 可撤回"
        else:
            try:
                await bot.users.recall_message(openid, stream.stream_msg_id)
                outcome["recall"] = "被接受"
                await message.reply("pyqbot：已用 stream_msg_id 撤回 C，请确认 C 已经不见了")
            except pyqbot.QQBotError as error:
                outcome["recall"] = {"err_code": error.err_code, "message": error.message}
        note("recall_C", outcome["recall"])
        await bot.close()

    await run_until_closed(bot, wait_seconds, outcome)

    note("quote_indices_and_two_streams", outcome | {"quotes": quotes})
    assert quotes, outcome


async def test_stream_recall_window(
    app_id: str, app_secret: str, openid: str, wait_seconds: float
) -> None:
    """测试用户发「撤回时限」，机器人用一条流式消息 D 回复，持续约 100 秒（每 20 秒一片）。

    第一片发出约 130 秒后（已过 2 分钟，离最后一片才约 30 秒）用 `stream_msg_id` 撤回 D：被接受说明时限
    从最后一片或结束分片算起，被拒说明从第一片算起（错误码记进 `quote.txt`）。共约 2 分半钟。
    应看到：D 逐段出现、结束，然后（撤回被接受时）消失。
    """
    bot = pyqbot.Bot(app_id, app_secret)
    outcome: dict[str, object] = {}
    loop = asyncio.get_running_loop()

    @bot.on_c2c_message
    async def on_message(message: pyqbot.C2CMessage) -> None:
        if message.user_openid != openid or message.content.strip() != "撤回时限":
            return
        stream = message.reply_stream(coalesce=False)
        async with stream:
            await stream.append("D：撤回时限实测，")
            first = loop.time()
            for second in range(20, 101, 20):
                await asyncio.sleep(first + second - loop.time())
                await stream.append(f"第 {second} 秒，")
            await stream.append("结束。")
        last = loop.time()
        await asyncio.sleep(first + RECALL_WINDOW + 10 - loop.time())
        timing = {
            "since_first_chunk": round(loop.time() - first, 1),
            "since_last_chunk": round(loop.time() - last, 1),
        }
        assert stream.stream_msg_id is not None
        try:
            await bot.users.recall_message(openid, stream.stream_msg_id)
            outcome["recall"] = timing | {"result": "被接受"}
        except pyqbot.QQBotError as error:
            outcome["recall"] = timing | {"err_code": error.err_code, "message": error.message}
        note("recall_window", outcome["recall"])
        await bot.close()

    await run_until_closed(bot, wait_seconds, outcome)

    note("stream_recall_window", outcome)
    assert "recall" in outcome, outcome
