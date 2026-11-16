"""富媒体上传与素材库：上传后向 `TEST_USER_OPENID` 主动发送，再由人确认客户端里的效果。

确认 `docs/errata.md` 里与上传有关的待实测项。运行前提见 `AGENTS.md`「实测」：每次都要先取得用户同意，
运行方式 `uv run --env-file .env pytest -m live --no-cov tests/live/test_live_upload.py`。
除素材库外，每个用例发出一条主动消息，占用当天对该用户的主动消息额度。

素材库是机器人全局的（与单聊、群聊无关，占每个机器人 100 张的额度），须单独征得同意后
另设 `LIVE_MEDIA_IMAGES=1` 才运行；用例结束时删除自己上传的图片。
"""

import json
import logging
import os
import struct
import zlib
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx2
import pytest

import pyqbot
from pyqbot._api.upload import INLINE_LIMIT

pytestmark = pytest.mark.live
_logger = logging.getLogger("pyqbot.live")

# 官方文档快照里引用的图片（server-inter/message/rich-media.md），公网可访问。
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


def png(width: int, height: int, row: bytes | None = None) -> bytes:
    """生成 RGB 的 PNG：给了 `row`（一行像素）就每行相同，否则是随机噪点（几乎不可压缩）。"""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    rows = b"".join(b"\x00" + (row or os.urandom(width * 3)) for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 1))
        + chunk(b"IEND", b"")
    )


async def test_url_upload(client: pyqbot.Client, openid: str) -> None:
    """应看到：一张图片（官方文档里「图片消息」的示意图）。"""
    media = await client.users.upload(openid, url=IMAGE_URL)

    sent = await client.users.send_message(openid, media=media)

    assert sent.id


async def test_inline_data_is_base64(client: pyqbot.Client, openid: str) -> None:
    """应看到：一个纯红色的小方块，下面一行「内联上传」。

    `file_data` 的编码文档没写，SDK 按 base64 发；图片显示正常即说明平台按 base64 解读。
    """
    data = png(64, 64, b"\xff\x00\x00" * 64)

    media = await client.users.upload(openid, data=data, file_name="pyqbot-red.png")
    sent = await client.users.send_message(openid, "内联上传", media=media)

    assert sent.id


async def test_large_file_is_uploaded_in_parts(
    client: pyqbot.Client, openid: str, tmp_path: Path
) -> None:
    """应看到：一张约 1200×1000 的彩色噪点图，下面一行「分片上传」。

    文件超过内联上限，走预上传、分片 PUT、逐片确认与合并。文档说这种方式上传图片会返回 `raw_url`。
    """
    file = tmp_path / "pyqbot-noise.png"
    file.write_bytes(png(1200, 1000))
    assert file.stat().st_size > INLINE_LIMIT

    media = await client.users.upload(openid, path=file)
    sent = await client.users.send_message(openid, "分片上传", media=media)

    assert sent.id
    assert media.raw_url


async def test_file_over_10m_is_uploaded(
    app_id: str, app_secret: str, openid: str, tmp_path: Path
) -> None:
    """应看到：一张约 2000×2000 的彩色噪点图，下面一行「多片上传」。

    约 12 MB，超过 `md5_10m` 的 10002432 字节。分片情况记进日志（`--log-cli-level=WARNING`）：
    2026-11-16 实测平台仍只给一片，`block_size` 等于文件大小。
    """
    finished: list[dict[str, object]] = []

    async def record(request: httpx2.Request) -> None:
        if request.url.path.endswith("/upload_part_finish"):
            finished.append(json.loads(request.content))

    file = tmp_path / "pyqbot-noise-12m.png"
    file.write_bytes(png(2000, 2000))
    async with (
        httpx2.AsyncClient(event_hooks={"request": [record]}) as http_client,
        pyqbot.Client(app_id, app_secret, http_client=http_client) as client,
    ):
        media = await client.users.upload(openid, path=file)
        sent = await client.users.send_message(openid, "多片上传", media=media)

    parts = [(body["part_index"], body["block_size"]) for body in finished]
    _logger.warning("文件 %d 字节，分片（序号, 大小）：%s", file.stat().st_size, parts)
    assert sent.id
    assert sum(int(str(size)) for _, size in parts) == file.stat().st_size


async def test_upload_and_send_directly(client: pyqbot.Client, openid: str) -> None:
    """应看到：与 `test_url_upload` 相同的图片，由上传接口直接发出（`srv_send_msg`）。"""
    media = await client.users.upload(openid, url=IMAGE_URL, send=True)

    assert media.id


async def test_media_image_library(client: pyqbot.Client, openid: str) -> None:
    """应看到：一条 Markdown，标题「素材库」，下面是一个 120×80 的纯蓝色图片。

    须单独征得同意：素材库是机器人全局的。用例结束时删除上传的图片，删除后不再出现在列表里。
    """
    if os.environ.get("LIVE_MEDIA_IMAGES") != "1":
        pytest.skip("素材库是机器人全局的，须单独同意后设 LIVE_MEDIA_IMAGES=1")

    image = await client.images.upload(
        data=png(120, 80, b"\x00\x00\xff" * 120), file_name="pyqbot.png"
    )
    try:
        assert image.url.startswith("qqbot-media://")
        listed = [item async for item in client.images.iter_images()]
        assert image.image_id in [item.image_id for item in listed]

        sent = await client.users.send_message(
            openid, markdown=f"# 素材库\n\n![素材 #120px #80px]({image.url})"
        )
        assert sent.id
    finally:
        await client.images.delete(image)

    remaining = [item.image_id async for item in client.images.iter_images()]
    assert image.image_id not in remaining
