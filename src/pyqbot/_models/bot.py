"""机器人自身的信息（`autogen/api/users_me.get.md`）与分享链接（`autogen/api/v2_generate_url_link.post.md`）。"""

from .._model import Model


class BotInfo(Model):
    """机器人自身的信息，由 `client.get_me()` 返回。

    Attributes:
        id: 机器人的用户 ID。
        username: 机器人的名字。
        avatar: 头像地址。
        bot: 是否为机器人。
        union_openid: 跨应用统一的 openid，需特殊申请才会返回。
        union_user_account: 跨应用统一的账号，需特殊申请才会返回。
        share_url: 机器人的分享链接（只在官方示例里出现，见 `docs/errata.md`）。
        welcome_msg: 欢迎语（同上）。
    """

    id: str
    username: str | None = None
    avatar: str | None = None
    bot: bool | None = None
    union_openid: str | None = None
    union_user_account: str | None = None
    share_url: str | None = None
    welcome_msg: str | None = None


class _ShareLink(Model):
    url: str


class ShareLinkResponse(Model):
    """`POST /v2/generate_url_link` 的响应。"""

    data: _ShareLink
