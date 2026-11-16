"""事件订阅位 Intents（`dev-prepare/event-emit/payload.md`「事件订阅 Intents」）。"""

import enum


class Intents(enum.IntFlag):
    """连接网关时订阅的事件类别，多个类别用 `|` 组合。

    除 `GUILDS`、`GUILD_MEMBERS`、`PUBLIC_GUILD_MESSAGES` 外都要先在开放平台申请权限，
    订阅了没有权限的类别，网关会直接关闭连接，所以这里不提供「全部」的组合。
    未列出的位（上游新增的类别）会原样保留，如 `Intents(1 << 31)`。

    Attributes:
        GUILDS: 频道与子频道的创建、更新、删除。
        GUILD_MEMBERS: 频道成员的加入、更新、移除。
        GUILD_MESSAGES: 频道内的全部消息及其撤回，仅私域机器人可用。
        GUILD_MESSAGE_REACTIONS: 频道消息的表情表态。
        DIRECT_MESSAGE: 频道私信及其撤回。
        GROUP_MEMBER_EVENT: 群成员的加入、退出与入群申请。
        GROUP_AND_C2C_EVENT: 单聊与群聊：消息、好友增删、机器人进出群、主动消息开关等。
        INTERACTION: 互动事件，如按钮回调。
        MESSAGE_AUDIT: 消息审核结果。
        FORUMS_EVENT: 论坛的主题、帖子、回复，仅私域机器人可用。
        AUDIO_ACTION: 音频播放与上下麦。
        PUBLIC_GUILD_MESSAGES: 频道内 @机器人 的消息及频道消息删除（公域）。

    Example:
        ```python
        intents = pyqbot.Intents.GROUP_AND_C2C_EVENT | pyqbot.Intents.INTERACTION
        ```
    """

    GUILDS = 1 << 0
    GUILD_MEMBERS = 1 << 1
    GUILD_MESSAGES = 1 << 9
    GUILD_MESSAGE_REACTIONS = 1 << 10
    DIRECT_MESSAGE = 1 << 12
    GROUP_MEMBER_EVENT = 1 << 24
    GROUP_AND_C2C_EVENT = 1 << 25
    INTERACTION = 1 << 26
    MESSAGE_AUDIT = 1 << 27
    FORUMS_EVENT = 1 << 28
    AUDIO_ACTION = 1 << 29
    PUBLIC_GUILD_MESSAGES = 1 << 30
