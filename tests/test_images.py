"""素材库：上传三步、列出、删除，以及对象存储请求的失败映射与脱敏。"""

import hashlib
import json
import traceback
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
import pytest

import pyqbot
from pyqbot._model import decode
from pyqbot._models.upload import ImagePrepared

TOKEN = "token-value-never-shown"
SIGNATURE = "q-signature-0123456789abcdef"
PREVIEW = "https://cos.test/preview.png?q-signature=preview-signature-0123"
PRESIGNED = f"https://cos.test/robot_upload/k.png?q-sign-algorithm=sha1&q-signature={SIGNATURE}"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(32))
COMPLETED: dict[str, object] = {
    "image_id": "102083127_3f9a",
    "url": "qqbot-media://image/v1/tok",
    "ttl": 7776000,
    "preview_url": PREVIEW,
}

type Respond = Callable[[httpx2.Request], httpx2.Response]


class Platform:
    """扮演开放平台与对象存储：`cos.test` 上的 PUT 记进 `puts`，其余请求记进 `calls`。"""

    def __init__(self) -> None:
        self.calls: list[httpx2.Request] = []
        self.puts: list[httpx2.Request] = []
        self.put: Respond = lambda request: httpx2.Response(200, headers={"ETag": '"etag-md5"'})
        self.respond: Respond = self.default

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "cos.test":
            self.puts.append(request)
            return self.put(request)
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})
        self.calls.append(request)
        return self.respond(request)

    def default(self, request: httpx2.Request) -> httpx2.Response:
        match request.url.path:
            case "/v2/media-images/prepare":
                body = {"upload_id": "up-1", "presigned_url": PRESIGNED, "expires_in": 3600}
                return httpx2.Response(200, json=body)
            case "/v2/media-images/complete":
                return httpx2.Response(200, json=COMPLETED)
            case _:
                return httpx2.Response(200, json={})

    def bodies(self) -> list[object]:
        return [json.loads(request.content) if request.content else None for request in self.calls]


@asynccontextmanager
async def client_for(platform: Platform) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client("app-id", "app-secret", http_client=http_client) as client,
    ):
        yield client


def raising(error: Exception) -> Respond:
    def respond(request: httpx2.Request) -> httpx2.Response:
        raise error

    return respond


def assert_hidden(error: BaseException, *secrets: str) -> None:
    shown = "".join(traceback.format_exception(error))
    for secret in secrets:
        assert secret not in str(error)
        assert secret not in repr(error)
        assert secret not in shown


# ---- 上传 ----


async def test_upload_prepares_puts_and_completes(tmp_path: Path) -> None:
    platform = Platform()
    file = tmp_path / "kline.png"
    file.write_bytes(PNG)

    async with client_for(platform) as client:
        image = await client.images.upload(path=file)

    assert image == pyqbot.MediaImage(
        image_id="102083127_3f9a",
        url="qqbot-media://image/v1/tok",
        ttl=7776000,
        preview_url=PREVIEW,
    )
    assert [(r.method, r.url.path) for r in platform.calls] == [
        ("POST", "/v2/media-images/prepare"),
        ("POST", "/v2/media-images/complete"),
    ]
    assert platform.bodies() == [
        {
            "file_name": "kline.png",
            "file_size": len(PNG),  # 这里是整数，分片上传的 upload_prepare 是字符串
            "content_type": "image/png",
            "md5": hashlib.md5(PNG).hexdigest(),
            "sha1": hashlib.sha1(PNG).hexdigest(),
        },
        {"upload_id": "up-1", "md5": "etag-md5"},  # 去掉引号的 ETag
    ]
    [put] = platform.puts
    assert (put.method, str(put.url), put.content) == ("PUT", PRESIGNED, PNG)
    assert put.headers["Content-Type"] == "image/png"
    assert "Authorization" not in put.headers


@pytest.mark.parametrize(
    ("file_name", "content_type"),
    [
        ("a.JPG", "image/jpeg"),
        ("a.jpeg", "image/jpeg"),
        ("a.gif", "image/gif"),
        ("a.webp", "image/webp"),
    ],
)
async def test_content_type_follows_the_extension(file_name: str, content_type: str) -> None:
    platform = Platform()

    async with client_for(platform) as client:
        await client.images.upload(data=PNG, file_name=file_name)

    [put] = platform.puts
    assert put.headers["Content-Type"] == content_type
    prepare = platform.bodies()[0]
    assert isinstance(prepare, dict)
    assert prepare["content_type"] == content_type  # pyright: ignore[reportUnknownMemberType]


async def test_local_md5_is_used_when_the_put_response_has_no_etag() -> None:
    platform = Platform()
    platform.put = lambda request: httpx2.Response(200)

    async with client_for(platform) as client:
        await client.images.upload(data=PNG, file_name="a.png")

    assert platform.bodies()[1] == {"upload_id": "up-1", "md5": hashlib.md5(PNG).hexdigest()}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "必须且只能传一个"),
        ({"path": "a.png", "data": PNG, "file_name": "a.png"}, "必须且只能传一个"),
        ({"data": PNG}, "file_name"),
        ({"data": PNG, "file_name": "a.bmp"}, "png、jpeg、gif、webp"),
        ({"data": b"", "file_name": "a.png"}, "空文件"),
    ],
)
async def test_invalid_arguments_are_rejected_before_sending(
    kwargs: dict[str, object], message: str
) -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match=message):
            await client.images.upload(**kwargs)  # pyright: ignore[reportArgumentType]

    assert platform.calls == []


async def test_rejected_prepare_is_an_api_error_and_nothing_is_put() -> None:
    platform = Platform()
    platform.respond = lambda request: httpx2.Response(
        200, json={"err_code": 40035007, "message": "图片数量超过上限"}
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="图片数量超过上限") as caught:
            await client.images.upload(data=PNG, file_name="a.png")

    assert caught.value.err_code == 40035007
    assert platform.puts == []


async def test_rejected_put_is_an_api_error_without_the_signature() -> None:
    platform = Platform()
    platform.put = lambda request: httpx2.Response(
        403, text=f"<Error><Code>AccessDenied</Code><Message>{SIGNATURE}</Message></Error>"
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.images.upload(data=PNG, file_name="a.png")

    assert (
        str(caught.value) == "PUT https://cos.test/robot_upload/k.png 失败：HTTP 403 AccessDenied"
    )
    assert caught.value.status_code == 403
    assert not caught.value.outcome_unknown
    assert_hidden(caught.value, SIGNATURE)
    assert [r.url.path for r in platform.calls] == ["/v2/media-images/prepare"]


async def test_put_with_a_server_error_may_have_been_stored() -> None:
    platform = Platform()
    platform.put = lambda request: httpx2.Response(503)

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.images.upload(data=PNG, file_name="a.png")

    assert caught.value.outcome_unknown


async def test_put_transport_error_echoing_the_url_is_redacted() -> None:
    platform = Platform()
    platform.put = raising(httpx2.ConnectError(f"proxy refused {PRESIGNED}"))

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.NetworkError) as caught:
            await client.images.upload(data=PNG, file_name="a.png")

    assert_hidden(caught.value, SIGNATURE)
    assert "***" in str(caught.value)
    assert caught.value.__cause__ is None


def assert_preview_hidden(image: pyqbot.MediaImage) -> None:
    assert image.preview_url == PREVIEW  # 属性照常可读
    assert "preview-signature" not in repr(image)
    assert "preview-signature" not in repr(list(image.__rich_repr__()))


async def test_preview_url_is_hidden_from_repr_of_uploaded_and_listed_images() -> None:
    platform = Platform()
    page: dict[str, object] = {"images": [{**COMPLETED, "file_name": "a.png"}], "next_cursor": ""}

    async with client_for(platform) as client:
        uploaded = await client.images.upload(data=PNG, file_name="a.png")
        platform.respond = lambda request: httpx2.Response(200, json=page)
        listed = [image async for image in client.images.iter_images()]

    for image in (uploaded, *listed):
        assert_preview_hidden(image)


def test_presigned_url_is_hidden_from_repr() -> None:
    prepared = decode(
        json.dumps({"upload_id": "x", "presigned_url": PRESIGNED}).encode(), ImagePrepared
    )

    assert SIGNATURE not in repr(prepared)


# ---- 列出与删除 ----


async def test_iter_images_follows_next_cursor() -> None:
    pages: dict[str | None, object] = {
        None: {"images": [{"image_id": "1", "url": "u1"}], "next_cursor": "c1", "total": 2},
        "c1": {
            "images": [
                {
                    "image_id": "2",
                    "url": "u2",
                    "file_name": "b.png",
                    "created_at": 1792051409,
                    "expires_at": 1792656210,
                },
                {"url": "missing image_id"},
            ],
            "next_cursor": "",
        },
    }
    platform = Platform()
    platform.respond = lambda request: httpx2.Response(
        200, json=pages[request.url.params.get("cursor")]
    )

    async with client_for(platform) as client:
        images = [image async for image in client.images.iter_images()]

    assert [(i.image_id, i.url, i.file_name, i.created_at, i.expires_at) for i in images] == [
        ("1", "u1", None, None, None),
        ("2", "u2", "b.png", 1792051409, 1792656210),
    ]
    assert [(r.method, r.url.path, dict(r.url.params)) for r in platform.calls] == [
        ("GET", "/v2/media-images", {}),
        ("GET", "/v2/media-images", {"cursor": "c1"}),
    ]


@pytest.mark.parametrize(
    ("created_at", "expected"),
    [("1794861718", 1794861718), (1794861718, 1794861718), ("soon", None), ("9" * 5000, None)],
)
async def test_list_times_may_be_digit_strings(created_at: object, expected: int | None) -> None:
    # 文档写 int64，实测是数字字符串；认不出时为 None，不让整张图丢掉。
    image = {"image_id": "1", "url": "u", "created_at": created_at, "expires_at": "1802637718"}
    platform = Platform()
    platform.respond = lambda request: httpx2.Response(200, json={"images": [image]})

    async with client_for(platform) as client:
        [listed] = [image async for image in client.images.iter_images()]

    assert (listed.created_at, listed.expires_at) == (expected, 1802637718)
    assert listed.to_dict()["created_at"] == created_at  # 原值保留


async def test_delete_accepts_an_id_or_an_image() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        await client.images.delete("a/b")
        await client.images.delete(pyqbot.MediaImage(image_id="102083127_3f9a", url="u"))

    assert [(r.method, r.url.raw_path.decode()) for r in platform.calls] == [
        ("DELETE", "/v2/media-images/a%2Fb/delete"),
        ("DELETE", "/v2/media-images/102083127_3f9a/delete"),
    ]


async def test_delete_failures_become_api_errors() -> None:
    platform = Platform()
    platform.respond = lambda request: httpx2.Response(
        200, json={"err_code": 40035008, "message": "图片不存在或已被删除"}
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.images.delete("gone")
        with pytest.raises(ValueError, match="image_id"):
            await client.images.delete("")

    assert caught.value.err_code == 40035008
