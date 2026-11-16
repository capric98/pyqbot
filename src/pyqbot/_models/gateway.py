"""网关地址（`autogen/api/gateway.get.md`）。"""

from .._model import Model


class Gateway(Model):
    """`GET /gateway` 的响应。"""

    url: str
