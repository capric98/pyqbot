"""指令面板接口。"""

from collections.abc import AsyncIterator, Iterable

from .._http import HTTP, path_segment
from .._models.panel import (
    PanelCreated,
    PanelDetail,
    PanelItem,
    PanelPage,
    PanelRecord,
    PanelScope,
    PanelTargetOp,
    PanelTargetType,
    PanelVersion,
)
from .paging import Page, paginate


class Panels:
    """指令面板，经 `client.panels` 使用。面板按场景生效，可以只关联指定的用户或群。

    改动面板（创建、修改、删除、增删关联对象）会影响看得到它的所有用户。
    """

    def __init__(self, http: HTTP) -> None:
        self._http = http

    def iter_panels(self, scope: PanelScope, *, limit: int = 50) -> AsyncIterator[PanelRecord]:
        """逐个产出 `scope` 场景下生效的面板，按设置时间从新到旧，翻页由 SDK 完成。

        对应官方接口 `GET /v2/panels`（限频 30 次/分钟，每页一次）。

        Args:
            scope: 生效场景。
            limit: 每页条数，最多 50。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            async for record in client.panels.iter_panels(pyqbot.PanelScope.C2C):
                print(record.panel_id, record.items)
            ```
        """

        async def fetch(cursor: str | None) -> Page[PanelRecord, str]:
            params: dict[str, str | int] = {"scope": scope, "limit": limit}
            if cursor:
                params["cursor"] = cursor
            page = await self._http.request("GET", "/v2/panels", type_=PanelPage, params=params)
            return Page(page.records, None if page.is_end else page.next_cursor)

        return paginate(fetch)

    async def create(
        self,
        scope: PanelScope,
        items: Iterable[PanelItem],
        *,
        remark: str | None = None,
        user_openids: Iterable[str] = (),
        group_openids: Iterable[str] = (),
    ) -> str:
        """创建面板，返回面板 ID。一个机器人最多 20 个面板。

        不传 `user_openids` / `group_openids` 时对该场景的所有用户或群生效（`target_type=all`）；
        传了就只对它们生效（`specific`），之后可以用 `add_targets()` / `remove_targets()` 增删。
        数量与长度由平台检查：每个面板最多 20 个元素，每次最多关联 20 个对象。

        对应官方接口 `POST /v2/panels`（限频 10 次/分钟）。

        Args:
            scope: 生效场景。
            items: 面板元素。
            remark: 备注，只给开发者看，最多 255 个字符。
            user_openids: 只对这些用户生效，只能用于 `PanelScope.C2C`。
            group_openids: 只对这些群生效，只能用于 `PanelScope.GROUP`。

        Raises:
            APIError: 平台拒绝，如超出数量（`err_code` 40030013）、内容有安全风险（40030020）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `user_openids` / `group_openids` 与 `scope` 不匹配。
            RuntimeError: 客户端已关闭。

        Example:
            ```python
            panel_id = await client.panels.create(
                pyqbot.PanelScope.C2C,
                [pyqbot.PanelItem.command_button("/天气", desc="查询当前天气")],
                user_openids=[openid],
            )
            ```
        """
        targets = _targets(scope, user_openids, group_openids)
        body: dict[str, object] = {
            "scope": scope,
            "target_type": PanelTargetType.SPECIFIC if targets else PanelTargetType.ALL,
            **targets,
            "panel": _panel(items, remark),
        }
        created = await self._http.request("POST", "/v2/panels", type_=PanelCreated, json=body)
        return created.panel_id

    async def get(self, panel_id: str) -> PanelDetail:
        """取面板的详情，含关联的用户或群。

        对应官方接口 `GET /v2/panels/{panel_id}`（限频 30 次/分钟）。

        Raises:
            APIError: 平台拒绝，如面板不存在（`err_code` 40030006）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `panel_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        return await self._http.request("GET", _path(panel_id), type_=PanelDetail)

    async def update(
        self, panel_id: str, items: Iterable[PanelItem], *, remark: str | None = None
    ) -> int | None:
        """用 `items` 与 `remark` 覆盖面板的内容，关联的用户或群不变；返回新的版本号（平台没给时为 `None`）。

        官方说备注也会被覆盖，所以不传 `remark` 时原有备注可能被清空。

        对应官方接口 `PUT /v2/panels/{panel_id}`（限频 10 次/分钟）。

        Raises:
            APIError: 平台拒绝，如面板不存在（`err_code` 40030006）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `panel_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        body = {"panel": _panel(items, remark)}
        result = await self._http.request("PUT", _path(panel_id), type_=PanelVersion, json=body)
        return result.version

    async def delete(self, panel_id: str) -> None:
        """删除面板，它随即对所有用户和群失效。

        对应官方接口 `DELETE /v2/panels/{panel_id}`（限频 10 次/分钟）。

        Raises:
            APIError: 平台拒绝，如面板不存在（`err_code` 40030006）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `panel_id` 为空。
            RuntimeError: 客户端已关闭。
        """
        await self._http.request("DELETE", _path(panel_id), type_=None)

    async def add_targets(
        self,
        panel_id: str,
        *,
        user_openids: Iterable[str] = (),
        group_openids: Iterable[str] = (),
    ) -> None:
        """让面板对更多用户（单聊面板）或群（群聊面板）生效。只能用于 `specific` 面板。

        对应官方接口 `PUT /v2/panels/{panel_id}/target`（`op=add`，限频 60 次/分钟）。

        Args:
            panel_id: 面板 ID。
            user_openids: 要关联的用户，一次最多 20 个。
            group_openids: 要关联的群，一次最多 20 个。

        Raises:
            APIError: 平台拒绝，如面板是全局面板（`err_code` 40030021）、超出数量（40030013）。
            NetworkError: 没有拿到平台的响应。
            ValueError: `panel_id` 为空，或 `user_openids` 与 `group_openids` 没有恰好传一个。
            RuntimeError: 客户端已关闭。
        """
        await self._update_targets(panel_id, PanelTargetOp.ADD, user_openids, group_openids)

    async def remove_targets(
        self,
        panel_id: str,
        *,
        user_openids: Iterable[str] = (),
        group_openids: Iterable[str] = (),
    ) -> None:
        """让面板不再对这些用户或群生效，参数同 `add_targets()`。

        对应官方接口 `PUT /v2/panels/{panel_id}/target`（`op=del`，限频 60 次/分钟）。

        Raises:
            APIError: 平台拒绝。
            NetworkError: 没有拿到平台的响应。
            ValueError: `panel_id` 为空，或 `user_openids` 与 `group_openids` 没有恰好传一个。
            RuntimeError: 客户端已关闭。
        """
        await self._update_targets(panel_id, PanelTargetOp.DEL, user_openids, group_openids)

    async def _update_targets(
        self,
        panel_id: str,
        op: PanelTargetOp,
        user_openids: Iterable[str],
        group_openids: Iterable[str],
    ) -> None:
        users, groups = list(user_openids), list(group_openids)
        if bool(users) == bool(groups):
            raise ValueError("user_openids 与 group_openids 必须恰好传一个，且不能为空")
        body: dict[str, object] = {"op": op}
        body |= {"user_openids": users} if users else {"group_openids": groups}
        await self._http.request("PUT", f"{_path(panel_id)}/target", type_=None, json=body)


def _path(panel_id: str) -> str:
    return f"/v2/panels/{path_segment(panel_id, 'panel_id')}"


def _panel(items: Iterable[PanelItem], remark: str | None) -> dict[str, object]:
    panel: dict[str, object] = {"items": list(items)}
    if remark is not None:
        panel["remark"] = remark
    return panel


def _targets(
    scope: PanelScope, user_openids: Iterable[str], group_openids: Iterable[str]
) -> dict[str, list[str]]:
    """`create()` 的关联对象字段；没有关联对象时为空字典。

    Raises:
        ValueError: 关联对象与 `scope` 不匹配：平台只认 c2c 的用户、group 的群，其余会被忽略。
    """
    users, groups = list(user_openids), list(group_openids)
    if users and scope != PanelScope.C2C:
        raise ValueError(f"user_openids 只能用于 c2c 场景的面板，scope 是 {scope}")
    if groups and scope != PanelScope.GROUP:
        raise ValueError(f"group_openids 只能用于 group 场景的面板，scope 是 {scope}")
    if users:
        return {"user_openids": users}
    if groups:
        return {"group_openids": groups}
    return {}
