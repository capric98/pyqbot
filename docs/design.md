# 设计：入口、初始化与模块约定

总约束见根目录 `AGENTS.md`，接口行为以 `docs/upstream/qqbot-api-v2/` 为准。本文只定各模块之间必须一致的东西，模块内部的接口由实现者设计。标「已落地」的已有代码和测试，其余是规划。

## 目标用户代码

```python
import pyqbot

# 只调接口的脚本：Client 可以单独使用
async with pyqbot.Client(APP_ID, APP_SECRET) as client:
    await client.send_c2c_message(openid, "你好")  # 方法名仅示意

# 事件驱动：Bot 建在 Client 之上
bot = pyqbot.Bot(APP_ID, APP_SECRET)


@bot.on_c2c_message  # 注册方式仅示意
async def reply(message: pyqbot.C2CMessage) -> None:
    await message.reply("收到")


bot.run()  # 同步入口，阻塞到退出
```

## 入口与初始化

`Client` 与 `Bot` 的构造参数相同（已落地），构造时不发请求，参数不合法立刻抛 `ValueError`：

| 参数 | 说明 |
| --- | --- |
| `app_id`、`app_secret` | 位置参数。`app_id` 接受 `str` 或 `int` |
| `base_url=` | 默认 `https://api.bot.qq.com`，可覆盖；末尾的 `/` 会去掉 |
| `timeout=` | 单次请求超时（秒），默认 30 |
| `http_client=` | 自备的 `httpx2.AsyncClient`（代理、证书、连接池；测试替身也从这里进） |

- **配置**（已落地）：参数收拢成只读的 `pyqbot.Config`，经 `client.config` 读取；`repr` 不含 `app_secret`。各模块都从它取凭证、地址、超时，不各存一份。
- **`httpx2.AsyncClient` 的归属**（已落地）：不传 `http_client` 时由 `Client` 自建、`close()` 时关闭；传入的归调用方，SDK 只用不关。经 `client.http_client` 取回。
- **生命周期**（已落地）：推荐 `async with`；也可直接构造，用完 `await client.close()`（可重复调用）。关闭后不可复用。`Bot` 持有一个 `Client`（`bot.client`），`async with bot` / `bot.close()` 同时管理它。
- **`Bot` 的运行入口**（规划，随网关落地）：`await bot.start()` 连接网关并分发事件，直到 `close()` 或不可恢复的错误，退出时释放资源；`bot.run()` 是它的同步包装（`asyncio.run`），处理 Ctrl+C。`async with bot` 只管资源，不连网关。
- **接口挂在哪**（规划）：扁平地挂在 `Client` 上（`client.send_group_message(...)`）；`Bot` 不重复这些方法，统一走 `bot.client`。

## 包结构与依赖方向

只允许依赖排在自己上面的模块。公共 API 只有 `pyqbot/__init__.py` 导出的名字。

```text
src/pyqbot/
  _errors.py  _config.py  _model.py   地基，互不依赖（已落地）
  _models/        数据模型，按领域分文件              ← _model
  _credentials.py access_token 的获取、缓存、刷新     ← _config _errors
  _http.py        请求层：拼 URL、鉴权头、解码、错误映射 ← _credentials _errors _model
  _api/           接口封装，每组一个 mixin 类          ← _http _models
  _client.py      Client = 生命周期（已落地）+ _api 各组
  _gateway/       WebSocket：协议数据、心跳、重连与恢复 ← Client 的公共接口
  _events/        事件模型与分发器，不做 IO、不依赖 _gateway ← _models
  _bot.py         Bot = Client + _gateway + _events（生命周期已落地）
```

Webhook（未确认）：若做，是接到同一个分发器上的另一个事件源，放 `_webhook/`。签名校验要用 Ed25519，标准库没有，所以只能是可选 extra；现在不设计、不加依赖。`_events/` 不依赖 `_gateway/` 就是为它留的位置。

## 共用地基（已落地）

- **`pyqbot._model.Model`**：所有模型的基类（内部，不导出）。子类自动不可变、字段仅限关键字，不必也不要重复声明 `frozen` / `kw_only`；解码时忽略未知字段。对外只有 `to_dict()`，返回与接口 JSON 一一对应的字典。
- **异常**（`_errors.py`）：
  ```text
  QQBotError        基类：message、err_code、trace_id（后两者可为 None）
  ├── APIError      平台返回了失败：另带 status_code；可按需再细分
  ├── NetworkError  没拿到响应：连接失败、超时
  └── GatewayError  网关被关闭且不可恢复（规划，网关模块添加）
  ```
- **`pyqbot.Config`**：见上。

## 后续模块要遵守的约定

1. **命名与可见性**：内部模块里要给别的模块用的名字不加下划线，`_` 前缀的名字只在本模块、本类及其子类内使用（pyright strict 会拒绝越界访问）。是否公共只看有没有从包顶层导出；新增导出同时更新 `__all__`。
2. **地址与超时只认 `Config`**：请求一律用 `config.base_url + "/path"` 的绝对地址，并显式传 `timeout=config.timeout`；不依赖 `httpx2.AsyncClient` 自身的 `base_url` / `timeout`，这样自建与注入的客户端行为一致。所有网络 IO（含 WebSocket）都走 `client.http_client`，任何模块不得另建 `httpx2` 客户端。
3. **异常**：运行期失败只抛 `QQBotError` 的子类，新增的类都放 `_errors.py` 并导出。`httpx2`、`msgspec` 的异常不得漏给用户，包装后用 `raise ... from` 保留原因。获取 token 的接口用 `code` 表示错误，同样填进 `err_code`。用法错误（参数不合法、关闭后再用）抛内置的 `ValueError` / `RuntimeError`。
4. **模型**：继承 `Model`。可选字段写 `X | None = None`，不向外暴露 `msgspec.UNSET`；集合字段用 `tuple[X, ...]`、默认 `()`（写 `= []` 会触发 ruff RUF012）；接口字段名不是 snake_case 时用 `msgspec.field(name=...)`。枚举必须容忍未知取值，做法由第一个用到枚举的模块定在 `_model.py` 里，后来者复用。内部可以随意用 msgspec，但公共签名里不出现它的类型。
5. **接口封装**：每组一个 `_api/<组>.py`，写成 mixin 并加进 `Client` 的基类；只经请求层发请求，不直接碰 `httpx2`。
6. **`Bot` 与网关只用 `Client` 的公共接口**（`config`、`http_client`、接口方法）。因此凭证模块接入时，要在 `Client` 上提供取当前有效 access_token 的公共方法：网关鉴权要用，用户调用尚未封装的接口时也用得上。
7. **凭证不落日志**：`app_secret`、access_token 不得出现在 `repr`、日志和异常文案里。

## 测试约定

- 替身一律从公共入口的 `http_client=` 注入，不为测试另开后门。可运行的示范见 `tests/test_network_doubles.py`。
- HTTP：`httpx2.AsyncClient(transport=httpx2.MockTransport(handler))`。
- WebSocket：在同一个客户端上加 `mounts={"wss://": ASGIWebSocketTransport(app)}`，`app` 是扮演网关的 ASGI 应用。这个客户端必须在测试函数体内用 `async with` 打开：不进入会缺少内部任务组而报 `AttributeError`，放进 yield fixture 则在清理时报 cancel scope 跨任务退出（两种都实测过）。
- `tests/conftest.py` 有一个 autouse 兜底：凡是走到真实传输层的请求都直接失败。
- 不真实等待：token 过期、心跳间隔等用 monkeypatch 控制时间。
- 测试优先只用 `pyqbot` 的公共接口；地基自身的测试可以直接导入内部模块（如 `pyqbot._model`）。

## 首批小模块候选

| # | 模块 | 职责边界 | 官方文档 | 依赖 | 为什么适合先做 |
| --- | --- | --- | --- | --- | --- |
| 1 | 凭证 `_credentials.py` | 获取 access_token，缓存，临近过期时刷新，并发调用只发一次请求，失败映射成异常；并接到 `Client` 上（约定 6）。不管鉴权头怎么拼 | `dev-prepare/access-token.md` | `_config` `_errors` | 只有一个接口，状态机自成一体，其它所有模块都要用它 |
| 2 | 网关协议数据 `_gateway/` 内 | OpCode、Intents、上下行 payload 的编解码、关闭码该恢复 / 重新鉴权 / 放弃的分类。纯数据，不建连接 | `dev-prepare/event-emit/payload.md`、`dev-prepare/event-emit/websocket.md`、`dev-prepare/error-trace/websocket.md` | `_model` | 无 IO，全是表格到代码的映射；与 1 不碰同一个文件 |
| 3 | 错误映射（`_http.py` 的一部分） | 纯函数：状态码 + 响应头 + 响应体 → 异常或「成功」，含 `trace_id` 的提取与 `APIError` 的细分 | `dev-prepare/api-call-guide.md`、`dev-prepare/error-trace/index.md` | `_errors` | 无 IO，输入输出都能列成表；201/202 带 error body 的情况需要先想清楚 |
| 4 | 事件分发器 `_events/` 内 | 处理函数的注册表与并发调用、处理函数出错不影响其它处理函数和连接。不含事件模型，不连网关 | `dev-prepare/event-emit/payload.md`、`autogen/index.md` 的「事件」 | 无 | 纯 asyncio，独立；但对外的注册方式是易用性的核心，设计空间比前三个大 |
| 5 | 请求层 + 第一个接口 | `_http.py` 的发送与解码，加 `GET /users/@me` 打通 mixin 的写法 | `dev-prepare/api-call-guide.md`、`autogen/api/users_me.get.md` | 1、3 | 不能最先做，列在这里表明顺序 |

建议先做 1 和 2：互不依赖、不改同一个文件，一个考验异步与并发，一个考验数据建模与对上游的宽容。

已发现的官方文档出入（按 `AGENTS.md`，实现前先向用户确认，不要猜）：

- 获取 token 的返回示例里 `expires_in` 是字符串 `"7200"`，同页表格写的是 number。
- 网关鉴权的 token 格式，`dev-prepare/event-emit/websocket.md` 写 `QQBot {AccessToken}`，`dev-prepare/interface-framework/reference.md` 写 `Bot {appid}.{app_token}`；`dev-prepare/getting-started.md` 说 Token 鉴权已废弃，前者应是现行写法。
