# 设计：入口、初始化与模块约定

总约束见根目录 `AGENTS.md`，接口行为以 `docs/upstream/qqbot-api-v2/` 为准。本文只定各模块之间必须一致的东西，模块内部的接口由实现者设计。标「已落地」的已有代码和测试，其余是规划。

## 目标用户代码

```python
import pyqbot

# 只调接口的脚本：Client 可以单独使用
async with pyqbot.Client(APP_ID, APP_SECRET) as client:
    await client.users.send_message(openid, "你好")

# 事件驱动：Bot 继承 Client，接口用法完全相同
bot = pyqbot.Bot(APP_ID, APP_SECRET)


@bot.on_c2c_message
async def reply(message: pyqbot.C2CMessage) -> None:
    await message.reply("收到")


bot.run()  # 同步入口，阻塞到退出
```

## 入口与初始化

`Bot` 继承 `Client`（已落地），构造参数、生命周期与接口都相同。构造时不发请求，参数不合法立刻抛 `ValueError`：

| 参数 | 说明 |
| --- | --- |
| `app_id`、`app_secret` | 位置参数。`app_id` 接受 `str` 或 `int` |
| `base_url=` | 默认 `https://api.bot.qq.com`，可覆盖；末尾的 `/` 会去掉 |
| `timeout=` | 单次请求超时（秒），默认 30 |
| `http_client=` | 自备的 `httpx2.AsyncClient`（代理、证书、连接池；测试替身也从这里进） |

- **配置**（已落地）：参数收拢成只读的 `pyqbot.Config`，经 `client.config` 读取；`repr` 不含 `app_secret`。各模块都从它取凭证、地址、超时，不各存一份。
- **`httpx2.AsyncClient` 的归属**（已落地）：不传 `http_client` 时由 `Client` 自建、`close()` 时关闭；传入的归调用方，SDK 只用不关。经 `client.http_client` 取回。
- **生命周期**（已落地）：推荐 `async with`；也可直接构造，用完 `await client.close()`（可重复调用）。关闭后不可复用。
- **access_token**（已落地）：`await client.get_access_token()` 返回当前有效的 token（不带 `QQBot ` 前缀），首次调用才取，之后按需刷新；关闭后调用抛 `RuntimeError`。请求层在 `Client` 内部，直接用 `_credentials.AccessTokenManager`。
- **`Bot` 的运行入口**（规划）：`await bot.start()` 连接网关并分发事件，直到 `close()`（正常返回）或不可恢复的错误（抛 `GatewayError`）；`bot.run()` 是它的同步包装：`asyncio.run` 里 `async with self: await self.start()`，Ctrl+C 时干净退出、不打印 traceback。`async with bot` 只管资源，不连网关。细节见「网关连接」与「事件」。
- **接口挂在哪**（规划）：一层命名空间，`client.groups.send_message(...)`，不扁平地挂在 `Client` 上，也不多层嵌套。按用户心目中的资源分组（如 `users`、`groups`），不按文档章节。最常用的操作另在模型对象上提供快捷方法（如 `message.reply()`）。属于客户端自身的方法（如 `get_access_token()`）仍直接挂在 `Client` 上。

## 包结构与依赖方向

只允许依赖排在自己上面的模块。公共 API 只有 `pyqbot/__init__.py` 导出的名字。

```text
src/pyqbot/
  _errors.py  _config.py  _redact.py  地基，互不依赖（已落地）
  _model.py       Model、OpenIntEnum、宽容解码（已落地）     ← _redact
  _models/        数据模型与事件模型，按领域分文件           ← _model
  _credentials.py access_token 的获取、缓存、刷新（已落地）  ← _config _errors _model _redact
  _http.py        请求层：拼 URL、鉴权头、解码、错误映射       ← _credentials _errors _model _redact
  _api/           接口封装，每组一个持有请求层的小类          ← _http _models
  _client.py      Client = 生命周期 + 凭证（已落地）+ 各组接口属性
  _gateway/       WebSocket：协议数据（已落地）、连接状态机   ← _errors _model _redact
  _events/        分发器，不依赖 _gateway                   ← _models
  _bot.py         Bot(Client)：事件注册、start() / run()，把上面几块接起来
```

Webhook（未确认）：若做，是接到同一个分发器上的另一个事件源，放 `_webhook/`。签名校验要用 Ed25519，标准库没有，所以只能是可选 extra；现在不设计、不加依赖。`_events/` 不依赖 `_gateway/` 就是为它留的位置。

## 共用地基（已落地）

- **`pyqbot._model.Model`**：所有模型的基类（内部，不导出）。子类自动不可变、字段仅限关键字，不必也不要重复声明 `frozen` / `kw_only`；解码时忽略未知字段。对外只有 `to_dict()`，返回与接口 JSON 一一对应的字典。
- **`pyqbot._model.decode(data, type_)`**：解码接口与网关数据的统一入口，宽容规则见约定 4。
- **`pyqbot._model.OpenIntEnum`**：接口里的整数枚举都继承它，见约定 4。第一个字符串枚举出现时再照样加 `OpenStrEnum`。
- **`pyqbot._redact`**：凭证脱敏，见约定 7。
- **异常**（`_errors.py`）：
  ```text
  QQBotError        基类：message、err_code、trace_id（后两者可为 None）
  ├── APIError      平台返回了失败：另带 status_code；可按需再细分
  ├── NetworkError  没拿到响应：连接失败、超时
  ├── PayloadError  网关下发的一帧解不开：只丢弃这一帧，连接照常
  └── GatewayError  网关被关闭且不可恢复（规划，网关模块添加）
  ```
- **`pyqbot.Config`**：见上。

## 请求层与接口分组（规划）

- **`_http.py` 的 `HTTP`**（内部）：`Client` 构造时创建，各组接口只经它发请求。`await http.request(method, path, *, type_, params=None, json=None)` 负责拼绝对地址、加 `Authorization: QQBot {token}`、显式传超时，成功时用 `_model.decode()` 解成 `type_`（没有响应体的接口返回 `None`）。
- **失败映射**：拿不到响应抛 `NetworkError`；状态码不是 2xx，或响应体带非零的 `code` / `err_code`，抛 `APIError`。文案先脱敏（约定 7）。第一版不做自动重试和限频退避。
- **接口分组**：`_api/users.py`、`_api/groups.py` 各一个小类，挂成 `client.users`、`client.groups`。首批只有发文本消息：`send_message(openid, content, *, reply_to=None)`，返回带类型的结果。其它消息类型以后用仅限关键字的参数追加，不改已有签名。
- **被动回复**：`reply_to` 传收到的消息对象。`msg_id` 取自它，`msg_seq` 由 SDK 在这个消息对象上递增，调用方不用管。

## 网关连接（规划）

`_gateway/connection.py` 的 `GatewayConnection`（内部）只管连接本身，不认识 `Client` 和事件模型。它需要的东西都由 `Bot.start()` 注入：

| 注入项 | 类型 | 说明 |
| --- | --- | --- |
| `http_client` | `httpx2.AsyncClient` | 建 WebSocket 用 |
| `get_url` | `() -> Awaitable[str]` | 取网关地址，每次建连前调用 |
| `get_token` | `() -> Awaitable[str]` | 取 access_token，每次建连前调用，所以 token 过期不用单独处理 |
| `intents` | `Intents` | Identify 时订阅的事件类别 |
| `on_dispatch` | `(GatewayPayload) -> None` | 每收到一条 Dispatch 调用一次。同步、必须立刻返回，不得在里面等待 |

- **`await connection.run()`**：一直运行到 `await connection.close()`（正常返回）或遇到不可恢复的错误（抛 `GatewayError`）。
- **会话状态**：`session_id`（来自 READY）与 `seq`（最近一条已交给 `on_dispatch` 的 `s`）。有会话就 Resume，没有就 Identify。
- **断开后怎么办**：

  | 情况 | 动作 |
  | --- | --- |
  | 收到关闭码 | 按 `classify_close_code()`：Resume、Identify（清掉会话）或放弃（抛 `GatewayError`，`err_code` 为关闭码） |
  | 网络错误、没有关闭帧、心跳没有应答、收到 OpCode 7 | 重连并 Resume |
  | 收到 OpCode 9 | 清掉会话，重连并 Identify；连续 3 次就放弃 |
  | Hello、READY、RESUMED 超时未到 | 按网络错误处理 |

- **心跳**：按 Hello 给的周期发送，`d` 为当前的 `seq`。到下一次该发时上一次还没收到应答，就认为连接已死，断开重连。收到服务端的 OpCode 1 立刻补发一次。
- **退避**：重连间隔从 1 秒起每次翻倍，上限 60 秒，带随机抖动；收到 READY 或 RESUMED 后归零。两次 Identify 至少间隔 5 秒（平台按 5 秒窗口限制新建会话数）。这些时间都做成构造参数，测试里设成接近 0。
- **坏帧**：单帧解不开（`PayloadError`）或遇到未知的 OpCode，记日志后跳过，不影响连接。
- **日志**：用标准库 `logging.getLogger("pyqbot")`，内容先脱敏（约定 7）。
- **测试**：用 `ASGIWebSocketTransport` 扮演网关，覆盖上表每一行，以及关闭时不残留任务。

## 事件（规划）

- **事件模型**（`_models/`）：每种事件一个 `Event` 的子类。`Event` 是带 `__dict__` 的 `Model`（`dict=True`），所以可以挂不属于字段的东西；`repr`、`to_dict()`、相等性仍只看字段。子类用 `ClassVar` 声明事件名与所需的 Intent：`event_name = "C2C_MESSAGE_CREATE"`、`intent = Intents.GROUP_AND_C2C_EVENT`。
- **模型上的行为**：分发前由分发器把 `Client` 绑到事件对象上，`await message.reply("收到")` 这类方法经它调用接口。没有绑定的对象（比如测试里自己构造的）调用这些方法抛 `RuntimeError`，文案说明原因。
- **注册**：`Bot` 上每种事件一个装饰器，名字按用户的说法起：`@bot.on_c2c_message`、`@bot.on_group_at_message`。装饰器原样返回处理函数；处理函数必须是 `async def`、只收一个事件对象，注册时不是协程函数就抛 `TypeError`。同一事件可以注册多个处理函数。
- **Intents 自动推导**：默认按已注册的处理函数算出要订阅的 Intents，用户不必了解这个概念；需要时用 `Bot(..., intents=...)` 覆盖。
- **分发器**（`_events/dispatcher.py`，内部）：`dispatch(payload, client)` 是同步的，立刻返回。没有处理函数的事件不解码；解码失败记日志后丢弃；每个处理函数在自己的任务里运行，互不影响，抛出的异常记日志，不影响连接和其它处理函数。`await dispatcher.aclose()` 取消并等待还在运行的处理函数。
- **未知事件**：直接忽略。
- **首批事件**：`C2C_MESSAGE_CREATE`（`C2CMessage`）、`GROUP_AT_MESSAGE_CREATE`（`GroupMessage`），都带 `reply()`。

## 后续模块要遵守的约定

1. **命名与可见性**：内部模块里要给别的模块用的名字不加下划线，`_` 前缀的名字只在本模块、本类及其子类内使用（pyright strict 会拒绝越界访问）。是否公共只看有没有从包顶层导出；新增导出同时更新 `__all__`。
2. **地址与超时只认 `Config`**：请求一律用 `config.base_url + "/path"` 的绝对地址，并显式传 `timeout=config.timeout`；不依赖 `httpx2.AsyncClient` 自身的 `base_url` / `timeout`，这样自建与注入的客户端行为一致。所有网络 IO（含 WebSocket）都走 `client.http_client`，任何模块不得另建 `httpx2` 客户端。
3. **异常**：运行期失败只抛 `QQBotError` 的子类，新增的类都放 `_errors.py` 并导出。只有基类带 `QQBot`，子类不加前缀、以 `Error` 结尾，且不与内置异常重名。`httpx2`、`msgspec` 的异常（含超深嵌套 JSON 引起的 `RecursionError`）不得漏给用户，包装后用 `raise ... from` 保留原因。`err_code` 优先取获取 token 接口的 `code`（业务失败时 HTTP 仍是 200），其次通用结构的 `err_code`；`trace_id` 优先取响应头 `X-Tps-trace-ID`，其次响应体。用法错误（参数不合法、关闭后再用）抛内置的 `ValueError` / `RuntimeError`。
4. **模型**：继承 `Model`。可选字段写 `X | None = None`，不向外暴露 `msgspec.UNSET`；集合字段用 `tuple[X, ...]`、默认 `()`（写 `= []` 会触发 ruff RUF012）；接口字段名不是 snake_case 时用 `msgspec.field(name=...)`。内部可以随意用 msgspec，但公共签名里不出现它的类型。
   - **宽容解码落到字段级**：只有 SDK 自己要用的字段才写成必填；其余字段都给默认值。解码一律经 `_model.decode()`：有默认值的字段类型不符时退回默认值（嵌套模型逐层处理），只有必填字段缺失或类型不符才让整条数据失败。
   - **枚举容忍未知取值**：取值互斥的枚举继承 `OpenIntEnum`，字段直接写枚举类型。未知的整数得到伪成员：是该枚举的实例，`name` 为 `"UNKNOWN"`，`value`、比较与 `to_dict()` 都是原值；每次得到的是不同对象，只用 `==` / `match` 的值模式比较，不用 `is`。msgspec 解码按 JSON 类型严格校验（`true`、`1.0` 不算整数）；直接调用 `MyEnum(True)` 则按标准库语义命中值相等的成员。
   - 位标志用标准库 `enum.IntFlag`：它默认保留未知位，例如 `Intents`。不用 `MyEnum | int` 这类联合类型：调用方每处都要再判断一次类型。
5. **接口封装**：每组一个 `_api/<组>.py`，写成持有请求层的小类，由 `Client` 在构造时创建成属性（`self.groups = Groups(self._http)`）；不用 mixin。只经请求层发请求，不直接碰 `httpx2`。
6. **模块之间靠注入，不互相认识**：网关连接不依赖 `Client` 和事件模型，分发器不依赖网关连接，各自需要的能力由 `Bot` 在启动时传进去。这样每一块都能单独测试，Webhook 以后也能接到同一个分发器上。
7. **凭证不落日志**：`app_secret`、access_token 不得出现在 `repr`、日志和异常文案里。
   - 平台返回的文案和底层库的异常文案，进入异常或日志前一律经 `_redact.redact(text, *secrets)`，传入 `app_secret` 与手头所有已知的 access_token。
   - 包装底层异常时写 `raise ... from _redact.safe_cause(exc, *secrets)`：traceback 会连异常链一起打印，链上出现凭证时整条链丢掉。
   - 持有凭证的 `Model` 在类体里写 `_secret_fields = frozenset({"token"})`，这些字段在 `repr()` 与 `__rich_repr__()` 里显示为 `***`（字段名写错会在类创建时报错）；dataclass 用 `field(repr=False)`。
   - 每处都要有测试，且测试在去掉脱敏后必须失败，例如让替身回显 `app_secret`。

## 测试约定

- 替身一律从公共入口的 `http_client=` 注入，不为测试另开后门。可运行的示范见 `tests/test_network_doubles.py`。
- HTTP：`httpx2.AsyncClient(transport=httpx2.MockTransport(handler))`。
- WebSocket：在同一个客户端上加 `mounts={"wss://": ASGIWebSocketTransport(app)}`，`app` 是扮演网关的 ASGI 应用。这个客户端必须在测试函数体内用 `async with` 打开：不进入会缺少内部任务组而报 `AttributeError`，放进 yield fixture 则在清理时报 cancel scope 跨任务退出（两种都实测过）。
- `tests/conftest.py` 有一个 autouse 兜底：凡是走到真实传输层的请求都直接失败。
- 不真实等待：token 过期、心跳间隔等用 monkeypatch 控制时间。等待并发结果的测试套一层 `asyncio.timeout`，回归时失败而不是挂起。
- 测试优先只用 `pyqbot` 的公共接口；地基自身的测试可以直接导入内部模块（如 `pyqbot._model`）。

## 首批小模块候选

| # | 模块 | 职责边界 | 官方文档 | 依赖 | 为什么适合先做 |
| --- | --- | --- | --- | --- | --- |
| 1 | 凭证 `_credentials.py`（已落地） | 获取 access_token，缓存，临近过期时刷新，并发调用只发一次请求，失败映射成异常；并接到 `Client` 上。不管鉴权头怎么拼 | `dev-prepare/access-token.md` | `_config` `_errors` | 只有一个接口，状态机自成一体，其它所有模块都要用它 |
| 2 | 网关协议数据 `_gateway/` 内（已落地） | OpCode、Intents、上下行 payload 的编解码、关闭码该恢复 / 重新鉴权 / 放弃的分类。纯数据，不建连接 | `dev-prepare/event-emit/payload.md`、`dev-prepare/event-emit/websocket.md`、`dev-prepare/error-trace/websocket.md` | `_model` | 无 IO，全是表格到代码的映射；与 1 不碰同一个文件 |
| 3 | 错误映射（`_http.py` 的一部分） | 纯函数：状态码 + 响应头 + 响应体 → 异常或「成功」，含 `trace_id` 的提取与 `APIError` 的细分 | `dev-prepare/api-call-guide.md`、`dev-prepare/error-trace/index.md` | `_errors` | 无 IO，输入输出都能列成表；201/202 带 error body 的情况需要先想清楚 |
| 4 | 事件分发器 `_events/` 内 | 处理函数的注册表与并发调用、处理函数出错不影响其它处理函数和连接。不含事件模型，不连网关 | `dev-prepare/event-emit/payload.md`、`autogen/index.md` 的「事件」 | 无 | 纯 asyncio，独立；但对外的注册方式是易用性的核心，设计空间比前三个大 |
| 5 | 请求层 + 第一个接口 | `_http.py` 的发送与解码，加 `GET /users/@me` 打通接口分组的写法 | `dev-prepare/api-call-guide.md`、`autogen/api/users_me.get.md` | 1、3 | 不能最先做，列在这里表明顺序 |

官方文档的出入（含当前实现的取舍与待实测项）集中记在 [`errata.md`](errata.md)。
