"""流式消息结束分片的实测：qtalk-bot 的纯文本（`content_type=text`）流式消息，空的结束分片被拒，err_code 40034019。

要回答的问题（结论记进 `docs/errata.md`）：

- 什么情况下出现 40034019：纯文本本身、emoji、换行、链接、分片多、同一条消息上还有别的回复或流式消息、
  最后一片之后隔很久才结束。之前 `test_c2c_reply_limit_and_plain_stream` 的纯文本流式消息，空的结束分片被接受了。
- 怎样能正常结束：结束分片带上最后一段、用 replace 带全文结束、结束分片改用 `content_type=markdown`。
- 结束分片被拒后，客户端里这条消息是否一直显示「生成中」，平台会不会超时自动结束。

测试用户在单聊里发编号（发「帮助」看 `VARIANTS`），机器人按对应的方式流式回复这条消息，都逐片发送；结束分片被拒时
不另发消息，免得盖住客户端里的状态。测试用户看完可以发「看 编号 说明」（如「看 3 三个点还在」），机器人记下距那次
结束分片多少秒。全部做完发「结束」，机器人回一句小结。

运行前提见 `AGENTS.md`「实测」：每次都要先取得用户同意；消耗一次网关连接，所以还要 `LIVE_GATEWAY=1`。
`LIVE_WAIT_SECONDS`（默认 1800）是连上网关后等测试用户操作完的秒数。运行方式：
`LIVE_GATEWAY=1 uv run --env-file .env pytest -m live --no-cov tests/live/test_live_stream_finish.py -s --log-cli-level=WARNING`。

结果追加到 `.cache/live/finish.txt`；错误文案里有 openid，已被 git 忽略、只留在本机。
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

import pyqbot
from pyqbot._models.stream import StreamContentType, StreamInputMode, StreamInputState

pytestmark = pytest.mark.live

OUTPUT = Path(__file__).parents[2] / ".cache" / "live" / "finish.txt"
_logger = logging.getLogger("pyqbot.live")


@dataclass(frozen=True)
class Variant:
    """一种结束方式：正文分片、是否 Markdown、结束分片怎么发、最后一片之后等几秒再结束。"""

    label: str
    pieces: tuple[str, ...]
    markdown: bool = False
    end: str = "empty"  # empty：空的结束分片；with_last：最后一段随结束分片发；replace：带全文；markdown_end
    idle: float = 0.0


STEPS = tuple(f"🔍 步骤 {step}：检索资料\n" for step in range(1, 21))
VARIANTS: dict[int, Variant] = {
    1: Variant("纯中文，空结束分片", ("结束测试1：纯中文", "，第二片")),
    2: Variant("含 emoji", ("结束测试2：🔍 搜索中", "，第二片")),
    3: Variant("含换行", ("结束测试3：第一行\n", "第二行")),
    4: Variant("含链接", ("结束测试4：见 https://www.qq.com", " 第二片")),
    5: Variant("20 片，含 emoji 与换行", ("结束测试5：\n", *STEPS)),
    6: Variant("最后一段随结束分片发出", ("结束测试6：", "第二片", "，最后一段")),
    7: Variant("replace 带全文结束", ("结束测试7：", "第二片"), end="replace"),
    8: Variant("结束分片改用 markdown", ("结束测试8：", "第二片"), end="markdown_end"),
    9: Variant(
        "对照：Markdown，含 emoji、换行与链接",
        ("结束测试9：🔍 第一行\n", "见 https://www.qq.com"),
        markdown=True,
    ),
    12: Variant("最后一片之后等一会再结束", ("结束测试12：", "第二片"), idle=60),
    13: Variant("对照：Markdown，等一会再结束", ("结束测试13：", "第二片"), markdown=True, idle=60),
    20: Variant(
        "重测 13：Markdown，等一会再结束，期间不发消息",
        ("结束测试20：", "第二片"),
        markdown=True,
        idle=60,
    ),
}
# 流还没结束时，对同一条消息插进一条别的消息，再结束这条流：(这条流是否 Markdown, 插进的是什么)。
INTERLEAVED: dict[int, tuple[bool, str]] = {
    10: (False, "Markdown 流"),
    17: (True, "Markdown 流"),
    18: (False, "普通文本消息"),
    19: (True, "普通 Markdown 消息"),
}
HELP = (
    "pyqbot 结束分片实测，发编号：\n"
    + "\n".join(f"{number}：{variant.label}" for number, variant in VARIANTS.items())
    + "".join(
        f"\n{number}：{'Markdown' if markdown else '纯文本'}流还没结束，插进一条{other}，再结束它"
        for number, (markdown, other) in INTERLEAVED.items()
    )
    + "\n11：先对这条消息回一条普通消息，再回纯文本流"
    + "\n12、13 可以带秒数，如「12 120」"
    + "\n14：仿 qtalk-bot：正在输入、纯文本过程流，结束分片与 Markdown 回答流的第一片同时发"
    + "\n15：同上，但过程流先结束再开回答流"
    + "\n16：同上，但只有过程流、没有回答流"
    + "\n看 编号 说明：记下观察\n结束：断开"
)
# 仿 qtalk-bot 的过程消息：纯文本、每步一行，后续分片以换行或空格开头，片间隔 2 秒。
PROGRESS = ("正在理解问题", "\n正在搜索🔍", " 上海 天气", "\n- 整理搜索结果，准备回答")


@pytest.fixture
def wait_seconds() -> float:
    if os.environ.get("LIVE_GATEWAY") != "1":
        pytest.skip("需要显式设置 LIVE_GATEWAY=1：用例消耗一次网关连接")
    return float(os.environ.get("LIVE_WAIT_SECONDS", "1800"))


@pytest.fixture
def openid() -> str:
    value = os.environ.get("TEST_USER_OPENID")
    if not value:
        pytest.skip("缺少环境变量 TEST_USER_OPENID：用 uv run --env-file .env 运行")
    return value


def note(title: str, value: object) -> None:
    line = f"{title}: {json.dumps(value, ensure_ascii=False, default=str)}"
    _logger.warning("%s", line)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("a", encoding="utf-8") as report:
        report.write(line + "\n")


def describe(error: pyqbot.QQBotError) -> dict[str, object]:
    return {
        "status_code": getattr(error, "status_code", None),
        "err_code": error.err_code,
        "message": error.message,
        "trace_id": error.trace_id,
    }


async def end_stream(stream: pyqbot.StreamMessage, variant: Variant) -> None:
    """按 `variant.end` 发结束分片；SDK 只会发空的 append 结束分片，其余几种借用内部方法。"""
    match variant.end:
        case "with_last":
            await stream._send(StreamInputMode.APPEND, variant.pieces[-1], StreamInputState.DONE)  # pyright: ignore[reportPrivateUsage]  试 SDK 不提供的结束方式
        case "replace":
            full = "".join(variant.pieces)
            await stream._send(StreamInputMode.REPLACE, full, StreamInputState.DONE)  # pyright: ignore[reportPrivateUsage]  同上
        case "markdown_end":
            stream._content_type = StreamContentType.MARKDOWN  # pyright: ignore[reportPrivateUsage]  同上
            await stream.finish()
        case _:
            await stream.finish()


async def test_stream_finish_variants(
    app_id: str, app_secret: str, openid: str, wait_seconds: float
) -> None:
    """测试用户依次发 14、15、16、1～13（12、13 各要等一分钟），被拒时看三个点的状态，最后发「结束」。

    第二轮只发 17～20：区分「插进任何消息都会结束流」与「只有类型不同的消息才会」；20 的等待期间不要发消息。
    """
    bot = pyqbot.Bot(app_id, app_secret)
    loop = asyncio.get_running_loop()
    results: dict[int, dict[str, object]] = {}
    ended_at: dict[int, float] = {}
    outcome: dict[str, object] = {}

    @bot.on_c2c_message
    async def on_message(message: pyqbot.C2CMessage) -> None:
        if message.user_openid != openid:
            return
        command, *args = message.content.strip().split() or [""]
        if command.isdigit() and (number := int(command)) in {
            *VARIANTS,
            *INTERLEAVED,
            11,
            14,
            15,
            16,
        }:
            result = await run(number, message, [int(arg) for arg in args if arg.isdigit()])
            results[number] = result
            ended_at[number] = loop.time()
            note(f"variant.{number}", result)
        elif command == "看" and args and args[0].isdigit():
            number = int(args[0])
            since = round(loop.time() - ended_at[number], 1) if number in ended_at else None
            note(
                "observe",
                {"variant": number, "remark": " ".join(args[1:]), "seconds_since_end": since},
            )
            await message.reply(f"pyqbot：记下了（第 {number} 种，距结束分片 {since} 秒）")
        elif command == "帮助":
            await message.reply(HELP)
        elif command == "结束":
            summary = "；".join(
                f"{number} {'接受' if result.get('end') == '被接受' else result.get('end') or result.get('chunk_error')}"
                for number, result in sorted(results.items())
            )
            await message.reply(f"pyqbot：结束分片的结果：{summary or '无'}")
            outcome["finished"] = True
            await bot.close()

    async def run(number: int, message: pyqbot.C2CMessage, args: list[int]) -> dict[str, object]:
        if number in INTERLEAVED:
            return await interleaved(message, number)
        if number in (14, 15, 16):
            return await like_qtalk(message, number)
        result: dict[str, object] = {}
        if number == 11:
            try:
                await message.reply("结束测试11：先回一条普通消息")
                result["reply"] = "被接受"
            except pyqbot.QQBotError as error:
                result["reply"] = describe(error)
            variant = Variant("先回普通消息，再回纯文本流", ("结束测试11：纯文本流", "，第二片"))
        else:
            variant = VARIANTS[number]
            if args and variant.idle:
                variant = Variant(
                    variant.label, variant.pieces, variant.markdown, variant.end, args[0]
                )
        result |= {"label": variant.label, "idle": variant.idle}
        stream = message.reply_stream(markdown=variant.markdown, coalesce=False)
        body = variant.pieces[:-1] if variant.end == "with_last" else variant.pieces
        try:
            for piece in body:
                await stream.append(piece)
                await asyncio.sleep(0.5)
        except pyqbot.QQBotError as error:
            return result | {"chunk_error": describe(error), "sent_text": stream.sent_text}
        await asyncio.sleep(variant.idle)
        try:
            await end_stream(stream, variant)
            result["end"] = "被接受"
        except pyqbot.QQBotError as error:
            result["end"] = describe(error)
        return result | {"sent_text": stream.sent_text, "ref_idxs": stream.ref_idxs}

    async def interleaved(message: pyqbot.C2CMessage, number: int) -> dict[str, object]:
        """流还没结束时对同一条消息插进 `INTERLEAVED` 里的那条消息，再结束这条流。"""
        markdown, other = INTERLEAVED[number]
        kind = "Markdown" if markdown else "纯文本"
        result: dict[str, object] = {"label": f"{kind}流还没结束，插进一条{other}"}
        progress = message.reply_stream(markdown=markdown, coalesce=False)
        try:
            await progress.append(f"结束测试{number}：{kind}过程消息，第一步")
            await asyncio.sleep(0.5)
            await progress.append("\n第二步")
            match other:
                case "Markdown 流":
                    async with message.reply_stream(coalesce=False) as answer:
                        await answer.append(f"**结束测试{number}：正式回答**")
                        await asyncio.sleep(0.5)
                        await answer.append("，回答完毕")
                case "普通文本消息":
                    await message.reply(f"结束测试{number}：插进来的普通文本消息")
                case _:
                    await message.reply(markdown=f"**结束测试{number}：插进来的 Markdown 消息**")
            result["other"] = "被接受"
        except pyqbot.QQBotError as error:
            result["chunk_error"] = describe(error)
        try:
            await progress.finish()
            result["end"] = "被接受"
        except pyqbot.QQBotError as error:
            result["end"] = describe(error)
        return result

    async def like_qtalk(message: pyqbot.C2CMessage, number: int) -> dict[str, object]:
        """仿 qtalk-bot：先「正在输入」，再开纯文本过程流；14 的结束分片与回答流第一片同时发，15 先结束再回答，16 不回答。"""
        labels = {14: "结束与回答流同时", 15: "先结束再开回答流", 16: "只有过程流"}
        result: dict[str, object] = {"label": f"仿 qtalk-bot：{labels[number]}"}
        try:
            await bot.users.send_typing(openid, seconds=60, reply_to=message)
            result["typing"] = "被接受"
        except pyqbot.QQBotError as error:
            result["typing"] = describe(error)
        progress = message.reply_stream(markdown=False, coalesce=False)
        try:
            for piece in (f"结束测试{number}：{PROGRESS[0]}", *PROGRESS[1:]):
                await progress.append(piece)
                await asyncio.sleep(2)
        except pyqbot.QQBotError as error:
            return result | {"chunk_error": describe(error)}

        async def finish_progress() -> None:
            try:
                await progress.finish()
                result["end"] = "被接受"
            except pyqbot.QQBotError as error:
                result["end"] = describe(error)

        finishing = asyncio.create_task(finish_progress()) if number == 14 else None
        if number == 15:
            await finish_progress()
        if number != 16:
            try:
                async with message.reply_stream(coalesce=False) as answer:
                    await answer.append(f"**结束测试{number}：正式回答**")
                    await asyncio.sleep(0.5)
                    await answer.append("，回答完毕")
                result["answer"] = "被接受"
            except pyqbot.QQBotError as error:
                result["answer"] = describe(error)
        if finishing is not None:
            await finishing
        if number == 16:
            await finish_progress()
        return result

    async with bot:
        try:
            async with asyncio.timeout(wait_seconds):
                await bot.start()
        except TimeoutError:
            outcome["timeout"] = f"{wait_seconds} 秒内没有等到「结束」"

    note("stream_finish_variants", outcome | {"results": results})
    assert results, outcome
