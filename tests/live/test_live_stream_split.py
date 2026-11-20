"""流式消息「自动分条」的实测：很长的流式消息在客户端显示成几条气泡，测清楚平台按什么拆、拆在哪。

要回答的问题（结论记进 `docs/errata.md`）：

- 按什么触发：Markdown 原文的字符数、UTF-8 字节数、时长还是分片数。
- 拆在哪里：硬切还是落在分片、段落边界；切进代码块、表格时两边的渲染。
- 分片响应里有没有信号：拆开前后 `id`、`ext_info.ref_idx`、`timestamp`、`remain_msg_len` 的变化，以及文档外的字段。
- 引用拆出的气泡时 `ref_msg_idx` 是哪个；拆出的气泡占不占被动回复次数。
- 有没有硬上限：多长时分片被拒、报什么错误码。

测试用户在单聊里发指令（发「帮助」可看 `HELP`），机器人逐片（`coalesce=False`）流式回复这条指令。正文是编号
段落，每段 100 字（含末尾空行），第 k 段从原文第 (k-1)×100 字开始；段内是循环的「一二三…十」或「abc…j」，
方便从气泡的开头读出位置。每片默认 137 字，与段长互质，看拆分点落在分片边界、段落边界还是任意位置。

流式消息发完后，测试用户引用拆出的第二条气泡（只有一条就引用它），写上看到的气泡数，可加备注；机器人用被引用
的内容在原文里定位拆分点，被动回复这条引用一句小结。指令那条消息只收到流式消息本身，留给「配额」用。

运行前提见 `AGENTS.md`「实测」：每次都要先取得用户同意；消耗一次网关连接，所以还要 `LIVE_GATEWAY=1`。
`LIVE_WAIT_SECONDS`（默认 3600）是连上网关后等测试用户操作完的秒数。运行方式：
`LIVE_GATEWAY=1 uv run --env-file .env pytest -m live --no-cov tests/live/test_live_stream_split.py -s --log-cli-level=WARNING`。

小结追加到 `.cache/live/split.txt`，每条流式消息逐片的响应存进 `.cache/live/raw/split_<运行时间>_<序号>.json`，
收到的引用消息存进 `.cache/live/raw/split_<运行时间>_quote_<序号>.json`；含消息索引与 openid，已被 git 忽略、只留在本机。
"""

import asyncio
import json
import logging
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import cast

import httpx2
import pytest

import pyqbot
from pyqbot._redact import redact

pytestmark = pytest.mark.live

OUTPUT = Path(__file__).parents[2] / ".cache" / "live" / "split.txt"
RAW_DIR = OUTPUT.parent / "raw"
RUN = time.strftime("%Y%m%d-%H%M%S")  # 每次运行的序号都从 1 起，文件名带上运行时间免得覆盖
PARAGRAPH = 100
DEFAULT_PIECE = 137
MAX_CHARS = 60000  # 防手误；硬上限要单独发「快 30000 1000」这类指令去试
MAX_PIECES = 2000
MAX_SECONDS = 900
QUOTA_TRIES = 6
MAX_SEQUENCE = 12
FORMAT_TOTAL = 9000  # 各种语法都超过 15000 字节
FORMAT_PIECE = 60  # 格式用例切得细一些，拆分点的字节数误差在 180 以内
FILLER = "一二三四五六七八九十"
LINK = "https://www.qq.com"
DOCUMENTED_FIELDS = {"id", "timestamp", "ext_info", "remain_msg_len"}
_logger = logging.getLogger("pyqbot.live")

HELP = """pyqbot 分条实测，可用的指令：
快 字数 [每片字数]：中文，不停顿
英 字数 [每片字数]：ASCII，不停顿
慢 字数 秒数：中文，约每 10 秒一片
碎 字数 每片字数：中文，很多小片，不停顿
代码 位置 / 表格 位置：中文段落中间插一个约 600 字的代码块 / 表格，横跨这个位置
格式 种类 [字数] [每片字数]：整条都是某种 Markdown 语法，种类为 加粗、列表、标题、链接、表格、混合
配额：对上一条流式消息回复的那条指令，再被动回复普通消息直到被拒
序号 [次数]：同上，但被拒也继续，看哪些 msg_seq 已被占用
结束：断开
每条流式消息发完后，引用拆出的第二条气泡（只有一条就引用它），写上看到几条气泡，可再加备注。"""


@dataclass
class Chunk:
    """一个分片发出后的状态：到这一片为止发了多少，平台的响应里各字段的值。"""

    index: int
    chars: int
    bytes: int
    seconds: float
    id: str | None
    ref_idx: str | None
    timestamp: str | None
    remain_msg_len: int | None
    extra: dict[str, object]


@dataclass
class Experiment:
    number: int
    label: str
    text: str
    trigger: pyqbot.C2CMessage
    piece: int
    marks: dict[str, int] = field(default_factory=dict[str, int])
    chunks: list[Chunk] = field(default_factory=list[Chunk])
    error: dict[str, object] | None = None
    seconds: float = 0.0


@pytest.fixture
def openid() -> str:
    value = os.environ.get("TEST_USER_OPENID")
    if not value:
        pytest.skip("缺少环境变量 TEST_USER_OPENID：用 uv run --env-file .env 运行")
    return value


@pytest.fixture
def wait_seconds() -> float:
    if os.environ.get("LIVE_GATEWAY") != "1":
        pytest.skip("需要显式设置 LIVE_GATEWAY=1：用例消耗一次网关连接")
    return float(os.environ.get("LIVE_WAIT_SECONDS", "3600"))


def note(title: str, value: object) -> None:
    line = f"{title}: {json.dumps(value, ensure_ascii=False, default=str)}"
    _logger.warning("%s", line)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("a", encoding="utf-8") as report:
        report.write(line + "\n")


def keep_raw(name: str, value: object) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    (RAW_DIR / f"split_{RUN}_{name}.json").write_text(text, encoding="utf-8")


def paragraphs(first: int, total: int, *, ascii_only: bool = False) -> str:
    """从第 `first` 段起的编号段落，截到 `total` 字。"""
    filler = "abcdefghij" if ascii_only else "一二三四五六七八九十"
    body_length = PARAGRAPH - len("0001 ") - len("\n\n")
    body = (filler * (body_length // len(filler) + 1))[:body_length]
    parts: list[str] = []
    length = 0
    number = first
    while length < total:
        part = f"{number:04d} {body}\n\n"
        parts.append(part)
        length += len(part)
        number += 1
    return "".join(parts)[:total]


def with_block(kind: str, around: int) -> tuple[str, dict[str, int]]:
    """在中文段落中间插一个代码块或表格，让它横跨第 `around` 字；返回全文与块的起止位置。"""
    before = paragraphs(1, max(0, (around - 300) // PARAGRAPH * PARAGRAPH))
    rows = range(1, 18)
    if kind == "代码":
        lines = "".join(
            f"c{row:03d} 一二三四五六七八九十一二三四五六七八九十一二三四五六七八\n" for row in rows
        )
        block = f"```text\n{lines}```\n\n"
    else:
        lines = "".join(
            f"| r{row:03d} | 一二三四五六七八九十一二三四五六七八九十一二三四五六 |\n"
            for row in rows
        )
        block = f"| 行 | 内容 |\n| --- | --- |\n{lines}\n"
    after = paragraphs(len(before) // PARAGRAPH + 1, 1000)
    start = len(before)
    return before + block + after, {"block_start": start, "block_end": start + len(block)}


def format_unit(kind: str, number: int) -> str:
    """`formatted()` 的一段：带编号，只用一种 Markdown 语法（混合的仿大模型回答）。"""
    n = f"{number:04d}"
    match kind:
        case "加粗":
            return f"{n} " + "一二三**四五六七**八九十" * 6 + "\n\n"
        case "列表":
            return f"- {n} {FILLER * 3}\n"
        case "标题":
            return f"### {n} {FILLER}\n\n{FILLER * 5}\n\n"
        case "链接":
            return f"{n} [{FILLER}]({LINK}/{n}) {FILLER * 3}\n\n"
        case "表格":
            return f"| {n} | {FILLER} | {FILLER * 2} |\n"
        case "混合":
            return (
                f"## {n} 小节\n\n{FILLER}**{FILLER}**{FILLER}`code_{n}`{FILLER}\n\n"
                f"- {FILLER}\n- **{FILLER}**\n- [{FILLER}]({LINK}/{n})\n\n> {FILLER * 2}\n\n"
                f"| 甲 | 乙 |\n| --- | --- |\n| {FILLER} | {FILLER} |\n\n"
            )
        case _:
            raise ValueError("种类只能是 加粗、列表、标题、链接、表格、混合")


def formatted(kind: str, total: int) -> str:
    """整条都用 `kind` 这种 Markdown 语法的中文，截到 `total` 字。"""
    parts = ["| 编号 | 甲 | 乙 |\n| --- | --- | --- |\n"] if kind == "表格" else []
    length = sum(map(len, parts))
    number = 1
    while length < total:
        parts.append(format_unit(kind, number))
        length += len(parts[-1])
        number += 1
    return "".join(parts)[:total]


def plan(command: str, args: list[str]) -> tuple[str, int, float, dict[str, int]]:
    """按指令给出正文、每片字数、片间停顿（秒）与要记下的位置。"""
    marks: dict[str, int] = {}
    interval = 0.0
    if command == "格式" and args:
        kind, *rest = args
        total, piece = ([int(arg) for arg in rest] + [FORMAT_TOTAL, FORMAT_PIECE][len(rest) :])[:2]
        return check(formatted(kind, total), piece), piece, interval, marks
    numbers = [int(arg) for arg in args]
    match command, numbers:
        case "快" | "英", [total]:
            text, piece = paragraphs(1, total, ascii_only=command == "英"), DEFAULT_PIECE
        case "快" | "英", [total, piece]:
            text = paragraphs(1, total, ascii_only=command == "英")
        case "慢", [total, seconds] if 0 < seconds <= MAX_SECONDS:
            count = max(1, round(seconds / 10))
            text, piece, interval = paragraphs(1, total), math.ceil(total / count), seconds / count
        case "碎", [total, piece]:
            text = paragraphs(1, total)
        case "代码" | "表格", [around]:
            (text, marks), piece = with_block(command, around), DEFAULT_PIECE
        case _:
            raise ValueError("参数不对")
    return check(text, piece), piece, interval, marks


def check(text: str, piece: int) -> str:
    if not 0 < len(text) <= MAX_CHARS or piece <= 0 or len(text) / piece > MAX_PIECES:
        raise ValueError(f"字数要在 1～{MAX_CHARS}，分片数不超过 {MAX_PIECES}")
    return text


def as_json_object(value: object) -> dict[str, object] | None:
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def chunk_record(
    index: int, sent_text: str, seconds: float, stream: pyqbot.StreamMessage, body: object
) -> Chunk:
    sent = stream.last_sent
    raw = as_json_object(body)
    extra = {k: v for k, v in raw.items() if k not in DOCUMENTED_FIELDS} if raw else {"body": body}
    return Chunk(
        index=index,
        chars=len(sent_text),
        bytes=len(sent_text.encode()),
        seconds=round(seconds, 2),
        id=sent.id if sent else None,
        ref_idx=sent.ext_info.ref_idx if sent and sent.ext_info else None,
        timestamp=sent.timestamp.isoformat() if sent and sent.timestamp else None,
        remain_msg_len=sent.remain_msg_len if sent else None,
        extra=extra,
    )


def summarize(experiment: Experiment) -> dict[str, object]:
    """逐片响应里有变化的地方：`id`、`ref_idx` 换成新值的分片，`remain_msg_len` 的取值，文档外的字段。"""
    changes: list[dict[str, object]] = []
    previous: dict[str, str] = {}
    remains: dict[str, list[int]] = {}
    extra_keys: set[str] = set()
    for chunk in experiment.chunks:
        for key, value in (("id", chunk.id), ("ref_idx", chunk.ref_idx)):
            if value is not None and value != previous.get(key):
                if key in previous:
                    changes.append({"field": key, "chunk": chunk.index, "chars": chunk.chars})
                previous[key] = value
        remains.setdefault(str(chunk.remain_msg_len), []).append(chunk.index)
        extra_keys.update(chunk.extra)
    return {
        "number": experiment.number,
        "label": experiment.label,
        "chars": len(experiment.text),
        "bytes": len(experiment.text.encode()),
        "piece": experiment.piece,
        "chunks": len(experiment.chunks),
        "seconds": round(experiment.seconds, 1),
        "marks": experiment.marks,
        "id_or_ref_changes": changes,
        "remain_msg_len": {value: [ids[0], ids[-1], len(ids)] for value, ids in remains.items()},
        "extra_fields": sorted(extra_keys),
        "error": experiment.error,
    }


def locate(text: str, quoted: str) -> int | None:
    """被引用的气泡从原文第几个字开始：先用它的开头在原文里找，找不到再按里面第一个段落编号估算。"""
    if (offset := text.find(quoted[:150])) >= 0:
        return offset
    if numbers := re.findall(r"(?m)^(\d{4}) ", quoted):
        return text.find(f"{numbers[0]} ")
    return None


async def test_stream_auto_split(
    app_id: str, app_secret: str, openid: str, wait_seconds: float
) -> None:
    """测试用户按 `HELP` 发指令，每条流式消息发完引用拆出的第二条气泡、写上气泡数；全部做完发「结束」。

    建议的顺序：`快 8000` → `英 8000` → `慢 1200 300` → `碎 2000 4` → `配额`（对一条没拆开的）→
    `快 8000` 后 `配额`（对拆开的）→ 按测出的位置发 `代码`、`表格` → `快 30000 1000` 试硬上限。
    """
    outcome: dict[str, object] = {}
    experiments: list[Experiment] = []
    known: dict[str, str] = {}  # 引用索引、消息 ID → 第几次的哪个值
    reports: list[pyqbot.C2CMessage] = []
    responses: list[object] = []  # 当前分片的原始响应体，由钩子填
    busy = asyncio.Lock()
    loop = asyncio.get_running_loop()

    async def keep_stream_response(response: httpx2.Response) -> None:
        if not response.request.url.path.endswith("/stream_messages"):
            return
        await response.aread()
        token = response.request.headers.get("Authorization", "").removeprefix("QQBot ")
        text = redact(response.text, app_secret, token)  # 钩子在 SDK 脱敏之前拿到响应
        try:
            responses.append(json.loads(text))
        except ValueError:
            responses.append(text)

    limits = httpx2.Limits(keepalive_expiry=60)  # 同 SDK 自建的客户端
    hooks = {"response": [keep_stream_response]}
    async with httpx2.AsyncClient(event_hooks=hooks, limits=limits) as http_client:
        bot = pyqbot.Bot(app_id, app_secret, http_client=http_client)

        @bot.on_c2c_message
        async def on_message(message: pyqbot.C2CMessage) -> None:
            if message.user_openid != openid:
                return
            text = message.content.strip()
            if not text:
                return
            if message.message_type == pyqbot.ReceivedMessageType.QUOTE or text[:1].isdigit():
                await report(message, text)
                return
            command, *args = text.split()
            match command:
                case "帮助":
                    await message.reply(HELP)
                case "快" | "英" | "慢" | "碎" | "代码" | "表格" | "格式":
                    await experiment(message, command, args)
                case "配额":
                    await quota(message)
                case "序号":
                    await sequence(message, args)
                case "结束":
                    outcome["finished"] = True
                    await bot.close()
                case _:
                    pass

        async def experiment(message: pyqbot.C2CMessage, command: str, args: list[str]) -> None:
            try:
                text, piece, interval, marks = plan(command, args)
            except ValueError as error:
                await message.reply(f"pyqbot：{error}。{HELP}")
                return
            if busy.locked():
                await message.reply("pyqbot：上一条流式消息还在发，发完再来")
                return
            async with busy:
                current = Experiment(
                    len(experiments) + 1, " ".join([command, *args]), text, message, piece, marks
                )
                experiments.append(current)
                await stream(current, interval)
            summary = summarize(current)
            keep_raw(
                str(current.number),
                summary | {"chunks": [asdict(chunk) for chunk in current.chunks]},
            )
            note(f"experiment.{current.number}", summary)

        async def stream(current: Experiment, interval: float) -> None:
            pieces = [
                current.text[start : start + current.piece]
                for start in range(0, len(current.text), current.piece)
            ]
            sender = current.trigger.reply_stream(coalesce=False)
            began = loop.time()
            sent_chars = 0

            def record(index: int) -> None:
                body = responses[-1] if responses else None
                elapsed = loop.time() - began
                chunk = chunk_record(index, current.text[:sent_chars], elapsed, sender, body)
                current.chunks.append(chunk)
                for key, value in (("id", chunk.id), ("ref_idx", chunk.ref_idx)):
                    if value is not None:
                        known.setdefault(value, f"第 {current.number} 次第 {index} 片的 {key}")

            try:
                async with sender:
                    for index, piece in enumerate(pieces):
                        responses.clear()
                        await sender.append(piece)
                        sent_chars += len(piece)
                        record(index)
                        if interval:
                            await asyncio.sleep(interval)
                    responses.clear()
                record(len(pieces))  # 结束分片
            except pyqbot.QQBotError as error:
                current.error = {
                    "after_chunks": len(current.chunks),
                    "chars": sent_chars,
                    "seconds": round(loop.time() - began, 1),
                    "status_code": getattr(error, "status_code", None),
                    "err_code": error.err_code,
                    "message": error.message,
                    "body": responses[-1] if responses else None,
                }
            current.seconds = loop.time() - began

        async def report(message: pyqbot.C2CMessage, text: str) -> None:
            if not experiments:
                await message.reply("pyqbot：还没有流式消息")
                return
            bubbles, _, remark = text.partition(" ")
            ref = message.ref_msg_idx or ""
            target = next(
                (
                    item
                    for item in experiments
                    if known.get(ref, "").startswith(f"第 {item.number} 次")
                ),
                experiments[-1],
            )
            quoted = next(
                (element.content for element in message.msg_elements if element.content), ""
            )
            offset = locate(target.text, quoted) if quoted else None
            reports.append(message)
            entry: dict[str, object] = {
                "experiment": target.number,
                "bubbles": bubbles,
                "remark": remark,
                "ref_msg_idx": known.get(ref, ref),
                "msg_elements": [
                    known.get(item.msg_idx or "", item.msg_idx) for item in message.msg_elements
                ],
                "quoted_length": len(quoted),
                "quoted_head": quoted[:60],
                "quoted_tail": quoted[-60:],
                "quoted_offset": offset,
                "bytes_before_split": len(target.text[:offset].encode()) if offset else None,
                "bytes_with_next_piece": (
                    len(target.text[: offset + target.piece].encode()) if offset else None
                ),
            }
            keep_raw(f"quote_{len(reports)}", entry | {"message": message.to_dict()})
            note("report", entry)
            summary = summarize(target)
            where = (
                f"从原文第 {offset} 字开始（前面 {entry['bytes_before_split']} 字节）"
                if offset is not None
                else "在原文里定位不了"
            )
            await message.reply(
                f"pyqbot：第 {target.number} 次（{target.label}）共 {len(target.text)} 字、"
                f"{summary['chunks']} 片、{summary['seconds']} 秒，你看到 {bubbles} 条。"
                f"引用的气泡对上 {entry['ref_msg_idx']}，{len(quoted)} 字，{where}。"
                f"响应里 id/ref_idx 的变化：{summary['id_or_ref_changes'] or '无'}；"
                f"remain_msg_len：{summary['remain_msg_len']}；文档外字段：{summary['extra_fields'] or '无'}；"
                f"错误：{target.error or '无'}"
            )

        async def quota(message: pyqbot.C2CMessage) -> None:
            if not experiments:
                await message.reply("pyqbot：还没有流式消息")
                return
            target = experiments[-1]
            accepted = 0
            error: dict[str, object] | None = None
            for attempt in range(1, QUOTA_TRIES + 1):
                try:
                    await target.trigger.reply(
                        f"pyqbot：配额测试 {attempt}（第 {target.number} 次的指令）"
                    )
                except pyqbot.APIError as exc:
                    error = {"attempt": attempt, "err_code": exc.err_code, "message": exc.message}
                    break
                accepted += 1
            result = {"experiment": target.number, "accepted": accepted, "error": error}
            note("quota", result)
            await message.reply(
                f"pyqbot：第 {target.number} 次的指令在流式消息之外又被动回复了 {accepted} 条"
                + (
                    f"，第 {accepted + 1} 条被拒：{error['err_code']} {error['message']}"
                    if error
                    else "，都被接受"
                )
            )

        async def sequence(message: pyqbot.C2CMessage, args: list[str]) -> None:
            if not experiments:
                await message.reply("pyqbot：还没有流式消息")
                return
            target = experiments[-1]
            count = min(
                int(args[0]) if args and args[0].isdigit() else MAX_SEQUENCE - 1, MAX_SEQUENCE
            )
            results: list[dict[str, object]] = []
            for _ in range(count):
                # SDK 记在消息上的计数；SDK 遇到 msg_seq 被占用会自己换下一个，那时 seq_after 会跳过几个。
                before = int(target.trigger.__dict__.get("_msg_seq", 0))
                result: dict[str, object] = {"msg_seq": before + 1}
                try:
                    await target.trigger.reply(f"pyqbot：序号测试 msg_seq={before + 1}")
                    result["result"] = "被接受"
                except pyqbot.APIError as exc:
                    result |= {"err_code": exc.err_code, "message": exc.message}
                result["seq_after"] = int(target.trigger.__dict__.get("_msg_seq", 0))
                results.append(result)
            note("sequence", {"experiment": target.number, "results": results})
            accepted = [str(item["msg_seq"]) for item in results if item.get("result")]
            rejected = [
                f"{item['msg_seq']}:{item.get('err_code')}"
                for item in results
                if not item.get("result")
            ]
            await message.reply(
                f"pyqbot：第 {target.number} 次的指令，被接受的 msg_seq {', '.join(accepted) or '无'}；"
                f"被拒的 {', '.join(rejected) or '无'}"
            )

        async with bot:
            try:
                async with asyncio.timeout(wait_seconds):
                    await bot.start()
            except TimeoutError:
                outcome["timeout"] = f"{wait_seconds} 秒内没有等到「结束」"

    note("stream_auto_split", outcome | {"experiments": [summarize(item) for item in experiments]})
    assert experiments, outcome
