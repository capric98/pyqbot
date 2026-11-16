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
- **`Bot` 的运行入口**（已落地）：`await bot.start()` 连接网关并分发事件，直到 `close()`（正常返回）或不可恢复的错误（抛 `GatewayError`）；没有要订阅的事件、重复调用或已关闭时抛 `RuntimeError`。`bot.run()` 是它的同步包装：`asyncio.run` 里 `async with self: await self.start()`，Ctrl+C 时干净退出、不打印 traceback。`async with bot` 只管资源，不连网关。`close()` 的顺序是断开网关、取消处理函数、关 HTTP 连接。细节见「网关连接」与「事件」。
- **接口挂在哪**（已落地）：一层命名空间，`client.groups.send_message(...)`，不扁平地挂在 `Client` 上，也不多层嵌套。按用户心目中的资源分组（如 `users`、`groups`），不按文档章节。最常用的操作另在模型对象上提供快捷方法（如 `message.reply()`）。属于客户端自身的方法（如 `get_access_token()`）仍直接挂在 `Client` 上。

## 包结构与依赖方向

只允许依赖排在自己上面的模块。公共 API 只有 `pyqbot/__init__.py` 导出的名字。

```text
src/pyqbot/
  _errors.py  _config.py  _redact.py  地基，互不依赖（已落地）
  _model.py       Model、OpenIntEnum、宽容解码（已落地）     ← _redact
  _models/        数据模型与事件模型，按领域分文件（部分落地） ← _model _gateway.intents
  _credentials.py access_token 的获取、缓存、刷新（已落地）  ← _config _errors _model _redact
  _http.py        请求层：拼 URL、鉴权头、解码、错误映射（已落地） ← _credentials _errors _model _redact
  _api/           接口封装，每组一个持有请求层的小类（已落地） ← _http _models
  _client.py      Client = 生命周期 + 凭证 + 各组接口属性（已落地）
  _gateway/       WebSocket：协议数据、连接状态机（已落地）   ← _errors _model _redact
  _events/        分发器（已落地），不依赖网关连接           ← _models _errors _gateway.intents
  _bot.py         Bot(Client)：事件注册（已落地）、start() / run()，把上面几块接起来
```

Webhook（未确认）：若做，是接到同一个分发器上的另一个事件源，放 `_webhook/`。签名校验要用 Ed25519，标准库没有，所以只能是可选 extra；现在不设计、不加依赖。`_events/` 不依赖网关连接（只用 `Intents`）就是为它留的位置。

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
  └── GatewayError  网关被关闭且不可恢复：err_code 为关闭码（有的话）
  ```
- **`pyqbot.Config`**：见上。

## 请求层与接口分组（已落地）

- **`_http.py` 的 `HTTP`**（内部）：`Client` 构造时创建，各组接口只经它发请求。`await http.request(method, path, *, type_, params=None, json=None)` 负责拼绝对地址、加 `Authorization: QQBot {token}`、显式传超时，`json` 经 msgspec 编码，成功时用 `_model.decode()` 解成 `type_`；`type_=None` 不解码、返回 `None`，给没有响应体的接口用。token 取自注入的 `Client.get_access_token`，所以客户端关闭后请求抛 `RuntimeError`。路径参数一律经 `path_segment()` 转义。
- **失败映射**（`dev-prepare/api-call-guide.md`）：文案前缀为 `{method} {path} 失败：`，脱敏时传 `app_secret` 与本次请求用的 token（约定 7）；`err_code`、`trace_id` 的取法同约定 3。不做自动重试和限频退避。

  | 情况 | 结果 |
  | --- | --- |
  | 拿不到响应（`httpx2.RequestError`） | `NetworkError` |
  | 响应体带非零或认不出的 `err_code` / `code`，不论状态码（文档说 201、202 会带失败结构） | `APIError` |
  | 状态码不是 2xx | `APIError` |
  | 响应体不是 JSON | `APIError`（「无法解析响应」） |
  | 2xx、没有错误码，但解不成 `type_` | `APIError`（「响应无法识别」） |

- **接口分组**：`_api/users.py`、`_api/groups.py` 各一个小类，挂成 `client.users`、`client.groups`。首批只有发文本消息：`send_message(openid, content, *, reply_to=None)`，返回 `pyqbot.SentMessage`。其它消息类型以后用仅限关键字的参数追加，不改已有签名。
- **被动回复**：`reply_to` 只接受对应场景收到的消息（`users` 收 `C2CMessage`，`groups` 收 `GroupMessage`，见「事件」）。`msg_id` 取 `reply_to.id`，`msg_seq` 由 `next_msg_seq()` 在这个消息对象上从 1 递增，发送失败也不回退；调用方不用管。
- **网关地址**：`Client._get_gateway_url()` 调 `GET /gateway`，由 `Bot.start()` 作为 `get_url` 注入网关连接。

## 网关连接（已落地）

`_gateway/connection.py` 的 `GatewayConnection`（内部）只管连接本身，不认识 `Client` 和事件模型。`Bot.start()` 以关键字参数注入：

| 注入项 | 类型 | 说明 |
| --- | --- | --- |
| `http_client` | `httpx2.AsyncClient` | 建 WebSocket 用 |
| `get_url` | `() -> Awaitable[str]` | 取网关地址，每次建连前调用 |
| `get_token` | `() -> Awaitable[str]` | 取 access_token，每次建连前调用，所以 token 过期不用单独处理 |
| `intents` | `Intents` | Identify 时订阅的事件类别 |
| `on_dispatch` | `(GatewayPayload) -> None` | 每条 Dispatch（含 READY、RESUMED）调用一次。同步、必须立刻返回；抛出的异常记日志，不影响连接 |

另有 `shard`（原样用于 Identify）、`connect_timeout`（WebSocket 握手超时，传 `config.timeout`，见约定 2）和下文的各个时间参数，默认值就是生产取值。`shard` 不合法、期限参数（各个 `*_timeout`）不是有限正数等配置错误，构造即抛 `ValueError`。

- **`await connection.run()`**：一直运行到 `await connection.close()`（正常返回）或遇到不可恢复的错误（抛 `GatewayError`）。`get_url` / `get_token` 抛 `NetworkError` 时按网络错误退避重试，抛其它异常原样向外抛；编程错误（见下面的分类）等连接关好后原样抛出，不包成异常组。`run()` 只能调用一次；`close()` 之后再调 `run()` 立即返回。
- **关闭**：`close()` 可重复、可并发调用，只有第一次触发收尾，其余的等同一次收尾。收尾先等 httpx2 优雅关闭，超过 `close_timeout`（默认 5 秒）就再取消一次强制结束（此时底层连接可能没关干净），所以 `close()` 与 `run()` 一定返回。连接已拿到断开原因、正在关闭 WebSocket，或 worker 已在被取消时，收尾不再取消它，只等期限；它自己关完后不再重连，已拿到的致命原因照样抛 `GatewayError`。`run()` 被取消（只算进入 `run()` 之后新增的取消）时同样先等收尾，期间再次取消不会打断它，收尾后抛 `CancelledError`。断开重连前关闭旧连接也受 `close_timeout` 限制。
- **会话状态**：`session_id`（来自 READY）与 `seq`（最近一条已交给 `on_dispatch` 的 `s`，`on_dispatch` 抛异常也算）。有会话就 Resume，没有就 Identify。
- **断开后怎么办**：

  | 情况 | 动作 |
  | --- | --- |
  | 收到关闭码 | 按 `classify_close_code()`：Resume、Identify（清掉会话）或放弃（抛 `GatewayError`，`err_code` 为关闭码） |
  | 网络错误（含握手被拒）、没有关闭帧、心跳没有应答、发送超时、收到 OpCode 7 | 重连并 Resume |
  | 收到 OpCode 9 | 清掉会话，重连并 Identify；连续 3 次（中间没有 READY / RESUMED）就放弃 |
  | Hello、认证结果超时未到 | 按网络错误处理 |

  建连、读写、关闭 WebSocket 时冒出的异常（httpx2 的会话用 anyio 任务组，可能是异常组）递归展开到每个叶子再分类：`OSError`（含超时、TLS）、`EOFError`、`httpx2.HTTPError`、`HTTPXWSException`，以及异常类定义在 `anyio`、`wsproto`、`h11`、`httpcore2`、`httpx2` 里的，算网络错误；其它都算编程错误。有一个叶子是编程错误就抛它，结束 `run()`。已拿到断开原因后，关闭阶段的异常一律不覆盖它。

- **心跳**：认证成功（收到本连接的第一条 Dispatch）后立刻发一次，之后按 Hello 给的周期发送，`d` 为当前的 `seq`。到下一次该发时上一次还没收到应答（包括还没写出去），就认为连接已死，断开重连。收到服务端的 OpCode 1 立刻补发一次。不用 WebSocket 层的 Ping。
- **发送超时**：httpx2 的写入没有超时，所以心跳、Identify、Resume 的每次发送都受 `send_timeout`（默认 10 秒）限制，超时即认为连接已死。其它发送失败只记日志，断开原因由读循环拿到。
- **认证超时**：`handshake_timeout` 分别限制等 Hello 和等第一条 Dispatch 的时间。不等 RESUMED：它要在补发完遗漏事件之后才到。
- **退避**：重连间隔从 1 秒起每次翻倍，上限 60 秒，乘以 [0.5, 1] 的随机抖动；收到 READY 或 RESUMED 后从头算。两次 Identify 至少间隔 5 秒（`/gateway/bot` 的 `max_concurrency` 是每 5 秒可新建的会话数）。
- **坏帧**：单帧解不开（`PayloadError`）、非文本帧或意料之外的 OpCode，记日志后跳过，不影响连接。
- **日志**：用标准库 `logging.getLogger("pyqbot")`，内容先脱敏（约定 7）。脱敏用这个连接取到过的所有 token（平台可能回显轮换前的），平台给的字符串（事件名、关闭原因、异常文案）一律先脱敏。

## 事件（已落地）

- **事件模型**（`_models/`）：每种事件一个 `Event` 的子类，收到的消息继承 `ReceivedMessage`（带 `id`）。首批是 `C2CMessage`、`GroupMessage`，都带 `reply()`。子类用 `ClassVar` 声明 `event_name`（Dispatch 的 `t`）与 `intent`。绑定的 `Client` 与回复计数存在实例的 `__dict__` 里（`dict=True`），`repr`、`to_dict()`、编码与相等性只看字段。
- **模型上的行为**：分发器在调用处理函数前 `bind_client(event, client)`，`message.reply()` 这类快捷方法经 `self._bound_client()` 调用接口；没有绑定时抛 `RuntimeError`。同一事件的所有处理函数拿到同一个对象，所以 `msg_seq` 在它们之间也是递增的。
- **常用信息一步拿到**：嵌在发送者里的 openid 在消息上另有属性（`message.user_openid`、`message.member_openid`）；用户写类型标注会用到的嵌套类型（发送者、附件）从顶层导出，其余不导出。文本字段缺失与空串没有区别时默认 `""`（如 `content`），省得处处判断 `None`。
- **注册**（`Bot`）：每种事件一个装饰器 `@bot.on_<事件>`，原样返回处理函数；类型写成 `[F: Handler[事件模型]](handler: F) -> F`，参数类型不对时 pyright 报错。处理函数必须是 `async def`，否则注册时抛 `TypeError`。同一事件可以注册多个。
- **Intents**：默认按已注册的处理函数推导（`Bot._resolve_intents()`），`Bot(..., intents=...)` 传入则以它为准。`Bot.start()` 用它 Identify，所以 `start()` 之后再注册的处理函数不会改变订阅。
- **分发器**（`_events/dispatcher.py`）：`dispatch(payload, client)` 同步、立刻返回，`payload` 只需有 `t` 与 `decode_data()`（`GatewayPayload` 满足），所以不依赖网关。没有处理函数的事件与未知事件直接忽略、不解码，解码失败（`PayloadError`）记 WARNING 后丢弃；每个处理函数一个任务（`eager_start=False`，装了 eager 任务工厂也不在 `dispatch()` 里开跑），异常记 ERROR，不影响其它处理函数。
- **日志不带凭证**：处理函数名取函数自身的 `__qualname__`（`partial` 逐层取被包的函数，可调用对象取类名），不用 `repr()`，因为 `partial` 的 repr 带着绑定的参数；任务名、日志与注册时的 `TypeError` 都用它。处理函数的异常链先格式化成文本，经 `Bot` 注入的 `Client._redact_secrets` 脱敏（约定 7）再写日志，不交给 `logger.exception`。
- **关闭**（`await aclose(grace_period=5)`）：可以重复、并发调用，一定返回。只有第一次调用标记关闭并取消处理函数，每个任务只取消一次，之后的调用只等待，不打断处理函数的清理。在处理函数里调用（`bot.close()` 也一样）只请求停止、立刻返回，不等任何处理函数，所以处理函数之间不会互相等待。在外面调用时最多等 `grace_period` 秒，还没结束的（吞掉了取消）记一条 WARNING 后不再等。`Bot.close()` 依次断开网关、调它、关 HTTP 连接。
- **加一种事件**：在 `_models/` 按官方文档定义模型（声明 `event_name`、`intent`，只把 SDK 要用的字段写成必填，需要的话加 `reply()`），从顶层导出；在 `Bot` 上照 `on_c2c_message` 加一个装饰器。分发器与 Intents 推导不用改。

## 后续模块要遵守的约定

1. **命名与可见性**：内部模块里要给别的模块用的名字不加下划线，`_` 前缀的名字只在本模块、本类及其子类内使用（pyright strict 会拒绝越界访问）。是否公共只看有没有从包顶层导出；新增导出同时更新 `__all__`。
2. **地址与超时只认 `Config`**：请求一律用 `config.base_url + "/path"` 的绝对地址，并显式传 `timeout=config.timeout`；不依赖 `httpx2.AsyncClient` 自身的 `base_url` / `timeout`，这样自建与注入的客户端行为一致。所有网络 IO（含 WebSocket）都走 `client.http_client`，任何模块不得另建 `httpx2` 客户端。
3. **异常**：运行期失败只抛 `QQBotError` 的子类，新增的类都放 `_errors.py` 并导出。只有基类带 `QQBot`，子类不加前缀、以 `Error` 结尾，且不与内置异常重名。`httpx2`、`msgspec` 的异常（含超深嵌套 JSON 引起的 `RecursionError`）不得漏给用户，包装后用 `raise ... from` 保留原因。响应体里 `err_code` 与 `code` 任一个非零就算失败（获取 token 的接口只有 `code`，且业务失败时 HTTP 仍是 200）；两个都有时异常的 `err_code` 取响应体的 `err_code`，`code` 是旧式错误码（见 `errata.md`）；`trace_id` 优先取响应头 `X-Tps-trace-ID`，其次响应体。用法错误（参数不合法、关闭后再用）抛内置的 `ValueError` / `RuntimeError`。
4. **模型**：继承 `Model`。可选字段写 `X | None = None`，不向外暴露 `msgspec.UNSET`；集合字段用 `tuple[X, ...]`、默认 `()`（写 `= []` 会触发 ruff RUF012）；接口字段名不是 snake_case 时用 `msgspec.field(name=...)`。内部可以随意用 msgspec，但公共签名里不出现它的类型。
   - **宽容解码落到字段级**：只有 SDK 自己要用的字段才写成必填；其余字段都给默认值。解码一律经 `_model.decode()`：有默认值的字段类型不符时退回默认值（嵌套模型逐层处理；`tuple[模型, ...]` 逐个元素处理，清理后仍不合法的元素只丢掉它自己），只有必填字段缺失或类型不符才让整条数据失败。
   - **枚举容忍未知取值**：取值互斥的枚举继承 `OpenIntEnum`，字段直接写枚举类型。未知的整数得到伪成员：是该枚举的实例，`name` 为 `"UNKNOWN"`，`value`、比较与 `to_dict()` 都是原值；每次得到的是不同对象，只用 `==` / `match` 的值模式比较，不用 `is`。msgspec 解码按 JSON 类型严格校验（`true`、`1.0` 不算整数）；直接调用 `MyEnum(True)` 则按标准库语义命中值相等的成员。
   - 位标志用标准库 `enum.IntFlag`：它默认保留未知位，例如 `Intents`。不用 `MyEnum | int` 这类联合类型：调用方每处都要再判断一次类型。
5. **接口封装**：每组一个 `_api/<组>.py`，写成持有请求层的小类，由 `Client` 在构造时创建成属性（`self.groups = Groups(self._http)`）；不用 mixin。只经请求层发请求，不直接碰 `httpx2`。
6. **模块之间靠注入，不互相认识**：网关连接不依赖 `Client` 和事件模型，分发器不依赖网关连接，各自需要的能力由 `Bot` 在启动时传进去。这样每一块都能单独测试，Webhook 以后也能接到同一个分发器上。
7. **凭证不落日志**：`app_secret`、access_token 不得出现在 `repr`、日志和异常文案里。
   - 平台返回的文案和底层库的异常文案，进入异常或日志前一律经 `_redact.redact(text, *secrets)`，传入 `app_secret` 与手头所有已知的 access_token。
   - 包装底层异常时写 `raise ... from _redact.safe_cause(exc, *secrets)`：traceback 会连异常链一起打印，链上出现凭证时整条链丢掉。
   - 持有凭证的 `Model` 在类体里写 `_secret_fields = frozenset({"token"})`，这些字段在 `repr()` 与 `__rich_repr__()` 里显示为 `***`（字段名写错会在类创建时报错）；dataclass 用 `field(repr=False)`。
   - 每处都要有测试，且测试在去掉脱敏后必须失败，例如让替身回显 `app_secret`。
   - openid（用户、群、群成员）不是凭证，可以出现在异常文案和日志里，例如请求路径。

## 测试约定

- 替身一律从公共入口的 `http_client=` 注入，不为测试另开后门。可运行的示范见 `tests/test_network_doubles.py`。
- HTTP：`httpx2.AsyncClient(transport=httpx2.MockTransport(handler))`。
- WebSocket：在同一个客户端上加 `mounts={"wss://": ASGIWebSocketTransport(app)}`，`app` 是扮演网关的 ASGI 应用。这个客户端必须在测试函数体内用 `async with` 打开：不进入会缺少内部任务组而报 `AttributeError`，放进 yield fixture 则在清理时报 cancel scope 跨任务退出（两种都实测过）。
- `tests/conftest.py` 有一个 autouse 兜底：凡是走到真实传输层的请求都直接失败。
- 不真实等待：token 过期、心跳间隔等用 monkeypatch 控制时间。等待并发结果的测试套一层 `asyncio.timeout`，回归时失败而不是挂起。
- 测试优先只用 `pyqbot` 的公共接口；地基自身的测试可以直接导入内部模块（如 `pyqbot._model`）。

## 后续模块

骨架已经打通：凭证、请求层、网关连接、事件分发、`Bot.start()` / `run()` 都已落地，单聊消息能收能回。剩下的主要是按现有写法铺开：

- **其余事件**：`autogen/event/` 下还有二十种，照「加一种事件」的步骤做。
- **其余接口**：`autogen/api/` 下的群管理、用户、面板等，以及 `server-inter/channel/` 下的频道接口，照约定 5 按资源分组。
- **其它消息类型**：Markdown、富媒体、卡片、键盘，在 `send_message` 上用仅限关键字的参数追加。
- **富媒体上传**：预上传、分片、完成三步，需要实测。
- **Webhook**（未确认）：见上。
- **待定的语义**：HTTP 202 加 304023 / 304024 表示「已受理、等待审核」，现在按失败抛出，做频道消息时要定下怎么表达（见 `errata.md`）。

官方文档的出入（含当前实现的取舍与待实测项）集中记在 [`errata.md`](errata.md)。
