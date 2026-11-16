"""通知类事件与互动事件的实测：要测试用户在手机上配合操作，再由人确认客户端里的效果。

确认 `docs/errata.md` 里与这些事件有关的待实测项，尤其是被动回复的 `event_id` 取外层 `id` 还是 `d.id`。
运行前提见 `AGENTS.md`「实测」：每次都要先取得用户同意；每个用例消耗一次网关连接，所以还要 `LIVE_GATEWAY=1`。
`LIVE_WAIT_SECONDS`（默认 180）是连上网关后等测试用户操作的秒数。运行方式：
`LIVE_GATEWAY=1 uv run --env-file .env pytest -m live --no-cov tests/live/test_live_events.py::<用例> -s`。

只处理 `TEST_USER_OPENID` 触发的事件，其他人的只记一笔。每条 Dispatch 的外层 `id` 与 `d.id`（如有）
都记进日志与 `.cache/live/events.txt`（已被 git 忽略），不含 openid；原始的 `d` 另存进
`.cache/live/raw/`（含 openid，只留在本机）。
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
RAW_DIR = OUTPUT.parent / "raw"
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
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(data, ensure_ascii=False, indent=2)
        (RAW_DIR / f"event_{payload.t}_{payload.s}.json").write_text(raw, encoding="utf-8")
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
            "scene_param": event.scene_param,
            "short_code": event.short_code,
        }
        sent = await event.reply("pyqbot：欢迎回来")
        outcome["sent"] = sent.id
        await bot.close()

    await run_until_closed(bot, wait_seconds, outcome)

    note("friend_del_then_add", outcome)
    assert "sent" in outcome, outcome  # 已经删过时只加回也行，FRIEND_DEL 有就记下


async def test_c2c_msg_reject_then_receive(
    app_id: str,
    app_secret: str,
    openid: str,
    wait_seconds: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """让测试用户在机器人资料卡里关闭「主动消息」，再打开。

    文档说应收到 `C2C_MSG_REJECT`、`C2C_MSG_RECEIVE` 各一条，打开后用 event_id 被动回复
    「pyqbot：主动消息已打开」。2026-11-16 实测平台没有推这两个事件，只推了 `type=18`（用户授权）的
    `INTERACTION_CREATE`：最后一条授权互动之后 15 秒没有新的（测试用户切换完了），就用它被动回复
    「pyqbot：授权已变更」，看平台是否接受。授权数据记进日志，原始事件见 `.cache/live/raw/`。
    """
    bot = pyqbot.Bot(app_id, app_secret)
    record_event_ids(bot, monkeypatch)
    outcome: dict[str, object] = {}
    interactions: list[object] = []
    outcome["interactions"] = interactions
    pending: list[asyncio.Task[None]] = []

    async def reply_after_quiet(event: pyqbot.Interaction) -> None:
        await asyncio.sleep(15)
        try:
            sent = await event.reply("pyqbot：授权已变更")
            outcome["authorize_reply"] = sent.id
        except pyqbot.APIError as error:
            outcome["authorize_reply_error"] = {
                "err_code": error.err_code,
                "message": error.message,
            }
        await bot.close()

    @bot.on_interaction
    async def authorized(event: pyqbot.Interaction) -> None:
        if event.user_openid != openid:
            note("interaction.ignored", "不是测试用户")
            return
        authorize = event.data.resolved.authorize_data
        interactions.append(
            {
                "type": event.type,
                "chat_type": event.chat_type,
                "scene": event.scene,
                "data_type": event.data.type,
                "authorize": authorize.to_dict() if authorize is not None else None,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            }
        )
        if event.type == pyqbot.InteractionType.USER_AUTHORIZE:
            for task in pending:
                task.cancel()
            pending[:] = [asyncio.create_task(reply_after_quiet(event))]

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
        for task in pending:
            task.cancel()
        sent = await event.reply("pyqbot：主动消息已打开")
        outcome["sent"] = sent.id
        await bot.close()

    await run_until_closed(bot, wait_seconds, outcome)
    for task in pending:
        task.cancel()

    note("c2c_msg_reject_then_receive", outcome)
    assert "sent" in outcome or "authorize_reply" in outcome, outcome


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


# ---- 测试群：入群与 @ 消息 ----

GROUP_FILE = OUTPUT.parent / "test_group.env"


async def test_group_add_robot(
    app_id: str, app_secret: str, wait_seconds: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    """让测试用户把机器人拉进测试群；运行期间不要把它拉进别的群。

    应收到 `GROUP_ADD_ROBOT`，机器人用 event_id 在群里被动回复「pyqbot：已加入，用于 SDK 实测」。
    群的 openid 与拉人的成员写进 `.cache/live/test_group.env`，供群用例的 `TEST_GROUP_OPENID` 使用。
    """
    bot = pyqbot.Bot(app_id, app_secret)
    record_event_ids(bot, monkeypatch)
    outcome: dict[str, object] = {}

    @bot.on_group_add_robot
    async def joined(event: pyqbot.GroupAddRobot) -> None:
        if "add" in outcome:
            note("group_add_robot.ignored", "只认第一个入群事件")
            return
        outcome["add"] = {"event_id": event.event_id, "timestamp": event.timestamp}
        GROUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        GROUP_FILE.write_text(
            f"TEST_GROUP_OPENID={event.group_openid}\n"
            f"# 拉机器人进群的成员：{event.op_member_openid}\n",
            encoding="utf-8",
        )
        sent = await event.reply("pyqbot：已加入，用于 SDK 实测")
        outcome["sent"] = sent.id
        await bot.close()

    await run_until_closed(bot, wait_seconds, outcome)

    note("group_add_robot", outcome)
    assert "sent" in outcome, outcome


async def test_group_at_message(
    app_id: str, app_secret: str, wait_seconds: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    """让测试群里的成员 @机器人 发「/ping」。

    应看到机器人被动回复「pyqbot：pong」。日志里看 `content` 的原样（官方示例带首尾空格）、`author`
    有哪些字段与 `member_role`，以及同一条消息是否另推了全量的 `GROUP_MESSAGE_CREATE`（要有接收全部
    消息的权限）。发消息成员的 openid 追加进 `.cache/live/test_group.env`，供禁言等用例挑选。
    """
    group = os.environ.get("TEST_GROUP_OPENID")
    if not group:
        pytest.skip("缺少环境变量 TEST_GROUP_OPENID：先跑 test_group_add_robot")
    bot = pyqbot.Bot(app_id, app_secret)
    record_event_ids(bot, monkeypatch)
    all_messages: list[object] = []
    outcome: dict[str, object] = {"all_messages": all_messages}

    @bot.on_group_message
    async def any_message(message: pyqbot.GroupMessage) -> None:
        if message.group_openid == group:
            all_messages.append({"id": message.id, "content": message.content})

    @bot.on_group_at_message
    async def mentioned(message: pyqbot.GroupAtMessage) -> None:
        if message.group_openid != group:
            note("group_at_message.ignored", "不是测试群")
            return
        author = message.author.to_dict()
        outcome["at"] = {
            "id": message.id,
            "content": message.content,
            "author_keys": sorted(author),
            "member_role": message.author.member_role,
            "message_type": message.message_type,
            # ext 里有 auth_token，只记键名
            "scene_ext_keys": [item.split("=")[0] for item in message.message_scene.ext]
            if message.message_scene
            else None,
        }
        with GROUP_FILE.open("a", encoding="utf-8") as file:
            file.write(f"# @ 机器人的成员：{message.author.member_openid}\n")
        sent = await message.reply("pyqbot：pong")
        outcome["sent"] = sent.id
        await asyncio.sleep(5)  # 等同一条消息的全量事件（如果有）
        await bot.close()

    await run_until_closed(bot, wait_seconds, outcome)

    note("group_at_message", outcome)
    assert "sent" in outcome, outcome
