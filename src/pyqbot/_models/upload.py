"""富媒体上传与素材库的模型。

富媒体见 `autogen/api/v2_users_user_openid_files.post.md` 与预上传、分片完成两页（群聊相同）；
素材库见 `server-inter/message/material-management.md`。上传结果是 `_models/send.py` 的 `Media`。
"""

import msgspec

from .._model import Model, OpenIntEnum


class FileType(OpenIntEnum):
    """富媒体的类型，即上传接口的 `file_type`。

    超过该类型的软限制（图片、语音 20 MB，视频 30 MB）时平台会按文件上传，超过 200 MB 报错。
    各页列出的支持格式不一致，见 `docs/errata.md`。
    """

    IMAGE = 1
    VIDEO = 2
    VOICE = 3
    FILE = 4


class UploadPart(Model):
    """预上传给出的一个分片。"""

    _secret_fields = frozenset({"presigned_url"})  # 查询串是临时签名

    index: int
    presigned_url: str


class UploadConfig(Model):
    """平台下发的分片上传配置；时间单位是秒，默认值取自文档。"""

    concurrency: int = 1
    retry_timeout: int = 300
    retry_delay: int = 1


class UploadPrepared(Model):
    """预上传（`upload_prepare`）的响应。"""

    upload_id: str
    block_size: int | str  # 文档写的是字符串
    parts: tuple[UploadPart, ...]
    upload_config: UploadConfig = msgspec.field(default_factory=UploadConfig)

    def __post_init__(self) -> None:
        # 在解码时检查：不合法就是「响应无法识别」。宽容解码会丢掉坏的分片，序号就不连续了。
        if self.chunk_size <= 0:
            raise ValueError("block_size 不是正数")
        indexes = sorted(part.index for part in self.parts)
        if (
            not indexes
            or indexes[0] not in (0, 1)
            or indexes != list(range(indexes[0], indexes[0] + len(indexes)))
        ):
            raise ValueError("parts 的序号不是从 0 或 1 开始的连续整数")

    @property
    def chunk_size(self) -> int:
        """分片大小（字节）。"""
        return int(self.block_size)

    @property
    def first_index(self) -> int:
        """第一片的序号：文档写从 0 开始，实测从 1 开始（`docs/errata.md`）。"""
        return min(part.index for part in self.parts)


class ImagePrepared(Model):
    """素材库申请上传（`/v2/media-images/prepare`）的响应。"""

    _secret_fields = frozenset({"presigned_url"})

    upload_id: str
    presigned_url: str


class MediaImage(Model):
    """素材库里的一张图片，在 Markdown 里写 `![说明 #宽px #高px](url)` 引用（宽高必须写，否则不显示）。

    Attributes:
        image_id: 图片 ID，删除时用。
        url: Markdown 里引用的地址，形如 `qqbot-media://image/v1/...`，只有本机器人能引用。
        file_name: 上传时的文件名；只有列出图片时返回。
        preview_url: 临时预览链接，时效很短，不要保存；带签名，所以 `repr()` 里显示为 `***`。
        ttl: 有效期窗口，单位秒；只有上传时返回。
    """

    _secret_fields = frozenset({"preview_url"})  # 也是带签名的预签名地址

    image_id: str
    url: str
    file_name: str | None = None
    preview_url: str | None = None
    ttl: int | None = None
    # 文档写 int64，实测列出时是数字字符串（`docs/errata.md`）；两种都收，由同名属性换成整数。
    _created_at: int | str | None = msgspec.field(default=None, name="created_at")
    _expires_at: int | str | None = msgspec.field(default=None, name="expires_at")

    @property
    def created_at(self) -> int | None:
        """上传时间（Unix 秒）；只有列出图片时返回。"""
        return _unix_seconds(self._created_at)

    @property
    def expires_at(self) -> int | None:
        """过期时间（Unix 秒），每次被消息引用后顺延到 90 天后；只有列出图片时返回。"""
        return _unix_seconds(self._expires_at)


def _unix_seconds(value: int | str | None) -> int | None:
    if not isinstance(value, str):
        return value
    try:
        return int(value)
    except ValueError:
        return None


class ImagePage(Model):
    """素材库图片列表的一页。"""

    images: tuple[MediaImage, ...] = ()
    next_cursor: str | None = None
