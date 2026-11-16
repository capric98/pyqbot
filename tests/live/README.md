# 实测清单

对真实接口的用例，默认不运行。每次运行前都要先向用户说明会调用哪些接口并取得同意（`AGENTS.md`「实测」），同意只对当次有效。各用例的细节以 docstring 为准，这里只列要做什么、看什么。

## 怎么运行

```sh
uv run --env-file .env pytest -m live --no-cov                      # 全部（未打开开关的会 skip）
uv run --env-file .env pytest -m live --no-cov -k upload --log-cli-level=WARNING   # 只跑一部分，并在终端显示用例记的日志
LIVE_GATEWAY=1 uv run --env-file .env pytest -m live --no-cov tests/live/test_live_events.py::test_friend_del_then_add --log-cli-level=WARNING
```

## `.env` 里的变量与开关

开关的值写 `1` 才算打开；没有的变量或没打开的开关会让对应用例 skip。

| 名字 | 作用 |
| --- | --- |
| `APP_ID`、`APP_SECRET` | 机器人凭证，所有真实接口用例都要 |
| `TEST_USER_OPENID` | 测试用户的单聊 openid；只能给他发消息 |
| `LIVE_GATEWAY` | 连网关的用例（每个消耗一次连接次数） |
| `LIVE_WAIT_SECONDS` | 连上网关后等测试用户操作的秒数；`test_live.py`、`test_live_bot.py` 默认 0，其余默认 180 |
| `LIVE_WRONG_SECRET` | 用错误的密钥鉴权一次 |
| `LIVE_TOKEN_WINDOW` | 观察 token 换发，最长两个多小时 |
| `LIVE_GLOBAL_CONFIG` | 改菜单、增删面板（影响所有用户） |
| `LIVE_MEDIA_IMAGES` | 素材库（机器人全局） |
| `TEST_GROUP_OPENID` | 测试群；群用例都要（由 `test_group_add_robot` 取得） |
| `LIVE_GROUP_WRITE` | 会改动群或机器人配置的群用例 |
| `TEST_GROUP_MEMBER_OPENID` | 群里一个可以被禁言、不在黑名单的普通成员 |
| `TEST_GROUP_REMOVABLE_OPENID` | 同意被移出测试群的成员 |
| `TEST_GROUP_APPLICANT_OPENID` | 正在申请加入测试群的用户 |

## 用例

### 只读

- `test_live.py::test_token_success_response`：看 `report.txt` 里 token 响应的结构（`expires_in` 的类型等）。
- `test_live.py::test_sdk_token_works_for_read_only_endpoints`：`/users/@me`、`/gateway`、`/gateway/bot` 都是 200。
- `test_live.py::test_wrong_secret_error`（`LIVE_WRONG_SECRET`）：看错误响应的字段与 SDK 抛出的异常类型、`err_code`。
- `test_live.py::test_token_refresh_window`（`LIVE_TOKEN_WINDOW`）：看 `token_window.jsonl` 里何时换发、旧 token 是否还能用。
- `test_live.py::test_gateway_accepts_group_member_intent`（`LIVE_GATEWAY`）：`report.txt` 里收到 READY，没有被关闭码拒绝。
- `test_live_bot.py::test_get_me`：`bot.txt` 里的名字、头像是这个机器人的；原始响应里有没有 `share_url`、`welcome_msg`。
- `test_live_bot.py::test_generate_share_link`：`bot.txt` 里有一条 https 链接。
- `test_live_bot.py::test_get_menu`：`bot.txt` 里的按钮与测试账号单聊窗口的菜单一致。
- `test_live_bot.py::test_raw_recorder_redacts_credentials_echoed_by_the_platform`：本地自检，不访问网络；没有 `live` 标记，随默认的 `uv run pytest` 运行，不在 `-m live` 里。

### 会给测试用户发消息

都是主动消息，占用主动消息额度；发完请测试用户确认看到的效果。

- `test_live_messages.py::test_markdown`：标题、粗体、斜体、可点的链接。
- `test_live_messages.py::test_markdown_with_buttons`：两行按钮；点「回调」文字变「已回调」，「指令」点后直接发出 `/pyqbot`。
- `test_live_messages.py::test_card`：图文卡片，点击打开 qq.com。
- `test_live_messages.py::test_quote_previous_message`：第二条以引用形式展示第一条。
- `test_live_messages.py::test_typing`：「正在输入」约 10 秒后消失；被拒就把错误码记进 errata。
- `test_live_messages.py::test_send_then_recall`：消息出现后很快变成撤回提示。
- `test_live_messages.py::test_quote_by_message_id`：用消息 ID（不是引用索引）引用上一条；被拒的错误码记进日志。
- `test_live_messages.py::test_text_with_media_and_card`：图片、卡片各带一行文字，看文字是否显示。
- `test_live_messages.py::test_wakeup`：互动召回「pyqbot：互动召回实测」；每个周期只能发一条，会占掉当前周期。
- `test_live_upload.py::test_url_upload`：官方示意图。
- `test_live_upload.py::test_inline_data_is_base64`：红色小方块与「内联上传」。
- `test_live_upload.py::test_large_file_is_uploaded_in_parts`：约 1200×1000 的噪点图与「分片上传」。
- `test_live_upload.py::test_file_over_10m_is_uploaded`：约 2000×2000 的噪点图与「多片上传」；分片情况记进日志。
- `test_live_upload.py::test_upload_and_send_directly`：同 `test_url_upload` 的图，由上传接口直接发出。
- `test_live_upload.py::test_image_and_voice_formats`：gif、webp、bmp、jpg 四张绿色小图与一条 wav 语音；被拒的格式记进日志。
- `test_live_upload.py::test_inline_size_limit`：不发消息，内联约 3.6、4.5、5.5 MB 的图片，看「5M」限制的是编码前还是编码后。
- `test_live_upload.py::test_large_file_type_upload`：约 25 MB 的文件（`FileType.FILE`），看是否支持、分几片。
- `test_live_upload.py::test_ffmpeg_voice_and_video_formats`：mp3、ogg 两条语音与一段 mp4 视频，样本由 ffmpeg 生成（`FFMPEG` 或 PATH）。
- `test_live_upload.py::test_large_video_in_parts`：约 25 MB 的雪花视频，看视频类型怎么分片。

### 需要测试用户动手配合

都要 `LIVE_GATEWAY`，并把 `LIVE_WAIT_SECONDS` 设得够人操作；只认测试用户触发的事件。

- `test_live.py::test_bot_replies_to_a_c2c_message`：测试用户发一条单聊，收到机器人的回复。
- `test_live.py::test_gateway_identify_wait_for_message_then_resume`：等待期间可发一条单聊；看 `report.txt` 里 Resume 是否成功。
- `test_live_bot.py::test_stream_reply`：测试用户发一条单聊，回复分段出现，最后不再显示「生成中」。
- `test_live_bot.py::test_markdown_showcase_stream`：发「开始」后流式收到一段覆盖各种 Markdown 语法的内容（`LIVE_MARKDOWN_COMPARE=1` 时再收到普通版），看各语法的渲染。
- `test_live_events.py::test_friend_del_then_add`：删好友再加回（在 QQ 里打开 `test_generate_share_link` 生成的链接），收到「pyqbot：欢迎回来」。
- `test_live_events.py::test_c2c_reply_limit_and_plain_stream`：先后发两条单聊；第一条收到「正在输入」与最多 4 条回复，第二条收到纯文本流式回复（`**` 不加粗）。
- `test_live_events.py::test_c2c_reply_after_10_and_55_minutes`：发一条单聊后约 10、55 分钟各收到一条被动回复（被拒的收不到）；约 56 分钟，在后台跑。
- `test_live_events.py::test_interaction_ack_timing_and_event_ids`：先点「晚回应」再点「快回应」，收到最多三条回复。
- `test_live_events.py::test_interaction_ack_threshold`：四个按钮分别在 0、0.3、0.6、1 秒后回应，看哪些变成「已点」（实测约 1 秒为界）。
- `test_live.py::test_resume_replays_backlog`：先发一条多图单聊，断开后 30 秒内再发两条文字，看 Resume 补发与心跳的先后。
- `test_live_events.py::test_multi_image_message`：在电脑上一次发多张图，记下一条消息里的附件数与大小。
- `test_live_events.py::test_c2c_msg_reject_then_receive`：资料卡里关闭再打开主动消息；平台实际推的是授权互动，停手 15 秒后收到「pyqbot：授权已变更」。
- `test_live_events.py::test_callback_button_interaction`：点「点我」，按钮立刻变「已点」（SDK 自动回应），约 3 秒后收到回复。
- `test_live_misc.py::test_message_upload_shortcut`：测试用户发一条单聊，收到带图的「pyqbot：upload 快捷方法」。

### 影响机器人全局配置，须单独同意

- `test_live_bot.py::test_set_menu_to_itself`（`LIVE_GLOBAL_CONFIG`）：菜单原样设回，版本号变大、菜单看起来不变。
- `test_live_bot.py::test_menu_set_then_clear`（`LIVE_GLOBAL_CONFIG`）：单聊窗口底部出现「pyqbot」菜单约 30 秒后消失；只在菜单原本为空时运行。
- `test_live_bot.py::test_panel_lifecycle`（`LIVE_GLOBAL_CONFIG`）：在单聊输入框输入 `/` 唤出面板，约 30 秒内是「pyqbot」，之后约 30 秒是「pyqbot2」（删掉 `/` 重新输入才刷新），结束后消失。
- `test_live_upload.py::test_media_image_library`（`LIVE_MEDIA_IMAGES`）：收到「素材库」与蓝色图片，结束后图片从列表里删除。
- `test_live_upload.py::test_media_image_library_jpg`（`LIVE_MEDIA_IMAGES`）：不发消息，看 `.jpg` 文件名是否被接受，成功就删除。

### 需要测试群

先取得测试群：连上网关后把机器人拉进群，群的 openid 会写进 `.cache/live/test_group.env`，把其中的 `TEST_GROUP_OPENID` 加进 `.env`。

- `test_live_events.py::test_group_add_robot`（`LIVE_GATEWAY`）：拉机器人进群，群里收到「pyqbot：已加入，用于 SDK 实测」。
- `test_live_events.py::test_group_at_message`（`LIVE_GATEWAY`）：群里 @机器人 发「/ping」，收到「pyqbot：pong」；日志里看 `content` 是否带空格、有没有另推全量消息。
- `test_live_events.py::test_group_message_features`（`LIVE_GATEWAY`）：@机器人后收到按钮、图片、分片上传的大图（10 秒后撤回）；点「回调」收到回复，点「指令」看是否直接发出。
- `test_live_events.py::test_group_notices`（`LIVE_GATEWAY`）：等满等待时间，记下进群、退群、群主动消息开关、移出与拉回机器人等事件。
- `test_live_groups.py::test_get_member_seen_in_a_message`：用 @ 过机器人的成员查单个成员。
- `test_live_groups.py::test_proactive_group_message`：往测试群发一条主动消息，预计被拒。

只读的只要 `TEST_GROUP_OPENID`，成员与黑名单要白名单（否则 `err_code` 40012010），禁言设置与入群申请要机器人是管理员（否则 40011030）：

- `test_live_groups.py::test_get_group`：群名、人数与客户端一致。
- `test_live_groups.py::test_get_bot_state`：`member_role` 与机器人在群里的身份一致。
- `test_live_groups.py::test_iter_members_and_get_member`：成员数与群人数一致（超过 30 人时说明翻页生效）。
- `test_live_groups.py::test_iter_blacklist`：与群设置里的黑名单一致。
- `test_live_groups.py::test_get_mute_settings`：全员禁言的模式与群设置一致。
- `test_live_groups.py::test_iter_join_requests`：与待审批的申请一致。
- `test_live_groups.py::test_iter_strategies`：机器人现有的入群自动审批策略。

会改动群或机器人配置的另要 `LIVE_GROUP_WRITE` 与括号里的变量，每个都须单独同意：

- `test_live_groups.py::test_mute_update_then_unmute`（`TEST_GROUP_MEMBER_OPENID`）：禁言约 2 分钟 → 改为约 5 分钟 → 解除。
- `test_live_groups.py::test_mute_twice_with_add`（`TEST_GROUP_MEMBER_OPENID`）：第二次 `add` 是报错还是改写到期时间。
- `test_live_groups.py::test_blacklist_add_only_works_for_users_outside_the_group`（`TEST_GROUP_MEMBER_OPENID`）：黑名单不变；看是部分失败还是整个请求报错。
- `test_live_groups.py::test_remove_member_and_blacklist`（`TEST_GROUP_REMOVABLE_OPENID`）：成员被移出并拉黑，再移出黑名单；移出群无法撤销。
- `test_live_groups.py::test_decline_a_join_request`（`TEST_GROUP_APPLICANT_OPENID`）：申请人收到拒绝，理由「pyqbot 实测」，没有被拉黑。
- `test_live_groups.py::test_join_strategy_lifecycle`：建一个停用的策略（机器人全局），改动与白名单生效后删除。

频道目前不能实测，条件见 `docs/errata.md`「频道：测试条件」。

## 结果在哪，怎么沉淀

- 落盘的只有 `test_live.py`、`test_live_bot.py`、`test_live_events.py`，都在 `.cache/live/`（已被 git 忽略）。`test_live_groups.py` 与多片上传用例只把要核对的结果记进日志，要加 `--log-cli-level=WARNING` 才看得到；其余用例以测试用户在客户端看到的效果为准。
- 落盘文件中，`report.txt`、`bot.txt`、`events.txt` 已脱敏、可以贴出来；`raw/` 去掉了凭证，但含 openid 与消息内容，只留在本机。
- 与 `docs/errata.md`「待实测」相符或不符的结论，改写对应条目（写明实测日期与结论），必要时调整实现。
- 能固定下来的真实响应，去掉凭证与 openid 后存进 `tests/fixtures/`，在 `tests/test_real_samples.py` 里加本地回归测试。
