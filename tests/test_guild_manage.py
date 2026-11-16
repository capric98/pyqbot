"""频道与子频道的管理接口：`client.guilds` 与 `client.channels`。"""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import httpx2
import pytest

import pyqbot
from pyqbot._api.params import str_list, unix_seconds

APP_SECRET = "secret-value-never-shown"
TOKEN = "access-token-value"

type Request = tuple[str, str, dict[str, str], object]


class Platform:
    """按 `(方法, 路径)` 给出预设的响应（值为 `Page` 的列表时依次给出，没有则是 204），记下除获取 token 以外的每个请求。"""

    def __init__(self, responses: dict[tuple[str, str], object] | None = None) -> None:
        self.requests: list[Request] = []
        self.responses = dict(responses or {})
        self.fallback: httpx2.Response | None = None

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})
        body = json.loads(request.content) if request.content else None
        path = request.url.raw_path.decode().partition("?")[0]
        self.requests.append((request.method, path, dict(request.url.params), body))
        if self.fallback is not None:
            return self.fallback
        response = self.responses.get((request.method, path))
        if isinstance(response, list):
            items = cast(list[object], response)
            if items and isinstance(first := items[0], Page):
                items.pop(0)
                return httpx2.Response(200, json=first.body, headers=first.headers)
        if response is None:
            return httpx2.Response(204)
        return httpx2.Response(200, json=response)


class Page:
    """分页测试里依次给出的一页响应。"""

    def __init__(self, body: object, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.headers = headers


@asynccontextmanager
async def client_for(platform: Platform) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client("app-id", APP_SECRET, http_client=http_client) as client,
    ):
        yield client


GUILD = {
    "id": "2452178231489345741",
    "name": "读书分享会",
    "icon": "https://groupprohead.gtimg.cn/1/40",
    "owner_id": "17481532452010052342",
    "owner": False,
    "joined_at": "2025-01-09T15:17:23+08:00",
    "member_count": 6,
    "max_members": 5000000,
    "description": "一起读书，共同成长",
}

CHANNEL = {
    "id": "123456",
    "guild_id": "123456789012345678",
    "name": "文字交流区",
    "type": 0,
    "sub_type": 0,
    "position": 1,
    "parent_id": "0",
    "owner_id": "123456789012345678",
    "private_type": 0,
    "speak_permission": 1,
    "permissions": "0",
}


def member(user_id: str, nick: str = "") -> dict[str, object]:
    return {
        "user": {"id": user_id, "username": f"u{user_id}", "bot": False},
        "nick": nick,
        "roles": ["1"],
        "joined_at": "2021-12-05T14:08:29+08:00",
    }


# ---- 频道 ----


async def test_iter_guilds_pages_with_after_until_an_empty_page() -> None:
    second = {**GUILD, "id": "9160663460093593400"}
    platform = Platform(
        {("GET", "/users/@me/guilds"): [Page([GUILD]), Page({"guilds": [second]}), Page([])]}
    )

    async with client_for(platform) as client:
        guilds = [guild async for guild in client.guilds.iter_guilds(limit=1)]

    assert [guild.id for guild in guilds] == ["2452178231489345741", "9160663460093593400"]
    assert guilds[0].joined_at == datetime(
        2025, 1, 9, 15, 17, 23, tzinfo=timezone(timedelta(hours=8))
    )
    assert [params for _, _, params, _ in platform.requests] == [
        {"limit": "1"},
        {"limit": "1", "after": "2452178231489345741"},
        {"limit": "1", "after": "9160663460093593400"},
    ]


async def test_iter_guilds_starts_after_the_given_guild() -> None:
    platform = Platform({("GET", "/users/@me/guilds"): [Page([])]})

    async with client_for(platform) as client:
        guilds = [guild async for guild in client.guilds.iter_guilds(after="42")]

    assert guilds == []
    assert platform.requests == [
        ("GET", "/users/@me/guilds", {"limit": "100", "after": "42"}, None)
    ]


TRACE = {"X-Tps-trace-ID": "trace-1"}


@pytest.mark.parametrize("body", ["oops", 1, False, None])
async def test_list_responses_that_are_neither_array_nor_object_are_api_errors(
    body: object,
) -> None:
    platform = Platform({("GET", "/guilds/g1/channels"): [Page(body, TRACE)]})

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="响应无法识别") as caught:
            await client.guilds.list_channels("g1")

    assert caught.value.status_code == 200
    assert caught.value.trace_id == "trace-1"


@pytest.mark.parametrize("body", [{"unrelated": []}, {"guilds": "oops"}])
async def test_an_object_without_a_usable_list_means_no_guilds(body: object) -> None:
    platform = Platform({("GET", "/users/@me/guilds"): [Page(body)]})

    async with client_for(platform) as client:
        guilds = [guild async for guild in client.guilds.iter_guilds()]

    assert guilds == []


async def test_list_skips_only_the_malformed_items() -> None:
    platform = Platform(
        {("GET", "/users/@me/guilds"): [Page([{"name": "没有 ID"}, GUILD]), Page([])]}
    )

    async with client_for(platform) as client:
        guilds = [guild async for guild in client.guilds.iter_guilds()]

    assert [guild.id for guild in guilds] == [GUILD["id"]]


@pytest.mark.parametrize("last", [{"name": "没有 ID"}, {**GUILD, "id": ""}])
async def test_iter_guilds_fails_when_the_last_guild_has_no_id(last: object) -> None:
    pages = [Page([GUILD, last], TRACE)]
    platform = Platform({("GET", "/users/@me/guilds"): pages})

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="无法继续翻页") as caught:
            [guild async for guild in client.guilds.iter_guilds()]

    assert caught.value.trace_id == "trace-1"


async def test_get_guild() -> None:
    platform = Platform({("GET", "/guilds/g%2F1"): GUILD})

    async with client_for(platform) as client:
        guild = await client.guilds.get("g/1")

    assert platform.requests == [("GET", "/guilds/g%2F1", {}, None)]
    assert guild.name == "读书分享会"
    assert guild.member_count == 6


# ---- 子频道 ----


@pytest.mark.parametrize("body", [[CHANNEL], {"channels": [CHANNEL]}])
async def test_list_channels_accepts_both_documented_shapes(body: object) -> None:
    platform = Platform({("GET", "/guilds/g1/channels"): body})

    async with client_for(platform) as client:
        channels = await client.guilds.list_channels("g1")

    assert platform.requests == [("GET", "/guilds/g1/channels", {}, None)]
    assert [channel.id for channel in channels] == ["123456"]
    assert channels[0].type == pyqbot.ChannelType.TEXT
    assert channels[0].speak_permission == pyqbot.SpeakPermission.EVERYONE


async def test_create_channel_sends_only_the_given_fields() -> None:
    platform = Platform({("POST", "/guilds/g1/channels"): {**CHANNEL, "name": "公告区"}})

    async with client_for(platform) as client:
        minimal = await client.guilds.create_channel("g1", "公告区")
        await client.guilds.create_channel(
            "g1",
            "开黑房",
            type=pyqbot.ChannelType.VOICE,
            sub_type=pyqbot.ChannelSubType.GAMING,
            position=4,
            parent_id="0",
            private_type=pyqbot.PrivateType.ADMINS_AND_MEMBERS,
            private_user_ids="u1",
            speak_permission=pyqbot.SpeakPermission.ADMINS_AND_MEMBERS,
            application_id="1000000",
        )

    assert minimal.name == "公告区"
    assert [body for *_, body in platform.requests] == [
        {"name": "公告区", "type": 0},
        {
            "name": "开黑房",
            "type": 2,
            "sub_type": 3,
            "position": 4,
            "parent_id": "0",
            "private_type": 2,
            "private_user_ids": ["u1"],
            "speak_permission": 2,
            "application_id": "1000000",
        },
    ]


async def test_get_update_and_delete_channel() -> None:
    renamed = {**CHANNEL, "name": "公告区（已改名）", "position": 5}
    platform = Platform(
        {
            ("GET", "/channels/123456"): CHANNEL,
            ("PATCH", "/channels/123456"): renamed,
            ("DELETE", "/channels/123456"): {},
        }
    )

    async with client_for(platform) as client:
        channel = await client.channels.get("123456")
        updated = await client.channels.update(
            "123456",
            name="公告区（已改名）",
            position=5,
            parent_id="0",
            private_type=pyqbot.PrivateType.PUBLIC,
            speak_permission=pyqbot.SpeakPermission.EVERYONE,
        )
        await client.channels.delete("123456")

    assert channel.permissions == "0"
    assert updated.position == 5
    assert platform.requests == [
        ("GET", "/channels/123456", {}, None),
        (
            "PATCH",
            "/channels/123456",
            {},
            {
                "name": "公告区（已改名）",
                "position": 5,
                "parent_id": "0",
                "private_type": 0,
                "speak_permission": 1,
            },
        ),
        ("DELETE", "/channels/123456", {}, None),
    ]


async def test_update_channel_without_changes_is_rejected_locally() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match="至少"):
            await client.channels.update("123456")

    assert platform.requests == []


@pytest.mark.parametrize(("body", "expected"), [({"online_nums": 3}, 3), ({}, 0)])
async def test_online_nums_treats_an_empty_object_as_zero(body: object, expected: int) -> None:
    platform = Platform({("GET", "/channels/c1/online_nums"): body})

    async with client_for(platform) as client:
        assert await client.channels.get_online_nums("c1") == expected

    assert platform.requests == [("GET", "/channels/c1/online_nums", {}, None)]


# ---- 子频道权限 ----


async def test_channel_permissions_are_decoded_into_flags() -> None:
    platform = Platform(
        {
            ("GET", "/channels/c1/members/u1/permissions"): {
                "channel_id": "c1",
                "user_id": "u1",
                "permissions": "4",
            },
            ("GET", "/channels/c1/roles/r1/permissions"): {
                "channel_id": "c1",
                "role_id": "r1",
                "permissions": "69",  # 1 | 4 | 64：64 是文档里没有的位
            },
        }
    )

    async with client_for(platform) as client:
        member_permissions = await client.channels.get_member_permissions("c1", "u1")
        role_permissions = await client.channels.get_role_permissions("c1", "r1")

    assert member_permissions == pyqbot.ChannelPermission.SPEAK
    assert pyqbot.ChannelPermission.VIEW in role_permissions
    assert int(role_permissions) == 69


@pytest.mark.parametrize("permissions", ["-1", "abc", 4, None, "9" * 5000])
async def test_unrecognised_permissions_are_an_api_error(permissions: object) -> None:
    body = {"channel_id": "c1", "permissions": permissions}
    platform = Platform({("GET", "/channels/c1/members/u1/permissions"): body})

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="响应无法识别"):
            await client.channels.get_member_permissions("c1", "u1")


async def test_update_permissions_sends_decimal_strings() -> None:
    platform = Platform()
    flags = pyqbot.ChannelPermission

    async with client_for(platform) as client:
        await client.channels.update_member_permissions(
            "c1", "u1", add=flags.VIEW | flags.SPEAK, remove=flags.MANAGE
        )
        await client.channels.update_role_permissions("c1", "r1", remove=flags.SPEAK)

    assert platform.requests == [
        ("PUT", "/channels/c1/members/u1/permissions", {}, {"add": "5", "remove": "2"}),
        ("PUT", "/channels/c1/roles/r1/permissions", {}, {"add": "0", "remove": "4"}),
    ]


# ---- 成员 ----


async def test_iter_members_drops_repeats_of_the_previous_page() -> None:
    pages = [
        Page([member("1"), member("2")]),
        Page([member("2"), member("3")]),  # 2 是上一页返回过的
        Page([member("3")]),  # 只剩重复的成员：锚点不变，结束
    ]
    platform = Platform({("GET", "/guilds/g1/members"): pages})

    async with client_for(platform) as client:
        members = [m async for m in client.guilds.iter_members("g1", limit=2)]

    assert [m.user.id for m in members if m.user] == ["1", "2", "3"]
    assert [params for _, _, params, _ in platform.requests] == [
        {"limit": "2"},
        {"limit": "2", "after": "2"},
        {"limit": "2", "after": "3"},
    ]


async def test_iter_members_skips_members_without_a_user_id() -> None:
    pages = [
        Page({"members": [{"nick": "坏记录"}, member("1"), {"user": {"id": ""}}, member("2")]}),
        Page([]),
    ]
    platform = Platform({("GET", "/guilds/g1/members"): pages})

    async with client_for(platform) as client:
        members = [m async for m in client.guilds.iter_members("g1")]

    assert [m.user.id for m in members if m.user] == ["1", "2"]
    assert [params for _, _, params, _ in platform.requests] == [
        {"limit": "400"},
        {"limit": "400", "after": "2"},
    ]


@pytest.mark.parametrize(
    "last", [{"nick": "坏记录"}, {"user": {"username": "x"}}, {"user": {"id": ""}}, "oops"]
)
async def test_iter_members_fails_when_the_last_member_has_no_user_id(last: object) -> None:
    pages = [Page([member("1"), last], TRACE)]
    platform = Platform({("GET", "/guilds/g1/members"): pages})

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="无法继续翻页") as caught:
            [m async for m in client.guilds.iter_members("g1")]

    assert caught.value.status_code == 200
    assert caught.value.trace_id == "trace-1"


async def test_get_member() -> None:
    platform = Platform({("GET", "/guilds/g1/members/u1"): member("u1", nick="小明")})

    async with client_for(platform) as client:
        result = await client.guilds.get_member("g1", "u1")

    assert result.nick == "小明"
    assert result.user is not None
    assert result.user.id == "u1"
    assert result.roles == ("1",)


async def test_remove_member_sends_the_body_with_delete() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        await client.guilds.remove_member("g1", "u1")
        await client.guilds.remove_member(
            "g1", "u2", add_blacklist=True, recall=pyqbot.RecallDays.ALL
        )

    assert platform.requests == [
        (
            "DELETE",
            "/guilds/g1/members/u1",
            {},
            {"add_blacklist": False, "delete_history_msg_days": 0},
        ),
        (
            "DELETE",
            "/guilds/g1/members/u2",
            {},
            {"add_blacklist": True, "delete_history_msg_days": -1},
        ),
    ]


async def test_iter_role_members_follows_next_until_zero() -> None:
    pages = [
        Page({"data": [member("1")], "next": "100"}),
        Page({"data": [member("2")], "next": "0"}),
    ]
    platform = Platform({("GET", "/guilds/g1/roles/4/members"): pages})

    async with client_for(platform) as client:
        members = [
            m async for m in client.guilds.iter_role_members("g1", pyqbot.DefaultRoleId.OWNER)
        ]

    assert [m.user.id for m in members if m.user] == ["1", "2"]
    assert [params for _, _, params, _ in platform.requests] == [
        {"limit": "400"},
        {"limit": "400", "start_index": "100"},
    ]


async def test_iter_role_members_stops_on_an_empty_page() -> None:
    platform = Platform({("GET", "/guilds/g1/roles/r1/members"): [Page({"data": [], "next": "5"})]})

    async with client_for(platform) as client:
        members = [m async for m in client.guilds.iter_role_members("g1", "r1", limit=10)]

    assert members == []
    assert len(platform.requests) == 1


# ---- 身份组 ----


async def test_list_roles() -> None:
    body = {
        "guild_id": "g1",
        "roles": [
            {"id": "4", "name": "创建者", "color": 4294927682, "hoist": 1, "number": 1},
            {"id": "2", "name": "管理员", "color": 4280276644, "hoist": 1, "number": 5},
        ],
        "role_num_limit": "30",
    }
    platform = Platform({("GET", "/guilds/g1/roles"): body})

    async with client_for(platform) as client:
        roles = await client.guilds.list_roles("g1")

    assert roles.role_num_limit == "30"
    assert [role.id for role in roles.roles] == [
        pyqbot.DefaultRoleId.OWNER,
        pyqbot.DefaultRoleId.ADMIN,
    ]


async def test_create_update_and_delete_role() -> None:
    role = {"id": "10177739", "name": "test", "color": 99999, "hoist": 1, "member_limit": 2000}
    platform = Platform(
        {
            ("POST", "/guilds/g1/roles"): {"role_id": "10177739", "role": role},
            ("PATCH", "/guilds/g1/roles/10177739"): {
                "guild_id": "g1",
                "role_id": "10177739",
                "role": {**role, "name": "改名"},
            },
        }
    )

    async with client_for(platform) as client:
        created = await client.guilds.create_role("g1", name="test", color=99999, hoist=True)
        updated = await client.guilds.update_role("g1", created.id, name="改名", hoist=False)
        await client.guilds.delete_role("g1", created.id)

    assert created.id == "10177739"
    assert updated.name == "改名"
    assert platform.requests == [
        ("POST", "/guilds/g1/roles", {}, {"name": "test", "color": 99999, "hoist": 1}),
        ("PATCH", "/guilds/g1/roles/10177739", {}, {"name": "改名", "hoist": 0}),
        ("DELETE", "/guilds/g1/roles/10177739", {}, None),
    ]


async def test_role_without_any_field_is_rejected_locally() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match="至少"):
            await client.guilds.create_role("g1")
        with pytest.raises(ValueError, match="至少"):
            await client.guilds.update_role("g1", "r1")

    assert platform.requests == []


async def test_member_roles_send_the_channel_only_when_given() -> None:
    platform = Platform()
    admin = pyqbot.DefaultRoleId.CHANNEL_ADMIN

    async with client_for(platform) as client:
        await client.guilds.add_member_role("g1", "u1", "r1")
        await client.guilds.add_member_role("g1", "u1", admin, channel_id="c1")
        await client.guilds.remove_member_role("g1", "u1", admin, channel_id="c1")
        await client.guilds.remove_member_role("g1", "u1", "r1")

    assert platform.requests == [
        ("PUT", "/guilds/g1/members/u1/roles/r1", {}, None),
        ("PUT", "/guilds/g1/members/u1/roles/5", {}, {"channel": {"id": "c1"}}),
        ("DELETE", "/guilds/g1/members/u1/roles/5", {}, {"channel": {"id": "c1"}}),
        ("DELETE", "/guilds/g1/members/u1/roles/r1", {}, None),
    ]


# ---- 禁言 ----


async def test_mute_sends_the_end_timestamp_and_unmute_sends_zero() -> None:
    until = datetime(2022, 1, 11, 16, 0, tzinfo=UTC)
    pages = [Page({}), Page({}), Page({"user_ids": ["u1"]}), Page({})]
    platform = Platform({("PATCH", "/guilds/g1/mute"): pages})

    async with client_for(platform) as client:
        await client.guilds.mute_all("g1", until)
        await client.guilds.unmute_all("g1")
        muted = await client.guilds.mute_members("g1", ["u1", "u2"], until)
        unmuted = await client.guilds.unmute_members("g1", "u1")
        await client.guilds.mute_member("g1", "u3", until)
        await client.guilds.unmute_member("g1", "u3")

    assert muted == ("u1",)
    assert unmuted == ()
    zero = {"mute_end_timestamp": "0", "mute_seconds": "0"}
    assert [(method, path, body) for method, path, _, body in platform.requests] == [
        ("PATCH", "/guilds/g1/mute", {"mute_end_timestamp": "1641916800"}),
        ("PATCH", "/guilds/g1/mute", zero),
        (
            "PATCH",
            "/guilds/g1/mute",
            {"mute_end_timestamp": "1641916800", "user_ids": ["u1", "u2"]},
        ),
        ("PATCH", "/guilds/g1/mute", {**zero, "user_ids": ["u1"]}),
        ("PATCH", "/guilds/g1/members/u3/mute", {"mute_end_timestamp": "1641916800"}),
        ("PATCH", "/guilds/g1/members/u3/mute", zero),
    ]


async def test_mute_rejects_a_naive_time_before_sending() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match="时区"):
            await client.guilds.mute_member("g1", "u1", datetime(2030, 1, 1))

    assert platform.requests == []


NOW = datetime(2022, 1, 11, 15, 50, 0, 500_000, tzinfo=UTC)


def test_unix_seconds_counts_a_duration_from_a_fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pyqbot._api.params.utc_now", lambda: NOW)

    # 15:50:00.5 + 10 分钟 = 16:00:00.5，不足一秒向上取整到 16:00:01。
    assert unix_seconds(timedelta(minutes=10), "until") == "1641916801"


@pytest.mark.parametrize("value", [timedelta(0), timedelta(seconds=-1)])
def test_unix_seconds_rejects_non_positive_durations(value: timedelta) -> None:
    with pytest.raises(ValueError, match="正的时长"):
        unix_seconds(value, "until")


def test_unix_seconds_keeps_the_instant_of_an_aware_datetime() -> None:
    beijing = timezone(timedelta(hours=8))

    assert unix_seconds(datetime(2022, 1, 12, 0, 0, 0, tzinfo=beijing), "x") == "1641916800"
    assert unix_seconds(datetime(2022, 1, 12, 0, 0, 0, 1, tzinfo=beijing), "x") == "1641916801"


def test_str_list_keeps_a_single_string_whole() -> None:
    assert str_list("abc") == ["abc"]
    assert str_list(iter(["a", "b"])) == ["a", "b"]


# ---- 接口权限与消息设置 ----


async def test_list_api_permissions() -> None:
    body = {
        "apis": [
            {
                "path": "/guilds/{guild_id}/members/{user_id}",
                "method": "GET",
                "desc": "获取",
                "auth_status": 0,
            },
            {
                "path": "/channels/{channel_id}/messages",
                "method": "POST",
                "desc": "创建消息",
                "auth_status": 1,
            },
        ]
    }
    platform = Platform({("GET", "/guilds/g1/api_permission"): body})

    async with client_for(platform) as client:
        apis = await client.guilds.list_api_permissions("g1")

    assert [(api.method, api.authorized) for api in apis] == [("GET", False), ("POST", True)]


async def test_request_api_permission() -> None:
    response = {
        "guild_id": "g1",
        "channel_id": "c1",
        "api_identify": {"path": "/guilds/{guild_id}", "method": "GET"},
        "title": "申请授权频道信息接口权限",
        "desc": "显示频道信息",
    }
    platform = Platform({("POST", "/guilds/g1/api_permission/demand"): response})

    async with client_for(platform) as client:
        demand = await client.guilds.request_api_permission(
            "g1", "c1", method="GET", path="/guilds/{guild_id}", desc="显示频道信息"
        )
        await client.guilds.request_api_permission(
            "g1", "c1", method="GET", path="/guilds/{guild_id}"
        )

    assert demand.api_identify == pyqbot.APIIdentify(path="/guilds/{guild_id}", method="GET")
    assert demand.title == "申请授权频道信息接口权限"
    identify = {"path": "/guilds/{guild_id}", "method": "GET"}
    assert [body for *_, body in platform.requests] == [
        {"channel_id": "c1", "api_identify": identify, "desc": "显示频道信息"},
        {"channel_id": "c1", "api_identify": identify},
    ]


@pytest.mark.parametrize(
    ("dm", "push", "expected"),
    [
        (True, False, (True, False)),
        ("true", "FALSE", (True, False)),
        ("1", "0", (True, False)),
        ("maybe", None, (None, None)),
    ],
)
async def test_message_setting_accepts_booleans_and_strings(
    dm: object, push: object, expected: tuple[bool | None, bool | None]
) -> None:
    body = {
        "disable_create_dm": dm,
        "disable_push_msg": push,
        "channel_ids": ["1146313"],
        "channel_push_max_num": 12,
    }
    platform = Platform({("GET", "/guilds/g1/message/setting"): body})

    async with client_for(platform) as client:
        setting = await client.guilds.get_message_setting("g1")

    assert (setting.disable_create_dm, setting.disable_push_msg) == expected
    assert setting.channel_ids == ("1146313",)
    assert setting.channel_push_max_num == 12


# ---- 通用 ----


async def test_platform_errors_become_api_errors_without_the_secret() -> None:
    platform = Platform()
    platform.fallback = httpx2.Response(
        403, json={"code": 11264, "message": f"无权限 {APP_SECRET} {TOKEN}", "trace_id": "t1"}
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await client.guilds.remove_member("g1", "u1")

    error = caught.value
    assert error.status_code == 403
    assert error.err_code == 11264
    assert error.trace_id == "t1"
    assert APP_SECRET not in str(error)
    assert TOKEN not in str(error)


async def test_invalid_path_parameters_are_rejected_locally() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match="guild_id"):
            await client.guilds.get("")
        with pytest.raises(ValueError, match="user_id"):
            await client.guilds.get_member("g1", "..")
        with pytest.raises(ValueError, match="role_id"):
            await client.guilds.delete_role("g1", "")
        with pytest.raises(ValueError, match="channel_id"):
            await client.channels.get(".")
        with pytest.raises(ValueError, match="role_id"):
            await client.channels.get_role_permissions("c1", "")

    assert platform.requests == []
