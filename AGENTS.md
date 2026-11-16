# AGENTS.md

pyqbot 是 QQ 机器人 API v2 的 Python SDK，存在的理由只有一个：比官方 SDK 好用。源码在 `src/pyqbot/`，测试在 `tests/`。

## 环境与命令

Python ≥ 3.14，一切经由 uv：依赖用 `uv add`（开发依赖加 `--dev`），不用 pip，不手改 `uv.lock`。

```sh
uv sync                                         # 安装依赖
uv run ruff check --fix && uv run ruff format   # lint + 格式化
uv run pyright                                  # 类型检查（strict）
uv run pytest                                   # 本地测试，含覆盖率门槛
uv run --env-file .env pytest -m live           # 实测，须先获用户同意
```

交付前，前四条必须全部通过。

## 技术栈

- 只提供 async 接口。并发用标准库 asyncio（`TaskGroup`、`asyncio.timeout`），自己的代码不直接依赖 anyio。
- HTTP 与 WebSocket 都用 httpx2（`httpx2[ws]`）。包名和导入名都是 `httpx2`，不要写成 `httpx`。
- 数据模型用 msgspec，全部继承同一个内部基类。对外只提供自己的方法（如 `to_dict()`），不让 msgspec 的 API 成为公共接口。

## 官方文档是唯一事实来源

- 接口行为以 `docs/upstream/qqbot-api-v2/` 的官方文档快照为准：总索引 `autogen/index.md`，接口 `autogen/api/`，事件 `autogen/event/`，鉴权与连接 `dev-prepare/`。不要凭记忆写，也不要照搬官方 SDK 或第三方实现——域名、鉴权方式都变过。
- 快照是生成物，不要手改；更新用 `uv run --locked scripts/sync_qqbot_docs.py`。
- 文档缺失、含糊或自相矛盾时不要猜：先问用户，经同意后实测。

## 代码规范

- 直接用 3.14 的现代写法（`X | None`、PEP 695 泛型、`match` 等），不为旧版本写兼容代码。
- 全量类型标注并通过 pyright strict；`Any`、`# type: ignore` 只在写明原因时使用。
- 文档、注释、docstring、异常与日志文案、提交描述默认用中文（用户另有要求除外）；标识符用英文。
- 注释只写「为什么」和文档没说清的坑，不复述代码。公共 API 必须有 Google 风格的 docstring，接口封装要注明对应的官方接口，如 `POST /v2/users/{openid}/messages`。
- 运行时依赖越少越好，新增前先征得用户同意。

## 接口设计

从调用方的代码倒推：先写出期望的用户代码（示例或测试），再实现。

- 协议细节由 SDK 内部消化：token 获取与刷新、心跳、重连与恢复、分片上传、回复所需的 `msg_id` / `msg_seq`。
- 返回带类型的模型而不是裸 `dict`，用枚举代替魔法数字；可选参数一律 keyword-only，并给合理默认值。
- 失败一律抛异常（统一基类，携带 `err_code`、`trace_id`），不用返回值表达错误。
- 对上游变化保持宽容：未知字段、未知事件不得导致崩溃。
- 公共 API 从包顶层导出，其余用 `_` 前缀标为内部实现。

## 测试

- 本地测试不访问真实网络，HTTP 与 WebSocket 都用本地替身。
- 每个改动都带测试。行与分支覆盖率门槛写在 `pyproject.toml`（`fail_under = 95`），只升不降；`# pragma: no cover` 必须附理由。
- 本地无法验证的行为走实测，结论要沉淀回本地测试：把真实响应脱敏后做成 fixture。

## 实测

`.env` 已被 git 忽略，永不提交。其中有 `APP_ID`、`APP_SECRET`，以及测试用户的单聊 openid `TEST_USER_OPENID`。

- 每次实测前向用户说明要调用哪些接口并取得同意，同意只对当次有效。
- 经允许可向 `TEST_USER_OPENID` 发送一条或多条消息，发完请用户确认是否看到预期效果。不得向其他用户或群发消息，不得自行执行群管理等影响他人的操作。
- 密钥与 access_token 不得出现在代码、日志、命令输出、fixture 或提交中。
- 实测代码放在 `tests/live/` 并标记 `@pytest.mark.live`，默认不运行；与官方文档不符的结论记入 `docs/errata.md`。

## 提交

遵循 Conventional Commits：`<type>(<scope>): <中文描述>`，一次提交只做一件事。
