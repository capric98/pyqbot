"""入群自动审批策略（`autogen/api/v2_groups_join_approval_strategy*`）。"""

from collections.abc import AsyncIterator, Iterable
from datetime import datetime, timedelta

from .._http import HTTP, path_segment
from .._models.group import (
    AddDel,
    JoinStrategy,
    JoinStrategyPage,
    JoinStrategyStatus,
    WhitelistUpdate,
)
from .paging import Page, paginate
from .params import rfc3339, str_list

_BASE = "/v2/groups/join_approval_strategy"
_PAGE_LIMIT = 50  # 文档给出的单页上限


class JoinStrategies:
    """入群自动审批策略，经 `client.join_strategies` 使用。

    策略属于机器人本身：关联若干个群和一份 QQ 号白名单，白名单里的人申请加入这些群时自动通过。
    限制（以平台为准，超出时由平台拒绝）：每个机器人最多 20 个策略，每个策略最多关联 100 个群；
    白名单最多 10 万个号码，单次增删最多 1 万个。只在机器人是群管理员的群里生效。
    """

    def __init__(self, http: HTTP) -> None:
        self._http = http

    def iter_strategies(self) -> AsyncIterator[JoinStrategy]:
        """按创建时间从新到旧列出生效中的策略。

        对应官方接口 `GET /v2/groups/join_approval_strategy`。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            RuntimeError: 客户端已关闭。
        """

        async def fetch(cursor: str | None) -> Page[JoinStrategy, str]:
            params = {"limit": _PAGE_LIMIT} | ({"cursor": cursor} if cursor else {})
            page = await self._http.request("GET", _BASE, type_=JoinStrategyPage, params=params)
            return Page(page.strategies, page.next_cursor)

        return paginate(fetch)

    async def create(
        self,
        *,
        group_openids: str | Iterable[str] | None = None,
        group_ids: int | Iterable[int] | None = None,
        enabled: bool = True,
        expire_at: datetime | timedelta | None = None,
        remark: str | None = None,
    ) -> JoinStrategy:
        """创建一个策略，返回的 `strategy_id` 用于之后的修改、执行与白名单操作。

        对应官方接口 `POST /v2/groups/join_approval_strategy`。

        Args:
            group_openids: 关联的群（`group_openid`）；与 `group_ids` 恰好传一个。
            group_ids: 关联的群（QQ 群号）；之后增删关联群时要用同一种写法。
            enabled: 是否启用。
            expire_at: 过期时间：带时区的 `datetime`，或从现在起算的 `timedelta`；不传默认一年。
            remark: 备注，最多 255 个字。

        Raises:
            APIError: 平台拒绝，例如策略数已达上限。
            NetworkError: 没有拿到平台的响应。
            ValueError: `group_openids` 与 `group_ids` 不是恰好传了一个，或 `expire_at` 不合法
                （同 `client.groups.mute_members()` 的 `until`）。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            strategy = await client.join_strategies.create(group_openids=[group_openid])
            await client.join_strategies.add_whitelist_users(strategy, [12345678])
            ```
        """
        body = _groups_body(group_openids, group_ids)
        body["is_enable"] = JoinStrategyStatus.ON if enabled else JoinStrategyStatus.OFF
        if expire_at is not None:
            body["expire_at"] = rfc3339(expire_at, "expire_at")
        if remark is not None:
            body["remark"] = remark
        return await self._http.request("POST", _BASE, type_=JoinStrategy, json=body)

    async def update(
        self,
        strategy: str | JoinStrategy,
        *,
        enabled: bool | None = None,
        expire_at: datetime | timedelta | None = None,
        remark: str | None = None,
    ) -> None:
        """修改策略的启用状态、过期时间或备注；不传的不变。增删关联群用 `add_groups()` / `remove_groups()`。

        对应官方接口 `PATCH /v2/groups/join_approval_strategy/{strategy_id}`。

        Args:
            strategy: 策略或它的 `strategy_id`。
            enabled: 启用或停用。
            expire_at: 新的过期时间，写法同 `create()`。
            remark: 新的备注。

        Raises:
            APIError: 平台拒绝，例如策略不存在。
            NetworkError: 没有拿到平台的响应。
            ValueError: `strategy_id` 为空，或 `expire_at` 不合法。
            RuntimeError: 客户端已关闭。
        """
        body: dict[str, object] = {}
        if enabled is not None:
            body["is_enable"] = JoinStrategyStatus.ON if enabled else JoinStrategyStatus.OFF
        if expire_at is not None:
            body["expire_at"] = rfc3339(expire_at, "expire_at")
        if remark is not None:
            body["remark"] = remark
        await self._http.request("PATCH", _strategy_path(strategy), type_=None, json=body)

    async def add_groups(
        self,
        strategy: str | JoinStrategy,
        *,
        group_openids: str | Iterable[str] | None = None,
        group_ids: int | Iterable[int] | None = None,
    ) -> None:
        """给策略增加关联群，写法（`group_openids` 或 `group_ids`）须与创建时一致。

        对应官方接口 `PATCH /v2/groups/join_approval_strategy/{strategy_id}`（`group_action.op` 为 `add`）。

        Raises:
            APIError: 平台拒绝，例如写法与创建时不一致。
            NetworkError: 没有拿到平台的响应。
            ValueError: `strategy_id` 为空，或 `group_openids` 与 `group_ids` 不是恰好传了一个。
            RuntimeError: 客户端已关闭。
        """
        await self._edit_groups(strategy, AddDel.ADD, group_openids, group_ids)

    async def remove_groups(
        self,
        strategy: str | JoinStrategy,
        *,
        group_openids: str | Iterable[str] | None = None,
        group_ids: int | Iterable[int] | None = None,
    ) -> None:
        """从策略移除关联群，写法同 `add_groups()`。

        对应官方接口 `PATCH /v2/groups/join_approval_strategy/{strategy_id}`（`group_action.op` 为 `del`）。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `strategy_id` 为空，或 `group_openids` 与 `group_ids` 不是恰好传了一个。
            RuntimeError: 客户端已关闭。
        """
        await self._edit_groups(strategy, AddDel.DEL, group_openids, group_ids)

    async def _edit_groups(
        self,
        strategy: str | JoinStrategy,
        op: AddDel,
        group_openids: str | Iterable[str] | None,
        group_ids: int | Iterable[int] | None,
    ) -> None:
        path = _strategy_path(strategy)
        action = {"op": op} | _groups_body(group_openids, group_ids)
        await self._http.request("PATCH", path, type_=None, json={"group_action": action})

    async def delete(self, strategy: str | JoinStrategy) -> None:
        """删除策略。

        对应官方接口 `DELETE /v2/groups/join_approval_strategy/{strategy_id}`。

        Raises:
            APIError: 平台拒绝，例如策略不存在。
            NetworkError: 没有拿到平台的响应。
            ValueError: `strategy_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        await self._http.request("DELETE", _strategy_path(strategy), type_=None)

    async def execute(self, strategy: str | JoinStrategy) -> None:
        """立即扫描策略关联的全部群，通过白名单号码的入群申请。异步执行，约 10 分钟完成。

        对应官方接口 `POST /v2/groups/join_approval_strategy/{strategy_id}/execute`。

        Raises:
            APIError: 平台拒绝，例如策略不存在。
            NetworkError: 没有拿到平台的响应。
            ValueError: `strategy_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        path = f"{_strategy_path(strategy)}/execute"
        await self._http.request("POST", path, type_=None, json={})

    async def add_whitelist_users(
        self, strategy: str | JoinStrategy, users: int | str | Iterable[int | str]
    ) -> WhitelistUpdate:
        """往策略的白名单里加 QQ 号，返回 `WhitelistUpdate`（含平台估算的号码数）。

        对应官方接口 `POST /v2/groups/join_approval_strategy/{strategy_id}/whitelist_users`
        （`op` 为 `add`）。

        Args:
            strategy: 策略或它的 `strategy_id`。
            users: 一个或多个 QQ 号（整数或字符串），单次最多 1 万个（超出由平台拒绝）。

        Raises:
            APIError: 平台拒绝，例如号码数超过上限。
            NetworkError: 没有拿到平台的响应。
            ValueError: `strategy_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        return await self._edit_whitelist(strategy, AddDel.ADD, users)

    async def remove_whitelist_users(
        self, strategy: str | JoinStrategy, users: int | str | Iterable[int | str]
    ) -> WhitelistUpdate:
        """从策略的白名单里删 QQ 号，返回 `WhitelistUpdate`（含平台估算的号码数）；参数同 `add_whitelist_users()`。

        对应官方接口 `POST /v2/groups/join_approval_strategy/{strategy_id}/whitelist_users`
        （`op` 为 `del`）。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `strategy_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        return await self._edit_whitelist(strategy, AddDel.DEL, users)

    async def _edit_whitelist(
        self, strategy: str | JoinStrategy, op: AddDel, users: int | str | Iterable[int | str]
    ) -> WhitelistUpdate:
        # 文档要求号码用字符串，避免 JS 的整数精度问题。
        numbers = [str(users)] if isinstance(users, int | str) else [str(user) for user in users]
        return await self._http.request(
            "POST",
            f"{_strategy_path(strategy)}/whitelist_users",
            type_=WhitelistUpdate,
            json={"op": op, "whitelist_users": numbers},
        )


def _strategy_path(strategy: str | JoinStrategy) -> str:
    strategy_id = strategy if isinstance(strategy, str) else strategy.strategy_id
    return f"{_BASE}/{path_segment(strategy_id, 'strategy_id')}"


def _groups_body(
    group_openids: str | Iterable[str] | None, group_ids: int | Iterable[int] | None
) -> dict[str, object]:
    """关联群的两种写法，恰好一种。

    Raises:
        ValueError: 两个都传了或都没传。
    """
    if group_openids is not None and group_ids is None:
        return {"group_openids": str_list(group_openids)}
    if group_ids is not None and group_openids is None:
        return {"group_ids": [group_ids] if isinstance(group_ids, int) else list(group_ids)}
    raise ValueError("group_openids 与 group_ids 必须且只能传一个")
