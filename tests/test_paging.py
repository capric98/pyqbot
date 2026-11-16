"""翻页工具：接口方法只写「怎么取一页」，`paginate()` 负责翻页。"""

import json
from collections.abc import AsyncIterator

import httpx2
import pytest

import pyqbot
from pyqbot._api.paging import Page, paginate
from pyqbot._http import HTTP
from pyqbot._model import Model

# 平台按 cursor 返回的三页成员，模仿 cursor → next_cursor 形式的接口。
PAGES: dict[str | None, object] = {
    None: {"members": [{"openid": "a"}, {"openid": "b"}], "next_cursor": "c1"},
    "c1": {"members": [], "next_cursor": "c2"},
    "c2": {"members": [{"openid": "c"}], "next_cursor": ""},
}


class Member(Model):
    openid: str


class MemberPage(Model):
    members: tuple[Member, ...] = ()
    next_cursor: str | None = None


class Members:
    """一个接口分组的写法示范：`iter_members()` 只描述怎么取一页。"""

    def __init__(self, http: HTTP) -> None:
        self._http = http

    def iter_members(self, group_openid: str, *, limit: int = 2) -> AsyncIterator[Member]:
        async def fetch(cursor: str | None) -> Page[Member, str]:
            params: dict[str, str | int] = {"limit": limit}
            if cursor is not None:
                params["cursor"] = cursor
            path = f"/v2/groups/{group_openid}/members"
            page = await self._http.request("GET", path, type_=MemberPage, params=params)
            return Page(page.members, page.next_cursor)

        return paginate(fetch)


async def test_cursor_pages_are_followed_until_the_last_one() -> None:
    seen: list[dict[str, str]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/app/getAppAccessToken":
            return httpx2.Response(200, json={"access_token": "t", "expires_in": "7200"})
        seen.append(dict(request.url.params))
        return httpx2.Response(200, content=json.dumps(PAGES[request.url.params.get("cursor")]))

    async with (
        httpx2.AsyncClient(transport=httpx2.MockTransport(handle)) as http_client,
        pyqbot.Client("app-id", "app-secret", http_client=http_client) as client,
    ):
        members = Members(client._http)  # pyright: ignore[reportPrivateUsage]  测试里直接接请求层
        got = [member.openid async for member in members.iter_members("g")]

    assert got == ["a", "b", "c"]
    assert seen == [{"limit": "2"}, {"limit": "2", "cursor": "c1"}, {"limit": "2", "cursor": "c2"}]


async def test_nothing_is_fetched_until_iteration_starts_and_stops_when_the_caller_breaks() -> None:
    calls: list[int | None] = []

    async def fetch(offset: int | None) -> Page[int, int]:
        calls.append(offset)
        start = offset or 0
        return Page(range(start, start + 3), start + 3)

    pages = paginate(fetch)
    assert calls == []

    got: list[int] = []
    async for item in pages:
        got.append(item)
        if item == 4:
            break

    assert got == [0, 1, 2, 3, 4]
    assert calls == [None, 3]


@pytest.mark.parametrize("last", [None, "", "same"])
async def test_iteration_ends_without_a_new_cursor(last: str | None) -> None:
    calls: list[str | None] = []

    async def fetch(cursor: str | None) -> Page[str, str]:
        calls.append(cursor)
        if cursor is None:
            return Page(["first"], "same")
        return Page(["second"], last)

    got = [item async for item in paginate(fetch)]

    assert got == ["first", "second"]
    assert calls == [None, "same"]


async def test_errors_from_fetching_a_page_reach_the_caller() -> None:
    async def fetch(cursor: str | None) -> Page[str, str]:
        if cursor is None:
            return Page(["first"], "next")
        raise pyqbot.APIError("GET /x 失败：坏了", status_code=500)

    got: list[str] = []

    async def collect() -> None:
        async for item in paginate(fetch):
            got.append(item)

    with pytest.raises(pyqbot.APIError, match="坏了"):
        await collect()

    assert got == ["first"]
