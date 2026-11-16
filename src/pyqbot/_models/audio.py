"""音频子频道：播放状态、上下麦，以及成员进出音视频 / 直播子频道的事件。

官方文档：`server-inter/channel/content/audio/model.md`、`server-inter/channel/role/audio_or_live_channel_member.md`。
"""

from .._gateway.intents import Intents
from .._model import OpenIntEnum
from .event import Event


class AudioStatus(OpenIntEnum):
    """音频播放的操作（官方 AudioControl 的 `status`）。"""

    START = 0
    PAUSE = 1
    RESUME = 2
    STOP = 3


class _AudioActionEvent(Event):
    # 文档没有给出这几个事件的 payload，按 AudioAction 建模，见 docs/errata.md。
    guild_id: str | None = None
    channel_id: str
    audio_url: str | None = None
    text: str = ""


class AudioStart(_AudioActionEvent):
    """音频开始播放，对应事件 `AUDIO_START`。

    Attributes:
        guild_id: 频道 ID。
        channel_id: 音频子频道的 ID。
        audio_url: 音频地址。
        text: 状态文本，如歌名，没有时为空串。
    """

    event_name = "AUDIO_START"
    intent = Intents.AUDIO_ACTION


class AudioFinish(_AudioActionEvent):
    """音频播放结束，对应事件 `AUDIO_FINISH`；字段同 `AudioStart`。"""

    event_name = "AUDIO_FINISH"
    intent = Intents.AUDIO_ACTION


class AudioOnMic(_AudioActionEvent):
    """音频子频道有人上麦，对应事件 `AUDIO_ON_MIC`；字段同 `AudioStart`。"""

    event_name = "AUDIO_ON_MIC"
    intent = Intents.AUDIO_ACTION


class AudioOffMic(_AudioActionEvent):
    """音频子频道有人下麦，对应事件 `AUDIO_OFF_MIC`；字段同 `AudioStart`。"""

    event_name = "AUDIO_OFF_MIC"
    intent = Intents.AUDIO_ACTION


class AudioOrLiveChannelType(OpenIntEnum):
    """成员进出的是哪种子频道（`channel_type`）。取值来自该事件的文档，与 `ChannelType` 不是同一套。

    Attributes:
        AUDIO: 音视频子频道。
        LIVE: 直播子频道。
    """

    AUDIO = 2
    LIVE = 5


class _AudioOrLiveChannelMemberEvent(Event):
    # 文档没有给出 Intent 位，见 docs/design.md「事件」。
    intent = Intents(0)

    guild_id: str | None = None
    channel_id: str
    channel_type: AudioOrLiveChannelType | None = None
    user_id: str


class AudioOrLiveChannelMemberEnter(_AudioOrLiveChannelMemberEvent):
    """用户进入音视频或直播子频道，对应事件 `AUDIO_OR_LIVE_CHANNEL_MEMBER_ENTER`。

    Attributes:
        guild_id: 频道 ID。
        channel_id: 子频道 ID。
        channel_type: 音视频还是直播子频道。
        user_id: 用户 ID。
    """

    event_name = "AUDIO_OR_LIVE_CHANNEL_MEMBER_ENTER"


class AudioOrLiveChannelMemberExit(_AudioOrLiveChannelMemberEvent):
    """用户离开音视频或直播子频道，对应事件 `AUDIO_OR_LIVE_CHANNEL_MEMBER_EXIT`。

    字段同 `AudioOrLiveChannelMemberEnter`。
    """

    event_name = "AUDIO_OR_LIVE_CHANNEL_MEMBER_EXIT"
