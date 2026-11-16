"""网关 payload 的编解码（`dev-prepare/event-emit/payload.md`、`dev-prepare/event-emit/websocket.md`）。

上下行都是 `{"op", "d", "s", "t", "id"}` 结构的 JSON 文本帧。下行先用 `decode_payload` 解出信封，
`d` 保持原始 JSON，再按 `op` / `t` 用 `GatewayPayload.decode_data` 解成 `Hello`、`Ready` 或事件模型，
避免先解成 `dict` 再转一次。上行的 `encode_*` 直接返回要发送的文本帧，结果含 token，不得记日志。
"""

import sys
from dataclasses import dataclass, field

import msgspec

from .._errors import PayloadError
from .._model import Model, OpenIntEnum, decode
from .intents import Intents

READY_EVENT = "READY"
RESUMED_EVENT = "RESUMED"  # d 为空字符串

# 文档出入见 docs/errata.md；格式只在这里出现。
_TOKEN_PREFIX = "QQBot "

# 文档称 properties「目前无实际作用」，按示例的三个键填上。
_PROPERTIES = {"$os": sys.platform, "$browser": "pyqbot", "$device": "pyqbot"}


class OpCode(OpenIntEnum):
    """payload 的 `op` 字段，含义见 `payload.md` 的 OpCode 表。"""

    DISPATCH = 0
    HEARTBEAT = 1
    IDENTIFY = 2
    RESUME = 6
    RECONNECT = 7
    INVALID_SESSION = 9
    HELLO = 10
    HEARTBEAT_ACK = 11
    HTTP_CALLBACK_ACK = 12
    CALLBACK_VALIDATION = 13


@dataclass(frozen=True, slots=True, kw_only=True)
class GatewayPayload:
    """解出的一条下行 payload。

    Attributes:
        op: 操作码。
        data: `d` 的原始 JSON；没有 `d` 时为 `b"null"`。
        s: 序列号，心跳与 Resume 要带上最近收到的值。
        t: Dispatch 的事件类型，如 `"C2C_MESSAGE_CREATE"`。
        id: 事件 ID。
    """

    op: OpCode
    data: bytes = field(default=b"null", repr=False)
    s: int | None = None
    t: str | None = None
    id: str | None = None

    def decode_data[T](self, type_: type[T]) -> T:
        """把 `d` 解码成 `type_`；模型里有默认值的字段类型不符时退回默认值。

        Raises:
            PayloadError: `d` 与 `type_` 不符。
        """
        try:
            return decode(self.data, type_)
        except (msgspec.DecodeError, RecursionError) as exc:
            # msgspec 的错误文案只有期望类型与 JSON 路径，不含数据内容。
            raise PayloadError(
                f"{self.op.name}（t={self.t}）的 d 无法解码为 {type_.__name__}：{exc}"
            ) from exc


class Hello(Model):
    """OpCode 10 Hello 的 `d`。

    Attributes:
        heartbeat_interval: 心跳周期，单位毫秒。
    """

    heartbeat_interval: float

    @property
    def heartbeat_interval_seconds(self) -> float:
        """心跳周期，单位秒。"""
        return self.heartbeat_interval / 1000


class ReadyUser(Model):
    """`Ready.user`：机器人自己。"""

    id: str | None = None
    username: str | None = None
    bot: bool | None = None


class Ready(Model):
    """`READY` 事件的 `d`。只有 `session_id`（Resume 要用）是必需的。"""

    session_id: str
    version: int | None = None
    user: ReadyUser | None = None
    shard: tuple[int, ...] = ()  # 文档出入，见 docs/errata.md；不校验


class _Envelope(Model):
    op: OpCode
    # Raw 不复制、不解析；它不可哈希，所以转成 bytes 放进 GatewayPayload。
    d: msgspec.Raw = msgspec.Raw(b"null")
    s: int | None = None
    t: str | None = None
    id: str | None = None


def decode_payload(frame: str | bytes) -> GatewayPayload:
    """解码一条下行 payload 的信封，`d` 保持原始 JSON。未知字段与未知的 `op` 不会报错。

    Raises:
        PayloadError: 不是合法的 JSON，或缺少 `op`、字段类型不符。
    """
    try:
        envelope = msgspec.json.decode(frame, type=_Envelope)
    except (msgspec.DecodeError, RecursionError) as exc:
        raise PayloadError(f"无法解码网关 payload：{exc}") from exc
    return GatewayPayload(
        op=envelope.op,
        data=bytes(envelope.d),
        s=envelope.s,
        t=envelope.t,
        id=envelope.id,
    )


class _IdentifyData(Model):
    _secret_fields = frozenset({"token"})

    token: str
    intents: int
    shard: tuple[int, int]
    properties: dict[str, str]


class _ResumeData(Model):
    _secret_fields = frozenset({"token"})

    token: str
    session_id: str
    seq: int


def encode_identify(
    access_token: str,
    intents: Intents,
    *,
    shard: tuple[int, int] = (0, 1),
) -> str:
    """编码 OpCode 2 Identify。

    Args:
        access_token: `Client.get_access_token()` 的返回值，前缀在这里加。
        intents: 要订阅的事件类别。
        shard: `(当前分片序号, 分片总数)`。

    Raises:
        ValueError: `access_token` 为空，或 `shard` 不满足 `0 <= 序号 < 总数`。
    """
    _check_token(access_token)
    shard_id, shard_count = shard
    if not 0 <= shard_id < shard_count:
        raise ValueError(f"shard 必须满足 0 <= 序号 < 总数，收到：{shard!r}")
    data = _IdentifyData(
        token=_TOKEN_PREFIX + access_token,
        intents=int(intents),
        shard=(shard_id, shard_count),
        properties=_PROPERTIES,
    )
    return _encode(OpCode.IDENTIFY, data)


def encode_resume(access_token: str, session_id: str, seq: int) -> str:
    """编码 OpCode 6 Resume，网关会补发 `seq` 之后的事件。

    Args:
        access_token: `Client.get_access_token()` 的返回值，前缀在这里加。
        session_id: `Ready.session_id`。
        seq: 最近一条已处理的下行 payload 的 `s`。

    Raises:
        ValueError: `access_token` 或 `session_id` 为空。
    """
    _check_token(access_token)
    if not session_id:
        raise ValueError("session_id 不能为空")
    data = _ResumeData(token=_TOKEN_PREFIX + access_token, session_id=session_id, seq=seq)
    return _encode(OpCode.RESUME, data)


def encode_heartbeat(seq: int | None) -> str:
    """编码 OpCode 1 Heartbeat；`seq` 是最近收到的 `s`，还没收到过时传 `None`。"""
    return _encode(OpCode.HEARTBEAT, seq)


def _check_token(access_token: str) -> None:
    if not access_token:
        raise ValueError("access_token 不能为空")


def _encode(op: OpCode, data: Model | int | None) -> str:
    # 上行只发 op 与 d：文档的上行示例都不带 s、t、id。
    return msgspec.json.encode({"op": op, "d": data}).decode()
