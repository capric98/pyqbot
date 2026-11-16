"""入群自动审批策略：列出、创建、修改、增删关联群、删除、执行与白名单。"""

import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone

import httpx2
import pytest

import pyqbot

BASE = "/v2/groups/join_approval_strategy"
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


# ---- 列出 ----


async def test_iter_strategies_decodes_the_documented_example_and_follows_the_cursor() -> None:
    pages: dict[str | None, object] = {
        None: {
            "strategies": [
                {
                    "strategy_id": "st_d83eca11e9",
                    "group_openids": [],
                    "group_ids": [],
                    "whitelist_user_count": 2,
                    "is_enable": "on",
                    "expire_at": "2027-08-05T15:30:16+08:00",
                    "created_at": "2026-08-05T15:30:16+08:00",
                    "updated_at": "2026-08-05T15:45:28+08:00",
                },
            ],
            "next_cursor": "c1",
        },
        "c1": {
            "strategies": [
                # 文档写群号是 uint64，示例却是打了码的字符串（docs/errata.md）。
                {
                    "strategy_id": "st_42cc",
                    "group_ids": ["26****763", 26000978],
                    "is_enable": "off",
                },
                {"group_ids": ["没有 strategy_id"]},
            ],
            "next_cursor": "",
        },
    }
    platform = Platform()
    platform.respond = lambda request: httpx2.Response(
        200, json=pages[request.url.params.get("cursor")]
    )

    async with client_for(platform) as client:
        strategies = [s async for s in client.join_strategies.iter_strategies()]

    first, second = strategies
    assert first == pyqbot.JoinStrategy(
        strategy_id="st_d83eca11e9",
        whitelist_user_count=2,
        is_enable=pyqbot.JoinStrategyStatus.ON,
        expire_at=datetime(2027, 8, 5, 15, 30, 16, tzinfo=CST),
        created_at=datetime(2026, 8, 5, 15, 30, 16, tzinfo=CST),
        updated_at=datetime(2026, 8, 5, 15, 45, 28, tzinfo=CST),
    )
    assert first.enabled is True
    assert first.to_dict()["is_enable"] == "on"
    assert second.group_ids == ("26****763", 26000978)
    assert second.enabled is False
    assert platform.requests() == [
        ("GET", BASE, {"limit": "50"}, None),
        ("GET", BASE, {"limit": "50", "cursor": "c1"}, None),
    ]


async def test_enabled_is_none_when_missing_or_unknown() -> None:
    page = {"strategies": [{"strategy_id": "s", "is_enable": "paused"}, {"strategy_id": "t"}]}

    async with client_for(Platform(page)) as client:
        unknown, missing = [s async for s in client.join_strategies.iter_strategies()]

    assert unknown.is_enable == "paused"
    assert isinstance(unknown.is_enable, pyqbot.JoinStrategyStatus)
    assert unknown.enabled is None
    assert missing.enabled is None
    assert (
        pyqbot.JoinStrategy(strategy_id="s", is_enable=pyqbot.JoinStrategyStatus.OFF).enabled
        is False
    )


# ---- 创建 ----


async def test_create_with_group_openids_and_defaults() -> None:
    platform = Platform(
        {
            "strategy_id": "st_d83eca11e9",
            "is_enable": "on",
            "expire_at": "2027-08-05T15:30:16+08:00",
        }
    )

    async with client_for(platform) as client:
        strategy = await client.join_strategies.create(group_openids=["g1", "g2"])

    assert strategy.strategy_id == "st_d83eca11e9"
    assert strategy.enabled is True
    assert strategy.expire_at == datetime(2027, 8, 5, 15, 30, 16, tzinfo=CST)
    # 不传 expire_at 就不发，由平台按默认一年处理。
    assert platform.requests() == [
        ("POST", BASE, {}, {"group_openids": ["g1", "g2"], "is_enable": "on"})
    ]


async def test_create_with_group_ids_and_every_option() -> None:
    platform = Platform({"strategy_id": "st_1"})
    expire_at = datetime(2027, 1, 1, tzinfo=UTC)

    async with client_for(platform) as client:
        await client.join_strategies.create(
            group_ids=[123456789, 987654321], enabled=False, expire_at=expire_at, remark="测试"
        )
        await client.join_strategies.create(group_ids=123, group_openids=None)
        await client.join_strategies.create(group_openids="g1")

    assert [body for *_, body in platform.requests()] == [
        {
            "group_ids": [123456789, 987654321],
            "is_enable": "off",
            "expire_at": "2027-01-01T00:00:00+00:00",
            "remark": "测试",
        },
        {"group_ids": [123], "is_enable": "on"},
        {"group_openids": ["g1"], "is_enable": "on"},
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "必须且只能传一个"),
        ({"group_openids": ["g"], "group_ids": [1]}, "必须且只能传一个"),
        ({"group_openids": ["g"], "expire_at": datetime(2027, 1, 1)}, "必须带时区"),
        ({"group_openids": ["g"], "expire_at": timedelta(0)}, "必须是正的时长"),
    ],
)
async def test_invalid_create_arguments_are_rejected_before_sending(
    kwargs: dict[str, object], message: str
) -> None:
    platform = Platform()

    async with client_for(platform) as client:
        with pytest.raises(ValueError, match=message):
            await client.join_strategies.create(**kwargs)  # pyright: ignore[reportArgumentType]

    assert platform.calls == []


async def test_create_failure_is_an_api_error() -> None:
    platform = Platform()
    platform.respond = lambda request: httpx2.Response(
        400, json={"err_code": 1100, "message": "策略数量超过上限", "trace_id": "trace-abc"}
    )

    async with client_for(platform) as client:
        with pytest.raises(pyqbot.APIError, match="策略数量超过上限") as caught:
            await client.join_strategies.create(group_openids="g")

    assert (caught.value.status_code, caught.value.err_code) == (400, 1100)
    assert caught.value.trace_id == "trace-abc"


# ---- 修改 ----


async def test_update_sends_only_what_was_given() -> None:
    platform = Platform({"is_enable": "off", "expire_at": "2027-08-05T15:30:16+08:00"})
    strategy = pyqbot.JoinStrategy(strategy_id="st_2")

    async with client_for(platform) as client:
        await client.join_strategies.update("st_1", enabled=False)
        await client.join_strategies.update(
            strategy, enabled=True, expire_at=datetime(2027, 1, 1, 8, tzinfo=CST), remark="新"
        )
        await client.join_strategies.update("st_1")

    assert platform.requests() == [
        ("PATCH", f"{BASE}/st_1", {}, {"is_enable": "off"}),
        (
            "PATCH",
            f"{BASE}/st_2",
            {},
            {"is_enable": "on", "expire_at": "2027-01-01T00:00:00+00:00", "remark": "新"},
        ),
        ("PATCH", f"{BASE}/st_1", {}, {}),
    ]


async def test_add_and_remove_groups_send_a_group_action() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        await client.join_strategies.add_groups("st_1", group_openids=["aBC"])
        await client.join_strategies.remove_groups("st_1", group_ids=123)
        with pytest.raises(ValueError, match="必须且只能传一个"):
            await client.join_strategies.add_groups("st_1")

    path = f"{BASE}/st_1"
    assert platform.requests() == [
        ("PATCH", path, {}, {"group_action": {"op": "add", "group_openids": ["aBC"]}}),
        ("PATCH", path, {}, {"group_action": {"op": "del", "group_ids": [123]}}),
    ]


# ---- 删除与执行 ----


async def test_delete_and_execute() -> None:
    platform = Platform()

    async with client_for(platform) as client:
        await client.join_strategies.delete("a/b")
        await client.join_strategies.execute(pyqbot.JoinStrategy(strategy_id="st_1"))
        with pytest.raises(ValueError, match="strategy_id"):
            await client.join_strategies.delete("")

    # DELETE 按惯例不发请求体，尽管文档示例带了 {}（docs/errata.md）。
    assert platform.requests() == [
        ("DELETE", f"{BASE}/a%2Fb", {}, None),
        ("POST", f"{BASE}/st_1/execute", {}, {}),
    ]


# ---- 白名单 ----


async def test_whitelist_users_are_sent_as_strings() -> None:
    platform = Platform(
        {
            "strategy_id": "st_1",
            "whitelist_user_count": 2,
            "updated_at": "2026-08-05T15:45:28+08:00",
        }
    )

    async with client_for(platform) as client:
        added = await client.join_strategies.add_whitelist_users("st_1", [1234567, "1234568"])
        await client.join_strategies.add_whitelist_users("st_1", 1234569)
        await client.join_strategies.remove_whitelist_users("st_1", "1234567")

    assert added == pyqbot.WhitelistUpdate(
        strategy_id="st_1",
        whitelist_user_count=2,
        updated_at=datetime(2026, 8, 5, 15, 45, 28, tzinfo=CST),
    )
    path = f"{BASE}/st_1/whitelist_users"
    assert platform.requests() == [
        ("POST", path, {}, {"op": "add", "whitelist_users": ["1234567", "1234568"]}),
        ("POST", path, {}, {"op": "add", "whitelist_users": ["1234569"]}),
        ("POST", path, {}, {"op": "del", "whitelist_users": ["1234567"]}),
    ]
