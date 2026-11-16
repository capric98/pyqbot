"""异常层级。SDK 的所有失败都以这里的异常抛出，不用返回值表达错误。"""


class QQBotError(Exception):
    """pyqbot 抛出的所有异常的基类。

    Attributes:
        message: 错误描述，只用于人工排查；判断错误类型请用异常类型和 `err_code`。
        err_code: 平台返回的错误码；错误不是平台返回的（如网络故障）时为 `None`。
        trace_id: 平台的链路追踪 ID，找平台协助排查时提供；拿不到时为 `None`。
    """

    def __init__(
        self,
        message: str,
        *,
        err_code: int | None = None,
        trace_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.err_code = err_code
        self.trace_id = trace_id

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
    ) -> None:
        super().__init__(message, err_code=err_code, trace_id=trace_id)
        self.status_code = status_code


class NetworkError(QQBotError):
    """没有拿到平台的响应：连接失败、超时、连接中途断开等。

    底层的 httpx2 异常保留在 `__cause__` 上。
    """


class PayloadError(QQBotError):
    """网关下发的一帧数据无法解码。只影响这一帧，不代表连接不可用。"""
