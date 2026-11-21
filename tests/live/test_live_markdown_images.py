"""Markdown 正文里的图片实测：第三方网站的图、打不开的地址、宽高，以及素材库的图删掉之后。

要回答的问题（结论记进 `docs/errata.md`）：

- 流式消息的正文中间放第三方网站的图能不能显示：境内的图站、境内访问不了的境外图站、地址带查询串的。
  已测过的只有 QQ 自己 CDN 上的图（`test_markdown_showcase_stream`）与群消息里的第三方图床。
- 地址打不开（404、不是图片、主机解析不了）时，分片或消息会不会被拒，用户看到的是什么。
- 不写宽高、宽高与实际比例不符、宽高写得很大时怎么显示。
- 素材库的图能不能在流式消息里引用；发出后立刻删掉素材，已发的消息里图还在不在（官方「素材管理」说不受影响，
  发送时平台已转存副本）；引用已经删掉的素材会怎样。

测试用户在单聊里发编号（发「帮助」看 `VARIANTS`），机器人回一条正文中间带图的消息，流式的逐片发送，图片那一片
之后与结束之前各停 `PAUSE` 秒，方便看图是什么时候出现的；发完再回一句各分片的结果。测试用户看完发
「看 编号 说明」（如「看 2 图没显示，那里是空白」）。全部做完发「结束」。

运行前提见 `AGENTS.md`「实测」：每次都要先取得用户同意；消耗一次网关连接，所以还要 `LIVE_GATEWAY=1`；用到素材库的
几种（素材库是机器人全局的，须单独同意）另要 `LIVE_MEDIA_IMAGES=1`，没打开时这几种跳过。上传的素材都在用例里删掉。
`LIVE_WAIT_SECONDS`（默认 1800）是连上网关后等测试用户操作完的秒数。运行方式：
`LIVE_GATEWAY=1 LIVE_MEDIA_IMAGES=1 uv run --env-file .env pytest -m live --no-cov tests/live/test_live_markdown_images.py -s --log-cli-level=WARNING`。

结果追加到 `.cache/live/markdown_images.txt`；错误文案里有 openid，已被 git 忽略、只留在本机。
"""

import asyncio
import json
import logging
import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

import pyqbot

pytestmark = pytest.mark.live

OUTPUT = Path(__file__).parents[2] / ".cache" / "live" / "markdown_images.txt"
_logger = logging.getLogger("pyqbot.live")

PAUSE = 3.0

# 2026-11-20 核对过都能下载，括号里是实际的像素。
BAIDU = "https://www.baidu.com/img/PCtm_d9c8750bed0b3c7d089fa7d55720d6cf.png"  # 540×258
WIKI = (  # 500×925
    "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a8/Tour_Eiffel_Wikimedia_Commons.jpg"
    "/500px-Tour_Eiffel_Wikimedia_Commons.jpg"
)
NASA = (  # 2020×660
    "https://assets.science.nasa.gov/dynamicimage/assets/science/psd/solar/2023/09/s"
    "/solarsys_scale.jpg?w=2020&h=660&fit=clip"
)
MISSING = "https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.49.0/assets/img/no-such-image.jpg"  # 404


@dataclass(frozen=True)
class Variant:
    """一种图片写法。`image` 是 Markdown 的图片语法，素材库的用 `{url}` 占位。

    `library` 为 `delete_after` 时发出后立刻删掉素材，为 `deleted_before` 时先删掉素材再引用；`color` 是那张素材
    的颜色（RGB），每种不同，方便辨认。
    """

    label: str
    image: str
    stream: bool = True
    force_verify: bool = False
    library: str = ""
    color: bytes = b""


VARIANTS: dict[int, Variant] = {
    1: Variant("流式，境内的第三方图站，带宽高", f"![百度的标志 #540px #258px]({BAIDU})"),
    2: Variant(
        "流式，维基共享资源的图（境内访问不了），带宽高", f"![埃菲尔铁塔 #250px #462px]({WIKI})"
    ),
    3: Variant("流式，NASA 的图，地址带查询串", f"![行星大小对比 #505px #165px]({NASA})"),
    4: Variant("流式，地址是 404", f"![不存在的图 #300px #200px]({MISSING})"),
    5: Variant("流式，地址是网页、不是图片", "![网页 #300px #200px](https://www.qq.com/)"),
    6: Variant(
        "流式，主机解析不了", "![解析不了 #300px #200px](https://no-such-host.invalid/x.png)"
    ),
    7: Variant("流式，不写宽高", f"![百度的标志]({BAIDU})"),
    8: Variant(
        "流式，宽高与实际比例不符（540×258 写成 300×300）", f"![百度的标志 #300px #300px]({BAIDU})"
    ),
    9: Variant("流式，宽高写得很大（2160×1032）", f"![百度的标志 #2160px #1032px]({BAIDU})"),
    10: Variant(
        "普通消息，地址是 404，不强制校验",
        f"![不存在的图 #300px #200px]({MISSING})",
        stream=False,
    ),
    11: Variant(
        "普通消息，地址是 404，强制校验",
        f"![不存在的图 #300px #200px]({MISSING})",
        stream=False,
        force_verify=True,
    ),
    12: Variant(
        "流式，素材库的图（橙色），结束后立刻删掉素材",
        "![橙色的素材 #300px #200px]({url})",
        library="delete_after",
        color=b"\xff\x80\x00",
    ),
    13: Variant(
        "普通消息，素材库的图（紫色），发出后立刻删掉素材",
        "![紫色的素材 #300px #200px]({url})",
        stream=False,
        library="delete_after",
        color=b"\x80\x00\xc0",
    ),
    14: Variant(
        "流式，引用已经删掉的素材（绿色）",
        "![绿色的素材 #300px #200px]({url})",
        library="deleted_before",
        color=b"\x00\xa0\x40",
    ),
    15: Variant(
        "流式，素材库的图（蓝色）不写宽高，结束后立刻删掉素材",
        "![蓝色的素材]({url})",
        library="delete_after",
        color=b"\x00\x60\xff",
    ),
}
HELP = (
    "pyqbot 图片实测，发编号：\n"
    + "\n".join(f"{number}：{variant.label}" for number, variant in VARIANTS.items())
    + "\n每种看：图有没有显示、是流式过程中出现还是结束后才出现、大小与比例；没显示时那里是什么"
    + "\n12、13、15 收到「素材已删除」后，退出聊天再进来看图还在不在"
    + "\n看 编号 说明：记下观察\n结束：断开"
)


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


def verdict(value: object) -> str:
    """一个结果的短写法：被拒的只写错误码。"""
    if isinstance(value, dict):
        return f"被拒（{cast(dict[str, object], value).get('err_code')}）"
    return str(value)


def brief(result: dict[str, object]) -> str:
    """回给测试用户的一句小结。"""
    names = {"upload": "上传", "delete_before": "先删素材", "send": "发送", "end": "结束分片"}
    parts = [f"{names[key]} {verdict(result[key])}" for key in names if key in result]
    if "chunks" in result:
        chunks = "、".join(verdict(chunk) for chunk in cast(list[object], result["chunks"]))
        parts.insert(-1 if "end" in result else len(parts), f"各分片 {chunks}")
    if "delete" in result:
        deleted = verdict(result["delete"])
        parts.append(
            f"素材{deleted}，退出聊天再进来看图还在不在" if deleted == "已删除" else deleted
        )
    return "；".join(parts)


def png(width: int, height: int, color: bytes) -> bytes:
    """生成纯色的 RGB PNG。"""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    rows = (b"\x00" + color * width) * height
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 1))
        + chunk(b"IEND", b"")
    )


async def test_markdown_image_variants(
    app_id: str, app_secret: str, openid: str, wait_seconds: float
) -> None:
    """测试用户依次发 1～15（12～15 要 `LIVE_MEDIA_IMAGES=1`），每种看完发「看 编号 说明」，最后发「结束」。

    每种要看的：图有没有显示、是流式过程中出现还是结束后才出现、大小与比例；没显示时那里是什么（裂图、空白、
    原文）。12、13、15 收到「素材已删除」之后，退出聊天再进来（最好换一台设备）看图还在不在。
    """
    library_enabled = os.environ.get("LIVE_MEDIA_IMAGES") == "1"
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
        if command.isdigit() and (number := int(command)) in VARIANTS:
            variant = VARIANTS[number]
            if variant.library and not library_enabled:
                await message.reply(
                    f"pyqbot：第 {number} 种要用素材库，没有打开 LIVE_MEDIA_IMAGES，跳过"
                )
                return
            result = await run(number, variant, message)
            results[number] = result
            ended_at[number] = loop.time()
            note(f"variant.{number}", result)
            await message.reply(f"pyqbot：第 {number} 种发完了。{brief(result)}")
        elif command == "看" and args and args[0].isdigit():
            number = int(args[0])
            since = round(loop.time() - ended_at[number], 1) if number in ended_at else None
            note(
                "observe",
                {"variant": number, "remark": " ".join(args[1:]), "seconds_since_end": since},
            )
            await message.reply(f"pyqbot：记下了（第 {number} 种，距发完 {since} 秒）")
        elif command == "帮助":
            await message.reply(HELP)
        elif command == "结束":
            done = "、".join(str(number) for number in sorted(results))
            await message.reply(f"pyqbot：图片实测结束，做过的：{done or '无'}")
            outcome["finished"] = True
            await bot.close()

    async def run(number: int, variant: Variant, message: pyqbot.C2CMessage) -> dict[str, object]:
        result: dict[str, object] = {"label": variant.label}
        image: pyqbot.MediaImage | None = None
        syntax = variant.image
        if variant.library:
            try:
                image = await bot.images.upload(
                    data=png(300, 200, variant.color), file_name=f"pyqbot-{number}.png"
                )
            except pyqbot.QQBotError as error:
                return result | {"upload": describe(error)}
            result |= {"upload": "被接受", "ttl": image.ttl}
            syntax = syntax.format(url=image.url)
            if variant.library == "deleted_before":
                result["delete_before"] = await delete(image)
                image = None
        try:
            if variant.stream:
                result |= await send_stream(message, number, syntax)
            else:
                result |= await send_plain(message, number, syntax, force=variant.force_verify)
        finally:
            if image is not None:
                result["delete"] = await delete(image)
        return result

    async def delete(image: pyqbot.MediaImage) -> object:
        try:
            await bot.images.delete(image)
        except pyqbot.QQBotError as error:
            return describe(error)
        return "已删除"

    async def send_stream(
        message: pyqbot.C2CMessage, number: int, syntax: str
    ) -> dict[str, object]:
        """三片：图前的文字、图片、图后的文字；素材库的引用地址不进结果，只记各片是否被接受。"""
        pieces = (f"图片测试{number}：图前的一段文字。\n\n", f"{syntax}\n\n", "图后的一段文字。")
        stream = message.reply_stream(coalesce=False)
        chunks: list[object] = []
        for piece in pieces:
            try:
                await stream.append(piece)
            except pyqbot.QQBotError as error:
                return {"chunks": [*chunks, describe(error)]}
            chunks.append("被接受")
            await asyncio.sleep(PAUSE)
        try:
            await stream.finish()
        except pyqbot.QQBotError as error:
            return {"chunks": chunks, "end": describe(error)}
        return {"chunks": chunks, "end": "被接受", "bubbles": len(stream.ref_idxs)}

    async def send_plain(
        message: pyqbot.C2CMessage, number: int, syntax: str, *, force: bool
    ) -> dict[str, object]:
        content = f"图片测试{number}：图前的一段文字。\n\n{syntax}\n\n图后的一段文字。"
        markdown = pyqbot.Markdown(content=content, force_verify_image_resource=force or None)
        try:
            await message.reply(markdown=markdown)
        except pyqbot.QQBotError as error:
            return {"send": describe(error)}
        return {"send": "被接受"}

    async with bot:
        try:
            async with asyncio.timeout(wait_seconds):
                await bot.start()
        except TimeoutError:
            outcome["timeout"] = f"{wait_seconds} 秒内没有等到「结束」"

    note("markdown_image_variants", outcome | {"results": results})
    assert results, outcome
