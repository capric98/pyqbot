"""发消息时由调用方构造的内容：Markdown、键盘、图文卡片与富媒体，以及频道的 Embed 与 Ark。

字段与 `autogen/api/v2_users_user_openid_messages.post.md` 的请求体一一对应（群聊相同），
Embed 与 Ark 见 `server-inter/message/template/model.md`；各页之间的出入见 `docs/errata.md`。
"""

from collections.abc import Iterable, Mapping

from .._model import Model, OpenIntEnum, RequestModel


class MarkdownParam(RequestModel):
    """Markdown 模板的一个变量：`values` 依次填入模板里名为 `key` 的变量。"""

    key: str
    values: tuple[str, ...] = ()


class Markdown(RequestModel):
    """Markdown 消息的内容；只有正文时直接给 `send_message(markdown="...")` 传字符串即可。

    `content`（自定义 Markdown，所有机器人可用）与 `custom_template_id`（模板，官方已标为弃用，
    只为已申请过模板的机器人保留）二选一，模板用 `Markdown.from_template()` 构造更方便。
    平台模板的整数 `template_id` 已弃用，不支持。语法见官方文档 `server-inter/message/type/markdown.md`。
    形如 `[文字](目标)` 而目标不是 URL 的文字，即使转义了方括号也会被判违规（40034006），圆括号也要转义。
    图片写 `![说明 #宽px #高px](地址)`：宽高必须写，并按原图的比例，不写时不显示图片，写错会变形。
    平台抓不到图时消息照发，客户端显示「图片加载失败」。

    Attributes:
        content: Markdown 正文。
        custom_template_id: 模板 ID。
        params: 模板变量。
        force_verify_image_resource: 为 `True` 时，正文里的图片转存失败则整条消息发送失败
            （`err_code` 40034141）；流式消息没有这个开关。

    Raises:
        ValueError: `content` 与 `custom_template_id` 都给了或都没给，或没有模板却给了 `params`。

    Example:
        ```python
        markdown = pyqbot.Markdown(
            content="![图 #200px #100px](https://...)", force_verify_image_resource=True
        )
        await client.users.send_message(user_openid, markdown=markdown)
        ```
    """

    content: str | None = None
    custom_template_id: str | None = None
    params: tuple[MarkdownParam, ...] = ()
    force_verify_image_resource: bool | None = None

    def __post_init__(self) -> None:
        if (self.content is None) == (self.custom_template_id is None):
            raise ValueError("Markdown 的 content 与 custom_template_id 必须二选一")
        if self.params and self.custom_template_id is None:
            raise ValueError("Markdown 的 params 只能与 custom_template_id 一起使用")

    @classmethod
    def from_template(
        cls,
        template_id: str,
        *,
        params: Mapping[str, str | Iterable[str]] | None = None,
    ) -> Markdown:
        """用模板构造，`params` 的值是单个字符串或字符串序列。

        Example:
            ```python
            pyqbot.Markdown.from_template("101993071_1658748972", params={"title": "标题"})
            ```
        """
        return cls(
            custom_template_id=template_id,
            params=tuple(
                MarkdownParam(key=key, values=(value,) if isinstance(value, str) else tuple(value))
                for key, value in (params or {}).items()
            ),
        )


class ButtonStyle(OpenIntEnum):
    """按钮样式（`render_data.style`）。"""

    GRAY_OUTLINE = 0
    BLUE_OUTLINE = 1
    RED_TEXT = 3  # 白色背景、红色文字
    BLUE_FILLED = 4  # 蓝色背景、白色文字


class ButtonActionType(OpenIntEnum):
    """点击按钮的行为（`action.type`）。

    Attributes:
        LINK: 跳转，`data` 是 http 链接或小程序地址。
        CALLBACK: 回调，平台推送 `INTERACTION_CREATE` 事件，`data` 随事件带给机器人。
        COMMAND: 指令，在输入框插入 `@机器人 data`。
    """

    LINK = 0
    CALLBACK = 1
    COMMAND = 2


class ButtonPermissionType(OpenIntEnum):
    """谁可以点击按钮（`action.permission.type`）。

    Attributes:
        SPECIFIED_USERS: 只有 `specify_user_ids` 里的用户。
        ADMINS: 只有管理员。
        EVERYONE: 所有人。
        SPECIFIED_ROLES: 只有 `specify_role_ids` 里的身份组，只有频道可用。
    """

    SPECIFIED_USERS = 0
    ADMINS = 1
    EVERYONE = 2
    SPECIFIED_ROLES = 3


class ButtonRenderData(RequestModel):
    """按钮的外观。

    Attributes:
        label: 按钮文字。文档写最多 10 个字符，实测 20 个字也被接受。
        visited_label: 点击后的文字。同组的按钮（`Button.group_id`）点过之后一直显示它；不分组的只是临时显示，
            下一条消息到来后变回 `label`。
        style: 样式。
    """

    label: str
    visited_label: str | None = None
    style: ButtonStyle | None = None


class ButtonPermission(RequestModel):
    """谁可以点击按钮，常用的写法见各个工厂方法。

    Attributes:
        type: 权限类型。
        specify_user_ids: 可以点击的用户 openid（单聊为 `user_openid`，群聊为 `member_openid`）。
        specify_role_ids: 可以点击的身份组 ID，只有频道可用。
    """

    type: ButtonPermissionType
    specify_user_ids: tuple[str, ...] = ()
    specify_role_ids: tuple[str, ...] = ()

    @classmethod
    def everyone(cls) -> ButtonPermission:
        """所有人可以点击。"""
        return cls(type=ButtonPermissionType.EVERYONE)

    @classmethod
    def admins(cls) -> ButtonPermission:
        """只有管理员可以点击。"""
        return cls(type=ButtonPermissionType.ADMINS)

    @classmethod
    def users(cls, *openids: str) -> ButtonPermission:
        """只有这些用户可以点击。"""
        return cls(type=ButtonPermissionType.SPECIFIED_USERS, specify_user_ids=openids)

    @classmethod
    def roles(cls, *role_ids: str) -> ButtonPermission:
        """只有这些身份组可以点击，只有频道可用。"""
        return cls(type=ButtonPermissionType.SPECIFIED_ROLES, specify_role_ids=role_ids)


class ButtonModal(RequestModel):
    """点击后的二次确认。文字超过下面的长度时整条消息被拒（`err_code` 40011021）。

    Attributes:
        content: 提示文字，最多 40 个字符，不能有链接。
        confirm_text: 确认按钮的文字，最多 4 个字符，默认「确认」。
        cancel_text: 取消按钮的文字，最多 4 个字符，默认「取消」。
    """

    content: str
    confirm_text: str | None = None
    cancel_text: str | None = None


class ButtonAction(RequestModel):
    """点击按钮的行为。

    Attributes:
        type: 行为类型。
        data: 跳转的链接、回调数据或指令文字。
        permission: 谁可以点击。
        unsupport_tips: 客户端版本过低时的提示文字。
        enter: 只对指令按钮有效：点击后直接发送 `data`。官方说只有单聊可用。
        reply: 只对指令按钮有效：发送的指令是否引用这条消息。
        anchor: 只对指令按钮有效：为 1 时点击后唤起图片选择器（只有手机端单聊），会忽略 `enter`。
        modal: 点击后的二次确认。
    """

    type: ButtonActionType
    data: str
    permission: ButtonPermission | None = None
    unsupport_tips: str | None = None
    enter: bool | None = None
    reply: bool | None = None
    anchor: int | None = None
    modal: ButtonModal | None = None


class Button(RequestModel):
    """消息键盘上的一个按钮，一般用 `link()`、`callback()`、`command()` 构造。

    Attributes:
        id: 按钮 ID，在同一个键盘内唯一；回调事件里会带上它。用 `group_id` 时必须填。
        render_data: 外观。
        action: 点击后的行为。
        group_id: 分组：同组的一个回调按钮被点击后，其余按钮变灰不可点，这个状态一直保持。同组的按钮必须各带
            一个 `id`，否则整条消息被拒（`err_code` 40011021）。只对回调按钮有效。
    """

    render_data: ButtonRenderData
    action: ButtonAction
    id: str | None = None
    group_id: str | None = None

    @classmethod
    def link(
        cls,
        label: str,
        url: str,
        *,
        id: str | None = None,
        style: ButtonStyle = ButtonStyle.GRAY_OUTLINE,
        permission: ButtonPermission | None = None,
        unsupport_tips: str | None = None,
    ) -> Button:
        """跳转按钮：点击后打开 `url`。

        `url` 用 http(s) 链接；App 的自定义 scheme（如 `app://...`）会让整条消息被拒（40034028）。
        `permission=None` 表示所有人可点；点击后按钮文字不变。
        """
        return cls._make(
            label,
            ButtonAction(
                type=ButtonActionType.LINK,
                data=url,
                permission=permission or ButtonPermission.everyone(),
                unsupport_tips=unsupport_tips,
            ),
            id=id,
            style=style,
            visited_label=None,
        )

    @classmethod
    def callback(
        cls,
        label: str,
        data: str,
        *,
        id: str | None = None,
        visited_label: str | None = None,
        style: ButtonStyle = ButtonStyle.GRAY_OUTLINE,
        permission: ButtonPermission | None = None,
        group_id: str | None = None,
        modal: ButtonModal | None = None,
        unsupport_tips: str | None = None,
    ) -> Button:
        """回调按钮：点击后平台推送 `INTERACTION_CREATE` 事件，带上 `data` 与 `id`。

        `permission=None` 表示所有人可点；`visited_label=None` 表示点击后文字不变；
        `group_id` 相同的回调按钮被点了一个，其余变灰不可点，同组的按钮要各传一个 `id`（见 `Button`）。
        """
        return cls._make(
            label,
            ButtonAction(
                type=ButtonActionType.CALLBACK,
                data=data,
                permission=permission or ButtonPermission.everyone(),
                modal=modal,
                unsupport_tips=unsupport_tips,
            ),
            id=id,
            style=style,
            visited_label=visited_label,
            group_id=group_id,
        )

    @classmethod
    def command(
        cls,
        label: str,
        data: str,
        *,
        enter: bool = False,
        reply: bool = False,
        id: str | None = None,
        visited_label: str | None = None,
        style: ButtonStyle = ButtonStyle.GRAY_OUTLINE,
        permission: ButtonPermission | None = None,
        modal: ButtonModal | None = None,
        unsupport_tips: str | None = None,
    ) -> Button:
        """指令按钮：点击后把指令填进输入框，群里是 `@机器人 data`，单聊里就是 `data`。

        `enter=True` 时点击后直接发送，不用用户再按发送（只有单聊可用，群里仍只填进输入框）；
        `reply=True` 时发送的指令引用这条消息（单聊实测收到的消息里没有 `ref_msg_idx`）。`permission=None` 表示所有人可点；
        `visited_label=None` 表示点击后文字不变。
        """
        return cls._make(
            label,
            ButtonAction(
                type=ButtonActionType.COMMAND,
                data=data,
                permission=permission or ButtonPermission.everyone(),
                enter=enter or None,
                reply=reply or None,
                modal=modal,
                unsupport_tips=unsupport_tips,
            ),
            id=id,
            style=style,
            visited_label=visited_label,
        )

    @classmethod
    def _make(
        cls,
        label: str,
        action: ButtonAction,
        *,
        id: str | None,
        style: ButtonStyle,
        visited_label: str | None,
        group_id: str | None = None,
    ) -> Button:
        # visited_label 在 msg-btn.md 里是必填，接口页说不传则不变：总是填上（见 docs/errata.md）。
        render = ButtonRenderData(label=label, visited_label=visited_label or label, style=style)
        return cls(render_data=render, action=action, id=id, group_id=group_id)


class KeyboardRow(RequestModel):
    """键盘的一行按钮，从左到右排列。"""

    buttons: tuple[Button, ...] = ()


class KeyboardContent(RequestModel):
    """自定义键盘的布局。"""

    rows: tuple[KeyboardRow, ...] = ()


class Keyboard(RequestModel):
    """消息下方的按钮，只能随 Markdown 消息发送。

    `id`（申请过的键盘模板）与 `content`（自定义按钮）二选一；自定义按钮用 `Keyboard.from_rows()` 构造更方便。
    官方说自定义按钮最多 5 行、每行最多 5 个，超出时由平台拒绝。

    Raises:
        ValueError: `id` 与 `content` 都给了或都没给。

    Example:
        ```python
        keyboard = pyqbot.Keyboard.from_rows(
            [pyqbot.Button.callback("赞", "like"), pyqbot.Button.callback("踩", "dislike")],
            [pyqbot.Button.link("主页", "https://example.com")],
        )
        await client.users.send_message(user_openid, markdown="**投票**", keyboard=keyboard)
        ```
    """

    id: str | None = None
    content: KeyboardContent | None = None

    def __post_init__(self) -> None:
        if (self.id is None) == (self.content is None):
            raise ValueError("Keyboard 的 id 与 content 必须二选一")

    @classmethod
    def from_rows(cls, *rows: Iterable[Button]) -> Keyboard:
        """自定义按钮，每个参数是一行。"""
        return cls(
            content=KeyboardContent(rows=tuple(KeyboardRow(buttons=tuple(row)) for row in rows))
        )


class Card(RequestModel):
    """图文卡片（官方的 `card.type` 为 `tuwen`）。长度限制由平台检查。

    Attributes:
        title: 标题，1～50 个字符。
        description: 描述，1～200 个字符。
        url: 点击后打开的链接，必须是 https，最长 1024 个字符。
        pic_url: 图片链接，必须是 https，最长 1024 个字符。
    """

    title: str
    description: str
    url: str
    pic_url: str


class Media(Model):
    """上传好的富媒体文件，发送时传给 `send_message(media=...)`。

    一般由上传接口返回；手里已有 `file_info` 时也可以直接构造 `Media(file_info=...)`。
    单聊与群聊上传的文件不互通。

    Attributes:
        file_info: 平台给出的文件信息，原样透传。
        file_uuid: 文件 ID。
        ttl: `file_info` 的有效期，单位秒；0 表示长期有效。
        id: 上传时直接发送（`srv_send_msg`）的那条消息的 ID。
        raw_url: 文件的下载地址，有效期与 `ttl` 相同；只有部分上传方式会返回。
    """

    file_info: str
    file_uuid: str | None = None
    ttl: int | None = None
    id: str | None = None
    raw_url: str | None = None


# ---- 频道消息的内容（`server-inter/channel/message/send.md`）----


class EmbedThumbnail(RequestModel):
    """Embed 的缩略图。"""

    url: str


class EmbedField(RequestModel):
    """Embed 的一行文字。"""

    name: str


class Embed(RequestModel):
    """Embed 消息，只能发到子频道与频道私信；一般用 `Embed.from_lines()` 构造。

    Attributes:
        title: 标题。
        prompt: 消息弹窗（通知栏）里显示的内容。
        thumbnail: 缩略图。
        fields: 正文，每项一行。

    Example:
        ```python
        embed = pyqbot.Embed.from_lines("标题", "当前等级：黄金", "之前等级：白银", prompt="消息通知")
        await client.channels.send_message(channel_id, embed=embed)
        ```
    """

    title: str
    prompt: str | None = None
    thumbnail: EmbedThumbnail | None = None
    fields: tuple[EmbedField, ...] = ()

    @classmethod
    def from_lines(
        cls,
        title: str,
        *lines: str,
        prompt: str | None = None,
        thumbnail_url: str | None = None,
    ) -> Embed:
        """用标题与若干行文字构造。"""
        thumbnail = None if thumbnail_url is None else EmbedThumbnail(url=thumbnail_url)
        fields = tuple(EmbedField(name=line) for line in lines)
        return cls(title=title, prompt=prompt, thumbnail=thumbnail, fields=fields)


class ArkObjKv(RequestModel):
    """Ark 数组变量里一个元素的一项。"""

    key: str
    value: str


class ArkObj(RequestModel):
    """Ark 数组变量的一个元素。"""

    obj_kv: tuple[ArkObjKv, ...] = ()


class ArkKv(RequestModel):
    """Ark 模板的一个变量：字符串变量填 `value`，数组变量填 `obj`。"""

    key: str
    value: str | None = None
    obj: tuple[ArkObj, ...] = ()


class Ark(RequestModel):
    """Ark（结构化卡片）消息，需要向平台申请权限；一般用 `Ark.from_template()` 构造。

    模板与各自的变量见官方文档 `server-inter/message/type/ark.md`。

    Attributes:
        template_id: 模板 ID，如 23、24、37。
        kv: 模板变量。
    """

    template_id: int
    kv: tuple[ArkKv, ...] = ()

    @classmethod
    def from_template(
        cls,
        template_id: int,
        kv: Mapping[str, str | Iterable[Mapping[str, str]]],
    ) -> Ark:
        """用模板 ID 与变量构造：字符串是普通变量，字典序列是数组变量（每个字典是一个元素）。

        Example:
            ```python
            ark = pyqbot.Ark.from_template(
                23,
                {
                    "#DESC#": "描述",
                    "#PROMPT#": "提示",
                    "#LIST#": [{"desc": "已评审", "link": "https://qun.qq.com"}, {"desc": "请关注"}],
                },
            )
            ```
        """
        return cls(
            template_id=template_id,
            kv=tuple(
                ArkKv(key=key, value=value)
                if isinstance(value, str)
                else ArkKv(
                    key=key,
                    obj=tuple(
                        ArkObj(obj_kv=tuple(ArkObjKv(key=k, value=v) for k, v in item.items()))
                        for item in value
                    ),
                )
                for key, value in kv.items()
            ),
        )
