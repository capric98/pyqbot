"""单聊与群聊共用的发消息实现：两者的请求体与响应相同，只有路径和单聊独有的字段不同。

`msg_type` 的推断与参数组合的规则见 `docs/design.md`「请求层与接口分组」。
"""

from .._http import HTTP, path_segment
from .._models.event import ReplyTarget, reply_fields
from .._models.message import C2CMessage, GroupMessage, MessageType, SentMessage
from .._models.send import Card, Keyboard, Markdown, Media

type Quote = str | SentMessage | C2CMessage | GroupMessage

_CARD_TYPE = "tuwen"  # 图文卡片，目前唯一的卡片类型
_INPUT_TYPE = 1  # 文档只说「填1」
MAX_TYPING_SECONDS = 60


def message_body(
    content: str | None,
    *,
    markdown: str | Markdown | None,
    keyboard: Keyboard | None,
    media: Media | None,
    card: Card | None,
    quote: Quote | None,
) -> dict[str, object]:
    """按传了哪些内容推断 `msg_type`，拼出请求体（不含被动回复的字段）。

    Raises:
        ValueError: 没有任何内容（空串的 `content` 算没传），或内容参数的组合不合法。
    """
    content = content or None  # 空串当作没传，免得把空文本发出去（如原样复读一条纯图片消息）
    candidates = (("markdown", markdown), ("media", media), ("card", card))
    kinds = [name for name, value in candidates if value is not None]
    if len(kinds) > 1:
        raise ValueError(f"{'、'.join(kinds)} 只能传一个")
    if content is None and not kinds:
        raise ValueError("没有要发送的内容：content、markdown、media、card 至少传一个")
    if markdown is not None and content is not None:
        raise ValueError("传了 markdown 时不能再传 content，正文写在 markdown 里")
    if keyboard is not None and markdown is None:
        raise ValueError("keyboard 只能随 markdown 消息发送")

    body: dict[str, object] = {}
    if content is not None:
        body["content"] = content
    if markdown is not None:
        body["msg_type"] = MessageType.MARKDOWN
        body["markdown"] = Markdown(content=markdown) if isinstance(markdown, str) else markdown
    elif media is not None:
        body["msg_type"] = MessageType.MEDIA
        body["media"] = {"file_info": media.file_info}
    elif card is not None:
        body["msg_type"] = MessageType.CARD
        body["card"] = {"type": _CARD_TYPE, "content": card}
    else:
        body["msg_type"] = MessageType.TEXT
    if keyboard is not None:
        body["keyboard"] = keyboard
    if quote is not None:
        body["message_reference"] = {"message_id": _ref_idx(quote)}
    return body


async def send_message(
    http: HTTP,
    path: str,
    body: dict[str, object],
    *,
    reply_to: ReplyTarget | None,
) -> SentMessage:
    """发送 `message_body()` 拼好的消息；`reply_to` 不为 `None` 时是被动回复。"""
    if reply_to is not None:
        body |= reply_fields(reply_to)
    return await http.request("POST", path, type_=SentMessage, json=body)


def typing_body(seconds: int) -> dict[str, object]:
    """「正在输入」的请求体（不含被动回复的字段）。

    Raises:
        ValueError: `seconds` 不是 1～60 之间的整数。
    """
    # bool 是 int 的子类，不排除会编码成 true。
    if isinstance(seconds, bool) or not 1 <= seconds <= MAX_TYPING_SECONDS:
        raise ValueError(f"seconds 必须是 1～{MAX_TYPING_SECONDS} 之间的整数，收到：{seconds!r}")
    return {
        "msg_type": MessageType.INPUT_NOTIFY,
        "input_notify": {"input_type": _INPUT_TYPE, "input_second": seconds},
    }


def message_path(base: str, message: str | SentMessage | GroupMessage) -> str:
    """撤回接口的路径：`{base}/{message_id}`。

    Raises:
        ValueError: 消息 ID 为空。
    """
    message_id = message if isinstance(message, str) else message.id
    return f"{base}/{path_segment(message_id, 'message_id')}"


def _ref_idx(quote: Quote) -> str:
    match quote:
        case str():
            ref = quote
        case SentMessage():
            ref = quote.ext_info.ref_idx if quote.ext_info is not None else None
        case _:
            ref = quote.msg_idx
    if not ref:
        raise ValueError(f"quote 没有可用的引用索引（{type(quote).__name__}）")
    return ref
