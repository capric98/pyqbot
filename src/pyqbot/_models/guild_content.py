"""频道的内容：精华消息、频道公告与日程。

官方文档：`server-inter/channel/content/pins/model.md`、`announces/model.md`、`schedule/model.md`。
"""

from datetime import UTC, datetime, timedelta

from .._model import Model, OpenIntEnum, OpenStrEnum, RequestModel
from .guild import GuildMember


class PinnedMessages(Model):
    """子频道的精华消息。

    Attributes:
        guild_id: 频道 ID。
        channel_id: 子频道 ID。
        message_ids: 精华消息的 ID；添加精华消息后是添加之后的全部。
    """

    guild_id: str | None = None
    channel_id: str | None = None
    message_ids: tuple[str, ...] = ()


class AnnouncementType(OpenIntEnum):
    """频道公告的类别（`announces_type`）。

    Attributes:
        MEMBER: 成员公告。
        WELCOME: 欢迎公告。
    """

    MEMBER = 0
    WELCOME = 1


class RecommendChannel(RequestModel):
    """频道公告里推荐的子频道。

    Attributes:
        channel_id: 子频道 ID；子频道须对全体成员可见。
        introduce: 推荐语。
    """

    channel_id: str
    introduce: str = ""


class Announcement(Model):
    """频道公告：一条消息，或一组推荐子频道（两种互相顶替）。

    Attributes:
        guild_id: 频道 ID。
        channel_id: 消息所在的子频道 ID。
        message_id: 设为公告的消息 ID；推荐子频道类型的公告为空串。
        announces_type: 公告类别。
        recommend_channels: 推荐的子频道。
    """

    guild_id: str | None = None
    channel_id: str | None = None
    message_id: str = ""
    announces_type: AnnouncementType | None = None
    recommend_channels: tuple[RecommendChannel, ...] = ()


class RemindType(OpenStrEnum):
    """日程的提醒方式（`remind_type`，接口里是字符串）。

    Attributes:
        NONE: 不提醒。
        AT_START: 开始时提醒。
        BEFORE_5_MINUTES: 开始前 5 分钟提醒。
        BEFORE_15_MINUTES: 开始前 15 分钟提醒。
        BEFORE_30_MINUTES: 开始前 30 分钟提醒。
        BEFORE_60_MINUTES: 开始前 60 分钟提醒。
    """

    NONE = "0"
    AT_START = "1"
    BEFORE_5_MINUTES = "2"
    BEFORE_15_MINUTES = "3"
    BEFORE_30_MINUTES = "4"
    BEFORE_60_MINUTES = "5"


class Schedule(Model):
    """日程子频道里的一个日程。

    时间字段照接口是毫秒时间戳的字符串，要时间对象时用 `start`、`end` 属性。

    Attributes:
        id: 日程 ID。
        name: 名称。
        description: 描述，没有时为空串。
        start_timestamp: 开始时间，Unix 毫秒的字符串。
        end_timestamp: 结束时间，Unix 毫秒的字符串。
        creator: 创建者。
        jump_channel_id: 日程开始时跳转到的子频道 ID，`"0"` 表示不跳转。
        remind_type: 提醒方式。
    """

    id: str
    name: str = ""
    description: str = ""
    start_timestamp: str | None = None
    end_timestamp: str | None = None
    creator: GuildMember | None = None
    jump_channel_id: str | None = None
    remind_type: RemindType | None = None

    @property
    def start(self) -> datetime | None:
        """开始时间（UTC）；没有或认不出时为 `None`。"""
        return _from_millis(self.start_timestamp)

    @property
    def end(self) -> datetime | None:
        """结束时间（UTC）；没有或认不出时为 `None`。"""
        return _from_millis(self.end_timestamp)


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _from_millis(value: str | None) -> datetime | None:
    if value is None or not value.isdecimal():
        return None
    try:
        return _EPOCH + timedelta(milliseconds=int(value))
    except OverflowError, ValueError:  # 超出 datetime 的范围；位数超过整数转换的上限
        return None
