"""单聊的自定义菜单接口。"""

from collections.abc import Iterable

from .._http import HTTP
from .._models.menu import CurrentMenu, MenuItem, MenuVersion


class CustomMenu:
    """单聊窗口底部的自定义菜单，经 `client.menu` 使用。菜单是机器人全局的，对所有用户生效。"""

    def __init__(self, http: HTTP) -> None:
        self._http = http

    async def get(self) -> CurrentMenu:
        """取当前生效的菜单。

        对应官方接口 `GET /v2/menu`（限频 30 次/分钟）。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            RuntimeError: 客户端已关闭。
        """
        return await self._http.request("GET", "/v2/menu", type_=CurrentMenu)

    async def set(self, items: Iterable[MenuItem]) -> int | None:
        """用 `items` 整体覆盖菜单，立即对所有用户生效；返回新的版本号（平台没给时为 `None`）。

        数量、名字长度与链接格式由平台检查：一级最多 10 个，二级最多 5 个，链接必须是 https。

        对应官方接口 `PUT /v2/menu`（限频 5 次/分钟）。

        Args:
            items: 菜单按钮，从左到右排列。

        Raises:
            APIError: 平台拒绝，如超出数量（`err_code` 40030013）、链接不是 https（40030008）、
                内容有安全风险（40030020）。
            NetworkError: 没有拿到平台的响应。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            await client.menu.set([
                pyqbot.MenuItem.message_button("帮助", "/help"),
                pyqbot.MenuItem.submenu(
                    "更多",
                    pyqbot.SubMenuItem.link_button("官网", "https://example.com"),
                ),
            ])
            ```
        """
        body = {"menu": {"items": list(items)}}
        result = await self._http.request("PUT", "/v2/menu", type_=MenuVersion, json=body)
        return result.version
