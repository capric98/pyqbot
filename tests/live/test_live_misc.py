"""零散接口与快捷方法的实测：要测试用户先给机器人发一条单聊消息，再由人确认客户端里的效果。

运行前提见 `AGENTS.md`「实测」与 `tests/live/README.md`：每次都要先取得用户同意；用例消耗一次网关连接，
所以还要 `LIVE_GATEWAY=1`，`LIVE_WAIT_SECONDS`（默认 180）是连上网关后等测试用户发消息的秒数。
"""

import asyncio
import os

import pytest

import pyqbot

pytestmark = pytest.mark.live

IMAGE_URL = "https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.49.0/assets/img/image-send.35813305.jpg"


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


async def test_message_upload_shortcut(
    app_id: str, app_secret: str, openid: str, wait_seconds: float
) -> None:
    """让测试用户给机器人发任意一条单聊消息，机器人用 `message.upload()` 上传图片后被动回复。

    应看到：测试用户收到一条带官方示例图片的回复「pyqbot：upload 快捷方法」。只认测试用户的消息，
    其他人的忽略。确认 `C2CMessage.upload()` 固定的目标与 `client.users.upload()` 一致。
    """
    bot = pyqbot.Bot(app_id, app_secret)
    outcome: dict[str, object] = {}

    @bot.on_c2c_message
    async def received(message: pyqbot.C2CMessage) -> None:
        if message.user_openid != openid:
            return
        media = await message.upload(url=IMAGE_URL)
        sent = await message.reply("pyqbot：upload 快捷方法", media=media)
        outcome["sent"] = sent.id
        await bot.close()

    async with bot:
        try:
            async with asyncio.timeout(wait_seconds):
                await bot.start()
        except TimeoutError:
            outcome["timeout"] = f"{wait_seconds} 秒内没有等到测试用户的消息"

    assert "sent" in outcome, outcome
