"""异常层级。平台与网络的失败都以这里的异常抛出，不用返回值表达错误。"""


class QQBotError(Exception):
    """平台与网络失败的统一基类。

    用法错误（参数不合法、关闭后再用）抛内置的 `ValueError` / `RuntimeError`，读不了本地文件抛 `OSError`。

    Attributes:
        message: 错误描述，只用于人工排查；判断错误类型请用异常类型和 `err_code`。
        err_code: 平台返回的错误码；错误不是平台返回的（如网络故障）时为 `None`。
        trace_id: 平台的链路追踪 ID，找平台协助排查时提供；拿不到时为 `None`。
        outcome_unknown: 请求可能已经生效（如消息其实发出去了），只是没能确认：请求发出后超时或断开、
            HTTP 5xx、HTTP 2xx 却没有错误码也确认不了成功（如响应无法识别）。为 `False` 时请求没有生效
            （连不上、平台带错误码或以 4xx 拒绝、获取 access_token 失败等），`PartialFailureError`、
            `AuditPendingError` 除外，见各自的说明。
    """

    def __init__(
        self,
        message: str,
        *,
        err_code: int | None = None,
        trace_id: str | None = None,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.err_code = err_code
        self.trace_id = trace_id
        self.outcome_unknown = outcome_unknown

    def __str__(self) -> str:
        details = [
            f"{name}={value}"
            for name, value in (("err_code", self.err_code), ("trace_id", self.trace_id))
            if value is not None
        ]
        return f"{self.message}（{', '.join(details)}）" if details else self.message


class APIError(QQBotError):
    """平台收到了请求，但返回了失败。

    Attributes:
        status_code: 响应的 HTTP 状态码。
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        err_code: int | None = None,
        trace_id: str | None = None,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(
            message, err_code=err_code, trace_id=trace_id, outcome_unknown=outcome_unknown
        )
        self.status_code = status_code


class PartialFailureError(APIError):
    """批量操作里有一部分对象失败了，其余已经生效；文案说明是哪一步失败。

    Attributes:
        failed_ids: 失败的对象（如 `member_openid`）。平台给出失败清单时顺序同它，只给成功清单时按请求的顺序。
    """

    def __init__(
        self,
        message: str,
        *,
        failed_ids: tuple[str, ...],
        status_code: int,
        err_code: int | None = None,
        trace_id: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, err_code=err_code, trace_id=trace_id)
        self._failed_ids = failed_ids

    @property
    def failed_ids(self) -> tuple[str, ...]:
        return self._failed_ids


class AuditPendingError(APIError):
    """消息已被平台受理，但要等人工审核后才会发出，所以这次调用拿不到发出的消息。

    频道的主动消息、被动回复都可能这样（`err_code` 为 304023、304024，HTTP 状态码多为 202）。
    审核结果由 `MESSAGE_AUDIT_PASS` / `MESSAGE_AUDIT_REJECT` 事件推送，用 `audit_id` 对应。

    Attributes:
        audit_id: 审核 ID；平台没有给出时为 `None`。
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        err_code: int | None = None,
        trace_id: str | None = None,
        audit_id: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, err_code=err_code, trace_id=trace_id)
        self.audit_id = audit_id


class NetworkError(QQBotError):
    """没有拿到平台的响应：连接失败、超时、连接中途断开等。

    底层异常能安全保留（不含凭证）时放在 `__cause__` 上，否则丢弃。
    """


class PayloadError(QQBotError):
    """网关下发的一帧数据无法解码。内部异常，不导出：SDK 接住后丢弃这一帧，调用方见不到。"""


class GatewayError(QQBotError):
    """网关连接被关闭且无法恢复，重连也不会成功。

    网关以关闭码断开时，`err_code` 是该关闭码，含义见官方文档的 WebSocket 错误码；
    其它原因（如连续多次会话无效）时为 `None`。
    """
