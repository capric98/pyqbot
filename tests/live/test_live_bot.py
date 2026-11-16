"""机器人级接口与流式消息的实测，确认 `docs/errata.md` 里相关的待实测项。运行前提见 `AGENTS.md`「实测」。

运行方式 `uv run --env-file .env pytest -m live --no-cov tests/live/test_live_bot.py`。

- 只读的几项（`get_me`、分享链接、读菜单）直接运行。
- `LIVE_GLOBAL_CONFIG=1`：改菜单、增删面板。**会影响所有用户，须单独征得同意**。
- `LIVE_GATEWAY=1`：流式回复，连一次网关，等测试用户发来一条单聊消息（`LIVE_WAIT_SECONDS` 秒）。

要人看的结果（分享链接、菜单、面板等）追加到 `.cache/live/bot.txt`，各接口的原始响应写到
`.cache/live/raw/bot_*.json`。写盘前都去掉了 `app_secret` 与 access_token，但含 openid，已被 git 忽略、
只留在本机；原始响应再去掉 openid 等后做成 `tests/fixtures/` 的 fixture。

末尾的 `test_raw_recorder_*` 是本地测试（不访问网络，没有 live 标记），随 `uv run pytest` 运行。
"""

import asyncio
import json
import os
from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path

import httpx2
import pytest

import pyqbot
from pyqbot._redact import redact

OUTPUT_DIR = Path(__file__).parents[2] / ".cache" / "live"
RAW_DIR = OUTPUT_DIR / "raw"
CALLBACK_DATA = "pyqbot-live"
TOKEN_PATH = "/app/getAppAccessToken"


def require_flag(name: str) -> None:
    if os.environ.get(name) != "1":
        pytest.skip(f"需要显式设置 {name}=1")


def note(client: pyqbot.Client, text: str) -> None:
    """把要人看的结果脱敏后追加到 `bot.txt`。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIR / "bot.txt").open("a", encoding="utf-8") as output:
        output.write(redact_secrets(client, text) + "\n")


def redact_secrets(client: pyqbot.Client, text: str) -> str:
    """去掉 `app_secret` 与这个客户端取到过的所有 access_token（平台可能回显换掉之前的）。"""
    return client._redact_secrets(text)  # pyright: ignore[reportPrivateUsage]  实测复用 SDK 的脱敏


type ResponseHook = Callable[[httpx2.Response], Awaitable[None]]


def raw_recorder(directory: Path, redact_text: Callable[[str], str]) -> ResponseHook:
    """响应钩子：把接口的响应体脱敏后写到 `directory/bot_<方法><路径>.json`。

    钩子在请求层脱敏之前就拿到响应，所以这里必须自己脱敏：`redact_text` 去掉已知的凭证，
    另外去掉本次请求头里的 token。获取 token 的响应整个就是凭证，不写。
    """

    async def keep(response: httpx2.Response) -> None:
        request = response.request
        if request.url.path == TOKEN_PATH:
            return
        await response.aread()
        token = request.headers.get("Authorization", "").removeprefix("QQBot ")
        try:
            text = json.dumps(response.json(), ensure_ascii=False, indent=2)
        except ValueError:
            text = response.text
        name = f"{request.method} {request.url.path}".replace("/", "_").replace(" ", "")
        write_text(directory / f"bot_{name}.json", redact(redact_text(text), token))

    return keep


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_texts(directory: Path) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in directory.iterdir()}


@pytest.fixture
def openid() -> str:
    value = os.environ.get("TEST_USER_OPENID")
    if not value:
        pytest.skip("缺少环境变量 TEST_USER_OPENID：用 uv run --env-file .env 运行")
    return value


@pytest.fixture
async def client(app_id: str, app_secret: str) -> AsyncGenerator[pyqbot.Client]:
    clients: list[pyqbot.Client] = []

    def redact_text(text: str) -> str:
        # 钩子要在 Client 之前建好；第一个请求发出时 Client 已经存在。
        return redact_secrets(clients[0], redact(text, app_secret))

    hook = raw_recorder(RAW_DIR, redact_text)
    async with (
        httpx2.AsyncClient(event_hooks={"response": [hook]}) as http_client,
        pyqbot.Client(app_id, app_secret, http_client=http_client) as client,
    ):
        clients.append(client)
        yield client


@pytest.mark.live
async def test_get_me(client: pyqbot.Client) -> None:
    """只读。应看到：`bot.txt` 里的名字与头像是这个机器人的；看原始响应里有没有 `share_url`、`welcome_msg`。"""
    me = await client.get_me()

    note(client, f"机器人：{me.username}（id {me.id}）头像 {me.avatar}")
    assert me.id


@pytest.mark.live
async def test_generate_share_link(client: pyqbot.Client) -> None:
    """生成链接本身不影响任何人。应看到：`bot.txt` 里有一条 https 链接。

    确认 `FRIEND_ADD.scene_param`：先让机器人与测试账号解除好友，再用测试账号打开这条链接添加机器人，
    看 `FRIEND_ADD` 事件的 `scene_param` 是否为 `pyqbot-live`、`scene` 是否为 2003 或 2004。
    收事件要连网关，可以与事件包的实测合并进行。
    """
    url = await client.generate_share_link(callback_data=CALLBACK_DATA)

    note(client, f"分享链接（callback_data={CALLBACK_DATA}）：{url}")
    assert url.startswith("https://")


@pytest.mark.live
async def test_get_menu(client: pyqbot.Client) -> None:
    """只读。应看到：`bot.txt` 里的按钮与测试账号单聊窗口底部的菜单一致（没设置过时为空）。"""
    current = await client.menu.get()

    note(client, f"菜单版本 {current.version}：{[item.to_dict() for item in current.items]}")


@pytest.mark.live
async def test_set_menu_to_itself(client: pyqbot.Client) -> None:
    """**会改动对所有用户生效的菜单，须单独征得同意。**

    把菜单原样设置回去，所以用户看到的菜单不变。应看到：版本号变大，测试账号的菜单与之前相同。
    另外看 `version` 是否随每次设置递增，以及从未设置过时设置一个空菜单是否被接受。
    """
    require_flag("LIVE_GLOBAL_CONFIG")
    before = await client.menu.get()

    version = await client.menu.set(before.items)

    after = await client.menu.get()
    note(client, f"菜单版本 {before.version} → {version}（再读为 {after.version}）")
    assert after.items == before.items


@pytest.mark.live
async def test_panel_lifecycle(client: pyqbot.Client, openid: str) -> None:
    """**会创建对外生效的面板，须单独征得同意。** 面板只关联测试用户，用完即删。

    应看到：运行期间测试账号单聊的指令面板里出现「pyqbot」→ 修改后变成「pyqbot2」；
    结束后面板消失。`iter_panels` 里有这个面板，详情里 `user_openids` 是测试用户。
    """
    require_flag("LIVE_GLOBAL_CONFIG")
    panel_id = await client.panels.create(
        pyqbot.PanelScope.C2C,
        [pyqbot.PanelItem.command_button("pyqbot", desc="pyqbot 实测")],
        remark="pyqbot 实测，可删除",
        user_openids=[openid],
    )
    try:
        detail = await client.panels.get(panel_id)
        note(client, f"面板 {panel_id}：{detail.to_dict()}")
        assert detail.target_type == pyqbot.PanelTargetType.SPECIFIC
        assert openid in detail.user_openids

        listed = [r.panel_id async for r in client.panels.iter_panels(pyqbot.PanelScope.C2C)]
        assert panel_id in listed

        item = pyqbot.PanelItem.command_button("pyqbot2", desc="修改后")
        version = await client.panels.set(panel_id, [item], remark="pyqbot 实测，可删除")
        note(client, f"修改后版本 {version}；去测试账号确认面板已变成「pyqbot2」")
        await asyncio.sleep(20)

        await client.panels.remove_targets(panel_id, user_openids=[openid])
        assert openid not in (await client.panels.get(panel_id)).user_openids
        await client.panels.add_targets(panel_id, user_openids=[openid])
    finally:
        await client.panels.delete(panel_id)


@pytest.mark.live
async def test_stream_reply(app_id: str, app_secret: str, openid: str) -> None:
    """流式回复：连上网关，等测试用户发来一条单聊消息，用 `reply_stream()` 分几片回复。

    应看到：一条消息逐段出现「pyqbot 流式回复：」「第一段，」「第二段，」「**完。**」（加粗），
    最后不再显示「生成中」。确认 `docs/errata.md` 的流式消息各项：同一 `msg_seq`、空的结束分片是否被接受，
    以及 `remain_msg_len` 的取值（记在 `bot.txt`）。
    """
    require_flag("LIVE_GATEWAY")
    wait_seconds = float(os.environ.get("LIVE_WAIT_SECONDS", "0"))
    bot = pyqbot.Bot(app_id, app_secret)
    outcome: dict[str, object] = {}

    @bot.on_c2c_message
    async def reply(message: pyqbot.C2CMessage) -> None:
        if message.user_openid != openid:
            return
        async with message.reply_stream() as stream:
            for piece in ("pyqbot 流式回复：", "第一段，", "第二段，", "**完。**"):
                await stream.append(piece)
                await asyncio.sleep(1)
                if stream.last_sent is not None:
                    note(bot, f"remain_msg_len={stream.last_sent.remain_msg_len}")
        outcome["stream_msg_id"] = stream.stream_msg_id
        await bot.close()

    async with bot:
        try:
            async with asyncio.timeout(wait_seconds):
                await bot.start()
        except TimeoutError:
            outcome["timeout"] = f"{wait_seconds} 秒内没有收到测试用户的消息"

    assert "stream_msg_id" in outcome, outcome


# ---- 本地测试：落盘前脱敏（不访问网络，随 `uv run pytest` 运行）----


async def test_raw_recorder_redacts_credentials_echoed_by_the_platform(tmp_path: Path) -> None:
    secret, token = "app-secret-value", "access-token-value"

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == TOKEN_PATH:
            return httpx2.Response(200, json={"access_token": token, "expires_in": "7200"})
        if request.url.path == "/users/@me":
            return httpx2.Response(401, json={"message": f"无效 {secret} {token}", "err_code": 1})
        return httpx2.Response(500, text=f"<html>{token}</html>")

    hook = raw_recorder(tmp_path, lambda text: redact(text, secret))
    async with (
        httpx2.AsyncClient(
            transport=httpx2.MockTransport(handle), event_hooks={"response": [hook]}
        ) as http_client,
        pyqbot.Client("app-id", secret, http_client=http_client) as client,
    ):
        with pytest.raises(pyqbot.APIError):
            await client.get_me()
        with pytest.raises(pyqbot.APIError):
            await client.menu.get()

    written = read_texts(tmp_path)
    assert sorted(written) == ["bot_GET_users_@me.json", "bot_GET_v2_menu.json"]
    assert "无效 *** ***" in written["bot_GET_users_@me.json"]
    assert written["bot_GET_v2_menu.json"] == "<html>***</html>"
    for text in written.values():
        assert secret not in text
        assert token not in text
