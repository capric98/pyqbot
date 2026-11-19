# pyqbot

一个人类能使用的 QQ 机器人 Python SDK：对接 QQ 机器人 API v2，只有 async 接口，类型完整。

> 0.1.0，尚未发布，接口仍可能变动。频道相关的接口已实现，但还没有实测。

## 特点

- **协议细节由 SDK 处理**：access_token 的获取与刷新，网关的心跳、断线重连与会话恢复，被动回复要带的
  `msg_id` / `event_id` 与 `msg_seq`，大文件的分片上传（并发与重试）。
- **带类型的模型**：事件和响应都是不可变的模型，取值用枚举；把群消息当作单聊的回复对象传进去时，
  pyright 就会报错。平台多给字段、推来未知事件或未知枚举值都不会崩溃。
- **统一的异常**：失败一律抛 `QQBotError` 的子类，带 `err_code` 与 `trace_id`；异常、日志和 `repr`
  里都不会出现 AppSecret 与 access_token。
- **按实测而不是按文档**：官方文档与平台实际行为对不上的地方逐条实测过。例如回调按钮客户端只等约 1 秒，
  所以 `Bot` 默认先替你回应互动；流式消息逐片发送很慢，所以默认把攒下的内容合并成一片发出。
- **依赖少**：运行时只依赖 httpx2（含 WebSocket 与 SOCKS 代理支持）与 msgspec。

## 安装

需要 Python 3.14 及以上。还没有发布到 PyPI，从 GitHub 安装：

```sh
uv add git+https://github.com/capric98/pyqbot
```

## 最小的机器人

```python
import os

import pyqbot

bot = pyqbot.Bot(os.environ["APP_ID"], os.environ["APP_SECRET"])


@bot.on_c2c_message
async def echo(message: pyqbot.C2CMessage) -> None:
    if message.content:  # 纯图片等消息的 content 是空串
        await message.reply(message.content)


@bot.on_group_at_message
async def ping(message: pyqbot.GroupAtMessage) -> None:
    if message.content.strip() == "/ping":
        await message.reply("pong")


bot.run()  # 连接网关并一直运行，Ctrl+C 退出
```

要订阅哪些事件由注册的处理函数推导，不用自己算 Intents。

## 不跑机器人、只调接口

`Client` 可以单独使用（`Bot` 继承它，接口完全相同）：

```python
import asyncio
import os

import pyqbot


async def main() -> None:
    async with pyqbot.Client(os.environ["APP_ID"], os.environ["APP_SECRET"]) as client:
        me = await client.get_me()
        print(f"我是 {me.username}")
        # 不是回复，所以是主动消息，受每日条数限制
        await client.users.send_message(os.environ["USER_OPENID"], "早上好")


asyncio.run(main())
```

## 文档

- [使用指南](docs/guide.md)：按主题讲怎么用，每个主题都指向更细的出处。
- 公共类与方法的 docstring：参数、异常、前提条件，以及对应的官方接口。
- [设计与约定](docs/design.md)：SDK 为什么这样设计、各模块共同遵守的约定。
- [官方文档出入](docs/errata.md)：官方文档缺失或自相矛盾之处，以及实测得出的平台真实行为。
- [实测清单](tests/live/README.md)：对真实接口跑过哪些用例、怎么跑。
- [官方文档快照](docs/upstream/qqbot-api-v2/README.md)：QQ 机器人 API v2 的官方文档，接口与事件的原始定义。
