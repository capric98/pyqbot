"""发消息的各种内容类型：向 `TEST_USER_OPENID` 主动发送，再由人确认客户端里的效果。

确认 `docs/errata.md` 里与发消息有关的待实测项。运行前提见 `AGENTS.md`「实测」：每次都要先取得用户同意，
运行方式 `uv run --env-file .env pytest -m live --no-cov tests/live/test_live_messages.py`。
每个用例都是一条主动消息（撤回用例两条），占用当天对该用户的主动消息额度。
"""

import logging
import os
from collections.abc import AsyncGenerator

import pytest

import pyqbot

pytestmark = pytest.mark.live
_logger = logging.getLogger("pyqbot.live")
IMAGE_URL = "https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.49.0/assets/img/image-send.35813305.jpg"


@pytest.fixture
def openid() -> str:
    value = os.environ.get("TEST_USER_OPENID")
    if not value:
        pytest.skip("缺少环境变量 TEST_USER_OPENID：用 uv run --env-file .env 运行")
    return value


@pytest.fixture
async def client(app_id: str, app_secret: str) -> AsyncGenerator[pyqbot.Client]:
    async with pyqbot.Client(app_id, app_secret) as client:
        yield client


async def test_markdown(client: pyqbot.Client, openid: str) -> None:
    """应看到：一级标题「pyqbot Markdown」，下面一行粗体、一行斜体、一个可点的链接。"""
    sent = await client.users.send_message(
        openid,
        markdown="# pyqbot Markdown\n\n**粗体** 与 _斜体_\n\n[链接](https://www.qq.com)",
    )

    assert sent.id


async def test_markdown_with_buttons(client: pyqbot.Client, openid: str) -> None:
    """应看到：Markdown 下方两行按钮。

    第一行「回调」（蓝色线框）与「跳转」：点「回调」后按钮文字变成「已回调」（平台会推送
    INTERACTION_CREATE，本用例不连网关、不回应，客户端可能转圈直到超时）；点「跳转」打开 qq.com。
    第二行「指令」（蓝底白字）：点后直接发出「/pyqbot」（`enter=True`）。
    """
    keyboard = pyqbot.Keyboard.from_rows(
        [
            pyqbot.Button.callback(
                "回调", "pyqbot-live", visited_label="已回调", style=pyqbot.ButtonStyle.BLUE_OUTLINE
            ),
            pyqbot.Button.link("跳转", "https://www.qq.com"),
        ],
        [
            pyqbot.Button.command(
                "指令", "/pyqbot", enter=True, style=pyqbot.ButtonStyle.BLUE_FILLED
            )
        ],
    )

    sent = await client.users.send_message(openid, markdown="**带按钮的消息**", keyboard=keyboard)

    assert sent.id


async def test_card(client: pyqbot.Client, openid: str) -> None:
    """应看到：一张图文卡片，标题「pyqbot 卡片」、描述一行、一张图，点击打开 qq.com。

    `pic_url` 用 favicon.ico 时平台报 40034141「图片转存失败」，所以用富媒体实测里能上传的 jpg。
    """
    card = pyqbot.Card(
        title="pyqbot 卡片",
        description="这是一张由实测发出的图文卡片",
        url="https://www.qq.com",
        pic_url=IMAGE_URL,
    )

    sent = await client.users.send_message(openid, card=card)

    assert sent.id


async def test_quote_previous_message(client: pyqbot.Client, openid: str) -> None:
    """应看到：先是「被引用的消息」，紧接着一条以引用形式展示它的「这条引用了上一条」。"""
    first = await client.users.send_message(openid, "被引用的消息")
    assert first.ext_info is not None
    assert first.ext_info.ref_idx

    sent = await client.users.send_message(openid, "这条引用了上一条", quote=first)

    assert sent.id


async def test_typing(client: pyqbot.Client, openid: str) -> None:
    """应看到：机器人显示「正在输入」约 10 秒后消失，期间没有新消息。

    主动发送：官方示例都带 msg_id，平台若拒绝（抛 `APIError`），把错误码记进 errata。
    """
    await client.users.send_typing(openid, seconds=10)


async def test_send_then_recall(client: pyqbot.Client, openid: str) -> None:
    """应看到：「这条马上会被撤回」出现后很快变成撤回提示。"""
    sent = await client.users.send_message(openid, "这条马上会被撤回")

    await client.users.recall_message(openid, sent)


def outcome(error: pyqbot.APIError) -> tuple[int | None, str]:
    return error.err_code, error.message


async def test_quote_by_message_id(client: pyqbot.Client, openid: str) -> None:
    """应看到：「pyqbot：被按消息 ID 引用」，然后一条引用它的消息；被拒就只有第一条，错误码记进日志。

    字段说明要 `REFIDX_` 引用索引，群聊示例填的却是消息 ID；这里把 `SentMessage.id` 当字符串传。
    """
    first = await client.users.send_message(openid, "pyqbot：被按消息 ID 引用")
    try:
        sent = await client.users.send_message(
            openid, "pyqbot：这条按消息 ID 引用了上一条", quote=first.id
        )
        _logger.warning("按消息 ID 引用：被接受 %s", sent.id)
    except pyqbot.APIError as error:
        _logger.warning("按消息 ID 引用：被拒 %s", outcome(error))


async def test_text_with_media_and_card(client: pyqbot.Client, openid: str) -> None:
    """应看到：一张图片与一张卡片，各带一行文字「pyqbot：图片 / 卡片附带的文字」；看文字是否显示。"""
    media = await client.users.upload(openid, url=IMAGE_URL)
    card = pyqbot.Card(
        title="pyqbot 卡片", description="带文字的卡片", url="https://www.qq.com", pic_url=IMAGE_URL
    )
    try:
        sent = await client.users.send_message(openid, "pyqbot：图片附带的文字", media=media)
        _logger.warning("图片带文字：被接受 %s", sent.id)
    except pyqbot.APIError as error:
        _logger.warning("图片带文字：被拒 %s", outcome(error))
    try:
        sent = await client.users.send_message(openid, "pyqbot：卡片附带的文字", card=card)
        _logger.warning("卡片带文字：被接受 %s", sent.id)
    except pyqbot.APIError as error:
        _logger.warning("卡片带文字：被拒 %s", outcome(error))


async def test_wakeup(client: pyqbot.Client, openid: str) -> None:
    """互动召回（`is_wakeup`）：每个周期只能发一条，测一次就占掉当前周期。

    应看到「pyqbot：互动召回实测」；被拒就把错误码记进日志。
    """
    try:
        sent = await client.users.send_message(openid, "pyqbot：互动召回实测", wakeup=True)
        _logger.warning("互动召回：被接受 %s", sent.id)
    except pyqbot.APIError as error:
        _logger.warning("互动召回：被拒 %s", outcome(error))
