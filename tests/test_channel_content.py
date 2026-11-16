"""频道的内容接口：表情表态、精华消息、频道公告、日程、论坛与音频。"""

import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone

import httpx2
import pytest

import pyqbot
from pyqbot._api.params import unix_millis

APP_SECRET = "secret-value-never-shown"
UTC8 = timezone(timedelta(hours=8))
EMOJI = pyqbot.Emoji(id="4", type=pyqbot.EmojiType.SYSTEM)
SCHEDULE = {
    "id": "112233",
    "name": "上王者",
    "start_timestamp": "1642076400000",
    "end_timestamp": "1642083600000",
    "creator": {
        "user": {"id": "xxxxxx", "username": "xxxxxx", "bot": True},
        "nick": "",
        "joined_at": "2022-01-11T10:24:13+08:00",
    },
    "jump_channel_id": "0",
    "remind_type": "0",
}
THREAD = {
    "guild_id": "75827011639035987",
    "channel_id": "2324603",
    "author_id": "144115218680332809",
    "thread_info": {
        "thread_id": "B_79051362477c03001441152186803328090X60-1645413753",
        "title": "帖子标题",
        "content": '{"paragraphs":[{"elems":[{"text":{"text":"正文"},"type":1}],"props":{}}]}',
        "date_time": "2022-02-21T11:22:33+08:00",
    },
}

type Respond = Callable[[httpx2.Request], httpx2.Response]


class Platform:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, object]] = []
        self.respond: Respond = lambda request: httpx2.Response(204)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": "t", "expires_in": "7200"})
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.raw_path.decode(), body))
        return self.respond(request)

    def returning(self, data: object, status_code: int = 200) -> None:
        self.respond = lambda request: httpx2.Response(status_code, json=data)


@asynccontextmanager
async def client_for(platform: Platform) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client("app-id", APP_SECRET, http_client=http_client) as client,
    ):
        yield client


# ---- 表情表态 ----


async def test_reactions_are_added_and_removed_by_emoji_type_and_id() -> None:
    platform = Platform()
    emoji = pyqbot.Emoji(id="128077", type=pyqbot.EmojiType.EMOJI)
    message = pyqbot.GuildMessage(id="m/1", channel_id="c", guild_id="g")

    async with client_for(platform) as client:
        await client.channels.add_reaction("c", "m", EMOJI)
        await client.channels.remove_reaction("c", message, emoji)

    assert platform.requests == [
        ("PUT", "/channels/c/messages/m/reactions/1/4", None),
        ("DELETE", "/channels/c/messages/m%2F1/reactions/2/128077", None),
    ]


async def test_reaction_users_are_paged_by_cookie_until_the_end() -> None:
    platform = Platform()
    pages = iter(
        [
            {
                "users": [{"id": "1", "username": "a", "avatar": "x"}],
                "cookie": "1_2",
                "is_end": False,
            },
            {"users": [{"id": "2"}, {"id": "3"}], "cookie": "1_3", "is_end": True},
        ]
    )
    platform.respond = lambda request: httpx2.Response(200, json=next(pages))

    async with client_for(platform) as client:
        users = [
            user async for user in client.channels.iter_reaction_users("c", "m", EMOJI, limit=50)
        ]

    assert [user.id for user in users] == ["1", "2", "3"]
    assert users[0].username == "a"
    assert [path for _, path, _ in platform.requests] == [
        "/channels/c/messages/m/reactions/1/4?limit=50",
        "/channels/c/messages/m/reactions/1/4?cookie=1_2",
    ]


async def test_reaction_with_an_empty_emoji_id_is_rejected() -> None:
    async with client_for(Platform()) as client:
        with pytest.raises(ValueError, match=r"emoji\.id 不合法"):
            await client.channels.add_reaction("c", "m", pyqbot.Emoji(id="", type=EMOJI.type))


# ---- 精华消息 ----


async def test_pins_are_listed_added_and_removed() -> None:
    platform = Platform()
    pins = {"guild_id": "g", "channel_id": "c", "message_ids": ["m1", "m2"]}
    platform.returning(pins)

    async with client_for(platform) as client:
        listed = await client.channels.get_pins("c")
        added = await client.channels.add_pin(
            "c", pyqbot.GuildMessage(id="m2", channel_id="c", guild_id="g")
        )
        platform.respond = lambda request: httpx2.Response(204)
        await client.channels.remove_pin("c", "m1")
        await client.channels.remove_all_pins("c")

    assert (
        listed
        == added
        == pyqbot.PinnedMessages(guild_id="g", channel_id="c", message_ids=("m1", "m2"))
    )
    assert platform.requests == [
        ("GET", "/channels/c/pins", None),
        ("PUT", "/channels/c/pins/m2", None),
        ("DELETE", "/channels/c/pins/m1", None),
        ("DELETE", "/channels/c/pins/all", None),
    ]


async def test_removing_the_pin_all_by_id_is_refused() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match="remove_all_pins"):
            await client.channels.remove_pin("c", "all")

    assert platform.requests == []


# ---- 频道公告 ----


async def test_announcements_are_created_and_deleted() -> None:
    platform = Platform()
    platform.returning(
        {
            "guild_id": "g",
            "channel_id": "c",
            "message_id": "",
            "announces_type": 1,
            "recommend_channels": [{"channel_id": "c1", "introduce": "推荐语"}],
        }
    )
    channels = [pyqbot.RecommendChannel(channel_id="c1", introduce="推荐语")]

    async with client_for(platform) as client:
        await client.guilds.announce_message("g", "c", "m")
        announcement = await client.guilds.announce_channels(
            "g", iter(channels), announces_type=pyqbot.AnnouncementType.WELCOME
        )
        platform.respond = lambda request: httpx2.Response(204)
        await client.guilds.delete_announcement(
            "g", message=pyqbot.GuildMessage(id="m", channel_id="c", guild_id="g")
        )
        await client.guilds.delete_announcement("g")

    assert announcement.announces_type == pyqbot.AnnouncementType.WELCOME
    assert announcement.recommend_channels == tuple(channels)
    assert announcement.message_id == ""
    assert platform.requests == [
        ("POST", "/guilds/g/announces", {"channel_id": "c", "message_id": "m"}),
        (
            "POST",
            "/guilds/g/announces",
            {
                "announces_type": 1,
                "recommend_channels": [{"channel_id": "c1", "introduce": "推荐语"}],
            },
        ),
        ("DELETE", "/guilds/g/announces/m", None),
        ("DELETE", "/guilds/g/announces/all", None),
    ]


async def test_message_announcement_needs_a_message_id() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match="消息 ID 不能为空"):
            await client.guilds.announce_message("g", "c", "")

    assert platform.requests == []


# ---- 日程 ----


async def test_schedules_are_listed_with_since_in_milliseconds() -> None:
    platform = Platform()
    platform.returning([SCHEDULE, {"name": "没有 id 的被丢掉"}, SCHEDULE | {"remind_type": 5}])

    async with client_for(platform) as client:
        schedules = await client.channels.list_schedules(
            "c", since=datetime(2022, 1, 13, 20, 20, tzinfo=UTC8)
        )
        await client.channels.list_schedules("c")

    assert [schedule.id for schedule in schedules] == ["112233", "112233"]
    first = schedules[0]
    assert first.remind_type == pyqbot.RemindType.NONE
    assert schedules[1].remind_type is None  # 类型不符的可选字段退回默认值
    assert first.creator is not None
    assert first.creator.user is not None
    assert first.creator.user.bot is True
    assert first.start == datetime(2022, 1, 13, 20, 20, tzinfo=UTC8)
    assert first.end == datetime(2022, 1, 13, 22, 20, tzinfo=UTC8)
    assert [path for _, path, _ in platform.requests] == [
        "/channels/c/schedules?since=1642076400000",
        "/channels/c/schedules",
    ]


async def test_schedule_is_created_updated_fetched_and_deleted() -> None:
    platform = Platform()
    platform.returning(SCHEDULE)
    start = datetime(2022, 1, 13, 12, 20, 53, tzinfo=UTC)

    async with client_for(platform) as client:
        created = await client.channels.create_schedule(
            "c", "上王者", start, start + timedelta(hours=2)
        )
        await client.channels.update_schedule(
            "c",
            created,
            "今晚八点上王者",
            start,
            start + timedelta(hours=2),
            description="描述",
            jump_channel_id="c2",
            remind_type=pyqbot.RemindType.BEFORE_15_MINUTES,
        )
        fetched = await client.channels.get_schedule("c", "112233")
        platform.respond = lambda request: httpx2.Response(204)
        await client.channels.delete_schedule("c", "112233")

    assert created == fetched
    assert platform.requests == [
        (
            "POST",
            "/channels/c/schedules",
            {
                "schedule": {
                    "name": "上王者",
                    "start_timestamp": "1642076453000",
                    "end_timestamp": "1642083653000",
                    "remind_type": "0",
                }
            },
        ),
        (
            "PATCH",
            "/channels/c/schedules/112233",
            {
                "schedule": {
                    "name": "今晚八点上王者",
                    "start_timestamp": "1642076453000",
                    "end_timestamp": "1642083653000",
                    "remind_type": "3",
                    "description": "描述",
                    "jump_channel_id": "c2",
                }
            },
        ),
        ("GET", "/channels/c/schedules/112233", None),
        ("DELETE", "/channels/c/schedules/112233", None),
    ]


async def test_naive_datetimes_are_rejected_before_sending() -> None:
    platform = Platform()
    naive = datetime(2022, 1, 13, 20, 20)

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match="since 必须带时区"):
            await client.channels.list_schedules("c", since=naive)
        with pytest.raises(ValueError, match="end 必须带时区"):
            await client.channels.create_schedule("c", "x", datetime.now(UTC), naive)

    assert platform.requests == []


@pytest.mark.parametrize("value", [None, "", "abc", "-1", "9" * 30, "9" * 5000], ids=repr)
def test_schedule_times_that_cannot_be_read_are_none(value: str | None) -> None:
    schedule = pyqbot.Schedule(id="s", start_timestamp=value, end_timestamp=value)

    assert (schedule.start, schedule.end) == (None, None)


def test_unix_millis_rounds_partial_milliseconds_up() -> None:
    assert unix_millis(datetime(1970, 1, 1, tzinfo=UTC), "t") == "0"
    assert unix_millis(datetime(1970, 1, 1, 0, 0, 0, 1, tzinfo=UTC), "t") == "1"
    assert (
        unix_millis(datetime(2022, 1, 13, 20, 20, 53, 123000, tzinfo=UTC8), "t") == "1642076453123"
    )
    assert (
        unix_millis(datetime(2022, 1, 13, 20, 20, 53, 123001, tzinfo=UTC8), "t") == "1642076453124"
    )


async def test_schedule_times_may_be_durations_from_now(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2022, 1, 13, 12, 20, 53, 500, tzinfo=UTC)
    monkeypatch.setattr("pyqbot._api.params.utc_now", lambda: now)
    platform = Platform()
    platform.returning(SCHEDULE)

    async with client_for(platform) as client:
        await client.channels.create_schedule(
            "c", "上王者", timedelta(minutes=10), timedelta(hours=2)
        )
        with pytest.raises(ValueError, match="end 必须是正的时长"):
            await client.channels.create_schedule("c", "x", timedelta(hours=1), timedelta(0))

    [(_, _, body)] = platform.requests
    assert body == {
        "schedule": {
            "name": "上王者",
            "start_timestamp": "1642077053001",
            "end_timestamp": "1642083653001",
            "remind_type": "0",
        }
    }


# ---- 论坛 ----


async def test_threads_are_listed_fetched_published_and_deleted() -> None:
    platform = Platform()
    platform.returning({"threads": [THREAD, THREAD], "is_finish": 1})

    async with client_for(platform) as client:
        listed = await client.channels.list_threads("c")
        platform.returning({"thread": THREAD})
        thread = await client.channels.get_thread("c", "t/1")
        platform.returning({"task_id": "1645413752912602306", "create_time": "1645503180"})
        task = await client.channels.publish_thread(
            "c", "标题", "<p>正文</p>", format=pyqbot.ForumThreadFormat.HTML
        )
        await client.channels.publish_thread("c", "标题", "正文")
        platform.respond = lambda request: httpx2.Response(204)
        await client.channels.delete_thread("c", thread)

    assert listed.finished
    assert listed.threads == (thread, thread)
    assert thread.author_id == "144115218680332809"
    assert thread.thread_info.title == "帖子标题"
    assert isinstance(thread.thread_info.content, str)
    text = pyqbot.ForumRichText.from_json(thread.thread_info.content).paragraphs[0].elems[0].text
    assert text is not None
    assert text.text == "正文"
    assert task == pyqbot.ForumPublishTask(task_id="1645413752912602306", create_time="1645503180")
    thread_id = "B_79051362477c03001441152186803328090X60-1645413753"
    assert platform.requests == [
        ("GET", "/channels/c/threads", None),
        ("GET", "/channels/c/threads/t%2F1", None),
        ("PUT", "/channels/c/threads", {"title": "标题", "content": "<p>正文</p>", "format": 2}),
        ("PUT", "/channels/c/threads", {"title": "标题", "content": "正文", "format": 1}),
        ("DELETE", f"/channels/c/threads/{thread_id}", None),
    ]


def test_unfinished_or_missing_is_finish_means_not_finished() -> None:
    assert not pyqbot.ForumThreadList(is_finish=0).finished
    assert not pyqbot.ForumThreadList().finished


# ---- 音频 ----


async def test_audio_is_controlled_and_the_mic_toggled() -> None:
    platform = Platform()
    platform.returning({})

    async with client_for(platform) as client:
        await client.channels.control_audio(
            "c", pyqbot.AudioStatus.START, audio_url="https://a.mp3", text="简单爱"
        )
        await client.channels.control_audio(
            "c", pyqbot.AudioStatus.START, audio_url="https://b.mp3"
        )
        await client.channels.control_audio("c", pyqbot.AudioStatus.PAUSE)
        await client.channels.join_mic("c")
        await client.channels.leave_mic("c")

    assert platform.requests == [
        (
            "POST",
            "/channels/c/audio",
            {"status": 0, "audio_url": "https://a.mp3", "text": "简单爱"},
        ),
        ("POST", "/channels/c/audio", {"status": 0, "audio_url": "https://b.mp3"}),
        ("POST", "/channels/c/audio", {"status": 1}),
        ("PUT", "/channels/c/mic", None),
        ("DELETE", "/channels/c/mic", None),
    ]


@pytest.mark.parametrize(
    ("status", "arguments", "match"),
    [
        (pyqbot.AudioStatus.START, {}, "要给出 audio_url"),
        (pyqbot.AudioStatus.STOP, {"audio_url": "https://a"}, "只在开始播放"),
        (pyqbot.AudioStatus.RESUME, {"text": "歌"}, "只在开始播放"),
    ],
)
async def test_audio_arguments_must_match_the_status(
    status: pyqbot.AudioStatus, arguments: dict[str, str], match: str
) -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match=match):
            await client.channels.control_audio("c", status, **arguments)

    assert platform.requests == []


# ---- 失败 ----


async def test_platform_errors_are_mapped_and_redacted() -> None:
    platform = Platform()
    platform.returning({"code": 302015, "message": f"开始时间不能早于当前时间 {APP_SECRET}"}, 400)

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.channels.create_schedule("c", "x", datetime.now(UTC), datetime.now(UTC))

    assert caught.value.err_code == 302015
    assert APP_SECRET not in str(caught.value)
    assert "POST /channels/c/schedules 失败" in str(caught.value)
