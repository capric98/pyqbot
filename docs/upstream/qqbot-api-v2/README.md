# QQ 机器人 API v2 官方文档快照

来源：[QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/)。抓取时间：2026-11-16T00:15:21+00:00（UTC）。共 192 页。

本目录保存官网已部署页面的正文，保留原文、表格、代码示例和原始标题锚点；站内 API v2 链接已改为本地 Markdown 链接，正文图片直接使用官网提供的 URL，加载图片需要联网。官网内嵌且没有独立 URL 的图片改为查看官方原文的链接。

目录沿用官方 URL 的层级，目录入口保存为 `index.md`。`autogen/api/` 和 `autogen/event/` 分别是官网的接口、事件参考；`server-inter/` 保存场景说明和频道接口；`openapi/`、`gateway/` 保留官网仍部署的补充页面。部分官方目录页只有标题，按原样保存。

`manifest.json` 记录每页来源、官网更新时间、内容哈希、站点配置来源、官方图片 URL 与链接校正记录。官网的更新时间未注明时区，保持原始显示值。

这是外部官方资料归档，内容权利归原作者所有，不属于本项目原创 SDK 文档，不适用项目代码的 MIT 许可证。开发时请结合来源页确认最新规则。

## 更新方式

在项目根目录执行（需安装 uv，Python 3.9+）：

```sh
uv run --locked scripts/sync_qqbot_docs.py
```

文档工具依赖使用 [uv 脚本依赖管理](https://docs.astral.sh/uv/guides/scripts/#declaring-script-dependencies)：声明保存在脚本开头的 PEP 723 元数据中，直接与间接依赖版本锁定在 `scripts/sync_qqbot_docs.py.lock`，运行时由 uv 自动准备环境。

同步脚本从官方 VuePress 路由配置提取所有 API v2 页面，并补充正文中发现的同目录链接。原始 HTML 和路由配置缓存在已忽略的 `.cache/qqbot-docs/`，图片不下载到项目。已有缓存时可离线重新生成 Markdown：

```sh
uv run --locked scripts/sync_qqbot_docs.py --offline
```

这里的 `--offline` 是脚本参数，仅控制文档抓取；正文图片仍使用在线 URL。管理脚本依赖可用 `uv add --script scripts/sync_qqbot_docs.py <包名>`；更新锁文件可用 `uv lock --script scripts/sync_qqbot_docs.py`。

## 文档目录

> 官网正文中有 3 个链接目标不可用，另有 14 处锚点无法匹配；这些链接保留官网地址，未生成替代内容。能唯一匹配的大小写或分隔符差异已校正。详情见 `manifest.json` 的 `unavailable_pages`、`unresolved_anchors` 和 `normalized_links`。

### 入口与变更记录

- [接口文档索引](autogen/index.md) — `autogen/index.md`
- [变更记录](changelog.md) — `changelog.md`
- [启动接入](index.md) — `index.md`

### 起步指南、鉴权与事件连接

- [获取访问凭证](dev-prepare/access-token.md) — `dev-prepare/access-token.md`
- [API 调用指南](dev-prepare/api-call-guide.md) — `dev-prepare/api-call-guide.md`
- [错误与调试](dev-prepare/error-trace/index.md) — `dev-prepare/error-trace/index.md`
- [WebSocket](dev-prepare/error-trace/websocket.md) — `dev-prepare/error-trace/websocket.md`
- [通用数据结构](dev-prepare/event-emit/payload.md) — `dev-prepare/event-emit/payload.md`
- [Webhook 方式](dev-prepare/event-emit/webhook.md) — `dev-prepare/event-emit/webhook.md`
- [WebSocket 方式](dev-prepare/event-emit/websocket.md) — `dev-prepare/event-emit/websocket.md`
- [启动接入](dev-prepare/getting-started.md) — `dev-prepare/getting-started.md`
- [接口调用与鉴权](dev-prepare/interface-framework/api-use.md) — `dev-prepare/interface-framework/api-use.md`
- [事件订阅与通知](dev-prepare/interface-framework/event-emit.md) — `dev-prepare/interface-framework/event-emit.md`
- [接口通信基础框架](dev-prepare/interface-framework/index.md) — `dev-prepare/interface-framework/index.md`
- [opcode](dev-prepare/interface-framework/opcode.md) — `dev-prepare/interface-framework/opcode.md`
- [使用 Websocket 接入](dev-prepare/interface-framework/reference.md) — `dev-prepare/interface-framework/reference.md`
- [安全和授权](dev-prepare/interface-framework/sign.md) — `dev-prepare/interface-framework/sign.md`

### 接口参考

- [删除子频道](autogen/api/channels_channel_id.delete.md) — `autogen/api/channels_channel_id.delete.md`
- [获取子频道详情](autogen/api/channels_channel_id.get.md) — `autogen/api/channels_channel_id.get.md`
- [修改子频道](autogen/api/channels_channel_id.patch.md) — `autogen/api/channels_channel_id.patch.md`
- [获取通用 WSS 接入点](autogen/api/gateway.get.md) — `autogen/api/gateway.get.md`
- [获取频道详情](autogen/api/guilds_guild_id.get.md) — `autogen/api/guilds_guild_id.get.md`
- [获取子频道列表](autogen/api/guilds_guild_id_channels.get.md) — `autogen/api/guilds_guild_id_channels.get.md`
- [创建子频道](autogen/api/guilds_guild_id_channels.post.md) — `autogen/api/guilds_guild_id_channels.post.md`
- [互动事件响应](autogen/api/interactions_interaction_id.put.md) — `autogen/api/interactions_interaction_id.put.md`
- [获取机器人详情](autogen/api/users_me.get.md) — `autogen/api/users_me.get.md`
- [获取机器人频道列表](autogen/api/users_me_guilds.get.md) — `autogen/api/users_me_guilds.get.md`
- [生成分享链接](autogen/api/v2_generate_url_link.post.md) — `autogen/api/v2_generate_url_link.post.md`
- [群聊分片上传完成](autogen/api/v2_groups_group_id_upload_part_finish.post.md) — `autogen/api/v2_groups_group_id_upload_part_finish.post.md`
- [群聊富媒体预上传](autogen/api/v2_groups_group_id_upload_prepare.post.md) — `autogen/api/v2_groups_group_id_upload_prepare.post.md`
- [入群申请审批](autogen/api/v2_groups_group_openid_approval_join_request_member_openid.post.md) — `autogen/api/v2_groups_group_openid_approval_join_request_member_openid.post.md`
- [群成员批量移除](autogen/api/v2_groups_group_openid_batch_remove_members.post.md) — `autogen/api/v2_groups_group_openid_batch_remove_members.post.md`
- [获取机器人群内状态](autogen/api/v2_groups_group_openid_bot_state.get.md) — `autogen/api/v2_groups_group_openid_bot_state.get.md`
- [群聊富媒体上传](autogen/api/v2_groups_group_openid_files.post.md) — `autogen/api/v2_groups_group_openid_files.post.md`
- [获取群基本信息](autogen/api/v2_groups_group_openid_info.get.md) — `autogen/api/v2_groups_group_openid_info.get.md`
- [入群申请列表拉取](autogen/api/v2_groups_group_openid_join_request_list.get.md) — `autogen/api/v2_groups_group_openid_join_request_list.get.md`
- [群黑名单查询](autogen/api/v2_groups_group_openid_member_blacklist.get.md) — `autogen/api/v2_groups_group_openid_member_blacklist.get.md`
- [群黑名单操作](autogen/api/v2_groups_group_openid_member_blacklist.post.md) — `autogen/api/v2_groups_group_openid_member_blacklist.post.md`
- [获取群成员列表](autogen/api/v2_groups_group_openid_members.get.md) — `autogen/api/v2_groups_group_openid_members.get.md`
- [获取群成员信息](autogen/api/v2_groups_group_openid_members_member_openid.get.md) — `autogen/api/v2_groups_group_openid_members_member_openid.get.md`
- [发送群聊消息](autogen/api/v2_groups_group_openid_messages.post.md) — `autogen/api/v2_groups_group_openid_messages.post.md`
- [撤回群聊消息](autogen/api/v2_groups_group_openid_messages_message_id.delete.md) — `autogen/api/v2_groups_group_openid_messages_message_id.delete.md`
- [查询群禁言状态](autogen/api/v2_groups_group_openid_restrict_chat_setting.get.md) — `autogen/api/v2_groups_group_openid_restrict_chat_setting.get.md`
- [设置群成员禁言](autogen/api/v2_groups_group_openid_restrict_chat_setting.post.md) — `autogen/api/v2_groups_group_openid_restrict_chat_setting.post.md`
- [查询入群自动审批策略列表](autogen/api/v2_groups_join_approval_strategy.get.md) — `autogen/api/v2_groups_join_approval_strategy.get.md`
- [创建入群自动审批策略](autogen/api/v2_groups_join_approval_strategy.post.md) — `autogen/api/v2_groups_join_approval_strategy.post.md`
- [删除入群自动审批策略](autogen/api/v2_groups_join_approval_strategy_strategy_id.delete.md) — `autogen/api/v2_groups_join_approval_strategy_strategy_id.delete.md`
- [修改入群自动审批策略](autogen/api/v2_groups_join_approval_strategy_strategy_id.patch.md) — `autogen/api/v2_groups_join_approval_strategy_strategy_id.patch.md`
- [执行入群自动审批策略](autogen/api/v2_groups_join_approval_strategy_strategy_id_execute.post.md) — `autogen/api/v2_groups_join_approval_strategy_strategy_id_execute.post.md`
- [修改入群自动审批策略的白名单号码](autogen/api/v2_groups_join_approval_strategy_strategy_id_whitelist_users.post.md) — `autogen/api/v2_groups_join_approval_strategy_strategy_id_whitelist_users.post.md`
- [查询全局自定义菜单](autogen/api/v2_menu.get.md) — `autogen/api/v2_menu.get.md`
- [修改全局自定义菜单](autogen/api/v2_menu.put.md) — `autogen/api/v2_menu.put.md`
- [查询指令面板列表](autogen/api/v2_panels.get.md) — `autogen/api/v2_panels.get.md`
- [创建指令面板](autogen/api/v2_panels.post.md) — `autogen/api/v2_panels.post.md`
- [删除指令面板](autogen/api/v2_panels_panel_id.delete.md) — `autogen/api/v2_panels_panel_id.delete.md`
- [查询指令面板详情](autogen/api/v2_panels_panel_id.get.md) — `autogen/api/v2_panels_panel_id.get.md`
- [修改指令面板](autogen/api/v2_panels_panel_id.put.md) — `autogen/api/v2_panels_panel_id.put.md`
- [修改指令面板关联对象](autogen/api/v2_panels_panel_id_target.put.md) — `autogen/api/v2_panels_panel_id_target.put.md`
- [单聊分片上传完成](autogen/api/v2_users_user_id_upload_part_finish.post.md) — `autogen/api/v2_users_user_id_upload_part_finish.post.md`
- [单聊富媒体预上传](autogen/api/v2_users_user_id_upload_prepare.post.md) — `autogen/api/v2_users_user_id_upload_prepare.post.md`
- [单聊富媒体上传](autogen/api/v2_users_user_openid_files.post.md) — `autogen/api/v2_users_user_openid_files.post.md`
- [发送单聊消息](autogen/api/v2_users_user_openid_messages.post.md) — `autogen/api/v2_users_user_openid_messages.post.md`
- [撤回单聊消息](autogen/api/v2_users_user_openid_messages_message_id.delete.md) — `autogen/api/v2_users_user_openid_messages_message_id.delete.md`
- [流式发送单聊消息](autogen/api/v2_users_user_openid_stream_messages.post.md) — `autogen/api/v2_users_user_openid_stream_messages.post.md`

### 事件参考

- [单聊消息事件](autogen/event/c2c_message_create.md) — `autogen/event/c2c_message_create.md`
- [单聊消息接收开启](autogen/event/c2c_msg_receive.md) — `autogen/event/c2c_msg_receive.md`
- [单聊消息接收关闭](autogen/event/c2c_msg_reject.md) — `autogen/event/c2c_msg_reject.md`
- [子频道创建](autogen/event/channel_create.md) — `autogen/event/channel_create.md`
- [子频道删除](autogen/event/channel_delete.md) — `autogen/event/channel_delete.md`
- [子频道更新](autogen/event/channel_update.md) — `autogen/event/channel_update.md`
- [用户添加好友](autogen/event/friend_add.md) — `autogen/event/friend_add.md`
- [用户删除好友](autogen/event/friend_del.md) — `autogen/event/friend_del.md`
- [机器人加入群聊](autogen/event/group_add_robot.md) — `autogen/event/group_add_robot.md`
- [群@机器人消息](autogen/event/group_at_message_create.md) — `autogen/event/group_at_message_create.md`
- [机器人退出群聊](autogen/event/group_del_robot.md) — `autogen/event/group_del_robot.md`
- [用户申请加群事件](autogen/event/group_join_request.md) — `autogen/event/group_join_request.md`
- [群成员加入](autogen/event/group_member_add.md) — `autogen/event/group_member_add.md`
- [群成员退出](autogen/event/group_member_remove.md) — `autogen/event/group_member_remove.md`
- [群消息（全量模式）](autogen/event/group_message_create.md) — `autogen/event/group_message_create.md`
- [群聊消息接收开启](autogen/event/group_msg_receive.md) — `autogen/event/group_msg_receive.md`
- [群聊消息接收关闭](autogen/event/group_msg_reject.md) — `autogen/event/group_msg_reject.md`
- [频道创建](autogen/event/guild_create.md) — `autogen/event/guild_create.md`
- [频道解散](autogen/event/guild_delete.md) — `autogen/event/guild_delete.md`
- [频道更新](autogen/event/guild_update.md) — `autogen/event/guild_update.md`
- [互动事件](autogen/event/interaction_create.md) — `autogen/event/interaction_create.md`
- [订阅消息授权状态变更](autogen/event/subscribe_message_status.md) — `autogen/event/subscribe_message_status.md`

### 消息收发、类型与交互

- [消息相关](server-inter/message/index.md) — `server-inter/message/index.md`
- [素材管理](server-inter/message/material-management.md) — `server-inter/message/material-management.md`
- [消息收发概述](server-inter/message/overview.md) — `server-inter/message/overview.md`
- [富媒体消息概述](server-inter/message/rich-media.md) — `server-inter/message/rich-media.md`
- [消息对象(Message)](server-inter/message/template/model.md) — `server-inter/message/template/model.md`
- [表情表态](server-inter/message/trans/emoji.md) — `server-inter/message/trans/emoji.md`
- [消息按钮](server-inter/message/trans/msg-btn.md) — `server-inter/message/trans/msg-btn.md`
- [消息交互概述](server-inter/message/trans/overview.md) — `server-inter/message/trans/overview.md`
- [文本交互](server-inter/message/trans/text-chain.md) — `server-inter/message/trans/text-chain.md`
- [结构化卡片消息](server-inter/message/type/ark.md) — `server-inter/message/type/ark.md`
- [Embed 消息](server-inter/message/type/embed.md) — `server-inter/message/type/embed.md`
- [Markdown 消息](server-inter/message/type/markdown.md) — `server-inter/message/type/markdown.md`
- [消息类型](server-inter/message/type/overview.md) — `server-inter/message/type/overview.md`

### 机器人与用户

- [用户模块](server-inter/user/index.md) — `server-inter/user/index.md`
- [事件](server-inter/user/manage/event.md) — `server-inter/user/manage/event.md`
- [用户管理](server-inter/user/manage/index.md) — `server-inter/user/manage/index.md`

### 群聊管理

- [群组模块](server-inter/group/index.md) — `server-inter/group/index.md`
- [群管理](server-inter/group/manage/index.md) — `server-inter/group/manage/index.md`

### 菜单与面板

- [自定义菜单与指令面板](server-inter/menu-panel/index.md) — `server-inter/menu-panel/index.md`

### 频道管理

- [获取机器人在频道可用权限列表](server-inter/channel/api_permissions/get_guild_api_permission.md) — `server-inter/channel/api_permissions/get_guild_api_permission.md`
- [频道模块](server-inter/channel/api_permissions/index.md) — `server-inter/channel/api_permissions/index.md`
- [接口权限对象](server-inter/channel/api_permissions/model.md) — `server-inter/channel/api_permissions/model.md`
- [发送机器人在频道接口权限的授权链接](server-inter/channel/api_permissions/post_api_permission_demand.md) — `server-inter/channel/api_permissions/post_api_permission_demand.md`
- [删除子频道公告（2022年3月15日后废弃）](server-inter/channel/content/announces/delete_channel_announces.md) — `server-inter/channel/content/announces/delete_channel_announces.md`
- [删除频道公告](server-inter/channel/content/announces/delete_guild_announces.md) — `server-inter/channel/content/announces/delete_guild_announces.md`
- [公告对象(Announces)](server-inter/channel/content/announces/model.md) — `server-inter/channel/content/announces/model.md`
- [创建子频道公告（2022年3月15日后废弃）](server-inter/channel/content/announces/post_channel_announces.md) — `server-inter/channel/content/announces/post_channel_announces.md`
- [创建频道公告](server-inter/channel/content/announces/post_guild_announces.md) — `server-inter/channel/content/announces/post_guild_announces.md`
- [音频控制](server-inter/channel/content/audio/audio_control.md) — `server-inter/channel/content/audio/audio_control.md`
- [机器人下麦](server-inter/channel/content/audio/delete_mic.md) — `server-inter/channel/content/audio/delete_mic.md`
- [语音对象](server-inter/channel/content/audio/model.md) — `server-inter/channel/content/audio/model.md`
- [机器人上麦](server-inter/channel/content/audio/put_mic.md) — `server-inter/channel/content/audio/put_mic.md`
- [删除帖子](server-inter/channel/content/forum/delete_thread.md) — `server-inter/channel/content/forum/delete_thread.md`
- [论坛事件对象(ForumEvent)](server-inter/channel/content/forum/forum.md) — `server-inter/channel/content/forum/forum.md`
- [获取帖子详情](server-inter/channel/content/forum/get_thread.md) — `server-inter/channel/content/forum/get_thread.md`
- [获取帖子列表](server-inter/channel/content/forum/get_threads_list.md) — `server-inter/channel/content/forum/get_threads_list.md`
- [论坛对象(forum)](server-inter/channel/content/forum/model.md) — `server-inter/channel/content/forum/model.md`
- [开放论坛事件对象(OpenForumEvent)](server-inter/channel/content/forum/open_forum.md) — `server-inter/channel/content/forum/open_forum.md`
- [发表帖子](server-inter/channel/content/forum/put_thread.md) — `server-inter/channel/content/forum/put_thread.md`
- [频道模块](server-inter/channel/content/index.md) — `server-inter/channel/content/index.md`
- [删除精华消息](server-inter/channel/content/pins/delete_pins_message.md) — `server-inter/channel/content/pins/delete_pins_message.md`
- [获取精华消息](server-inter/channel/content/pins/get_pins_message.md) — `server-inter/channel/content/pins/get_pins_message.md`
- [精华消息对象(PinsMessage)](server-inter/channel/content/pins/model.md) — `server-inter/channel/content/pins/model.md`
- [添加精华消息](server-inter/channel/content/pins/put_pins_message.md) — `server-inter/channel/content/pins/put_pins_message.md`
- [删除日程](server-inter/channel/content/schedule/delete_schedule.md) — `server-inter/channel/content/schedule/delete_schedule.md`
- [获取日程详情](server-inter/channel/content/schedule/get_schedule.md) — `server-inter/channel/content/schedule/get_schedule.md`
- [获取频道日程列表](server-inter/channel/content/schedule/get_schedules.md) — `server-inter/channel/content/schedule/get_schedules.md`
- [日程对象(Schedule)](server-inter/channel/content/schedule/model.md) — `server-inter/channel/content/schedule/model.md`
- [修改日程](server-inter/channel/content/schedule/patch_schedule.md) — `server-inter/channel/content/schedule/patch_schedule.md`
- [创建日程](server-inter/channel/content/schedule/post_schedule.md) — `server-inter/channel/content/schedule/post_schedule.md`
- [频道模块](server-inter/channel/index.md) — `server-inter/channel/index.md`
- [子频道对象(Channel)](server-inter/channel/manage/channel/model.md) — `server-inter/channel/manage/channel/model.md`
- [频道对象(Guild)](server-inter/channel/manage/guild/model.md) — `server-inter/channel/manage/guild/model.md`
- [频道模块](server-inter/channel/manage/index.md) — `server-inter/channel/manage/index.md`
- [用户对象(User)](server-inter/channel/manage/user/model.md) — `server-inter/channel/manage/user/model.md`
- [频道私信](server-inter/channel/message/dms.md) — `server-inter/channel/message/dms.md`
- [频道消息事件](server-inter/channel/message/event.md) — `server-inter/channel/message/event.md`
- [内嵌格式](server-inter/channel/message/format.md) — `server-inter/channel/message/format.md`
- [撤回子频道消息](server-inter/channel/message/recall.md) — `server-inter/channel/message/recall.md`
- [发送子频道消息](server-inter/channel/message/send.md) — `server-inter/channel/message/send.md`
- [频道模块](server-inter/channel/miniapp/index.md) — `server-inter/channel/miniapp/index.md`
- [获取频道和当前人信息](server-inter/channel/miniapp/interface.md) — `server-inter/channel/miniapp/interface.md`
- [开放数据域加密](server-inter/channel/miniapp/opendata.md) — `server-inter/channel/miniapp/opendata.md`
- [获取子频道用户权限](server-inter/channel/role-group/channel_permissions/get_channel_permissions.md) — `server-inter/channel/role-group/channel_permissions/get_channel_permissions.md`
- [获取子频道身份组权限](server-inter/channel/role-group/channel_permissions/get_channel_roles_permissions.md) — `server-inter/channel/role-group/channel_permissions/get_channel_roles_permissions.md`
- [子频道权限对象(ChannelPermissions)](server-inter/channel/role-group/channel_permissions/model.md) — `server-inter/channel/role-group/channel_permissions/model.md`
- [修改子频道用户权限](server-inter/channel/role-group/channel_permissions/put_channel_permissions.md) — `server-inter/channel/role-group/channel_permissions/put_channel_permissions.md`
- [修改子频道身份组权限](server-inter/channel/role-group/channel_permissions/put_channel_roles_permissions.md) — `server-inter/channel/role-group/channel_permissions/put_channel_roles_permissions.md`
- [删除频道身份组成员](server-inter/channel/role-group/delete_guild_member_role.md) — `server-inter/channel/role-group/delete_guild_member_role.md`
- [删除频道身份组](server-inter/channel/role-group/delete_guild_role.md) — `server-inter/channel/role-group/delete_guild_role.md`
- [获取频道身份组列表](server-inter/channel/role-group/get_guild_roles.md) — `server-inter/channel/role-group/get_guild_roles.md`
- [频道模块](server-inter/channel/role-group/index.md) — `server-inter/channel/role-group/index.md`
- [修改频道身份组](server-inter/channel/role-group/patch_guild_role.md) — `server-inter/channel/role-group/patch_guild_role.md`
- [创建频道身份组](server-inter/channel/role-group/post_guild_role.md) — `server-inter/channel/role-group/post_guild_role.md`
- [创建频道身份组成员](server-inter/channel/role-group/put_guild_member_role.md) — `server-inter/channel/role-group/put_guild_member_role.md`
- [音视频/直播子频道成员进出事件](server-inter/channel/role/audio_or_live_channel_member.md) — `server-inter/channel/role/audio_or_live_channel_member.md`
- [获取子频道在线成员数](server-inter/channel/role/get_online_nums.md) — `server-inter/channel/role/get_online_nums.md`
- [频道成员事件](server-inter/channel/role/guild_member.md) — `server-inter/channel/role/guild_member.md`
- [频道模块](server-inter/channel/role/index.md) — `server-inter/channel/role/index.md`
- [删除频道成员](server-inter/channel/role/member/delete_member.md) — `server-inter/channel/role/member/delete_member.md`
- [获取频道成员详情](server-inter/channel/role/member/get_member.md) — `server-inter/channel/role/member/get_member.md`
- [获取频道成员列表](server-inter/channel/role/member/get_members.md) — `server-inter/channel/role/member/get_members.md`
- [获取频道身份组成员列表](server-inter/channel/role/member/get_role_members.md) — `server-inter/channel/role/member/get_role_members.md`
- [成员对象(Member)](server-inter/channel/role/member/model.md) — `server-inter/channel/role/member/model.md`
- [频道身份组对象(Role)](server-inter/channel/role/member/role_model.md) — `server-inter/channel/role/member/role_model.md`
- [频道模块](server-inter/channel/speak/index.md) — `server-inter/channel/speak/index.md`
- [频道指定成员禁言](server-inter/channel/speak/patch_guild_member_mute.md) — `server-inter/channel/speak/patch_guild_member_mute.md`
- [频道全员禁言](server-inter/channel/speak/patch_guild_mute.md) — `server-inter/channel/speak/patch_guild_mute.md`
- [频道批量成员禁言](server-inter/channel/speak/patch_guild_mute_multi_member.md) — `server-inter/channel/speak/patch_guild_mute_multi_member.md`
- [获取频道消息频率的设置详情](server-inter/channel/speak/setting/message_setting.md) — `server-inter/channel/speak/setting/message_setting.md`
- [频道消息频率设置对象 (MessageSetting)](server-inter/channel/speak/setting/model.md) — `server-inter/channel/speak/setting/model.md`

### 补充接口、模型与错误码

- [业务报错返回的数据信息(Data)](gateway/error/data/model.md) — `gateway/error/data/model.md`
- [websocket 错误](gateway/error/error.md) — `gateway/error/error.md`
- [表情对象](openapi/emoji/model.md) — `openapi/emoji/model.md`
- [业务报错返回的数据信息(Data)](openapi/error/data/model.md) — `openapi/error/data/model.md`
- [错误与调试](openapi/error/error.md) — `openapi/error/error.md`
- [删除频道成员](openapi/member/delete_member.md) — `openapi/member/delete_member.md`
- [获取成员详情](openapi/member/get_member.md) — `openapi/member/get_member.md`
- [获取频道成员列表](openapi/member/get_members.md) — `openapi/member/get_members.md`
- [成员对象(Member)](openapi/member/model.md) — `openapi/member/model.md`
- [表情表态对象](openapi/reaction/model.md) — `openapi/reaction/model.md`
- [获取用户频道列表](openapi/user/guilds.md) — `openapi/user/guilds.md`
- [获取用户详情](openapi/user/me.md) — `openapi/user/me.md`
- [用户对象(User)](openapi/user/model.md) — `openapi/user/model.md`
- [获取带分片 WSS 接入点](openapi/wss/shard_url_get.md) — `openapi/wss/shard_url_get.md`
- [获取通用 WSS 接入点](openapi/wss/url_get.md) — `openapi/wss/url_get.md`
