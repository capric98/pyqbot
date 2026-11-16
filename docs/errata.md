# 官方文档出入

`docs/upstream/qqbot-api-v2/` 里缺失、含糊或自相矛盾的地方。文档位置都相对于该目录。每条写明矛盾之处和当前实现的做法；实测得出结论后移到「已确认」，并把真实响应脱敏后做成本地测试的 fixture。

## 待实测

### 获取 token：`expires_in` 的类型

- **位置**：`dev-prepare/access-token.md`「返回参数」表格与「返回示例」。
- **矛盾**：表格写 `number`，示例是字符串 `"7200"`。
- **当前做法**：两种都接受（`_credentials._TokenResponse`）；转成数字后不是有限正数时按「响应缺少有效的 expires_in」抛 `APIError`。

### 获取 token：失败时的错误字段

- **位置**：`dev-prepare/access-token.md`「失败响应」；`dev-prepare/api-call-guide.md` 的通用失败结构。
- **矛盾**：前者用 `code` + `message`，且业务失败时 HTTP 仍是 200；后者用 `err_code` + `message` + `trace_id`。获取 token 的接口在网关层出错时会返回哪一种，文档没说。
- **当前做法**：两种都认，`err_code` 优先取 `code`；`trace_id` 优先取响应头 `X-Tps-trace-ID`，其次响应体。错误码为 `0` 或缺失才算成功；认不出的错误码（非数字字符串）也算失败，只是 `err_code` 留空。

### 获取 token：60 秒换发窗口的边界

- **位置**：`dev-prepare/access-token.md`「凭证有效期与刷新」。
- **含糊**：「接近过期时间 60 秒内」获取会得到新 token、「老的在这个 60 秒内仍然有效」。没有说明：边界是否包含 60 秒整；窗口内再次获取得到的 `expires_in` 是剩余时间还是满额；旧 token 的有效期是延长到新 token 签发后 60 秒，还是仍到它原本的过期时刻。
- **当前做法**：把 `expires_in` 当作从发请求之前起算的剩余秒数，剩余 50 秒时刷新；刷新失败时，旧 token 在按原有效期估算的过期时刻之前继续使用。理由见 `_credentials.py` 的模块说明。

### 网关鉴权的 token 格式

- **位置**：`dev-prepare/event-emit/websocket.md` 的 Identify 字段表；`dev-prepare/interface-framework/reference.md`；`dev-prepare/getting-started.md`。
- **矛盾**：前者写 `QQBot {AccessToken}`，后者写 `Bot {appid}.{app_token}`；`getting-started.md` 说 Token 鉴权已废弃，所以前者应是现行写法。
- **当前做法**：Identify 与 Resume 都发 `QQBot {access_token}`，前缀只在 `_gateway/payload.py` 一处。

### 关闭码：表格与表下简化说明冲突

- **位置**：`dev-prepare/error-trace/websocket.md` 与 `dev-prepare/event-emit/websocket.md` 的「WebSocket 错误码」。
- **矛盾**：
  - 4001、4002、4010~4014 在表格里两列都是「否」，表下「其他错误，请重新发起 identify」却会让它们重新 Identify。
  - 4008 在表格里两列都是「是」，表下只说「4009 可以重新发起 resume」，按简化说明 4008 应 Identify。
  - `error-trace/websocket.md` 的表格里 4014 重复了一行（内容相同）。
- **当前做法**（`_gateway/close_codes.py`）：以表格为准。两列都「是」的 Resume；只有 Identify 列「是」的 Identify；两列都「否」的放弃，因为同样的参数重连只会再被关闭，还消耗每日连接次数。

### 关闭码：未列出的取值

- **位置**：同上。
- **含糊**：表格之外的 4000~4999、标准关闭码（如 1000、1006）以及没有关闭帧的断线，文档没有分类。
- **当前做法**：其它 4000~4999 按「其他错误，请重新发起 identify」Identify；其余按 `event-emit/websocket.md`「断开之后短时间内重连会补发中间遗漏的事件」尝试 Resume，会话已失效时网关会再以 4006 或 OpCode 9 告知。

### Intents 的几处出入

- **位置**：`dev-prepare/event-emit/payload.md`「事件订阅 Intents」；`autogen/event/`；`server-inter/channel/content/forum/open_forum.md`。
- **矛盾**：
  - `payload.md` 没有 `GROUP_MEMBER_EVENT`，`autogen/event/group_member_add.md`、`group_member_remove.md`、`group_join_request.md` 写它是 `1 << 24`。
  - `open_forum.md` 提到 `OPEN_FORUM_EVENT`（标题拼作 `OEPN_FORUM_EVENT`），但没有给出位。
  - `autogen/event/` 把 `GROUP_MESSAGE_CREATE`、`SUBSCRIBE_MESSAGE_STATUS` 归在 `GROUP_AND_C2C_EVENT (1 << 25)` 下，`payload.md` 的该类列表里没有它们。
- **当前做法**：`Intents` 收录 `GROUP_MEMBER_EVENT = 1 << 24`；不收录 `OPEN_FORUM_EVENT`，需要时可用 `Intents(位)` 自行传入（未知位会原样保留）。事件归属以 `autogen/event/` 为准。

### READY 示例里的 `shard`

- **位置**：`dev-prepare/event-emit/websocket.md`「登录鉴权获得 Session」的 Ready 示例。
- **矛盾**：示例是 `[0, 0]`，与 Identify 发送的 `[分片序号, 分片总数]`（不分片时 `[0, 1]`）对不上。
- **当前做法**：不校验，原样保留；类型不符（如 `null`）时退回 `()`，不影响 READY 解码。

## 已确认

（暂无）
