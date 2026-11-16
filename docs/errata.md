# 官方文档出入

`docs/upstream/qqbot-api-v2/` 里缺失、含糊或自相矛盾的地方。文档位置都相对于该目录。每条写明矛盾之处和当前实现的做法；实测得出结论后移到「已确认」，并把真实响应脱敏后做成本地测试的 fixture（`tests/fixtures/`）。实测代码在 `tests/live/`。

## 待实测

### 获取 token：60 秒换发窗口的边界

- **位置**：`dev-prepare/access-token.md`「凭证有效期与刷新」。
- **含糊**：「接近过期时间 60 秒内」获取会得到新 token、「老的在这个 60 秒内仍然有效」。没有说明：边界是否包含 60 秒整；旧 token 的有效期是延长到新 token 签发后 60 秒，还是仍到它原本的过期时刻。
- **已知**：`expires_in` 是剩余秒数，不是固定的 7200（2026-11-16 实测：签发约 3 分钟后再取，同一个 token 返回 `"7008"`）。
- **当前做法**：剩余 50 秒时刷新；刷新失败时，旧 token 在按原有效期估算的过期时刻之前继续使用。理由见 `_credentials.py` 的模块说明。
- **怎么测**：`tests/live/test_live.py::test_token_refresh_window`，要跑到当前 token 过期为止。

### 获取 token：平台自身出错时的错误字段

- **位置**：`dev-prepare/access-token.md`「失败响应」；`dev-prepare/api-call-guide.md` 的通用失败结构。
- **含糊**：密钥错误时用 `code` + `message`（已确认，见下）。平台自身出错（限频、内部错误）时用 `code` 还是通用结构的 `err_code`，没有测到。
- **当前做法**：两种都认，`err_code` 优先取 `code`。

### 单聊被动回复的有效期：5 分钟还是 60 分钟

- **位置**：`autogen/api/v2_users_user_openid_messages.post.md` 的页首说明与请求体 `msg_id` 一行；`server-inter/message/overview.md`「被动消息」表格。
- **矛盾**：接口页的 `msg_id` 写「5 分钟内有效」，同一页的页首和 `overview.md` 的表格都写单聊 60 分钟。群聊三处都是 5 分钟，没有矛盾。
- **当前做法**：SDK 不在本地判断是否过期，照常发送，由平台拒绝（如 `40034005`、`304103`）后抛 `APIError`。
- **怎么测**：收到单聊消息后分别隔约 10 分钟、约 55 分钟被动回复，看是否成功。

### HTTP 201、202：「成功」但带失败结构

- **位置**：`dev-prepare/api-call-guide.md`「HTTP 状态码」。
- **含糊**：201、202 是「异步操作成功」，但「会返回一个 error body，需要特殊处理」，没有说明哪些接口会返回、失败结构里是什么。公共错误码表里的 `304023`、`304024`（异步调用成功、等待人工审核）可能就是这种情况，属于频道消息。
- **当前做法**：不看状态码，只要响应体带非零的 `err_code` / `code` 就抛 `APIError`，调用方可按 `status_code` 与 `err_code` 区分；没有错误码则按成功解码。
- **不主动实测**：单聊、群聊的发消息接口还没见过这种响应，实际遇到时记到这里。

### 关闭码：表格与表下简化说明冲突

- **位置**：`dev-prepare/error-trace/websocket.md` 与 `dev-prepare/event-emit/websocket.md` 的「WebSocket 错误码」。
- **矛盾**：
  - 4001、4002、4010~4014 在表格里两列都是「否」，表下「其他错误，请重新发起 identify」却会让它们重新 Identify。
  - 4008 在表格里两列都是「是」，表下只说「4009 可以重新发起 resume」，按简化说明 4008 应 Identify。
  - `error-trace/websocket.md` 的表格里 4014 重复了一行（内容相同）。
- **当前做法**（`_gateway/close_codes.py`）：以表格为准。两列都「是」的 Resume；只有 Identify 列「是」的 Identify；两列都「否」的放弃，因为同样的参数重连只会再被关闭，还消耗每日连接次数。
- **不主动实测**：故意触发这些关闭码只能看到网关返回什么，验证不了该不该重试，还白白消耗连接次数。实际遇到时记到这里。

### 关闭码：未列出的取值

- **位置**：同上。
- **含糊**：表格之外的 4000~4999、标准关闭码（如 1006）以及没有关闭帧的断线，文档没有分类。
- **已知**：客户端以 1000 正常关闭后重连并 Resume 可以恢复会话（已确认，见下）。
- **当前做法**：其它 4000~4999 按「其他错误，请重新发起 identify」Identify；其余尝试 Resume，会话已失效时网关会再以 4006 或 OpCode 9 告知。

### Intents：尚未确认的两处

- **位置**：`dev-prepare/event-emit/payload.md`「事件订阅 Intents」；`autogen/event/`；`server-inter/channel/content/forum/open_forum.md`。
- **矛盾**：
  - `open_forum.md` 提到 `OPEN_FORUM_EVENT`（标题拼作 `OEPN_FORUM_EVENT`），但没有给出位。
  - `autogen/event/` 把 `GROUP_MESSAGE_CREATE`、`SUBSCRIBE_MESSAGE_STATUS` 归在 `GROUP_AND_C2C_EVENT (1 << 25)` 下，`payload.md` 的该类列表里没有它们。
- **当前做法**：不收录 `OPEN_FORUM_EVENT`，需要时可用 `Intents(位)` 自行传入（未知位会原样保留）。事件归属以 `autogen/event/` 为准。

## 已确认

以下都是 2026-11-16 用真实机器人实测的结果。

### 获取 token：`expires_in` 是字符串

- **位置**：`dev-prepare/access-token.md`「返回参数」表格与「返回示例」。
- **结论**：成功响应是 `{"access_token": "...", "expires_in": "7200"}`，`expires_in` 是字符串，表格写的 `number` 不对。成功时没有 `code` 字段。
- **实现**：字符串与数字都接受。fixture：`token_success.json`。

### 获取 token：密钥错误时用 `code`，HTTP 状态码是 200

- **位置**：`dev-prepare/access-token.md`「失败响应」。
- **结论**：密钥错误时返回 HTTP 200，响应体是 `{"code": 100016, "message": "invalid appid or secret"}`，没有 `err_code` 和 `trace_id`；trace id 只在响应头 `X-Tps-trace-ID` 里。
- **实现**：抛 `APIError`，`status_code` 为 200，`err_code` 为 100016。fixture：`token_wrong_secret.json`。

### 鉴权格式：HTTP 与网关都是 `QQBot {access_token}`

- **位置**：`dev-prepare/api-call-guide.md`；`dev-prepare/event-emit/websocket.md` 的 Identify 字段表；`dev-prepare/interface-framework/reference.md`（写的是旧格式 `Bot {appid}.{app_token}`）。
- **结论**：请求头 `Authorization: QQBot {access_token}` 可用；网关的 Identify 与 Resume 里 `token` 填 `QQBot {access_token}` 都被接受。旧格式没有测。

### 网关地址与 `/gateway/bot`

- **位置**：`autogen/api/gateway.get.md`；`openapi/wss/shard_url_get.md`（只在旧版补充页面里）。
- **结论**：`GET /gateway` 返回 `wss://api.sgroup.qq.com/websocket`，与 API 不是同一个域名。`GET /gateway/bot` 仍然可用，返回 `shards` 和 `session_start_limit`（每日 1500 次，`max_concurrency` 为 1）。fixture：`gateway_bot.json`。

### READY：`shard` 是 `[0, 1]`，`user` 多一个 `status`

- **位置**：`dev-prepare/event-emit/websocket.md`「登录鉴权获得 Session」的 Ready 示例。
- **结论**：Identify 发 `[0, 1]`，READY 里的 `shard` 也是 `[0, 1]`，文档示例的 `[0, 0]` 不对。`user.id` 是字符串；`user` 里另有文档没提的 `status`（整数）。Hello 的 `heartbeat_interval` 是整数毫秒（实测 41250）；心跳应答的 `d` 是 `null`。
- **实现**：`shard` 不校验。fixture：`gateway_ready.json`。

### 正常关闭后可以 Resume

- **位置**：`dev-prepare/event-emit/websocket.md`「恢复登录态 Session」。
- **结论**：客户端以关闭码 1000 断开后重连，发 Resume 可以恢复会话，网关回 `RESUMED`，它的 `d` 是空字符串。

### `GROUP_MEMBER_EVENT` 是 `1 << 24`

- **位置**：`dev-prepare/event-emit/payload.md` 没有列出；`autogen/event/group_member_add.md` 等写的是 `1 << 24`。
- **结论**：Identify 的 `intents` 带上 `1 << 24` 被接受，正常收到 READY。
- **实现**：`Intents.GROUP_MEMBER_EVENT`。

### 单聊消息事件的实际字段

- **位置**：`autogen/event/c2c_message_create.md`。
- **结论**：与文档一致。`author.id` 与 `author.user_openid` 相同，是 32 位大写十六进制；`author` 里另有文档没提的 `avatar`。纯文本消息没有 `attachments` 等字段。消息 `id` 以 `ROBOT1.0_` 开头，`timestamp` 形如 `2026-11-16T11:55:42+08:00`。fixture：`gateway_c2c_message_create.json`。
