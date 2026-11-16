"""素材库接口（`server-inter/message/material-management.md`）。"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import PurePosixPath

from .._http import HTTP, path_segment
from .._models.upload import ImagePage, ImagePrepared, MediaImage
from .paging import Page, paginate
from .upload import digests, local_source, read

# 平台要求扩展名与 Content-Type 一致，所以按扩展名决定，不让调用方另传。
_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class Images:
    """素材库：预先上传、供 Markdown 消息引用的图片，经 `client.images` 使用。

    素材属于机器人本身，单聊、群聊都能引用。限制（以平台为准，超出时由平台拒绝）：
    单张不超过 10 MB；格式为 png、jpeg、gif、webp；每个机器人最多 100 张（删除可释放）；
    连续 90 天没被消息引用就失效，每次引用后顺延。
    """

    def __init__(self, http: HTTP) -> None:
        self._http = http

    async def upload(
        self,
        *,
        path: str | os.PathLike[str] | None = None,
        data: bytes | None = None,
        file_name: str | None = None,
    ) -> MediaImage:
        """上传一张图片到素材库，返回的 `url` 可以直接写进 Markdown。

        依次调用官方接口 `POST /v2/media-images/prepare`、PUT 预签名地址、`POST /v2/media-images/complete`。

        Args:
            path: 本地图片的路径；与 `data` 二选一。
            data: 图片的内容；与 `path` 二选一，此时必须给出 `file_name`。
            file_name: 上报给平台的文件名，默认取 `path` 的文件名。格式由扩展名决定：
                `.png`、`.jpg`、`.jpeg`、`.gif`、`.webp`。

        Raises:
            APIError: 平台拒绝，例如超过大小上限（`err_code` 40035002）或数量上限（40035007）。
            NetworkError: 没有拿到平台或对象存储的响应。
            ValueError: `path` 与 `data` 不是恰好传了一个，`data` 没有 `file_name`，文件为空，
                或扩展名不是支持的图片格式。
            OSError: 读取文件失败。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            image = await client.images.upload(path="kline.png")
            await client.users.send_message(openid, markdown=f"![K 线 #800px #400px]({image.url})")
            ```
        """
        source, name, size = await local_source(path, data, file_name)
        content_type = _CONTENT_TYPES.get(PurePosixPath(name).suffix.lower())
        if content_type is None:
            raise ValueError(f"素材库只支持 png、jpeg、gif、webp，无法从文件名 {name!r} 判断格式")
        hashes = await asyncio.to_thread(digests, source, size)
        prepared = await self._http.request(
            "POST",
            "/v2/media-images/prepare",
            type_=ImagePrepared,
            json={
                "file_name": name,
                "file_size": size,
                "content_type": content_type,
                "md5": hashes.md5,
                "sha1": hashes.sha1,
            },
        )
        # 大小由平台在 prepare 时把关，过了这一步才把整张图读进内存。
        content = await asyncio.to_thread(read, source, 0, size)
        response = await self._http.put_presigned(
            prepared.presigned_url, content, content_type=content_type
        )
        # 文档要求 complete 带 PUT 响应的 ETag（去掉引号即 MD5）；没有时退回本地算的 MD5。
        etag = response.headers.get("ETag", "").strip('"') or hashes.md5
        return await self._http.request(
            "POST",
            "/v2/media-images/complete",
            type_=MediaImage,
            json={"upload_id": prepared.upload_id, "md5": etag},
        )

    def iter_images(self) -> AsyncIterator[MediaImage]:
        """按上传时间从新到旧列出素材库里仍有效的图片。

        对应官方接口 `GET /v2/media-images`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            async for image in client.images.iter_images():
                print(image.image_id, image.file_name, image.expires_at)
            ```
        """

        async def fetch(cursor: str | None) -> Page[MediaImage, str]:
            params = {"cursor": cursor} if cursor else None
            page = await self._http.request(
                "GET", "/v2/media-images", type_=ImagePage, params=params
            )
            return Page(page.images, page.next_cursor)

        return paginate(fetch)

    async def delete(self, image: str | MediaImage) -> None:
        """从素材库删除一张图片，释放数量额度。引用链接随即失效，已发出的消息不受影响。

        对应官方接口 `DELETE /v2/media-images/{image_id}/delete`。

        Args:
            image: 要删除的图片或它的 `image_id`。

        Raises:
            APIError: 平台拒绝，例如图片不存在或已删除（`err_code` 40035008）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `image_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        image_id = image if isinstance(image, str) else image.image_id
        path = f"/v2/media-images/{path_segment(image_id, 'image_id')}/delete"
        await self._http.request("DELETE", path, type_=None)
