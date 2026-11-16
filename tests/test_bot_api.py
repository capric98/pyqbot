"""机器人级接口：机器人自身、分享链接、自定义菜单与指令面板。"""

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx2
import pytest

import pyqbot

APP_SECRET = "secret-value-never-shown"
TOKEN = "access-token-value"

type Request = tuple[str, str, dict[str, str], object]


class Platform:
    """按 `(方法, 路径)` 给出预设的响应，记下除获取 token 以外的每个请求。"""

    def __init__(self, responses: dict[tuple[str, str], object] | None = None) -> None:
        self.requests: list[Request] = []
        self.responses = responses or {}
        self.fallback: httpx2.Response | None = None

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})
        body = json.loads(request.content) if request.content else None
        path = request.url.raw_path.decode().partition("?")[0]
        self.requests.append((request.method, path, dict(request.url.params), body))
        if self.fallback is not None:
            return self.fallback
        return httpx2.Response(200, json=self.responses.get((request.method, path), {}))


@asynccontextmanager
async def client_for(platform: Platform) -> AsyncGenerator[pyqbot.Client]:
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(platform.handle)) as http_client,
        pyqbot.Client("app-id", APP_SECRET, http_client=http_client) as client,
    ):
        yield client


# ---- 机器人自身 ----


async def test_get_me_decodes_the_bot_and_the_fields_only_in_the_example() -> None:
    me = {
        "id": "5777414462219517083",
        "username": "阳光小助手",
        "avatar": "https://thirdqq.qlogo.cn/g?b=oidb",
        "bot": True,
        "union_openid": "9F2E",
        "union_user_account": "",
        "share_url": "https://qun.qq.com/qunpro/robot/qunshare?robot_uin=1",
        "welcome_msg": "欢迎",
        "unknown_future_field": 1,
    }
    platform = Platform({("GET", "/users/@me"): me})

    async with client_for(platform) as client:
        bot = await client.get_me()

    assert platform.requests == [("GET", "/users/@me", {}, None)]
    assert bot.id == "5777414462219517083"
    assert bot.username == "阳光小助手"
    assert bot.bot is True
    assert bot.share_url == "https://qun.qq.com/qunpro/robot/qunshare?robot_uin=1"
    assert bot.welcome_msg == "欢迎"
    assert bot.union_user_account == ""


async def test_share_link_sends_callback_data_only_when_given() -> None:
    link = {"data": {"url": "https://qun.qq.com/qunpro/robot/qunshare?data=x"}}
    platform = Platform({("POST", "/v2/generate_url_link"): link})

    async with client_for(platform) as client:
        with_data = await client.generate_share_link(callback_data="from_web")
        without = await client.generate_share_link()

    assert with_data == without == "https://qun.qq.com/qunpro/robot/qunshare?data=x"
    assert platform.requests == [
        ("POST", "/v2/generate_url_link", {}, {"callback_data": "from_web"}),
        ("POST", "/v2/generate_url_link", {}, {}),
    ]


async def test_share_link_without_url_is_an_unrecognised_response() -> None:
    platform = Platform({("POST", "/v2/generate_url_link"): {"data": {}}})

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="响应无法识别"):
            await client.generate_share_link()


# ---- 自定义菜单 ----


MENU_RESPONSE = {
    "menu": {
        "items": [
            {"type": "send_message", "name": "帮助", "send_message": "/help"},
            {"type": "switch", "name": "搜索", "switch": {"switch_id": "search", "default": True}},
            {
                "type": "menu",
                "name": "更多",
                "sub_menu_items": [{"type": "link", "name": "官网", "link": "https://a"}],
            },
            {"type": "future_type", "name": "新类型"},
        ]
    },
    "version": 3,
}


async def test_menu_is_decoded_and_tolerates_unknown_button_types() -> None:
    platform = Platform({("GET", "/v2/menu"): MENU_RESPONSE})

    async with client_for(platform) as client:
        current = await client.menu.get()

    assert platform.requests == [("GET", "/v2/menu", {}, None)]
    assert current.version == 3
    help_, switch, more, future = current.items
    assert help_ == pyqbot.MenuItem.message_button("帮助", "/help")
    assert switch == pyqbot.MenuItem.switch_button("搜索", "search", default=True)
    assert more.sub_menu_items == (pyqbot.SubMenuItem.link_button("官网", "https://a"),)
    assert future.type is not None
    assert future.type.name == "UNKNOWN"
    assert future.type == "future_type"


async def test_menu_that_was_never_set_has_no_items() -> None:
    platform = Platform({("GET", "/v2/menu"): {"version": 0}})

    async with client_for(platform) as client:
        current = await client.menu.get()

    assert current.menu is None
    assert current.items == ()


async def test_set_menu_overwrites_it_with_the_factories_output() -> None:
    platform = Platform({("PUT", "/v2/menu"): {"version": 4}})

    async with client_for(platform) as client:
        version = await client.menu.set(
            [
                pyqbot.MenuItem.message_button("帮助", "/help"),
                pyqbot.MenuItem.link_button("官网", "https://example.com"),
                pyqbot.MenuItem.switch_button("搜索", "search"),
                pyqbot.MenuItem.submenu(
                    "更多",
                    pyqbot.SubMenuItem.message_button("设置", "/settings"),
                    pyqbot.SubMenuItem.link_button("文档", "https://example.com/doc"),
                ),
            ]
        )

    assert version == 4
    assert platform.requests == [
        (
            "PUT",
            "/v2/menu",
            {},
            {
                "menu": {
                    "items": [
                        {"name": "帮助", "type": "send_message", "send_message": "/help"},
                        {"name": "官网", "type": "link", "link": "https://example.com"},
                        {
                            "name": "搜索",
                            "type": "switch",
                            "switch": {"switch_id": "search", "default": False},
                        },
                        {
                            "name": "更多",
                            "type": "menu",
                            "sub_menu_items": [
                                {
                                    "name": "设置",
                                    "type": "send_message",
                                    "send_message": "/settings",
                                },
                                {"name": "文档", "type": "link", "link": "https://example.com/doc"},
                            ],
                        },
                    ]
                }
            },
        )
    ]


async def test_menu_read_back_can_be_set_again_and_an_empty_menu_is_sent_as_such() -> None:
    platform = Platform({("GET", "/v2/menu"): MENU_RESPONSE})

    async with client_for(platform) as client:
        current = await client.menu.get()
        assert await client.menu.set(current.items) is None  # 平台没给 version
        await client.menu.set([])

    assert platform.requests[1][3] == {"menu": MENU_RESPONSE["menu"]}
    assert platform.requests[2][3] == {"menu": {"items": []}}


# ---- 指令面板 ----


RECORD = {
    "panel_id": "p_1",
    "scope": "c2c",
    "target_type": "all",
    "panel": {"items": [{"type": "command", "name": "查询天气", "desc": "查询当前天气"}]},
    "created_at": "2024-01-15T10:30:00Z",
    "version": 1,
}


async def test_iter_panels_follows_next_cursor_until_is_end() -> None:
    pages = {
        None: {"records": [RECORD], "next_cursor": "c1", "is_end": False},
        "c1": {"records": [RECORD | {"panel_id": "p_2"}], "next_cursor": "c2", "is_end": True},
    }

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": TOKEN, "expires_in": "7200"})
        seen.append(dict(request.url.params))
        return httpx2.Response(200, json=pages[request.url.params.get("cursor")])

    seen: list[dict[str, str]] = []
    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(handle)) as http_client,
        pyqbot.Client("app-id", APP_SECRET, http_client=http_client) as client,
    ):
        records = [r async for r in client.panels.iter_panels(pyqbot.PanelScope.C2C, limit=1)]

    assert [r.panel_id for r in records] == ["p_1", "p_2"]
    assert seen == [
        {"scope": "c2c", "limit": "1"},
        {"scope": "c2c", "limit": "1", "cursor": "c1"},
    ]
    first = records[0]
    assert first.scope == pyqbot.PanelScope.C2C
    assert first.target_type == pyqbot.PanelTargetType.ALL
    assert first.created_at == datetime(2024, 1, 15, 10, 30, tzinfo=UTC)
    assert first.items == (pyqbot.PanelItem.command_button("查询天气", desc="查询当前天气"),)


async def test_iter_panels_stops_on_an_empty_cursor_even_without_is_end() -> None:
    platform = Platform({("GET", "/v2/panels"): {"records": [RECORD], "next_cursor": ""}})

    async with client_for(platform) as client:
        records = [r async for r in client.panels.iter_panels(pyqbot.PanelScope.GROUP)]

    assert len(records) == 1
    assert platform.requests == [("GET", "/v2/panels", {"scope": "group", "limit": "50"}, None)]


async def test_create_global_panel() -> None:
    platform = Platform({("POST", "/v2/panels"): {"panel_id": "p_new"}})

    async with client_for(platform) as client:
        panel_id = await client.panels.create(
            pyqbot.PanelScope.C2C,
            [
                pyqbot.PanelItem.command_button("查询天气", desc="查询当前天气"),
                pyqbot.PanelItem.link_button("更多服务", "https://example.com", only_admin=True),
            ],
            remark="C2C面板",
        )

    assert panel_id == "p_new"
    assert platform.requests == [
        (
            "POST",
            "/v2/panels",
            {},
            {
                "scope": "c2c",
                "target_type": "all",
                "panel": {
                    "items": [
                        {"name": "查询天气", "desc": "查询当前天气", "type": "command"},
                        {
                            "name": "更多服务",
                            "type": "link",
                            "only_admin": True,
                            "link": "https://example.com",
                        },
                    ],
                    "remark": "C2C面板",
                },
            },
        )
    ]


async def test_create_with_targets_is_specific() -> None:
    platform = Platform({("POST", "/v2/panels"): {"panel_id": "p_new"}})
    item = pyqbot.PanelItem.command_button("群签到")

    async with client_for(platform) as client:
        await client.panels.create(pyqbot.PanelScope.GROUP, [item], group_openids=["g1", "g2"])
        await client.panels.create(pyqbot.PanelScope.C2C, [item], user_openids=iter(["u1"]))

    assert [body for *_, body in platform.requests] == [
        {
            "scope": "group",
            "target_type": "specific",
            "group_openids": ["g1", "g2"],
            "panel": {"items": [{"name": "群签到", "type": "command"}]},
        },
        {
            "scope": "c2c",
            "target_type": "specific",
            "user_openids": ["u1"],
            "panel": {"items": [{"name": "群签到", "type": "command"}]},
        },
    ]


async def test_a_single_string_is_one_openid() -> None:
    platform = Platform({("POST", "/v2/panels"): {"panel_id": "p_new"}})
    item = pyqbot.PanelItem.command_button("群签到")

    async with client_for(platform) as client:
        await client.panels.create(pyqbot.PanelScope.GROUP, [item], group_openids="g123")
        await client.panels.add_targets("p_1", user_openids="u123")
        await client.panels.remove_targets("p_1", group_openids="g123")

    bodies = [body for *_, body in platform.requests]
    assert isinstance(bodies[0], dict)
    assert bodies[0]["group_openids"] == ["g123"]
    assert bodies[1:] == [
        {"op": "add", "user_openids": ["u123"]},
        {"op": "del", "group_openids": ["g123"]},
    ]


@pytest.mark.parametrize(
    ("scope", "users", "groups", "match"),
    [
        (pyqbot.PanelScope.GROUP, ["u"], [], "user_openids 只能用于 c2c"),
        (pyqbot.PanelScope.DM, ["u"], [], "user_openids 只能用于 c2c"),
        (pyqbot.PanelScope.C2C, [], ["g"], "group_openids 只能用于 group"),
        (pyqbot.PanelScope.CHANNEL, [], ["g"], "group_openids 只能用于 group"),
        (pyqbot.PanelScope.C2C, ["u"], ["g"], "group_openids 只能用于 group"),
    ],
)
async def test_create_rejects_targets_that_do_not_match_the_scope(
    scope: pyqbot.PanelScope, users: list[str], groups: list[str], match: str
) -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match=match):
            await client.panels.create(scope, [], user_openids=users, group_openids=groups)

    assert platform.requests == []


async def test_get_panel_detail_includes_its_targets() -> None:
    detail = RECORD | {"target_type": "specific", "user_openids": ["u1"], "group_openids": []}
    platform = Platform({("GET", "/v2/panels/p%2F1"): detail})

    async with client_for(platform) as client:
        panel = await client.panels.get("p/1")

    assert platform.requests == [("GET", "/v2/panels/p%2F1", {}, None)]
    assert panel.panel_id == "p_1"
    assert panel.target_type == pyqbot.PanelTargetType.SPECIFIC
    assert panel.user_openids == ("u1",)
    assert panel.group_openids == ()


async def test_panel_record_without_panel_has_no_items() -> None:
    platform = Platform({("GET", "/v2/panels/p_1"): {"panel_id": "p_1"}})

    async with client_for(platform) as client:
        panel = await client.panels.get("p_1")

    assert panel.items == ()


async def test_set_overwrites_items_and_remark() -> None:
    platform = Platform({("PUT", "/v2/panels/p_1"): {"version": 2}})
    item = pyqbot.PanelItem.command_button("新指令", desc="更新后的指令")

    async with client_for(platform) as client:
        assert await client.panels.set("p_1", [item], remark="更新备注") == 2
        assert await client.panels.set("p_1", []) == 2

    assert [body for *_, body in platform.requests] == [
        {
            "panel": {
                "items": [{"name": "新指令", "desc": "更新后的指令", "type": "command"}],
                "remark": "更新备注",
            }
        },
        {"panel": {"items": []}},
    ]


async def test_delete_panel_ignores_the_response_body() -> None:
    platform = Platform()
    platform.fallback = httpx2.Response(200, json={"unexpected": True})

    async with client_for(platform) as client:
        assert await client.panels.delete("p_1") is None

    assert platform.requests == [("DELETE", "/v2/panels/p_1", {}, None)]


async def test_add_and_remove_targets() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        await client.panels.add_targets("p_1", group_openids=["g3"])
        await client.panels.remove_targets("p_1", user_openids=("u1", "u2"))

    assert platform.requests == [
        ("PUT", "/v2/panels/p_1/target", {}, {"op": "add", "group_openids": ["g3"]}),
        ("PUT", "/v2/panels/p_1/target", {}, {"op": "del", "user_openids": ["u1", "u2"]}),
    ]


@pytest.mark.parametrize(
    "arguments",
    [{}, {"user_openids": []}, {"user_openids": ["u"], "group_openids": ["g"]}],
    ids=["none", "empty", "both"],
)
async def test_targets_need_exactly_one_non_empty_list(arguments: dict[str, list[str]]) -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match="必须恰好传一个"):
            await client.panels.add_targets("p_1", **arguments)

    assert platform.requests == []


async def test_panel_id_must_not_be_empty() -> None:
    async with client_for(Platform()) as client:
        with pytest.raises(ValueError, match="panel_id 不合法"):
            await client.panels.delete("")


# ---- 失败映射 ----


type Call = Callable[[pyqbot.Client], Awaitable[object]]


async def _first_panel(client: pyqbot.Client) -> object:
    return [r async for r in client.panels.iter_panels(pyqbot.PanelScope.C2C)]


CALLS: dict[str, Call] = {
    "GET /users/@me": lambda c: c.get_me(),
    "POST /v2/generate_url_link": lambda c: c.generate_share_link(),
    "GET /v2/menu": lambda c: c.menu.get(),
    "PUT /v2/menu": lambda c: c.menu.set([]),
    "GET /v2/panels": _first_panel,
    "POST /v2/panels": lambda c: c.panels.create(pyqbot.PanelScope.C2C, []),
    "GET /v2/panels/p": lambda c: c.panels.get("p"),
    "PUT /v2/panels/p": lambda c: c.panels.set("p", []),
    "DELETE /v2/panels/p": lambda c: c.panels.delete("p"),
    "PUT /v2/panels/p/target": lambda c: c.panels.add_targets("p", user_openids=["u"]),
}


@pytest.mark.parametrize("action", CALLS)
async def test_platform_errors_become_api_errors_without_credentials(action: str) -> None:
    platform = Platform()
    platform.fallback = httpx2.Response(
        400,
        json={
            "err_code": 40030013,
            "message": f"超出数量限制 {APP_SECRET} {TOKEN}",
            "trace_id": "tr",
        },
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError) as caught:
            await CALLS[action](client)

    assert caught.value.err_code == 40030013
    assert caught.value.trace_id == "tr"
    assert f"{action} 失败：超出数量限制" in str(caught.value)
    assert APP_SECRET not in str(caught.value)
    assert TOKEN not in str(caught.value)
