"""客户端配置：凭证、API 地址、超时、代理。"""

from dataclasses import dataclass, field

import httpx2

DEFAULT_BASE_URL = "https://api.bot.qq.com"
DEFAULT_TIMEOUT = 30.0
_PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})


@dataclass(frozen=True, slots=True, kw_only=True)
class Config:
    """一个客户端的只读配置，由 `Client` 创建，经 `Client.config` 读取。

    Attributes:
        app_id: 机器人的 AppID。
        app_secret: 机器人的 AppSecret，不出现在 `repr()` 里。
        base_url: API 地址，不带末尾的 `/`。
        timeout: 单次请求的超时时间，单位秒。
        proxy: 代理地址，可能带账号密码，不出现在 `repr()` 里；不用代理时为 `None`。
    """

    app_id: str
    app_secret: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT
    proxy: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.app_id:
            raise ValueError("app_id 不能为空")
        if not self.app_secret:
            raise ValueError("app_secret 不能为空")
        if not _is_http_url(self.base_url):
            raise ValueError(f"base_url 必须是完整的 http(s) 地址，收到：{self.base_url!r}")
        if not self.timeout > 0:
            raise ValueError(f"timeout 必须大于 0，收到：{self.timeout!r}")
        if self.proxy is not None and not _is_proxy_url(self.proxy):
            # 不回显地址：里面可能有密码。
            raise ValueError("proxy 必须是完整的 http、https、socks5 或 socks5h 地址")
        # frozen dataclass 只能这样写入规范化后的值。
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))


def _is_http_url(value: str) -> bool:
    try:
        url = httpx2.URL(value)
    except httpx2.InvalidURL:
        return False
    return url.scheme in ("http", "https") and bool(url.host)


def _is_proxy_url(value: str) -> bool:
    try:
        url = httpx2.URL(value)
    except httpx2.InvalidURL:
        return False
    return url.scheme in _PROXY_SCHEMES and bool(url.host)


def proxy_secrets(proxy: str | None) -> tuple[str, ...]:
    """代理地址里要脱敏的部分：账号与密码（转义前后两种写法）；只有账号时它多半是令牌，也算。"""
    if proxy is None:
        return ()
    url = httpx2.URL(proxy)
    userinfo = url.userinfo.decode("ascii")
    raw_username, _, raw_password = userinfo.partition(":")
    if raw_password:
        return (userinfo, raw_password, url.password)
    return (raw_username, url.username)
