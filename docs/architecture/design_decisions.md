# 设计决策（ADR）

本文档记录项目中的关键设计决策。若没有新的 ADR 明确替代，以下决策都视为已接受并长期有效。

为避免长清单继续失控，ADR 仅按主题分组展示；编号保持稳定，便于其他文档引用。

## A. 客户端分层与 UI

## ADR-001：客户端运行时使用 PySide6 + qasync + asyncio

- 状态：Accepted
- 决策：客户端统一使用 PySide6 作为 GUI 框架，使用 qasync 把 Qt 事件循环与 asyncio 主循环整合起来。
- 结果：网络 IO 走 asyncio；UI 更新回到 Qt 主线程；阻塞任务显式下沉到 executor 或独立工作线程。

## ADR-002：QFluentWidgets 优先于手写通用控件

- 状态：Accepted
- 决策：有现成 QFluentWidgets 组件时优先复用，不重复手写通用按钮、卡片、菜单、设置项和提示层。
- 结果：具体规则见 [ui_guidelines.md]../ui_guidelines.md)。

## ADR-003：客户端采用 UI -> Controller -> Manager -> Service -> Network 主链路

- 状态：Accepted
- 决策：命令路径走 Controller / Manager / Service；通知路径走 Manager -> EventBus -> UI。
- 结果：UI 不直接访问 HTTP / WebSocket / Database；Service 不直接更新 UI。

## ADR-004：ConnectionManager 作为实时链路协调者

- 状态：Accepted
- 决策：WebSocket 连接生命周期由 `ConnectionManager` 统一管理，其他 Manager 通过它暴露的接口与实时链路交互。
- 结果：除 `ConnectionManager` 外，其他模块不应直接依赖底层 `WebSocketClient`。

## ADR-013：UI 设计系统以 CardWidget / Acrylic / Gallery 风格统一

- 状态：Accepted
- 决策：容器类业务组件统一收敛到 `CardWidget` 体系，Tooltip 使用 Acrylic 方案，QSS 组织方式参考 QFluentWidgets Gallery。
- 结果：具体约束见 [ui_guidelines.md]../ui_guidelines.md)。

## ADR-020：`SessionManager` 通过 `SessionService` 访问远程会话 HTTP 能力

- 状态：Accepted
- 决策：会话详情拉取、会话列表刷新、未读统计拉取、私聊会话创建等远程 HTTP 能力统一收敛到 `SessionService`；`SessionManager` 只编排本地状态、缓存与 EventBus。
- 结果：后续扩展缓存策略、灰度接口或批量接口时优先修改 `SessionService`。

## ADR-021：UI Controller 的远程操作统一通过 Service 边界发起

- 状态：Accepted
- 决策：`AuthController`、`ContactController`、`DiscoveryController` 等 UI controller 不直接发 HTTP 请求；远程能力分别收敛到对应 Service。
- 结果：Controller 负责参数整理和交互编排；Service 负责远程 API。

## ADR-022：`ConnectionManager` 通过 `AuthService` 读取认证状态

- 状态：Accepted
- 决策：`ConnectionManager` 构造带 token 的 WS URL、发送 WS `auth` 命令时，只通过 `AuthService` 读取当前 access token。
- 结果：实时连接层只依赖认证边界与 WebSocket transport，不直接依赖 `HTTPClient`。

## ADR-023：本地搜索查询通过 Storage 公共 API 暴露

- 状态：Accepted
- 决策：消息搜索等本地缓存查询通过 `Database.search_messages.)` 这类公共 storage API 暴露；Manager 不直接写 SQL，也不调用 storage 私有 helper。
- 结果：搜索语义、SQLite 兼容和结果解码统一留在 storage 层。

## B. 一致性、权限与领域真相

## ADR-005：命令幂等依赖 `msg_id` + ACK 机制

- 状态：Accepted
- 决策：消息发送及其他可重试命令必须带唯一 `msg_id`，服务端对其做幂等处理，客户端等待 ACK 并在超时后复用同一 `msg_id` 重发。
- 结果：`msg_id` 成为 ACK、重发、日志与冲突检查的统一主键。

## ADR-006：会话内顺序由 `session_seq` 表达

- 状态：Accepted
- 决策：消息排序、已读游标推进、断线补偿全部基于每个会话独立递增的 `session_seq`。
- 结果：客户端按会话维护消息同步高水位。

## ADR-007：断线补偿使用游标，不使用时间戳

- 状态：Accepted
- 决策：客户端维护 `session_cursors` 与 `event_cursors`，服务端分别补偿遗漏消息和遗漏事件。
- 结果：`session_seq` 负责新消息，`event_seq` 负责 `read`、`message_edit`、`message_recall`、`message_delete` 等事件。

## ADR-008：已读是成员游标，不是消息全局状态

- 状态：Accepted
- 决策：已读由 `SessionMember.last_read_seq` 表达，不把 `message.status` 改成全局 `read`。
- 结果：私聊展示对方已读，群聊展示读人数或读者列表。

## ADR-009：`session_members` 是聊天权限与已读的真相来源

- 状态：Accepted
- 决策：会话成员关系、已读游标、会话权限统一以 `session_members` 为准。
- 结果：群组域模型不再绕开 `session_members` 充当聊天权限真相；历史漂移只允许在受控迁移里回填。

## ADR-010：WebSocket Gateway 不能绕过 Service 执行业务变更

- 状态：Accepted
- 决策：撤回、编辑、删除、已读等 WS 命令必须复用 Service 规则。
- 结果：任何“只在 WS 入口广播、不经 Service 校验”的实现都视为错误设计。

## ADR-011：本地 SQLite 是缓存与恢复层，不是业务真相层

- 状态：Accepted
- 决策：客户端使用 SQLite 保存消息、会话和同步高水位，但不把本地缓存当作权限和业务真相来源。
- 结果：本地缓存用于恢复、展示和重试，最终权限与业务规则仍以后端为准。

## ADR-012：消息流与状态事件流分离

- 状态：Accepted
- 决策：新消息使用 `session_seq` 排序与补偿，已读、编辑、撤回、删除使用独立 `event_seq` 事件流。
- 结果：重连同步返回 `history_messages` 与 `history_events` 两条载荷，客户端分别推进消息游标和事件游标。

## ADR-015：好友请求以用户对为边界做幂等归一化

- 状态：Accepted
- 决策：好友请求禁止自加；同方向重复发送返回现有 `pending` 请求；若检测到反向 `pending` 请求，则直接接受现有请求并建立好友关系。
- 结果：好友请求接口允许返回 `pending` 或 `accepted`，客户端不得假设结果永远是“已发送”。

## C. 基础设施、入口与配置边界

## ADR-014：正式扩展路径通过抽象边界实现，而不是到处埋兼容分支

- 状态：Accepted
- 决策：需要支持 Redis、对象存储、事件流时，应通过清晰接口或网关抽象演进，而不是把“未来扩展”散落在各层 if/else 中。
- 结果：优先收敛边界，再替换实现。

## ADR-016：`HTTPClient` 只对内部相对路径继承应用鉴权，refresh 采用单飞

- 状态：Accepted
- 决策：`HTTPClient` 只把相对路径视为应用内部 API，请求才会继承应用 access token 与 401 refresh；绝对 URL 默认视为外部服务，不继承应用鉴权，也不会触发应用 refresh；并发 401 只允许一次 refresh in-flight。
- 结果：外部 provider 请求可以安全复用 `HTTPClient` transport；内部 API 不会因为并发刷新出现竞态失败。

## ADR-017：实时连接与限流状态通过基础设施边界暴露

- 状态：Accepted
- 决策：连接注册 / fanout 统一通过 `RealtimeHub` 暴露；HTTP 限流计数统一通过 `RateLimitStore` 暴露；当前默认实现可使用进程内内存结构。
- 结果：后续接入 Redis / PubSub / 共享限流存储时，优先替换基础设施实现，不改业务规则与协议。

## ADR-018：服务端时间统一使用 timezone-aware UTC，应用生命周期使用 lifespan

- 状态：Accepted
- 决策：服务端运行时与持久化默认使用 timezone-aware UTC；启动初始化使用 FastAPI lifespan，而不是遗留 `on_event` 钩子。
- 结果：时间比较统一通过 UTC helper 处理；启动初始化不再依赖已弃用 API。

## ADR-019：上传链路使用结构化异常与归一化 payload

- 状态：Accepted
- 决策：`HTTPClient.upload_file` 失败时抛结构化异常，不返回 `None`；`FileService` 负责把上传返回归一化为带 `url` 的正式 payload。
- 结果：聊天附件、头像更新和失败重试可以共享同一套失败模型。

## ADR-024：Legacy Chat HTTP 兼容入口已移除

- 状态：Accepted
- 决策：历史 `/api/chat/*` HTTP 兼容入口不再保留；服务端只维护正式 `/api/v1/*` API 边界。
- 结果：不再通过重复 router 挂载维护 legacy HTTP 别名。

## ADR-025：Legacy Chat HTTP Sync 不再单独保留

- 状态：Accepted
- 决策：历史 `POST /api/chat/sync` 兼容入口不再保留；断线补偿只通过正式实时链路的 `session_cursors + event_cursors` 语义维护。
- 结果：当前代码基线不再维护额外的 legacy HTTP sync 语义。

## ADR-026：聊天 WebSocket 正式入口收敛到 `/ws`

- 状态：Accepted
- 决策：`/ws` 作为唯一正式聊天 WebSocket 入口；历史 `/ws/chat` alias 不再保留。
- 结果：客户端、测试和文档统一把 `/ws` 视为唯一 canonical endpoint。

## ADR-027：配置读取使用运行时快照，不在类定义或路由装饰期冻结

- 状态：Accepted
- 决策：`Settings` 在实例化时读取环境变量；应用入口通过 `create_app.settings)` 使用显式配置快照；需要重载时通过 `reload_settings.)` 清理缓存后重建。
- 结果：配置边界变成“可重建的 settings snapshot + app factory + 动态依赖”。

## ADR-028：数据库 runtime 通过显式配置函数绑定，不在模块导入时冻结 engine

- 状态：Accepted
- 决策：数据库层通过 `configure_database.settings)` 与 `get_engine.)` 绑定具体 engine；`SessionLocal` 保持为稳定 session factory。
- 结果：engine 生命周期与 app / config 生命周期对齐，而不是依赖模块导入副作用。

## ADR-029：认证、文件与限流依赖通过 app settings snapshot 读取配置

- 状态：Accepted
- 决策：HTTP Request 与 WebSocket 都通过 app state 中的 settings snapshot 读取配置；认证 token 解码、文件服务和动态限流优先消费这份显式 snapshot。
- 结果：`create_app.settings)` 真正成为运行时配置边界，HTTP / WS / Service 共享同一份配置快照。

## ADR-030：文件与媒体存储通过显式 `MediaStorage` 边界与规范附件元数据建模

- 状态：Accepted
- 决策：服务端上传链路通过 `MediaStorage` 抽象承载，默认实现为 `LocalMediaStorage`；上传成功后统一返回规范媒体元数据；消息附件通过 `messages.extra` 持久化可展示、可回放的远端媒体元数据。
- 结果：服务端只保存 shareable metadata；客户端保留本地重试状态；后续切换对象存储时只扩展 `MediaStorage` 实现。

## D. 传输安全、通话与 E2EE

## ADR-031：生产环境传输链路统一收敛到 HTTPS / WSS

- 状态：Accepted
- 决策：生产环境中的后端 API 与实时链路统一通过 `HTTPS` 与 `WSS` 提供；开发环境可以保留 `HTTP` / `WS` 作为本地调试基线，但不作为正式部署默认值。
- 结果：客户端配置与部署文档都把 TLS 视为正式基线。

## ADR-032：1:1 语音 / 视频通话使用 WebRTC 媒体链路，信令复用聊天 WebSocket

- 状态：Accepted
- 决策：1:1 语音与视频通话的媒体层统一使用 WebRTC；来电、接听、拒绝、挂断、offer / answer / ICE 等 signaling 继续复用现有聊天 WebSocket 协议。
- 结果：WebSocket 只承载通话信令，不传输音视频帧；客户端需通过 `CallManager` 统一维护通话状态机。

## ADR-033：私聊端到端加密采用设备模型与 Double Ratchet 路线，AI 会话保持服务端可见

- 状态：Accepted
- 决策：E2EE 首先只适用于 `private` 会话，并采用设备身份密钥 + prekey + Double Ratchet 路线；`AI` 会话明确保持 `server_visible_ai`。
- 结果：服务端只路由密文与附件加密元数据；AI 会话仍允许服务端与 provider 获取明文；群聊 E2EE 作为独立后续主题处理。

## ADR-034：E2EE 私聊的本地缓存优先持久化密文，数据库落盘加固通过 SQLCipher 演进

- 状态：Accepted
- 决策：启用 E2EE 的私聊在客户端本地优先持久化密文，解密后的明文默认仅保留在内存态或受保护的本地密钥缓存中；数据库落盘保护后续通过 `SQLite + SQLCipher` 演进，并使用系统安全存储保护 DB key。
- 结果：E2EE 私聊的本地搜索能力允许在 MVP 阶段降级或关闭；数据库加固作为独立后续阶段推进，不阻塞通话与私聊 E2EE 主链路落地。
