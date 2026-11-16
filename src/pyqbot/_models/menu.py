"""单聊的自定义菜单（`autogen/api/v2_menu.get.md`、`autogen/api/v2_menu.put.md`）。

`MenuItem` 等既是 `GET` 的解码结果，也是 `PUT` 的请求体，所以取回的菜单可以改一改再原样设置回去。
数量、长度与链接格式由平台检查（错误码 40030008、40030013 等），本地不检查：平台放宽限制时不用跟着改。
"""

from .._model import Model, OpenStrEnum, RequestModel


class MenuItemType(OpenStrEnum):
    """菜单按钮的类型。二级菜单只能是 `SEND_MESSAGE` 或 `LINK`。

    Attributes:
        SWITCH: 开关，用户切换后发出一条带 `switch_id` 标识的消息。
        SEND_MESSAGE: 点击后把文字填进输入框。
        LINK: 点击后打开链接。
        MENU: 折叠的二级菜单。
    """

    SWITCH = "switch"
    SEND_MESSAGE = "send_message"
    LINK = "link"
    MENU = "menu"


class MenuSwitch(RequestModel):
    """开关按钮的配置。

    Attributes:
        switch_id: 开关的标识：用户打开开关后发出的消息 `ext` 里带 `{switch_id}=1`，关闭后不带。
        default: 初始是否打开。
    """

    switch_id: str
    default: bool | None = None


class SubMenuItem(RequestModel):
    """二级菜单里的一个按钮，一般用 `message_button()`、`link_button()` 构造。

    Attributes:
        name: 按钮文字，最多 14 个字符（约 7 个汉字）。
        type: 按钮类型。
        send_message: 点击后填进输入框的文字，只对 `SEND_MESSAGE` 有效。
        link: 点击后打开的链接，必须是 https，只对 `LINK` 有效。
    """

    name: str | None = None
    type: MenuItemType | None = None
    send_message: str | None = None
    link: str | None = None

    @classmethod
    def message_button(cls, name: str, text: str) -> SubMenuItem:
        """点击后把 `text` 填进输入框。"""
        return cls(name=name, type=MenuItemType.SEND_MESSAGE, send_message=text)

    @classmethod
    def link_button(cls, name: str, url: str) -> SubMenuItem:
        """点击后打开 `url`（必须是 https）。"""
        return cls(name=name, type=MenuItemType.LINK, link=url)


class MenuItem(RequestModel):
    """菜单底栏的一个按钮，一般用 `message_button()`、`link_button()`、`switch_button()`、`submenu()` 构造。

    Attributes:
        name: 按钮文字，最多 10 个字符（一个汉字算 2 个）。
        type: 按钮类型。
        sub_menu_items: 二级菜单，最多 5 个，只对 `MENU` 有效。
        send_message: 点击后填进输入框的文字，只对 `SEND_MESSAGE` 有效。
        link: 点击后打开的链接，必须是 https，只对 `LINK` 有效。
        switch: 开关配置，只对 `SWITCH` 有效。
    """

    name: str | None = None
    type: MenuItemType | None = None
    sub_menu_items: tuple[SubMenuItem, ...] = ()
    send_message: str | None = None
    link: str | None = None
    switch: MenuSwitch | None = None

    @classmethod
    def message_button(cls, name: str, text: str) -> MenuItem:
        """点击后把 `text` 填进输入框。"""
        return cls(name=name, type=MenuItemType.SEND_MESSAGE, send_message=text)

    @classmethod
    def link_button(cls, name: str, url: str) -> MenuItem:
        """点击后打开 `url`（必须是 https）。"""
        return cls(name=name, type=MenuItemType.LINK, link=url)

    @classmethod
    def switch_button(cls, name: str, switch_id: str, *, default: bool = False) -> MenuItem:
        """开关：用户切换后发出一条消息，打开时消息的 `ext` 里带 `{switch_id}=1`；`default` 是初始是否打开。"""
        switch = MenuSwitch(switch_id=switch_id, default=default)
        return cls(name=name, type=MenuItemType.SWITCH, switch=switch)

    @classmethod
    def submenu(cls, name: str, *items: SubMenuItem) -> MenuItem:
        """折叠的二级菜单，点开后显示 `items`（最多 5 个）。"""
        return cls(name=name, type=MenuItemType.MENU, sub_menu_items=items)


class Menu(Model):
    """当前生效的菜单。

    Attributes:
        items: 菜单按钮，从左到右排列。
    """

    items: tuple[MenuItem, ...] = ()


class CurrentMenu(Model):
    """`client.menu.get()` 的结果。

    Attributes:
        version: 菜单的版本号。
        menu: 当前生效的菜单；从未设置过时为 `None`。
    """

    version: int | None = None
    menu: Menu | None = None

    @property
    def items(self) -> tuple[MenuItem, ...]:
        """当前的菜单按钮，从未设置过时为空。"""
        return self.menu.items if self.menu is not None else ()


class MenuVersion(Model):
    """`PUT /v2/menu` 的响应。"""

    version: int | None = None
