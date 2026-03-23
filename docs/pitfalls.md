# 常见陷阱与反模式

本文档记录项目中需要主动规避的错误设计。它不是重复架构文档，而是把容易再次犯错的地方直接点出来，方便 code review 与后续重构时对照检查。

## 1. UI 直接调用网络或数据库

错误模式：

- Widget 里直接发 HTTP 请求
- Widget 里直接发 WebSocket
- Widget 里直接读写 SQLite

为什么错：

- UI 与业务状态耦合
- 难测
- 页面一多就到处复制逻辑

正确方式：

- UI -> Controller -> Manager
- Manager 协调 Service / ConnectionManager / Storage

## 2. 在多个地方维护同一份业务真相

错误模式：

- 同时依赖多套成员关系判断聊天权限
- UI 自己维护未读、排序、会话状态真相
- 本地缓存和服务端权限混在一起判断

为什么错：

- 写路径复杂
- 读路径需要“修复”数据
- 状态长期漂移

正确方式：

- 会话权限与已读真相统一落到 `session_members`
- 客户端状态统一由 Manager 管理
- 本地缓存只做恢复与展示，不做最终权限真相
- 历史成员漂移通过启动期兼容迁移回填，不在 `list/get/send` 等业务请求里隐式补数据

## 3. 把群聊已读写成消息全局 `read`

错误模式：

- 只要有一个群成员读了消息，就把消息状态写成 `read`

为什么错：

- 群聊里“有人读了”不等于“所有人读了”
- 失去按成员统计与展示能力

正确方式：

- 已读使用成员读指针 `last_read_seq`
- 私聊显示对方已读
- 群聊显示读人数或读者列表

## 4. 用时间戳做正式断线补偿

错误模式：

- 用 `last_timestamp` 拉缺失消息
- 认为“created_at 更大就是新消息”

为什么错：

- 时间精度、时钟漂移、写入重排都会破坏正确性
- 不适合作为 IM 正式补偿依据

正确方式：

- 新消息补偿使用 `session_cursors`
- 状态事件补偿使用 `event_cursors`
- 会话顺序使用 `session_seq`

## 5. 拿 `session_seq` 补偿非消息事件

错误模式：

- 试图通过 `session_seq` 推断 edit / recall / delete / read 是否遗漏
- 把所有状态变更混到消息补偿里

为什么错：

- 新消息与状态变更不是同一类数据
- 客户端很难处理“没有新消息，但旧消息状态变了”的场景

正确方式：

- 新消息补偿使用 `session_cursors`
- 状态事件补偿使用 `event_cursors`
- `read`、`message_edit`、`message_recall`、`message_delete` 进入独立事件流

## 6. 用 `max(session_seq) + 1` 分配消息序号

错误模式：

- 读取当前最大值再加一

为什么错：

- 并发下会冲突
- 事务回滚和重试复杂

正确方式：

- 使用会话级高水位原子递增
- 把 `last_message_seq` 作为正式分配器

## 7. 把好友请求当成“每点一次就新建一条记录”

错误模式：

- 允许用户给自己发好友请求
- 同方向重复点击反复创建多条 `pending` 请求
- A 给 B 发过请求后，B 再给 A 发一条新的 `pending` 请求

为什么错：

- 会把简单的好友关系变成脏数据堆积
- UI 很难判断哪一条才是当前有效请求
- 互相想加好友时反而需要两边重复处理

正确方式：

- 自加直接拒绝
- 同方向重复发送按幂等处理，返回现有 `pending` 请求
- 发现反向 `pending` 时直接接受已有请求并建立好友关系

## 8. WebSocket Gateway 直接广播业务变更

错误模式：

- WS 入口只做“是不是会话成员”的校验
- 然后直接广播 edit / recall / delete / read

为什么错：

- HTTP 与 WS 规则容易分叉
- 权限校验、时间窗校验、消息归属校验会漏掉

正确方式：

- WS 与 HTTP 共用同一套 Service 规则
- Gateway 只做协议适配和错误转换

## 9. ACK 机制只有一半

错误模式：

- 客户端等待 ACK，但超时后不真正重发
- 重发时换了新的 `msg_id`
- 服务端没有做幂等去重

为什么错：

- 表面上有 ACK，实际上没有可靠性闭环

正确方式：

- 同一逻辑消息复用同一 `msg_id`
- ACK 超时自动重发
- 服务端幂等处理并返回权威结果

## 10. 把 EventBus 当成命令总线

错误模式：

- UI 通过 EventBus 反向驱动业务命令
- 任意层都往 EventBus 塞命令型消息

为什么错：

- 调用路径不清晰
- 难定位真正入口
- 更容易变成隐式耦合

正确方式：

- 命令走 Controller / Manager
- EventBus 只传播状态变化与通知

## 11. 长列表使用全量 reset

错误模式：

- 消息列表一变化就 `beginResetModel()`
- 会话列表一变化就全量重建

为什么错：

- 大列表性能差
- 滚动位置和选择态容易抖动

正确方式：

- 优先增量更新模型
- 只有全量快照替换时才考虑 reset

## 12. AI streaming 每个 token 都重绘 UI

错误模式：

- 每收到一个 token 就刷新一次整个界面

为什么错：

- 重绘过于频繁
- 长文本输出时体验会迅速变差

正确方式：

- 做节流或批量刷新
- 把 token 合并成短周期批次更新

## 13. 自定义一堆“伪 Fluent”基础控件

错误模式：

- 有现成 QFluentWidgets 组件，却重新写按钮、卡片、菜单、tooltip
- 页面各自发明一套容器和样式规则

为什么错：

- 风格漂移
- 重复维护
- 设计系统无法统一

正确方式：

- 优先复用 QFluentWidgets
- 容器统一 `CardWidget`
- Tooltip 默认 Acrylic + Filter
- 样式参考 Gallery 与共享 token

## 14. 大量内联 `setStyleSheet`

错误模式：

- Python 代码里拼大量样式字符串
- 相似页面复制粘贴一份颜色和圆角

为什么错：

- 样式难以统一
- 主题切换成本高
- 维护成本高

正确方式：

- 用共享 QSS 文件 + style registry
- 通过 objectName 和 token 管理差异

## 15. 未追踪的后台任务

错误模式：

- `asyncio.create_task()` 后不保存引用
- 程序退出时任务还在跑

为什么错：

- 无法取消
- 异常容易丢失
- 关闭时出现 pending task 警告

正确方式：

- 保存任务引用
- 关闭时 cancel + await
- 明确区分长期任务与短期任务

## 16. 吞掉 `CancelledError`

错误模式：

- `except Exception` 把取消异常一起吞了

为什么错：

- 任务无法正常退出
- 关闭流程和重连流程容易混乱

正确方式：

- 显式处理 `CancelledError`
- 需要时重新抛出

## 17. 在服务端继续使用 naive UTC 时间或遗留生命周期钩子

错误模式：

- 在服务端继续写 `datetime.utcnow()`
- 拿 naive datetime 和 aware datetime 混着比较
- 继续依赖 FastAPI `@app.on_event("startup")`

为什么错：

- 会持续制造时区歧义和运行时 warning
- SQLite / PostgreSQL / Python datetime 边界更容易出现隐性 bug
- 生命周期入口分散，不利于后续扩展启动与清理逻辑

正确方式：

- 统一通过 UTC helper 生成和归一化时间
- 时间比较前先归一化到 aware UTC
- 应用初始化使用 FastAPI lifespan

## 18. 文档长期滞后于设计与实现

错误模式：

- 协议改了但文档没改
- UI 规则变了但没有统一文档
- 架构错误被写进文档继续传播

为什么错：

- 后续重构没有统一目标
- AI / 新同事 / code review 都会被错误文档误导

正确方式：

- 改架构就改文档
- 改协议就改文档和测试
- 发现设计不对，优先修正文档里的错误设计

## 19. 在 HTTP / WebSocket 请求链路里直接回退到全局 `get_settings()`

错误模式：

- Request dependency 自己调用 `get_settings()`
- WebSocket 认证直接用全局 secret 解 token
- 动态限流在闭包里固化或偷读全局配置

为什么错：

- `create_app(settings)` 传入的自定义配置不会真正传到底层依赖
- 测试 app、灰度 app、兼容开关会和全局缓存重新耦合
- HTTP 和 WebSocket 可能读到不同配置快照，行为变得不可预测

正确方式：

- HTTP 通过 `request.app.state.settings` 读取当前配置
- WebSocket 通过 `websocket.app.state.settings` 读取当前配置
- token 解码、文件服务、动态限流优先接收显式 settings snapshot

## 20. 把本地附件状态或裸 URL 直接当成正式媒体模型

错误模式：

- 上传接口只返回一个 `file_url`
- 消息里直接塞 `local_path` 给服务端
- 文件列表、聊天消息、历史同步各自返回不同附件字段

为什么错：

- 历史回放和断线补偿拿不到稳定附件元数据
- 本地重试状态和服务端持久化状态耦在一起
- 后续切换对象存储时需要同时改协议、UI、消息模型

正确方式：

- 上传通过统一媒体描述返回 `storage_provider`、`storage_key`、`url`、`mime_type`、`original_name`、`size_bytes`、`checksum_sha256`
- 服务端消息只持久化可共享、可回放的远端附件元数据
- `local_path`、`uploading` 等临时状态只保留在客户端，并在真正发消息前剥离

