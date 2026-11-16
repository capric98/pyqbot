"""事件驱动的机器人。"""

import asyncio
import contextlib

import httpx2

from ._client import Client
from ._config import DEFAULT_BASE_URL, DEFAULT_TIMEOUT
from ._events.dispatcher import Dispatcher, Handler
from ._gateway.connection import GatewayConnection
from ._gateway.intents import Intents
from ._models.audio import (
    AudioFinish,
    AudioOffMic,
    AudioOnMic,
    AudioOrLiveChannelMemberEnter,
    AudioOrLiveChannelMemberExit,
    AudioStart,
)
from ._models.forum import (
    ForumPostCreate,
    ForumPostDelete,
    ForumPublishAuditResult,
    ForumReplyCreate,
    ForumReplyDelete,
    ForumThreadCreate,
    ForumThreadDelete,
    ForumThreadUpdate,
    OpenForumPostCreate,
    OpenForumPostDelete,
    OpenForumReplyCreate,
    OpenForumReplyDelete,
    OpenForumThreadCreate,
    OpenForumThreadDelete,
    OpenForumThreadUpdate,
)
from ._models.guild import (
    ChannelCreate,
    ChannelDelete,
    ChannelUpdate,
    GuildCreate,
    GuildDelete,
    GuildMemberAdd,
    GuildMemberRemove,
    GuildMemberUpdate,
    GuildUpdate,
)
from ._models.guild_message import (
    ChannelAtMessage,
    ChannelMessage,
    DirectMessage,
    DirectMessageDelete,
    MessageAuditPass,
    MessageAuditReject,
    MessageDelete,
    MessageReactionAdd,
    MessageReactionRemove,
    PublicMessageDelete,
)
from ._models.interaction import Interaction
from ._models.message import C2CMessage, GroupAtMessage, GroupMessage
from ._models.notice import (
    C2CMsgReceive,
    C2CMsgReject,
    FriendAdd,
    FriendDel,
    GroupAddRobot,
    GroupDelRobot,
    GroupJoinRequest,
    GroupMemberAdd,
    GroupMemberRemove,
    GroupMsgReceive,
    GroupMsgReject,
    SubscribeMessageStatus,
)


class Bot(Client):
    """事件驱动的机器人：用装饰器注册事件处理函数，再用 `run()` 或 `start()` 连接网关。

    构造参数、生命周期与接口都同 `Client`，只多一个 `intents`。

    Args:
        intents: 要订阅的事件类别。默认按已注册的处理函数推导，一般不用传；传入则以它为准。

    Example:
        ```python
        bot = pyqbot.Bot("APP_ID", "APP_SECRET")


        @bot.on_c2c_message
        async def echo(message: pyqbot.C2CMessage) -> None:
            await message.reply(message.content)


        bot.run()
        ```
    """

    def __init__(
        self,
        app_id: str | int,
        app_secret: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx2.AsyncClient | None = None,
        intents: Intents | None = None,
    ) -> None:
        super().__init__(
            app_id, app_secret, base_url=base_url, timeout=timeout, http_client=http_client
        )
        self._intents = intents
        self._dispatcher = Dispatcher(redact=self._redact_secrets)
        self._connection: GatewayConnection | None = None

    def on_c2c_message[F: Handler[C2CMessage]](self, handler: F) -> F:
        """注册单聊消息（`C2C_MESSAGE_CREATE`）的处理函数，原样返回它。

        处理函数必须是 `async def`，只收一个 `C2CMessage`；同一事件可以注册多个。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(C2CMessage, handler)
        return handler

    def on_group_at_message[F: Handler[GroupAtMessage]](self, handler: F) -> F:
        """注册群里 @机器人 的消息（`GROUP_AT_MESSAGE_CREATE`）的处理函数，原样返回它。

        处理函数必须是 `async def`，只收一个 `GroupAtMessage`；同一事件可以注册多个。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GroupAtMessage, handler)
        return handler

    def on_group_message[F: Handler[GroupMessage]](self, handler: F) -> F:
        """注册群里的全部消息（`GROUP_MESSAGE_CREATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        机器人须开启「接收所有消息」。只收 @机器人 的消息用 `on_group_at_message`，两者互不转发。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GroupMessage, handler)
        return handler

    def on_friend_add[F: Handler[FriendAdd]](self, handler: F) -> F:
        """注册用户添加机器人为好友（`FRIEND_ADD`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(FriendAdd, handler)
        return handler

    def on_friend_del[F: Handler[FriendDel]](self, handler: F) -> F:
        """注册用户删除机器人好友（`FRIEND_DEL`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(FriendDel, handler)
        return handler

    def on_c2c_msg_reject[F: Handler[C2CMsgReject]](self, handler: F) -> F:
        """注册用户关闭主动消息（`C2C_MSG_REJECT`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        2026-11-16 实测切换资料卡的主动消息开关时，平台没有推送这个事件，而是推送
        `type` 为 `USER_AUTHORIZE`、`authorize_data.scope` 为 `C2C_PUSH` 的 `Interaction`，开关状态看
        `authorize_data.switch`（`docs/errata.md`）。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(C2CMsgReject, handler)
        return handler

    def on_c2c_msg_receive[F: Handler[C2CMsgReceive]](self, handler: F) -> F:
        """注册用户打开主动消息（`C2C_MSG_RECEIVE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        2026-11-16 实测切换资料卡的主动消息开关时，平台没有推送这个事件，而是推送
        `type` 为 `USER_AUTHORIZE`、`authorize_data.scope` 为 `C2C_PUSH` 的 `Interaction`，开关状态看
        `authorize_data.switch`（`docs/errata.md`）。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(C2CMsgReceive, handler)
        return handler

    def on_group_add_robot[F: Handler[GroupAddRobot]](self, handler: F) -> F:
        """注册机器人被拉进群（`GROUP_ADD_ROBOT`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GroupAddRobot, handler)
        return handler

    def on_group_del_robot[F: Handler[GroupDelRobot]](self, handler: F) -> F:
        """注册机器人被移出群（`GROUP_DEL_ROBOT`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GroupDelRobot, handler)
        return handler

    def on_group_msg_reject[F: Handler[GroupMsgReject]](self, handler: F) -> F:
        """注册群关闭主动消息（`GROUP_MSG_REJECT`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GroupMsgReject, handler)
        return handler

    def on_group_msg_receive[F: Handler[GroupMsgReceive]](self, handler: F) -> F:
        """注册群打开主动消息（`GROUP_MSG_RECEIVE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GroupMsgReceive, handler)
        return handler

    def on_group_member_add[F: Handler[GroupMemberAdd]](self, handler: F) -> F:
        """注册群成员加入（`GROUP_MEMBER_ADD`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GroupMemberAdd, handler)
        return handler

    def on_group_member_remove[F: Handler[GroupMemberRemove]](self, handler: F) -> F:
        """注册群成员离开（`GROUP_MEMBER_REMOVE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GroupMemberRemove, handler)
        return handler

    def on_group_join_request[F: Handler[GroupJoinRequest]](self, handler: F) -> F:
        """注册入群申请（`GROUP_JOIN_REQUEST`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        只有机器人是群管理员时才会收到。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GroupJoinRequest, handler)
        return handler

    def on_subscribe_message_status[F: Handler[SubscribeMessageStatus]](self, handler: F) -> F:
        """注册订阅消息授权状态变更（`SUBSCRIBE_MESSAGE_STATUS`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(SubscribeMessageStatus, handler)
        return handler

    def on_interaction[F: Handler[Interaction]](self, handler: F) -> F:
        """注册互动事件（`INTERACTION_CREATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        回调按钮与快捷菜单要在收到后约 1 秒内 `ack()`（实测，见 `Interaction`）。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(Interaction, handler)
        return handler

    def on_guild_create[F: Handler[GuildCreate]](self, handler: F) -> F:
        """注册机器人加入频道（`GUILD_CREATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GuildCreate, handler)
        return handler

    def on_guild_update[F: Handler[GuildUpdate]](self, handler: F) -> F:
        """注册频道资料变更（`GUILD_UPDATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GuildUpdate, handler)
        return handler

    def on_guild_delete[F: Handler[GuildDelete]](self, handler: F) -> F:
        """注册频道解散或机器人被移出（`GUILD_DELETE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GuildDelete, handler)
        return handler

    def on_channel_create[F: Handler[ChannelCreate]](self, handler: F) -> F:
        """注册子频道创建（`CHANNEL_CREATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(ChannelCreate, handler)
        return handler

    def on_channel_update[F: Handler[ChannelUpdate]](self, handler: F) -> F:
        """注册子频道更新（`CHANNEL_UPDATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(ChannelUpdate, handler)
        return handler

    def on_channel_delete[F: Handler[ChannelDelete]](self, handler: F) -> F:
        """注册子频道删除（`CHANNEL_DELETE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(ChannelDelete, handler)
        return handler

    def on_guild_member_add[F: Handler[GuildMemberAdd]](self, handler: F) -> F:
        """注册用户加入频道（`GUILD_MEMBER_ADD`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GuildMemberAdd, handler)
        return handler

    def on_guild_member_update[F: Handler[GuildMemberUpdate]](self, handler: F) -> F:
        """注册频道成员资料变更（`GUILD_MEMBER_UPDATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GuildMemberUpdate, handler)
        return handler

    def on_guild_member_remove[F: Handler[GuildMemberRemove]](self, handler: F) -> F:
        """注册用户离开频道（`GUILD_MEMBER_REMOVE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(GuildMemberRemove, handler)
        return handler

    def on_channel_at_message[F: Handler[ChannelAtMessage]](self, handler: F) -> F:
        """注册子频道里 @机器人 的消息（`AT_MESSAGE_CREATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(ChannelAtMessage, handler)
        return handler

    def on_channel_message[F: Handler[ChannelMessage]](self, handler: F) -> F:
        """注册子频道里的全部消息（`MESSAGE_CREATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        仅私域机器人可用。只收 @机器人 的消息用 `on_channel_at_message`，两者互不转发。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(ChannelMessage, handler)
        return handler

    def on_direct_message[F: Handler[DirectMessage]](self, handler: F) -> F:
        """注册频道私信（`DIRECT_MESSAGE_CREATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(DirectMessage, handler)
        return handler

    def on_message_delete[F: Handler[MessageDelete]](self, handler: F) -> F:
        """注册子频道消息被删除（`MESSAGE_DELETE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        仅私域机器人可用；公域机器人用 `on_public_message_delete`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(MessageDelete, handler)
        return handler

    def on_public_message_delete[F: Handler[PublicMessageDelete]](self, handler: F) -> F:
        """注册子频道消息被删除（公域）（`PUBLIC_MESSAGE_DELETE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(PublicMessageDelete, handler)
        return handler

    def on_direct_message_delete[F: Handler[DirectMessageDelete]](self, handler: F) -> F:
        """注册频道私信被删除（`DIRECT_MESSAGE_DELETE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(DirectMessageDelete, handler)
        return handler

    def on_message_reaction_add[F: Handler[MessageReactionAdd]](self, handler: F) -> F:
        """注册添加表情表态（`MESSAGE_REACTION_ADD`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(MessageReactionAdd, handler)
        return handler

    def on_message_reaction_remove[F: Handler[MessageReactionRemove]](self, handler: F) -> F:
        """注册取消表情表态（`MESSAGE_REACTION_REMOVE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(MessageReactionRemove, handler)
        return handler

    def on_message_audit_pass[F: Handler[MessageAuditPass]](self, handler: F) -> F:
        """注册消息审核通过（`MESSAGE_AUDIT_PASS`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(MessageAuditPass, handler)
        return handler

    def on_message_audit_reject[F: Handler[MessageAuditReject]](self, handler: F) -> F:
        """注册消息审核不通过（`MESSAGE_AUDIT_REJECT`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(MessageAuditReject, handler)
        return handler

    def on_forum_thread_create[F: Handler[ForumThreadCreate]](self, handler: F) -> F:
        """注册论坛发表主帖（`FORUM_THREAD_CREATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        仅私域机器人可用。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(ForumThreadCreate, handler)
        return handler

    def on_forum_thread_update[F: Handler[ForumThreadUpdate]](self, handler: F) -> F:
        """注册论坛更新主帖（`FORUM_THREAD_UPDATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        仅私域机器人可用。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(ForumThreadUpdate, handler)
        return handler

    def on_forum_thread_delete[F: Handler[ForumThreadDelete]](self, handler: F) -> F:
        """注册论坛删除主帖（`FORUM_THREAD_DELETE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        仅私域机器人可用。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(ForumThreadDelete, handler)
        return handler

    def on_forum_post_create[F: Handler[ForumPostCreate]](self, handler: F) -> F:
        """注册论坛发表评论（`FORUM_POST_CREATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        仅私域机器人可用。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(ForumPostCreate, handler)
        return handler

    def on_forum_post_delete[F: Handler[ForumPostDelete]](self, handler: F) -> F:
        """注册论坛删除评论（`FORUM_POST_DELETE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        仅私域机器人可用。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(ForumPostDelete, handler)
        return handler

    def on_forum_reply_create[F: Handler[ForumReplyCreate]](self, handler: F) -> F:
        """注册论坛发表回复（`FORUM_REPLY_CREATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        仅私域机器人可用。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(ForumReplyCreate, handler)
        return handler

    def on_forum_reply_delete[F: Handler[ForumReplyDelete]](self, handler: F) -> F:
        """注册论坛删除回复（`FORUM_REPLY_DELETE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        仅私域机器人可用。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(ForumReplyDelete, handler)
        return handler

    def on_forum_publish_audit_result[F: Handler[ForumPublishAuditResult]](self, handler: F) -> F:
        """注册论坛发表的审核结果（`FORUM_PUBLISH_AUDIT_RESULT`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        仅私域机器人可用。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(ForumPublishAuditResult, handler)
        return handler

    def on_open_forum_thread_create[F: Handler[OpenForumThreadCreate]](self, handler: F) -> F:
        """注册公域论坛发表主帖（`OPEN_FORUM_THREAD_CREATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        文档没有给出它的 Intent 位，SDK 不替你订阅：要收到它，须在构造 `Bot` 时传入完整的 `intents`
        （传入后不再按处理函数推导）。只注册了这类处理函数又没传时，`start()` 抛 `RuntimeError`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(OpenForumThreadCreate, handler)
        return handler

    def on_open_forum_thread_update[F: Handler[OpenForumThreadUpdate]](self, handler: F) -> F:
        """注册公域论坛更新主帖（`OPEN_FORUM_THREAD_UPDATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        文档没有给出它的 Intent 位，SDK 不替你订阅：要收到它，须在构造 `Bot` 时传入完整的 `intents`
        （传入后不再按处理函数推导）。只注册了这类处理函数又没传时，`start()` 抛 `RuntimeError`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(OpenForumThreadUpdate, handler)
        return handler

    def on_open_forum_thread_delete[F: Handler[OpenForumThreadDelete]](self, handler: F) -> F:
        """注册公域论坛删除主帖（`OPEN_FORUM_THREAD_DELETE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        文档没有给出它的 Intent 位，SDK 不替你订阅：要收到它，须在构造 `Bot` 时传入完整的 `intents`
        （传入后不再按处理函数推导）。只注册了这类处理函数又没传时，`start()` 抛 `RuntimeError`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(OpenForumThreadDelete, handler)
        return handler

    def on_open_forum_post_create[F: Handler[OpenForumPostCreate]](self, handler: F) -> F:
        """注册公域论坛发表评论（`OPEN_FORUM_POST_CREATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        文档没有给出它的 Intent 位，SDK 不替你订阅：要收到它，须在构造 `Bot` 时传入完整的 `intents`
        （传入后不再按处理函数推导）。只注册了这类处理函数又没传时，`start()` 抛 `RuntimeError`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(OpenForumPostCreate, handler)
        return handler

    def on_open_forum_post_delete[F: Handler[OpenForumPostDelete]](self, handler: F) -> F:
        """注册公域论坛删除评论（`OPEN_FORUM_POST_DELETE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        文档没有给出它的 Intent 位，SDK 不替你订阅：要收到它，须在构造 `Bot` 时传入完整的 `intents`
        （传入后不再按处理函数推导）。只注册了这类处理函数又没传时，`start()` 抛 `RuntimeError`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(OpenForumPostDelete, handler)
        return handler

    def on_open_forum_reply_create[F: Handler[OpenForumReplyCreate]](self, handler: F) -> F:
        """注册公域论坛发表回复（`OPEN_FORUM_REPLY_CREATE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        文档没有给出它的 Intent 位，SDK 不替你订阅：要收到它，须在构造 `Bot` 时传入完整的 `intents`
        （传入后不再按处理函数推导）。只注册了这类处理函数又没传时，`start()` 抛 `RuntimeError`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(OpenForumReplyCreate, handler)
        return handler

    def on_open_forum_reply_delete[F: Handler[OpenForumReplyDelete]](self, handler: F) -> F:
        """注册公域论坛删除回复（`OPEN_FORUM_REPLY_DELETE`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        文档没有给出它的 Intent 位，SDK 不替你订阅：要收到它，须在构造 `Bot` 时传入完整的 `intents`
        （传入后不再按处理函数推导）。只注册了这类处理函数又没传时，`start()` 抛 `RuntimeError`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(OpenForumReplyDelete, handler)
        return handler

    def on_audio_start[F: Handler[AudioStart]](self, handler: F) -> F:
        """注册音频开始播放（`AUDIO_START`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(AudioStart, handler)
        return handler

    def on_audio_finish[F: Handler[AudioFinish]](self, handler: F) -> F:
        """注册音频播放结束（`AUDIO_FINISH`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(AudioFinish, handler)
        return handler

    def on_audio_on_mic[F: Handler[AudioOnMic]](self, handler: F) -> F:
        """注册上麦（`AUDIO_ON_MIC`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(AudioOnMic, handler)
        return handler

    def on_audio_off_mic[F: Handler[AudioOffMic]](self, handler: F) -> F:
        """注册下麦（`AUDIO_OFF_MIC`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(AudioOffMic, handler)
        return handler

    def on_audio_or_live_channel_member_enter[F: Handler[AudioOrLiveChannelMemberEnter]](
        self, handler: F
    ) -> F:
        """注册用户进入音视频或直播子频道（`AUDIO_OR_LIVE_CHANNEL_MEMBER_ENTER`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        文档没有给出它的 Intent 位，SDK 不替你订阅：要收到它，须在构造 `Bot` 时传入完整的 `intents`
        （传入后不再按处理函数推导）。只注册了这类处理函数又没传时，`start()` 抛 `RuntimeError`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(AudioOrLiveChannelMemberEnter, handler)
        return handler

    def on_audio_or_live_channel_member_exit[F: Handler[AudioOrLiveChannelMemberExit]](
        self, handler: F
    ) -> F:
        """注册用户离开音视频或直播子频道（`AUDIO_OR_LIVE_CHANNEL_MEMBER_EXIT`）的处理函数，原样返回它；要求同 `on_c2c_message`。

        文档没有给出它的 Intent 位，SDK 不替你订阅：要收到它，须在构造 `Bot` 时传入完整的 `intents`
        （传入后不再按处理函数推导）。只注册了这类处理函数又没传时，`start()` 抛 `RuntimeError`。

        Raises:
            TypeError: 处理函数不是 `async def` 定义的。
        """
        self._dispatcher.add_handler(AudioOrLiveChannelMemberExit, handler)
        return handler

    def _resolve_intents(self) -> Intents:
        """连接网关时要订阅的 Intents：构造时传入的，或按已注册的处理函数推导。"""
        return self._dispatcher.intents if self._intents is None else self._intents

    async def start(self) -> None:
        """连接网关，把事件分发给已注册的处理函数，直到 `close()` 被调用才返回。

        断线会自动重连并恢复会话。处理函数要在调用之前注册好；只能调用一次。

        Raises:
            GatewayError: 网关连接无法恢复，例如机器人被封禁，或没有所订阅事件的权限。
            APIError: 平台拒绝签发 access_token 或网关地址，例如 AppID、AppSecret 不正确。
            RuntimeError: 没有注册任何处理函数、重复调用，或已关闭。

        Example:
            ```python
            async with bot:
                await bot.start()
            ```
        """
        if self.is_closed:
            raise RuntimeError("Bot 已关闭，不能再启动，请新建一个 Bot")
        if self._connection is not None:
            raise RuntimeError("Bot.start() 只能调用一次")
        intents = self._resolve_intents()
        if not intents:
            raise RuntimeError(
                "没有要订阅的事件：先用 @bot.on_... 注册处理函数，或在构造时传入 intents"
            )
        self._connection = connection = GatewayConnection(
            http_client=self.http_client,
            get_url=self._get_gateway_url,
            get_token=self.get_access_token,
            intents=intents,
            on_dispatch=lambda payload: self._dispatcher.dispatch(payload, self),
            connect_timeout=self.config.timeout,
        )
        await connection.run()

    def run(self) -> None:
        """同步入口：连接网关并一直运行，按 Ctrl+C 退出。

        在脚本的最后调用，等价于 `asyncio.run` 里 `async with bot: await bot.start()`。
        已经在事件循环里时请改用 `start()`。可能抛出的异常同 `start()`。
        """

        async def main() -> None:
            async with self:
                await self.start()

        # Ctrl+C 时 asyncio.run 会先取消 main()、走完 async with 的清理，再抛 KeyboardInterrupt。
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(main())

    async def close(self) -> None:
        """断开网关，取消还在运行的处理函数，然后关闭连接；`start()` 随之返回。

        可以重复、并发调用，也可以在处理函数里调用（这时不等其它处理函数结束）。
        处理函数最多等 5 秒，到期仍不结束的记一条警告后不再等。构造时传入的 `http_client` 不会被关闭。
        """
        # 顺序不能换：先断开网关就不再有新事件，再取消处理函数，最后才能关 HTTP 连接。
        if self._connection is not None:
            await self._connection.close()
        await self._dispatcher.aclose()
        await super().close()
