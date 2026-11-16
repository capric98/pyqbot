# 官方文档出入

`docs/upstream/qqbot-api-v2/` 里缺失、含糊或自相矛盾的地方。文档位置都相对于该目录。每条写明矛盾之处和当前实现的做法；实测得出结论后移到「已确认」，并把真实响应脱敏后做成本地测试的 fixture（`tests/fixtures/`）。实测代码在 `tests/live/`。

## 待实测

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

### 网关心跳：从什么时候开始

- **位置**：`dev-prepare/event-emit/websocket.md`「发送心跳 Ack」「恢复登录态 Session」。
- **含糊**：「鉴权成功之后」按周期发心跳，但 Resume 成功的信号 `RESUMED` 要等遗漏事件补发完才到；第一次心跳是立刻发还是隔一个周期也没说。
- **当前做法**：本连接收到第一条 Dispatch（READY、补发的事件或 RESUMED）就算认证成功，立刻发一次心跳，之后按周期发。
- **怎么测**：断开后积压几条事件再 Resume，看 `RESUMED` 之前的事件与心跳应答的先后。

### OpCode 7、OpCode 9：之后该怎么做

- **位置**：`dev-prepare/event-emit/payload.md`「OpCode 含义」。
- **含糊**：只说 7「通知客户端重新连接」、9「identify 或 resume 的时候参数有错」。没说收到 7 之后该 Resume 还是 Identify，也没说 9 的 `d` 是什么。
- **当前做法**：7 重连并 Resume；9 不看 `d`，清掉会话重新 Identify，连续 3 次放弃。
- **不主动实测**：两者都无法主动触发，实际遇到时把 `d` 记到这里。

### 网关：WebSocket Ping、单帧大小与二进制帧

- **位置**：`dev-prepare/event-emit/websocket.md`。
- **含糊**：没说网关是否回应 WebSocket 层的 Ping、单帧最大多大、会不会发二进制帧。
- **当前做法**：关掉 httpx2 默认每 20 秒一次的 Ping，存活只看 OpCode 1 心跳；单帧上限放宽到 1 MiB（httpx2 默认 64 KiB）；二进制帧记日志后跳过。
- **已知**：网关会回应 WebSocket 层的 Ping。2026-11-16 实测时用 httpx2 默认的 20 秒 Ping（超时 20 秒）连了约 78 秒，连接没有因为 Ping 超时而断开。
- **怎么测**：长时间挂着连接，并发送带多张图片的消息，看帧大小与类型。

### Intents：尚未确认的两处

- **位置**：`dev-prepare/event-emit/payload.md`「事件订阅 Intents」；`autogen/event/`；`server-inter/channel/content/forum/open_forum.md`。
- **矛盾**：
  - `open_forum.md` 提到 `OPEN_FORUM_EVENT`（标题拼作 `OEPN_FORUM_EVENT`），但没有给出位。
  - `autogen/event/` 把 `GROUP_MESSAGE_CREATE`、`SUBSCRIBE_MESSAGE_STATUS` 归在 `GROUP_AND_C2C_EVENT (1 << 25)` 下，`payload.md` 的该类列表里没有它们。
- **当前做法**：不收录 `OPEN_FORUM_EVENT`，需要时可用 `Intents(位)` 自行传入（未知位会原样保留）。事件归属以 `autogen/event/` 为准。

### 消息事件的去重依据

- **位置**：`autogen/event/c2c_message_create.md` 页首；`autogen/event/group_at_message_create.md` 页首。
- **矛盾**：都说「相同 msg_id 可能重复推送」，一处要「结合 msg_seq 做去重」，单聊页紧接着又说「结合 message_scene.ext 中的 msg_idx 做去重」。事件体里没有 `msg_seq`（它是发消息时的参数）。
- **当前做法**：SDK 不去重，同一条消息重复推送时处理函数会被调用多次；`message_scene.ext` 原样提供（含 `msg_idx`）。
- **怎么测**：观察重复推送时 `id` 与 `msg_idx` 是否都相同，再决定 SDK 是否按 `id` 去重。

### 群 @ 消息的 `content` 带首尾空格

- **位置**：`autogen/event/group_at_message_create.md`。
- **含糊**：说 `content` 「已去除@机器人的前缀」，但三个示例都带首尾空格（如 `" /今日天气 "`、`" "`）。
- **当前做法**：原样保留，不替用户 `strip()`，在 `GroupMessage` 的 docstring 里提示。
- **怎么测**：在群里 @机器人 发 `/ping`，看 `content` 是否为 `" /ping"` 之类。

### 消息事件的 `author`：群聊未实测

- **位置**：同上两页的 `User` 结构。
- **含糊**：单聊的实测结果多一个 `avatar`（已确认，见下）；群聊 `author` 是否同样有 `avatar`、`member_role` 的取值是否只有三种，都没测到。`message_type` 的 101「并行消息」也没有说明含义。
- **当前做法**：`avatar` 两边都建模为可选；`member_role` 先用字符串，未知取值原样保留。

### 被动回复的 `event_id`：取外层 `id` 还是 `d.id`

- **位置**：`autogen/api/v2_users_user_openid_messages.post.md` 与群聊页的 `event_id` 一行；`autogen/event/interaction_create.md` 事件体的 `id`；`autogen/api/interactions_interaction_id.put.md` 的 `interaction_id`。
- **矛盾**：发消息接口说 `event_id`「从事件最外层的 id 获取」；`interaction_create.md` 说 `d.id`「用于被动消息发送和互动回调」；回应互动的接口说 `d.id`「不带 `INTERACTION_CREATE:` 前缀」，暗示外层 `id` 带前缀、两者不同。另外 `msg_seq` 只说「与 msg_id 联合使用」，没说用 `event_id` 时要不要带。
- **当前做法**：按发消息接口页，取外层 `id`（`event.event_id`）；`msg_seq` 照样按对象从 1 递增并带上。
- **怎么测**：点一次回调按钮，记下外层 `id` 与 `d.id`；分别用两者作为 `event_id` 被动回复，看哪个被接受；再用同一个 `event_id` 带递增的 `msg_seq` 连发两条。

### `msg_type` 的取值各页不一致

- **位置**：单聊发消息页（0/2/6/7/8）、群聊发消息页（0/2/7/8）、`server-inter/message/overview.md`（0/2/7）、`server-inter/message/type/overview.md`（表格 0/2/7，表下又说「发送侧只有 msg_type=0/2/3/7 四种」）。
- **当前做法**：以两个接口页为准：SDK 按参数推断 0/2/7/8，「正在输入」的 6 只在单聊提供。3（ARK）的发送文档里没有请求体字段，不支持。

### Markdown 对象的结构三处不同

- **位置**：接口页的 `MessageMarkdown`（`template_id` 整数、`content`、`custom_template_id`、`force_verify_image_resource`，两个模板字段标为弃用，没有 `params`）；`server-inter/message/type/markdown.md`（`content`、`custom_template_id`、`params`）；`server-inter/message/template/model.md`（`template_id`、`params`、`content`）。接口页还说填了 `markdown` 后「content/ark 必须全为空」，但 v2 的请求体没有 `ark` 字段。
- **当前做法**：`Markdown` 支持 `content`、`force_verify_image_resource`，以及 `markdown.md` 示例里的 `custom_template_id` + `params`；不支持整数的 `template_id`。`markdown` 与 `content` 同传时在本地抛 `ValueError`，`ark` 不理会。
- **怎么测**：自定义 `content` 已由实测用例覆盖（`tests/live/test_live_messages.py`）；模板没有可用的模板 ID，不测。

### 键盘：示例与字段说明互相矛盾

- **位置**：接口页的 `Keyboard` 等结构；`server-inter/message/trans/msg-btn.md`；`server-inter/message/trans/overview.md` 的示例；群聊发消息页的 Markdown + 键盘示例。
- **矛盾**：
  - 接口页说 `id` 与 `content` 互斥，`trans/overview.md` 的示例两个都带。
  - `action.enter` 说「仅单聊可用」，群聊页的示例却用了。
  - `render_data.style` 在 `msg-btn.md` 只有 0、1，接口页有 0、1、3、4；`permission.type` 在 `msg-btn.md` 多一个 3（指定身份组，仅频道）。
  - `msg-btn.md` 把 `visited_label`、`style`、`permission`、`unsupport_tips` 标为必填，接口页都是选填，且说 `visited_label`「不传则保持不变」。
  - `msg-btn.md` 说按钮挂在 Markdown 消息上，接口页没说 `keyboard` 能否随文本等其它类型发送。
- **当前做法**：`Keyboard` 的 `id` 与 `content` 二选一，否则抛 `ValueError`；`keyboard` 只能随 `markdown` 发送。`enter` 不按场景拦截。枚举收录 style 0/1/3/4、permission.type 0~3。`Button` 的工厂方法总是填上 `visited_label`（默认同 `label`）、`style`（默认灰色线框）与 `permission`（默认所有人：不填时按整数默认值是 0「指定用户」，可能谁都点不了），`unsupport_tips` 不填。
- **怎么测**：实测用例 `test_markdown_with_buttons` 看蓝底白字（style 4）是否生效、未填 `unsupport_tips` 是否被接受；另在群里发带 `enter` 的指令按钮，看是否生效。

### 引用：`message_reference.message_id` 的格式

- **位置**：接口页的 `MessageReference`；群聊发消息页的富媒体、卡片示例。
- **矛盾**：字段说明要 `REFIDX_` 开头的引用索引（自己发的取响应的 `ext_info.ref_idx`，收到的取 `message_scene.ext` 的 `msg_idx`），群聊页的示例填的却是 `ROBOT1.0_` 开头的消息 ID。
- **当前做法**：`quote=` 传 `SentMessage` 或收到的消息时填引用索引；传字符串则原样填入，所以消息 ID 也能试。
- **怎么测**：实测用例 `test_quote_previous_message` 覆盖引用索引；再用 `SentMessage.id` 作为字符串引用一次，看是否被接受。

### `content` 能否随富媒体、卡片一起发

- **位置**：接口页的 `content` 一行只说「msg_type=0 时为全文」；`server-inter/message/rich-media.md` 的示例只有 `media`。
- **含糊**：`msg_type` 为 7、8 时带上 `content` 是显示、忽略还是报错，没有说明。
- **当前做法**：不拦截，`content` 原样发出（`message.reply("图来了", media=media)` 这样的写法可用）。
- **怎么测**：富媒体上传落地后，发一条带 `content` 的图片消息与一条带 `content` 的卡片，看客户端的展示。

### 正在输入（`msg_type=6`）：是否必须是被动回复

- **位置**：单聊发消息页的 `InputNotify` 与「输入状态通知」示例。
- **含糊**：示例带 `msg_id` + `msg_seq`，但没说主动发送是否可行、是否占用被动回复次数（单聊每条消息 4 次），响应体也没有给出。
- **当前做法**：`send_typing()` 的 `reply_to` 可选；传了就像被动回复一样占用 `msg_seq`；响应体不解码。
- **怎么测**：实测用例 `test_typing` 主动发送；再收到一条消息后先 `send_typing` 再回复 4 次，看第 4 次回复是否因次数超限失败，并记下响应体。

### 互动召回 `is_wakeup` 与 `msg_id` / `event_id`

- **位置**：单聊发消息页的 `is_wakeup` 一行；`autogen/api/v2_users_user_openid_stream_messages.post.md` 的 `is_wakeup` 一行。
- **矛盾**：发消息页说与 `msg_id`、`event_id`「互斥使用」，流式消息页说「true 时不校验 msg_id/event_id 有效期」，即可以同时出现。
- **当前做法**：按发消息页，`wakeup=True` 与 `reply_to` 同传时在本地抛 `ValueError`。
- **不主动实测**：召回消息每个周期只能发一条，测一次就占掉一个周期。

### 撤回：能撤回哪些消息

- **位置**：`server-inter/message/overview.md`「撤回消息」；`autogen/api/v2_groups_group_openid_messages_message_id.delete.md`。
- **矛盾**：概述只说「机器人可撤回自己发送的消息」，群聊撤回页说机器人是群管理员时还能撤回普通成员的消息（`d.id`）。两处都说超过 2 分钟不可撤回。
- **当前做法**：`client.groups.recall_message()` 也接受收到的 `GroupMessage`；时限不在本地判断，由平台拒绝（40064004）。

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

### 发单聊消息：响应的字段与被动回复

- **位置**：`autogen/api/v2_users_user_openid_messages.post.md`。
- **结论**：被动回复（`msg_id` 取自收到的消息，`msg_seq` 为 1）被接受，HTTP 200，响应是 `{"id": "ROBOT1.0_...", "timestamp": "2026-11-16T12:35:16+08:00", "ext_info": {"ref_idx": "REFIDX_..."}}`。用的是 `tests/live/test_live.py::test_bot_replies_to_a_c2c_message`：真实的 `Bot` 连上网关，收到单聊消息后回复。
- **实现**：`SentMessage`，其中 `id` 必填，响应里没有它时抛 `APIError`。fixture：`message_sent.json`。

### 获取 token：换发窗口与旧 token 的有效期

- **位置**：`dev-prepare/access-token.md`「凭证有效期与刷新」。
- **结论**（`tests/live/test_live.py::test_token_refresh_window`，跑满一个 token 的有效期）：
  - `expires_in` 是剩余秒数。同一个 token 剩余 63 秒时再取，拿回的仍是它；6.5 秒后（剩余约 56 秒）再取，拿到了新 token，`expires_in` 是满额的 `"7200"`。换发的界线就在剩余 60 秒左右。
  - 新 token 签发后，旧 token 在约 54 秒时仍可用，约 61 秒时失效。它当时原本还剩约 56 秒，所以分不清是「到原本的过期时刻」还是「新 token 签发后 60 秒」，两者只差几秒。
- **实现**：剩余 50 秒时刷新，落在换发窗口内；刷新失败时旧 token 在按原有效期估算的过期时刻之前继续使用，与实测一致。

### token 过期后的响应：`code` 与 `err_code` 同时出现且不相同

- **位置**：`dev-prepare/api-call-guide.md` 的「响应结构」与错误码表。
- **结论**：用过期的 token 调 `GET /users/@me`，返回 HTTP 401，响应体是 `{"message": "AccessToken无效或过期", "code": 11244, "err_code": 40011027, "trace_id": "..."}`。两个错误码字段同时出现，`err_code` 是文档里现行的错误码，`code` 是旧式错误码。
- **实现**：两个都有时，异常的 `err_code` 取响应体的 `err_code`。fixture：`api_token_expired.json`。
