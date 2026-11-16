# AGENTS.md

pyqbot 是 QQ 机器人 API v2 的 Python SDK，存在的理由只有一个：比官方 SDK 好用。源码在 `src/pyqbot/`，测试在 `tests/`，包结构与模块约定见 `docs/design.md`。

## 环境与命令

Python ≥ 3.14，一切经由 uv：依赖用 `uv add`（开发依赖加 `--dev`），不用 pip，不手改 `uv.lock`。

```sh
uv sync                                         # 安装依赖
uv run ruff check --fix && uv run ruff format   # lint + 格式化
uv run pyright                                  # 类型检查（strict）
uv run pytest                                   # 本地测试，含覆盖率门槛
uv run --env-file .env pytest -m live --no-cov  # 实测，须先获用户同意
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
- 注释与 docstring 要短而够用。判断标准：删掉这句，读者会不会用错、改错，或要重新推导？不会就不写。
  - 只写代码表达不了的东西：为什么这样做、上游的坑、单位与约束。不复述代码、类型和参数名，不写改动过程。行内注释以两行为限。
  - 同一件事只说一处：跨模块的决定写在 `docs/design.md`，代码里至多留一句指向它；docstring 说过的，注释不再说。
  - 从包顶层导出的 API 必须有 Google 风格的 docstring：一句话摘要，加上调用方真正需要的 `Args` / `Raises`。摘要已说清返回值就不写 `Returns`，名字和类型已说清的参数不逐个解释；构造参数写在类的 docstring 里，`__init__` 不再重复。内部函数和类最多一句话。
  - 接口封装要注明对应的官方接口，如 `POST /v2/users/{openid}/messages`。
- 凭证（`app_secret`、access_token）不得出现在日志、异常文案和 `repr` 里：持有凭证的对象要隐藏该字段；平台返回的文案和底层库的异常文案，进入异常或日志前先脱敏。这些行为都要有测试，例如平台回显密钥时异常里没有它。
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

`.env` 已被 git 忽略，永不提交。其中有 `APP_ID`、`APP_SECRET`，测试用户的单聊 openid `TEST_USER_OPENID`，以及测试群的 `TEST_GROUP_OPENID`。

- 每次实测前向用户说明要调用哪些接口并取得同意，同意只对当次有效。
- 经允许可向 `TEST_USER_OPENID` 和测试群 `TEST_GROUP_OPENID` 发送一条或多条消息，也可以在测试群里执行群管理（禁言、移出、拉黑、审批入群等），发完请用户确认是否看到预期效果。群管理会影响群成员，每项都要单独同意。
- 密钥与 access_token 不得出现在代码、日志、命令输出、fixture 或提交中。
- 实测代码放在 `tests/live/` 并标记 `@pytest.mark.live`，默认不运行；与官方文档不符的结论记入 `docs/errata.md`。

## 提交

- 遵循 Conventional Commits：`<type>(<scope>): <中文描述>`，一次提交只做一件事。
- 可以直接在当前分支（包括 `main`）提交，不需要另开分支。
- 主 agent 可以自行提交，不必等用户要求：每完成一个独立的改动并通过检查就提交，不要让工作区积压大量未提交内容。子 agent 不提交；推送仍须用户要求。
