"""富媒体上传与素材库：上传后向 `TEST_USER_OPENID` 主动发送，再由人确认客户端里的效果。

确认 `docs/errata.md` 里与上传有关的待实测项。运行前提见 `AGENTS.md`「实测」：每次都要先取得用户同意，
运行方式 `uv run --env-file .env pytest -m live --no-cov tests/live/test_live_upload.py`。
除素材库外，每个用例发出一条主动消息，占用当天对该用户的主动消息额度。

素材库是机器人全局的（与单聊、群聊无关，占每个机器人 100 张的额度），须单独征得同意后
另设 `LIVE_MEDIA_IMAGES=1` 才运行；用例结束时删除自己上传的图片。
"""

import asyncio
import base64
import io
import json
import logging
import math
import os
import shutil
import struct
import wave
import zlib
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import httpx2
import pytest

import pyqbot
from pyqbot._api.upload import INLINE_LIMIT

pytestmark = pytest.mark.live
_logger = logging.getLogger("pyqbot.live")
TIME_KEYS = frozenset({"ttl", "created_at", "expires_at"})
# 64×64 纯绿的 gif、jpg（macOS 的 sips 从 PNG 转出）与 webp。
GIF_64 = base64.b64decode(
    "R0lGODdhQABAAJEAAAAAAADAAP///wAAACH5BAQAAAAALAAAAABAAEAAAAJFjI+py+0Po5y02ouz3rz7D4biSJbmiabqyrbuC8fyTNf2jef6zvf+DwwKh8Si8YhMKpfMpvMJjUqn1Kr1is1qt9yuN1AAADs="
)
JPEG_64 = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAASABIAAD/4QBMRXhpZgAATU0AKgAAAAgAAYdpAAQAAAABAAAAGgAAAAAAA6ABAAMAAAABAAEAAKACAAQAAAABAAAAQKADAAQAAAABAAAAQAAAAAD/7QA4UGhvdG9zaG9wIDMuMAA4QklNBAQAAAAAAAA4QklNBCUAAAAAABDUHYzZjwCyBOmACZjs+EJ+/8AAEQgAQABAAwEiAAIRAQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMBAQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYSQVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNUVVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/bAEMAAgICAgICAwICAwUDAwMFBgUFBQUGCAYGBgYGCAoICAgICAgKCgoKCgoKCgwMDAwMDA4ODg4ODw8PDw8PDw8PD//bAEMBAgICBAQEBwQEBxALCQsQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEP/dAAQABP/aAAwDAQACEQMRAD8A4Oiiiv8AP8/y/CiiigAooooAKKKKAP/Q4Oiiiv8AP8/y/CiiigAooooAKKKKAP/R4Oiiiv8AP8/y/CiiigAooooAKKKKAP/S4Oiiiv8AP8/y/CiiigAooooAKKKKAP/Z"
)
WEBP_64 = base64.b64decode(
    "UklGRiIAAABXRUJQVlA4TBUAAAAvP8APAAfQ4Ij+B4CE8P+9FtH/1A8A"
)  # ffmpeg 的 libwebp，无损

# 官方文档快照里引用的图片（server-inter/message/rich-media.md），公网可访问。
IMAGE_URL = "https://qq-ai.cdn-go.cn/web/bot-docs/-/v1.49.0/assets/img/image-send.35813305.jpg"


def bmp(width: int, height: int, bgr: bytes) -> bytes:
    """24 位 BMP：自下而上逐行，每行补齐到 4 字节。"""
    row = bgr * width
    row += b"\x00" * (-len(row) % 4)
    pixels = row * height
    header = struct.pack("<2sIHHI", b"BM", 54 + len(pixels), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    return header + info + pixels


def wav(seconds: float = 2.0, rate: int = 16000) -> bytes:
    """单声道 16 位的 440Hz 正弦波。"""
    frames = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
        for i in range(int(seconds * rate))
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(frames)
    return buffer.getvalue()


async def render(tmp_path: Path, name: str, *args: str) -> Path:
    """用 ffmpeg 生成样本：路径取环境变量 `FFMPEG`，没有就从 PATH 找，都没有则 skip。"""
    ffmpeg = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("需要 ffmpeg：放进 PATH，或设 FFMPEG=它的路径")
    out = tmp_path / name
    process = await asyncio.create_subprocess_exec(
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *args, str(out)
    )
    assert await process.wait() == 0, f"ffmpeg 生成 {name} 失败"
    return out


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
        mine = next(item for item in listed if item.image_id == image.image_id)
        lifetime = (
            mine.expires_at - mine.created_at
            if mine.expires_at is not None and mine.created_at is not None
            else None
        )
        _logger.warning(
            "素材：上传时 ttl=%s；列出时 expires_at - created_at=%s 秒", image.ttl, lifetime
        )
        token = await client.get_access_token()
        response = await client.http_client.get(
            client.config.base_url + "/v2/media-images",
            headers={"Authorization": f"QQBot {token}"},
            timeout=client.config.timeout,
        )
        body = cast(dict[str, list[dict[str, object]]], response.json())
        raw = next(i for i in body.get("images", []) if i.get("image_id") == image.image_id)
        _logger.warning(  # 只显示时间字段的值，其余只给类型（preview_url 带签名）
            "素材列表的原始字段：%s",
            {
                key: (type(value).__name__, value if key in TIME_KEYS else None)
                for key, value in raw.items()
            },
        )

        sent = await client.users.send_message(
            openid, markdown=f"# 素材库\n\n![素材 #120px #80px]({image.url})"
        )
        assert sent.id
    finally:
        await client.images.delete(image)

    remaining = [item.image_id async for item in client.images.iter_images()]
    assert image.image_id not in remaining


async def test_image_and_voice_formats(client: pyqbot.Client, openid: str) -> None:
    """应看到：四张绿色小图，文字分别是 gif、webp、bmp、jpg；再一条约 2 秒的 wav 语音。

    文档各页列的格式不一致；被拒的格式与错误码记进日志。mp3、ogg 本机生成不了，没有测。
    """
    samples = [
        ("gif", GIF_64),
        ("webp", WEBP_64),
        ("bmp", bmp(64, 64, b"\x00\xc0\x00")),
        ("jpg", JPEG_64),
        ("wav", wav()),
    ]
    results: dict[str, object] = {}
    for ext, data in samples:
        try:
            media = await client.users.upload(openid, data=data, file_name=f"pyqbot.{ext}")
            content = None if ext == "wav" else f"pyqbot：{ext}"
            sent = await client.users.send_message(openid, content, media=media)
            results[ext] = f"被接受 {sent.id[:24]}"
        except pyqbot.APIError as error:
            results[ext] = ("被拒", error.err_code, error.message)
    _logger.warning("格式：%s", results)


async def test_inline_size_limit(client: pyqbot.Client, openid: str) -> None:
    """不发消息。直接调上传接口，把约 3.6、4.5、5.5 MB 的 PNG 用 base64 内联（绕过 SDK 的 3 MiB 分流）。

    看哪些被接受，判断文档的「5M」限制的是编码前还是编码后的大小。结果记进日志。
    """
    token = await client.get_access_token()
    results: dict[str, object] = {}
    for width, height in ((1200, 1000), (1500, 1000), (1500, 1222)):
        data = png(width, height)
        encoded = base64.b64encode(data).decode()
        response = await client.http_client.post(
            f"{client.config.base_url}/v2/users/{openid}/files",
            headers={"Authorization": f"QQBot {token}"},
            json={"file_type": 1, "file_data": encoded, "srv_send_msg": False},
            timeout=120,
        )
        body = cast(dict[str, object], response.json())
        code = body.get("err_code") or body.get("code")
        results[f"原始 {len(data)} 字节，base64 {len(encoded)} 字节"] = (
            response.status_code,
            code,
            body.get("message") if code else "被接受",
        )
    _logger.warning("内联上限：%s", results)


async def test_large_file_type_upload(
    app_id: str, app_secret: str, openid: str, tmp_path: Path
) -> None:
    """应看到：一个名为 pyqbot-25m.bin 的文件消息；被拒就记下错误码。

    约 25 MB 的随机数据按 `FileType.FILE` 上传：12 MB 的图片也只给一片，这里看文件类型是否支持、平台分几片、
    最后一片不足 `block_size` 时填实际大小是否被接受。分片情况记进日志。
    """
    finished: list[dict[str, object]] = []
    prepared: list[object] = []

    async def record_request(request: httpx2.Request) -> None:
        if request.url.path.endswith("/upload_part_finish"):
            finished.append(json.loads(request.content))

    async def record_response(response: httpx2.Response) -> None:
        if response.request.url.path.endswith("/upload_prepare"):
            await response.aread()
            body = cast(dict[str, object], response.json())
            parts = cast(list[dict[str, object]], body.get("parts") or [])
            prepared.append(
                {
                    "block_size": body.get("block_size"),
                    "parts": [(part.get("index"), part.get("block_size")) for part in parts],
                    "err_code": body.get("err_code") or body.get("code"),
                }
            )

    file = tmp_path / "pyqbot-25m.bin"
    file.write_bytes(os.urandom(25 * 1024 * 1024))
    async with (
        httpx2.AsyncClient(
            event_hooks={"request": [record_request], "response": [record_response]}
        ) as http_client,
        pyqbot.Client(app_id, app_secret, http_client=http_client) as client,
    ):
        try:
            media = await client.users.upload(openid, path=file, file_type=pyqbot.FileType.FILE)
            sent = await client.users.send_message(openid, media=media)
            result: object = f"被接受 {sent.id[:24]}"
        except pyqbot.APIError as error:
            result = ("被拒", error.err_code, error.message)

    finishes = [(body["part_index"], body["block_size"]) for body in finished]
    _logger.warning("文件分片：预上传 %s；分片完成 %s；结果 %s", prepared, finishes, result)


async def test_media_image_library_jpg(client: pyqbot.Client) -> None:
    """素材库是机器人全局的，须单独同意后设 `LIVE_MEDIA_IMAGES=1`。不发消息。

    上传文件名为 `.jpg` 的图片（Content-Type 发 `image/jpeg`），看申请上传是否报 40035001
    （扩展名与 Content-Type 不一致）。成功就立刻删除。
    """
    if os.environ.get("LIVE_MEDIA_IMAGES") != "1":
        pytest.skip("素材库是机器人全局的，须单独同意后设 LIVE_MEDIA_IMAGES=1")
    try:
        image = await client.images.upload(data=JPEG_64, file_name="pyqbot.jpg")
    except pyqbot.APIError as error:
        _logger.warning("素材库 .jpg：被拒 %s", (error.err_code, error.message))
        return
    try:
        _logger.warning("素材库 .jpg：被接受 %s", image.image_id)
    finally:
        await client.images.delete(image)


TONE = ("-f", "lavfi", "-i", "sine=frequency=440:duration=2")


async def test_ffmpeg_voice_and_video_formats(
    client: pyqbot.Client, openid: str, tmp_path: Path
) -> None:
    """应看到：两条约 2 秒的语音（mp3、ogg），一段约 5 秒带声音的测试图样视频（mp4）。

    文档各页对语音格式说法不一；被拒的格式与错误码记进日志。样本由 ffmpeg 现场生成。
    """
    samples = [
        await render(tmp_path, "pyqbot.mp3", *TONE, "-c:a", "libmp3lame"),
        await render(tmp_path, "pyqbot.ogg", *TONE, "-c:a", "libvorbis"),
        await render(
            tmp_path,
            "pyqbot.mp4",
            *("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=5"),
            *("-f", "lavfi", "-i", "sine=frequency=440:duration=5"),
            *("-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"),
        ),
    ]
    results: dict[str, object] = {}
    for path in samples:
        try:
            media = await client.users.upload(openid, path=path)
            sent = await client.users.send_message(openid, media=media)
            results[path.suffix] = f"被接受 {sent.id[:24]}"
        except pyqbot.APIError as error:
            results[path.suffix] = ("被拒", error.err_code, error.message)
    _logger.warning("ffmpeg 生成的格式：%s", results)


async def test_large_video_in_parts(
    app_id: str, app_secret: str, openid: str, tmp_path: Path
) -> None:
    """应看到：一段约 10 秒的雪花噪点视频（约 25 MB，视频上限 30 MB）。

    看视频类型分几片、分片大小是多少（25 MB 的文件是 10 MiB 一片，12 MB 的图片只有一片）。分片情况记进日志。
    """
    video = await render(
        tmp_path,
        "pyqbot-noise.mp4",
        *("-f", "lavfi", "-i", "nullsrc=size=1280x720:rate=25,geq=random(1)*255:128:128"),
        *("-t", "10", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"),
        *("-b:v", "20M", "-maxrate", "20M", "-bufsize", "20M"),
    )
    prepared: list[object] = []

    async def record_response(response: httpx2.Response) -> None:
        if response.request.url.path.endswith("/upload_prepare"):
            await response.aread()
            body = cast(dict[str, object], response.json())
            parts = cast(list[dict[str, object]], body.get("parts") or [])
            prepared.append(
                {
                    "block_size": body.get("block_size"),
                    "parts": [(part.get("index"), part.get("block_size")) for part in parts],
                }
            )

    async with (
        httpx2.AsyncClient(event_hooks={"response": [record_response]}) as http_client,
        pyqbot.Client(app_id, app_secret, http_client=http_client) as client,
    ):
        try:
            media = await client.users.upload(openid, path=video)
            sent = await client.users.send_message(openid, media=media)
            result: object = f"被接受 {sent.id[:24]}"
        except pyqbot.APIError as error:
            result = ("被拒", error.err_code, error.message)

    _logger.warning("视频 %d 字节；预上传 %s；结果 %s", video.stat().st_size, prepared, result)


async def test_group_media_formats(app_id: str, app_secret: str, tmp_path: Path) -> None:
    """测试群里有人 @机器人 两次：第一次回复 gif、webp、bmp、jpg 四张图，第二次回复 wav、mp3、ogg 语音与
    mp4 视频（后三种由 ffmpeg 生成，没有 ffmpeg 就只有 wav）。

    要 `LIVE_GATEWAY` 与 `TEST_GROUP_OPENID`；每种格式被拒就记下错误码。一条消息只回四条，免得超过被动回复次数。
    """
    if os.environ.get("LIVE_GATEWAY") != "1":
        pytest.skip("需要显式设置 LIVE_GATEWAY=1：每个用例消耗一次网关连接")
    group = os.environ.get("TEST_GROUP_OPENID")
    if not group:
        pytest.skip("缺少环境变量 TEST_GROUP_OPENID")
    wait_seconds = float(os.environ.get("LIVE_WAIT_SECONDS", "180"))
    images = [
        ("gif", GIF_64),
        ("webp", WEBP_64),
        ("bmp", bmp(64, 64, b"\x00\xc0\x00")),
        ("jpg", JPEG_64),
    ]
    media: list[tuple[str, bytes]] = [("wav", wav())]
    if os.environ.get("FFMPEG") or shutil.which("ffmpeg"):
        for path in (
            await render(tmp_path, "pyqbot.mp3", *TONE, "-c:a", "libmp3lame"),
            await render(tmp_path, "pyqbot.ogg", *TONE, "-c:a", "libvorbis"),
            await render(
                tmp_path,
                "pyqbot.mp4",
                *("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=5"),
                *("-f", "lavfi", "-i", "sine=frequency=440:duration=5"),
                *("-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"),
            ),
        ):
            media.append((path.suffix.lstrip("."), path.read_bytes()))
    batches = [images, media]
    results: dict[str, object] = {}
    bot = pyqbot.Bot(app_id, app_secret)

    @bot.on_group_message
    @bot.on_group_at_message
    async def mentioned(message: pyqbot.GroupMessage) -> None:
        if message.group_openid != group or not message.mentions_me or not batches:
            return
        for ext, data in batches.pop(0):
            try:
                uploaded = await message.upload(data=data, file_name=f"pyqbot.{ext}")
                label = f"pyqbot：群 {ext}" if (ext, data) in images else None
                await message.reply(label, media=uploaded)
                results[ext] = "被接受"
            except pyqbot.APIError as error:
                results[ext] = ("被拒", error.err_code, error.message)
        if not batches:
            await bot.close()

    async with bot:
        try:
            async with asyncio.timeout(wait_seconds):
                await bot.start()
        except TimeoutError:
            results["timeout"] = f"{wait_seconds} 秒内没有等到两次 @"

    _logger.warning("群里的格式：%s", results)
    assert results, results
