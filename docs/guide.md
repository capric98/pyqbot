# 使用指南

按使用时会遇到的主题组织，每节给一个最短的可用示例，再写「细节去哪看」。参数的含义、默认值、会抛什么异常、
对应哪个官方接口，都以 docstring 为准（IDE 悬停、`help(pyqbot.Bot)` 或直接看源码），这里不重复。
平台的实际行为以 [`errata.md`](errata.md)「已确认」为准，它比官方文档可靠。

文中 `bot` 是 `pyqbot.Bot`，`client` 是 `pyqbot.Client`；`Bot` 继承 `Client`，凡是 `client.xxx` 的地方都可以换成 `bot.xxx`。

## 目录

1. [Client 与 Bot](#1-client-与-bot)
2. [收消息与注册事件](#2-收消息与注册事件)
3. [回复与主动发送](#3-回复与主动发送)
4. [上传富媒体](#4-上传富媒体)
5. [流式消息](#5-流式消息)
6. [互动：按钮回调](#6-互动按钮回调)
7. [群管理](#7-群管理)
8. [菜单、面板与素材库](#8-菜单面板与素材库)
9. [频道（已实现，未实测）](#9-频道已实现未实测)
10. [错误处理](#10-错误处理)
11. [日志](#11-日志)
12. [找细节](#12-找细节)

## 1. Client 与 Bot

- `Client`：只调接口，不收事件。适合脚本、定时任务，或嵌进已有的 Web 服务。
- `Bot`：`Client` 加上事件注册与网关连接。构造参数同 `Client`，只多 `intents` 与 `auto_ack`。

两者构造时都不发请求，参数不合法立刻抛 `ValueError`。推荐用 `async with` 管理生命周期，也可以用完后
`await client.close()`；关闭后不能再用（抛 `RuntimeError`），要新建一个。

```python
import asyncio

import pyqbot

bot = pyqbot.Bot("APP_ID", "APP_SECRET")


@bot.on_c2c_message
async def stop(message: pyqbot.C2CMessage) -> None:
    if message.content.strip() == "/stop":
        await message.reply("再见")
        await bot.close()  # start() 随之返回


async def main() -> None:
    async with bot:  # 只管 HTTP 连接，不连网关
        await bot.start()  # 连接网关并分发事件，直到 close()


asyncio.run(main())
```

- `bot.run()` 是同步入口，等价于上面的 `main()`，另外让 Ctrl+C 安静退出。已经在事件循环里时用 `start()`。
- `start()` 只能调用一次，要在它之前注册好处理函数：一个都没有时抛 `RuntimeError`，之后再注册的不改变订阅。
  断线由 SDK 自动重连并恢复会话，只有无法恢复时才抛 `GatewayError`。
- `close()` 依次断开网关、取消还在运行的处理函数（最多等 5 秒）、关闭 HTTP 连接；可以在处理函数里调用。
- 要先停收事件、让在途的处理函数做完再关：`await bot.stop()` 只断开网关（`start()` 随之返回），等处理函数自然结束、
  不取消它们，HTTP 连接照常可用；之后再 `close()`。要限时就套 `asyncio.timeout()`。
- **网关状态**：断线由 SDK 自己重连，`bot.gateway_status` 告诉你现在连着没有、处于这个状态多久，适合每隔
  几十秒轮询一次，做断线告警或容器的健康检查。它只读本地状态，不发请求；没有回调。

  ```python
  from datetime import timedelta


  def gateway_healthy(bot: pyqbot.Bot) -> bool:
      status = bot.gateway_status
      match status.state:
          case pyqbot.GatewayState.CONNECTED:
              return True
          case pyqbot.GatewayState.STOPPED:
              return False
          case _:  # NOT_STARTED、DISCONNECTED
              return status.elapsed <= timedelta(minutes=10)
  ```

  为什么这样判断见 `pyqbot.Bot.gateway_status`；各状态的含义见 `pyqbot.GatewayState`，`since`（UTC 时间，
  适合写进告警）与 `elapsed` 的计时见 `pyqbot.GatewayStatus`。
- 走代理时传 `proxy="socks5h://user:pass@host:1080"`（也支持 http、https、socks5）：接口请求、网关连接和经
  `client.http_client` 下载附件都走它，账号密码不会出现在 `repr`、日志和异常里。不传时照常读取 `HTTPS_PROXY` 等环境变量。
- 要自定义证书、连接池等时传 `http_client=httpx2.AsyncClient(...)`，它由你负责关闭，不能再传 `proxy`（代理配在它上面）。
  这时 SDK 不知道代理的账号密码：SOCKS 代理带账号时，别把 `httpcore2.socks` 的日志开到 DEBUG，它会原样打印账号密码。
- 调用 SDK 还没封装的接口：`await client.get_access_token()` 取 token，经 `client.http_client` 发请求。

接口按资源分组挂在客户端上，机器人自身的 `get_me()`、`generate_share_link()` 直接挂在客户端上：

| 属性 | 内容 | 源码 |
| --- | --- | --- |
| `client.users` | 单聊：发消息、正在输入、撤回、上传、流式消息 | `src/pyqbot/_api/users.py` |
| `client.groups` | 群聊：发消息、撤回、上传、群管理 | `src/pyqbot/_api/groups.py` |
| `client.interactions` | 回应互动 | `src/pyqbot/_api/interactions.py` |
| `client.menu`、`client.panels`、`client.images` | 自定义菜单、指令面板、素材库 | `src/pyqbot/_api/menu.py`、`panels.py`、`images.py` |
| `client.join_strategies` | 入群自动审批策略 | `src/pyqbot/_api/join_strategies.py` |
| `client.guilds`、`client.channels`、`client.dms` | 频道、子频道、频道私信 | `src/pyqbot/_api/guilds.py`、`channels.py`、`dms.py` |

**细节去哪看**

- `pyqbot.Client`、`pyqbot.Client.get_access_token`（`src/pyqbot/_client.py`）；`pyqbot.Bot`、`pyqbot.Bot.start`、
  `pyqbot.Bot.run`、`pyqbot.Bot.close`、`pyqbot.Bot.gateway_status`（`src/pyqbot/_bot.py`）；`pyqbot.GatewayStatus`、
  `pyqbot.GatewayState`（`src/pyqbot/_gateway/status.py`）。
- [`design.md`](design.md)「入口与初始化」（含「网关状态」）；断线后重连还是放弃，见「网关连接」。

## 2. 收消息与注册事件

每种事件一个装饰器 `@bot.on_<事件>`。处理函数必须是 `async def`（否则注册时抛 `TypeError`），只收一个事件对象，
参数类型标错时 pyright 会报。同一事件可以注册多个；每个处理函数在自己的任务里并发运行，抛出的异常记一条
ERROR 日志，不影响其它处理函数和连接。

```python
@bot.on_c2c_message
async def on_c2c(message: pyqbot.C2CMessage) -> None:
    print(message.user_openid, message.content, message.attachments)


# 两个都注册，就不用关心群设置的是「仅 @机器人」还是「全部消息」
@bot.on_group_message
@bot.on_group_at_message
async def on_group(message: pyqbot.GroupMessage) -> None:
    if message.mentions_me:
        await message.reply("叫我吗？")


@bot.on_friend_add
async def welcome(event: pyqbot.FriendAdd) -> None:
    await event.reply("你好，发送 /help 查看用法")
```

- **单聊**：`on_c2c_message`，收 `C2CMessage`。
- **群里 @机器人**：`on_group_at_message`，收 `GroupAtMessage`。`content` 开头留着一个空格（如 `" /ping"`），比较前先 `strip()`。
- **群里全部消息**：`on_group_message`，收 `GroupMessage`，要在群设置里选「获取群内全部消息」。这时 @机器人 的消息
  也只推这个事件（`on_group_at_message` 收不到），`content` 带着 `<@机器人的 member_openid>` 前缀，用
  `message.mentions_me` 判断是否 @ 了自己。`GroupAtMessage` 是 `GroupMessage` 的子类，所以像上面那样把一个
  处理函数注册到两处即可。
- **通知类事件**：

  | 事件 | 装饰器 | 能 `reply()` | 说明 |
  | --- | --- | --- | --- |
  | 加好友、删好友 | `on_friend_add`、`on_friend_del` | 加好友能 | |
  | 机器人进群、被移出群 | `on_group_add_robot`、`on_group_del_robot` | 进群能 | |
  | 群成员加入、离开 | `on_group_member_add`、`on_group_member_remove` | 否 | |
  | 入群申请 | `on_group_join_request` | 否 | 机器人须是群管理员；事件上有 `approve()` / `decline()` |
  | 群打开、关闭主动消息 | `on_group_msg_receive`、`on_group_msg_reject` | 打开能 | |
  | 用户打开、关闭主动消息 | `on_c2c_msg_receive`、`on_c2c_msg_reject` | 打开能 | 实测不推，改推授权类互动，见第 6 节 |
  | 订阅消息授权变更 | `on_subscribe_message_status` | 否 | |
  | 互动 | `on_interaction` | 能 | 见第 6 节 |

- 类名与装饰器的规律：事件名去掉下划线是类名（`FRIEND_ADD` → `FriendAdd`），`on_` 加事件名的小写是装饰器。
  消息事件例外，见上。完整列表是 `Bot` 上的 `on_*` 方法。
- **订阅**：`Bot` 按已注册的处理函数推导 Intents，一般不用管。传 `Bot(..., intents=...)` 则以它为准；订阅了没有
  权限的类别，网关会关闭连接，`start()` 抛 `GatewayError`。
- SDK 不去重：平台可能重复推送同一条消息（`id` 相同），需要时自己按 `id` 去重。
- 时间：RFC3339 字符串解成带时区的 `datetime`（如 `message.timestamp`），Unix 秒保持 `int`（如 `FriendAdd.timestamp`）。

**细节去哪看**

- `pyqbot.Bot` 的各个 `on_*`（`src/pyqbot/_bot.py`）；`pyqbot.C2CMessage`、`pyqbot.GroupMessage`、
  `pyqbot.GroupAtMessage`（`src/pyqbot/_models/message.py`）；通知类事件（`src/pyqbot/_models/notice.py`）；
  `pyqbot.Intents`（`src/pyqbot/_gateway/intents.py`）。
- [`design.md`](design.md)「事件」（尤其「字段相同、事件名不同的消息」「单聊、群聊的通知类事件」）。
- [`errata.md`](errata.md)「群：「获取群内全部消息」时 @ 消息只推全量事件」「群：机器人入群与 @ 消息」
  「群：消息功能、通知事件与主动消息」「单聊主动消息开关：不推 `C2C_MSG_REJECT` / `C2C_MSG_RECEIVE`」。

## 3. 回复与主动发送

事件对象上的 `reply()` 是被动回复：`msg_id`（收到的消息）或 `event_id`（其它可回复的事件）与 `msg_seq` 都由 SDK
填写，同一个事件回复多次时 `msg_seq` 自动递增。不在处理函数里时，把事件传给 `send_message(..., reply_to=event)`
效果相同；`reply_to` 的类型限定了场景，把群消息传给单聊接口时 pyright 会报错。

```python
@bot.on_c2c_message
async def show(message: pyqbot.C2CMessage) -> None:
    await message.send_typing(seconds=10)  # 「正在输入」，只有单聊有

    keyboard = pyqbot.Keyboard.from_rows(
        [
            pyqbot.Button.callback("赞", "like", visited_label="已赞"),
            pyqbot.Button.callback("踩", "dislike", visited_label="已踩"),
        ],
        [pyqbot.Button.link("主页", "https://example.com")],
    )
    sent = await message.reply(markdown="**今日菜单**\n- 番茄炒蛋", keyboard=keyboard)
    await message.reply("引用上一条", quote=sent)

    card = pyqbot.Card(
        title="pyqbot",
        description="QQ 机器人 Python SDK",
        url="https://example.com",
        pic_url="https://example.com/cover.jpg",
    )
    await message.reply(card=card)
    await bot.users.recall_message(message.user_openid, sent)  # 发出 2 分钟内可以撤回
```

不传 `reply_to` 就是主动消息，有每日条数限制：

```python
await client.users.send_message(user_openid, "早上好")
await client.users.send_message(user_openid, "好久不见", wakeup=True)  # 互动召回消息
await client.groups.send_message(group_openid, "大家好")
```

- **内容**：`content` 文本；`markdown` 传字符串或 `pyqbot.Markdown`；`keyboard` 只能随 `markdown`；`media`（见第 4 节）；
  `card` 图文卡片。`markdown`、`media`、`card` 只能选一个，`markdown` 不能再带 `content`，`content` 可以随 `media`、
  `card` 一起发。组合不合法时在本地抛 `ValueError`，不发请求。`msg_type` 由 SDK 推断，不用传。
- **引用**：`quote` 接受发出的消息、收到的消息或 `REFIDX_` 开头的引用索引。收到的消息引用了别的消息时，
  被引用消息的索引是 `message.ref_msg_idx`（引用机器人的消息时等于发送结果的 `ext_info.ref_idx` 或流式消息的
  `stream.ref_idx`），内容在 `message.msg_elements`。
- 用户每发一条单聊消息，客户端都先显示一个跳动三个点的空气泡，等机器人的回复来替换；不回复的话它约 1 分钟后才消失。
- **按钮**：`Button.callback()` 回调（见第 6 节）、`Button.link()` 跳转、`Button.command()` 指令。`enter=True` 的指令按钮
  在群里只会填进输入框，不会直接发出。
- **主动消息的前提**：群里要有主动消息权限，实测 `get_bot_state()` 的 `allow_proactive_msg` 为假时被拒（`err_code` 40034105）。
- **被动回复的期限**：单聊实测收到消息 55 分钟后仍能回复（接口页写的 5 分钟不对）。
- Markdown 实际支持的语法比官方文档列的多（代码块、表格、LaTeX 等），HTML 标签不生效。
- Markdown 里的图片写 `![说明 #宽px #高px](地址)`，流式消息里也能用。宽高必须写，并按原图的比例：不写时只显示
  「[说明]」，写错会变形。平台抓不到图（地址打不开、境内访问不了的网站）时消息照发，客户端显示「图片加载失败」；
  普通消息可以用 `pyqbot.Markdown(content=..., force_verify_image_resource=True)` 让它直接失败（40034141）。
- 卡片的 `pic_url` 用 `.ico` 会转存失败，用 jpg 等常见格式。

**细节去哪看**

- `client.users.send_message`、`send_typing`、`recall_message`（`Users`，`src/pyqbot/_api/users.py`）；
  `client.groups.send_message`、`recall_message`（`Groups`，`src/pyqbot/_api/groups.py`）。
- `pyqbot.C2CMessage.reply`、`pyqbot.C2CMessage.send_typing`、`pyqbot.GroupMessage.reply`（`src/pyqbot/_models/message.py`）；
  `pyqbot.FriendAdd.reply` 等（`src/pyqbot/_models/notice.py`）。
- `pyqbot.Markdown`、`pyqbot.Keyboard`、`pyqbot.Button`、`pyqbot.Card`（`src/pyqbot/_models/send.py`）。
- [`design.md`](design.md)「请求层与接口分组」的「发消息」「被动回复」「其它消息操作」。
- [`errata.md`](errata.md)「引用、带文字的富媒体与卡片」「键盘：单聊发送成功，`enter` 在群里只填进输入框」
  「Markdown：实际支持的语法比文档多」「卡片：`pic_url` 用 .ico 时转存失败」「单聊被动回复的有效期：至少 55 分钟」
  「正在输入与被动回复的次数」「Markdown 图片：不写宽高不显示，抓不到时显示「图片加载失败」，接口不报错」。

## 4. 上传富媒体

先上传拿到 `pyqbot.Media`，再作为 `media=` 发出。事件上的 `upload()` 固定了上传目标：

```python
@bot.on_c2c_message
async def send_files(message: pyqbot.C2CMessage) -> None:
    photo = await message.upload(path="cat.png")  # 超过 3 MiB 时自动分片上传
    await message.reply("猫来了", media=photo)

    video = await message.upload(url="https://example.com/clip.mp4")  # 由平台下载
    await message.reply(media=video)

    report = await message.upload(
        data=b"%PDF-...", file_name="report.pdf", file_type=pyqbot.FileType.FILE
    )
    await message.reply(media=report)
```

- `path`、`url`、`data` 恰好传一个；`data` 要配 `file_name`。
- `file_type` 不传时按扩展名推断（图片 png、jpg、jpeg、gif、webp、bmp，视频 mp4，语音 silk、slk、mp3、wav、ogg），
  推不出时抛 `ValueError`；任意文件都可以传 `FileType.FILE`。
- 本地数据不超过 3 MiB 时随请求内联上传，更大的由 SDK 分片上传，并发与重试按平台下发的配置。
- 单聊与群聊上传的文件不互通：发到哪里就在哪里上传（`client.users.upload` / `client.groups.upload`）。
- `send=True` 上传后直接作为主动消息发出，占主动消息额度。
- 实测单聊与群聊里 gif、webp、bmp、jpg 图片，wav、mp3、ogg 语音，mp4 视频都能正常发送。

**细节去哪看**

- `client.users.upload`（`src/pyqbot/_api/users.py`）、`client.groups.upload`（`src/pyqbot/_api/groups.py`）；
  `pyqbot.C2CMessage.upload`、`pyqbot.GroupMessage.upload`（`src/pyqbot/_models/message.py`）；`pyqbot.Media`
  （`src/pyqbot/_models/send.py`）；`pyqbot.FileType`（`src/pyqbot/_models/upload.py`）。
- [`design.md`](design.md)「请求层与接口分组」的「富媒体上传」。
- [`errata.md`](errata.md)「富媒体：内联上传与分片」「富媒体：图片、语音、视频格式比文档列的多」
  「分片上传：序号从 1 开始，图片只有一片」。

## 5. 流式消息

用户看到的是同一条消息逐渐变长，适合大模型逐字输出。只有单聊支持，而且只能是被动回复：

```python
@bot.on_c2c_message
async def chat(message: pyqbot.C2CMessage) -> None:
    async with message.reply_stream() as stream:
        async for piece in llm(message.content):  # llm() 是你自己的生成器
            await stream.append(piece)
```

- 默认合并分片（`coalesce=True`）：每片都要等上一片的响应（实测约 0.4 秒一次往返），所以上一片在路上时，
  `append()` 只把内容攒起来就返回，等它回来再合成一片发出。发送失败在下一次 `append()` / `replace()` /
  `finish()`（含正常退出 `async with`）时抛出。
- `reply_stream(coalesce=False)`：每次调用发一片、等它发完，失败当场抛出；逐字发送时会明显变慢。
- `replace(full_text)` 用全文替换正文，必须以用户已经看到的内容开头；可以与 `append()` 混用。
- 正常退出 `async with` 时发出结束分片；体内抛异常时也会先发结束分片再原样抛出。不用 `async with` 时自己调用 `finish()`。
- 某一片发送失败后这条流就终止了，之后 `append()` 抛 `RuntimeError`。
- `stream.sent_text` 是平台已经确认收下的全文（用户看到的内容），某一片失败后停在失败之前；
  `stream.ref_idx` 是引用这条消息时要用的索引，平台还没给出时为 `None`。
- **超长会被拆成几条**：平台把超过约 15000 字节（Markdown 原文按 UTF-8 计，中文约 5000 字）的流式消息拆成几条气泡，
  硬切在两片之间，不看段落。切到代码块、表格、列表项中间时，后一条显示错乱（代码块还会连带之后的正文）。
  想在合适的位置分条，就在接近上限时在段落之间 `finish()`，再对同一条消息开一条新的流式消息；留些余量，实测有一次
  不到 14400 字节就拆了。拆出的每条有自己的引用索引，在 `stream.ref_idxs` 里（新的要晚 0～2 片才出现）。
- `reply_stream(markdown=False)` 按纯文本显示。没被拆开的流式消息只占用一个 `msg_seq`，拆成几条就占几个；
  之后再被动回复同一条消息时平台报 `msg_seq` 已被占用（40054005），SDK 会自动换下一个重发。
- 流式消息撤回不了（平台拒绝 `stream_msg_id` 和 `ref_idx`）；对同一条消息可以先后回复两条流式消息。
- **先结束，再开下一条**：给同一个用户开下一条流式消息、或回复他的另一条消息之前，先结束（`await`）当前这条。
  否则平台会提前结束它，之后的分片报 40034019（空的结束分片 SDK 当作正常结束，不抛出）。
  对同一条消息插一条普通回复不受影响。比如「过程消息 + 回答」：先 `await progress.finish()`，再开回答流。
- 不在处理函数里时用 `client.users.stream_message(user_openid, reply_to=message)`。

**细节去哪看**

- `pyqbot.StreamMessage`（`src/pyqbot/_api/stream.py`）；`pyqbot.C2CMessage.reply_stream`（`src/pyqbot/_models/message.py`）；
  `client.users.stream_message`（`src/pyqbot/_api/users.py`）。
- [`design.md`](design.md)「请求层与接口分组」的「流式消息」。
- [`errata.md`](errata.md)「流式消息：每片要等上一片的往返，逐片发送很慢」「流式消息：路径用 `user_openid`，空的结束分片可用」
  「流式消息：`content_type=text` 时按原文显示」「流式消息撤回不了」「流式消息：超过约 15000 字节被拆成几条气泡，多出的每条占一个 `msg_seq`」
  「流式消息：被下一条流式消息或另一条回复提前结束，之后的分片报 40034019」。

## 6. 互动：按钮回调

用户点击 `Button.callback()` 生成的按钮后，平台推送 `INTERACTION_CREATE`，由 `on_interaction` 接收。客户端只等约
1 秒（官方文档写 3 秒）：没在这之前回应，用户会看到「请求第三方失败」。所以 `Bot` 默认 `auto_ack=True`，
对回调按钮与快捷菜单先替你回应「成功」，与你的处理函数并发进行，处理函数慢慢做也不影响按钮状态：

```python
@bot.on_interaction
async def clicked(interaction: pyqbot.Interaction) -> None:
    if interaction.button_data == "like":
        await interaction.reply("谢谢支持")  # 单聊、群聊、频道自动分派
```

要对某些按钮回应别的结果（如没有权限），给 `auto_ack` 传一个判断函数：返回 `True` 的照常由 SDK 回应，
其余由处理函数自己尽快 `ack()`，耗时的事放在回应之后。传 `auto_ack=False` 则全部自己回应。

```python
ADMINS = {"MEMBER_OPENID"}
strict_bot = pyqbot.Bot("APP_ID", "APP_SECRET", auto_ack=lambda i: i.button_data != "admin")


@strict_bot.on_interaction
async def admin_only(interaction: pyqbot.Interaction) -> None:
    if interaction.button_data != "admin":
        return  # 已由 SDK 回应
    if interaction.group_member_openid not in ADMINS:
        await interaction.ack(code=pyqbot.InteractionResult.ADMIN_ONLY)
        return
    await interaction.ack()
    await interaction.reply("已执行")
```

- 回应晚了或重复回应，接口都不报错，只是用户那边的提示不对，所以本地看不出来。
- 回应用的 `interaction.id` 与被动回复用的 `event_id` 不是同一个值，两者都由 SDK 处理。
- `interaction.reply()` 按发生的场景选接口，返回 `SentMessage`（单聊、群聊）或 `GuildMessage`（频道）；
  要撤回它就把返回值交给 `interaction.recall()`，同样按场景选接口，不用先判断类型。
- 用户在资料卡切换主动消息开关时，推的是 `type` 为 `USER_AUTHORIZE` 的互动，开关状态看
  `interaction.data.resolved.authorize_data.switch`。
- SDK 自建的 HTTP 客户端把空闲连接保留 60 秒，免得回应时重新握手；自备 `http_client` 时建议同样调长 `keepalive_expiry`。

**细节去哪看**

- `pyqbot.Interaction`、`pyqbot.Interaction.ack`、`pyqbot.Interaction.reply`、`pyqbot.InteractionType`、
  `pyqbot.InteractionResult`（`src/pyqbot/_models/interaction.py`）；`client.interactions.ack`（`src/pyqbot/_api/interactions.py`）；
  `pyqbot.Bot` 的 `auto_ack` 与 `pyqbot.Bot.on_interaction`（`src/pyqbot/_bot.py`）。
- [`design.md`](design.md)「事件」的「`Interaction` 的两个 ID」「多场景事件的回复分派」。
- [`errata.md`](errata.md)「回应互动：客户端只等约 1 秒，接口从不报错」「互动事件：按钮与授权的类型、场景」
  「被动回复的 `event_id`：取外层 `id`」。

## 7. 群管理

```python
from datetime import timedelta


async def moderate() -> None:
    state = await client.groups.get_bot_state(group_openid)
    if state.member_role != pyqbot.GroupMemberRole.ADMIN:
        return
    await client.groups.mute_members(group_openid, member_openid, timedelta(minutes=10))
    await client.groups.unmute_members(group_openid, member_openid)


@bot.on_group_join_request
async def review(event: pyqbot.GroupJoinRequest) -> None:
    await event.approve()
```

前提条件 SDK 不在本地检查，由平台拒绝（抛 `APIError`，看 `err_code`）。实测：

| 能力 | 前提 | 方法 |
| --- | --- | --- |
| 群信息、机器人在群里的状态 | 普通成员即可 | `get`、`get_bot_state` |
| 禁言（查询、禁言、改期、解除） | 群管理员，否则 40011030 | `get_mute_settings`、`mute_members`、`update_member_mutes`、`unmute_members` |
| 入群申请 | 群管理员，否则 40011030 | `iter_join_requests`、`approve_join_request`、`decline_join_request`，事件 `on_group_join_request` |
| 撤回普通成员的消息 | 群管理员 | `recall_message`（传收到的 `GroupMessage`） |
| 成员列表与查询、黑名单 | 内邀能力，是不是管理员都报 40012010 | `iter_members`、`get_member`、`iter_blacklist`、`add_to_blacklist`、`remove_from_blacklist` |
| 移出成员 | 内邀能力；实测是管理员时报 40103011 | `remove_members` |

- 时间参数（如禁言的 `until`）接受带时区的 `datetime` 或从现在起算的 `timedelta`；没有时区的 `datetime` 抛 `ValueError`。
- 对已在禁言中的成员再 `mute_members()`，到期时间改为新的，等同 `update_member_mutes()`。
- 批量参数接受单个字符串或可迭代对象，单次最多 20 个（超出由平台拒绝）。只有部分成功时抛 `PartialFailureError`，
  失败的对象在 `failed_ids`，其余已经生效。
- 列表接口叫 `iter_*`，用 `async for` 遍历，翻页由 SDK 完成。
- 入群自动审批策略在 `client.join_strategies`（策略属于机器人，可关联多个群）。

**细节去哪看**

- `client.groups` 的各方法（`Groups`，`src/pyqbot/_api/groups.py`），前提条件写在每个方法的 docstring 里；
  `client.join_strategies`（`JoinStrategies`，`src/pyqbot/_api/join_strategies.py`）；
  `pyqbot.GroupJoinRequest.approve`、`decline`（`src/pyqbot/_models/notice.py`）；`pyqbot.GroupBotState` 等（`src/pyqbot/_models/group.py`）。
- [`design.md`](design.md)「请求层与接口分组」的「群管理」「入群自动审批策略」「时间与批量参数」「分页接口」。
- [`errata.md`](errata.md)「群管理：权限不足时的错误码，机器人状态的真实响应」「禁言：再次 `add` 等于 `update`，空串的 `del` 立即解除」
  「入群申请 `GROUP_JOIN_REQUEST`：字段与审批」「撤回：管理员能撤回普通成员的消息」。

## 8. 菜单、面板与素材库

三者都属于机器人本身，改动立即影响所有用户：

```python
async def configure() -> None:
    # 单聊窗口底部的自定义菜单，整体覆盖；set([]) 清空
    await client.menu.set(
        [
            pyqbot.MenuItem.message_button("帮助", "/help"),
            pyqbot.MenuItem.submenu(
                "更多", pyqbot.SubMenuItem.link_button("官网", "https://example.com")
            ),
        ]
    )

    # 输入 / 时弹出的指令面板；传了 user_openids 就只对这些用户生效
    items = [pyqbot.PanelItem.command_button("/天气", desc="查询当前天气")]
    panel_id = await client.panels.create(pyqbot.PanelScope.C2C, items, user_openids=user_openid)
    await client.panels.set(panel_id, items, remark="天气")  # 不传 remark 会清空备注

    # 素材库：Markdown 里引用的图片，单聊、群聊通用
    image = await client.images.upload(path="chart.png")
    await client.users.send_message(user_openid, markdown=f"![走势 #800px #400px]({image.url})")
```

- 菜单：`get()` 取当前菜单，`set()` 整体覆盖。
- 面板：`create()` 不传关联对象即对整个场景生效；`set()` 覆盖内容与备注，关联对象用 `add_targets()` / `remove_targets()` 增删。
  客户端里要删掉 `/` 重新输入才会刷新。
- 素材库：格式由扩展名决定（png、jpg、jpeg、gif、webp）；`iter_images()` 列出、`delete()` 释放额度；
  连续 90 天没被引用就失效。`preview_url` 带签名，`repr()` 里显示为 `***`。
  引用它的消息（含流式消息）发完之后就可以 `delete()`，已发的消息不受影响，所以临时的图不必一直占着 100 张的额度；
  引用已经删掉的素材时流式消息不报错，客户端显示「图片加载失败」。

**细节去哪看**

- `client.menu`（`CustomMenu`，`src/pyqbot/_api/menu.py`）与 `pyqbot.MenuItem`、`pyqbot.SubMenuItem`（`src/pyqbot/_models/menu.py`）。
- `client.panels`（`Panels`，`src/pyqbot/_api/panels.py`）与 `pyqbot.PanelItem`、`pyqbot.PanelScope`（`src/pyqbot/_models/panel.py`）。
- `client.images`（`Images`，`src/pyqbot/_api/images.py`）与 `pyqbot.MediaImage`（`src/pyqbot/_models/upload.py`）。
- [`design.md`](design.md)「请求层与接口分组」的「机器人自身」「菜单与面板的模型」「素材库」。
- [`errata.md`](errata.md)「自定义菜单：`set([])` 能清空」「自定义菜单：没有设置过时 `menu` 是空对象」
  「指令面板：版本号在顶层递增，不传 `remark` 会清空备注」「素材库：列表的时间是数字字符串，有效期 90 天」「素材库：`.jpg` 被接受」
  「素材库：流式消息里可以引用，发出后删掉素材不影响已发的消息」。

## 9. 频道（已实现，未实测）

> **注意**：频道相关的接口与事件按官方文档实现，有本地测试，但**一个都没有对真实平台验证过**
> （测试条件见 [`errata.md`](errata.md)「频道：测试条件」）。官方文档在频道部分的出入很多，用之前先看 errata 的相关条目，
> 遇到与文档不符的行为欢迎反馈。

```python
@bot.on_channel_at_message
async def channel_ping(message: pyqbot.ChannelAtMessage) -> None:
    try:
        await message.reply("pong", image_path="pong.png")
    except pyqbot.AuditPendingError as error:
        print("等待人工审核：", error.audit_id)


@bot.on_message_audit_pass
async def audited(event: pyqbot.MessageAuditPass) -> None:
    print(event.audit_id, event.message_id)
```

- 分组：`client.guilds`（频道级：子频道列表、成员、身份组、禁言、公告等）、`client.channels`（子频道：管理、消息、
  表态、精华、日程、论坛、音频）、`client.dms`（频道私信；其中的 `guild_id` 是私信会话的 ID）。
- 消息内容与单聊、群聊不同：有 `embed`、`ark`、图片（`image` / `image_path` / `image_data`），没有 `media`、`card`；
  被动回复不带 `msg_seq`。
- 消息可能要人工审核：这时抛 `AuditPendingError`，结果由 `on_message_audit_pass` / `on_message_audit_reject` 推送，用 `audit_id` 对应。
- 标明「私域」的接口与事件只有私域机器人可用，标明「管理员」的要求机器人在该频道是管理员，都写在 docstring 里。
- 公域论坛（`OPEN_FORUM_*`）与音视频子频道进出（`AUDIO_OR_LIVE_CHANNEL_MEMBER_*`）没有 Intent 位，要在构造 `Bot` 时传完整的 `intents`。

**细节去哪看**

- `client.guilds`（`src/pyqbot/_api/guilds.py`）、`client.channels`（`src/pyqbot/_api/channels.py`）、`client.dms`（`src/pyqbot/_api/dms.py`）；
  模型与事件在 `src/pyqbot/_models/guild.py`、`guild_message.py`、`guild_content.py`、`guild_manage.py`、`forum.py`、`audio.py`。
- [`design.md`](design.md)「请求层与接口分组」的「频道管理」、「频道消息与内容」、「事件」的「频道的事件」。
- [`errata.md`](errata.md)「待实测」里与频道、子频道、论坛、表态、日程等相关的条目（都还没有实测）。

## 10. 错误处理

平台与网络的失败只抛 `QQBotError` 的子类，不用返回值表达错误：

```text
QQBotError          message、err_code、trace_id（后两者可能为 None）、outcome_unknown
├── APIError        平台返回了失败，另带 status_code
│   ├── PartialFailureError  批量操作部分失败（其余已生效），另带 failed_ids
│   └── AuditPendingError    已受理、等待人工审核（频道），另带 audit_id
├── NetworkError    没拿到响应：连接失败、超时
└── GatewayError    网关被关闭且无法恢复，err_code 是关闭码（有的话）
```

```python
async def notify() -> None:
    try:
        await client.users.send_message(user_openid, "提醒")
    except pyqbot.APIError as error:
        # 按 err_code 判断原因；找平台排查时提供 trace_id
        print(error.status_code, error.err_code, error.trace_id)
    except pyqbot.NetworkError as error:
        print("没拿到响应：", error)
```

- 用法错误在发请求之前抛内置异常：参数不合法 `ValueError`；关闭后再用、`start()` 调用两次、事件不是 `Bot`
  分发来的却调用 `reply()` 等 `RuntimeError`；读不了本地文件 `OSError`；处理函数不是 `async def` 时注册抛 `TypeError`。
- `str(error)` 已带上 `err_code` 与 `trace_id`。响应里同时有 `code` 与 `err_code` 时取 `err_code`（现行的错误码）。
- `error.outcome_unknown` 为假时可以确定请求没有生效（连不上、平台带错误码或以 4xx 拒绝），可以放心改发别的内容或重试。
  为真时请求可能已经（部分）生效（如消息其实发出去了）：请求发出后超时或断开、HTTP 5xx、2xx 或 3xx 却确认不了成功，
  以及 `PartialFailureError`（其余已生效）、`AuditPendingError`（审核通过后会发出）。
- SDK 不自动重试普通请求（分片上传的分片除外），也不做限频退避。网关断线会自动重连，只有无法恢复时 `start()` 才抛 `GatewayError`。
- 处理函数里没接住的异常只记 ERROR 日志，机器人继续运行；要给用户反馈就自己 `try`。
- AppSecret 与 access_token 不会出现在异常文案、异常链、日志和 `repr`（如 `client.config`）里，可以放心记录和上报。
  openid 不是凭证，会出现在文案里（如请求路径）。

**细节去哪看**

- `pyqbot.QQBotError` 及各子类（`src/pyqbot/_errors.py`）；每个方法会抛哪些异常写在它 docstring 的 `Raises` 里。
- [`design.md`](design.md)「共用地基」的「异常」、「请求层与接口分组」的「失败映射」、「后续模块要遵守的约定」第 3 条（异常）与第 7 条（凭证不落日志）。
- [`errata.md`](errata.md)「token 过期后的响应：`code` 与 `err_code` 同时出现且不相同」「获取 token：密钥错误时用 `code`，HTTP 状态码是 200」。

## 11. 日志

SDK 用标准库 `logging`，logger 名是 `"pyqbot"`，不自己配置 handler：

```python
import logging

logging.basicConfig(level=logging.WARNING)
logging.getLogger("pyqbot").setLevel(logging.INFO)
```

- INFO：发送 Identify / Resume、网关连接就绪。
- WARNING：网关断开与重连、丢弃无法解码的事件、流式消息没有正常结束、关闭时处理函数没能按时结束。
- ERROR：处理函数抛出的异常（带 traceback）。
- 日志内容都先脱敏。SDK 不改动 httpx2 的 logger；自己打开 httpx2 的 INFO 日志时，里面会有分片上传的预签名地址（短期有效）。

**细节去哪看**

- [`design.md`](design.md)「网关连接」的「日志」、「事件」的「日志不带凭证」、「请求层与接口分组」的「对象存储的 PUT」。

## 12. 找细节

| 想知道 | 去哪看 |
| --- | --- |
| 某个类或方法的参数、默认值、会抛哪些异常、要什么权限、对应哪个官方接口 | docstring：IDE 悬停、`help(pyqbot.Xxx)`，或 `src/pyqbot/` 下的源码（各节「细节去哪看」写了位置） |
| SDK 为什么这样设计、内部怎么处理（token、重连、`msg_seq`、分片、合并分片、自动回应）、各模块共同的约定 | [`docs/design.md`](design.md) |
| 平台实际怎么表现、和官方文档哪里不一样、哪些已实测、哪些还待实测 | [`docs/errata.md`](errata.md)：「已确认」可当事实，「待实测」只是当前的取舍 |
| 对真实平台跑过哪些用例、每个用例看什么、怎么自己跑 | [`tests/live/README.md`](../tests/live/README.md) |
| 官方接口与事件的原始定义：字段表、错误码、限频 | [`docs/upstream/qqbot-api-v2/`](upstream/qqbot-api-v2/README.md)，总索引是 `autogen/index.md`；快照是生成物，与平台不符时以 errata 为准 |
