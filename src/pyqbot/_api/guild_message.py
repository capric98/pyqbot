"""子频道与频道私信共用的发消息实现：两者的请求体与响应相同（`server-inter/channel/message/dms.md`）。

与单聊、群聊不同：没有 `msg_type`，被动回复不带 `msg_seq`，本地图片走 `multipart/form-data`，
见 `docs/design.md`「频道消息」。
"""

import asyncio
import os
from pathlib import Path

import msgspec

from .._http import HTTP, path_segment
from .._models.event import ReplyTarget, reply_fields
from .._models.guild_message import GuildMessage
from .._models.send import Ark, Embed, Keyboard, Markdown

_DATA_FILE_NAME = "image"  # image_data 没有文件名，multipart 里总要有一个


async def guild_message_request(
    content: str | None,
    *,
    markdown: str | Markdown | None,
    keyboard: Keyboard | None,
    embed: Embed | None,
    ark: Ark | None,
    image: str | None,
    image_path: str | os.PathLike[str] | None,
    image_data: bytes | None,
    quote: str | GuildMessage | None,
) -> tuple[dict[str, object], tuple[str, bytes] | None]:
    """检查参数并拼出请求体（不含被动回复的字段），另返回要随 multipart 上传的图片。

    Raises:
        ValueError: 没有任何内容（空串的 `content` 算没传）；`image`、`image_path`、`image_data` 传了不止一个；
            `keyboard` 没有随 `markdown`；`quote` 是空的消息 ID。
        OSError: 读取 `image_path` 失败。
    """
    content = content or None  # 同 `message_body()`
    images = [
        name
        for name, value in (
            ("image", image),
            ("image_path", image_path),
            ("image_data", image_data),
        )
        if value is not None
    ]
    if len(images) > 1:
        raise ValueError(f"{'、'.join(images)} 只能传一个")
    if content is None and markdown is None and embed is None and ark is None and not images:
        raise ValueError("没有要发送的内容：content、markdown、embed、ark、图片至少传一个")
    if keyboard is not None and markdown is None:
        raise ValueError("keyboard 只能随 markdown 消息发送")
    quote_id = None if quote is None else message_id_of(quote)
    if quote_id == "":
        raise ValueError("quote 没有可用的消息 ID")

    body: dict[str, object] = {}
    if content is not None:
        body["content"] = content
    if markdown is not None:
        body["markdown"] = Markdown(content=markdown) if isinstance(markdown, str) else markdown
    if keyboard is not None:
        body["keyboard"] = keyboard
    if embed is not None:
        body["embed"] = embed
    if ark is not None:
        body["ark"] = ark
    if image is not None:
        body["image"] = image
    if quote_id is not None:
        body["message_reference"] = {"message_id": quote_id}

    file_image = None
    if image_path is not None:
        source = Path(image_path)
        file_image = (source.name, await asyncio.to_thread(source.read_bytes))
    elif image_data is not None:
        file_image = (_DATA_FILE_NAME, image_data)
    return body, file_image


async def send_guild_message(
    http: HTTP,
    path: str,
    body: dict[str, object],
    file_image: tuple[str, bytes] | None,
    *,
    reply_to: ReplyTarget | None,
) -> GuildMessage:
    """发送 `guild_message_request()` 拼好的消息；`reply_to` 不为 `None` 时是被动回复。"""
    if reply_to is not None:
        # 频道发消息的文档没有 msg_seq，不发也不占用（docs/errata.md）。
        body |= reply_fields(reply_to, seq=False)
    if file_image is None:
        return await http.request("POST", path, type_=GuildMessage, json=body)
    # multipart 里对象与数组字段要写成 JSON 字符串（send.md「Content-Type」）。
    fields = {
        key: value if isinstance(value, str) else msgspec.json.encode(value).decode()
        for key, value in body.items()
    }
    return await http.request(
        "POST", path, type_=GuildMessage, data=fields, files={"file_image": file_image}
    )


def recall_params(hidetip: bool) -> dict[str, str | int]:
    """撤回接口的查询参数。"""
    return {"hidetip": "true" if hidetip else "false"}


def message_id_of(message: str | GuildMessage) -> str:
    """消息 ID：字符串原样返回，消息对象取 `id`。"""
    return message if isinstance(message, str) else message.id


def message_path(base: str, message: str | GuildMessage) -> str:
    """`{base}/{message_id}`。

    Raises:
        ValueError: 消息 ID 为空。
    """
    return f"{base}/{path_segment(message_id_of(message), 'message_id')}"
