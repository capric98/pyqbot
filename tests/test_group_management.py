"""群管理：群信息、成员、黑名单、禁言、入群申请，以及入群申请事件上的审批快捷方法。"""

import asyncio
import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone

import httpx2
import pytest

import pyqbot
from pyqbot._gateway.payload import decode_payload
from pyqbot._models.event import bind_client

GROUP = "3E5D8A1F7B2C9E4D6A0F1B3C5D7E9F2A"
MEMBER = "7A3B9C1D5E2F4A6B8C0D1E3F5A7B9C2D"
CST = timezone(timedelta(hours=8))
TOKEN = "token-value-never-shown"

type Respond = Callable[[httpx2.Request], httpx2.Response]


class Platform:
    """扮演开放平台：记录除取 token 外的请求，响应由 `respond` 决定（默认 `{}`）。"""

    def __init__(self, body: object = None) -> None:
        self.calls: list[httpx2.Request] = []
        self.respond: Respond = lambda request: httpx2.Response(200, json=body or {})

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})
        self.calls.append(request)
        return self.respond(request)

    def requests(self) -> list[tuple[str, str, dict[str, str], object]]:
        """每个请求的方法、未解码的路径、查询参数与请求体（没有请求体为 `None`）。"""
        return [
            (
                request.method,
                request.url.raw_path.decode().partition("?")[0],
                dict(request.url.params),
                json.loads(request.content) if request.content else None,
            )
            for request in self.calls
        ]


@asynccontextmanager
async def client_for(platform: Platform) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client("app-id", "app-secret", http_client=http_client) as client,
    ):
        yield client


def paged(pages: dict[str | None, object]) -> Respond:
    """按查询参数里的 `cursor` 返回对应的一页。"""
    return lambda request: httpx2.Response(200, json=pages[request.url.params.get("cursor")])


# ---- 群信息与机器人状态 ----


async def test_get_group_decodes_the_documented_example() -> None:
    platform = Platform(
        {
            "group_openid": GROUP,
            "group_name": "读书分享会",
            "group_finger_memo": "每周共读一本好书",
            "group_class_text": "文化",
            "group_tags": ["阅读", "文学", "成长"],
            "group_member_num": 256,
        }
    )

    async with client_for(platform) as client:
        info = await client.groups.get(GROUP)

    assert info == pyqbot.GroupInfo(
        group_openid=GROUP,
        group_name="读书分享会",
        group_finger_memo="每周共读一本好书",
        group_class_text="文化",
        group_tags=("阅读", "文学", "成长"),
        group_member_num=256,
    )
    assert platform.requests() == [("GET", f"/v2/groups/{GROUP}/info", {}, None)]


async def test_get_bot_state_decodes_to_enums_and_datetimes() -> None:
    platform = Platform(
        {
            "member_openid": MEMBER,
            "joined_at": "2025-06-15T14:30:00+08:00",
            "allow_proactive_msg": False,
            "recv_msg_setting": "only_mention",
            "member_role": "admin",
        }
    )

    async with client_for(platform) as client:
        state = await client.groups.get_bot_state(GROUP)

    assert state == pyqbot.GroupBotState(
        member_openid=MEMBER,
        joined_at=datetime(2025, 6, 15, 14, 30, tzinfo=CST),
        allow_proactive_msg=False,
        recv_msg_setting=pyqbot.RecvMsgSetting.ONLY_MENTION,
        member_role=pyqbot.GroupMemberRole.ADMIN,
    )
    assert platform.requests() == [("GET", f"/v2/groups/{GROUP}/bot_state", {}, None)]


async def test_unknown_values_and_bad_optional_fields_do_not_fail() -> None:
    platform = Platform({"recv_msg_setting": "everything", "joined_at": 123, "extra": 1})

    async with client_for(platform) as client:
        state = await client.groups.get_bot_state(GROUP)

    assert state.recv_msg_setting == "everything"
    assert state.recv_msg_setting is not None
    assert state.recv_msg_setting.name == "UNKNOWN"
    assert state.joined_at is None


async def test_without_whitelist_the_platform_error_is_raised() -> None:
    platform = Platform()
    platform.respond = lambda request: httpx2.Response(
        200, json={"err_code": 11253, "message": "应用无接口访问权限", "trace_id": "tr-1"}
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="应用无接口访问权限") as caught:
            await client.groups.get(GROUP)

    assert (caught.value.err_code, caught.value.trace_id) == (11253, "tr-1")
    assert str(caught.value).startswith(f"GET /v2/groups/{GROUP}/info 失败：")


async def test_path_parameters_are_escaped_and_must_not_be_empty() -> None:
    platform = Platform({"member_openid": "m"})

    async with client_for(platform) as client:
        await client.groups.get_member("a/b", "../m")
        with pytest.raises(ValueError, match="member_openid"):
            await client.groups.get_member(GROUP, "")
        with pytest.raises(ValueError, match="openid"):
            await client.groups.get("")

    assert platform.requests() == [("GET", "/v2/groups/a%2Fb/members/..%2Fm", {}, None)]


# ---- 成员 ----

MEMBER_JSON: dict[str, object] = {
    "member_openid": MEMBER,
    "username": "小明",
    "member_role": "admin",
    "bot": False,
    "joined_at": "2025-08-20T09:15:00+08:00",
    "union_openid": "B4C6D8E0F2A4B6C8D0E2F4A6B8C0D2E4",
}
MEMBER_INFO = pyqbot.GroupMember(
    member_openid=MEMBER,
    username="小明",
    member_role=pyqbot.GroupMemberRole.ADMIN,
    bot=False,
    joined_at=datetime(2025, 8, 20, 9, 15, tzinfo=CST),
    union_openid="B4C6D8E0F2A4B6C8D0E2F4A6B8C0D2E4",
)


async def test_get_member() -> None:
    platform = Platform(MEMBER_JSON)

    async with client_for(platform) as client:
        member = await client.groups.get_member(GROUP, MEMBER)

    assert member == MEMBER_INFO
    assert platform.requests() == [("GET", f"/v2/groups/{GROUP}/members/{MEMBER}", {}, None)]


async def test_get_member_without_an_openid_is_unrecognisable() -> None:
    platform = Platform({"username": "小明"})

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="响应无法识别"):
            await client.groups.get_member(GROUP, MEMBER)


async def test_iter_members_follows_the_cursor_in_the_query_string() -> None:
    platform = Platform()
    platform.respond = paged(
        {
            None: {"members": [MEMBER_JSON], "next_cursor": "bG1f"},
            "bG1f": {"members": [{"member_openid": "m2"}, {"username": "没有 openid"}]},
        }
    )

    async with client_for(platform) as client:
        members = [member async for member in client.groups.iter_members(GROUP)]

    assert members == [MEMBER_INFO, pyqbot.GroupMember(member_openid="m2")]
    path = f"/v2/groups/{GROUP}/members"
    assert platform.requests() == [
        ("GET", path, {}, None),
        ("GET", path, {"cursor": "bG1f"}, None),
    ]


async def test_remove_members_returns_nothing_when_everything_succeeds() -> None:
    platform = Platform(
        {"remove_members_result": "success", "add_to_member_blacklist_fail_openids": []}
    )

    async with client_for(platform) as client:
        await client.groups.remove_members(GROUP, ["m1", "m2"], add_to_blacklist=True)
        await client.groups.remove_members(GROUP, "m3")  # 单个 openid 不会被拆成字符
        await client.groups.remove_members(GROUP, iter(["m4"]))

    path = f"/v2/groups/{GROUP}/batch_remove_members"
    assert platform.requests() == [
        ("POST", path, {}, {"member_openids": ["m1", "m2"], "add_to_member_blacklist": True}),
        ("POST", path, {}, {"member_openids": ["m3"], "add_to_member_blacklist": False}),
        ("POST", path, {}, {"member_openids": ["m4"], "add_to_member_blacklist": False}),
    ]


@pytest.mark.parametrize("body", [{}, {"add_to_member_blacklist_fail_openids": None}])
async def test_a_missing_failure_list_means_no_failures(body: dict[str, object]) -> None:
    async with client_for(Platform(body or {"remove_members_result": "success"})) as client:
        await client.groups.remove_members(GROUP, "m1", add_to_blacklist=True)


async def test_blacklist_failures_after_removal_are_a_partial_failure() -> None:
    platform = Platform()
    platform.respond = lambda request: httpx2.Response(
        200,
        json={"remove_members_result": "success", "add_to_member_blacklist_fail_openids": ["m2"]},
        headers={"X-Tps-trace-ID": "trace-1"},
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.PartialFailureError) as caught:
            await client.groups.remove_members(GROUP, ["m1", "m2"], add_to_blacklist=True)

    error = caught.value
    assert isinstance(error, pyqbot.APIError)
    assert error.failed_ids == ("m2",)
    assert (error.status_code, error.err_code, error.trace_id) == (200, None, "trace-1")
    assert error.outcome_unknown  # 除了 failed_ids 都生效了，不能当作没有生效
    assert error.message == (
        f"POST /v2/groups/{GROUP}/batch_remove_members 部分失败："
        "成员已移出，但 1 个未能加入黑名单：m2"
    )
    with pytest.raises(AttributeError):
        error.failed_ids = ()  # pyright: ignore[reportAttributeAccessIssue]


async def test_removal_that_is_not_reported_as_success_is_an_api_error() -> None:
    platform = Platform({"remove_members_result": "failed"})

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="remove_members_result 为 'failed'") as caught:
            await client.groups.remove_members(GROUP, "m1")

    assert not isinstance(caught.value, pyqbot.PartialFailureError)
    assert caught.value.outcome_unknown  # 不是 success，又没有错误码：说不清移出了没有


@pytest.mark.parametrize(
    "fail_openids",
    [["m1", 2], "m1", {"m1": True}, 0],
    ids=["mixed_types", "string", "object", "number"],
)
async def test_malformed_failure_lists_are_not_mistaken_for_success(fail_openids: object) -> None:
    removed = Platform({"add_to_member_blacklist_fail_openids": fail_openids})
    blacklisted = Platform({"fail_openids": fail_openids})

    async with client_for(removed) as client:
        with pytest.raises(pyqbot.APIError, match="响应无法识别"):
            await client.groups.remove_members(GROUP, "m1", add_to_blacklist=True)
    async with client_for(blacklisted) as client:
        with pytest.raises(pyqbot.APIError, match="响应无法识别"):
            await client.groups.add_to_blacklist(GROUP, "m1")


@pytest.mark.parametrize("result", [False, 0, {"ok": True}], ids=["false", "number", "object"])
async def test_malformed_removal_result_is_not_mistaken_for_success(result: object) -> None:
    platform = Platform({"remove_members_result": result})

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="响应无法识别"):
            await client.groups.remove_members(GROUP, "m1")


@pytest.mark.parametrize("body", [{}, {"remove_members_result": None}], ids=["missing", "null"])
async def test_a_missing_removal_result_is_not_a_failure(body: dict[str, object]) -> None:
    async with client_for(Platform(body or {"add_to_member_blacklist_fail_openids": []})) as client:
        await client.groups.remove_members(GROUP, "m1")


async def test_partial_failure_text_and_trace_id_are_redacted() -> None:
    platform = Platform()
    platform.respond = lambda request: httpx2.Response(
        200, json={"fail_openids": [f"echo-{TOKEN}"]}, headers={"X-Tps-trace-ID": TOKEN}
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.PartialFailureError) as caught:
            await client.groups.add_to_blacklist(GROUP, "m1")

    assert TOKEN not in str(caught.value)
    assert TOKEN not in repr(caught.value)
    assert caught.value.trace_id == "***"


async def test_unrecognised_removal_result_is_redacted() -> None:
    platform = Platform()
    platform.respond = lambda request: httpx2.Response(
        200, json={"remove_members_result": "app-secret"}, headers={"X-Tps-trace-ID": TOKEN}
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.groups.remove_members(GROUP, "m1")

    assert "app-secret" not in str(caught.value)
    assert caught.value.trace_id == "***"


# ---- 黑名单 ----


async def test_iter_blacklist_asks_for_full_pages() -> None:
    user: dict[str, object] = {
        "union_openid": "U",
        "member_openid": MEMBER,
        "username": "阳光少年",
        "banned_at": "2025-07-01T10:30:00+08:00",
        "bot": False,
    }
    platform = Platform()
    platform.respond = paged(
        {
            None: {"users": [user], "next_cursor": "c1"},
            "c1": {"users": [{"member_openid": "m2"}], "next_cursor": ""},
        }
    )

    async with client_for(platform) as client:
        users = [user async for user in client.groups.iter_blacklist(GROUP)]

    assert users == [
        pyqbot.BlacklistedUser(
            member_openid=MEMBER,
            username="阳光少年",
            banned_at=datetime(2025, 7, 1, 10, 30, tzinfo=CST),
            bot=False,
            union_openid="U",
        ),
        pyqbot.BlacklistedUser(member_openid="m2"),
    ]
    path = f"/v2/groups/{GROUP}/member_blacklist"
    assert platform.requests() == [
        ("GET", path, {"limit": "100"}, None),
        ("GET", path, {"limit": "100", "cursor": "c1"}, None),
    ]


async def test_blacklist_add_and_remove() -> None:
    platform = Platform({"fail_openids": []})

    async with client_for(platform) as client:
        await client.groups.add_to_blacklist(GROUP, ["m1", "m2"])
        await client.groups.remove_from_blacklist(GROUP, "m1")

    path = f"/v2/groups/{GROUP}/member_blacklist"
    assert platform.requests() == [
        ("POST", path, {}, {"op": "add", "member_openids": ["m1", "m2"]}),
        ("POST", path, {}, {"op": "del", "member_openids": ["m1"]}),
    ]


@pytest.mark.parametrize(
    ("op", "step"), [("add_to_blacklist", "加入"), ("remove_from_blacklist", "移出")]
)
async def test_blacklist_failures_are_a_partial_failure(op: str, step: str) -> None:
    platform = Platform({"fail_openids": ["m1", "m3"]})

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.PartialFailureError) as caught:
            await getattr(client.groups, op)(GROUP, ["m1", "m2", "m3"])

    assert caught.value.failed_ids == ("m1", "m3")
    assert caught.value.message.endswith(f"部分失败：2 个未能{step}黑名单：m1、m3")


# ---- 禁言 ----


async def test_get_mute_settings_decodes_the_documented_example() -> None:
    platform = Platform(
        {
            "global_rule": {
                "mode": "schedule",
                "schedule_rules": [
                    {
                        "task_id": "task_7ffd",
                        "start_at": "2026-07-22T10:44:00+08:00",
                        "end_at": "2026-07-22T11:44:00+08:00",
                        "enabled": False,
                    }
                ],
                "recurring_rules": [
                    {
                        "task_id": "task_3a63",
                        "weekdays": [1, 2, 3, 4, 5, 6, 7],
                        "start_time": "13:05",
                        "end_time": "14:05",
                        "enabled": True,
                    }
                ],
            },
            "members": [
                {
                    "member_openid": "EC58",
                    "mute_expire_at": "2026-08-05T11:23:04+08:00",
                    "username": "T小不点101",
                    "union_openid": "EC58",
                },
                {"username": "没有 openid 的成员被单独丢掉"},
            ],
        }
    )

    async with client_for(platform) as client:
        settings = await client.groups.get_mute_settings(GROUP)

    assert settings == pyqbot.GroupMuteSettings(
        global_rule=pyqbot.GroupMuteRule(
            mode=pyqbot.GroupMuteMode.SCHEDULE,
            schedule_rules=(
                pyqbot.MuteScheduleRule(
                    task_id="task_7ffd",
                    start_at=datetime(2026, 7, 22, 10, 44, tzinfo=CST),
                    end_at=datetime(2026, 7, 22, 11, 44, tzinfo=CST),
                    enabled=False,
                ),
            ),
            recurring_rules=(
                pyqbot.MuteRecurringRule(
                    task_id="task_3a63",
                    weekdays=(1, 2, 3, 4, 5, 6, 7),
                    start_time="13:05",
                    end_time="14:05",
                    enabled=True,
                ),
            ),
        ),
        members=(
            pyqbot.MutedMember(
                member_openid="EC58",
                mute_expire_at=datetime(2026, 8, 5, 11, 23, 4, tzinfo=CST),
                username="T小不点101",
                union_openid="EC58",
            ),
        ),
    )
    # 文档的示例带了 {} 请求体，这里按查询接口不发请求体（docs/errata.md）。
    assert platform.requests() == [("GET", f"/v2/groups/{GROUP}/restrict_chat_setting", {}, None)]


async def test_empty_mute_settings_have_defaults() -> None:
    async with client_for(Platform()) as client:
        settings = await client.groups.get_mute_settings(GROUP)

    assert settings == pyqbot.GroupMuteSettings()
    assert settings.global_rule.mode is None


NOW = datetime(2026, 8, 5, 12, 0, 0, 500_000, tzinfo=UTC)


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """把「现在」固定在 `NOW`（带半秒），不读真实时间。"""
    monkeypatch.setattr("pyqbot._api.params.utc_now", lambda: NOW)


async def mute_expiry(until: datetime | timedelta, *, update: bool = False) -> str:
    platform = Platform()
    async with client_for(platform) as client:
        mute = client.groups.update_member_mutes if update else client.groups.mute_members
        await mute(GROUP, MEMBER, until)
    [(_, _, _, body)] = platform.requests()
    assert isinstance(body, dict)
    [member] = body["members"]  # pyright: ignore[reportUnknownVariableType]
    return member["mute_expire_at"]  # pyright: ignore[reportUnknownVariableType]


async def test_mute_until_an_aware_datetime_is_sent_in_utc() -> None:
    platform = Platform()
    until = datetime(2026, 8, 5, 11, 23, 5, tzinfo=CST)

    async with client_for(platform) as client:
        await client.groups.mute_members(GROUP, ["m1", "m2"], until)

    stamp = "2026-08-05T03:23:05+00:00"
    assert platform.requests() == [
        (
            "POST",
            f"/v2/groups/{GROUP}/restrict_chat_setting",
            {},
            {
                "members": [
                    {"op": "add", "member_openid": "m1", "mute_expire_at": stamp},
                    {"op": "add", "member_openid": "m2", "mute_expire_at": stamp},
                ]
            },
        )
    ]


@pytest.mark.usefixtures("frozen_clock")
@pytest.mark.parametrize(
    ("until", "expected"),
    [
        # 现在是 12:00:00.5，截掉小数会得到比现在还早的 12:00:00。
        (timedelta(milliseconds=100), "2026-08-05T12:00:01+00:00"),
        (timedelta(milliseconds=500), "2026-08-05T12:00:01+00:00"),
        (timedelta(minutes=10), "2026-08-05T12:10:01+00:00"),
        (timedelta(seconds=59, microseconds=500_000), "2026-08-05T12:01:00+00:00"),
    ],
)
async def test_a_duration_counts_from_now_and_rounds_up(until: timedelta, expected: str) -> None:
    assert await mute_expiry(until) == expected


@pytest.mark.parametrize(
    ("until", "expected"),
    [
        (datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC), "2026-08-05T12:00:00+00:00"),
        (datetime(2026, 8, 5, 12, 0, 0, 1, tzinfo=UTC), "2026-08-05T12:00:01+00:00"),
        (datetime(2026, 8, 5, 23, 59, 59, 999_999, tzinfo=CST), "2026-08-05T16:00:00+00:00"),
        # 秒级偏移直接输出是 +00:00:30，不是合法的 RFC3339。
        (
            datetime(2026, 8, 5, 12, 0, 30, tzinfo=timezone(timedelta(seconds=30))),
            "2026-08-05T12:00:00+00:00",
        ),
        (
            datetime(2026, 8, 5, 12, 0, 0, 250_000, tzinfo=timezone(timedelta(seconds=-30))),
            "2026-08-05T12:00:31+00:00",
        ),
    ],
)
async def test_a_datetime_is_converted_to_utc_and_rounded_up(
    until: datetime, expected: str
) -> None:
    assert await mute_expiry(until) == expected


@pytest.mark.usefixtures("frozen_clock")
async def test_update_mute_sends_update_with_the_same_time_rules() -> None:
    assert await mute_expiry(timedelta(hours=1), update=True) == "2026-08-05T13:00:01+00:00"


async def test_update_mute_request() -> None:
    platform = Platform()
    until = datetime(2026, 8, 6, tzinfo=UTC)

    async with client_for(platform) as client:
        await client.groups.update_member_mutes(GROUP, ["m1", "m2"], until)

    stamp = "2026-08-06T00:00:00+00:00"
    assert platform.requests() == [
        (
            "POST",
            f"/v2/groups/{GROUP}/restrict_chat_setting",
            {},
            {
                "members": [
                    {"op": "update", "member_openid": "m1", "mute_expire_at": stamp},
                    {"op": "update", "member_openid": "m2", "mute_expire_at": stamp},
                ]
            },
        )
    ]


@pytest.mark.parametrize(
    ("until", "message"),
    [
        (datetime(2026, 8, 5, 11, 23), "必须带时区"),
        (timedelta(0), "必须是正的时长"),
        (timedelta(seconds=-1), "必须是正的时长"),
    ],
)
async def test_mute_rejects_ambiguous_or_past_times_before_sending(
    until: datetime | timedelta, message: str
) -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match=message):
            await client.groups.mute_members(GROUP, MEMBER, until)
        with pytest.raises(ValueError, match=message):
            await client.groups.update_member_mutes(GROUP, MEMBER, until)

    assert platform.calls == []


async def test_unmute_sends_an_empty_expiry() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        await client.groups.unmute_members(GROUP, "m1")

    assert platform.requests() == [
        (
            "POST",
            f"/v2/groups/{GROUP}/restrict_chat_setting",
            {},
            {"members": [{"op": "del", "member_openid": "m1", "mute_expire_at": ""}]},
        )
    ]


async def test_mute_rejected_because_the_bot_is_not_an_admin() -> None:
    platform = Platform()
    platform.respond = lambda request: httpx2.Response(
        403, json={"code": 11264, "message": "机器人不是管理员"}
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="机器人不是管理员") as caught:
            await client.groups.mute_members(GROUP, MEMBER, timedelta(minutes=1))

    assert (caught.value.status_code, caught.value.err_code) == (403, 11264)


# ---- 入群申请 ----

JOIN_REQUEST_JSON: dict[str, object] = {
    "join_request_id": "Ael-dmvl",
    "risk_tips": "",
    "union_openid": "FE00",
    "member_openid": "FE00",
    "username": "痞孓小光光",
    "apply_at": "2026-08-05T14:19:09+08:00",
    "apply_source": "self_apply",
    "invited_by": "",
    "bot": False,
    "verify_info": {"method": "verify_message", "verify_message": "几款看看", "review_qa_list": []},
}


async def test_iter_join_requests_reads_the_list_field() -> None:
    platform = Platform()
    platform.respond = paged(
        {
            None: {"list": [JOIN_REQUEST_JSON], "next_cursor": "1785767153250497"},
            "1785767153250497": {"list": [{"member_openid": "没有申请 ID"}], "next_cursor": ""},
        }
    )

    async with client_for(platform) as client:
        requests = [request async for request in client.groups.iter_join_requests(GROUP)]

    [request] = requests
    assert request.join_request_id == "Ael-dmvl"
    assert request.member_openid == "FE00"
    assert request.apply_at == datetime(2026, 8, 5, 14, 19, 9, tzinfo=CST)
    assert request.apply_source == pyqbot.JoinRequestSource.SELF_APPLY
    assert request.verify_info is not None
    assert request.verify_info.method == pyqbot.JoinRequestVerifyMethod.VERIFY_MESSAGE
    assert request.verify_info.verify_message == "几款看看"
    assert request.to_dict()["join_request_id"] == "Ael-dmvl"
    path = f"/v2/groups/{GROUP}/join_request_list"
    assert platform.requests() == [
        ("GET", path, {"limit": "50"}, None),
        ("GET", path, {"limit": "50", "cursor": "1785767153250497"}, None),
    ]


async def test_join_request_page_keeps_the_interface_field_name() -> None:
    platform = Platform()
    platform.respond = paged({None: {"list": [JOIN_REQUEST_JSON]}})

    async with client_for(platform) as client:
        [request] = [request async for request in client.groups.iter_join_requests(GROUP)]

    assert isinstance(request, pyqbot.GroupJoinRequestInfo)


async def test_approve_and_decline_join_requests() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        await client.groups.approve_join_request(GROUP, "FE00", join_request_id="AURi")
        await client.groups.approve_join_request(GROUP, "FE00")
        await client.groups.decline_join_request(
            GROUP, "FE00", join_request_id="AVKi", reason="机器人自动拒绝", add_to_blacklist=True
        )
        await client.groups.decline_join_request(GROUP, "FE00")

    path = f"/v2/groups/{GROUP}/approval_join_request/FE00"
    assert platform.requests() == [
        ("POST", path, {}, {"op": "approve", "join_request_id": "AURi"}),
        ("POST", path, {}, {"op": "approve"}),
        (
            "POST",
            path,
            {},
            {
                "op": "decline",
                "join_request_id": "AVKi",
                "reject_reason": "机器人自动拒绝",
                "add_to_member_blacklist": True,
            },
        ),
        ("POST", path, {}, {"op": "decline", "add_to_member_blacklist": False}),
    ]


async def test_join_request_review_errors() -> None:
    platform = Platform()
    platform.respond = lambda request: httpx2.Response(
        200, json={"err_code": 500001, "message": "申请已处理"}
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="申请已处理"):
            await client.groups.approve_join_request(GROUP, "FE00")
        with pytest.raises(ValueError, match="member_openid"):
            await client.groups.decline_join_request(GROUP, "..")

    assert len(platform.calls) == 1


# ---- 入群申请事件上的快捷方法 ----

JOIN_EVENT: dict[str, object] = {
    "group_openid": GROUP,
    "join_request_id": "AVKi",
    "member_openid": "FE00",
    "apply_source": "self_apply",
}


async def test_join_request_event_can_be_approved_or_declined() -> None:
    platform = Platform()
    event = pyqbot.GroupJoinRequest(
        group_openid=GROUP, join_request_id="AVKi", member_openid="FE00"
    )

    async with client_for(platform) as client:
        bind_client(event, client)
        await event.approve()
        await event.decline()
        await event.decline(reason="不认识", add_to_blacklist=True)

    path = f"/v2/groups/{GROUP}/approval_join_request/FE00"
    assert platform.requests() == [
        ("POST", path, {}, {"op": "approve", "join_request_id": "AVKi"}),
        (
            "POST",
            path,
            {},
            {"op": "decline", "join_request_id": "AVKi", "add_to_member_blacklist": False},
        ),
        (
            "POST",
            path,
            {},
            {
                "op": "decline",
                "join_request_id": "AVKi",
                "reject_reason": "不认识",
                "add_to_member_blacklist": True,
            },
        ),
    ]


async def test_join_request_shortcuts_need_a_bound_client() -> None:
    event = pyqbot.GroupJoinRequest(group_openid=GROUP, join_request_id="r", member_openid="m")

    with pytest.raises(RuntimeError, match="没有绑定 Client"):
        await event.approve()
    with pytest.raises(RuntimeError, match="没有绑定 Client"):
        await event.decline()


async def test_bot_dispatches_join_requests_that_can_be_approved_in_the_handler() -> None:
    platform = Platform()
    approved = asyncio.Event()
    frame = {"op": 0, "s": 1, "t": "GROUP_JOIN_REQUEST", "d": JOIN_EVENT, "id": "E:1"}

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Bot("app-id", "app-secret", http_client=http_client) as bot,
    ):

        @bot.on_group_join_request
        async def review(event: pyqbot.GroupJoinRequest) -> None:
            await event.approve()
            approved.set()

        # 由测试代替 Bot.start() 把 Dispatch 交给分发器。
        bot._dispatcher.dispatch(decode_payload(json.dumps(frame)), bot)  # pyright: ignore[reportPrivateUsage]
        async with asyncio.timeout(5):
            await approved.wait()

    assert platform.requests() == [
        (
            "POST",
            f"/v2/groups/{GROUP}/approval_join_request/FE00",
            {},
            {"op": "approve", "join_request_id": "AVKi"},
        )
    ]
