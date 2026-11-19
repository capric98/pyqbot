"""凭证脱敏：凭证（`app_secret`、access_token）进入异常文案、日志之前都经过这里。"""

import logging
import traceback

REDACTED = "***"


def redact(text: str, *secrets: str | None) -> str:
    """把 `text` 里出现的每个凭证替换成 `***`，空值与 `None` 跳过。"""
    # 先替换长的：一个凭证恰好包含另一个时，避免只替换掉一部分。
    for secret in sorted(filter(None, secrets), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return text


def redact_optional(text: str | None, *secrets: str | None) -> str | None:
    """同 `redact()`，`text` 为 `None` 时返回 `None`；用于 `trace_id` 这类可能缺失的外部文本。"""
    return text and redact(text, *secrets)


def safe_cause[E: BaseException](exc: E, *secrets: str | None) -> E | None:
    """给 `raise ... from` 用：`exc` 的异常链里出现凭证时返回 `None`（丢掉整条链），否则返回 `exc`。"""
    # traceback 会连同 __cause__ / __context__ 一起打印，光给新异常的文案脱敏不够。
    shown = "".join(traceback.format_exception(exc))
    return exc if redact(shown, *secrets) == shown else None


class _SocksAuthFilter(logging.Filter):
    """httpcore2 的 DEBUG 日志把 SOCKS 代理的账号密码原样打成 `auth=(b'…', b'…')`：从 `auth=` 起截掉。"""

    def filter(self, record: logging.LogRecord) -> bool:
        head, found, _ = record.getMessage().partition("auth=")
        if found:
            record.msg, record.args = f"{head}auth={REDACTED}", None
        return True


def hide_socks_auth() -> None:
    """给 httpcore2 的 SOCKS 日志挂上过滤器，进程内只挂一次。"""
    logger = logging.getLogger("httpcore2.socks")
    if not any(isinstance(item, _SocksAuthFilter) for item in logger.filters):
        logger.addFilter(_SocksAuthFilter())
