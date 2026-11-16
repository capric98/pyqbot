"""客户端配置：凭证、API 地址、超时。"""

from dataclasses import dataclass, field

import httpx2

DEFAULT_BASE_URL = "https://api.bot.qq.com"
DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True, slots=True, kw_only=True)
class Config:
    """一个客户端的只读配置。

    由 `Client` 根据构造参数创建，通过 `Client.config` 读取，一般不需要自己实例化。
    SDK 内部各模块都从这里取凭证、API 地址和超时，不各自保存一份。

    Attributes:
        app_id: 机器人的 AppID。
        app_secret: 机器人的 AppSecret。不会出现在 `repr()` 里。
        base_url: API 地址，不带末尾的 `/`。
        timeout: 单次请求的超时时间，单位秒。
    """

    app_id: str
    app_secret: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        """校验并规范化各字段。

        Raises:
            ValueError: 凭证为空、`base_url` 不是完整的 http(s) 地址，或 `timeout` 不是正数。
        """
        if not self.app_id:
            raise ValueError("app_id 不能为空")
        if not self.app_secret:
            raise ValueError("app_secret 不能为空")
        if not _is_http_url(self.base_url):
            raise ValueError(f"base_url 必须是完整的 http(s) 地址，收到：{self.base_url!r}")
        if not self.timeout > 0:
            raise ValueError(f"timeout 必须大于 0，收到：{self.timeout!r}")
        # 请求层按 base_url + "/path" 拼接，这里统一去掉末尾的斜杠；
        # frozen dataclass 只能绕过自身的 __setattr__ 来写入规范化后的值。
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))


def _is_http_url(value: str) -> bool:
    try:
        url = httpx2.URL(value)
    except httpx2.InvalidURL:
        return False
    return url.scheme in ("http", "https") and bool(url.host)
