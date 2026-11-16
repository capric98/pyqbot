"""通知类事件与互动事件的实测：要测试用户在手机上配合操作，再由人确认客户端里的效果。

确认 `docs/errata.md` 里与这些事件有关的待实测项，尤其是被动回复的 `event_id` 取外层 `id` 还是 `d.id`。
运行前提见 `AGENTS.md`「实测」：每次都要先取得用户同意；每个用例消耗一次网关连接，所以还要 `LIVE_GATEWAY=1`。
`LIVE_WAIT_SECONDS`（默认 180）是连上网关后等测试用户操作的秒数。运行方式：
`LIVE_GATEWAY=1 uv run --env-file .env pytest -m live --no-cov tests/live/test_live_events.py::<用例> -s`。

只处理 `TEST_USER_OPENID` 触发的事件，其他人的只记一笔。每条 Dispatch 的外层 `id` 与 `d.id`（如有）
都记进日志与 `.cache/live/events.txt`（已被 git 忽略），不含 openid 与消息内容。
"""

import asyncio
import json
import logging
import os
import secrets
from pathlib import Path
from typing import cast

import pytest

import pyqbot
from pyqbot._gateway.payload import GatewayPayload

pytestmark = pytest.mark.live

OUTPUT = Path(__file__).parents[2] / ".cache" / "live" / "events.txt"
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
    return float(os.environ.get("LIVE_WAIT_SECONDS", "180"))


def note(title: str, value: object) -> None:
    line = f"{title}: {json.dumps(value, ensure_ascii=False)}"
    _logger.warning("%s", line)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("a", encoding="utf-8") as report:
        report.write(line + "\n")


def record_event_ids(bot: pyqbot.Bot, monkeypatch: pytest.MonkeyPatch) -> None:
    """在分发之前记下每条 Dispatch 的外层 `id` 与 `d.id`，用来回答 errata 里「event_id 取哪个」。"""
    dispatcher = bot._dispatcher  # pyright: ignore[reportPrivateUsage]  实测要看原始 payload
    dispatch = dispatcher.dispatch

    def recording(payload: GatewayPayload, client: pyqbot.Client) -> None:
        data: object = json.loads(payload.data)
        inner = cast(dict[str, object], data).get("id") if isinstance(data, dict) else None
        note("dispatch", {"t": payload.t, "outer_id": payload.id, "d_id": inner})
        dispatch(payload, client)

    monkeypatch.setattr(dispatcher, "dispatch", recording)


async def run_until_closed(
    bot: pyqbot.Bot, wait_seconds: float, outcome: dict[str, object]
) -> None:
    async with bot:
        try:
            async with asyncio.timeout(wait_seconds):
                await bot.start()
        except TimeoutError:
            outcome["timeout"] = f"{wait_seconds} 秒内没有等到测试用户的操作"


async def test_friend_del_then_add(
    app_id: str,
    app_secret: str,
    openid: str,
    wait_seconds: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """让测试用户在 QQ 里删除机器人好友，再重新添加。

    应收到 `FRIEND_DEL`、`FRIEND_ADD` 各一条；加回后测试用户应看到机器人用 event_id 被动回复的
    「pyqbot：欢迎回来」。日志里看两条事件的外层 `id` 与 `d.id`，以及 `FRIEND_ADD` 的 `scene`。
    """
    bot = pyqbot.Bot(app_id, app_secret)
    record_event_ids(bot, monkeypatch)
    outcome: dict[str, object] = {}

    @bot.on_friend_del
    async def removed(event: pyqbot.FriendDel) -> None:
        if event.openid != openid:
            note("friend_del.ignored", "不是测试用户")
            return
        outcome["del"] = {
            "event_id": event.event_id,
            "has_union_openid": bool(event.author.union_openid),
        }

    @bot.on_friend_add
    async def added(event: pyqbot.FriendAdd) -> None:
        if event.openid != openid:
            note("friend_add.ignored", "不是测试用户")
            return
        outcome["add"] = {
            "event_id": event.event_id,
            "scene": event.scene,
            "short_code": event.short_code,
        }
        sent = await event.reply("pyqbot：欢迎回来")
        outcome["sent"] = sent.id
        await bot.close()

    await run_until_closed(bot, wait_seconds, outcome)

    note("friend_del_then_add", outcome)
    assert "del" in outcome, outcome
    assert "sent" in outcome, outcome


async def test_c2c_msg_reject_then_receive(
    app_id: str,
    app_secret: str,
    openid: str,
    wait_seconds: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """让测试用户在机器人资料卡里关闭「主动消息」，再打开。

    应收到 `C2C_MSG_REJECT`、`C2C_MSG_RECEIVE` 各一条；打开后测试用户应看到机器人用 event_id 被动回复的
    「pyqbot：主动消息已打开」。日志里看两条事件的外层 `id` 与 `d.id`，以及切换开关时有没有推送
    `type=18`（用户授权）的 `INTERACTION_CREATE`、它带不带 `chat_type`。同时订阅了互动，需要该权限。
    """
    bot = pyqbot.Bot(app_id, app_secret)
    record_event_ids(bot, monkeypatch)
    outcome: dict[str, object] = {}
    interactions: list[object] = []
    outcome["interactions"] = interactions

    @bot.on_interaction
    async def authorized(event: pyqbot.Interaction) -> None:
        if event.user_openid != openid:
            note("interaction.ignored", "不是测试用户")
            return
        interactions.append(
            {"type": event.type, "chat_type": event.chat_type, "data_type": event.data.type}
        )

    @bot.on_c2c_msg_reject
    async def rejected(event: pyqbot.C2CMsgReject) -> None:
        if event.openid != openid:
            note("c2c_msg_reject.ignored", "不是测试用户")
            return
        outcome["reject"] = {"event_id": event.event_id, "timestamp": event.timestamp}

    @bot.on_c2c_msg_receive
    async def received(event: pyqbot.C2CMsgReceive) -> None:
        if event.openid != openid:
            note("c2c_msg_receive.ignored", "不是测试用户")
            return
        outcome["receive"] = {"event_id": event.event_id, "timestamp": event.timestamp}
        sent = await event.reply("pyqbot：主动消息已打开")
        outcome["sent"] = sent.id
        await bot.close()

    await run_until_closed(bot, wait_seconds, outcome)

    note("c2c_msg_reject_then_receive", outcome)
    assert "reject" in outcome, outcome
    assert "sent" in outcome, outcome


async def test_callback_button_interaction(
    app_id: str,
    app_secret: str,
    openid: str,
    wait_seconds: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """向测试用户主动发一条带回调按钮的 Markdown，让他点「点我」。

    应看到：点后按钮不再转圈、文字变成「已点」（`ack()` 生效），随后收到被动回复「pyqbot：你点了
    pyqbot-live-click-…」（每次运行的标识不同）。只认测试用户对本次按钮的点击，其它互动只记一笔。日志里看 `INTERACTION_CREATE` 的外层 `id` 与 `d.id` 是否不同、是否带
    `INTERACTION_CREATE:` 前缀；被动回复用的是外层 `id`，被拒时把错误码记进 errata。占用一条主动消息额度。
    """
    bot = pyqbot.Bot(app_id, app_secret)
    record_event_ids(bot, monkeypatch)
    outcome: dict[str, object] = {}
    button_data = (
        f"pyqbot-live-click-{secrets.token_hex(4)}"  # 区分本次运行的按钮与旧消息、其它互动
    )

    @bot.on_interaction
    async def clicked(event: pyqbot.Interaction) -> None:
        if event.user_openid != openid:
            note("interaction.ignored", "不是测试用户")
            return
        if event.type != pyqbot.InteractionType.INLINE_KEYBOARD or event.button_data != button_data:
            note("interaction.unrelated", {"type": event.type, "chat_type": event.chat_type})
            return
        outcome["interaction"] = {
            "event_id": event.event_id,
            "id": event.id,
            "type": event.type,
            "chat_type": event.chat_type,
            "data_type": event.data.type,
        }
        await event.ack()
        outcome["acked"] = True
        sent = await event.reply(f"pyqbot：你点了 {event.button_data}")
        outcome["sent"] = sent.id
        await bot.close()

    keyboard = pyqbot.Keyboard.from_rows(
        [pyqbot.Button.callback("点我", button_data, visited_label="已点")]
    )
    async with bot:
        await bot.users.send_message(
            openid, markdown="**pyqbot 互动实测**：请点下面的按钮", keyboard=keyboard
        )
        try:
            async with asyncio.timeout(wait_seconds):
                await bot.start()
        except TimeoutError:
            outcome["timeout"] = f"{wait_seconds} 秒内没有等到测试用户点击"

    note("callback_button_interaction", outcome)
    assert "sent" in outcome, outcome
