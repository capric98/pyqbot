"""单聊与群聊共用的富媒体上传：按来源与大小选用 URL、内联数据或分片上传。规则见 `docs/design.md`。"""

import asyncio
import base64
import hashlib
import os
from collections.abc import Awaitable, Callable, Coroutine, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from .._errors import APIError, NetworkError, QQBotError
from .._http import HTTP
from .._models.send import Media
from .._models.upload import FileType, UploadPart, UploadPrepared

type Source = Path | bytes

INLINE_LIMIT = 3 * 1024 * 1024
"""不超过它的本地数据用 `file_data` 内联上传，否则分片：base64 后约 4 MiB，留在文档的 5M 之内。"""
MD5_10M_SIZE = 10002432
MAX_CONCURRENCY = 8  # 每个并发的分片都在内存里，平台下发再大也不超过它
_READ_SIZE = 1024 * 1024
_PART_FINISH_RETRY_CODE = 40093001  # 「分片转存 BDH 通道异常，请重试」

_FILE_TYPES = {
    **dict.fromkeys((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"), FileType.IMAGE),
    ".mp4": FileType.VIDEO,
    **dict.fromkeys((".silk", ".slk", ".mp3", ".wav", ".ogg"), FileType.VOICE),
}


async def upload_media(
    http: HTTP,
    base: str,
    *,
    path: str | os.PathLike[str] | None,
    url: str | None,
    data: bytes | None,
    file_name: str | None,
    file_type: FileType | None,
    send: bool,
) -> Media:
    """上传到 `{base}/files`（`base` 是 `/v2/users/{openid}` 或 `/v2/groups/{group_openid}`）。

    Raises:
        ValueError: 参数组合不合法、文件为空，或推断不出 `file_type`。
    """
    given = [
        name for name, value in (("path", path), ("url", url), ("data", data)) if value is not None
    ]
    if len(given) != 1:
        raise ValueError(f"path、url、data 必须且只能传一个，实际传了：{'、'.join(given) or '无'}")

    body: dict[str, object]
    if url is not None:
        if file_name is not None:
            raise ValueError("file_name 只用于 path 或 data：url 上传的文件由平台下载")
        if file_type is None:
            file_type = _infer_file_type(urlsplit(url).path, "url")
        body = {"file_type": file_type, "url": url}
    else:
        source, name, size = await local_source(path, data, file_name)
        if file_type is None:
            file_type = _infer_file_type(name, "文件名")
        body = {"file_type": file_type, "file_name": name}
        if size <= INLINE_LIMIT:
            content = await asyncio.to_thread(read, source, 0, size)
            # 文档没说 file_data 的编码，按 base64（docs/errata.md）。
            body["file_data"] = base64.b64encode(content).decode("ascii")
        else:
            body["upload_id"] = await _upload_parts(http, base, source, name, size, file_type)
    # 显式发出 false：文档没写默认值，省略时万一被当成直接发送会占用主动消息额度。
    body["srv_send_msg"] = send
    return await http.request("POST", f"{base}/files", type_=Media, json=body)


async def local_source(
    path: str | os.PathLike[str] | None, data: bytes | None, file_name: str | None
) -> tuple[Source, str, int]:
    """把 `path=` / `data=` 换成（来源、文件名、字节数）。

    Raises:
        ValueError: `path` 与 `data` 不是恰好传了一个，`data` 没有 `file_name`，或文件为空。
        OSError: 读取文件信息失败。
    """
    source: Source
    if (path is None) == (data is None):
        raise ValueError("path 与 data 必须且只能传一个")
    if data is not None:
        if not file_name:
            raise ValueError("用 data 上传时必须给出 file_name")
        source, name, size = data, file_name, len(data)
    else:
        source = Path(path or "")  # 上面已排除 path 为 None
        name = file_name or source.name
        size = (await asyncio.to_thread(source.stat)).st_size
    if size == 0:
        raise ValueError(f"{name!r} 是空文件，不能上传")
    return source, name, size


def _infer_file_type(name: str, what: str) -> FileType:
    file_type = _FILE_TYPES.get(PurePosixPath(name).suffix.lower())
    if file_type is None:
        raise ValueError(
            f"无法从{what} {name!r} 推断 file_type，请显式传入，如 pyqbot.FileType.FILE"
        )
    return file_type


@dataclass(frozen=True, slots=True)
class Digests:
    """整个文件的 MD5、SHA1，以及前 `MD5_10M_SIZE` 字节的 MD5（十六进制）。"""

    md5: str
    sha1: str
    md5_10m: str


def digests(source: Source, size: int) -> Digests:
    """逐块计算 `Digests`，不把整个文件读进内存。会阻塞，在线程里调用。"""
    md5 = hashlib.md5(usedforsecurity=False)
    sha1 = hashlib.sha1(usedforsecurity=False)
    md5_10m = hashlib.md5(usedforsecurity=False)
    head = MD5_10M_SIZE
    for chunk in _chunks(source, size):
        md5.update(chunk)
        sha1.update(chunk)
        if head > 0:
            md5_10m.update(chunk[:head])
            head -= len(chunk)
    return Digests(md5.hexdigest(), sha1.hexdigest(), md5_10m.hexdigest())


def _chunks(source: Source, size: int) -> Iterator[bytes]:
    if isinstance(source, bytes):
        for offset in range(0, size, _READ_SIZE):
            yield source[offset : offset + _READ_SIZE]
        return
    with source.open("rb") as file:
        while chunk := file.read(_READ_SIZE):
            yield chunk


def read(source: Source, offset: int, length: int) -> bytes:
    """读出 `[offset, offset + length)`。读文件时会阻塞，在线程里调用。"""
    if isinstance(source, bytes):
        return source[offset : offset + length]
    with source.open("rb") as file:
        file.seek(offset)
        return file.read(length)


def _read_part(source: Source, offset: int, length: int) -> tuple[bytes, str]:
    chunk = read(source, offset, length)
    return chunk, hashlib.md5(chunk, usedforsecurity=False).hexdigest()


async def _upload_parts(
    http: HTTP, base: str, source: Source, name: str, size: int, file_type: FileType
) -> str:
    """走完预上传、分片 PUT 与逐片确认，返回合并要用的 `upload_id`。"""
    hashes = await asyncio.to_thread(digests, source, size)
    prepared = await http.request(
        "POST",
        f"{base}/upload_prepare",
        type_=UploadPrepared,
        json={
            "file_type": file_type,
            "file_size": str(size),
            "file_name": name,
            "md5": hashes.md5,
            "sha1": hashes.sha1,
            "md5_10m": hashes.md5_10m,
        },
    )
    config = prepared.upload_config
    slots = asyncio.Semaphore(max(1, min(config.concurrency, MAX_CONCURRENCY)))
    delay, give_up_after = max(0, config.retry_delay), max(0, config.retry_timeout)
    chunk_size, first_index = prepared.chunk_size, prepared.first_index

    async def upload_part(part: UploadPart) -> None:
        offset = (part.index - first_index) * chunk_size
        async with slots:
            # 分片数与文件大小对不上时不在本地判断，由合并接口拒绝。
            length = max(0, min(chunk_size, size - offset))
            chunk, md5 = await asyncio.to_thread(_read_part, source, offset, length)
            await _retrying(
                lambda: http.put_presigned(part.presigned_url, chunk), delay, give_up_after
            )
            body = {
                "upload_id": prepared.upload_id,
                "part_index": part.index,
                "block_size": str(len(chunk)),
                "md5": md5,
            }
            finish = f"{base}/upload_part_finish"
            await _retrying(
                lambda: http.request("POST", finish, type_=None, json=body), delay, give_up_after
            )

    await _run_all(upload_part(part) for part in prepared.parts)
    return prepared.upload_id


def _is_transient(exc: QQBotError) -> bool:
    return isinstance(exc, NetworkError) or (
        isinstance(exc, APIError)
        and (
            exc.status_code >= 500
            or exc.status_code == 429
            or exc.err_code == _PART_FINISH_RETRY_CODE
        )
    )


async def _retrying[T](
    operation: Callable[[], Awaitable[T]], delay: float, give_up_after: float
) -> T:
    """临时性失败时隔 `delay` 秒重试；下一次尝试会晚于首次尝试后 `give_up_after` 秒时不再重试，抛出最后的异常。"""
    deadline = monotonic() + give_up_after
    while True:
        try:
            return await operation()
        except QQBotError as exc:
            if not _is_transient(exc) or monotonic() + delay > deadline:
                raise
        await asyncio.sleep(delay)


# create_task 的签名就是 Coroutine[Any, Any, T]。
async def _run_all(jobs: Iterable[Coroutine[Any, Any, None]]) -> None:
    """并发运行；一个失败就取消其余，抛出最先失败的那个异常本身，而不是异常组。"""
    failure: BaseException | None = None
    try:
        async with asyncio.TaskGroup() as group:
            for job in jobs:
                group.create_task(job)
    except BaseExceptionGroup as exc_group:
        failure = exc_group.exceptions[0]
    if failure is not None:
        raise failure
