"""对真实接口的实测，用来确认 `docs/errata.md` 里的待实测项。运行前提见 `AGENTS.md`「实测」。

只读的几项直接运行：`uv run --env-file .env pytest -m live --no-cov`。
有额外代价的要显式打开：`LIVE_WRONG_SECRET=1`（一次失败的鉴权）、`LIVE_GATEWAY=1`（每个用例消耗一次
网关连接次数）；`LIVE_WAIT_SECONDS` 是连上网关后等待一条单聊消息的秒数。

观察结果写到 `.cache/live/`（已被 git 忽略）：`report.txt` 是脱敏后的结构，字符串只留长度，可以贴出来；
`raw/` 是去掉 token 的原始数据，含 openid 与消息内容，只留在本机。
"""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from time import monotonic
from typing import cast

import httpx2
import pytest
from httpx2.websockets import AsyncWebSocketSession, WebSocketDisconnect, WebSocketNetworkError

import pyqbot
from pyqbot._gateway.close_codes import classify_close_code
from pyqbot._gateway.payload import (
    READY_EVENT,
    RESUMED_EVENT,
    GatewayPayload,
    Hello,
    OpCode,
    Ready,
    decode_payload,
    encode_heartbeat,
    encode_identify,
    encode_resume,
)
from pyqbot._redact import redact

pytestmark = pytest.mark.live

OUTPUT_DIR = Path(__file__).parents[2] / ".cache" / "live"
API_BASE = "https://api.bot.qq.com"
TOKEN_URL = API_BASE + "/app/getAppAccessToken"
WRONG_SECRET = "pyqbot-live-test-wrong-secret"
REPLY_TIMEOUT = 15.0  # 秒：等网关对 Identify / Resume 的答复
C2C_MESSAGE_EVENT = "C2C_MESSAGE_CREATE"

_TOKEN_KEYS = frozenset({"access_token", "token"})
# 这些键的字符串值不敏感，原样显示才看得出格式。
_SHOWN_TEXT_KEYS = frozenset({"t", "url", "message", "reason", "expires_in", "code", "timestamp"})


class ConnectionClosedError(Exception):
    """网关连接已断开，关闭码已经记进 report.txt。"""


def require_flag(name: str) -> None:
    if os.environ.get(name) != "1":
        pytest.skip(f"需要显式设置 {name}=1")


def outline(value: object, *secrets: str) -> object:
    """脱敏后的结构：键名保留，字符串只留长度，数字与布尔原样。"""
    if isinstance(value, dict):
        items = cast(dict[str, object], value)
        return {key: _outline_field(key, item, secrets) for key, item in items.items()}
    if isinstance(value, list):
        return [outline(item, *secrets) for item in cast(list[object], value)]
    if isinstance(value, str):
        return f"<str len={len(value)}>"
    return value


def _outline_field(key: str, value: object, secrets: tuple[str, ...]) -> object:
    if isinstance(value, str) and key in _SHOWN_TEXT_KEYS:
        return redact(value, *secrets)
    if isinstance(value, int) and not isinstance(value, bool) and key.endswith("id"):
        return "<int>"
    return outline(value, *secrets)


def scrub(value: object) -> object:
    """落盘用：去掉 token，其余原样。"""
    if isinstance(value, dict):
        items = cast(dict[str, object], value)
        return {
            key: "<token>" if key in _TOKEN_KEYS else scrub(item) for key, item in items.items()
        }
    if isinstance(value, list):
        return [scrub(item) for item in cast(list[object], value)]
    return value


def note(title: str, value: object) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIR / "report.txt").open("a", encoding="utf-8") as report:
        report.write(f"{title}: {json.dumps(value, ensure_ascii=False)}\n")


def save_raw(name: str, value: object) -> None:
    raw_dir = OUTPUT_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(scrub(value), ensure_ascii=False, indent=2)
    (raw_dir / f"{name}.json").write_text(text, encoding="utf-8")


def note_response(name: str, response: httpx2.Response, *secrets: str) -> object:
    try:
        body: object = response.json()
    except ValueError:
        body = f"<非 JSON，{len(response.content)} 字节>"
    note(
        name,
        {
            "status": response.status_code,
            "has_trace_header": "X-Tps-trace-ID" in response.headers,
            "body": outline(body, *secrets),
        },
    )
    save_raw(name, body)
    return body


def note_payload(label: str, payload: GatewayPayload, *secrets: str) -> None:
    data: object = json.loads(payload.data)
    note(
        label,
        {"op": payload.op.name, "s": payload.s, "t": payload.t, "d": outline(data, *secrets)},
    )
    if payload.op == OpCode.DISPATCH:
        save_raw(f"event_{payload.t}", data)


async def test_token_success_response(app_id: str, app_secret: str) -> None:
    async with httpx2.AsyncClient() as http:
        response = await http.post(
            "https://api.bot.qq.com/app/getAppAccessToken",
            json={"appId": app_id, "clientSecret": app_secret},
            timeout=30,
        )

    body = note_response("token_success", response, app_secret)

    assert response.status_code == 200
    assert isinstance(body, dict)
    assert "access_token" in body


async def test_sdk_token_works_for_read_only_endpoints(app_id: str, app_secret: str) -> None:
    async with pyqbot.Client(app_id, app_secret) as client:
        token = await client.get_access_token()
        for name, path in (
            ("users_me", "/users/@me"),
            ("gateway", "/gateway"),
            ("gateway_bot", "/gateway/bot"),
        ):
            response = await client.http_client.get(
                client.config.base_url + path,
                headers={"Authorization": f"QQBot {token}"},
                timeout=client.config.timeout,
            )
            note_response(name, response, app_secret, token)
            assert response.status_code == 200, name


async def test_wrong_secret_error(app_id: str) -> None:
    require_flag("LIVE_WRONG_SECRET")
    seen: list[httpx2.Response] = []

    async def keep(response: httpx2.Response) -> None:
        await response.aread()
        seen.append(response)

    # 只发一次请求：用事件钩子同时拿到原始响应和 SDK 抛出的异常。
    async with (
        httpx2.AsyncClient(event_hooks={"response": [keep]}) as http,
        pyqbot.Client(app_id, WRONG_SECRET, http_client=http) as client,
    ):
        with pytest.raises(pyqbot.QQBotError) as caught:
            await client.get_access_token()

    assert len(seen) == 1
    note_response("token_wrong_secret", seen[0], WRONG_SECRET)
    error = caught.value
    note(
        "token_wrong_secret_sdk_error",
        {
            "type": type(error).__name__,
            "status_code": getattr(error, "status_code", None),
            "err_code": error.err_code,
            "has_trace_id": error.trace_id is not None,
            "message": redact(error.message, WRONG_SECRET),
        },
    )


async def test_token_refresh_window(app_id: str, app_secret: str) -> None:
    """观察 token 临近过期时的换发行为；要跑到当前 token 过期为止，最长两个多小时。

    每次请求记一行到 `token_window.jsonl`：已过去的秒数、token 的指纹、`expires_in`，
    换发之后再加上旧 token 是否还能用。
    """
    require_flag("LIVE_TOKEN_WINDOW")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUTPUT_DIR / "token_window.jsonl"
    started = monotonic()
    first_token: str | None = None
    first_remaining = 7200.0
    changed_at: float | None = None

    async with httpx2.AsyncClient() as http:
        while True:
            elapsed = monotonic() - started
            response = await http.post(
                TOKEN_URL, json={"appId": app_id, "clientSecret": app_secret}, timeout=30
            )
            body = cast(dict[str, object], response.json())
            token = body.get("access_token")
            remaining = _as_seconds(body.get("expires_in"))
            entry: dict[str, object] = {
                "elapsed": round(elapsed, 1),
                "token": _fingerprint(token),
                "expires_in": body.get("expires_in"),
                "code": body.get("code"),
            }
            if isinstance(token, str) and first_token is None:
                first_token, first_remaining = token, remaining or first_remaining
            if isinstance(token, str) and first_token is not None and token != first_token:
                changed_at = elapsed if changed_at is None else changed_at
                old = await http.get(
                    API_BASE + "/users/@me",
                    headers={"Authorization": f"QQBot {first_token}"},
                    timeout=30,
                )
                entry["since_change"] = round(elapsed - changed_at, 1)
                entry["old_token_status"] = old.status_code
                entry["old_token_body"] = outline(
                    _json_or_none(old), app_secret, token, first_token
                )
            with log.open("a", encoding="utf-8") as lines:
                lines.write(json.dumps(entry, ensure_ascii=False) + "\n")

            if changed_at is not None and elapsed - changed_at > 150:
                break
            if elapsed > first_remaining + 400:
                break
            await asyncio.sleep(_poll_delay(remaining, changed=changed_at is not None))


def _poll_delay(remaining: float | None, *, changed: bool) -> float:
    if changed:
        return 5
    if remaining is None:  # 限频等失败响应
        return 15
    if remaining > 180:
        return min(300, remaining - 150)
    return 10 if remaining > 75 else 5


def _as_seconds(value: object) -> float | None:
    try:
        return float(cast(str, value))
    except TypeError, ValueError:
        return None


def _fingerprint(token: object) -> str | None:
    return hashlib.sha256(token.encode()).hexdigest()[:8] if isinstance(token, str) else None


def _json_or_none(response: httpx2.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return None


async def test_bot_replies_to_a_c2c_message(app_id: str, app_secret: str) -> None:
    """完整链路：`Bot` 连上网关，收到测试用户的一条单聊消息后回复它，然后退出。

    只回复 `TEST_USER_OPENID` 发来的消息，其他人的消息只记一笔、不回复。
    """
    require_flag("LIVE_GATEWAY")
    test_user = os.environ.get("TEST_USER_OPENID", "")
    wait_seconds = float(os.environ.get("LIVE_WAIT_SECONDS", "0"))
    bot = pyqbot.Bot(app_id, app_secret)
    outcome: dict[str, object] = {}

    @bot.on_c2c_message
    async def reply(message: pyqbot.C2CMessage) -> None:
        if message.user_openid != test_user:
            note("bot_reply.ignored", "消息不是测试用户发来的，没有回复")
            return
        sent = await message.reply(f"pyqbot 收到：{message.content}")
        outcome["sent"] = outline(sent.to_dict())
        save_raw("sent_message", sent.to_dict())
        await bot.close()

    async with bot:
        try:
            async with asyncio.timeout(wait_seconds):
                await bot.start()
        except TimeoutError:
            outcome["timeout"] = f"{wait_seconds} 秒内没有收到测试用户的消息"

    note("bot_reply", outcome)
    assert "sent" in outcome, outcome


async def test_gateway_identify_wait_for_message_then_resume(app_id: str, app_secret: str) -> None:
    require_flag("LIVE_GATEWAY")
    wait_seconds = float(os.environ.get("LIVE_WAIT_SECONDS", "0"))

    async with pyqbot.Client(app_id, app_secret) as client:
        token = await client.get_access_token()
        secrets = (app_secret, token)
        url = await _gateway_url(client, token)
        intents = pyqbot.Intents.GROUP_AND_C2C_EVENT

        async with client.http_client.websocket(url) as ws:
            session = await _identify(ws, token, intents, "identify", secrets)
            assert session is not None, "没有收到 READY，见 report.txt"
            session_id, seq, interval = session
            seq = await _listen(ws, seq, interval, max(wait_seconds, 5), "identify", secrets)

        # 上面正常关闭了连接（关闭码 1000），再连一次看能否恢复原会话。
        async with client.http_client.websocket(url) as ws:
            try:
                await _next(ws, "resume.hello", secrets)
                await ws.send_text(encode_resume(token, session_id, seq))
                await _next(ws, "resume.reply", secrets)
            except ConnectionClosedError:
                pass


async def test_resume_replays_backlog(app_id: str, app_secret: str) -> None:
    """测试用户配合：连上后先发一条带多张图片的单聊；连接随即以 1000 断开，30 秒内再连发两条文字；之后用
    Resume 恢复。

    记下每帧的长度与类型（看多图消息有多大）、补发的事件、`RESUMED` 与心跳应答的先后。按 SDK 的做法，收到
    第一条 Dispatch 就立刻发一次心跳。结果在 `report.txt`。
    """
    require_flag("LIVE_GATEWAY")
    wait_seconds = float(os.environ.get("LIVE_WAIT_SECONDS", "180"))

    async with pyqbot.Client(app_id, app_secret) as client:
        token = await client.get_access_token()
        secrets = (app_secret, token)
        url = await _gateway_url(client, token)
        frames: list[object] = []

        async with client.http_client.websocket(url) as ws:
            session = await _identify(
                ws, token, pyqbot.Intents.GROUP_AND_C2C_EVENT, "backlog", secrets
            )
            assert session is not None, "没有收到 READY，见 report.txt"
            session_id, seq, interval = session
            deadline, next_beat = monotonic() + wait_seconds, monotonic()
            while monotonic() < deadline:
                if monotonic() >= next_beat:
                    await ws.send_text(encode_heartbeat(seq))
                    next_beat = monotonic() + interval
                try:
                    raw = await ws.receive_text(
                        timeout=max(0.1, min(next_beat, deadline) - monotonic())
                    )
                except TimeoutError:
                    continue
                payload = decode_payload(raw)
                seq = payload.s or seq
                frames.append((payload.op.name, payload.t, len(raw.encode())))
                if payload.t == C2C_MESSAGE_EVENT:
                    save_raw("backlog_first_message", json.loads(payload.data))
                    break
        note("backlog.identify_frames", frames)

        await asyncio.sleep(30)  # 测试用户在这期间连发两条文字

        order: list[object] = []
        async with client.http_client.websocket(url) as ws:
            await _next(ws, "backlog.resume_hello", secrets)
            await ws.send_text(encode_resume(token, session_id, seq))
            beat_sent = resumed = acked = False
            deadline = monotonic() + REPLY_TIMEOUT
            while monotonic() < deadline and not (resumed and acked):
                try:
                    raw = await ws.receive_text(timeout=max(0.1, deadline - monotonic()))
                except TimeoutError:
                    break
                except WebSocketDisconnect as closed:
                    order.append(("closed", closed.code))
                    break
                payload = decode_payload(raw)
                order.append((payload.op.name, payload.t, payload.s, len(raw.encode())))
                resumed = resumed or payload.t == RESUMED_EVENT
                acked = acked or payload.op == OpCode.HEARTBEAT_ACK
                if payload.op == OpCode.DISPATCH and not beat_sent:
                    await ws.send_text(encode_heartbeat(payload.s or seq))
                    order.append("发出心跳")
                    beat_sent = True
        note("backlog.resume_order", order)
        assert resumed, order


async def test_gateway_accepts_group_member_intent(app_id: str, app_secret: str) -> None:
    require_flag("LIVE_GATEWAY")

    async with pyqbot.Client(app_id, app_secret) as client:
        token = await client.get_access_token()
        url = await _gateway_url(client, token)
        intents = pyqbot.Intents.GROUP_AND_C2C_EVENT | pyqbot.Intents.GROUP_MEMBER_EVENT

        async with client.http_client.websocket(url) as ws:
            session = await _identify(
                ws, token, intents, "group_member_intent", (app_secret, token)
            )

    note("group_member_intent.accepted", session is not None)


async def _gateway_url(client: pyqbot.Client, token: str) -> str:
    response = await client.http_client.get(
        client.config.base_url + "/gateway",
        headers={"Authorization": f"QQBot {token}"},
        timeout=client.config.timeout,
    )
    body = cast(dict[str, str], response.json())
    return body["url"]


async def _next(
    ws: AsyncWebSocketSession,
    label: str,
    secrets: tuple[str, ...],
    *,
    within: float = REPLY_TIMEOUT,
) -> GatewayPayload | None:
    """收一帧并记下来，`within` 秒内没收到返回 `None`；连接断开时记下关闭码并抛 `ConnectionClosedError`。"""
    try:
        payload = decode_payload(await ws.receive_text(timeout=max(within, 0.1)))
    except TimeoutError:
        return None
    except WebSocketDisconnect as closed:
        action = classify_close_code(closed.code).action.value
        reason = redact(closed.reason or "", *secrets)
        note(f"{label}.closed", {"code": closed.code, "reason": reason, "sdk_action": action})
        raise ConnectionClosedError from closed
    except WebSocketNetworkError as error:
        note(f"{label}.network_error", type(error).__name__)
        raise ConnectionClosedError from error
    note_payload(label, payload, *secrets)
    return payload


async def _identify(
    ws: AsyncWebSocketSession,
    token: str,
    intents: pyqbot.Intents,
    label: str,
    secrets: tuple[str, ...],
) -> tuple[str, int, float] | None:
    """走完 Hello → Identify → READY，返回 `(session_id, seq, 心跳周期秒数)`；没成功返回 `None`。"""
    try:
        hello = await _next(ws, f"{label}.hello", secrets)
        if hello is None:
            return None
        interval = hello.decode_data(Hello).heartbeat_interval_seconds
        await ws.send_text(encode_identify(token, intents))
        deadline = monotonic() + REPLY_TIMEOUT
        while monotonic() < deadline:
            payload = await _next(ws, f"{label}.reply", secrets, within=deadline - monotonic())
            if payload is not None and payload.t == READY_EVENT:
                ready = payload.decode_data(Ready)
                seen = {
                    "version": ready.version,
                    "shard": list(ready.shard),
                    "has_user": bool(ready.user),
                }
                note(f"{label}.ready_as_sdk_model", seen)
                return ready.session_id, payload.s or 0, interval
    except ConnectionClosedError:
        pass
    return None


async def _listen(
    ws: AsyncWebSocketSession,
    seq: int,
    interval: float,
    seconds: float,
    label: str,
    secrets: tuple[str, ...],
) -> int:
    """按心跳周期发心跳并记录收到的帧，收到一条单聊消息或到时间后返回最新的 `seq`。"""
    deadline = monotonic() + seconds
    next_beat = monotonic()
    try:
        while monotonic() < deadline:
            if monotonic() >= next_beat:
                await ws.send_text(encode_heartbeat(seq))
                next_beat = monotonic() + interval
            wait = min(next_beat, deadline) - monotonic()
            payload = await _next(ws, f"{label}.frame", secrets, within=wait)
            if payload is None:
                continue
            seq = payload.s or seq
            if payload.t == C2C_MESSAGE_EVENT:
                break
    except ConnectionClosedError:
        pass
    return seq
