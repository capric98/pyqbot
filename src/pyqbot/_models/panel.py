"""指令面板（`autogen/api/v2_panels*.md`）。

`PanelItem` 既是取回的面板元素，也是创建、修改时的请求体，所以取回的面板可以改一改再原样设置回去。
数量与长度由平台检查（错误码 40030013 等），本地不检查，理由同 `menu.py`。
"""

from datetime import datetime

from .._model import Model, OpenStrEnum, RequestModel


class PanelScope(OpenStrEnum):
    """面板的生效场景。"""

    C2C = "c2c"
    GROUP = "group"
    CHANNEL = "channel"  # 文字子频道
    DM = "dm"  # 频道私信


class PanelTargetType(OpenStrEnum):
    """面板的作用范围。

    Attributes:
        ALL: 对该场景的所有用户或群生效。
        SPECIFIC: 只对关联的用户（单聊）或群（群聊）生效，只有 `C2C`、`GROUP` 支持。
    """

    ALL = "all"
    SPECIFIC = "specific"


class PanelItemType(OpenStrEnum):
    """面板元素的类型。

    Attributes:
        COMMAND: 指令：点击后把 `name` 填进输入框。
        LINK: 链接：点击后打开 `link`。
    """

    COMMAND = "command"
    LINK = "link"


class PanelTargetOp(OpenStrEnum):
    """`PUT /v2/panels/{panel_id}/target` 的 `op`。"""

    ADD = "add"
    DEL = "del"


class PanelItem(RequestModel):
    """面板里的一个元素，一般用 `command_button()`、`link_button()` 构造。

    Attributes:
        name: 显示的名字，最多 14 个字符（约 7 个汉字）；指令元素点击后填进输入框的就是它。
        desc: 说明文字，最多 30 个字符（约 15 个汉字）。
        type: 元素类型。
        only_admin: 是否只有频道或群的管理员可以点击。
        link: 点击后打开的链接，只对 `LINK` 有效。
    """

    name: str | None = None
    desc: str | None = None
    type: PanelItemType | None = None
    only_admin: bool | None = None
    link: str | None = None

    @classmethod
    def command_button(
        cls, name: str, *, desc: str | None = None, only_admin: bool = False
    ) -> PanelItem:
        """指令：点击后把 `name` 填进输入框。"""
        return cls(name=name, desc=desc, type=PanelItemType.COMMAND, only_admin=only_admin or None)

    @classmethod
    def link_button(
        cls, name: str, url: str, *, desc: str | None = None, only_admin: bool = False
    ) -> PanelItem:
        """链接：点击后打开 `url`。"""
        return cls(
            name=name, desc=desc, type=PanelItemType.LINK, only_admin=only_admin or None, link=url
        )


class Panel(Model):
    """面板的内容。

    Attributes:
        items: 面板元素，最多 20 个。
        remark: 备注，只给开发者看。
        version: 版本号。
    """

    items: tuple[PanelItem, ...] = ()
    remark: str | None = None
    version: int | None = None


class PanelRecord(Model):
    """一个指令面板，由 `client.panels.iter_panels()` 产出。

    Attributes:
        panel_id: 面板 ID，修改、删除时要用。
        scope: 生效场景。
        target_type: 作用范围。
        panel: 面板的内容。
        created_at: 创建时间。
        updated_at: 更新时间。
        version: 版本号。
    """

    panel_id: str
    scope: PanelScope | None = None
    target_type: PanelTargetType | None = None
    panel: Panel | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int | None = None

    @property
    def items(self) -> tuple[PanelItem, ...]:
        """面板元素，即 `panel.items`。"""
        return self.panel.items if self.panel is not None else ()


class PanelDetail(PanelRecord):
    """指令面板的详情，由 `client.panels.get()` 返回；比 `PanelRecord` 多了关联对象。

    Attributes:
        user_openids: 关联的用户，只有单聊的 `SPECIFIC` 面板有，最多返回 1000 个。
        group_openids: 关联的群，只有群聊的 `SPECIFIC` 面板有，最多返回 1000 个。
    """

    user_openids: tuple[str, ...] = ()
    group_openids: tuple[str, ...] = ()


class PanelPage(Model):
    """`GET /v2/panels` 的一页。"""

    records: tuple[PanelRecord, ...] = ()
    next_cursor: str | None = None
    is_end: bool | None = None


class PanelCreated(Model):
    """`POST /v2/panels` 的响应。"""

    panel_id: str


class PanelVersion(Model):
    """`PUT /v2/panels/{panel_id}` 的响应。"""

    version: int | None = None
