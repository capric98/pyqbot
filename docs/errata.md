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
- **当前做法**：`avatar` 两边都建模为可选；`member_role` 是 `MemberRole`（`OpenStrEnum`，收录 member、admin、owner），未知取值得到伪成员、原值保留。

### 被动回复的 `event_id`：取外层 `id` 还是 `d.id`

- **位置**：`autogen/api/v2_users_user_openid_messages.post.md` 与群聊页的 `event_id` 一行；`autogen/event/interaction_create.md` 事件体的 `id`；`autogen/api/interactions_interaction_id.put.md` 的 `interaction_id`。
- **矛盾**：发消息接口说 `event_id`「从事件最外层的 id 获取」；`interaction_create.md` 说 `d.id`「用于被动消息发送和互动回调」；回应互动的接口说 `d.id`「不带 `INTERACTION_CREATE:` 前缀」，暗示外层 `id` 带前缀、两者不同。另外 `msg_seq` 只说「与 msg_id 联合使用」，没说用 `event_id` 时要不要带。
- **当前做法**：按发消息接口页，取外层 `id`（`event.event_id`）；`msg_seq` 照样按对象从 1 递增并带上。
- **怎么测**：点一次回调按钮，记下外层 `id` 与 `d.id`；分别用两者作为 `event_id` 被动回复，看哪个被接受；再用同一个 `event_id` 带递增的 `msg_seq` 连发两条。`tests/live/test_live_events.py` 的三个用例会把每条事件的外层 `id` 与 `d.id` 记进 `.cache/live/events.txt`，并用外层 `id` 回复；互动用例回复成功即说明外层 `id` 可用。

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
- **当前做法**：按发消息页，`wakeup=True` 与 `reply_to` 同传时在本地抛 `ValueError`。流式消息暂不提供 `is_wakeup`。
- **不主动实测**：召回消息每个周期只能发一条，测一次就占掉一个周期。

### 撤回：能撤回哪些消息

- **位置**：`server-inter/message/overview.md`「撤回消息」；`autogen/api/v2_groups_group_openid_messages_message_id.delete.md`。
- **矛盾**：概述只说「机器人可撤回自己发送的消息」，群聊撤回页说机器人是群管理员时还能撤回普通成员的消息（`d.id`）。两处都说超过 2 分钟不可撤回。
- **当前做法**：`client.groups.recall_message()` 也接受收到的 `GroupMessage`；时限不在本地判断，由平台拒绝（40064004）。

### 入群申请 `GROUP_JOIN_REQUEST` 的字段

- **位置**：`autogen/event/group_join_request.md`。
- **矛盾**：`VerifyInfo` 的字段叫 `method`，`verify_message`、`review_qa_list` 的说明却写「仅 `auth_type=...` 时」；`auto_approved` 的结构名拼成 `AutoAppproved`；申请时间是 RFC3339 字符串 `apply_at`，其它群事件都是整数秒的 `timestamp`。
- **当前做法**：按字段表与示例：`verify_info.method`（`JoinRequestVerifyMethod`），`auto_approved.strategy_id`，`apply_at` 解成 `datetime`（不是 RFC3339 时退回 `None`，不让整条事件丢掉）。`group_openid`、`join_request_id` 与 `member_openid` 必填：后者是审批接口 `POST /v2/groups/{group_openid}/approval_join_request/{member_openid}` 的路径参数，三个示例都有。
- **怎么测**：要一个机器人是管理员的测试群，再请人申请加群，会影响其他用户，须单独征得同意；记下 `verify_info` 的键名与 `apply_at` 的格式。

### 好友事件的 `author`、`short_code` 与 `union_openid`

- **位置**：`autogen/event/friend_add.md`、`friend_del.md`；`server-inter/user/manage/event.md`；`server-inter/channel/manage/user/model.md`。
- **矛盾**：`autogen` 的 `FRIEND_ADD`、`FRIEND_DEL` 都有 `author{union_openid}`，`FRIEND_ADD` 还有 `short_code`；`manage/event.md` 两个都没有，`FRIEND_DEL` 的 `autogen` 示例也没有 `author`。频道的用户模型说事件里的用户对象不带 `union_openid`，而单聊、群聊的消息事件和 `FRIEND_ADD` 都列了它。
- **当前做法**：`author`、`short_code`、`union_openid` 都可缺省（`author` 缺失时各字段为 `None`），只有 `openid` 必填。
- **怎么测**：实测用例 `test_friend_del_then_add` 记下两条事件是否带 `author`、`union_openid` 是否为空。

### 互动事件 `INTERACTION_CREATE` 的类型与场景

- **位置**：`autogen/event/interaction_create.md`。
- **矛盾**：外层 `type` 有 11~16 与 18、19、20，`data.type` 说「与外层 type 含义一致」却只列了 11~16；20（群授权状态变更）没有说明；示例 3（用户授权）没有 `data.type` 与 `chat_type`，只有 `scene`。
- **当前做法**：两处用同一个 `InteractionType`，未知取值保留原值；`chat_type`、`data.type` 都可缺省，`reply()` 在没有 `chat_type` 时按 `scene` 判断场景。
- **怎么测**：实测用例 `test_callback_button_interaction` 记下按钮互动的 `chat_type` 与 `data.type`；`test_c2c_msg_reject_then_receive` 期间同时订阅互动，看切换主动消息开关时是否推送 `type=18`，以及它带不带 `chat_type`。

### 回应互动的期限

- **位置**：`server-inter/message/trans/overview.md`「响应互动」；`autogen/api/interactions_interaction_id.put.md`；`autogen/event/interaction_create.md`。
- **含糊**：只有 `trans/overview.md` 写了「指令回调类场景为 3 秒」，接口页与事件页只说「超时后失效」。
- **当前做法**：在 `Interaction.ack()` 与 `client.interactions.ack()` 的 docstring 里写 3 秒；SDK 不自动回应，不计时，也不在本地拦截重复回应，超时与重复都由平台拒绝。
- **怎么测**：点回调按钮后分别隔 1 秒、5 秒回应，看后者是否报错与错误码；对同一互动回应两次，记下错误码。

### 全量群消息与 @ 消息会不会重复推送

- **位置**：`autogen/event/group_message_create.md`；`group_at_message_create.md`。
- **含糊**：开启「接收所有消息」后，群里 @机器人 的消息是只推 `GROUP_MESSAGE_CREATE`，还是两个事件都推，没有说明。
- **当前做法**：两个事件各走各的处理函数（`on_group_message`、`on_group_at_message`），SDK 不合并、不去重。
- **怎么测**：开启全量模式的群里 @机器人 发一条消息，看收到几条事件、`id` 是否相同。要群与权限配置，须单独征得同意。

### 富媒体：各页列出的支持格式不一致

- **位置**：`server-inter/message/rich-media.md` 的「支持的消息类型」与同页「文件类型与限制」表格；单聊、群聊上传页的 `file_type` 一行。
- **矛盾**：正文说图片 jpg/png/gif/webp/bmp、语音 silk/mp3/wav/ogg；同页表格与单聊上传页说图片 png/jpg、语音 silk；群聊上传页说语音 silk/mp3/wav。
- **当前做法**：不传 `file_type` 时按最宽的列表推断（png/jpg/jpeg/gif/webp/bmp 为图片，mp4 为视频，silk/slk/mp3/wav/ogg 为语音），平台不支持时由它拒绝（850019），调用方可改传 `FileType.FILE`。
- **怎么测**：单聊、群聊分别上传 gif、webp、bmp 图片与 mp3、wav、ogg 语音，看是否成功、展示成什么。

### 富媒体：`file_data` 的编码与 5M 的口径

- **位置**：单聊、群聊上传页的 `file_data` 一行与「直接上传二进制数据」，示例只写了 `"xxxx图片的二进制数据"`。
- **含糊**：字段是字符串，却没说二进制怎么编码；5M 是编码前还是编码后、按 10^6 还是 2^20 也没说。
- **当前做法**：标准 base64（带填充）；原始数据不超过 3 MiB 才内联（base64 后约 4 MiB），更大的分片上传。
- **怎么测**：实测用例 `test_inline_data_is_base64`，图片显示正常即确认 base64；要确认上限可再内联一个 4～5 MB 的文件。

### 分片上传：`block_size` 默认 5MB 与示例的 10485760

- **位置**：`rich-media.md`「注意事项」与预上传页 `block_size` 一行都说默认 5MB，预上传页的响应示例是 `"10485760"`（10 MiB）。
- **当前做法**：不假设大小，一律按响应顶层的 `block_size` 切片；它是字符串还是数字都接受。
- **怎么测**：实测用例 `test_large_file_is_uploaded_in_parts` 运行时记下响应的 `block_size` 与 `upload_config`。

### 分片上传：`md5_10m` 在文件不足 10002432 字节时

- **位置**：预上传页的 `md5_10m` 一行；`rich-media.md`「注意事项」。
- **含糊**：只说是「文件前 10002432 字节的 MD5」，没说文件不够长时怎么算。
- **当前做法**：取整个文件的 MD5（即前 min(文件大小, 10002432) 字节）。
- **怎么测**：实测用例 `test_large_file_is_uploaded_in_parts` 的文件约 3.6 MB，成功即确认；再上传一个超过 10002432 字节的文件确认另一种情况。

### 分片上传：分片完成接口的 `block_size`

- **位置**：单聊分片完成页写「分块大小（字节）」，群聊页写「该分块的实际大小」。
- **含糊**：最后一片不足 `block_size` 时填哪个。
- **当前做法**：填这一片的实际字节数，字符串。
- **怎么测**：实测用例 `test_large_file_is_uploaded_in_parts` 的文件大小不是分片大小的整数倍，成功即确认。

### 分片上传：`upload_config.retry_timeout` 的含义

- **位置**：预上传页的 `UploadConfig`。
- **含糊**：「重试超时时间（秒），默认 300」没说是从什么时候算、限制的是单次请求还是整个重试过程。
- **当前做法**：PUT 与分片完成各自重试；从这一步首次尝试算起，等完 `retry_delay` 会超过 `retry_timeout` 就不再重试。规则见 `design.md`。
- **不主动实测**：要人为制造对象存储或平台的临时故障，实际遇到时记到这里。

### `file_size`：预上传是字符串，素材库是整数

- **位置**：预上传页的 `file_size`（string）；`server-inter/message/material-management.md` 申请上传的 `file_size`（uint64，示例是数字）。
- **当前做法**：各按各页：预上传发字符串，素材库发整数。
- **怎么测**：实测用例 `test_large_file_is_uploaded_in_parts` 与 `test_media_image_library` 成功即确认。

### 素材库：`expires_at` 的示例与 90 天不符

- **位置**：`material-management.md` 查询有效图片的响应示例。
- **矛盾**：示例里 `expires_at - created_at` 是 604801 秒（约 7 天），而限制说明与 `complete` 的 `ttl` 都是 90 天（7776000 秒）。
- **当前做法**：原样透出，SDK 不据此计算。
- **怎么测**：实测用例 `test_media_image_library` 上传后列出，记下 `expires_at - created_at`。

### 素材库：`.jpg` 是否算与 `image/jpeg` 一致

- **位置**：`material-management.md`「限制说明」要求扩展名与 Content-Type 一致；错误码 40035001 写「扩展名与 Content-Type 需为 png/jpeg/gif/webp 且一致」。
- **含糊**：`.jpg` 扩展名配 `image/jpeg` 算不算一致。
- **当前做法**：`.jpg`、`.jpeg` 都发 `image/jpeg`；其它扩展名在本地抛 `ValueError`。
- **怎么测**：在素材库上传一张文件名为 `.jpg` 的图片，看 prepare 是否返回 40035001。

### 流式消息：路径参数与示例的 openid

- **位置**：`autogen/api/v2_users_user_openid_stream_messages.post.md` 的「路径参数」与请求示例。
- **含糊**：路径参数 `user_openid` 的描述是空的；第三个示例（结束片）路径里的 openid 有 44 位，前两个示例与真实的 `user_openid` 都是 32 位。
- **当前做法**：按单聊发消息接口理解为用户的 `user_openid`，`message.reply_stream()` 取 `message.user_openid`。
- **怎么测**：实测用例 `tests/live/test_live_bot.py::test_stream_reply`。

### 流式消息：`content_raw` 说是 Markdown，`content_type` 却可以是 text

- **位置**：同上，请求体的 `content_type` 与 `content_raw` 两行。
- **矛盾**：`content_type` 可选 `text` / `markdown`，`content_raw` 的描述却是「Markdown 格式的文本内容」。
- **当前做法**：`markdown=True`（默认）发 `content_type=markdown`，`markdown=False` 发 `text`，`content_raw` 原样填调用方的文字。
- **怎么测**：用 `reply_stream(markdown=False)` 发一段带 `**` 的文字，看是否按原文显示。

### 流式消息：各分片的 `msg_seq`、`index` 与结束分片

- **位置**：同上，请求体与三个请求示例。
- **含糊**：`msg_seq` 只说「用于去重」，没说同一条流式消息的各分片是否共用一个（三个示例都是 1）；某个分片发送失败后 `index` 该重用还是跳过；结束分片（`input_state=10`）能否不带内容。
- **当前做法**：所有分片共用第一次取的 `msg_seq`；`index` 每发一个分片加 1，失败的也算，且失败后这条流式消息在本地终止；结束分片是 `input_mode=append`、`content_raw=""`。
- **怎么测**：实测用例 `test_stream_reply`。看两点：结束分片的请求是否成功（不抛 `APIError`）；测试账号的客户端里这条消息是否停止显示「生成中」、正文是否完整。请求成功但客户端仍显示「生成中」，同样算空的结束分片不可用。
- **不可用时的备选**：结束分片改用 `input_mode=replace`、`content_raw` 带上完整正文（SDK 在本地累计 `append` / `replace` 过的内容，按 `replace` 的语义它一定以已下发的内容开头）；或者每次 `append` 先压住最后一段，到结束时随 `input_state=10` 一起发出（代价是最后一段晚一拍出现）。

### `GET /users/@me`：示例比字段表多出字段

- **位置**：`autogen/api/users_me.get.md`；旧版 `openapi/user/me.md`。
- **矛盾**：字段表是 `id`、`username`、`avatar`、`bot`、`union_openid`、`union_user_account`，示例另有 `share_url`、`welcome_msg`；旧版示例没有 `bot`。
- **当前做法**：`BotInfo` 只有 `id` 必填，其余（含示例多出的两个）都是可选。
- **怎么测**：实测用例 `test_get_me`，看原始响应（`.cache/live/raw/`）里实际有哪些字段。

### 自定义菜单：怎么清空，哪些字段必填

- **位置**：`autogen/api/v2_menu.put.md`。
- **含糊**：`menu`、`items` 以及菜单项的所有字段都标为选填，错误码表却有「必填字段缺失」（40030016）；也没说怎么清空菜单。
- **当前做法**：工厂方法总是填 `name`、`type` 与对应类型的字段；`client.menu.set([])` 发 `{"menu": {"items": []}}`。
- **怎么测**：在征得同意后，于测试机器人上 `set([])`，看菜单是否消失（会影响所有用户）。

### 指令面板：请求里的 `panel.version` 与修改时的备注

- **位置**：`autogen/api/v2_panels.post.md`、`autogen/api/v2_panels_panel_id.put.md` 的 `Panel`。
- **含糊**：请求体的 `panel.version` 只写「当前版本号」，没说是否用于并发校验；修改接口说「覆盖原有的面板元素列表和备注」，没说不传 `remark` 时备注是清空还是保留。
- **当前做法**：不发送 `version`；`update()` 不传 `remark` 时请求里没有它，docstring 提示备注可能被清空。
- **怎么测**：实测用例 `test_panel_lifecycle` 之外，再修改一次不带 `remark`，用 `get()` 看备注。

### 频道：测试条件

以下频道相关的条目目前都不能实测：`AGENTS.md` 只允许对测试用户发单聊消息。共同的前提是一个机器人所在的测试频道（沙箱频道即可），多数还要由另一个人在频道里操作，会影响其他用户，须单独征得同意。私域事件（`GUILD_MESSAGES`、`FORUMS_EVENT`）另需私域机器人。

### 子频道全量消息 `MESSAGE_CREATE` 的 Intent

- **位置**：`server-inter/channel/message/event.md` 的 `MESSAGE_CREATE` 标题；`dev-prepare/event-emit/payload.md`「事件订阅 Intents」。
- **矛盾**：`event.md` 写 `intents PUBLIC_GUILD_MESSAGES，私域`，`payload.md` 把它列在 `GUILD_MESSAGES (1 << 9)`（仅私域）下。
- **当前做法**：`GUILD_MESSAGES`：`payload.md` 是 Intents 的总表，且与「仅私域」吻合；`PUBLIC_GUILD_MESSAGES` 下只有 `AT_MESSAGE_CREATE` 与 `PUBLIC_MESSAGE_DELETE`。
- **怎么测**：私域机器人；由人在子频道发一条不 @机器人 的消息，分别只订阅 `GUILD_MESSAGES`、只订阅 `PUBLIC_GUILD_MESSAGES`，看哪次收到。

### 论坛事件的 Intent 名称

- **位置**：`server-inter/channel/content/forum/forum.md` 标题；`payload.md`。
- **矛盾**：`forum.md` 叫 `FORUM_EVENT`，`payload.md` 叫 `FORUMS_EVENT (1 << 28)`，事件列表一致。
- **当前做法**：`Intents.FORUMS_EVENT`。
- **怎么测**：私域机器人，测试频道里有论坛子频道；只订阅 `1 << 28`，由人发帖，看是否收到 `FORUM_THREAD_CREATE`。

### 没有 Intent 位的频道事件

- **位置**：`forum/open_forum.md`（`OPEN_FORUM_*`）；`server-inter/channel/role/audio_or_live_channel_member.md`（`AUDIO_OR_LIVE_CHANNEL_MEMBER_*`）。
- **含糊**：两组事件都没有给出 Intent 位，`payload.md` 的总表里也没有。
- **当前做法**：`intent` 为 `Intents(0)`，不编造位：注册了照常分发，但不参与推导，要收到须在构造 `Bot` 时自己传入完整的 `intents`（见 `design.md`「事件」）。
- **怎么测**：先向平台确认这两组事件的位；测试频道里有音视频子频道与论坛子频道，带上该位 Identify，由人进出音视频子频道、在论坛发帖，看是否收到。

### 音视频 / 直播子频道成员进出：`channel_type`

- **位置**：`role/audio_or_live_channel_member.md` 的两个示例。
- **矛盾**：示例的注释写「2-音视频子频道 5-直播子频道」，而 `ChannelType` 里语音是 2、直播是 10005；示例带 `//` 注释，不是合法 JSON。
- **当前做法**：单独的 `AudioOrLiveChannelType`（2、5），认不出的取值（如 10005）保留原值；`channel_id`、`user_id` 必填。
- **怎么测**：由人分别进出音视频子频道与直播子频道，记下 `channel_type`。

### 公域论坛事件的字段

- **位置**：`forum/open_forum.md` 的三个示例。
- **含糊**：示例只有 `guild_id`、`channel_id`、`author_id`，没有主帖、评论、回复的 ID 与内容；都带尾逗号，不是合法 JSON。
- **当前做法**：只建模这三个字段，`channel_id` 必填；ID 也收整数（同下一条）。
- **怎么测**：公域机器人，由人在论坛子频道发帖、评论、回复，记下完整的事件体。

### 论坛事件：`title`、`content` 的形式与 ID 的类型

- **位置**：`forum/model.md` 的 `ThreadInfo`、`PostInfo`、`ReplyInfo`、`RichObject`；`forum/forum.md` 的四个示例；`forum/get_thread.md`。
- **矛盾**：
  - 模型说 `title`、`content` 是字符串，`forum.md` 的示例里是 `RichObject` 数组；`get_thread.md` 说 `content` 是字符串、内容按 `RichText`（`paragraphs`）结构。`model.md` 定义的 `RichText` 没有被任何字段引用。
  - `guild_id`、`channel_id`、`author_id` 在模型里是字符串，主帖、回复、审核结果的示例里是数字，评论的示例里是字符串；`RichObject` 里的 `ChannelInfo.channel_id`、`AtRoleInfo.role_id` 是 uint64。
- **当前做法**：`title`、`content` 为 `str | tuple[ForumRichObject, ...]`，原样保留；字符串由调用方按需用 `ForumRichText.from_json()` 解析。上述 ID 字段收字符串与整数，统一成字符串（见 `design.md`「事件」）。
- **怎么测**：私域机器人，由人发一个带文字、链接、表情、#子频道、@ 的主帖，再评论、回复，记下三种事件里 `title`、`content` 的形式与 ID 的 JSON 类型。

### 论坛富文本的 `EmojiInfo` 与表情表态的 `Emoji`

- **位置**：`forum/model.md` 的 `EmojiInfo`；`forum/forum.md` 评论的示例；`openapi/emoji/model.md`。
- **矛盾**：`EmojiInfo` 的 `id`、`type` 在表格里都是字符串，示例里 `id` 是数字、`type` 是字符串 `"1"`；表情表态的 `Emoji.type` 是 uint32。
- **当前做法**：`ForumEmojiInfo.id` 收字符串与整数、统一成字符串，`type` 保持字符串（表格与示例一致），不复用 `EmojiType`；表态的 `Emoji` 照 `emoji/model.md`：`id` 字符串，`type` 为 `EmojiType`，两者都必填（表态接口的路径要用）。
- **怎么测**：同上，帖子里放一个系统表情和一个 emoji，记下 `emoji_info`；再由人对消息表态，记下 `emoji`。

### 消息删除事件与音频事件：没有给出事件体

- **位置**：`payload.md` 列出的 `MESSAGE_DELETE`、`PUBLIC_MESSAGE_DELETE`、`DIRECT_MESSAGE_DELETE` 与 `AUDIO_START`、`AUDIO_FINISH`、`AUDIO_ON_MIC`、`AUDIO_OFF_MIC`；`server-inter/message/template/model.md` 的 `MessageDelete`；`content/audio/model.md` 的 `AudioAction`。
- **含糊**：这些事件都没有页面说明事件体，`MessageDelete`、`AudioAction` 两个结构也没有被任何事件链接；被删除的消息带哪些字段、上下麦的是谁都不清楚。
- **当前做法**：按名字对应：删除事件为 `MessageDelete`（`message` 必填，其中 `id`、`channel_id`、`guild_id` 必填；`op_user` 可缺省），音频事件为 `AudioAction`（`channel_id` 必填）。
- **怎么测**：由人撤回一条子频道消息、一条私信；机器人在音频子频道播放并上下麦（音频接口落地后）；记下事件体。

### 子频道事件：`position` 与 `op_user_id`

- **位置**：`autogen/event/channel_create.md`、`channel_update.md`、`channel_delete.md`。
- **矛盾**：事件体表格没有 `position`、示例里有；表格有 `op_user_id`、示例里没有。
- **当前做法**：都建模，都可缺省（`position` 是 `Channel` 的字段）。
- **怎么测**：由有管理权限的人在测试频道里创建、修改、删除子频道，记下事件体。

### 频道事件：`GUILD_UPDATE`、`GUILD_DELETE` 的示例缺字段

- **位置**：`autogen/event/guild_update.md`、`guild_delete.md`。
- **矛盾**：表格有 `joined_at`、`op_user_id`，两个示例都没有。
- **当前做法**：都可缺省，只有 `id` 必填。
- **怎么测**：修改测试频道的资料、把机器人移出测试频道，记下事件体。移出后要重新添加机器人。

### 消息审核：`MESSAGE_AUDIT_REJECT` 的 `message_id`

- **位置**：`server-inter/channel/message/event.md` 的示例；`server-inter/message/template/model.md` 的 `MessageAudited`。
- **矛盾**：模型说 `message_id`「只有审核通过事件才会有值」，审核不通过的示例里却有。
- **当前做法**：两个事件同一结构，`message_id` 可缺省，只有 `audit_id` 必填。
- **怎么测**：机器人向测试频道的子频道发主动消息（频道消息接口落地后），平台返回 304023 时等审核结果事件，记下 `message_id`。

### 频道消息：`seq` 与 `seq_in_channel`

- **位置**：`server-inter/message/template/model.md` 的 `Message`；`server-inter/channel/message/event.md` 的三个示例与「发送时机」。
- **矛盾**：模型说 `seq` 2022 年 8 月后废弃、改用 `seq_in_channel`（字符串），示例都还用 `seq` 且没有 `seq_in_channel`；「发送时机」仍让开发者按 `Message.seq` 排序。
- **当前做法**：两个都建模（`seq` 整数，`seq_in_channel` 字符串），都可缺省；docstring 推荐用 `seq_in_channel` 排序。
- **怎么测**：由人在子频道 @机器人 发几条消息，记下两个字段是否都有、类型与递增规律。

### 频道成员事件的 `joined_at`、`roles`

- **位置**：`server-inter/channel/role/guild_member.md` 的「注」。
- **含糊**：说这两个字段「尚有一些字段未标准化」，没说实际是什么形式。
- **当前做法**：按 `Member` 结构（RFC3339 字符串、字符串数组）解码，形式不对时退回默认值（`None`、空元组），事件照常分发。
- **怎么测**：由人加入、退出测试频道，修改频道昵称或身份组，记下这两个字段。

### 频道成员事件能被动回复，却没有子频道 ID

- **位置**：`server-inter/channel/message/send.md`「目前支持被动回复的事件类型」；`role/guild_member.md`。
- **含糊**：`GUILD_MEMBER_*` 可以用 `event_id` 被动回复，但发消息接口的路径要 `channel_id`，事件里只有 `guild_id`。
- **当前做法**：`GuildMember*` 继承 `ChannelReplyTarget`，回复时由调用方指定子频道（见 `design.md`「事件」）。
- **怎么测**：由人加入测试频道，用事件 ID 被动回复到任一子频道，看是否被接受、是否限定子频道。

### 频道里的互动事件能否被动回复

- **位置**：`server-inter/channel/message/send.md`「目前支持被动回复的事件类型」；`autogen/event/interaction_create.md`。
- **矛盾**：频道发消息页列出的可用 `event_id` 回复的事件里没有 `INTERACTION_CREATE`；互动事件页又笼统地说事件 ID「用于被动消息发送」，且互动包括频道场景。
- **当前做法**：`Interaction` 同时继承 `ChannelReplyTarget`，在频道里用 `event_id` 回复到 `channel_id`；平台不接受时由它拒绝。
- **怎么测**：在测试频道发一条带回调按钮的消息，点击后用互动事件的 `event_id` 被动回复，记下是否成功与错误码；不接受就去掉 `Interaction` 的频道标记。

### 群管理：GET 的分页参数写在「请求体」，GET、DELETE 的示例带 `{}`

- **位置**：`autogen/api/` 下 `v2_groups_group_openid_members.get.md`、`..._member_blacklist.get.md`、`..._join_request_list.get.md`、`v2_groups_join_approval_strategy.get.md` 的「请求体」表格；`..._restrict_chat_setting.get.md`、`v2_groups_join_approval_strategy.get.md`、`v2_groups_join_approval_strategy_strategy_id.delete.md` 的请求示例。
- **矛盾**：`cursor`、`limit` 列在 GET 的「请求体」里，成员列表的示例却写成查询串 `?cursor=`；禁言查询、策略列表的 GET 与策略删除的 DELETE 示例各带了一个 `{}` 请求体。
- **当前做法**：`cursor`、`limit` 一律作为查询参数，GET 与 DELETE 不发请求体。翻页时 `limit` 取文档给的最大值（黑名单 100，入群申请与策略 50；成员列表没有 `limit`）。
- **怎么测**：实测用例 `test_iter_members_and_get_member` 在超过 30 人的群里翻页，成员不重复、总数与群人数一致即确认 `cursor` 在查询串里生效；`test_get_mute_settings` 成功即确认 GET 不需要请求体。

### 机器人群内状态：示例 JSON 不完整

- **位置**：`autogen/api/v2_groups_group_openid_bot_state.get.md` 的响应示例。
- **含糊**：最后一行是 `"member_role": "member`，少了右引号，不是合法的 JSON；其余字段与字段表一致。
- **当前做法**：按字段表解码，所有字段都可缺省，`recv_msg_setting`、`member_role` 是可容忍未知取值的枚举。
- **怎么测**：实测用例 `test_get_bot_state` 记下真实响应。

### 禁言：`add` 对已禁言的成员，`del` 的 `mute_expire_at`

- **位置**：`autogen/api/v2_groups_group_openid_restrict_chat_setting.post.md` 的 `SetMemberMuteState`。
- **含糊**：`op` 分 `add`（增加）与 `update`（更新到期时间），没说对已在禁言中的成员 `add` 会怎样；`mute_expire_at` 说「`op=del` 时可传空串表示立即解除」，没说不传或传一个时刻会怎样。
- **当前做法**：`client.groups.mute()` 发 `add`，`update_mute()` 发 `update`，两者的 docstring 都写明「再次 `add` 是否等于 `update`」尚待实测；`unmute()` 发 `del` 并带 `mute_expire_at: ""`。
- **怎么测**：实测用例 `test_mute_twice_with_add` 对同一成员连续 `add` 两次，看第二次是报错还是改写到期时间；`test_mute_update_then_unmute` 确认 `update` 与带空串的 `del`。

### 群黑名单：在群里的用户怎么拉黑失败

- **位置**：`autogen/api/v2_groups_group_openid_member_blacklist.post.md`。
- **含糊**：只有不在群里的用户才能加入黑名单，但没说对在群里的用户 `add` 时，是放进响应的 `fail_openids` 还是整个请求报错；`op=del` 时 `fail_openids`「同义」也没说清。批量移出成员的响应同理：`add_to_member_blacklist_fail_openids` 是拉黑失败的成员，`remove_members_result` 只说「成功时返回 success」，没有逐个的移出结果，也没说失败时是什么。
- **当前做法**：`fail_openids` 非空时 `add_to_blacklist()`、`remove_from_blacklist()` 抛 `PartialFailureError`（`failed_ids` 即它）；`remove_members()` 在拉黑失败清单非空时同样抛它，`remove_members_result` 是字符串但不是 `success` 时抛 `APIError`，缺失或 `null` 算没有报告。失败清单缺失或为 `null` 算没有失败，不是字符串列表时按「响应无法识别」抛 `APIError`，不退回空清单；`remove_members_result` 不是字符串也不是 `null` 时同样按「响应无法识别」处理。
- **怎么测**：实测用例 `test_blacklist_add_only_works_for_users_outside_the_group`。

### 入群申请审批：`join_request_id` 标为可选

- **位置**：`autogen/api/v2_groups_group_openid_approval_join_request_member_openid.post.md`。
- **含糊**：`join_request_id` 标为非必填，没说不传时审批的是哪条申请；`add_to_member_blacklist` 的说明写「`action=decline` 时可填」，字段名其实是 `op`。
- **当前做法**：`join_request_id` 是可选的关键字参数，不传就不发；事件上的 `approve()` / `decline()` 总是带上事件里的申请 ID。`decline_join_request()` 总是发出 `add_to_member_blacklist`（默认 `false`），`approve` 不发。
- **怎么测**：实测用例 `test_decline_a_join_request`；要验证不传 ID 的效果须再有一条申请。

### 入群自动审批策略：`group_ids` 的类型与创建示例

- **位置**：`autogen/api/v2_groups_join_approval_strategy.post.md`、`..._strategy_id.patch.md` 的 `group_ids`；`v2_groups_join_approval_strategy.get.md` 的响应示例；`..._strategy_id_execute.post.md` 的请求示例。
- **矛盾**：创建与修改都说 `group_ids` 是「QQ 群号列表（uint64）」，列表的响应示例却是打了码的字符串（`"10****499"`）；白名单号码明确要求字符串「避免 JS 精度问题」，群号没有。创建示例带了 `"expire_at": ""`，字段说明是「不传默认一年过期」。执行接口说请求为空，示例是 `{}`。
- **当前做法**：请求里 `group_ids` 发整数；响应里的 `JoinStrategy.group_ids` 是 `tuple[int | str, ...]`，原样保留。不传 `expire_at` 时不发这个键。执行接口发 `{}`。
- **怎么测**：实测用例 `test_join_strategy_lifecycle` 用 `group_openids` 创建；要确认 `group_ids` 须用户另给一个测试群的群号，看创建能否成功、列表里返回什么类型、是否打码。

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
