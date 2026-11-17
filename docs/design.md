# 设计：入口、初始化与模块约定

总约束见根目录 `AGENTS.md`，接口行为以 `docs/upstream/qqbot-api-v2/` 为准。本文只定各模块之间必须一致的东西，模块内部的接口由实现者设计。除「后续模块」与 Webhook 外都已落地。

## 目标用户代码

```python
import pyqbot

# 只调接口的脚本：Client 可以单独使用
async with pyqbot.Client(APP_ID, APP_SECRET) as client:
    await client.users.send_message(user_openid, "你好")

# 事件驱动：Bot 继承 Client，接口用法完全相同
bot = pyqbot.Bot(APP_ID, APP_SECRET)


@bot.on_c2c_message
async def reply(message: pyqbot.C2CMessage) -> None:
    await message.reply("收到")


bot.run()  # 同步入口，阻塞到退出
```

## 入口与初始化

`Bot` 继承 `Client`，构造参数、生命周期与接口都相同。构造时不发请求，参数不合法立刻抛 `ValueError`：

| 参数 | 说明 |
| --- | --- |
| `app_id`、`app_secret` | 位置参数。`app_id` 接受 `str` 或 `int` |
| `base_url=` | 默认 `https://api.bot.qq.com`，可覆盖；末尾的 `/` 会去掉 |
| `timeout=` | 单次请求超时（秒），默认 30 |
| `http_client=` | 自备的 `httpx2.AsyncClient`（代理、证书、连接池；测试替身也从这里进） |

- **配置**：参数收拢成只读的 `pyqbot.Config`，经 `client.config` 读取；`repr` 不含 `app_secret`。各模块都从它取凭证、地址、超时，不各存一份。
- **`httpx2.AsyncClient` 的归属**：不传 `http_client` 时由 `Client` 自建、`close()` 时关闭；传入的归调用方，SDK 只用不关。经 `client.http_client` 取回。
- **生命周期**：推荐 `async with`；也可直接构造，用完 `await client.close()`（可重复调用）。关闭后不可复用。
- **access_token**：`await client.get_access_token()` 返回当前有效的 token（不带 `QQBot ` 前缀），首次调用才取，之后按需刷新；关闭后调用抛 `RuntimeError`。请求层在 `Client` 内部，直接用 `_credentials.AccessTokenManager`。
- **`Bot` 的运行入口**：`await bot.start()` 连接网关并分发事件，直到 `close()`（正常返回）或不可恢复的错误（抛 `GatewayError`）；没有要订阅的事件、重复调用或已关闭时抛 `RuntimeError`。`bot.run()` 是它的同步包装：`asyncio.run` 里 `async with self: await self.start()`，Ctrl+C 时干净退出、不打印 traceback。`async with bot` 只管资源，不连网关。`close()` 的顺序是断开网关、取消处理函数、关 HTTP 连接。细节见「网关连接」与「事件」。
- **接口挂在哪**：一层命名空间，`client.groups.send_message(...)`，不扁平地挂在 `Client` 上，也不多层嵌套。按用户心目中的资源分组（如 `users`、`groups`），不按文档章节。最常用的操作另在模型对象上提供快捷方法（如 `message.reply()`）。属于客户端自身的方法（如 `get_access_token()`）仍直接挂在 `Client` 上。

## 包结构与依赖方向

只允许依赖排在自己上面的模块。公共 API 只有 `pyqbot/__init__.py` 导出的名字。

```text
src/pyqbot/
  _errors.py  _config.py  _redact.py  地基，互不依赖
  _model.py       Model、RequestModel、Open*Enum、宽容解码 ← _redact
  _models/        数据模型与事件模型，按领域分文件 ← _model _gateway.intents
  _credentials.py access_token 的获取、缓存、刷新  ← _config _errors _model _redact
  _http.py        请求层：拼 URL、鉴权头、解码、错误映射 ← _credentials _errors _model _redact
  _api/           接口封装，每组一个持有请求层的小类，另有翻页工具 paging ← _http _models
  _client.py      Client = 生命周期 + 凭证 + 各组接口属性
  _gateway/       WebSocket：协议数据、连接状态机   ← _errors _model _redact
  _events/        分发器，不依赖网关连接           ← _models _errors _gateway.intents
  _bot.py         Bot(Client)：事件注册、start() / run()，把上面几块接起来
```

Webhook（未确认）：若做，是接到同一个分发器上的另一个事件源，放 `_webhook/`。签名校验要用 Ed25519，标准库没有，所以只能是可选 extra；现在不设计、不加依赖。`_events/` 不依赖网关连接（只用 `Intents`）就是为它留的位置。

## 共用地基

- **`pyqbot._model.Model`**：所有模型的基类（内部，不导出）。子类自动不可变、字段仅限关键字，不必也不要重复声明 `frozen` / `kw_only`；解码时忽略未知字段。对外只有 `to_dict()`，返回与接口 JSON 一一对应的字典。
- **`pyqbot._model.RequestModel`**：调用方构造、编码进请求体的模型（如 `Keyboard`）继承它。取默认值的字段不编码（`omit_defaults`），所以没传的可选字段不会以 `null` 发出去，`to_dict()` 里也没有。参数之间的约束（如二选一）在 `__post_init__` 里检查，抛 `ValueError`。
- **`pyqbot._model.decode(data, type_)`**：解码接口与网关数据的统一入口，宽容规则见约定 4。
- **`pyqbot._model.OpenIntEnum` / `OpenStrEnum`**：接口里的整数、字符串枚举分别继承它们，见约定 4。
- **`pyqbot._redact`**：凭证脱敏，见约定 7。
- **异常**（`_errors.py`，例外见约定 3）：
  ```text
  QQBotError        平台与网络失败的基类：message、err_code、trace_id（后两者可为 None）
  ├── APIError      平台返回了失败：另带 status_code；可按需再细分
  │   ├── PartialFailureError  批量操作部分失败（其余已生效）：另带 failed_ids
  │   └── AuditPendingError  已受理、等待人工审核：另带 audit_id（见「频道消息与内容」）
  ├── NetworkError  没拿到响应：连接失败、超时
  └── GatewayError  网关被关闭且不可恢复：err_code 为关闭码（有的话）
  ```
  另有内部的 `PayloadError`（不导出）：网关下发的一帧解不开。SDK 自己接住并丢弃这一帧，调用方见不到；等有公共接口会把它抛给调用方时（如 Webhook）再决定导出与命名。
- **`pyqbot.Config`**：见上。

## 请求层与接口分组

- **`_http.py` 的 `HTTP`**（内部）：`Client` 构造时创建，各组接口只经它发请求。`await http.request(method, path, *, type_, params=None, json=None, data=None, files=None)` 负责拼绝对地址、加 `Authorization: QQBot {token}`、显式传超时，`json` 经 msgspec 编码（`data` / `files` 则发 `multipart/form-data`，与 `json` 二选一；`request_decoded()` 同），成功时用 `_model.decode()` 解成 `type_`；`type_=None` 不解码、返回 `None`，给没有响应体的接口用。token 取自注入的 `Client.get_access_token`，所以客户端关闭后请求抛 `RuntimeError`。路径参数一律经 `path_segment()` 转义。
- **失败映射**（`dev-prepare/api-call-guide.md`）：文案前缀为 `{method} {path} 失败：`，脱敏时传 `app_secret` 与本次请求用的 token（约定 7）；`err_code`、`trace_id` 的取法同约定 3。不做自动重试和限频退避。

  | 情况 | 结果 |
  | --- | --- |
  | 拿不到响应（`httpx2.RequestError`） | `NetworkError` |
  | 2xx 且错误码为 304023 / 304024（已受理、等待人工审核） | `AuditPendingError` |
  | 响应体带非零或认不出的 `err_code` / `code`，不论状态码（文档说 201、202 会带失败结构） | `APIError` |
  | 状态码不是 2xx | `APIError` |
  | 响应体不是 JSON | `APIError`（「无法解析响应」） |
  | 2xx、没有错误码，但解不成 `type_` | `APIError`（「响应无法识别」） |

- **接口分组**：`_api/users.py`、`_api/groups.py` 各一个小类，挂成 `client.users`、`client.groups`；第一个参数分别叫 `user_openid`、`group_openid`（与模型字段同名，不用含糊的 `openid`）。频道的见下文「频道管理」与「频道消息与内容」。单聊与群聊共用 `_api/message.py` 拼请求体。`_api/interactions.py` 挂成 `client.interactions`，只有回应互动的 `ack()`。
- **发消息**：`send_message(user_openid, content=None, *, markdown, keyboard, media, card, quote, reply_to)`，单聊另有 `wakeup`；返回 `pyqbot.SentMessage`。正文 `content` 可以按位置传（约定 5 里的唯一例外）；新的内容类型照样追加仅限关键字的参数，不改已有签名。
  - `msg_type` 由 SDK 推断：传了 `markdown` 为 2、`media` 为 7、`card` 为 8，否则为 0。调用方不接触 `msg_type`。
  - 发请求前抛 `ValueError` 的组合：什么内容都没有；`markdown`、`media`、`card` 传了不止一个；`markdown` 与 `content` 同传（接口页）；`keyboard` 不随 `markdown`（`msg-btn.md`）；`wakeup` 与 `reply_to` 同传。`content` 可以随 `media`、`card` 一起发（文档没禁止，见 `errata.md`）。
  - `markdown` 接受字符串（即 `{"content": ...}`）或 `Markdown`；`media` 是 `Media`（上传接口的响应模型，只发出 `file_info`）；`card` 是 `Card`（即 `card.content`，`type` 固定为 `tuwen`）。
  - `quote` 填 `message_reference.message_id`：接受引用索引字符串、`SentMessage`（取 `ext_info.ref_idx`）或同场景收到的消息（取 `msg_idx`，即 `message_scene.ext` 里的 `msg_idx`）；取不到时抛 `ValueError`。
  - 模型上的快捷方法（如 `message.reply()`）参数与 `send_message` 相同，只是固定了 `reply_to`。`C2CMessage.upload()`、`GroupMessage.upload()` 同理固定了上传目标，常见写法是 `await message.reply(media=await message.upload(path="cat.png"))`。
- **被动回复**：`reply_to` 的类型是场景标记类（`users` 收 `C2CReplyTarget`，`groups` 收 `GroupReplyTarget`，见「事件」），所以把群聊的回复对象传给单聊接口时 pyright 报错。收到的消息填 `msg_id`（取 `id`），其余事件填 `event_id`（取 `event.event_id`，为 `None` 时抛 `ValueError`）。两种都由 `next_msg_seq()` 在这个对象上从 1 递增 `msg_seq`，发送失败也不回退，请求在本地被拒（`ValueError`）时不占用；调用方不用管。
- **其它消息操作**：撤回是 `recall_message(user_openid | group_openid, message)`，`message` 可以是消息 ID、`SentMessage`，群聊还可以是收到的 `GroupMessage`（机器人是管理员时）。「正在输入」是 `client.users.send_typing(user_openid, *, seconds=60, reply_to=None)`（`msg_type=6`，只有单聊），也是被动回复、占用 `msg_seq`；文档没有它的响应体，所以不解码、返回 `None`。
- **分页接口**：方法名为 `iter_<资源>`，返回 `AsyncIterator`，调用方写 `async for x in client.groups.iter_blacklist(...)`。方法内只写「怎么取一页」的 `fetch(cursor)`，返回 `_api.paging.Page(items, next)`，再 `return paginate(fetch)`：
  ```python
  def iter_blacklist(self, group_openid: str) -> AsyncIterator[BlacklistedUser]:
      async def fetch(cursor: str | None) -> Page[BlacklistedUser, str]:
          params = {"limit": 100} | ({"cursor": cursor} if cursor else {})
          page = await self._http.request("GET", path, type_=BlacklistPage, params=params)
          return Page(page.users, page.next_cursor)

      return paginate(fetch)
  ```
  `fetch(None)` 取第一页。`next` 为 `None`、空串或与刚用过的相同时结束；游标的类型随接口（字符串、`cookie`、偏移量等），`is_end` 之类的结束标志在 `fetch` 里换成 `next=None`，`before/after` 形式把下一页的锚点放进 `next`。要整页信息（总数等）的接口另给一个取单页的方法，不经它。
- **网关地址**：`Client._get_gateway_url()` 调 `GET /gateway`，由 `Bot.start()` 作为 `get_url` 注入网关连接。
- **富媒体上传**（`_api/upload.py`，单聊与群聊共用）：`client.users.upload(user_openid, *, path, url, data, file_name, file_type, send)`，群聊同形，返回 `Media`。协议步骤对调用方不可见。本地文件读不了抛 `OSError`（约定 3）。
  - **分派**：`path`、`url`、`data` 恰好传一个，否则抛 `ValueError`。`url` 交给平台下载；本地数据（读 `path` 或 `data`）不超过 `INLINE_LIMIT`（3 MiB，base64 后约 4 MiB，留在文档的 5M 之内）时 base64 后放进 `file_data`，更大的分片上传。`file_type` 不传就按扩展名推断（`url` 取路径部分），推不出抛 `ValueError`。`file_name` 默认取 `path` 的文件名，`data` 必须给，`url` 不能给。`srv_send_msg` 即 `send=`，总是显式发出（文档没写默认值）。
  - **分片**：在线程里逐块读文件，算出 MD5、SHA1、`md5_10m` 后调 `upload_prepare`；按响应顶层的 `block_size` 切片（序号为 i 的分片从 `(i - 最小序号) * block_size` 起，到文件末尾为止；文档说序号从 0 开始，实测从 1 开始），每片在线程里读出、算 MD5，PUT 成功后调 `upload_part_finish`（`part_index` 原样填平台给的序号，`block_size` 填这一片的实际字节数），全部完成后带 `upload_id` 调 `/files`。只有正在上传的分片在内存里，占用约为并发数 × `block_size`。预上传响应的 `block_size` 不是正整数、`parts` 的 `index` 不是从 0 或 1 开始的连续整数（宽容解码丢掉坏分片后会断号）时按「响应无法识别」抛 `APIError`；分片数与文件大小对不上不在本地判断，由合并接口拒绝。
  - **并发**：`TaskGroup` + 信号量，并发数取 `upload_config.concurrency`，限制在 1～8。一片最终失败就取消其余、不再合并，抛出那个异常本身而不是异常组。
  - **重试**：只有 PUT 与 `upload_part_finish` 重试（平台为分片下发了 `upload_config`；预上传与合并照常不重试），两者各自计时。只重试临时性失败：`NetworkError`、HTTP 5xx 或 429、`err_code` 40093001（「请重试」）。每次失败后等 `retry_delay` 秒再试；等完会超过从这一步首次尝试算起的 `retry_timeout` 秒就不再重试，抛出最后一次的异常。其它失败（如对象存储 403 签名失效）立即抛出。
- **对象存储的 PUT**：`HTTP.put_presigned(url, content, *, content_type=None)` 自己构造 `httpx2.Request`，经 `client.http_client` 的 `send()` 发出：不合并客户端默认的 headers、cookies、params（params 会替换掉签名查询串），`auth=None` 关掉客户端的鉴权，不跟随重定向，显式传超时；不拼 `base_url`、不解析响应体，返回 2xx 的响应（素材库要读 `ETag`）。错误语义同 `request()`：拿不到响应抛 `NetworkError`（两者共用 `_network_error()`），地址解析不了也是；非 2xx 抛 `APIError`（`err_code`、`trace_id` 为 `None`，文案附上对象存储 XML 里的 `<Code>`）。预签名地址的查询串是临时签名，按凭证对待：文案只写 `PUT scheme://host/path`；脱敏时在凭证之外再替换整个地址、查询串和其中不短于 8 个字符的参数值（编码前后两种写法），异常链里出现它们就整条丢掉；持有预签名地址的模型（含公开的 `MediaImage.preview_url`）把它列进 `_secret_fields`。SDK 不改动第三方库的 logger：调用方自己开启 httpx2 的 INFO 日志时，日志里会有预签名地址（短期有效，只对这一次上传有效）。
- **素材库**（`_api/images.py`，挂成 `client.images`，属于机器人本身）：`upload(*, path, data, file_name)` 返回 `MediaImage`，`iter_images()`，`delete(image)`。Content-Type 由扩展名决定（png、jpg/jpeg、gif、webp），其它扩展名抛 `ValueError`；大小与数量上限不在本地检查，由平台在 prepare 时拒绝，所以先流式算哈希，prepare 通过后才把整个文件读进内存 PUT。`complete` 的 `md5` 取 PUT 响应的 `ETag`（去掉引号），没有时退回本地算的 MD5。列表的 `total` 暂不暴露。
- **机器人自身**：只关于这个机器人、没有可以归组的资源的接口直接挂在 `Client` 上：`get_me()`（`GET /users/@me`）、`generate_share_link()`（`POST /v2/generate_url_link`，只返回链接字符串）。机器人全局的配置有自己的资源，仍按约定 5 分组：`client.menu`（单聊自定义菜单，`get()` / `set(items)`）、`client.panels`（指令面板）。
- **菜单与面板的模型**：`MenuItem`、`PanelItem` 等同时用于解码与请求体（继承 `RequestModel`、不在 `__post_init__` 里校验，所以取回的内容可以原样设置回去，未知的 `type` 也不会让解码失败）。数量、长度、https 由平台检查（错误码 400300xx），本地只拦平台会静默忽略的组合：面板的 `user_openids` 只能配 c2c、`group_openids` 只能配 group。`create()` 传了关联对象即 `target_type=specific`，否则为 `all`；增删关联对象是 `add_targets()` / `remove_targets()`，`op` 不对外。整体覆盖内容叫 `set()`（同菜单），与只改传入字段的 `update()` 区分。
- **流式消息**（只有单聊）：`client.users.stream_message(user_openid, *, reply_to, markdown=True, coalesce=True)` 与 `C2CMessage.reply_stream()` 返回 `StreamMessage`，不发请求；`async with` 体里 `await stream.append(text)` / `replace(full_text)` 追加内容，退出时发结束分片。
  - **合并分片**（`coalesce=True`，默认）：分片必须等上一个的响应（要用它的 `stream_msg_id`，序号也得按顺序到），每片至少一次网络往返；实测跨境约 0.4 秒，大模型逐字输出时一片几个字会显得很慢（`errata.md`）。所以 `append()` / `replace()` 只把内容放进待发区就返回，由一个后台任务每次把待发区里攒下的全部内容合成一片发出，同时只有一个请求在路上：网络慢就多攒一些，吐字快也不会堆积请求。待发区里接连的 `append` 拼接；`replace` 整个替换，之后的 `append` 接在它后面（合起来仍是 `replace`）。发送失败（含客户端已关闭）先存起来，在下一次 `append()` / `replace()` / `finish()`（含正常退出 `async with`）时抛出一次。用法错误（没有事件 ID 的回复对象）仍当场抛。`finish()` 先等待发区发完（`shield`，调用方被取消不打断在途的分片）再发结束分片；被取消退出 `async with` 时不等、也不取消发送任务，攒下的内容照常发出，只是没有结束分片。`coalesce=False` 时每次调用直接发一片、等它完成，以下几条的锁与取消语义都按这种方式描述。
  - 分片的填法：`index` 从 0 起每发一个分片（含结束分片，发送失败的也算）加 1；`stream_msg_id` 第一个分片不填，之后填第一个分片响应的 `id`；`msg_id` / `event_id` 与 `msg_seq` 在第一个分片时经 `reply_fields()` 取一次，所有分片共用，所以整条流式消息只占用回复对象的一个 `msg_seq`（文档示例如此，见 `errata.md`）。同一个对象的分片用锁串行发出。
  - `append("")` 不发请求。`append()` 与 `replace()` 可以混用，每个分片带自己的 `input_mode`。结束分片是 `input_mode=append`、`content_raw=""`、`input_state=10`；一个分片也没发过时退出不发任何请求。
  - `async with` 体里抛 `Exception` 时仍发结束分片（免得用户那边一直显示生成中），结束分片失败只记 WARNING，原异常照常抛出；被取消等 `BaseException` 不发，不拖住取消。
  - 分片发送失败（含请求在途时被取消）后平台状态未知，这条流式消息就此终止：之后 `append()` / `replace()` 抛 `RuntimeError`，退出时不再发结束分片。还在等锁时被取消的调用什么也没发，不占 `index`，也不影响这条流。结束后再 `append()` 也抛 `RuntimeError`；`finish()` 可重复调用。
  - 每个分片的响应是 `SentStreamChunk`（`SentMessage` 的子类，多一个 `remain_msg_len`），经 `stream.last_sent` 取最近一个；SDK 不按 `remain_msg_len` 做任何判断。`is_wakeup` 暂不提供（与发消息页的说法冲突，见 `errata.md`）。
- **群管理**（`_api/groups.py`，挂在 `client.groups` 上）：`get`、`get_bot_state`、`iter_members`、`get_member`、`remove_members`、`iter_blacklist`、`add_to_blacklist` / `remove_from_blacklist`、`get_mute_settings`、`mute_members` / `unmute_members` / `update_member_mutes`、`iter_join_requests`、`approve_join_request` / `decline_join_request`。白名单、内邀、管理员等前提写在各方法的 docstring 里，本地不检查，由平台拒绝。GET 的 `cursor`、`limit` 一律放查询串、不发请求体（文档的出入见 `errata.md`），翻页时 `limit` 取文档给的最大值、不对调用方暴露。批量接口（含频道的批量禁言）全部成功时返回 `None`；平台报告部分失败时抛 `PartialFailureError`（继承 `APIError`），文案写明是哪一步失败（如「成员已移出，但 N 个未能加入黑名单」）。平台给失败清单时 `failed_ids` 照它；只给成功清单时（频道批量禁言）把请求的 ID 展开一次，求出没列在成功清单里的。它要用成功响应的状态码与 trace_id，所以这类接口经 `HTTP.request_decoded()` 发请求，结果的 `partial_failure()` / `failure()` 构造已脱敏的异常。成败清单（以及 `remove_members_result` 这类表示成败的字段）在模型里写成 `object`，经 `_model.outcome_ids()` 在 `__post_init__` 里校验：缺失或 `null` 为空清单，类型不符就让整条响应「无法识别」，不能像普通可选字段那样退回默认值，否则成败会被算错。禁言分 `mute_members()`（`add`）与 `update_member_mutes()`（`update`，改正在禁言中的到期时间）；全员禁言只能查。入群申请的数据是 `GroupJoinRequestInfo`（`iter_join_requests()` 的结果），事件 `GroupJoinRequest` 继承它与 `Event`（同 `GuildCreate(Guild, Event)`），另有 `approve()` / `decline()`。
- **入群自动审批策略**（`_api/join_strategies.py`，挂成 `client.join_strategies`，属于机器人本身）：`iter_strategies()`、`create()`、`update()`、`add_groups()` / `remove_groups()`、`delete()`、`execute()`、`add_whitelist_users()` / `remove_whitelist_users()`；`strategy` 参数接受 `strategy_id` 或 `JoinStrategy`。`group_openids` 与 `group_ids` 恰好传一个，否则 `ValueError`。修改接口的响应只有启用状态与过期时间，所以 `update()` 等返回 `None`。
- **时间与批量参数**（`_api/params.py`，频道的禁言、日程也用它）：
  - **时间参数：输入校验统一，编码随接口**。调用方传带时区的 `datetime`（没有时区抛 `ValueError`：无法知道指哪个时区）或正的 `timedelta`（从现在起算），先转成 UTC（带秒级偏移的时区直接输出不是合法的 RFC3339），不足一秒（毫秒编码时不足一毫秒）向上取整：截止时刻晚一点无害，截掉则可能早于现在。编码随接口：RFC3339 字符串（`rfc3339()`，如 `2026-08-05T03:23:05+00:00`：群禁言、入群策略）、Unix 秒的字符串（`unix_seconds()`：频道禁言）、Unix 毫秒的字符串（`unix_millis()`：日程）。当前时间取自 `params.utc_now()`，测试替换它来固定时钟。响应里的时间照「事件」的时间戳规则解码。
  - 接受多个 ID 的参数写成 `str | Iterable[str]`，单个字符串当作一个元素（`str_list()`），免得被拆成字符；QQ 号、群号这类整数同理写 `int | Iterable[int]`。单次数量上限写在 docstring 里，本地不检查，也不自动拆成多次请求（部分失败难以表达）。
  - 接口里的 `on|off`、`add|del` 之类，公共签名用 `bool`（如 `enabled=`）或分开的方法（如 `add_to_blacklist` / `remove_from_blacklist`）表达，请求体里用 `OpenStrEnum`；响应模型保留接口原样的字段，字段类型是从顶层导出的枚举（如 `JoinStrategyStatus`，否则调用方无法标注或构造），另给便捷属性（如 `JoinStrategy.enabled`）。
- **频道管理**（`_api/guilds.py`、`_api/channels.py`，模型在 `_models/guild.py` 与 `guild_manage.py`）：
  - **分组边界**：路径以 `/guilds/{guild_id}` 或 `/users/@me/guilds` 开头的挂在 `client.guilds`：频道列表与详情、子频道的列出与创建、成员、身份组（含成员加入、移出身份组）、禁言、接口权限、消息频率设置。路径以 `/channels/{channel_id}` 开头的挂在 `client.channels`：子频道的详情、修改、删除、在线人数，以及子频道的用户、身份组权限；频道消息与内容的接口也加在这个类里。资源本身的读写叫 `get` / `update` / `delete`，其余方法名带上资源（`list_roles`、`add_member_role`）。
  - **权限位**：子频道权限是 `ChannelPermission`（`enum.IntFlag`，未知位保留），接口里的十进制字符串由 SDK 转换：查询返回 `ChannelPermission`（十进制字符串在解码阶段校验，`int()` 失败也映射成 `APIError`），修改是 `update_*_permissions(..., add=, remove=)`，不传的一侧发 `"0"`。`Channel.permissions` 保留原样的字符串，另给 `Channel.permission_flags`（认不出为 `None`，同日程的时间属性）。
  - **列表的两种形状**：表格是 `{guilds: [...]}`、示例是裸数组的接口（频道、子频道、成员列表），经 `request_decoded()` 解成任意 JSON，数组与对象都包成 `{key: [...]}` 交给 `decode()`，坏条目只丢它自己（对象里 `key` 缺失或类型不对时为空列表）；根既不是数组也不是对象时，经 `failure()` 抛「响应无法识别」的 `APIError`（带状态码与 trace_id）。
  - **翻页**：频道列表与成员列表以本页最后一条的 ID（成员是 `user.id`）作 `after`，空页结束；最后一条解不出非空 ID 时抛 `APIError`，不当作结束（否则漏掉后面的条目）。没有 `user.id` 的成员跳过；平台会重复上一页的成员，迭代器只记上一页的用户 ID 去重，内存不随人数增长。身份组成员以 `next` 作 `start_index`，空页或 `next` 为 `"0"` 时结束。
  - **禁言**：时间参数见「时间与批量参数」（Unix 秒），只发 `mute_end_timestamp`；解除是单独的 `unmute_*`，两个字段都发 `"0"`。全员、批量、单个成员各一对方法（`mute_all`、`mute_members`、`mute_member`）；批量的部分失败见「群管理」。成员移出时拉黑的选项与群管理同名（`add_to_blacklist=`）。
  - **前提**：私域、管理员等前提写在各方法 docstring 的摘要里，本地不检查。

## 频道消息与内容

- **接口分组**：`client.channels`（子频道：消息、表态、精华、日程、论坛、音频）、`client.guilds`（频道公告）、`client.dms`（频道私信）。子频道公告（`/channels/{channel_id}/announces`）官方已弃用、让改用精华消息，不实现。子频道与私信共用 `_api/guild_message.py` 拼请求体。
- **发消息**：`send_message(channel_id, content=None, *, markdown, keyboard, embed, ark, image, image_path, image_data, quote, reply_to)`，私信同形（第一个参数是私信会话的 `guild_id`），返回 `GuildMessage`。没有 `msg_type`，各内容字段原样放进请求体，可以同时给。
  - 发请求前抛 `ValueError` 的组合：什么内容都没有（`content`、`markdown`、`embed`、`ark`、图片都没给）；`image`（URL，由平台转存）、`image_path`、`image_data` 传了不止一个；`keyboard` 不随 `markdown`。发消息页没列 `keyboard`，照单聊群聊接受（见 `errata.md`）。
  - `embed`、`ark` 是请求模型 `Embed`、`Ark`（与消息里解码用的 `MessageEmbed`、`MessageArk` 分开）；`quote` 是消息 ID 或 `GuildMessage`，填 `message_reference.message_id`，`ignore_get_message_error` 暂不提供。
  - **本地图片**：`image_path` / `image_data` 时整个请求改为 `multipart/form-data`：图片放在 `file_image`（`image_data` 的文件名固定为 `image`），其余字段中字符串原样、对象与数组写成 JSON 字符串（`send.md`）。文件在线程里读出，读不了抛 `OSError`（约定 3）。
  - **被动回复**：`reply_to` 照单聊群聊用场景标记限定（`ChannelReplyTarget` / `DirectMessageReplyTarget`），填 `msg_id` / `event_id`，但不带 `msg_seq`：发消息页没有这个字段，所以 `reply_fields(target, seq=False)` 既不发也不占用计数（见 `errata.md`）。
  - **待审核**：响应是 2xx 且错误码为 304023 / 304024 时，请求层（`_raise_if_audit_pending()`，在判定失败之前调用）抛 `AuditPendingError`，`audit_id` 取响应体的 `data.message_audit.audit_id`（缺了为 `None`，经脱敏）。只看错误码与 2xx，不限接口；非 2xx 带这两个码仍是普通 `APIError`。审核结果由 `MESSAGE_AUDIT_*` 事件推送，SDK 不替调用方等待。
- **快捷方法**：`ChannelMessage`（含 `ChannelAtMessage`）、`MessageReaction*`、论坛的 `Forum*` 事件的 `reply()` 发到事件的 `channel_id`，`DirectMessage.reply()` 发到它的 `guild_id`，参数同 `send_message`。频道成员事件没有子频道，不加 `reply()`，作为 `client.channels.send_message(channel_id, ..., reply_to=event)` 的 `reply_to`。`Interaction.reply()` 见「事件」的「多场景事件的回复分派」。
- **撤回**：`recall_message(channel_id, message, *, hidetip=False)`，私信同形；`hidetip` 总是显式发出（`true` / `false`）。
- **表情表态**：`add_reaction()` / `remove_reaction()`（`channel_id, message, emoji`，路径用 `emoji.type` 的整数值与 `emoji.id`）；`iter_reaction_users()` 照「分页接口」，第一页只发 `limit`（默认 20，只在第一页有效），之后只发上一页的 `cookie`，`is_end` 为真时结束。
- **「全部」的 message_id**：精华消息的 `all` 会清空全部，所以单独给 `remove_all_pins()`，`remove_pin(..., "all")` 抛 `ValueError`；频道公告同一时间只有一个，`delete_announcement(guild_id)` 不传 `message` 就是 `all`（推荐子频道类型的公告只能这样删）。
- **时间参数**：日程的 `start`、`end` 见「时间与批量参数」（Unix 毫秒；`since` 只收 `datetime`）。日程的时间字段在接口里是毫秒字符串，模型照原样保留，另给 `Schedule.start` / `end` 属性（UTC 的 `datetime`，认不出为 `None`）。
- **顶层是数组的响应**（如日程列表）：`type_` 写 `tuple[模型, ...]`，`decode()` 照「宽容解码」逐个元素处理，不合法的元素只丢掉它自己。「频道管理」的列表接口另用 `_list_items()`：那些接口的表格与示例形状不一致（对象或数组），要先取任意 JSON 再包装；只有数组一种形状的接口直接用前者。
- **论坛**：`list_threads()` 返回 `ForumThreadList`（文档没有翻页参数，`finished` 为 `False` 时也取不到后面的），`get_thread()` 去掉 `thread` 外壳返回 `ForumThread`；`publish_thread()` 只返回 `ForumPublishTask`，结果看 `FORUM_PUBLISH_AUDIT_RESULT`。
- **音频**：`control_audio(channel_id, status, *, audio_url, text)`：`START` 必须有 `audio_url`，其它操作不能带 `audio_url`、`text`（`audio/model.md`）；上下麦是 `join_mic()` / `leave_mic()`。

## 网关连接

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

## 事件

- **事件模型**（`_models/`）：每种事件一个 `Event` 的子类，收到的消息继承 `ReceivedMessage`（带 `id`）。子类用 `ClassVar` 声明 `event_name`（Dispatch 的 `t`）与 `intent`。绑定的 `Client`、事件 ID 与回复计数存在实例的 `__dict__` 里（`dict=True`），`repr`、`to_dict()`、编码与相等性只看字段。
- **事件 ID**：分发器把 payload 外层的 `id` 经 `bind_event_id()` 记到事件上，对外是只读的 `event.event_id`（不是分发来的事件为 `None`）。被动回复的 `event_id` 取它（文档的出入见 `errata.md`）。
- **可以被动回复的事件**（`_models/event.py`）：`ReplyTarget` 是基类，场景用无字段的标记子类表示：`C2CReplyTarget`、`GroupReplyTarget`，频道另有两个（见下文「频道的事件」），都从顶层导出。`ReceivedMessage` 也是 `ReplyTarget`，所以 `C2CMessage(_ChatMessage, C2CReplyTarget)` 这样多继承即可。多个场景都会发生的事件（如 `INTERACTION_CREATE`）同时继承各场景的标记，场景不对时由平台拒绝。
- **模型上的行为**：分发器在调用处理函数前 `bind_client(event, client)`，`message.reply()` 这类快捷方法经 `self._bound_client()` 调用接口；没有绑定时抛 `RuntimeError`。同一事件的所有处理函数拿到同一个对象，所以 `msg_seq` 在它们之间也是递增的。
- **常用信息一步拿到**：嵌在发送者里的 openid 在消息上另有属性（`message.user_openid`、`message.member_openid`）；调用方写类型标注或构造会用到的嵌套类型（发送者、附件、互动的 `InteractionData`、论坛富文本的段落与元素等）从顶层导出，只给 SDK 自己用的外壳不导出。文本字段缺失与空串没有区别时默认 `""`（如 `content`），省得处处判断 `None`。
- **注册**（`Bot`）：每种事件一个装饰器 `@bot.on_<事件>`，原样返回处理函数；类型写成 `[F: Handler[事件模型]](handler: F) -> F`，参数类型不对时 pyright 报错。处理函数必须是 `async def`，否则注册时抛 `TypeError`。同一事件可以注册多个。
- **Intents**：默认按已注册的处理函数推导（`Bot._resolve_intents()`），`Bot(..., intents=...)` 传入则以它为准。`Bot.start()` 用它 Identify，所以 `start()` 之后再注册的处理函数不会改变订阅。
- **分发器**（`_events/dispatcher.py`）：`dispatch(payload, client)` 同步、立刻返回，`payload` 只需有 `t` 与 `decode_data()`（`GatewayPayload` 满足），所以不依赖网关。没有处理函数的事件与未知事件直接忽略、不解码，解码失败（`PayloadError`）记 WARNING 后丢弃；每个处理函数一个任务（`eager_start=False`，装了 eager 任务工厂也不在 `dispatch()` 里开跑），异常记 ERROR，不影响其它处理函数。
- **日志不带凭证**：处理函数名取函数自身的 `__qualname__`（`partial` 逐层取被包的函数，可调用对象取类名），不用 `repr()`，因为 `partial` 的 repr 带着绑定的参数；任务名、日志与注册时的 `TypeError` 都用它。处理函数的异常链先格式化成文本，经 `Bot` 注入的 `Client._redact_secrets` 脱敏（约定 7）再写日志，不交给 `logger.exception`。
- **关闭**（`await aclose(grace_period=5)`）：可以重复、并发调用，一定返回。只有第一次调用标记关闭并取消处理函数，每个任务只取消一次，之后的调用只等待，不打断处理函数的清理。在处理函数里调用（`bot.close()` 也一样）只请求停止、立刻返回，不等任何处理函数，所以处理函数之间不会互相等待。在外面调用时最多等 `grace_period` 秒，还没结束的（吞掉了取消）记一条 WARNING 后不再等。`Bot.close()` 依次断开网关、调它、关 HTTP 连接。
- **加一种事件**：在 `_models/` 按官方文档定义模型（声明 `event_name`、`intent`，只把 SDK 要用的字段写成必填，需要的话加 `reply()`），从顶层导出；在 `Bot` 上照 `on_c2c_message` 加一个装饰器。分发器与 Intents 推导不用改。
- **加一种可以被动回复的事件**：在上一条之外，让模型继承发消息接口文档里它所属场景的标记类（`event_id` 支持的事件列在 `event_id` 一行），如 `class FriendAdd(C2CReplyTarget)`。`send_message` 的签名、`msg_seq` 与 `event_id` 的填写都不用改。需要快捷方法时照 `C2CMessage.reply()` 写 `reply()`，`reply_to=self`。
- **单聊、群聊的通知类事件**（`_models/notice.py`、`_models/interaction.py`）：类名照事件名去掉下划线（`FRIEND_ADD` → `FriendAdd`，`C2C_MSG_REJECT` → `C2CMsgReject`），装饰器是 `on_` 加事件名的小写（`on_friend_add`、`on_group_member_add`）；`INTERACTION_CREATE` 是 `Interaction` / `on_interaction`。可用 `event_id` 回复的是 `FriendAdd`、`C2CMsgReceive`、`GroupAddRobot`、`GroupMsgReceive` 与 `Interaction`，都有 `reply()`，参数同所属场景的 `send_message`。除 SDK 要用的 openid 之外，事件的主体（如 `GroupMemberAdd.member_openid`、`GroupJoinRequest.join_request_id`，以及审批接口要用的 `GroupJoinRequest.member_openid`）也是必填，缺了这条事件就没有意义。
- **时间戳**：RFC3339 字符串解成带时区的 `datetime`（如消息的 `timestamp`、`GroupJoinRequest.apply_at`）；整数的 Unix 秒保持 `int`，字段名照官方 JSON（`timestamp`、`subscribe_ts`）。不转成 `datetime`：`to_dict()` 要与接口 JSON 一一对应，`decode()` 严格解码也不会把整数当成时间。调用方要时间对象时写 `datetime.fromtimestamp(event.timestamp, UTC)`。
- **字段相同、事件名不同的消息**：`GroupMessage`（`GROUP_MESSAGE_CREATE`，群里的全部消息）是基类，`GroupAtMessage`（`GROUP_AT_MESSAGE_CREATE`）继承它、只覆盖 `event_name`；频道的 `ChannelMessage` / `ChannelAtMessage` 同理。类名与装饰器对应：`on_group_message` 收 `GroupMessage`，`on_group_at_message` 收 `GroupAtMessage`。分发只按事件名找处理函数，不看继承，所以 `on_group_at_message` 收不到全量消息。群设置为「获取群内全部消息」时，平台连 @机器人 的消息也只推 `GROUP_MESSAGE_CREATE`（`content` 带 `<@机器人>` 前缀，`mentions` 里机器人那一项 `is_you` 为真，见 `errata.md`），所以给 `GroupMessage` 加了 `mentions_me`，`GroupAtMessage` 上恒为真，处理函数不必关心是哪种设置；反过来，标注为 `GroupMessage` 的处理函数可以两处都注册。接受群消息的参数（`quote`、`recall_message`）写基类。以后遇到同类情况照此办理：更宽的事件做基类，窄的加限定词（`At`）。消息里的成员是 `GroupMessageMember`，成员查询的结果是 `GroupMember`（与频道的 `GuildMember` 对应）。
- **`Interaction` 的两个 ID**：字段 `id`（`d.id`）只用于回应互动 `ack()`（`PUT /interactions/{id}`）；被动回复用 `event_id`（payload 外层的 `id`），与其它事件一样由 `reply_fields()` 填写。**自动回应**：客户端只等约 1 秒（`errata.md`），所以 `Bot(auto_ack=True)`（默认）在第一次注册互动处理函数时，先插一个内部处理函数，对回调按钮与快捷菜单回应「成功」。分发器按注册顺序启动任务，回应最先发出，与用户的处理函数并发。要对部分互动回应别的结果，给 `auto_ack` 传判断函数（返回假的留给处理函数自己 `ack()`，抛异常时不回应），或传 `False` 全部自己回应。SDK 自建的 HTTP 客户端把空闲连接保留 `KEEPALIVE_EXPIRY`（60 秒，httpx2 默认 5 秒），免得回应时重新握手；传入自己的 `http_client` 时不改它。重复回应平台不报错，本地不拦。
- **多场景事件的回复分派**：`Interaction.reply()` 按 `chat_type` 选接口，没有时按 `scene`，三个场景：单聊发给 `user_openid`，群聊发到 `group_openid`，频道发到 `channel_id`（不带 `msg_seq`，见「频道消息与内容」）。参数是两套发消息接口的并集，返回 `SentMessage | GuildMessage`；只有一边支持的参数（`media`、`card`、`SentMessage` 引用只用于单聊群聊，`embed`、`ark`、图片、`GuildMessage` 引用只用于频道）在另一边传了抛 `ValueError`。认不出场景、缺少该场景的 openid / `channel_id` 也抛 `ValueError`，都在发请求之前。
- **频道的事件**（`_models/guild.py`、`guild_message.py`、`forum.py`、`audio.py`）：类名与装饰器的规则同上（`GUILD_MEMBER_ADD` → `GuildMemberAdd` / `on_guild_member_add`）。消息照群聊：`MESSAGE_CREATE` 是 `ChannelMessage` / `on_channel_message`，`AT_MESSAGE_CREATE` 是它的子类 `ChannelAtMessage` / `on_channel_at_message`，`DIRECT_MESSAGE_CREATE` 是 `DirectMessage` / `on_direct_message`；`PublicMessageDelete` 继承 `MessageDelete`。
  - **数据模型与事件**：频道里的对象另有纯数据模型（`Guild`、`Channel`、`GuildUser`、`GuildMember`、`GuildRole`、`GuildMessage` 等），供事件嵌套与频道接口返回；同形的事件直接继承它（`GuildCreate(Guild, Event)`），处理函数拿到的事件也能当数据模型用。`GuildMessage`（官方的 Message 对象）继承 `ReceivedMessage`：msgspec 只允许一个带字段的基类，而 `reply_fields()` 靠它认出消息；它没有 `event_name`、不带场景标记，不会被分发，也不能作为 `reply_to`。频道成员事件的 `user` 必填，所以不继承 `GuildMember`（那里的 `user` 可选：消息里的 `member` 没有它）。
  - **场景标记**：`ChannelReplyTarget`（`POST /channels/{channel_id}/messages`）与 `DirectMessageReplyTarget`（`POST /dms/{guild_id}/messages`）。继承前者的是 `ChannelMessage`、`ChannelAtMessage`（用 `msg_id`），`send.md` 的 `event_id` 列表里的 `GuildMember*`、`MessageReaction*`、`ForumThread*`、`ForumPost*`、`ForumReply*`，以及 `Interaction`；继承后者的只有 `DirectMessage`。
  - **发送接口与 `reply()`**：见「频道消息与内容」。
  - **没有 Intent 位的事件**（`OPEN_FORUM_*`、`AUDIO_OR_LIVE_CHANNEL_MEMBER_*`）：`intent` 为 `Intents(0)`，不编造位。注册了照常分发，但不参与推导：调用方须在构造 `Bot` 时传入完整的 `intents`；只注册这类处理函数又不传时，`start()` 照常抛「没有要订阅的事件」。
  - **论坛富文本与 ID**：论坛事件的 `title`、`content` 是 `str | tuple[ForumRichObject, ...]`，两种原样保留（模型写字符串，事件示例是数组）；字符串可能是 JSON 形式的 RichText，由调用方按需用 `ForumRichText.from_json()` 解析，SDK 不猜。论坛事件与富文本里的 ID 在示例里有时是数字：对外标注为 `str`，运行时也收整数并在 `__post_init__` 里转成字符串（`forum.py` 的 `_Id`），`to_dict()` 里随之是字符串。其它频道事件的示例里 ID 都是字符串，不放宽。

## 后续模块要遵守的约定

1. **命名与可见性**：内部模块里要给别的模块用的名字不加下划线，`_` 前缀的名字只在本模块、本类及其子类内使用（pyright strict 会拒绝越界访问）。是否公共只看有没有从包顶层导出；新增导出同时更新 `__all__`。
2. **地址与超时只认 `Config`**：请求一律用 `config.base_url + "/path"` 的绝对地址，并显式传 `timeout=config.timeout`；不依赖 `httpx2.AsyncClient` 自身的 `base_url` / `timeout`，这样自建与注入的客户端行为一致。所有网络 IO（含 WebSocket）都走 `client.http_client`，任何模块不得另建 `httpx2` 客户端。
3. **异常**：平台与网络的失败只抛 `QQBotError` 的子类，新增的类都放 `_errors.py` 并导出。只有基类带 `QQBot`，子类不加前缀、以 `Error` 结尾，且不与内置异常重名。`httpx2`、`msgspec` 的异常（含超深嵌套 JSON 引起的 `RecursionError`）不得漏给用户，包装后用 `raise ... from` 保留原因。响应体里 `err_code` 与 `code` 任一个非零就算失败（获取 token 的接口只有 `code`，且业务失败时 HTTP 仍是 200）；两个都有时异常的 `err_code` 取响应体的 `err_code`，`code` 是旧式错误码（见 `errata.md`）；`trace_id` 优先取响应头 `X-Tps-trace-ID`，其次响应体。批量操作只有部分对象失败时抛 `PartialFailureError`，不用返回值表达失败（见「群管理」）。例外只有两类，都抛内置异常，docstring 的 Raises 写明：
   - 用法错误：参数不合法抛 `ValueError`，关闭后再用等生命周期错误抛 `RuntimeError`，都在发请求之前。
   - 本地文件读不了（不存在、无权限、读取中被删）原样抛 `OSError`：调用方自己给的文件出错时，标准库异常更符合预期。
4. **模型**：继承 `Model`。可选字段写 `X | None = None`，不向外暴露 `msgspec.UNSET`；集合字段用 `tuple[X, ...]`、默认 `()`（写 `= []` 会触发 ruff RUF012）；接口字段名不是 snake_case 时用 `msgspec.field(name=...)`。内部可以随意用 msgspec，但公共签名里不出现它的类型。
   - **宽容解码落到字段级**：只有 SDK 自己要用的字段，以及调用方拿不到就没法继续的字段（如 `SentMessage.id`）才写成必填；其余字段都给默认值。解码一律经 `_model.decode()`：有默认值的字段类型不符时退回默认值（嵌套模型逐层处理；`tuple[模型, ...]` 逐个元素处理，清理后仍不合法的元素只丢掉它自己），只有必填字段缺失或类型不符才让整条数据失败。
   - **枚举容忍未知取值**：取值互斥的枚举继承 `OpenIntEnum`（整数）或 `OpenStrEnum`（字符串，如 `scope: c2c|group`），字段直接写枚举类型。未知的取值得到伪成员：是该枚举的实例，`name` 为 `"UNKNOWN"`，`value`、比较与 `to_dict()` 都是原值；每次得到的是不同对象，只用 `==` / `match` 的值模式比较，不用 `is`。msgspec 解码按 JSON 类型严格校验（`true`、`1.0` 不算整数，数字不算字符串）；直接调用 `MyEnum(True)` 则按标准库语义命中值相等的成员。
   - **请求模型**：调用方构造的模型继承 `RequestModel`，字段名与官方 JSON 一致；常用写法另给工厂类方法（如 `Button.callback()`、`Keyboard.from_rows()`），只填文档里有的字段。官方 JSON 里的固定外壳（如卡片的 `type: "tuwen"`）由接口方法补上，不让调用方填。
   - 位标志用标准库 `enum.IntFlag`：它默认保留未知位，例如 `Intents`。不用 `MyEnum | int` 这类联合类型：调用方每处都要再判断一次类型。
   - 接口里换了形式的字段（毫秒字符串、十进制字符串的权限位）照原样保留，另给类型化的只读属性（`Schedule.start`、`Channel.permission_flags`），认不出时为 `None`。
5. **接口封装**：每组一个 `_api/<组>.py`，写成持有请求层的小类，由 `Client` 在构造时创建成属性（`self.groups = Groups(self._http)`）；不用 mixin。只经请求层发请求，不直接碰 `httpx2`。
   - 可选参数一律仅限关键字；唯一的例外是发消息类方法（`send_message()`、`reply()` 等）的正文 `content`，可以按位置传。
   - 同一件事各组用同一个名字：资源详情叫 `get`，只改传入字段叫 `update`，整体覆盖叫 `set`；批量操作成员叫 `*_members`；拉黑选项叫 `add_to_blacklist`。ID 参数用模型里的字段名（`user_openid`、`group_openid`、`guild_id`），不用含糊的 `openid`。
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

- **Webhook**（未确认）：见「包结构与依赖方向」。
- **文本里的交互标签**：`<qqbot-at-user>` 等（`trans/text-chain.md`）现在由调用方自己拼。

已知限制，都还没有处理，动手前先和用户确认做法：

- **获取 token 失败后没有冷却**：平台持续拒绝或不可达时，每次接口调用都会再请求一次 `getAppAccessToken`（同时发起的调用只合并成一次）。
- **超过 1 MiB 的事件**：单帧上限是 1 MiB，超过时连接断开并 Resume；平台若补发同一条事件，会反复断开。没有遇到过，是推断。
- **网关地址不合法**：`httpx2.InvalidURL` 被当成传输错误，会一直退避重连而不是抛出。
- **网关连接有少数测试真实等待几十毫秒**：与「不真实等待」的约定不符，改掉需要虚拟时间的事件循环。

官方文档的出入（含当前实现的取舍与待实测项）集中记在 [`errata.md`](errata.md)。
实测用例的清单与跑法见 [`tests/live/README.md`](../tests/live/README.md)；频道目前不能实测，条件见 `errata.md`「频道：测试条件」。
