# 官方文档出入

`docs/upstream/qqbot-api-v2/` 里缺失、含糊或自相矛盾的地方。文档位置都相对于该目录。每条写明矛盾之处和当前实现的做法；实测得出结论后移到「已确认」，并把真实响应脱敏后做成本地测试的 fixture（`tests/fixtures/`）。实测代码在 `tests/live/`。

## 待实测

### 获取 token：平台自身出错时的错误字段

- **位置**：`dev-prepare/access-token.md`「失败响应」；`dev-prepare/api-call-guide.md` 的通用失败结构。
- **含糊**：密钥错误时用 `code` + `message`（已确认，见下）。平台自身出错（限频、内部错误）时用 `code` 还是通用结构的 `err_code`，没有测到。
- **当前做法**：两种都认，`err_code` 优先取 `code`。

### HTTP 201、202：「成功」但带失败结构

- **位置**：`dev-prepare/api-call-guide.md`「HTTP 状态码」。
- **含糊**：201、202 是「异步操作成功」，但「会返回一个 error body，需要特殊处理」，没有说明哪些接口会返回、失败结构里是什么。公共错误码表里的 `304023`、`304024`（异步调用成功、等待人工审核）可能就是这种情况，属于频道消息。
- **当前做法**：不看状态码，只要响应体带非零的 `err_code` / `code` 就抛 `APIError`；其中 2xx 且错误码为 304023 / 304024 的抛子类 `AuditPendingError`，带出 `data.message_audit.audit_id`（`server-inter/channel/message/send.md`「错误码」）。没有错误码则按成功解码。
- **不主动实测**：单聊、群聊的发消息接口还没见过这种响应；频道见「频道：测试条件」，实际遇到时记到这里。

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

### OpCode 9：之后该怎么做

- **位置**：`dev-prepare/event-emit/payload.md`「OpCode 含义」。
- **含糊**：只说 9「identify 或 resume 的时候参数有错」，没说 `d` 是什么。OpCode 7 已确认，见「已确认」。
- **当前做法**：不看 `d`，清掉会话重新 Identify，连续 3 次放弃。
- **不主动实测**：无法主动触发，实际遇到时把 `d` 记到这里。

### 网关：WebSocket Ping、单帧大小与二进制帧

- **位置**：`dev-prepare/event-emit/websocket.md`。
- **含糊**：没说网关是否回应 WebSocket 层的 Ping、单帧最大多大、会不会发二进制帧。
- **当前做法**：关掉 httpx2 默认每 20 秒一次的 Ping，存活只看 OpCode 1 心跳；单帧上限放宽到 1 MiB（httpx2 默认 64 KiB）；二进制帧记日志后跳过。
- **已知**：网关会回应 WebSocket 层的 Ping。2026-11-16 实测时用 httpx2 默认的 20 秒 Ping（超时 20 秒）连了约 78 秒，连接没有因为 Ping 超时而断开。
- **已知**（2026-11-16）：
  - 手机上一次选多张图发出时，拆成每张一条消息，每条的 `d` 约 1.2 KB（`test_resume_replays_backlog`）。
  - 电脑上一次发 4 张图加一行文字，是一条消息带 4 个附件，`d` 约 2.3 KB（`test_multi_image_message`）。
  - 图片只以链接出现，帧都很小；没有见到二进制帧。
- **已知**（`test_long_connection`，2026-11-16 起挂了 6 小时，只有 OpCode 1 心跳）：除了每小时一次的 OpCode 7，连接没有断过；没有收到二进制帧。
- **仍不清楚**：单帧上限。见过最大的 `d` 约 2.3 KB，离 1 MiB 很远。

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
- **已知**（`test_long_connection`，6 小时，重连并 Resume 5 次）：收到 32 条 `GROUP_MESSAGE_CREATE`，`id` 与 `msg_idx` 都没有重复，还没见过重复推送。
- **怎么测**：观察重复推送时 `id` 与 `msg_idx` 是否都相同，再决定 SDK 是否按 `id` 去重。

### `msg_type` 的取值各页不一致

- **位置**：单聊发消息页（0/2/6/7/8）、群聊发消息页（0/2/7/8）、`server-inter/message/overview.md`（0/2/7）、`server-inter/message/type/overview.md`（表格 0/2/7，表下又说「发送侧只有 msg_type=0/2/3/7 四种」）。
- **当前做法**：以两个接口页为准：SDK 按参数推断 0/2/7/8，「正在输入」的 6 只在单聊提供。3（ARK）的发送文档里没有请求体字段，不支持。

### Markdown 对象的结构三处不同

- **位置**：接口页的 `MessageMarkdown`（`template_id` 整数、`content`、`custom_template_id`、`force_verify_image_resource`，两个模板字段标为弃用，没有 `params`）；`server-inter/message/type/markdown.md`（`content`、`custom_template_id`、`params`）；`server-inter/message/template/model.md`（`template_id`、`params`、`content`）。接口页还说填了 `markdown` 后「content/ark 必须全为空」，但 v2 的请求体没有 `ark` 字段。
- **当前做法**：`Markdown` 支持 `content`、`force_verify_image_resource`，以及 `markdown.md` 示例里的 `custom_template_id` + `params`；不支持整数的 `template_id`。`markdown` 与 `content` 同传时在本地抛 `ValueError`，`ark` 不理会。
- **已知**：自定义 `content` 可用，标题、粗体、斜体、链接都正常显示（2026-11-16，`test_markdown`）。
- **不测**：模板没有可用的模板 ID。

### 互动召回 `is_wakeup` 与 `msg_id` / `event_id`

- **位置**：单聊发消息页的 `is_wakeup` 一行；`autogen/api/v2_users_user_openid_stream_messages.post.md` 的 `is_wakeup` 一行。
- **矛盾**：发消息页说与 `msg_id`、`event_id`「互斥使用」，流式消息页说「true 时不校验 msg_id/event_id 有效期」，即可以同时出现。
- **当前做法**：按发消息页，`wakeup=True` 与 `reply_to` 同传时在本地抛 `ValueError`。流式消息暂不提供 `is_wakeup`。
- **已知**：不带 `msg_id` 的召回消息（`wakeup=True`）被接受，测试用户收到了（2026-11-16，`test_wakeup`）。
- **不主动实测**：与 `msg_id` / `event_id` 同传的情况；召回消息每个周期只能发一条，测一次就占掉一个周期。

### 分片上传：`upload_config.retry_timeout` 的含义

- **位置**：预上传页的 `UploadConfig`。
- **含糊**：「重试超时时间（秒），默认 300」没说是从什么时候算、限制的是单次请求还是整个重试过程。
- **当前做法**：PUT 与分片完成各自重试；从这一步首次尝试算起，等完 `retry_delay` 会超过 `retry_timeout` 就不再重试。规则见 `design.md`。
- **不主动实测**：要人为制造对象存储或平台的临时故障，实际遇到时记到这里。

### 频道：测试条件

以下频道相关的条目目前都不能实测：`AGENTS.md` 只允许对测试用户发单聊消息。共同的前提是一个机器人所在的测试频道（沙箱频道即可），多数还要由另一个人在频道里操作，会影响其他用户，须单独征得同意。私域事件（`GUILD_MESSAGES`、`FORUMS_EVENT`）另需私域机器人。

管理接口（`client.guilds`、`client.channels`）另需：机器人在测试频道里是管理员；成员列表、身份组成员列表、移出成员、创建/修改/删除子频道要私域机器人，且开通私域后要把机器人移出频道再重新添加；禁言、移出成员、改身份组与权限须有一个同意配合的测试成员（不能是管理员）；子频道在线人数要有音视频或直播子频道；授权链接每个频道每天只能发 3 条。这些操作都会影响频道里的其他人，每次须单独征得同意，用完把测试成员与子频道恢复原状。

频道的消息与内容接口还要：在测试频道里能发消息的子频道（发消息时机器人须在线，即连着网关）；撤回、论坛接口要私域机器人；精华消息、公告、日程要机器人是管理员，日程另需日程子频道；论坛要论坛子频道；音频要申请过权限的音频机器人与语音子频道；私信要一个与机器人同在测试频道、同意接收私信的测试用户；表情表态的用户列表要有人先对消息表态。所以目前没有频道的实测用例。

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

### 频道、子频道、成员列表：响应是对象还是裸数组

- **位置**：`autogen/api/users_me_guilds.get.md`、`autogen/api/guilds_guild_id_channels.get.md` 的响应体与示例；`server-inter/channel/role/member/get_members.md`。
- **矛盾**：两个 `autogen` 页的表格说响应是 `{guilds: [...]}`、`{channels: [...]}`，示例（以及旧版的 `openapi/user/guilds.md`）都是裸数组；成员列表只说「返回 Member 对象数组」。
- **当前做法**：三者都两种形状都认（成员列表按 `{members: [...]}` 推测），对象里没有可用的列表时为空；根既不是数组也不是对象时抛 `APIError`，见 `design.md`「频道管理」。
- **怎么测**：各调一次，记下响应的形状。

### 频道成员列表：重复与结束

- **位置**：`role/member/get_members.md`「有关返回结果的说明」。
- **含糊**：说翻页时「可能会返回上一次请求已经返回过的 member」，要调用方按 user id 去重；没说重复只来自上一页还是可能来自更早的页。
- **当前做法**：按文档字面只记上一页的用户 ID 去重；以最后一个成员的 user id 作 `after`，空页结束。没有 user id 的成员跳过；最后一个成员没有 user id 时无法继续，抛 `APIError`。
- **怎么测**：在成员较多的频道用小的 `limit`（如 2）翻完，统计重复的 user id 出现在第几页。

### 身份组成员列表：`next` 的结束标志

- **位置**：`role/member/get_role_members.md`。
- **含糊**：没说最后一页的 `next` 是什么；唯一的示例只有一个成员、`next` 是 `"0"`，而 `"0"` 也是第一次请求的 `start_index`。
- **当前做法**：`data` 为空或 `next` 为 `"0"` 时结束。
- **怎么测**：对人数多于 `limit` 的身份组翻完，记下最后一页的 `next`。

### 身份组：`hoist` 的类型

- **位置**：`role-group/post_guild_role.md`、`patch_guild_role.md`。
- **矛盾**：参数表说 `hoist` 是 int32，两页的请求示例都是字符串 `"1"`；响应里是整数。
- **当前做法**：公共参数是 `bool`，按参数表发整数 0 / 1。
- **怎么测**：创建一个 `hoist=True` 的身份组，看响应里的 `hoist` 是否为 1，再删除它。

### 禁言：全员与批量共用一个接口，两个时间字段

- **位置**：`speak/patch_guild_mute.md`、`patch_guild_mute_multi_member.md`、`patch_guild_member_mute.md`。
- **含糊**：
  - `PATCH /guilds/{guild_id}/mute` 在两页里分别是全员禁言（成功 204）和带 `user_ids` 的批量禁言（成功 200，返回 `{user_ids}`）。
  - `mute_end_timestamp` 与 `mute_seconds`「二选一」，同时传「以 `mute_end_timestamp` 为准」；没说只传 `mute_seconds` 时缺省的 `mute_end_timestamp` 会不会被当成 0（解除）。解除时说「任一传 `'0'` 即可」。
- **当前做法**：全员与单个成员不解码响应；批量解成 `{user_ids}`（见下一条）。禁言只发 `mute_end_timestamp`（`timedelta` 在本地换算成时刻），解除时两个字段都发 `"0"`。
- **怎么测**：对测试成员分别禁言、批量禁言并解除，看是否生效、批量的响应是否有 `user_ids`；全员禁言要另征得同意。

### 频道批量禁言：只给成功清单

- **位置**：`speak/patch_guild_mute_multi_member.md`「返回」与示例。
- **含糊**：只说「返回设置成功的成员 `user_ids`」，示例请求两个、响应一个，没说没列出的是失败还是另有原因（如本来就在禁言中、是管理员），也没说批量解除禁言的响应是否同形、`user_ids` 缺失或为空意味着什么。
- **当前做法**：`mute_members()` / `unmute_members()` 把请求的 ID 与成功清单求差，非空时抛 `PartialFailureError`（`failed_ids` 按请求的顺序、去重）；成功清单缺失或 `null` 当作空清单（即全部失败），不是字符串列表时整条响应「无法识别」。全部成功返回 `None`。
- **怎么测**：在测试频道里对一个普通成员和一个管理员批量禁言，看响应是否只列普通成员；再批量解除，看响应是否同样列出成功的成员。

### 子频道在线人数：空对象还是 `{online_nums}`

- **位置**：`role/get_online_nums.md`「返回」。
- **矛盾**：说「成功返回空对象」，紧接着的代码块与示例都是 `{"online_nums": 1}`。
- **当前做法**：返回整数，没有 `online_nums` 时为 0（推测是 0 被省略）。
- **怎么测**：在没人与有人的音视频子频道各查一次。

### 消息频率设置：字段的类型与含义

- **位置**：`speak/setting/model.md`、`message_setting.md`。
- **矛盾**：`disable_create_dm`、`disable_push_msg` 在表格里是字符串，示例里是布尔；说明写「是否允许」，字段名却是 `disable_*`。`channel_push_max_num` 只说「每个子频道允许主动推送消息最大消息条数」，没说按天还是别的周期。
- **当前做法**：两种都收，字符串 `true` / `1`、`false` / `0` 换成布尔，其它为 `None`；docstring 按字段名解释为「是否禁止」。
- **怎么测**：查一次测试频道的设置，对照管理端的开关与主动消息限额的说明，确认 `channel_push_max_num` 的周期。

### 管理接口的成功响应

- **位置**：`autogen/api/channels_channel_id.delete.md`；`role-group/`、`role/member/delete_member.md` 等。
- **含糊**：删除子频道说「成功返回 HTTP 200」、响应「无」，示例却是 `{}`；其余增删改多是 204，没有响应体。
- **当前做法**：这些接口都不解码响应（`type_=None`），200、204、空对象都算成功。
- **怎么测**：随上面各条实测时一并记下状态码与响应体。

### 频道里的互动事件能否被动回复

- **位置**：`server-inter/channel/message/send.md`「目前支持被动回复的事件类型」；`autogen/event/interaction_create.md`。
- **矛盾**：频道发消息页列出的可用 `event_id` 回复的事件里没有 `INTERACTION_CREATE`；互动事件页又笼统地说事件 ID「用于被动消息发送」，且互动包括频道场景。
- **当前做法**：`Interaction` 同时继承 `ChannelReplyTarget`，在频道里用 `event_id` 回复到 `channel_id`；平台不接受时由它拒绝。
- **怎么测**：在测试频道发一条带回调按钮的消息，点击后用互动事件的 `event_id` 被动回复，记下是否成功与错误码；不接受就去掉 `Interaction` 的频道标记。

### 群管理：GET 的分页参数写在「请求体」，GET、DELETE 的示例带 `{}`

- **位置**：`autogen/api/` 下 `v2_groups_group_openid_members.get.md`、`..._member_blacklist.get.md`、`..._join_request_list.get.md`、`v2_groups_join_approval_strategy.get.md` 的「请求体」表格；`..._restrict_chat_setting.get.md`、`v2_groups_join_approval_strategy.get.md`、`v2_groups_join_approval_strategy_strategy_id.delete.md` 的请求示例。
- **矛盾**：`cursor`、`limit` 列在 GET 的「请求体」里，成员列表的示例却写成查询串 `?cursor=`；禁言查询、策略列表的 GET 与策略删除的 DELETE 示例各带了一个 `{}` 请求体。
- **当前做法**：`cursor`、`limit` 一律作为查询参数，GET 与 DELETE 不发请求体。翻页时 `limit` 取文档给的最大值（黑名单 100，入群申请与策略 50；成员列表没有 `limit`）。
- **已知**：不带请求体的禁言查询、入群申请列表、策略列表的 GET 与策略删除的 DELETE 都成功（2026-11-16）。成员列表与黑名单报 40012010，翻页没测到。
- **怎么测**：实测用例 `test_iter_members_and_get_member` 在超过 30 人的群里翻页，成员不重复、总数与群人数一致即确认 `cursor` 在查询串里生效；`test_get_mute_settings` 成功即确认 GET 不需要请求体。

### 群黑名单：在群里的用户怎么拉黑失败

- **位置**：`autogen/api/v2_groups_group_openid_member_blacklist.post.md`。
- **含糊**：只有不在群里的用户才能加入黑名单，但没说对在群里的用户 `add` 时，是放进响应的 `fail_openids` 还是整个请求报错；`op=del` 时 `fail_openids`「同义」也没说清。批量移出成员的响应同理：`add_to_member_blacklist_fail_openids` 是拉黑失败的成员，`remove_members_result` 只说「成功时返回 success」，没有逐个的移出结果，也没说失败时是什么。
- **当前做法**：`fail_openids` 非空时 `add_to_blacklist()`、`remove_from_blacklist()` 抛 `PartialFailureError`（`failed_ids` 即它）；`remove_members()` 在拉黑失败清单非空时同样抛它，`remove_members_result` 是字符串但不是 `success` 时抛 `APIError`，缺失或 `null` 算没有报告。失败清单缺失或为 `null` 算没有失败，不是字符串列表时按「响应无法识别」抛 `APIError`，不退回空清单；`remove_members_result` 不是字符串也不是 `null` 时同样按「响应无法识别」处理。
- **已知**（2026-11-16，机器人是管理员）：查黑名单仍报 40012010，用例第一步就停了，拉黑没有发出。移出成员报 40103011「操作失败, 机器人已经关闭操作权限」（文档没有这个错误码）；用户在群设置「机器人管理员权限设置」里打开「移除群成员」后，只移出、不拉黑又试了两次，仍是 40103011，请求体与文档一致。移出接口页写着「该能力正在内邀接入中」。
- **已知**（2026-11-17，机器人加入白名单群、开通「移除群成员」之后）：只移出、不拉黑被接受，`remove_members()` 没有抛异常，即 `remove_members_result` 是 `success` 或没有给出，拉黑失败清单为空，用户确认该成员已不在群里；原始响应没有留存。查黑名单仍报 40012010，拉黑仍没有发出。
- **怎么测**：开通黑名单接口后，再跑实测用例 `test_blacklist_add_only_works_for_users_outside_the_group` 与 `LIVE_REMOVE_BLACKLIST=1` 的 `test_remove_member_and_blacklist`。

### 入群申请审批：`join_request_id` 标为可选

- **位置**：`autogen/api/v2_groups_group_openid_approval_join_request_member_openid.post.md`。
- **含糊**：`join_request_id` 标为非必填，没说不传时审批的是哪条申请；`add_to_member_blacklist` 的说明写「`action=decline` 时可填」，字段名其实是 `op`。
- **当前做法**：`join_request_id` 是可选的关键字参数，不传就不发；事件上的 `approve()` / `decline()` 总是带上事件里的申请 ID。`decline_join_request()` 总是发出 `add_to_member_blacklist`（默认 `false`），`approve` 不发。
- **已知**：带上事件里的 `join_request_id` 时，拒绝（带理由、不拉黑）与通过都被接受（2026-11-16，`test_group_admin_session`）。
- **怎么测**：不传 `join_request_id` 审批一次，看是否生效。

### 入群自动审批策略：`group_ids` 的类型与创建示例

- **位置**：`autogen/api/v2_groups_join_approval_strategy.post.md`、`..._strategy_id.patch.md` 的 `group_ids`；`v2_groups_join_approval_strategy.get.md` 的响应示例；`..._strategy_id_execute.post.md` 的请求示例。
- **矛盾**：创建与修改都说 `group_ids` 是「QQ 群号列表（uint64）」，列表的响应示例却是打了码的字符串（`"10****499"`）；白名单号码明确要求字符串「避免 JS 精度问题」，群号没有。创建示例带了 `"expire_at": ""`，字段说明是「不传默认一年过期」。执行接口说请求为空，示例是 `{}`。
- **当前做法**：请求里 `group_ids` 发整数；响应里的 `JoinStrategy.group_ids` 是 `tuple[int | str, ...]`，原样保留。不传 `expire_at` 时不发这个键。执行接口发 `{}`。
- **已知**（2026-11-16，`test_join_strategy_lifecycle`，机器人在测试群里不是管理员）：
  - 用 `group_openids` 创建停用的策略、改备注、加删白名单都被接受。
  - 创建的响应只回了 `strategy_id`、`is_enable`、`expire_at`。
  - 列表里有 `group_openids`，`group_ids` 是空的；`whitelist_user_count` 是 1（加两个、删一个）。
  - `expire_at` 按秒原样保存，返回时换成 +08:00；`created_at`、`updated_at` 是 RFC3339。
  - 执行接口发 `{}`：策略停用、机器人不是管理员时报 50105002「处理失败，请稍后重试」；策略启用、机器人是管理员时被接受。
- **怎么测**：要确认 `group_ids`，须用户另给一个测试群的群号，看创建能否成功、列表里返回什么类型、是否打码。

### 频道发消息：没有 `msg_seq`

- **位置**：`server-inter/channel/message/send.md`「通用参数」；单聊、群聊的发消息页有 `msg_seq`。
- **含糊**：子频道（私信同参数）的请求体没有 `msg_seq`，没说同一条消息能被动回复几次、靠什么去重。
- **当前做法**：频道不发 `msg_seq`，也不占用回复对象的计数（`reply_fields(..., seq=False)`）。
- **怎么测**：见「频道：测试条件」。由人 @机器人 发一条消息，对它连续被动回复 3 条，看是否都成功；再带上 `msg_seq` 发一次，看是否被拒或被去重。

### 频道发消息：`keyboard`

- **位置**：`send.md` 的「通用参数」；`server-inter/message/trans/msg-btn.md`。
- **含糊**：发消息页没有 `keyboard`，按钮页却有「仅频道可用」的身份组权限（`specify_role_ids`），频道里也有互动事件。
- **当前做法**：子频道与私信接受 `keyboard`，照单聊群聊只能随 `markdown` 发送。
- **怎么测**：Markdown 已开通的机器人在测试子频道发一条带回调按钮的 Markdown 消息，看按钮是否显示、点击后是否推送 `INTERACTION_CREATE`。

### 频道发消息：待审核响应用 `code`，`ark` 能否发送

- **位置**：`send.md`「错误码」的示例；`dev-prepare/api-call-guide.md` 的通用失败结构；`server-inter/message/type/overview.md`「各场景支持情况」。
- **矛盾**：审核示例的错误码字段是 `code`，通用结构是 `err_code`；`overview.md` 说结构化卡片在频道「发 ❌」，`send.md` 与 `ark.md` 却给了频道发 `ark` 的方法。
- **当前做法**：两个错误码字段都认（同「获取 token：平台自身出错时的错误字段」）；`ark` 照 `send.md` 发送，能否发由平台决定（无权限时 `304004`）。
- **怎么测**：向测试子频道发主动消息直到平台要求审核，记下响应体；有 Ark 权限的机器人发一条模板 23 的 Ark。

### 频道的 @ 写法：`<@user_id>` 还是 `<qqbot-at-user>`

- **位置**：`server-inter/channel/message/format.md`「支持的格式」；`server-inter/message/trans/text-chain.md`「使用 @ 能力」。
- **矛盾**：`format.md` 用 `<@user_id>` / `<@!user_id>` 与 `@everyone`，`text-chain.md` 说它们「即将弃用」、改用 `<qqbot-at-user id="" />` 与 `<qqbot-at-everyone />`，并说子频道里 `id` 填 `user_openid`（频道里用户的 ID 是 `GuildUser.id`）。
- **当前做法**：SDK 不拼这些标签，`content` 原样发送；docstring 举的是 `format.md` 的写法。
- **怎么测**：在测试子频道分别用两种写法 @测试用户，看是否都渲染成 @ 标签，`id` 该填哪个值。

### Ark：示例用了模板没有的变量

- **位置**：`server-inter/message/type/ark.md`「请求示例」；`send.md`「form-data 格式示例」。
- **矛盾**：第一个示例用模板 23，却填了模板 23 没有定义的 `#TITLE#`、`#META_URL#`、`#META_LIST#`（模板 23 只有 `#DESC#`、`#PROMPT#`、`#LIST#`）；`send.md` 的 form-data 示例里 `ark` 字段的值多包了一层 `{"ark": ...}`，`template_id` 是没有列出的 1。
- **当前做法**：`Ark` 只是 `template_id` 与 `kv` 的容器，变量由调用方按模板的「字段说明」填；multipart 里的 `ark` 字段是 Ark 对象本身的 JSON，不多包一层。
- **怎么测**：有 Ark 权限的机器人用 multipart（带一张本地图片）发一条模板 23 的 Ark，看是否成功。

### 表情表态：emoji 的 ID

- **位置**：`openapi/emoji/model.md` 的 `Emoji` 与「Emoji 列表」。
- **矛盾**：字段说明说「emoji 使用 emoji 本身为 id」，列表里 type 2 的 ID 却是码点的十进制（如 `9728` 是 ☀）。
- **当前做法**：`Emoji.id` 原样放进表态接口的路径（经转义），不转换；`EmojiType` 的 docstring 按列表写成码点的十进制。
- **怎么测**：对测试子频道的一条消息分别用 `"128077"` 与 `"👍"` 表态，看哪个成功；再由人用 emoji 表态，记下事件里的 `emoji.id`。

### 日程列表：`since` 写成 GET 的请求体

- **位置**：`server-inter/channel/content/schedule/get_schedules.md` 的「参数」与示例。
- **含糊**：`GET` 接口的示例把 `since` 放在 JSON 请求体里。
- **当前做法**：放进查询参数 `?since=毫秒`，GET 不带请求体。
- **怎么测**：在日程子频道建两个日程，一个今天结束、一个明天结束，用 `since` 取明天之后的，看是否只返回后者。

### 修改日程：没传的字段怎么办

- **位置**：`schedule/patch_schedule.md`。
- **含糊**：`PATCH` 的请求体是完整的 `Schedule`（「不需要带 id」），没说缺省字段是保留还是清空。
- **当前做法**：`update_schedule()` 的名称与时间必填，其余只在给出时发送；docstring 提示按需要的结果给全。
- **怎么测**：建一个带描述的日程，修改时不传 `description`，再取详情看描述是否还在。

### 帖子详情：`thread` 是 `ThreadInfo` 还是 `Thread`

- **位置**：`server-inter/channel/content/forum/get_thread.md` 的「返回」与示例。
- **矛盾**：返回表说 `thread` 是 `ThreadInfo`（`thread_id`、`title`、`content`、`date_time`），示例却是完整的 `Thread`（`guild_id`、`channel_id`、`author_id` 加嵌套的 `thread_info`）。
- **当前做法**：按示例解成 `ForumThread`，`thread_info` 必填；若实际是扁平的 `ThreadInfo`，会按「响应无法识别」抛 `APIError`。两种都认要先取原始字典再分派，宽容解码没有现成入口，等实测确认再改。
- **怎么测**：私域机器人在论坛子频道取一个真实帖子的详情，看 `thread` 下是否有 `thread_info`。

### 帖子列表：没有翻页参数

- **位置**：`forum/get_threads_list.md`。
- **含糊**：响应有 `is_finish`（是否拉取完毕），但接口没有游标、偏移量之类的参数，取不到后面的帖子。
- **当前做法**：`list_threads()` 只取一次，返回 `ForumThreadList`，`finished` 反映 `is_finish`；不做成 `iter_*`。
- **怎么测**：在论坛子频道发足够多的帖子，看 `is_finish` 何时为 0、响应里是否另有游标字段。

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

### `GET /users/@me`：实际字段是示例那一套

- **位置**：`autogen/api/users_me.get.md`：字段表是 `id`、`username`、`avatar`、`bot`、`union_openid`、`union_user_account`，示例另有 `share_url`、`welcome_msg`。
- **结论**：响应只有 `id`（19 位数字的字符串）、`username`、`avatar`、`share_url`、`welcome_msg`；字段表里的 `bot`、`union_openid`、`union_user_account` 都没有返回。`share_url` 是 `https://qun.qq.com/qunpro/robot/qunshare?...` 形式的链接，`welcome_msg` 没有设置时是空字符串。
- **实现**：`BotInfo` 只有 `id` 必填，不变。fixture：`bot_info.json`。

### 生成分享链接：响应多出 `retcode`、`msg`

- **位置**：`autogen/api/v2_generate_url_link.post.md`：响应体只有 `data.url`，示例链接是 `qun.qq.com` 的长链接。
- **结论**：响应是 `{"retcode": 0, "msg": "success", "data": {"url": "https://bot.q.qq.com/s/..."}}`，链接是短链接。失败时是否用 `retcode` 表示还没见到。
- **实现**：只读 `data.url`；失败时如果没有 `err_code` / `code`、也没有 `data`，抛「响应无法识别」的 `APIError`。fixture：`share_link.json`。

### 自定义菜单：没有设置过时 `menu` 是空对象

- **位置**：`autogen/api/v2_menu.get.md`：「未设置过菜单时该字段为空」。
- **结论**：没有设置过菜单的机器人，响应是 `{"menu": {}}`，没有 `version`。
- **实现**：`CurrentMenu.version` 为 `None`，`items` 为空。fixture：`menu_unset.json`。

### 分片上传：序号从 1 开始，图片只有一片

- **位置**：单聊预上传页 `UploadPart.index` 写「分片序号，从 0 开始」，示例也从 0 开始；分片完成页的示例 `part_index` 是 0。
- **结论**（`test_large_file_is_uploaded_in_parts`，3602158 字节的 PNG）：
  - 预上传的响应：`parts` 只有一片，`index` 是 1；每一片另带文档没有的 `block_size`。顶层与这一片的 `block_size` 都是字符串 `"3602158"`，即文件大小。`upload_config` 是 `{"concurrency": 1, "retry_timeout": 300, "retry_delay": 1}`。
  - 分片完成时 `part_index` 原样填 1 被接受；`md5_10m` 填整个文件的 MD5（文件不足 10002432 字节）被接受；合并后返回 `raw_url`。
  - 12005713 字节的 PNG（`test_file_over_10m_is_uploaded`）同样只有一片、`block_size` 等于文件大小；`md5_10m` 填前 10002432 字节的 MD5 被接受。
- **实现**：允许序号从 0 或 1 开始（须连续），第 n 片的偏移按「序号 − 最小序号」计算，分片完成时原样回报平台给的序号。fixture：`upload_prepared.json`。

### 卡片：`pic_url` 用 .ico 时转存失败

- **位置**：单聊发消息页的卡片（`msg_type=8`）。文档没有写 `pic_url` 支持哪些格式。
- **结论**：`pic_url` 填 `https://www.qq.com/favicon.ico` 时，发消息返回 `err_code` 40034141「图片转存失败，请重试」；换成 jpg 后卡片正常显示，点击打开 `url`。
- **实现**：不变，由平台拒绝。

### 被动回复的 `event_id`：取外层 `id`

- **位置**：发消息接口页的 `event_id` 一行（「从事件最外层的 id 获取」）；`autogen/event/interaction_create.md` 说 `d.id`「用于被动消息发送和互动回调」。
- **结论**：外层 `id` 形如 `INTERACTION_CREATE:<uuid>`、`FRIEND_ADD:<uuid>`、`FRIEND_DEL:<uuid>`；互动的 `d.id` 是不带前缀的 `<uuid>`，好友事件的 `d` 里没有 `id`。用外层 `id` 作 `event_id`、带 `msg_seq` 1 被动回复，按钮互动、授权互动与 `FRIEND_ADD` 都被接受（`tests/live/test_live_events.py`）。
- **补测**（`test_interaction_ack_timing_and_event_ids`）：用不带前缀的 `d.id` 作 `event_id` 被拒，HTTP 400，`err_code` 40034025「请求参数event_id无效」；用外层 `id` 带 `msg_seq` 1、2 连发两条都被接受。
- **实现**：不变，`event.event_id` 取外层 `id`。fixture：`gateway_friend_add.json`、`gateway_interaction_authorize.json`。

### 好友事件：都带 `author`，经分享链接添加时 `scene` 是 1000

- **位置**：`autogen/event/friend_add.md`、`friend_del.md`；`server-inter/user/manage/event.md`。
- **结论**（`test_friend_del_then_add`）：
  - `FRIEND_DEL` 与 `FRIEND_ADD` 都带 `author`，里面只有 `union_openid`，是空串。
  - 用 `generate_share_link(callback_data="pyqbot-live")` 生成的链接加回时，`FRIEND_ADD` 的 `scene_param` 是 `pyqbot-live`，`short_code` 是这条短链接的代码；`scene` 却是 1000（缺省），不是文档说的 2003 / 2004。
- **实现**：字段都可缺省，不变；`FriendAdd.scene_param` 的 docstring 提示以它区分来源。fixture：`gateway_friend_add.json`、`gateway_friend_del.json`。

### 互动事件：按钮与授权的类型、场景

- **位置**：`autogen/event/interaction_create.md`。
- **结论**：
  - 单聊里点回调按钮：`type` 11，`chat_type` 2（单聊），`data.type` 11；用 `d.id` 调 `PUT /interactions/{id}` 回应后，按钮不再转圈、文字变成 `visited_label`（`test_callback_button_interaction`）。
  - 切换资料卡的主动消息开关：`type` 18，没有 `chat_type` 和 `data.type`，`scene` 是 `"c2c"`，`data.resolved.authorize_data` 是 `{"opt_scene": "setting", "scope": "c2c_push"}`；另有文档没提的 `union_openid`（空串）。
  - `type` 20 没有见到。
- **实现**：不变；`reply()` 没有 `chat_type` 时按 `scene` 判断场景。fixture：`gateway_interaction_authorize.json`。

### 单聊主动消息开关：不推 `C2C_MSG_REJECT` / `C2C_MSG_RECEIVE`

- **位置**：`autogen/event/c2c_msg_reject.md`、`c2c_msg_receive.md`：用户在资料卡关闭 / 打开主动消息时触发。
- **结论**（`test_c2c_msg_reject_then_receive`，订阅了 `GROUP_AND_C2C_EVENT` 与互动）：
  - 切换资料卡的开关时，两个事件都没有推送，推的是 `type` 18 的 `INTERACTION_CREATE`（见上一条）。
  - 开关状态在 `authorize_data.switch`（文档没有）：打开时为 `true`，关闭时不带这个字段。每切换一次推一条；第一次只收到 1 条，是因为用例在第一条之后 15 秒就断开了。
  - 用这条授权互动的外层 `id` 被动回复被接受，测试用户收到了。
- **实现**：`on_c2c_msg_reject`、`on_c2c_msg_receive` 保留（文档仍有），docstring 写明实测没有推送、改看授权互动；`InteractionAuthorizeData.switch` 缺省为 `False`。fixture：`gateway_interaction_authorize.json`（关）、`gateway_interaction_authorize_on.json`（开）。

### 流式消息：路径用 `user_openid`，空的结束分片可用

- **位置**：`autogen/api/v2_users_user_openid_stream_messages.post.md` 的路径参数、请求体与三个示例。
- **结论**（`test_stream_reply`，被动回复一条单聊消息）：
  - 路径参数就是用户的 `user_openid`。
  - 所有分片共用第一次取的 `msg_seq`，`index` 从 0 起每片加 1，都被接受。
  - 结束分片 `input_mode=append`、`content_raw=""` 被接受。
  - 客户端里消息逐段出现：生成中显示跳动的三个点，每来一片手机轻微震动，发出结束分片后三个点消失，正文完整。
  - 每个分片响应的 `remain_msg_len` 都是 0。
- **实现**：不变。

### 素材库：列表的时间是数字字符串，有效期 90 天

- **位置**：`server-inter/message/material-management.md`：查询有效图片的 `created_at`、`expires_at` 写 int64，示例的差约 7 天；限制说明与 `complete` 的 `ttl` 是 90 天。
- **结论**（`test_media_image_library`）：
  - `complete` 返回整数 `ttl` 7776000。
  - 列出时 `created_at`、`expires_at` 是数字字符串（如 `"1794861718"`），两者相差 7776000 秒，即 90 天，示例的约 7 天不对。
  - 申请上传时 `file_size` 发整数被接受；预上传那边发字符串也被接受（见「分片上传」）。
- **实现**：`MediaImage.created_at`、`expires_at` 的字符串与整数都接受，统一返回整数（此前按整数解码，字符串被宽容解码丢成 `None`）。fixture：`media_images_list.json`。

### 指令面板：版本号在顶层递增，不传 `remark` 会清空备注

- **位置**：`autogen/api/v2_panels.post.md`、`autogen/api/v2_panels_panel_id.put.md` 的 `Panel`。
- **结论**（`test_panel_lifecycle`，只关联测试用户的单聊面板）：
  - 请求里不发 `panel.version` 被接受。
  - 详情顶层的 `version` 创建时为 1，每次修改加 1；`panel.version` 是空的。
  - 不带 `remark` 修改后，详情里的备注没有了，即被清空。
  - 移除、加回关联用户与删除都成功。
  - `created_at`、`updated_at` 是 RFC3339 字符串。
- **客户端**：在单聊输入框里输入 `/` 弹出「快捷指令」面板，先后看到「pyqbot」「pyqbot2」，删除后面板消失；修改后要删掉 `/` 重新输入才刷新（重测确认）。
- **实现**：不变；`panels.set()` 的 docstring 改为不传 `remark` 会清空备注。

### 群：机器人入群与 @ 消息

- **位置**：`autogen/event/group_add_robot.md`、`group_at_message_create.md` 及其 `User` 结构。
- **结论**（`test_group_add_robot`、`test_group_at_message`，用户提供的测试群）：
  - `GROUP_ADD_ROBOT` 的 `d` 只有 `group_openid`、`op_member_openid`、`timestamp`，外层 `id` 形如 `GROUP_ADD_ROBOT:<uuid>`；用它作 `event_id` 在群里被动回复被接受。
  - @ 消息的 `content` 只在开头留一个空格：手打的 `@机器人 /ping` 得到 `" /ping"`；由指令按钮填进输入框再发出的得到 `" /pyqbot-enter "`，首尾都有。
  - `author` 有 `avatar`、`bot`、`id`（与 `member_openid` 相同）、`member_openid`、`member_role`、`union_openid`（空串）、`username`（QQ 昵称），另有文档没有的 `member_nickname`（群名片）；没有 `union_user_account`。群主之外的管理员发消息时 `member_role` 是 `admin`。
  - `d` 里另有文档没有的 `group_id`，与 `group_openid` 相同。
  - `message_scene.ext` 有 `msg_idx=REFIDX_...` 与 `auth_token=...` 两项。
  - 外层 `id` 形如 `GROUP_AT_MESSAGE_CREATE:<小写字母与数字>`，`d.id` 是 `ROBOT1.0_` 开头的消息 ID；用 `msg_id`（`d.id`）被动回复被接受。
  - `message_type` 101 没有见到。
- **实现**：发送者（`GroupMessageAuthor`）与被 @ 的成员（`GroupMessageMember`）都有 `member_nickname`；`content` 仍原样保留，docstring 写明开头的空格。`group_id` 不收录。fixture：`gateway_group_add_robot.json`、`gateway_group_at_message_create.json`（`auth_token` 已替换）。

### 群管理：权限不足时的错误码，机器人状态的真实响应

- **位置**：群信息、成员、黑名单等接口页的错误码表写 11253「应用无接口访问权限」（「仅白名单机器人可用」）；禁言与入群申请页说要群管理员。
- **结论**（`tests/live/test_live_groups.py`，机器人是普通成员时）：
  - 群信息、机器人状态、入群自动审批策略列表可以调用。
  - 成员列表与黑名单报 `err_code` 40012010，文案同样是「应用无接口访问权限」：40012010 是现行错误码，11253 是旧式的。
  - 禁言设置与入群申请列表报 40011030「机器人不是群管理员」。
  - `bot_state` 的响应是合法的 JSON（文档示例少了引号），字段与字段表一致：`allow_proactive_msg` 为 false，`recv_msg_setting` 是空串（不在文档列的三个取值里），`member_role` 是 `member`，`joined_at` 是 RFC3339。
- **机器人是管理员之后**：禁言设置与入群申请列表可以查；成员列表、查单个成员、黑名单仍报 40012010（内邀能力，与身份无关）；批量移出成员报 40103011「操作失败, 机器人已经关闭操作权限」。
- **加入白名单群之后**（2026-11-17，开通了撤回消息、进群管理、发言管理、移除群成员、@全体成员）：批量移出成员被接受；成员列表、查单个成员、黑名单仍报 40012010，不在这几项里。
- **实现**：错误码写进各接口的 docstring；`recv_msg_setting` 的空串由 `RecvMsgSetting` 原样保留。

### 网关：Resume 时积压的事件先于 `RESUMED` 补发

- **位置**：`dev-prepare/event-emit/websocket.md`「发送心跳 Ack」「恢复登录态 Session」。
- **结论**（`test_resume_replays_backlog`，断开约 30 秒期间测试用户发了几条单聊）：
  - Resume 后，积压的 5 条 `C2C_MESSAGE_CREATE`（序号 3～7）先补发，然后才是 `RESUMED`（序号 8）。
  - 收到第一条补发事件就发心跳被接受；心跳应答排在 `RESUMED` 之后。
- **实现**：不变，SDK 正是收到第一条 Dispatch 就发心跳。

### 网关：每条连接整 1 小时收到 OpCode 7，Resume 即可

- **位置**：`dev-prepare/event-emit/payload.md`「OpCode 含义」只说 7「通知客户端重新连接」，没说之后该 Resume 还是 Identify。
- **结论**（`test_long_connection`，2026-11-16 18:24 起挂了 6 小时）：
  - 每条连接在 `READY` 或 `RESUMED` 之后整 60 分钟（误差不到 1 秒）收到 OpCode 7，6 小时共 5 次，此外没有断线。
  - 每次重连后发 Resume 都恢复成功，全程只 Identify 了 1 次。从收到 7 到 `RESUMED` 约 3.5～5 秒。
  - OpCode 7 的 `d` 没有记录。
- **实现**：不变，SDK 收到 7 后退避不到 1 秒就重连并 Resume。

### 键盘：单聊发送成功，`enter` 在群里只填进输入框

- **位置**：接口页的 `Keyboard` 等结构；`server-inter/message/trans/msg-btn.md`；群聊发消息页的示例。
- **结论**：
  - 单聊里 Markdown 加键盘发送成功，不填 `unsupport_tips` 被接受，style 1（蓝色线框）与 4（蓝底白字）按预期显示（`test_markdown_with_buttons`）。
  - 群里也能发 Markdown 加键盘。`enter=True` 的指令按钮在群里不会直接发出，只把「@机器人 指令」填进输入框，印证「仅单聊可用」（`test_group_message_features`）。
- **没有测**：`id` 与 `content` 同传、不填 `visited_label` 时的效果。
- **实现**：不变。

### 引用、带文字的富媒体与卡片

- **位置**：接口页的 `MessageReference` 与 `content` 一行；`server-inter/message/rich-media.md`。
- **结论**：
  - 引用索引（`ext_info.ref_idx`）与 `ROBOT1.0_` 开头的消息 ID 都能作 `message_reference.message_id`，客户端都以引用样式显示（`test_quote_previous_message`、`test_quote_by_message_id`）。
  - `msg_type` 为 7（富媒体）、8（卡片）时带 `content` 被接受，文字随消息显示（`test_text_with_media_and_card`）。
- **实现**：不变。

### 收到的引用消息：`ref_msg_idx` 与 `msg_elements`

- **位置**：`autogen/event/c2c_message_create.md` 的 `message_type`、`msg_elements` 与示例 3；流式消息接口页的 `MessageExtInfo.ref_idx`（「对应消息事件 ext 里的 msg_idx 与 ref_msg_idx」）。
- **结论**（2026-11-20，`test_quote_indices_and_two_streams`，测试用户在单聊里依次引用四条消息）：
  - 引用消息的 `message_type` 是 103，`message_scene.ext` 依次是 `ref_msg_idx`、`msg_idx`。
  - `ref_msg_idx` 就是被引用消息的索引，四次全部对上：机器人的普通消息是发送结果的 `ext_info.ref_idx`，流式消息是分片响应的 `ext_info.ref_idx`，用户自己的消息是它的 `msg_idx`。
  - `msg_elements` 只有一项，就是被引用的消息：`msg_idx` 与 `ref_msg_idx` 相同，`message_type` 也是 103（被引用的是纯文本也一样），`content` 是完整正文；没有 `author`（用例记下的是 SDK 解码后的结果，分不出是缺了还是 `null`）。
- **实现**：不变，`ref_msg_idx` 读 `message_scene.ext`。真实样本见 `tests/fixtures/gateway_c2c_message_create_quote.json`。

### 正在输入与被动回复的次数

- **位置**：单聊发消息页的 `InputNotify`、「输入状态通知」示例与被动回复次数的说明（每条消息 4 次）。
- **结论**：
  - 不带 `msg_id` 的主动发送被接受，客户端显示「正在输入」，`seconds=30` 时持续约 30 秒（`test_typing`）。
  - 用同一条消息先发「正在输入」（`msg_seq` 1），再被动回复 4 条（`msg_seq` 2～5），全部被接受，测试用户都收到了（`test_c2c_reply_limit_and_plain_stream`）。所以「正在输入」不占次数，或者上限不止 4 次。
  - 同一条消息先收到一条被拆成 6 条的流式消息，再被动回复 6 条（`msg_seq` 7～12）也都被接受，一共 12 条（`test_stream_auto_split`）。所以上限不止 4 次。
- **实现**：不变。

### 回应互动：客户端只等约 1 秒，接口从不报错

- **位置**：`server-inter/message/trans/overview.md`「响应互动」写 3 秒；接口页与事件页只说「超时后失效」。
- **结论**（单聊里的回调按钮）：
  - 从收到事件到回应完成，0.72 秒、0.92 秒的按钮正常变成 `visited_label`；1.39 秒、1.43 秒的显示「请求第三方失败」；隔 5 秒回应的也是失败（`test_interaction_ack_threshold`、`test_interaction_ack_timing_and_event_ids`）。
  - 超时、重复回应时 `PUT /interactions/{id}` 都返回成功，不报错。
  - 回应若是这次会话里第一个 HTTP 请求，单是建立连接就可能超时：「0 秒后回应」的按钮实际用了 1.39 秒。
  - 群里点回调按钮时，机器人正在分片上传大图，回应虽成功，按钮却显示「请求第三方失败」；随后的被动回复照常发出。
  - 改成 SDK 自动回应后，处理函数 3 秒后才回复，按钮仍立刻变成 `visited_label`（`test_callback_button_interaction`）。
  - `visited_label` 只是临时显示：收到这条回复（新消息）后，按钮又显示回 `label`。
  - 群里改用自动回应后，同样的场景（机器人正在分片上传大图）按钮也正常变成「已回调」。
- **实现**：`Bot` 默认先替处理函数回应「成功」（`auto_ack=True`，可关）；SDK 自建的 HTTP 客户端把空闲连接保留 60 秒，免得回应时重新握手。

### 富媒体：内联上传与分片

- **位置**：单聊、群聊上传页的 `file_data`（5M）；`rich-media.md`「注意事项」（分片默认 5MB）；预上传页的示例（`"10485760"`）；分片完成页的 `block_size`。
- **结论**：
  - 内联上传：原始 5.5 MB（base64 后 7.3 MB）的图片也被接受，「5M」在这几个大小上没有生效（`test_inline_size_limit`）。
  - 约 25 MB 的文件（`FileType.FILE`）：预上传给的 `block_size` 是 `"10485760"`，共 3 片（10、10、5 MiB），每片另带自己的 `block_size`。最后一片填实际大小被接受，文件消息发送成功（`test_large_file_type_upload`）。
  - 约 3.6 MB 与约 12 MB 的图片、约 24.5 MB 的 mp4 视频都只给一片，`block_size` 等于文件大小（`test_large_video_in_parts`）。是否分片看文件类型：只有「文件」按 10 MiB 切。
  - 群聊的分片上传（约 3.6 MB 的图片）同样成功。
- **实现**：不变；`INLINE_LIMIT` 仍是 3 MiB，偏保守但不出错。

### 素材库：`.jpg` 被接受

- **位置**：`material-management.md`「限制说明」与错误码 40035001。
- **结论**：文件名 `.jpg`、Content-Type `image/jpeg` 的图片申请上传成功（`test_media_image_library_jpg`）。
- **实现**：不变。

### 流式消息：`content_type=text` 时按原文显示

- **位置**：流式消息接口页的 `content_type` 与 `content_raw`。
- **结论**：`reply_stream(markdown=False)` 发的 `**这几个字不应加粗**` 被接受，客户端按原文显示星号（`test_c2c_reply_limit_and_plain_stream`）。
- **实现**：不变。

### 流式消息：每个分片的响应都带同一个 `id` 与 `ref_idx`，同一条消息可以回两条

- **位置**：流式消息接口页的响应（「首条返回 stream_msg_id」）与示例。
- **结论**（2026-11-20，`test_quote_indices_and_two_streams`，`coalesce=False` 逐片发 3 片加结束分片）：
  - 每个分片的响应（含结束分片）`id` 都是 `stream_msg_id`，`ext_info.ref_idx` 也都相同（被平台拆成几条时会变，见「流式消息：超过约 15000 字节被拆成几条气泡」）；引用这条流式消息时 `ref_msg_idx` 就是它。
  - 对同一条用户消息先后被动回复两条流式消息都被接受，各自正常显示、正常结束。
- **实现**：不变，`stream.ref_idx` 取第一次给出的值。

### 流式消息撤回不了

- **位置**：撤回单聊消息页只说「消息 ID」，流式消息页没提撤回。
- **结论**（2026-11-20）：用单聊的撤回接口撤回两分钟内结束的流式消息，传 `stream_msg_id` 报 40061001「请求参数无效」（两个用例各一次，最近的一次在结束后 10 秒），传 `ref_idx` 报 40011002「不支持的调用」（`test_waiting_bubble_and_stream_recall`）。分片响应里没有别的 ID。
- **实现**：`client.users.recall_message()` 的 docstring 与 `guide.md` 写明；不在本地拦，留给平台判断。

### 流式消息：被下一条流式消息或另一条回复提前结束，之后的分片报 40034019

- **位置**：流式消息接口页的错误码只有 40007、50001、50002；40034019、40034016 文档里都没有。
- **结论**（2026-11-20，`test_stream_finish_variants`，单聊，都逐片发送）：
  - 40034019「流式引导已经结束，不能继续发送」出现在流式消息还没结束时：
    - 对同一条消息再开一条流式消息并发完（纯文本流里插 Markdown 流、Markdown 流里插 Markdown 流），前一条的结束分片报 40034019。结束分片与新流的第一片同时发也一样（照 qtalk-bot 的时序：先「正在输入」，再开纯文本过程流，结束分片与 Markdown 回答流的第一片同时发）。
    - 等待结束期间，测试用户发来另一条消息、机器人回复了它，之后结束分片报 40034019。
    - 对同一条消息插一条普通文本或 Markdown 消息，结束分片照常被接受；先结束前一条再开新的流式消息，两条都正常。
  - 与 `content_type` 无关：纯文本的空结束分片在含 emoji、换行、链接、20 片、最后一片后隔 60 秒、之前先回过一条普通消息时都被接受；Markdown 流里插 Markdown 流同样报 40034019。qtalk-bot 的 Markdown 过程消息没遇到，应是结束分片碰巧先到了。
  - 被这样结束的流式消息，客户端里显示正常，就是已经发出的内容。
  - 其它结束方式：最后一段随结束分片（`input_state=10`）一起发、用 replace 带全文结束，都被接受。结束分片改用 `content_type=markdown` 报 40034016「流式消息msgtype不同」，这条消息之后一直显示一个闪烁的点，直到机器人回复了用户的下一条消息才消失。
- **没有测**：用户发来新消息而机器人不回复，会不会结束流；对用户的另一条消息开流式消息。
- **实现**：`StreamMessage.finish()` 的空结束分片遇到 40034019 时当作正常结束（记一条 DEBUG），内容分片遇到时照常抛出。`StreamMessage` 的 docstring 与 `guide.md` 写明先结束、再开下一条流式消息或回复另一条消息。没有加 `finish(text)`：空的结束分片本身没有问题。

### 流式消息：超过约 15000 字节被拆成几条气泡，多出的每条占一个 `msg_seq`

- **位置**：流式消息接口页没提长度上限，`remain_msg_len` 只写「流式消息剩余长度（字符数）」；发消息页说 `msg_seq` 用于去重。
- **结论**（2026-11-20，`test_stream_auto_split`，两次运行共 15 条流式消息，都逐片发送）：
  - 按 Markdown 原文的 UTF-8 字节数拆，与字符数、时长、分片数无关：中文 8000 字（22880 字节）拆成两条，ASCII 8000 字（8000 字节）不拆、20000 字在第 14933 字处拆开；1200 字拖 325 秒（31 片）、2000 字分 501 片（324 秒）都不拆。
  - 规则：接上某一片会让当前这条超过 15000 字节时，这一片整个放进下一条。硬切在两片之间，不看行、段落与 Markdown 结构。量到位置的 10 次拆分里，除下面的例外，第一条都不超过 15000 字节（最多正好 15000），再接一片都超过（最少 15020）；标题、列表、加粗、链接、表格、行内代码都不额外计重。
  - 例外：有一次表格横跨边界，第一条只有 14387 字节就拆了（再接一片也只有 14702）。原因不明，可能平台把积压的两片一起处理；整条都是表格的那次符合上面的规则。
  - 没有硬上限：中文 30000 字（85800 字节，每片 1000 字）全部被接受，拆成 6 条，每条 5 片（14300 字节）。
  - 显示：拆在代码块中间时，第一条的代码块正常；第二条的代码显示成纯文本，结尾的 ` ``` ` 反被当成代码块的开头，之后的正文都显示成代码。拆在表格中间时，第二条里的表格行显示成纯文本；拆在列表项中间时，这一项的后半段显示成纯文本。拆在段落、标题之间的显示正常。
  - 响应里没有可靠的信号：各片的 `id` 不变；`ext_info.ref_idx` 拆开后换成新值，但晚 0～2 片才出现（进了新气泡的那一片，响应里可能还是旧值）；`remain_msg_len` 在 15 条里每片都是 0；没有文档外的字段。
  - 引用拆出的气泡时，`ref_msg_idx` 与 `msg_elements[0].msg_idx` 都是拆开后新出现的那个 `ref_idx`。`msg_elements[0].content` 是那条气泡的 Markdown 原文，但去掉了开头的空白（有一次还少了开头的一个列表项）。
  - 多出的每条气泡各占被回复消息的一个 `msg_seq`：流式消息用 `msg_seq` 1，拆成 6 条之后，对同一条消息用 `msg_seq` 2～6 被动回复都报 40054005「消息被去重，请检查请求msgseq」，7～12 都被接受；拆成两条之后 `msg_seq` 2 也报 40054005。没拆开的流式消息之后，`msg_seq` 2～7 都被接受。
- **实现**：
  - 单聊、群聊的被动回复（含「正在输入」与流式消息的第一个分片）遇到 40054005 时换下一个 `msg_seq` 重发，最多重发 10 次。
  - `StreamMessage.ref_idxs` 列出响应里出现过的所有 `ref_idx`。`StreamMessage` 的 docstring 与 `guide.md` 写明上限与显示问题，建议在接近上限时在段落之间 `finish()`，再对同一条消息另开一条。
  - SDK 不在本地按字节数拆分，也不改写 Markdown。

### 单聊：用户发消息后客户端先显示等待气泡，没有回复时约 1 分钟后消失

- **位置**：文档没有提。
- **结论**（2026-11-20，`test_waiting_bubble_and_stream_recall`）：
  - 测试用户每发一条单聊消息，底部都先出现一个跳动三个点的空气泡；机器人回复时它就变成回复的文字或流式输出。
  - 机器人不回复时它一直在，重新进入聊天也在，约 1 分钟后消失（测试用户看到消失后发下一条，距前一条 61 秒）。上一个用例发「结束」后看到的就是它：机器人收到「结束」没有回复。
  - 撤回流式消息被拒不会引起它，被拒后流式消息照常显示。
- **没有测**：是否只在用过流式消息或某种机器人配置下才出现。
- **实现**：不变；`guide.md` 提醒不回复的消息会让用户看到这个气泡约 1 分钟。

### 自定义菜单：`set([])` 能清空

- **位置**：`autogen/api/v2_menu.put.md`。
- **结论**（`test_set_menu_to_itself`、`test_menu_set_then_clear`）：
  - 没有设置过时设空菜单，返回版本 1。
  - 再设一个只有一个按钮的菜单（版本 2），测试账号单聊窗口底部出现它；随后 `set([])` 返回版本 3，菜单消失，`GET` 的菜单项为空。
- **实现**：不变。

### 群：消息功能、通知事件与主动消息

- **位置**：群聊发消息、上传、撤回各页；`autogen/event/group_member_add.md`、`group_member_remove.md`、`group_del_robot.md`。
- **结论**（用户提供的测试群，机器人不是管理员）：
  - 被动回复 Markdown 加键盘、`message.upload(url=...)` 的图片、分片上传的大图都成功；撤回自己的消息成功。
  - 群里点回调按钮：`type` 11、`chat_type` 1、`scene` 为 `"group"`，用外层 `id` 被动回复成功。
  - 不带 `msg_id` 的群主动消息被拒：`err_code` 40034105「主动消息失败, 无权限」（`bot_state` 的 `allow_proactive_msg` 为 false）。群里打开主动消息后 `allow_proactive_msg` 为 true，同样的主动消息被接受（2026-11-17，`test_proactive_group_message`）。
  - 查单个成员与成员列表一样报 40012010。
  - `GROUP_MEMBER_ADD`、`GROUP_MEMBER_REMOVE` 有 `group_openid`、`member_openid`、`timestamp` 和文档没有的 `union_openid`（空串）；退群事件没有文档说的 `user_openid`。
  - `GROUP_DEL_ROBOT` 有 `group_openid`、`op_member_openid`、`timestamp`；拉回后的 `GROUP_ADD_ROBOT` 同前，用它回复成功。
- **没有测**：群级主动消息开关的事件（`GROUP_MSG_REJECT` / `RECEIVE`，或 `type` 19 的授权互动）。
- **实现**：`GroupMemberAdd`、`GroupMemberRemove` 补上 `union_openid`。fixture：`gateway_group_member_add.json`、`gateway_group_member_remove.json`。

### 单聊被动回复的有效期：至少 55 分钟

- **位置**：`autogen/api/v2_users_user_openid_messages.post.md` 的 `msg_id` 一行写「5 分钟内有效」，同页页首与 `server-inter/message/overview.md` 的表格写单聊 60 分钟。
- **结论**（`test_c2c_reply_after_10_and_55_minutes`）：收到单聊消息后断开网关，隔约 10 分钟、约 55 分钟各用它被动回复一次，都被接受，测试用户也都收到了。「5 分钟」不对，与 60 分钟的说法一致。
- **实现**：不变，SDK 不在本地判断是否过期。

### Markdown：实际支持的语法比文档多

- **位置**：`server-inter/message/type/markdown.md`「支持格式」只列了标题、文字样式、链接、图片、有序 / 无序 / 嵌套列表、块引用、分割线与换多行。
- **结论**（`test_markdown_showcase_stream`，同一段约 1000 字的 Markdown 先流式发出、再用普通 Markdown 消息发一遍）：
  - 文档列出的语法都正常渲染，包括带尺寸的图片与 `<https://...>` 自动链接。
  - 文档没列的也都能用：代码块、表格（含对齐）、LaTeX 公式（`$...$`、`\(...\)` 行内，`$$...$$`、`\[...\]` 块级）、任务列表（`- [x]`）、脚注。
  - HTML 标签（`<u>`、`<sup>`）不生效。
  - 流式与普通消息的最终渲染一致；流式切成 124 片、每片 4～12 字发出都被接受，`remain_msg_len` 一直是 0。
- **实现**：不变，SDK 不改写 Markdown 内容。

### 流式消息：每片要等上一片的往返，逐片发送很慢

- **位置**：流式消息接口页（限频 50 QPS，没提分片之间的时延）。
- **结论**（`test_markdown_showcase_stream`，同一段约 1000 字、124 段内容）：
  - 分片要等上一片的响应（带 `stream_msg_id`、按 `index` 顺序到），每片请求的往返约 0.4 秒（跨境访问；中位 0.39 秒，最长 1.43 秒）。
  - 一段一片地发，用了 125 个请求、58.3 秒，测试用户明显感到间隔长。
  - 改成合并分片后，同样的内容按每 0.05 秒一段产生，只发了 16 个请求、7.4 秒发完，基本跟上了生成速度；测试用户感觉顺畅，渲染正常。
- **实现**：`StreamMessage` 默认合并分片（`coalesce=True`）：同时只有一个请求在路上，期间追加的内容攒成下一片；`coalesce=False` 保留逐片发送。

### 入群申请 `GROUP_JOIN_REQUEST`：字段与审批

- **位置**：`autogen/event/group_join_request.md`；审批接口 `POST /v2/groups/{group_openid}/approval_join_request/{member_openid}`。
- **结论**（`test_group_admin_session`，机器人是管理员，群设为加群需回答问题由管理员审核）：
  - 事件体有 `apply_at`（RFC3339，`+08:00`）、`apply_source`（`self_apply`）、`group_openid`、`join_request_id`（约 200 字符的字符串）、`member_openid`、`username` 与 `verify_info`。
  - `verify_info` 是 `{"method": "admin_review_qa", "review_qa_list": [{"question": ..., "answer": ...}]}`，键名是 `method`，不是说明里的 `auth_type`；没有 `auto_approved`。
  - 申请人的 `member_openid` 与他之前在群里 @机器人、退群时的 `member_openid` 相同：同一个人退群重进，群成员 openid 不变。
  - 用事件的 `decline(reason="pyqbot 实测")` 与 `approve()` 审批都被接受；通过后紧接着推送 `GROUP_MEMBER_ADD`。
- **实现**：不变。

### 禁言：再次 `add` 等于 `update`，空串的 `del` 立即解除

- **位置**：`autogen/api/v2_groups_group_openid_restrict_chat_setting.post.md` 的 `SetMemberMuteState`。
- **结论**（`test_mute_update_then_unmute`、`test_mute_twice_with_add`，机器人是管理员，对象是普通成员）：
  - `add` 禁言 2 分钟后用 `update` 改为 5 分钟，查询到的到期时间随之改变。
  - 对已在禁言中的成员再 `add` 一次也不报错，到期时间改为新的，效果同 `update`。
  - `del` 带 `mute_expire_at: ""` 立即解除。
  - 禁言查询里的成员带 `username` 与 `union_openid`（空串）。
- **实现**：`mute_members()` 的 docstring 写明再次调用会改写到期时间。

### 撤回：管理员能撤回普通成员的消息

- **位置**：`server-inter/message/overview.md`「撤回消息」只说能撤回自己的；群聊撤回页说管理员还能撤回普通成员的消息。
- **结论**：机器人撤回自己 10 秒前发的群消息成功（`test_group_message_features`）；机器人是管理员时，用 `recall_message(group, message)` 撤回普通成员刚 @ 它的消息也成功（`test_group_admin_session`）。
- **实现**：不变，`client.groups.recall_message()` 接受收到的 `GroupMessage`。

### 群：「获取群内全部消息」时 @ 消息只推全量事件

- **位置**：`autogen/event/group_message_create.md`、`group_at_message_create.md`。没说开启接收全部消息后 @机器人 的消息推哪个事件。
- **结论**（`test_group_all_messages`，群设置「机器人可获取的群聊消息范围」为「获取群内全部消息」）：
  - `bot_state` 的 `recv_msg_setting` 随之变为 `all`（「仅获取 @机器人的消息」时是空串）。
  - 不 @ 机器人的消息推 `GROUP_MESSAGE_CREATE`，字段与 @ 消息相同，含 `author.member_nickname` 与 `group_id`。
  - @机器人 的消息也只推 `GROUP_MESSAGE_CREATE`，不推 `GROUP_AT_MESSAGE_CREATE`，所以不会重复。它的 `content` 是 `"<@机器人的 member_openid> 测试一下at"`，前缀没有去掉。
  - `mentions` 里机器人那一项有文档没提的 `is_you: true`、`scope: "single"`，以及 `bot: true`、`member_nickname`。
  - QQ 表情在 `content` 里写作 `<faceType=3,faceId="427",ext="...">`，`ext` 是 base64 的 JSON（如 `{"text":"偷感"}`）。
- **实现**：`GroupMessageMember` 补上 `is_you`、`scope`；`GroupMessage.mentions_me` 判断是否 @ 了本机器人（`GroupAtMessage` 上恒为真）；`on_group_at_message` 的 docstring 写明全量模式下收不到。表情原样保留在 `content` 里，不解析。fixture：`gateway_group_message_create_mention.json`。

### 富媒体：图片、语音、视频格式比文档列的多

- **位置**：`server-inter/message/rich-media.md` 的「支持的消息类型」与同页「文件类型与限制」表格；单聊、群聊上传页的 `file_type` 一行（图片 png/jpg、语音 silk 等，各页不一）。
- **结论**（`test_image_and_voice_formats`、`test_ffmpeg_voice_and_video_formats`、`test_group_media_formats`）：
  - 单聊与群聊里，gif、webp、bmp、jpg 图片，wav、mp3、ogg（vorbis）语音，mp4 视频都上传、发送成功，客户端正常显示、播放。
  - 曾用的 1×1 webp 样本是全透明像素，客户端显示空白；换成 64×64 的绿色 webp 后正常。
- **没有测**：silk 语音（本机没有编码器）。
- **实现**：不变，SDK 按扩展名推断 `file_type`。

### @全体成员：超限报 40034142，不是 304019

- **位置**：`server-inter/message/trans/text-chain.md`（机器人须是群管理员，每个群每天一次）；`openapi/error/error.md`、`dev-prepare/api-call-guide.md` 的 304019「@全体成员 次数超限」。群聊发消息页的错误码表里两者都没有。
- **结论**（`test_at_everyone`，2026-11-17，机器人是管理员，主动发文本）：第一次被接受；5 秒后再发一次被拒，`err_code` 40034142「消息发送失败，@全体成员次数超限」。用户确认第一条在群里正常显示。
- **实现**：不变，SDK 不在本地计数。群聊 `send_message()` 的 docstring 写明这个限制与错误码。

### 链接：按钮不接受自定义 scheme，第三方 https 链接可用

- **位置**：`server-inter/message/trans/msg-btn.md` 说跳转按钮用「http 或 小程序 客户端识别 scheme」；公共错误码 304003「url 未报备」。群聊发消息页的错误码表里没有 40034028。
- **结论**（2026-11-17，群主动消息，Markdown 加跳转按钮；被拒时把按钮逐个拆开重发）：
  - 跳转按钮的 `data` 是 App 的自定义 scheme（`xxx://...`）时整条消息被拒：40034028「请求参数不允许包含url {scheme 后的第一段}」。
  - 第三方网站的 https 链接作跳转按钮被接受，没有遇到 304003。单聊里正文链接与跳转按钮点开后都在 QQ 内置浏览器里打开。
  - Markdown 正文里第三方网站的 `[文字](https://...)` 与裸链接、第三方图床的带尺寸图片都被接受；`pic_url` 是第三方图床的卡片也被接受。用户确认这些消息在群里显示正常：图片、换行与空行、引用块里的图片、链接、卡片、按钮。
- **实现**：`Button.link()` 的 docstring 写明不能用自定义 scheme。SDK 不在本地校验，交给平台判断。

### Markdown：形如链接、目标却不是 URL 的文字被判「消息内容违规」

- **位置**：群聊发消息页错误码 40034006「消息内容违规」；`server-inter/message/type/markdown.md` 没提转义。
- **结论**（2026-11-17，群主动消息；一段转义测试的 Markdown 被拒后，逐行、逐段拆开重发）：
  - 触发的是 `方括号\[e\](f)`。`[e](f)`、`\[e\](f)`、`\[e\] (f)` 都报 40034006：方括号转义了、`]` 与 `(` 之间隔一个空格都没用。
  - `\[e\]\(f\)`（圆括号也转义）、`\[e\]`、`方括号 (f)`、`[e](https://example.com/f)` 都被接受。
  - 其余转义都被接受：`` \* \_ \~ \` \< \| \$ ``，行首的 `\#`、`\>`、`\-`、`\+`、`1\.`，以及 `\<b>f\</b>`、`C:\\path\\to`。
- **实现**：SDK 不改写 Markdown，`Markdown` 的 docstring 写明要把圆括号也转义。

### Markdown 图片：不写宽高不显示，抓不到时显示「图片加载失败」，接口不报错

- **位置**：`server-inter/message/type/markdown.md`「图片」（只给了带宽高的示例，说平台会下载转存）；`server-inter/message/material-management.md`「在 Markdown 消息中引用（与公网图片语法一致，宽高可选）」；接口页 `MessageMarkdown` 的 `force_verify_image_resource`。
- **结论**（2026-11-20，`test_markdown_image_variants`，单聊；流式的都逐片发三片：图前的文字、图片、图后的文字）：
  - 不写宽高时不显示图片：`![百度的标志](地址)` 显示成文字「[百度的标志]」。素材库的图不写宽高也一样，「宽高可选」不对。
  - 宽高按写的显示，不保持原图的比例：540×258 的图写成 `#300px #300px` 被拉伸；写成 `#2160px #1032px`（比例没变，只是很大）显示出来被压扁。
  - 平台抓不到图时接口不报错：流式消息的每一片与结束分片照样被接受，客户端在图的位置显示「图片加载失败」。404 的地址、地址是网页、主机解析不了、维基共享资源（`thumb.wikimedia.org`）的图都是这样。普通 Markdown 消息同样被接受、同样显示「图片加载失败」。
  - 普通 Markdown 消息带 `force_verify_image_resource` 时，404 的图让整条消息被拒：HTTP 400，`err_code` 40034141「图片转存失败，请重试」。流式消息没有这个开关。
  - 境内的第三方图站（`www.baidu.com`）与 NASA（`assets.science.nasa.gov`，地址带查询串）的图，各分片都被接受；测试用户没有记下观察（显示失败的几种都记了）。
- **没有测**：图是在流式过程中出现还是结束后才出现；宽高写到多大开始变形；群聊。
- **实现**：`Markdown`、`MediaImage` 的 docstring 与 `guide.md` 写明宽高必须写、要按原图的比例；SDK 不改写 Markdown，也不替调用方量图片的尺寸。

### 素材库：流式消息里可以引用，发出后删掉素材不影响已发的消息

- **位置**：`server-inter/message/material-management.md`「删除图片」（引用链接立即失效；已发送消息不受影响，发送时平台已转存图片副本）与错误码 40035009。
- **结论**（2026-11-20，同上用例，`LIVE_MEDIA_IMAGES=1`，每种上传一张 300×200 的纯色图）：
  - 流式消息正文中间引用 `qqbot-media://` 的图（带宽高），各分片被接受；结束分片返回后立刻删掉素材，删除成功。测试用户发出编号后就退出聊天，等发完、删完之后再进入，图片显示正常：与文档一致，已发的消息不受影响，也不是客户端的缓存。
  - 普通 Markdown 消息引用后立刻删掉素材：发送与删除都被接受（测试用户没有记下观察）。
  - 流式消息引用已经删掉的素材：各分片与结束分片都被接受，没有报 40035009，客户端显示「图片加载失败」（做了两次，退出再进入与一直留在聊天里都一样）。
  - 上传返回的 `ttl` 都是 7776000。
- **没有测**：普通消息引用已删除的素材是否报 40035009；流式消息还没结束就删掉素材。
- **实现**：不变；`Images.delete()` 的 docstring 已写明已发出的消息不受影响，`guide.md` 补上「发完就可以删，不占 100 张的额度」。

### 键盘：同组的回调按钮要各带 `id`，同组的点过之后一直变灰，不分组的只是临时的

- **位置**：`server-inter/message/trans/msg-btn.md` 与接口页的 `Button`（`id` 选填，「同一键盘内唯一」；`group_id`「同一分组内有一个按钮操作后，其它按钮则变灰不可点击」）、`ButtonModal`（`content` 最多 40 个字符，`confirm_text`、`cancel_text` 最多 4 个字符）、`render_data.label`。
- **结论**（2026-11-21，`test_button_and_markdown_variants`，单聊，两次运行：第一次回调按钮都不带 `id`，第二次同组的按钮各带一个 `id`）：
  - 两个以上的按钮用同一个 `group_id` 而不带 `id` 时整条消息被拒：HTTP 400，`err_code` 40011021「请求参数rows.buttons.id无效」。同组两个、四个排一行、四个分两行、其中一个带二次确认，5 次都一样。只有一个按钮带 `group_id` 时被接受；不分组的四个按钮被接受。
  - 四种样式（灰框、蓝框、红字、蓝底）的按钮在一条消息里被接受，四个都点得动（测试用户没有记下各自的样子）。
  - 同组的按钮各带 `id` 时都被接受（同样的 5 种）。点了一个之后，被点的变成 `visited_label`，同组其余的变灰；四个一组的两种，测试用户看到的是所有按钮都变灰。这个状态一直保持：退出聊天再进入还在，之后再有新消息（用户发的、机器人对这次点击的回复）也还在。四个按钮排一行放得下。每种都只记到一次点击（变灰之后有没有再点过没有记下）。
  - 带二次确认的红字按钮（同组、带 `id`）：确认之后变成 `visited_label`，状态同样保持。只记到确认之后的那一次点击。
  - 不带 `id` 时点过之后的状态是临时的：不分组的按钮、只有一个按钮的分组（点了不回复与点了回复一句两种）、指令按钮，点过之后都变了样子，但用户或机器人任何一方再发一条消息，就都恢复成可以点的样子。只有一个按钮的分组（不带 `id`）里，同一个按钮先后记到了两次点击。
  - 二次确认的文字超过文档写的长度时整条消息被拒（40011021）：`content` 41 个字报「rows.buttons.action.modal.content无效」，`confirm_text`、`cancel_text` 各 5 个字报「rows.buttons.action.modal.confirm_text无效」。
  - 按钮文字 10、12、20 个字的三个按钮（一行一个）在一条消息里被接受，文档写的 10 个字符不是被拒的界线（显示有没有截断没有记下）。
  - 指令按钮在单聊里：`enter=True` 的点了直接发出，机器人收到的 `content` 就是 `data` 原文，没有「@机器人」；不带 `enter` 的填进输入框，用户手动发出后 `content` 是 `data` 后面多一个空格；`enter=True`、`reply=True` 的也直接发出，但收到的消息没有 `ref_msg_idx`（两次都是），机器人看不出它引用了哪条消息。
- **没有测**：只有一个按钮、带 `id` 与 `group_id` 时点过之后的状态保不保持；不分组而带 `id` 的按钮；二次确认里点「取消」推不推互动事件；变灰的按钮再点推不推事件。
- **实现**：不变，SDK 不替调用方生成 `id`。`Button`、`ButtonRenderData`、`ButtonModal`、`Button.command()` 的 docstring 与 `guide.md` 写明：`group_id` 要与 `id` 一起用、两种按钮点过之后的状态、文字的上限、指令按钮在单聊里发出的内容。

### 互动事件作被动回复的对象：「正在输入」可以，流式消息不行

- **位置**：流式消息接口页的 `msg_id`、`event_id`；单聊发消息页的 `InputNotify`。
- **结论**（2026-11-21，同上用例；点回调按钮后用这次互动事件作 `reply_to`）：
  - `users.send_typing(reply_to=interaction)` 被接受，客户端显示了「正在输入」。
  - `users.stream_message(reply_to=interaction)` 的第一片被拒：HTTP 400，`err_code` 40111003「请求错误，参数msg_id不能为空」。流式消息只能回复消息，不能回复事件。
  - 随后的 `interaction.reply()`（普通的被动回复）照常送达。
- **实现**：不变，`reply_to` 的类型没有收窄。`users.stream_message()` 的 docstring 与 `guide.md` 写明要用收到的消息：点按钮之后要流式回答，只能对还在有效期内的某条用户消息回复。

### Markdown：2 个空格的嵌套列表不会压平，代码块里的图片写法只在气泡被拆开后才成图

- **位置**：`server-inter/message/type/markdown.md`「嵌套列表」（只说子项缩进 4 个空格）；代码块、HTML 文档都没提。
- **结论**（2026-11-21，同上用例，单聊，流式消息；测试用户做完之后口头总结，没有逐种记下）：
  - 嵌套列表的子项缩进 2 个空格与 4 个空格都有层次，没有被压平。第三层看起来比前两层缩进得更多，像隔了一层，可能是客户端渲染的结果。
  - 下面这些写法里的图片语法（都带宽高，地址是能显示的图）都没有显示成图片：`<img>` 标签、反斜杠转义的 `\![…](…)`、全角感叹号的「！[…](…)」、行内代码；顶格的反引号代码块、波浪线代码块、块公式（`\[`、`$$`）里夹着反引号行、行中间的三个反引号、反引号后面跟着别的字的行、列表项里缩进的代码块、四个反引号套三个反引号、前后都没有空行的代码块；流式消息的代码块还没有结束行的 8 秒里与补上结束行之后；流式消息结束时代码块仍没闭合。各种写法具体显示成代码还是纯文本没有记下。
  - 16776 字节的流式消息被拆成两条气泡、切口落在代码块里时：第二条里的代码行显示成纯文本，其中那行带宽高的图片语法显示成了图片；结尾的 ` ``` ` 之后直到消息末尾显示成代码。即前面「超过约 15000 字节被拆成几条气泡」一条里说的显示问题，对图片语法也成立：代码块里的图片语法落到拆出来的后一条气泡里就会被平台抓取、显示。
- **实现**：不变，SDK 不改写 Markdown；`guide.md` 写明这几点。调用方要让代码块里的内容保持原样又不想让其中的图片语法成图时，得保证整个代码块落在第一条气泡里（自己在约 15000 字节之前分条）。
