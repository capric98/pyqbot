"""富媒体上传：上传方式的选择、分片上传的全流程、并发与重试、对象存储请求的失败映射与脱敏。"""

import asyncio
import base64
import hashlib
import json
import math
import threading
import traceback
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import IO, Any, Self

import httpx2
import pytest

import pyqbot
import pyqbot._api.upload as upload_module
from pyqbot._model import decode
from pyqbot._models.upload import UploadPrepared

APP_SECRET = "secret-value-never-shown"
TOKEN = "token-value-never-shown"
SIGNATURE = "q-signature-0123456789abcdef"
MEDIA: dict[str, object] = {"file_uuid": "uuid", "file_info": "INFO", "ttl": 300}
COS_403 = "<Error><Code>SignatureDoesNotMatch</Code><Message>bad</Message></Error>"

type Respond = Callable[[httpx2.Request], httpx2.Response]
type Call = tuple[str, str, dict[str, object] | None]


def presigned(index: int) -> str:
    return f"https://cos.test/bucket/part{index}?partNumber={index + 1}&sign={SIGNATURE}{index}"


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def raising(error: Exception) -> Respond:
    def respond(request: httpx2.Request) -> httpx2.Response:
        raise error

    return respond


def status(code: int, body: dict[str, object] | None = None, *, text: str = "") -> Respond:
    if body is not None:
        return lambda request: httpx2.Response(code, json=body)
    return lambda request: httpx2.Response(code, text=text)


class Platform:
    """扮演开放平台与对象存储：`cos.test` 上的 PUT 记进 `puts`，其余请求记进 `calls`。"""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.puts: list[httpx2.Request] = []
        self.block_size: object = "10"
        self.config: dict[str, object] = {"concurrency": 1, "retry_timeout": 300, "retry_delay": 0}
        self.prepare: dict[str, object] | None = None  # 不为 None 时原样返回它
        self.extra_parts = 0
        self.put_failures: list[Respond] = []
        self.finish_failures: list[Respond] = []
        self.on_put: Callable[[httpx2.Request], Awaitable[None]] | None = None
        self.media: dict[str, object] = MEDIA

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "cos.test":
            self.puts.append(request)
            if self.on_put is not None:
                await self.on_put(request)
            if self.put_failures:
                return self.put_failures.pop(0)(request)
            return httpx2.Response(200)
        path = request.url.path
        if path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})
        body: dict[str, object] | None = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.raw_path.decode(), body))
        if path.endswith("/upload_prepare"):
            assert body is not None
            return httpx2.Response(200, json=self.prepare or self.prepared(body))
        if path.endswith("/upload_part_finish"):
            if self.finish_failures:
                return self.finish_failures.pop(0)(request)
            return httpx2.Response(200, json={})
        return httpx2.Response(200, json=self.media)

    def prepared(self, body: dict[str, object]) -> dict[str, object]:
        count = math.ceil(int(str(body["file_size"])) / int(str(self.block_size)))
        parts = [
            {"index": i, "presigned_url": presigned(i), "block_size": self.block_size}
            for i in range(count + self.extra_parts)
        ]
        return {
            "upload_id": "up-1",
            "block_size": self.block_size,
            "parts": parts,
            "upload_config": self.config,
            "unknown": True,
        }

    def paths(self) -> list[str]:
        return [path for _, path, _ in self.calls]


@asynccontextmanager
async def client_for(
    platform: Platform, *, request_timeout: float = 30
) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client(
            "app-id", APP_SECRET, timeout=request_timeout, http_client=http_client
        ) as client,
    ):
        yield client


@pytest.fixture
def small_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    """把内联上传的上限调到 16 字节，用几十字节的数据就能走分片。"""
    monkeypatch.setattr(upload_module, "INLINE_LIMIT", 16)


def assert_hidden(error: BaseException, *secrets: str) -> None:
    shown = "".join(traceback.format_exception(error))
    for secret in secrets:
        assert secret not in str(error)
        assert secret not in repr(error)
        assert secret not in shown


# ---- URL 与内联上传 ----


async def test_url_upload_posts_the_url_and_decodes_media() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        media = await client.users.upload("u", url="https://example.com/a/photo.JPG?x=1")

    assert media == pyqbot.Media(file_info="INFO", file_uuid="uuid", ttl=300)
    assert platform.calls == [
        (
            "POST",
            "/v2/users/u/files",
            {"file_type": 1, "url": "https://example.com/a/photo.JPG?x=1", "srv_send_msg": False},
        )
    ]


async def test_group_url_upload_with_explicit_file_type() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        await client.groups.upload(
            "g/1", url="https://example.com/stream", file_type=pyqbot.FileType.VIDEO
        )

    assert platform.calls == [
        (
            "POST",
            "/v2/groups/g%2F1/files",
            {"file_type": 2, "url": "https://example.com/stream", "srv_send_msg": False},
        )
    ]


async def test_small_data_is_sent_inline_as_base64() -> None:
    platform = Platform()
    data = b"\x89PNG\r\n\x1a\n\x00\xff"

    async with client_for(platform) as client:
        await client.users.upload("u", data=data, file_name="a.PNG")

    [(_, path, body)] = platform.calls
    assert path == "/v2/users/u/files"
    assert body == {
        "file_type": 1,
        "file_name": "a.PNG",
        "file_data": base64.b64encode(data).decode(),
        "srv_send_msg": False,
    }


async def test_small_file_is_read_and_named_after_its_path(tmp_path: Path) -> None:
    platform = Platform()
    file = tmp_path / "voice.silk"
    file.write_bytes(b"#!SILK_V3")

    async with client_for(platform) as client:
        await client.groups.upload("g", path=file)
        await client.groups.upload("g", path=str(file), file_name="renamed.mp4")

    assert [body for _, _, body in platform.calls] == [
        {
            "file_type": 3,
            "file_name": "voice.silk",
            "file_data": base64.b64encode(b"#!SILK_V3").decode(),
            "srv_send_msg": False,
        },
        {
            "file_type": 2,
            "file_name": "renamed.mp4",
            "file_data": base64.b64encode(b"#!SILK_V3").decode(),
            "srv_send_msg": False,
        },
    ]


async def test_data_exactly_at_the_inline_limit_is_still_inline(small_inline: None) -> None:
    platform = Platform()

    async with client_for(platform) as client:
        await client.users.upload(
            "u", data=b"x" * 16, file_name="a.txt", file_type=pyqbot.FileType.FILE
        )

    assert platform.paths() == ["/v2/users/u/files"]


async def test_send_asks_the_platform_to_send_and_returns_the_message_id() -> None:
    platform = Platform()
    platform.media = {**MEDIA, "id": "ROBOT1.0_msg"}

    async with client_for(platform) as client:
        media = await client.users.upload("u", url="https://example.com/a.png", send=True)

    assert media.id == "ROBOT1.0_msg"
    [(_, _, body)] = platform.calls
    assert body is not None
    assert body["srv_send_msg"] is True


async def test_uploaded_media_can_be_sent() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        media = await client.users.upload("u", url="https://example.com/a.png")
        platform.media = {"id": "sent"}
        await client.users.send_message("u", media=media)

    assert platform.calls[-1][2] == {"msg_type": 7, "media": {"file_info": "INFO"}}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "必须且只能传一个"),
        ({"url": "https://a/b.png", "data": b"x", "file_name": "a.png"}, "必须且只能传一个"),
        ({"data": b"x"}, "file_name"),
        ({"data": b"x", "file_name": ""}, "file_name"),
        ({"url": "https://a/b.png", "file_name": "b.png"}, "file_name"),
        ({"data": b"", "file_name": "a.png"}, "空文件"),
        ({"data": b"x", "file_name": "a.exe"}, "推断 file_type"),
        ({"data": b"x", "file_name": "README"}, "推断 file_type"),
        ({"url": "https://example.com/download?id=1.png"}, "推断 file_type"),
    ],
)
async def test_invalid_arguments_are_rejected_before_sending(
    kwargs: dict[str, object], message: str
) -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match=message):
            await client.users.upload("u", **kwargs)  # pyright: ignore[reportArgumentType]

    assert platform.calls == []


async def test_empty_openid_is_rejected() -> None:
    async with client_for(Platform()) as client:
        with pytest.raises(ValueError, match="openid"):
            await client.groups.upload("", url="https://a/b.png")


async def test_missing_file_raises_os_error(tmp_path: Path) -> None:
    async with client_for(Platform()) as client:
        with pytest.raises(FileNotFoundError):
            await client.users.upload("u", path=tmp_path / "missing.png")


async def test_upload_failure_becomes_api_error() -> None:
    platform = Platform()
    platform.media = {"err_code": 850019, "message": "不支持的文件格式"}

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="不支持的文件格式") as caught:
            await client.users.upload("u", url="https://example.com/a.png")

    assert caught.value.err_code == 850019


# ---- 分片上传 ----


async def test_large_data_goes_through_prepare_put_finish_and_merge(small_inline: None) -> None:
    platform = Platform()
    data = bytes(range(25))

    async with client_for(platform, request_timeout=7) as client:
        media = await client.users.upload("u", data=data, file_name="clip.mp4", send=True)

    assert media.file_info == "INFO"
    assert (
        platform.calls
        == [
            (
                "POST",
                "/v2/users/u/upload_prepare",
                {
                    "file_type": 2,
                    "file_size": "25",
                    "file_name": "clip.mp4",
                    "md5": md5(data),
                    "sha1": hashlib.sha1(data).hexdigest(),
                    "md5_10m": md5(data),  # 不足 10002432 字节时就是整个文件的 MD5
                },
            ),
            *(
                (
                    "POST",
                    "/v2/users/u/upload_part_finish",
                    {"upload_id": "up-1", "part_index": i, "block_size": size, "md5": md5(chunk)},
                )
                for i, (size, chunk) in enumerate(
                    [("10", data[:10]), ("10", data[10:20]), ("5", data[20:])]
                )
            ),
            (
                "POST",
                "/v2/users/u/files",
                {
                    "file_type": 2,
                    "file_name": "clip.mp4",
                    "upload_id": "up-1",
                    "srv_send_msg": True,
                },
            ),
        ]
    )
    assert [(put.method, str(put.url), put.content) for put in platform.puts] == [
        ("PUT", presigned(0), data[:10]),
        ("PUT", presigned(1), data[10:20]),
        ("PUT", presigned(2), data[20:]),
    ]
    for put in platform.puts:
        assert "Authorization" not in put.headers  # 预签名地址自带签名，不能带上 access_token
        assert put.extensions["timeout"]["read"] == 7


async def test_large_file_is_hashed_and_split_without_reading_it_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, small_inline: None
) -> None:
    monkeypatch.setattr(upload_module, "_READ_SIZE", 4)
    monkeypatch.setattr(upload_module, "MD5_10M_SIZE", 7)
    platform = Platform()
    platform.block_size = 8  # 文档写字符串，整数也接受
    data = bytes(range(100, 130))
    file = tmp_path / "big.bin"
    file.write_bytes(data)

    async with client_for(platform) as client:
        await client.groups.upload("g", path=file, file_type=pyqbot.FileType.FILE)

    _, prepare_path, prepare = platform.calls[0]
    assert prepare_path == "/v2/groups/g/upload_prepare"
    assert prepare == {
        "file_type": 4,
        "file_size": "30",
        "file_name": "big.bin",
        "md5": md5(data),
        "sha1": hashlib.sha1(data).hexdigest(),
        "md5_10m": md5(data[:7]),
    }
    assert [put.content for put in platform.puts] == [data[:8], data[8:16], data[16:24], data[24:]]
    assert platform.paths()[1:] == [
        *["/v2/groups/g/upload_part_finish"] * 4,
        "/v2/groups/g/files",
    ]


async def test_large_file_is_read_in_bounded_chunks_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, small_inline: None
) -> None:
    monkeypatch.setattr(upload_module, "_READ_SIZE", 4)
    file = tmp_path / "big.bin"
    file.write_bytes(bytes(30))
    reads: list[tuple[int, int]] = []  # （每次 read 的长度，所在线程）
    original_open = Path.open

    class SpyFile:
        def __init__(self, inner: IO[Any]) -> None:
            self._inner = inner

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc_info: object) -> None:
            self._inner.close()

        def seek(self, offset: int) -> int:
            return self._inner.seek(offset)

        def read(self, size: int = -1) -> bytes:
            reads.append((size, threading.get_ident()))
            return self._inner.read(size)

    def spy_open(self: Path, mode: str = "r") -> object:
        opened: IO[Any] = original_open(self, mode)
        return SpyFile(opened) if self == file else opened

    monkeypatch.setattr(Path, "open", spy_open)
    platform = Platform()
    platform.block_size = "8"

    async with client_for(platform) as client:
        await client.users.upload("u", path=file, file_name="big.png")

    assert reads
    assert all(0 < size <= 8 for size, _ in reads)  # 没有一次读整个文件
    assert threading.get_ident() not in {thread for _, thread in reads}  # 都不在事件循环线程
    assert len(platform.puts) == 4


async def test_parts_beyond_the_file_are_sent_empty_and_left_to_the_platform(
    small_inline: None,
) -> None:
    platform = Platform()
    platform.extra_parts = 1

    async with client_for(platform) as client:
        await client.users.upload("u", data=b"x" * 20, file_name="a.png")

    assert [put.content for put in platform.puts] == [b"x" * 10, b"x" * 10, b""]


async def test_parts_are_uploaded_concurrently_up_to_the_cap(small_inline: None) -> None:
    platform = Platform()
    platform.config["concurrency"] = 100
    in_flight = peak = 0
    full = asyncio.Event()

    async def on_put(request: httpx2.Request) -> None:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        if in_flight == upload_module.MAX_CONCURRENCY:
            full.set()
        await full.wait()
        in_flight -= 1

    platform.on_put = on_put

    async with asyncio.timeout(5), client_for(platform) as client:
        await client.users.upload("u", data=bytes(200), file_name="a.png")

    assert peak == upload_module.MAX_CONCURRENCY
    assert len(platform.puts) == 20


async def test_failed_part_cancels_the_others_without_finishing_or_merging(
    small_inline: None,
) -> None:
    platform = Platform()
    platform.config["concurrency"] = 2
    stalled = asyncio.Event()
    cancelled: list[str] = []

    async def on_put(request: httpx2.Request) -> None:
        if request.url.path.endswith("/part0"):
            stalled.set()
            try:
                await asyncio.Event().wait()  # 一直挂起，直到被取消
            except asyncio.CancelledError:
                cancelled.append(request.url.path)
                raise
        await stalled.wait()  # part0 挂起之后 part1 才失败
        platform.put_failures = [status(403, text=COS_403)]

    platform.on_put = on_put

    async with asyncio.timeout(5), client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="HTTP 403"):
            await client.users.upload("u", data=bytes(20), file_name="a.png")

    assert cancelled == ["/bucket/part0"]
    assert platform.paths() == ["/v2/users/u/upload_prepare"]  # 没有 part_finish，也没有合并


async def test_cancelling_the_upload_cancels_in_flight_parts(small_inline: None) -> None:
    platform = Platform()
    platform.config["concurrency"] = 2
    entered: list[str] = []
    cancelled: list[str] = []
    both_in_flight = asyncio.Event()

    async def on_put(request: httpx2.Request) -> None:
        entered.append(request.url.path)
        if len(entered) == 2:
            both_in_flight.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(request.url.path)
            raise

    platform.on_put = on_put

    async with asyncio.timeout(5), client_for(platform) as client:
        task = asyncio.create_task(client.users.upload("u", data=bytes(20), file_name="a.png"))
        await both_in_flight.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert sorted(cancelled) == ["/bucket/part0", "/bucket/part1"]
    assert platform.paths() == ["/v2/users/u/upload_prepare"]


@pytest.mark.parametrize(
    "prepare",
    [
        {"upload_id": "x", "block_size": "abc", "parts": [{"index": 0, "presigned_url": "u"}]},
        {"upload_id": "x", "block_size": "0", "parts": [{"index": 0, "presigned_url": "u"}]},
        {"upload_id": "x", "block_size": "10", "parts": []},
        {
            "upload_id": "x",
            "block_size": "10",
            "parts": [{"index": 0, "presigned_url": "u"}, {"index": 2, "presigned_url": "u"}],
        },
        {  # 坏掉的分片会被宽容解码丢掉，序号就断了
            "upload_id": "x",
            "block_size": "10",
            "parts": [{"index": 0}, {"index": 1, "presigned_url": "u"}],
        },
        {"block_size": "10", "parts": [{"index": 0, "presigned_url": "u"}]},
    ],
)
async def test_unusable_prepare_response_is_an_api_error(
    prepare: dict[str, object], small_inline: None
) -> None:
    platform = Platform()
    platform.prepare = prepare

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="响应无法识别"):
            await client.users.upload("u", data=bytes(20), file_name="a.png")

    assert platform.puts == []


async def test_missing_upload_config_falls_back_to_defaults(small_inline: None) -> None:
    platform = Platform()
    platform.prepare = {
        "upload_id": "up-1",
        "block_size": "100",
        "parts": [{"index": 0, "presigned_url": presigned(0)}],
    }

    async with client_for(platform) as client:
        await client.users.upload("u", data=bytes(20), file_name="a.png")

    assert len(platform.puts) == 1


def test_presigned_urls_are_hidden_from_repr() -> None:
    prepared = decode(
        json.dumps(
            {
                "upload_id": "x",
                "block_size": "1",
                "parts": [{"index": 0, "presigned_url": presigned(0)}],
            }
        ),
        UploadPrepared,
    )

    assert SIGNATURE not in repr(prepared)


# ---- 重试 ----


@pytest.mark.parametrize(
    "failure",
    [
        status(500),
        status(429),
        raising(httpx2.ConnectError("connection reset")),
    ],
)
async def test_transient_put_failures_are_retried(failure: Respond, small_inline: None) -> None:
    platform = Platform()
    platform.put_failures = [failure, failure]

    async with client_for(platform) as client:
        await client.users.upload("u", data=bytes(5) * 4, file_name="a.png")

    assert [str(put.url) for put in platform.puts] == [presigned(0)] * 3 + [presigned(1)]


@pytest.mark.parametrize(
    "failure",
    [
        status(200, {"err_code": 40093001, "message": "文件上传失败，请重试"}),
        status(502),
    ],
)
async def test_transient_part_finish_failures_are_retried(
    failure: Respond, small_inline: None
) -> None:
    platform = Platform()
    platform.finish_failures = [failure]

    async with client_for(platform) as client:
        await client.users.upload("u", data=bytes(20), file_name="a.png")

    assert platform.paths() == [
        "/v2/users/u/upload_prepare",
        *["/v2/users/u/upload_part_finish"] * 3,
        "/v2/users/u/files",
    ]


async def test_rejected_part_finish_is_not_retried(small_inline: None) -> None:
    platform = Platform()
    platform.finish_failures = [status(200, {"err_code": 40093002, "message": "超过容量"})]

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.users.upload("u", data=bytes(20), file_name="a.png")

    assert caught.value.err_code == 40093002
    assert platform.paths().count("/v2/users/u/upload_part_finish") == 1


async def test_rejected_put_fails_the_upload_with_the_error_itself(small_inline: None) -> None:
    platform = Platform()
    platform.config["concurrency"] = 2
    platform.put_failures = [status(403, text=COS_403)]

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError) as caught:  # 不是 ExceptionGroup
            await client.users.upload("u", data=bytes(40), file_name="a.png")

    error = caught.value
    assert error.status_code == 403
    assert error.err_code is None
    assert "PUT https://cos.test/bucket/part" in str(error)
    assert "SignatureDoesNotMatch" in str(error)
    assert_hidden(error, SIGNATURE)
    assert "/v2/users/u/files" not in platform.paths()


async def test_retries_stop_once_the_retry_timeout_would_be_exceeded(
    monkeypatch: pytest.MonkeyPatch, small_inline: None
) -> None:
    clock: Iterator[float] = iter([0, 200, 400])
    monkeypatch.setattr(upload_module, "monotonic", lambda: next(clock))
    platform = Platform()
    platform.put_failures = [status(503)] * 10

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="HTTP 503"):
            await client.users.upload("u", data=bytes(20), file_name="a.png")

    assert len(platform.puts) == 2  # 0 秒失败后重试；200 秒失败后再等就超过 300 秒


async def test_no_retry_when_the_delay_alone_exceeds_the_retry_timeout(
    small_inline: None,
) -> None:
    platform = Platform()
    platform.config.update(retry_delay=10, retry_timeout=5)
    platform.put_failures = [status(503)]

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError):
            await client.users.upload("u", data=bytes(20), file_name="a.png")

    assert len(platform.puts) == 1


# ---- 对象存储请求的失败映射与脱敏 ----


async def test_put_ignores_the_injected_clients_defaults(small_inline: None) -> None:
    platform = Platform()
    platform.block_size = "100"

    async with (
        httpx2.AsyncClient(
            transport=httpx2.MockTransport(platform.handle),
            headers={"Authorization": "Bearer caller-default", "X-Caller": "1"},
            auth=("user", "password"),
            params={"tenant": "caller"},
            cookies={"session": "caller"},
        ) as http_client,
        pyqbot.Client("app-id", APP_SECRET, http_client=http_client) as client,
    ):
        await client.users.upload("u", data=bytes(20), file_name="a.png")

    [put] = platform.puts
    assert str(put.url) == presigned(0)  # 签名查询串原样保留，没有被 params 替换
    for header in ("Authorization", "X-Caller", "Cookie"):
        assert header not in put.headers


async def test_transport_error_echoing_the_presigned_url_is_redacted(small_inline: None) -> None:
    platform = Platform()
    platform.config["retry_timeout"] = 0
    platform.put_failures = [raising(httpx2.ConnectError(f"cannot connect to {presigned(0)}"))]

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.NetworkError) as caught:
            await client.users.upload("u", data=bytes(20), file_name="a.png")

    assert str(caught.value).startswith("PUT https://cos.test/bucket/part0 失败：")
    assert_hidden(caught.value, SIGNATURE)
    assert caught.value.__cause__ is None  # 异常链里有签名，整条丢掉


async def test_decoded_signature_values_are_redacted_too(small_inline: None) -> None:
    platform = Platform()
    platform.config["retry_timeout"] = 0
    platform.prepare = {
        "upload_id": "x",
        "block_size": "100",
        "parts": [{"index": 0, "presigned_url": "https://cos.test/p?sign=ab%2Bcd%2Fefgh%3D"}],
        "upload_config": {"retry_timeout": 0},
    }
    platform.put_failures = [raising(httpx2.ConnectError("signature ab+cd/efgh= rejected"))]

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.NetworkError) as caught:
            await client.users.upload("u", data=bytes(20), file_name="a.png")

    assert_hidden(caught.value, "ab+cd/efgh=", "ab%2Bcd%2Fefgh%3D")
    assert "***" in str(caught.value)


async def test_put_timeout_and_harmless_errors_keep_their_cause(small_inline: None) -> None:
    platform = Platform()
    platform.config["retry_timeout"] = 0
    error = httpx2.ReadTimeout("timed out")
    platform.put_failures = [raising(error)]

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.NetworkError, match="请求超时") as caught:
            await client.users.upload("u", data=bytes(20), file_name="a.png")

    assert caught.value.__cause__ is error


async def test_invalid_presigned_url_is_a_network_error_without_the_url(
    small_inline: None,
) -> None:
    platform = Platform()
    platform.prepare = {
        "upload_id": "x",
        "block_size": "100",
        "parts": [{"index": 0, "presigned_url": f"https://[::1/{SIGNATURE}"}],
        "upload_config": {"retry_timeout": 0},
    }

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.NetworkError, match="地址不合法") as caught:
            await client.users.upload("u", data=bytes(20), file_name="a.png")

    assert_hidden(caught.value, SIGNATURE)
    assert platform.puts == []
