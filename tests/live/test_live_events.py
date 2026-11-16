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
import struct
import zlib
from collections.abc import Awaitable
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
        note(
            "dispatch",
            {"t": payload.t, "outer_id": payload.id, "d_id": inner, "bytes": len(payload.data)},
        )
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

    处理函数不自己回应，还故意等 3 秒才回复，验证 `Bot` 默认的自动回应：应看到点后按钮立刻变成「已点」，
    约 3 秒后收到被动回复「pyqbot：你点了 pyqbot-live-click-…」（每次运行的标识不同）。只认测试用户对本次按钮
    的点击，其它互动只记一笔。占用一条主动消息额度。
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
        await asyncio.sleep(3)  # 回应已由 SDK 先发出；超过客户端约 1 秒的等待也不影响
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


async def test_multi_image_message(
    app_id: str,
    app_secret: str,
    openid: str,
    wait_seconds: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """让测试用户在电脑上一次选多张图发给机器人（手机上会拆成每张一条）。

    记下每条单聊消息的附件数、类型与 `d` 的字节数；收到附件不止一个的消息就结束，机器人不回复。
    """
    bot = pyqbot.Bot(app_id, app_secret)
    record_event_ids(bot, monkeypatch)
    messages: list[object] = []
    outcome: dict[str, object] = {"messages": messages}

    @bot.on_c2c_message
    async def received(message: pyqbot.C2CMessage) -> None:
        if message.user_openid != openid:
            return
        messages.append(
            {
                "content": message.content,
                "attachments": [a.content_type for a in message.attachments],
                "sizes": [(a.width, a.height, a.size) for a in message.attachments],
            }
        )
        if len(message.attachments) > 1:
            await bot.close()

    await run_until_closed(bot, wait_seconds, outcome)

    note("multi_image_message", outcome)
    assert messages, outcome


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


# ---- 单聊：被动回复的次数与期限、纯文本流式、回应互动的期限 ----


def api_outcome(error: pyqbot.APIError) -> tuple[int | None, str]:
    return error.err_code, error.message


async def test_c2c_reply_limit_and_plain_stream(
    app_id: str,
    app_secret: str,
    openid: str,
    wait_seconds: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """让测试用户先后发两条单聊。

    第一条：机器人先用它发「正在输入」（占 `msg_seq` 1），再被动回复 4 条（`msg_seq` 2～5）。文档说每条消息可以
    被动回复 4 次：看「正在输入」算不算一次、第 4 条回复是否失败。
    第二条：用 `reply_stream(markdown=False)` 流式回复「pyqbot 纯文本流式：**这几个字不应加粗**」，看 `**`
    是否按原文显示。
    """
    bot = pyqbot.Bot(app_id, app_secret)
    record_event_ids(bot, monkeypatch)
    outcome: dict[str, object] = {}

    @bot.on_c2c_message
    async def received(message: pyqbot.C2CMessage) -> None:
        if message.user_openid != openid:
            return
        if "replies" not in outcome:
            replies: list[object] = []
            outcome["replies"] = replies
            try:
                await bot.users.send_typing(openid, seconds=5, reply_to=message)
                replies.append(("正在输入", "被接受"))
            except pyqbot.APIError as error:
                replies.append(("正在输入", api_outcome(error)))
            for i in range(1, 5):
                try:
                    await message.reply(f"pyqbot：第 {i} 条被动回复")
                    replies.append((i, "被接受"))
                except pyqbot.APIError as error:
                    replies.append((i, api_outcome(error)))
            return
        try:
            async with message.reply_stream(markdown=False) as stream:
                for piece in ("pyqbot 纯文本流式：", "**这几个字不应加粗**"):
                    await stream.append(piece)
                    await asyncio.sleep(1)
            outcome["plain_stream"] = "被接受"
        except pyqbot.APIError as error:
            outcome["plain_stream"] = api_outcome(error)
        await bot.close()

    await run_until_closed(bot, wait_seconds, outcome)

    note("c2c_reply_limit_and_plain_stream", outcome)
    assert "plain_stream" in outcome, outcome


async def test_c2c_reply_after_10_and_55_minutes(
    app_id: str,
    app_secret: str,
    openid: str,
    wait_seconds: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """让测试用户发一条单聊；机器人记下后断开网关，约 10 分钟、约 55 分钟后各用它被动回复一次。

    文档对单聊被动回复的有效期一处写 5 分钟、一处写 60 分钟。整个用例约 56 分钟，适合在后台跑。
    测试用户应先后收到「pyqbot：10 分钟后的被动回复」「pyqbot：55 分钟后的被动回复」，被拒的那条收不到。
    """
    bot = pyqbot.Bot(app_id, app_secret)
    record_event_ids(bot, monkeypatch)
    received: list[tuple[pyqbot.C2CMessage, float]] = []
    outcome: dict[str, object] = {}

    @bot.on_c2c_message
    async def got(message: pyqbot.C2CMessage) -> None:
        if message.user_openid == openid and not received:
            received.append((message, asyncio.get_running_loop().time()))
            await bot.close()

    await run_until_closed(bot, wait_seconds, outcome)
    assert received, outcome
    message, received_at = received[0]

    loop = asyncio.get_running_loop()
    async with pyqbot.Client(app_id, app_secret) as client:
        for minutes in (10, 55):
            await asyncio.sleep(max(0.0, received_at + minutes * 60 - loop.time()))
            try:
                await client.users.send_message(
                    openid, f"pyqbot：{minutes} 分钟后的被动回复", reply_to=message
                )
                outcome[f"{minutes} 分钟"] = "被接受"
            except pyqbot.APIError as error:
                outcome[f"{minutes} 分钟"] = api_outcome(error)
            note("c2c_reply_after_minutes", outcome)


async def test_interaction_ack_timing_and_event_ids(
    app_id: str,
    app_secret: str,
    openid: str,
    wait_seconds: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主动发一条带「晚回应」「快回应」两个回调按钮的 Markdown，让测试用户先点「晚回应」、再点「快回应」。

    「晚回应」：5 秒后才回应，看是否报错（文档只在一处写了 3 秒期限）。
    「快回应」：1 秒后回应，再回应第二次，记下错误码；然后用不带前缀的 `d.id` 作 `event_id` 被动回复一条，
    再用外层 `id` 连续被动回复两条（`msg_seq` 1、2）。测试用户应收到最多三条「pyqbot：…」回复。
    """
    bot = pyqbot.Bot(app_id, app_secret, auto_ack=False)  # 自己按时回应
    record_event_ids(bot, monkeypatch)
    tag = secrets.token_hex(4)
    slow, fast = f"pyqbot-slow-{tag}", f"pyqbot-fast-{tag}"
    outcome: dict[str, object] = {}

    @bot.on_interaction
    async def clicked(event: pyqbot.Interaction) -> None:
        if event.user_openid != openid or event.button_data not in (slow, fast):
            return
        if event.button_data == slow:
            await asyncio.sleep(5)
            try:
                await event.ack()
                outcome["slow_ack"] = "被接受"
            except pyqbot.APIError as error:
                outcome["slow_ack"] = api_outcome(error)
        else:
            await asyncio.sleep(1)
            results: dict[str, object] = {}
            for label in ("ack", "second_ack"):
                try:
                    await event.ack()
                    results[label] = "被接受"
                except pyqbot.APIError as error:
                    results[label] = api_outcome(error)
            token = await bot.get_access_token()
            response = await bot.http_client.post(
                f"{bot.config.base_url}/v2/users/{openid}/messages",
                headers={"Authorization": f"QQBot {token}"},
                json={
                    "content": "pyqbot：用不带前缀的 d.id 被动回复",
                    "msg_type": 0,
                    "event_id": event.id,
                    "msg_seq": 1,
                },
                timeout=30,
            )
            body = cast(dict[str, object], response.json())
            results["reply_with_d_id"] = (
                response.status_code,
                body.get("err_code") or body.get("code") or "被接受",
                body.get("message"),
            )
            for i in (1, 2):
                try:
                    await event.reply(f"pyqbot：用外层 id 被动回复第 {i} 条")
                    results[f"outer_id_reply_{i}"] = "被接受"
                except pyqbot.APIError as error:
                    results[f"outer_id_reply_{i}"] = api_outcome(error)
            outcome["fast"] = results
        if "slow_ack" in outcome and "fast" in outcome:
            await bot.close()

    keyboard = pyqbot.Keyboard.from_rows(
        [
            pyqbot.Button.callback("晚回应", slow, visited_label="已点晚回应"),
            pyqbot.Button.callback("快回应", fast, visited_label="已点快回应"),
        ]
    )
    async with bot:
        await bot.users.send_message(
            openid,
            markdown="**pyqbot 回应期限实测**：先点「晚回应」，再点「快回应」",
            keyboard=keyboard,
        )
        try:
            async with asyncio.timeout(wait_seconds):
                await bot.start()
        except TimeoutError:
            outcome["timeout"] = f"{wait_seconds} 秒内没有等到测试用户点完两个按钮"

    note("interaction_ack_timing_and_event_ids", outcome)
    assert "fast" in outcome, outcome


async def test_interaction_ack_threshold(
    app_id: str,
    app_secret: str,
    openid: str,
    wait_seconds: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主动发一条带四个回调按钮的 Markdown，按钮分别在收到点击后 0、0.3、0.6、1 秒回应。

    让测试用户逐个点，告诉我们哪些变成「已点」、哪些提示失败。2026-11-16 隔 1 秒和 5 秒回应时，接口都返回成功，
    客户端却都显示「请求第三方失败」。日志里记下每个按钮从收到事件到回应完成的实际耗时。
    """
    bot = pyqbot.Bot(app_id, app_secret, auto_ack=False)  # 自己按时回应
    record_event_ids(bot, monkeypatch)
    tag = secrets.token_hex(4)
    delays = {f"pyqbot-ack-{tag}-{delay}": delay for delay in (0.0, 0.3, 0.6, 1.0)}
    outcome: dict[str, object] = {}
    loop = asyncio.get_running_loop()

    @bot.on_interaction
    async def clicked(event: pyqbot.Interaction) -> None:
        delay = delays.get(event.button_data or "")
        if event.user_openid != openid or delay is None:
            return
        received = loop.time()
        await asyncio.sleep(delay)
        try:
            await event.ack()
            result: object = "被接受"
        except pyqbot.APIError as error:
            result = api_outcome(error)
        outcome[f"{delay} 秒"] = (result, f"实际 {loop.time() - received:.2f} 秒")
        if len(outcome) == len(delays):
            await bot.close()

    keyboard = pyqbot.Keyboard.from_rows(
        [
            pyqbot.Button.callback(f"{delay} 秒", data, visited_label=f"已点 {delay}")
            for data, delay in delays.items()
        ]
    )
    async with bot:
        await bot.users.send_message(
            openid, markdown="**pyqbot 回应阈值实测**：从左到右逐个点", keyboard=keyboard
        )
        try:
            async with asyncio.timeout(wait_seconds):
                await bot.start()
        except TimeoutError:
            outcome["timeout"] = f"{wait_seconds} 秒内没有点完四个按钮"

    note("interaction_ack_threshold", outcome)
    assert len(outcome) >= len(delays), outcome


# ---- 测试群：按钮、富媒体、撤回与通知事件 ----

IMAGE_URL = "https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.49.0/assets/img/image-send.35813305.jpg"


def noise_png(width: int, height: int) -> bytes:
    """随机噪点的 RGB PNG，几乎不可压缩，用来凑出走分片上传的大小。"""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    raw = b"".join(b"\x00" + os.urandom(width * 3) for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def group_or_skip() -> str:
    group = os.environ.get("TEST_GROUP_OPENID")
    if not group:
        pytest.skip("缺少环境变量 TEST_GROUP_OPENID：先跑 test_group_add_robot")
    return group


async def test_group_message_features(
    app_id: str, app_secret: str, wait_seconds: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    """让测试群里的成员 @机器人 发一条消息，机器人用它依次被动回复三条：

    1. Markdown 加两个按钮：「回调」与「指令」（`enter=True`，文档说只在单聊直接发出）。
    2. 用 `message.upload(url=...)` 上传的图片，带文字「pyqbot：群图片」。
    3. 约 3.6 MB 的噪点图，走群的分片上传，发出 10 秒后撤回。
    然后测试用户点「回调」：SDK 自动回应，再用互动的 event_id 被动回复「pyqbot：群里点了回调」；再点「指令」，看是直接
    发出「/pyqbot-enter」（会推来新的 @ 消息，机器人回复「pyqbot：收到指令按钮发出的消息」）还是只填进输入框。
    """
    group = group_or_skip()
    bot = pyqbot.Bot(app_id, app_secret)
    record_event_ids(bot, monkeypatch)
    tag = f"pyqbot-group-{secrets.token_hex(4)}"
    outcome: dict[str, object] = {}

    async def attempt(label: str, results: dict[str, object], action: Awaitable[object]) -> object:
        try:
            value = await action
            results[label] = "被接受"
            return value
        except pyqbot.APIError as error:
            results[label] = api_outcome(error)
            return None

    @bot.on_group_at_message
    async def mentioned(message: pyqbot.GroupAtMessage) -> None:
        if message.group_openid != group:
            return
        if "replies" in outcome:
            outcome["second_message"] = message.content
            await attempt("reply", outcome, message.reply("pyqbot：收到指令按钮发出的消息"))
            return
        results: dict[str, object] = {}
        outcome["replies"] = results
        keyboard = pyqbot.Keyboard.from_rows(
            [
                pyqbot.Button.callback("回调", tag, visited_label="已回调"),
                pyqbot.Button.command("指令", "/pyqbot-enter", enter=True),
            ]
        )
        await attempt(
            "markdown_keyboard",
            results,
            message.reply(
                markdown="**pyqbot 群按钮实测**：先点「回调」，再点「指令」", keyboard=keyboard
            ),
        )
        media = await attempt("upload_url", results, message.upload(url=IMAGE_URL))
        if isinstance(media, pyqbot.Media):
            await attempt("reply_image", results, message.reply("pyqbot：群图片", media=media))
        big = await attempt(
            "upload_in_parts",
            results,
            message.upload(data=noise_png(1200, 1000), file_name="pyqbot-noise.png"),
        )
        if isinstance(big, pyqbot.Media):
            sent = await attempt(
                "reply_big_image",
                results,
                message.reply("pyqbot：群分片上传，10 秒后撤回", media=big),
            )
            if isinstance(sent, pyqbot.SentMessage):
                await asyncio.sleep(10)
                await attempt("recall", results, bot.groups.recall_message(group, sent))

    @bot.on_interaction
    async def clicked(event: pyqbot.Interaction) -> None:
        if event.group_openid != group or event.button_data != tag:
            return
        results: dict[str, object] = {
            "type": event.type,
            "chat_type": event.chat_type,
            "scene": event.scene,
            "event_id_prefix": (event.event_id or "").split(":")[0],
        }
        outcome["interaction"] = results  # 回应由 SDK 自动发出
        await attempt("reply", results, event.reply("pyqbot：群里点了回调"))

    await run_until_closed(bot, wait_seconds, outcome)

    note("group_message_features", outcome)
    assert "replies" in outcome, outcome


async def test_group_notices(
    app_id: str, app_secret: str, wait_seconds: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    """等满 `LIVE_WAIT_SECONDS`，记下测试群里由人触发的通知事件；做了哪项就记哪项，都可选：

    有人进群、退群；在群设置里关闭再打开机器人的主动消息；把机器人移出群再拉回来。
    只在机器人被拉回时被动回复「pyqbot：已重新加入」，其余不回复。授权类互动（`type` 19、20）也一并记下。
    """
    group = group_or_skip()
    bot = pyqbot.Bot(app_id, app_secret)
    record_event_ids(bot, monkeypatch)
    seen: list[object] = []
    outcome: dict[str, object] = {"seen": seen}

    def remember(kind: str, event: object, **extra: object) -> None:
        seen.append({"kind": kind, **extra})
        note(f"group_notice.{kind}", extra)

    @bot.on_group_member_add
    async def member_added(event: pyqbot.GroupMemberAdd) -> None:
        if event.group_openid == group:
            remember("member_add", event, event_id=event.event_id)

    @bot.on_group_member_remove
    async def member_removed(event: pyqbot.GroupMemberRemove) -> None:
        if event.group_openid == group:
            remember("member_remove", event, has_user_openid=bool(event.user_openid))

    @bot.on_group_msg_reject
    async def rejected(event: pyqbot.GroupMsgReject) -> None:
        if event.group_openid == group:
            remember("msg_reject", event)

    @bot.on_group_msg_receive
    async def accepted(event: pyqbot.GroupMsgReceive) -> None:
        if event.group_openid == group:
            remember("msg_receive", event, event_id=event.event_id)

    @bot.on_group_del_robot
    async def removed(event: pyqbot.GroupDelRobot) -> None:
        if event.group_openid == group:
            remember("del_robot", event)

    @bot.on_group_add_robot
    async def added(event: pyqbot.GroupAddRobot) -> None:
        if event.group_openid != group:
            return
        try:
            await event.reply("pyqbot：已重新加入")
            remember("add_robot", event, reply="被接受")
        except pyqbot.APIError as error:
            remember("add_robot", event, reply=api_outcome(error))

    @bot.on_interaction
    async def authorized(event: pyqbot.Interaction) -> None:
        if event.group_openid != group:
            return
        authorize = event.data.resolved.authorize_data
        remember(
            "interaction",
            event,
            type=event.type,
            chat_type=event.chat_type,
            scene=event.scene,
            authorize=authorize.to_dict() if authorize else None,
        )

    await run_until_closed(bot, wait_seconds, outcome)

    note("group_notices", outcome)
