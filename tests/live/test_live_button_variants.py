"""按钮与 Markdown 边角写法的实测。

要回答的问题（结论记进 `docs/errata.md`）：

- 回调按钮：四种样式（尤其红字）在单聊里的样子；`group_id` 相同的按钮点了一个之后，其余的与被点的各变成什么，
  只有一个按钮时怎样，收到新消息、退出聊天再进来之后状态还在不在，变灰的按钮再点还推不推互动事件；二次确认
  （`modal`）的弹窗，点「取消」推不推互动事件，文字超过文档写的长度时会不会被拒。
- 按钮文字超过文档写的 10 个字符时会不会被拒、怎么显示；一行放四个按钮放不放得下。
- 指令按钮在单聊里点了之后实际发出的文字（`enter`、`reply`）。
- 嵌套列表的子项缩进 2 个空格时会不会被压平（官方只说要 4 个空格）。
- 不该成图的几种写法会不会显示出图片：`<img>` 标签、反斜杠转义的 `\\![…](…)`、全角感叹号的「！[…](…)」、行内
  代码里的图片语法。
- 各种代码块写法里的图片语法显示成代码还是图片：顶格的反引号围栏、波浪线围栏、块公式（`\\[`、`$$`）里夹着反引号
  行、行中间的三个反引号、反引号后面跟着别的字的行、列表项里缩进的围栏、四个反引号套三个反引号。
- 超长的流式消息被平台拆成几条气泡时，切口落在代码块里的话，后一条气泡里的图片语法会不会显示成图片。

测试用户在单聊里发编号（发「帮助」看清单），机器人回对应的一条或几条消息。按钮的点击都记下来：标了「会回复」的
每次点击回一句，其余的不回复（收到新消息会让按钮的临时状态复原，见 errata「回应互动」），发「查」看记到了哪些
点击。每种看完发「看 编号 说明」（如「看 2 取消变灰了，确认变成已确认」）。全部做完发「结束」。

运行前提见 `AGENTS.md`「实测」：每次都要先取得用户同意；消耗一次网关连接，所以还要 `LIVE_GATEWAY=1`。
`LIVE_WAIT_SECONDS`（默认 3600）是连上网关后等测试用户操作完的秒数。运行方式：
`LIVE_GATEWAY=1 uv run --env-file .env pytest -m live --no-cov tests/live/test_live_button_variants.py -s --log-cli-level=WARNING`。

结果追加到 `.cache/live/button_variants.txt`；错误文案里有 openid，已被 git 忽略、只留在本机。
"""

import asyncio
import json
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

import pyqbot

pytestmark = pytest.mark.live

OUTPUT = Path(__file__).parents[2] / ".cache" / "live" / "button_variants.txt"
_logger = logging.getLogger("pyqbot.live")

# 2026-11-20 核对过能下载，540×258；实测过带宽高时在流式消息里能显示（`test_live_markdown_images.py`）。
IMAGE = "https://www.baidu.com/img/PCtm_d9c8750bed0b3c7d089fa7d55720d6cf.png"
SHOWN = f"![百度的标志 #270px #129px]({IMAGE})"

Style = pyqbot.ButtonStyle


@dataclass(frozen=True)
class Spec:
    """一个回调按钮：`name` 写进按钮数据，`done` 是点过之后的字（空串表示不变）。"""

    label: str
    name: str
    done: str = ""
    style: pyqbot.ButtonStyle = Style.GRAY_OUTLINE
    modal: pyqbot.ButtonModal | None = None


@dataclass(frozen=True)
class Buttons:
    """一种回调按钮的写法。`grouped` 时所有按钮用同一个 `group_id`；`reply` 时每次点击回一句。"""

    label: str
    ask: str
    rows: tuple[tuple[Spec, ...], ...]
    grouped: bool = False
    reply: bool = False


@dataclass(frozen=True)
class Text:
    """一种 Markdown 写法，用流式消息发出。"""

    label: str
    body: str


CONFIRM = Spec("确认", "yes", "已确认", Style.BLUE_FILLED)
CANCEL = Spec("取消", "no", "已取消")
QUICK = (
    Spec("描述一下", "describe", "已选"),
    Spec("提取文字", "ocr", "已选"),
    Spec("翻译", "translate", "已选"),
    Spec("总结要点", "summary", "已选"),
)

BUTTONS: dict[int, Buttons] = {
    1: Buttons(
        "四种样式，不分组，不回复",
        "从左到右是灰框、蓝框、红字、蓝底。看各自的样子；每个点一下，看点过之后的字与样子。",
        (
            (
                Spec("灰框", "gray", "点过"),
                Spec("蓝框", "blue", "点过", Style.BLUE_OUTLINE),
                Spec("红字", "red", "点过", Style.RED_TEXT),
                Spec("蓝底", "filled", "点过", Style.BLUE_FILLED),
            ),
        ),
    ),
    2: Buttons(
        "同组的两个按钮，不回复",
        "点「确认」，看「取消」会不会变灰、「确认」自己变成什么；再点一下变灰的和点过的，发「查」看有没有"
        "记到。然后退出聊天再进来，看状态还在不在。",
        ((CONFIRM, CANCEL),),
        grouped=True,
    ),
    3: Buttons(
        "同组的两个按钮，会回复",
        "点「确认」，等回复到了之后看两个按钮各是什么样：文字有没有变回去，变灰还在不在。",
        ((CONFIRM, CANCEL),),
        grouped=True,
        reply=True,
    ),
    4: Buttons(
        "只有一个按钮、带分组，不回复",
        "点它，看它自己会不会变灰、还能不能再点；发「查」看记到几次。",
        ((Spec("你能做什么", "only", "已发送"),),),
        grouped=True,
    ),
    5: Buttons(
        "只有一个按钮、带分组，会回复",
        "点它，回复到了之后看按钮的样子，再点一次看还有没有反应。",
        ((Spec("你能做什么", "only", "已发送"),),),
        grouped=True,
        reply=True,
    ),
    6: Buttons(
        "红字加二次确认，同组，会回复",
        "先点「删除」，在弹窗里点「再想想」，发「查」看有没有记到点击；再点「删除」并确认，看回复与两个按钮"
        "的样子。",
        (
            (
                Spec(
                    "删除",
                    "delete",
                    "已删除",
                    Style.RED_TEXT,
                    pyqbot.ButtonModal(
                        content="确定删除吗？删除后不能恢复",
                        confirm_text="删除",
                        cancel_text="再想想",
                    ),
                ),
                Spec("保留", "keep", "已保留"),
            ),
        ),
        grouped=True,
        reply=True,
    ),
    10: Buttons(
        "四个按钮排一行，同组，不回复",
        "看一行放不放得下、字有没有被截断；点一个，看其余三个。",
        (QUICK,),
        grouped=True,
    ),
    11: Buttons(
        "四个按钮分两行，同组，会回复",
        "看排版；点一个，回复到了之后看四个按钮各是什么样。",
        (QUICK[:2], QUICK[2:]),
        grouped=True,
        reply=True,
    ),
}

LONG_MODAL = (
    Spec(
        "提示41字",
        "content41",
        modal=pyqbot.ButtonModal(content="确" * 41),
    ),
    Spec(
        "按钮5字",
        "texts5",
        modal=pyqbot.ButtonModal(
            content="确认与取消各五个字", confirm_text="确认删除它", cancel_text="还是不删了"
        ),
    ),
)
LONG_LABELS = (
    Spec("一二三四五六七八九十", "len10"),
    Spec("一二三四五六七八九十甲乙", "len12"),
    Spec("一二三四五六七八九十" * 2, "len20"),
)
COMMAND_MARK = "pyqbot指令"

TEXTS: dict[int, Text] = {
    12: Text(
        "嵌套列表缩进 2 个空格与 4 个空格",
        "缩进 2 个空格：\n\n- 第一层甲\n  - 第二层（2 个空格）\n    - 第三层（4 个空格）\n- 第一层乙\n\n"
        "缩进 4 个空格：\n\n- 第一层甲\n    - 第二层（4 个空格）\n        - 第三层（8 个空格）\n- 第一层乙\n\n"
        "有序列表里：\n\n1. 第一步\n   - 子项（3 个空格）\n2. 第二步\n    - 子项（4 个空格）\n\n"
        "看：各层有没有缩进，还是被压平成一层。",
    ),
    13: Text(
        "不该成图的四种写法",
        "下面四行都不应该显示出图片，看每一行实际显示成什么。\n\n"
        f'HTML 标签：<img src="{IMAGE}" width="270" height="129">\n\n'
        f"反斜杠转义：\\{SHOWN}\n\n"
        f"全角感叹号：！{SHOWN[1:]}\n\n"
        f"行内代码：`{SHOWN}`\n\n"
        "（完）",
    ),
    14: Text(
        "顶格的反引号代码块里的图片写法",
        f"下面应当是一个代码块，里面是一行图片写法的原文。\n\n```text\n{SHOWN}\n```\n\n（完）",
    ),
    15: Text(
        "波浪线代码块里的图片写法",
        f"下面如果是代码块，里面是一行图片写法的原文；看它是代码还是图片。\n\n~~~text\n{SHOWN}\n~~~\n\n（完）",
    ),
    16: Text(
        "块公式 \\[ … \\] 里夹着反引号行",
        "看：图片写法显示成代码还是图片，「（完）」在不在代码块里。\n\n"
        f"\\[\n```\n\\]\n{SHOWN}\n```\n\n（完）",
    ),
    17: Text(
        "块公式 $$ … $$ 里夹着反引号行",
        "看：图片写法显示成代码还是图片，「（完）」在不在代码块里。\n\n"
        f"$$\n```\n$$\n{SHOWN}\n```\n\n（完）",
    ),
    18: Text(
        "行中间的三个反引号",
        "看：图片写法显示成代码还是图片，「（完）」在不在代码块里。\n\n"
        f"这一行中间有 ``` 三个反引号\n```\n{SHOWN}\n```\n\n（完）",
    ),
    19: Text(
        "反引号后面跟着别的字的行",
        "看：图片写法显示成代码还是图片，「（完）」在不在代码块里。\n\n"
        f"```text\n第一行代码\n``` 这一行不是结束行\n{SHOWN}\n```\n\n（完）",
    ),
    20: Text(
        "列表项里缩进的代码块",
        "看：列表项下面是不是代码块，里面是图片写法的原文还是图片。\n\n"
        f"- 列表项\n\n  ```text\n  {SHOWN}\n  ```\n\n- 下一项\n\n（完）",
    ),
    21: Text(
        "四个反引号的代码块里套三个反引号",
        "看：是不是一整个代码块，图片写法显示成代码还是图片。\n\n"
        f"````markdown\n```python\nprint(1)\n```\n{SHOWN}\n````\n\n（完）",
    ),
}
LONG = 22
SPECIAL = {
    7: "二次确认的文字超过文档写的长度（两条消息）",
    8: "按钮文字 10、12、20 个字",
    9: "指令按钮：直接发、填进输入框、引用着发",
    LONG: "超长的流式消息，切口落在代码块里",
}


def labels() -> dict[int, str]:
    listing = {number: variant.label for number, variant in BUTTONS.items()}
    listing |= SPECIAL
    listing |= {number: variant.label for number, variant in TEXTS.items()}
    return dict(sorted(listing.items()))


HELP = (
    "pyqbot 按钮与 Markdown 实测，发编号：\n"
    + "\n".join(f"{number}：{label}" for number, label in labels().items())
    + "\n查：看记到的按钮点击\n看 编号 说明：记下观察\n结束：断开"
)


def long_body() -> str:
    """约 17000 字节：前面约 11000 字节的段落，后面一个代码块，图片写法在约 16000 字节处（平台在约 15000 字节处拆）。"""
    parts = ["前面是填充的段落，后面是一个很长的代码块，代码块里靠后的位置有一行图片写法。\n\n"]
    size = len(parts[0].encode())
    index = 0
    while size < 11000:
        index += 1
        paragraph = f"第 {index} 段：" + "这是填充用的文字。" * 12 + "\n\n"
        parts.append(paragraph)
        size += len(paragraph.encode())
    parts.append("```text\n")
    line = 0
    while size < 16000:
        line += 1
        code = f"{line:04d} " + "code " * 12 + "\n"
        parts.append(code)
        size += len(code.encode())
    parts.append(f"{SHOWN}\n")
    parts.extend(f"{line + extra:04d} " + "code " * 12 + "\n" for extra in range(1, 9))
    parts.append("```\n\n（完）看：拆成了几条；后一条里图片写法显示成代码还是图片。")
    return "".join(parts)


@pytest.fixture
def wait_seconds() -> float:
    if os.environ.get("LIVE_GATEWAY") != "1":
        pytest.skip("需要显式设置 LIVE_GATEWAY=1：用例消耗一次网关连接")
    return float(os.environ.get("LIVE_WAIT_SECONDS", "3600"))


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


def verdict(value: object) -> str:
    """一个结果的短写法：被拒的只写错误码。"""
    if isinstance(value, dict):
        return f"被拒（{cast(dict[str, object], value).get('err_code')}）"
    return str(value)


def summarize(result: object) -> str:
    """一种做法的结果：分了几步的（字典里的值是各步的结果）逐步列出。"""
    if not isinstance(result, dict):
        return verdict(result)
    steps = cast(dict[str, object], result)
    if "err_code" in steps:
        return verdict(steps)
    return "；".join(f"{key} {verdict(value)}" for key, value in steps.items())


async def test_button_and_markdown_variants(
    app_id: str, app_secret: str, openid: str, wait_seconds: float
) -> None:
    """测试用户依次发编号，每种按消息里写的去点、去看，看完发「看 编号 说明」，最后发「结束」。"""
    bot = pyqbot.Bot(app_id, app_secret)
    loop = asyncio.get_running_loop()
    run = secrets.token_hex(3)  # 区分本次运行的按钮与旧消息上的按钮
    sent_at: dict[int, float] = {}
    clicks: list[str] = []
    done: set[int] = set()
    outcome: dict[str, object] = {}

    def button(number: int, spec: Spec, *, grouped: bool) -> pyqbot.Button:
        return pyqbot.Button.callback(
            spec.label,
            f"pqb:{run}:{number}:{spec.name}",
            visited_label=spec.done or None,
            style=spec.style,
            group_id=f"g{run}{number}" if grouped else None,
            modal=spec.modal,
        )

    async def send(message: pyqbot.C2CMessage, markdown: str, keyboard: pyqbot.Keyboard) -> object:
        try:
            await message.reply(markdown=markdown, keyboard=keyboard)
        except pyqbot.QQBotError as error:
            return describe(error)
        return "被接受"

    async def run_buttons(number: int, variant: Buttons, message: pyqbot.C2CMessage) -> object:
        keyboard = pyqbot.Keyboard.from_rows(
            *(
                [button(number, spec, grouped=variant.grouped) for spec in row]
                for row in variant.rows
            )
        )
        tail = (
            "点了机器人会回一句。" if variant.reply else "点了机器人不回复，发「查」看记到的点击。"
        )
        return await send(message, f"**实测{number}**：{variant.ask}{tail}", keyboard)

    async def run_modal(number: int, message: pyqbot.C2CMessage) -> object:
        results: dict[str, object] = {}
        for spec in LONG_MODAL:
            keyboard = pyqbot.Keyboard.from_rows([button(number, spec, grouped=False)])
            text = f"**实测{number}**：点「{spec.label}」，看弹窗里的文字有没有被截断。"
            results[spec.name] = await send(message, text, keyboard)
        return results

    async def run_labels(number: int, message: pyqbot.C2CMessage) -> object:
        """三个长度放在一条消息里；被拒的话再逐个发，看是哪一个超了。"""
        rows = [[button(number, spec, grouped=False)] for spec in LONG_LABELS]
        text = f"**实测{number}**：三行按钮，文字分别是 10、12、20 个字，看有没有被截断。"
        results: dict[str, object] = {
            "together": await send(message, text, pyqbot.Keyboard.from_rows(*rows))
        }
        if results["together"] != "被接受":
            for spec, row in zip(LONG_LABELS, rows, strict=True):
                single = pyqbot.Keyboard.from_rows(row)
                results[spec.name] = await send(message, f"**实测{number}**：{spec.name}", single)
        return results

    async def run_commands(number: int, message: pyqbot.C2CMessage) -> object:
        keyboard = pyqbot.Keyboard.from_rows(
            [
                pyqbot.Button.command("直接发", f"{COMMAND_MARK}直发{run}", enter=True),
                pyqbot.Button.command("填输入框", f"{COMMAND_MARK}填入{run}"),
                pyqbot.Button.command(
                    "引用着发", f"{COMMAND_MARK}引用{run}", enter=True, reply=True
                ),
            ]
        )
        text = (
            f"**实测{number}**：三个指令按钮。「直接发」「引用着发」点了应当直接发出一条消息；「填输入框」只填进"
            "输入框，请再手动发出。每条发出后机器人回一句它收到的原文。"
        )
        return await send(message, text, keyboard)

    async def run_stream(number: int, body: str, message: pyqbot.C2CMessage) -> object:
        """按行攒成约 1500 字节的片逐片发；只记各片是否被接受与拆成了几条。"""
        pieces: list[str] = []
        current = f"**实测{number}**："
        for line in body.splitlines(keepends=True):
            if len((current + line).encode()) > 1500:
                pieces.append(current)
                current = ""
            current += line
        pieces.append(current)
        stream = message.reply_stream(coalesce=False)
        accepted = 0
        for piece in pieces:
            try:
                await stream.append(piece)
            except pyqbot.QQBotError as error:
                return {"pieces": len(pieces), "accepted": accepted, "rejected": describe(error)}
            accepted += 1
        try:
            await stream.finish()
        except pyqbot.QQBotError as error:
            return {"pieces": len(pieces), "accepted": accepted, "end": describe(error)}
        return {
            "pieces": len(pieces),
            "accepted": accepted,
            "end": "被接受",
            "bytes": len(body.encode()),
            "bubbles": len(stream.ref_idxs),
        }

    async def run_variant(number: int, message: pyqbot.C2CMessage) -> object:
        if number in BUTTONS:
            return await run_buttons(number, BUTTONS[number], message)
        if number in TEXTS:
            return await run_stream(number, TEXTS[number].body, message)
        if number == LONG:
            return await run_stream(number, long_body(), message)
        if number == 7:
            return await run_modal(number, message)
        if number == 8:
            return await run_labels(number, message)
        return await run_commands(number, message)

    @bot.on_c2c_message
    async def on_message(message: pyqbot.C2CMessage) -> None:
        if message.user_openid != openid:
            return
        content = message.content
        command, *args = content.strip().split() or [""]
        if COMMAND_MARK in content:
            quoted = message.ref_msg_idx is not None
            note("command_button", {"content": content, "quoted": quoted})
            await message.reply(
                f"pyqbot：收到指令按钮发来的消息，原文 {content!r}，{'带' if quoted else '不带'}引用"
            )
        elif command.isdigit() and (number := int(command)) in labels():
            result = await run_variant(number, message)
            done.add(number)
            sent_at[number] = loop.time()
            note(f"variant.{number}", {"label": labels()[number], "result": result})
            if result != "被接受":
                await message.reply(f"pyqbot：第 {number} 种的结果：{summarize(result)}")
        elif command == "查":
            listing = "\n".join(clicks) or "没有新的点击"
            clicks.clear()
            await message.reply(f"pyqbot：记到的点击：\n{listing}")
        elif command == "看" and args and args[0].isdigit():
            number = int(args[0])
            since = round(loop.time() - sent_at[number], 1) if number in sent_at else None
            note(
                "observe",
                {"variant": number, "remark": " ".join(args[1:]), "seconds_since_sent": since},
            )
            await message.reply(f"pyqbot：记下了（第 {number} 种）")
        elif command == "帮助":
            await message.reply(HELP)
        elif command == "结束":
            listing = "、".join(str(number) for number in sorted(done))
            await message.reply(f"pyqbot：实测结束，做过的：{listing or '无'}")
            outcome["finished"] = True
            await bot.close()

    @bot.on_interaction
    async def on_click(interaction: pyqbot.Interaction) -> None:
        if interaction.user_openid != openid:
            return
        parts = (interaction.button_data or "").split(":")
        if len(parts) != 4 or parts[0] != "pqb" or not parts[2].isdigit():
            return
        number, name = int(parts[2]), parts[3]
        current = parts[1] == run
        since = round(loop.time() - sent_at[number], 1) if number in sent_at else None
        note(
            "click",
            {"variant": number, "button": name, "this_run": current, "seconds_since_sent": since},
        )
        clicks.append(f"第 {number} 种「{name}」" + ("" if current else "（旧消息上的按钮）"))
        variant = BUTTONS.get(number)
        if variant is not None and variant.reply and current:
            try:
                await interaction.reply(f"pyqbot：收到点击（第 {number} 种「{name}」）")
            except pyqbot.QQBotError as error:
                note("click.reply", describe(error))

    async with bot:
        try:
            async with asyncio.timeout(wait_seconds):
                await bot.start()
        except TimeoutError:
            outcome["timeout"] = f"{wait_seconds} 秒内没有等到「结束」"

    note("button_and_markdown_variants", outcome | {"done": sorted(done)})
    assert done, outcome
