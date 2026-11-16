"""群管理与入群自动审批策略的实测。运行前须用户提供测试群，每次都要同意，群管理每项单独同意。

每个用例都要求环境变量 `TEST_GROUP_OPENID`（用户提供的测试群，机器人在群里；可由
`test_live_events.py::test_group_add_robot` 取得），没有就 skip。多数接口是内邀能力或仅限白名单机器人（实测 `err_code` 40012010），
禁言与入群申请要求机器人是群管理员（40011030）；不满足时用例以 `APIError` 失败，失败本身也是要记下的结论。

只读用例（群信息、机器人状态、成员、黑名单、禁言状态、入群申请、策略列表）只要 `TEST_GROUP_OPENID`。
会改动群或机器人配置的用例另要 `LIVE_GROUP_WRITE=1`，各自还要下面注明的环境变量。
运行方式 `uv run --env-file .env pytest -m live --no-cov tests/live/test_live_groups.py`。
确认 `docs/errata.md` 里与群管理有关的待实测项。
"""

import logging
import os
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import pyqbot

pytestmark = pytest.mark.live

_logger = logging.getLogger("pyqbot.live")


def note(title: str, value: object) -> None:
    """记下要人核对的结果：WARNING 级别，pytest 默认会显示。"""
    _logger.warning("%s: %r", title, value)


def env(name: str, why: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"缺少环境变量 {name}：{why}")
    return value


@pytest.fixture
def group() -> str:
    return env("TEST_GROUP_OPENID", "须用户提供测试群并单独同意，可能需要白名单")


@pytest.fixture
def write_allowed(group: str) -> str:
    if os.environ.get("LIVE_GROUP_WRITE") != "1":
        pytest.skip("会改动群或机器人配置：须用户单独同意后设 LIVE_GROUP_WRITE=1")
    return group


@pytest.fixture
async def client(app_id: str, app_secret: str) -> AsyncGenerator[pyqbot.Client]:
    async with pyqbot.Client(app_id, app_secret) as client:
        yield client


# ---- 只读 ----


async def test_get_group(client: pyqbot.Client, group: str) -> None:
    """须用户提供测试群并单独同意，可能需要白名单。应看到：打印的群名、人数与客户端里一致。"""
    info = await client.groups.get(group)

    note("群信息", info)
    assert info.group_openid in (None, group)


async def test_get_bot_state(client: pyqbot.Client, group: str) -> None:
    """须用户提供测试群并单独同意，可能需要白名单。

    应看到：`member_role` 与机器人在群里的实际身份一致；顺带确认文档里残缺的示例 JSON 的真实字段。
    """
    state = await client.groups.get_bot_state(group)

    note("机器人状态", state)
    assert state.member_role is not None


async def test_iter_members_and_get_member(client: pyqbot.Client, group: str) -> None:
    """须用户提供测试群并单独同意，可能需要白名单。

    应看到：成员数与 `get()` 的人数一致（超过 30 人时说明 `cursor` 放在查询串里能翻页）；
    第一个成员单独查到的信息与列表里相同。
    """
    members = [member async for member in client.groups.iter_members(group)]
    info = await client.groups.get(group)

    note("成员数 / 群人数", (len(members), info.group_member_num))
    assert members
    assert len({m.member_openid for m in members}) == len(members)  # 翻页没有重复
    assert await client.groups.get_member(group, members[0].member_openid) == members[0]


async def test_get_member_seen_in_a_message(client: pyqbot.Client, group: str) -> None:
    """只读。成员列表没有权限时，用 @ 过机器人的成员（记在 `.cache/live/test_group.env`）查单个成员。"""
    seen = Path(__file__).parents[2] / ".cache" / "live" / "test_group.env"
    prefix = "# @ 机器人的成员："
    lines = seen.read_text(encoding="utf-8").splitlines() if seen.exists() else []
    members = [line.removeprefix(prefix) for line in lines if line.startswith(prefix)]
    if not members:
        pytest.skip("还没有 @ 过机器人的成员：先跑 test_live_events.py::test_group_at_message")
    try:
        note("单个成员", await client.groups.get_member(group, members[-1]))
    except pyqbot.APIError as error:
        note("单个成员：被拒", (error.err_code, error.message))


async def test_iter_blacklist(client: pyqbot.Client, group: str) -> None:
    """须用户提供测试群并单独同意，可能需要白名单。应看到：与群设置里的黑名单一致（可能为空）。"""
    users = [user async for user in client.groups.iter_blacklist(group)]

    note("黑名单", users)


async def test_get_mute_settings(client: pyqbot.Client, group: str) -> None:
    """须用户提供测试群并单独同意，机器人须是管理员。

    应看到：全员禁言的模式与群设置一致；不发请求体的 GET 也能成功（文档示例带了 `{}`）。
    """
    settings = await client.groups.get_mute_settings(group)

    note("禁言状态", settings)
    assert settings.global_rule.mode is not None


async def test_iter_join_requests(client: pyqbot.Client, group: str) -> None:
    """须用户提供测试群并单独同意，机器人须是管理员。应看到：与群里待审批的申请一致（可能为空）。"""
    requests = [request async for request in client.groups.iter_join_requests(group)]

    note("入群申请", requests)


async def test_iter_strategies(client: pyqbot.Client, group: str) -> None:
    """须用户提供测试群并单独同意。应看到：机器人现有的入群自动审批策略（可能为空）。"""
    strategies = [strategy async for strategy in client.join_strategies.iter_strategies()]

    note("策略", strategies)


# ---- 写入 ----


@asynccontextmanager
async def undo_on_failure(undo: Callable[[], Awaitable[object]]) -> AsyncGenerator[None]:
    """块里失败时用 `undo` 恢复测试前的状态；`undo` 自己再失败只记下，不盖住原来的失败。"""
    try:
        yield
    except BaseException:
        try:
            await undo()
        except pyqbot.QQBotError as exc:
            note("清理失败，须人工恢复", exc)
        raise


async def muted_openids(client: pyqbot.Client, group: str) -> set[str]:
    return {m.member_openid for m in (await client.groups.get_mute_settings(group)).members}


async def test_mute_update_then_unmute(client: pyqbot.Client, write_allowed: str) -> None:
    """须用户单独同意；机器人须是管理员，`TEST_GROUP_MEMBER_OPENID` 是群里一个没在禁言中的普通成员。

    应看到：该成员先被禁言约 2 分钟，随即改为约 5 分钟（`update`），最后解除。
    确认 `update` 能改写到期时间，以及 `del` 带空串能否立即解除。中途失败也会解除禁言。
    """
    group = write_allowed
    member = env("TEST_GROUP_MEMBER_OPENID", "群里一个可以被禁言的普通成员")
    if member in await muted_openids(client, group):
        pytest.skip("该成员已在禁言中，用例结束时没法恢复原来的到期时间")

    async with undo_on_failure(lambda: client.groups.unmute_members(group, member)):
        await client.groups.mute_members(group, member, timedelta(minutes=2))
        await client.groups.update_member_mutes(
            group, member, datetime.now(UTC) + timedelta(minutes=5)
        )
        muted = {m.member_openid: m for m in (await client.groups.get_mute_settings(group)).members}
        expire_at = muted[member].mute_expire_at
        assert expire_at is not None
        assert expire_at > datetime.now(UTC) + timedelta(minutes=3)
        await client.groups.unmute_members(group, member)

    assert member not in await muted_openids(client, group)


async def test_mute_twice_with_add(client: pyqbot.Client, write_allowed: str) -> None:
    """须用户单独同意；前提同 `test_mute_update_then_unmute`。

    应看到：该成员被禁言约 2 分钟，随即再 `add` 一次改为约 5 分钟，最后解除。
    确认对已禁言的成员再次 `add` 是报错，还是等同于 `update`（结果记进 `docs/errata.md`）。
    """
    group = write_allowed
    member = env("TEST_GROUP_MEMBER_OPENID", "群里一个可以被禁言的普通成员")
    if member in await muted_openids(client, group):
        pytest.skip("该成员已在禁言中，用例结束时没法恢复原来的到期时间")

    async with undo_on_failure(lambda: client.groups.unmute_members(group, member)):
        await client.groups.mute_members(group, member, timedelta(minutes=2))
        await client.groups.mute_members(group, member, timedelta(minutes=5))
        muted = {m.member_openid: m for m in (await client.groups.get_mute_settings(group)).members}
        note("再次 add 之后", muted[member])
        await client.groups.unmute_members(group, member)


async def test_blacklist_add_only_works_for_users_outside_the_group(
    client: pyqbot.Client, write_allowed: str
) -> None:
    """须用户单独同意，可能需要白名单；`TEST_GROUP_MEMBER_OPENID` 是群里一个不在黑名单的普通成员。

    应看到：群黑名单没有变化。文档说在群里的用户不能拉黑，确认是部分失败（`fail_openids`）
    还是整个请求报错；万一拉黑成功，用例失败并把他移出黑名单。
    """
    group = write_allowed
    member = env("TEST_GROUP_MEMBER_OPENID", "群里的一个普通成员")
    if member in {user.member_openid async for user in client.groups.iter_blacklist(group)}:
        pytest.skip("该成员已在黑名单里")

    async with undo_on_failure(lambda: client.groups.remove_from_blacklist(group, member)):
        with pytest.raises(pyqbot.PartialFailureError) as caught:
            await client.groups.add_to_blacklist(group, member)

    assert caught.value.failed_ids == (member,)


async def test_remove_member_and_blacklist(client: pyqbot.Client, write_allowed: str) -> None:
    """须用户单独同意，可能需要白名单；`TEST_GROUP_REMOVABLE_OPENID` 是同意被移出的群成员。

    应看到：该成员被移出群并进了黑名单，之后又被移出黑名单；中途失败也会移出黑名单。
    移出群无法撤销，需要时由人重新拉回群。
    """
    group = write_allowed
    member = env("TEST_GROUP_REMOVABLE_OPENID", "同意被移出测试群的成员")

    async with undo_on_failure(lambda: client.groups.remove_from_blacklist(group, member)):
        await client.groups.remove_members(group, member, add_to_blacklist=True)
        blacklisted = {user.member_openid async for user in client.groups.iter_blacklist(group)}
        assert member in blacklisted
        await client.groups.remove_from_blacklist(group, member)


async def test_decline_a_join_request(client: pyqbot.Client, write_allowed: str) -> None:
    """须用户单独同意；机器人须是管理员，`TEST_GROUP_APPLICANT_OPENID` 已申请加入测试群。

    应看到：申请人收到拒绝，理由为「pyqbot 实测」，且没有被拉黑。
    """
    group = write_allowed
    applicant = env("TEST_GROUP_APPLICANT_OPENID", "正在申请加入测试群的用户")

    async for request in client.groups.iter_join_requests(group):
        if request.member_openid == applicant:
            await client.groups.decline_join_request(
                group,
                applicant,
                join_request_id=request.join_request_id,
                reason="pyqbot 实测",
            )
            return
    pytest.fail("待审批的申请里没有 TEST_GROUP_APPLICANT_OPENID")


async def test_join_strategy_lifecycle(client: pyqbot.Client, write_allowed: str) -> None:
    """须用户单独同意：会在机器人上建一个停用的策略（每个机器人最多 20 个），用例结束（含中途失败）时删除。

    应看到：策略列表里出现备注为「pyqbot 实测」的停用策略，修改与白名单操作生效，最后被删除。
    确认 `group_ids` 在响应里是整数还是字符串、`expire_at` 的秒精度与时区是否原样保存。
    """
    group = write_allowed
    expire_at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)

    strategy = await client.join_strategies.create(
        group_openids=group, enabled=False, expire_at=expire_at, remark="pyqbot 实测"
    )
    async with undo_on_failure(lambda: client.join_strategies.delete(strategy)):
        note("创建的响应", strategy)
        assert strategy.enabled is False
        await client.join_strategies.update(strategy, remark="pyqbot 实测（已修改）")
        whitelist = await client.join_strategies.add_whitelist_users(strategy, [10001, "10002"])
        assert whitelist.whitelist_user_count is not None
        await client.join_strategies.remove_whitelist_users(strategy, 10002)
        listed = {s.strategy_id: s async for s in client.join_strategies.iter_strategies()}
        note("新建的策略", listed[strategy.strategy_id])
        assert listed[strategy.strategy_id].remark == "pyqbot 实测（已修改）"
        assert listed[strategy.strategy_id].expire_at == expire_at
        try:  # 2026-11-16 停用的策略、机器人不是管理员时报 50105002，只记下
            await client.join_strategies.execute(strategy)
        except pyqbot.APIError as error:
            note("execute 失败", (error.err_code, error.message))
        await client.join_strategies.delete(strategy)


async def test_proactive_group_message(client: pyqbot.Client, group: str) -> None:
    """不带 `msg_id` 往测试群发一条主动消息「pyqbot：群主动消息实测」。

    机器人状态里 `allow_proactive_msg` 是 false，预计被拒；结果与错误码记进日志。
    """
    try:
        sent = await client.groups.send_message(group, "pyqbot：群主动消息实测")
        note("群主动消息：被接受", sent.id)
    except pyqbot.APIError as error:
        note("群主动消息：被拒", (error.err_code, error.message))
