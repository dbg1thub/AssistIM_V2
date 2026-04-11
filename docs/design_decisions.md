# 设计决策（ADR）

本文档记录项目中的关键设计决策。若没有新的 ADR 明确替代，以下决策都视为已接受并长期有效。

## ADR-001：客户端运行时使用 PySide6 + qasync + asyncio

- 状态：Accepted
- 决策：客户端统一使用 PySide6 作为 GUI 框架，使用 qasync 把 Qt 事件循环与 asyncio 主循环整合起来。
- 原因：这是桌面 Python 项目中成熟、常见且可维护的组合，能够避免大量线程同步复杂度。
- 结果：网络 IO 走 asyncio；UI 更新仍回到 Qt 主线程；阻塞任务必须显式下沉到 executor 或独立工作线程。

## ADR-002：QFluentWidgets 优先于手写通用控件

- 状态：Accepted
- 决策：有现成 QFluentWidgets 组件时，优先复用，不重复手写通用按钮、卡片、菜单、设置项、提示层。
- 原因：统一视觉、减少重复代码、降低样式漂移。
- 结果：具体规则见 [ui_guidelines.md](./ui_guidelines.md)。

## ADR-003：客户端采用 UI -> Controller -> Manager -> Service -> Network 主链路

- 状态：Accepted
- 决策：命令路径走 Controller / Manager / Service；通知路径走 Manager -> EventBus -> UI。
- 原因：这是低耦合且便于测试的常见客户端分层方式。
- 结果：UI 不能直接访问 HTTP / WebSocket / Database；Service 不直接更新 UI。

## ADR-004：ConnectionManager 作为实时链路协调者

- 状态：Accepted
- 决策：WebSocket 连接生命周期由 `ConnectionManager` 统一管理，其他 Manager 通过它暴露的接口与实时链路交互。
- 原因：把“连接状态机”与“消息业务状态机”分开，降低耦合。
- 结果：除 `ConnectionManager` 外，其他模块不应直接依赖底层 `WebSocketClient`。

## ADR-005：命令幂等依赖 `msg_id` + ACK 机制

- 状态：Accepted
- 决策：消息发送及其他可重试命令必须带唯一 `msg_id`，服务端对其做幂等处理，客户端等待 ACK 并在超时后复用同一 `msg_id` 重发。
- 原因：这是 IM 系统常见且经过验证的可靠性方案。
- 结果：`msg_id` 成为 ACK、重发、日志、冲突检查的统一主键。

## ADR-006：会话内顺序由 `session_seq` 表达

- 状态：Accepted
- 决策：消息排序、已读游标推进、断线补偿全部基于每个会话独立递增的 `session_seq`。
- 原因：会话维度排序比全局时间戳或伪全局序列更符合聊天领域模型，也更易扩展。
- 结果：会话需要维护自己的消息高水位；客户端按会话维护同步 cursor。

## ADR-007：断线补偿使用游标，不使用时间戳

- 状态：Accepted
- 决策：客户端维护 `session_cursors` 与 `event_cursors`，服务端分别补偿遗漏消息和遗漏事件。
- 原因：时间戳不可靠，而消息新增与状态变更是两种不同语义，不能混用一个序列。
- 结果：补偿协议以双高水位游标为准；`session_seq` 负责新消息，`event_seq` 负责 `read`、`message_edit`、`message_recall`、`message_delete` 等事件。

## ADR-008：已读是成员游标，不是消息全局状态

- 状态：Accepted
- 决策：已读由 `SessionMember.last_read_seq` 表达，不把 `message.status` 改成全局 `read`。
- 原因：群聊里“一个人已读”与“所有人已读”不是同一个语义。
- 结果：私聊展示“对方已读”，群聊展示读人数或读者列表。

## ADR-009：`session_members` 是聊天权限与已读的真相来源

- 状态：Accepted
- 决策：会话成员关系、已读游标、会话权限统一以 `session_members` 为准。
- 原因：多套成员真相会导致写路径复杂、读路径修复、权限语义漂移。
- 结果：群组域模型只保留群业务信息；聊天权限必须落到统一会话成员模型。历史漂移只允许在启动期兼容迁移里一次性回填，不允许在运行时请求链路里偷偷修复。

## ADR-010：WebSocket Gateway 不能绕过 Service 执行业务变更

- 状态：Accepted
- 决策：撤回、编辑、删除、已读等 WS 命令必须复用 Service 规则。
- 原因：HTTP 与 WebSocket 是两个入口，但业务规则必须只有一份。
- 结果：任何“只在 WS 入口广播、不经 Service 校验”的实现都视为错误设计。

## ADR-011：本地 SQLite 是缓存与恢复层，不是业务真相层

- 状态：Accepted
- 决策：客户端使用 SQLite 保存消息、会话和同步高水位，但不把本地缓存当作权限和业务真相来源。
- 原因：离线缓存与业务权限是两套问题，混在一起会引发错误判断。
- 结果：本地缓存用于恢复、展示和重试，最终权限与业务规则仍以后端为准。

## ADR-012：消息流与状态事件流分离

- 状态：Accepted
- 决策：新消息使用 `session_seq` 排序与补偿，已读、编辑、撤回、删除使用独立 `event_seq` 事件流。
- 原因：两类数据的语义、回放方式、增长速度不同，混在一个序列里会让补偿协议和客户端状态机变复杂。
- 结果：重连同步返回 `history_messages` 与 `history_events` 两条载荷，客户端分别推进消息游标和事件游标。

## ADR-013：UI 设计系统以 CardWidget / Acrylic / Gallery 风格统一

- 状态：Accepted
- 决策：容器类业务组件统一收敛到 `CardWidget` 体系，Tooltip 使用 Acrylic 方案，QSS 组织方式参考 QFluentWidgets Gallery。
- 原因：减少样式漂移、降低重复封装成本，并让界面持续保持一致性。
- 结果：具体约束见 [ui_guidelines.md](./ui_guidelines.md)。

## ADR-014：正式扩展路径通过抽象边界实现，而不是到处埋兼容分支

- 状态：Accepted
- 决策：需要支持 Redis、对象存储、事件流时，应通过清晰接口或网关抽象演进，而不是把“未来扩展”散落在各层 if/else 中。
- 原因：低耦合系统的扩展点应当集中，不应污染业务主路径。
- 结果：优先收敛边界，再替换实现。

## ADR-015：好友请求以用户对为边界做幂等归一化

- 状态：Accepted
- 决策：好友请求禁止自加；同方向重复发送返回现有 `pending` 请求；若检测到反向 `pending` 请求，则直接接受现有请求并建立好友关系。
- 原因：这是社交产品里更成熟、常见且低摩擦的流程，能够避免同一对用户悬挂多条有效请求。
- 结果：发送好友请求接口可能返回 `pending`，也可能返回 `accepted`；客户端必须根据返回状态更新页面与提示文案，而不是假设一定是“已发送”。

## ADR-016：`HTTPClient` 只对内部相对路径继承应用鉴权，refresh 采用单飞

- 状态：Accepted
- 决策：`HTTPClient` 只把相对路径视为应用内部 API，请求才会继承应用 access token 与 401 refresh；绝对 URL 默认视为外部服务，不继承应用鉴权，也不会触发应用 refresh。并且 access token refresh 必须是 single-flight，同一轮并发 401 只允许一次刷新，其他请求等待同一结果。
- 原因：AI provider、Ollama、第三方 HTTP 服务不应误带应用 Bearer token，更不能把外部 401 解释成应用登录过期；single-flight refresh 则是成熟客户端里常见的并发控制方式。
- 结果：外部 provider 请求可以安全复用 `HTTPClient` transport；内部 API 401 不会因为并发请求而出现“一个刷新成功、其他请求直接失败”的竞态。

## ADR-017：实时连接与限流状态通过基础设施边界暴露

- 状态：Accepted
- 决策：Presence / fanout / 连接注册统一通过 `RealtimeHub` 暴露；HTTP 限流计数统一通过 `RateLimitStore` 暴露；当前默认实现仍可使用进程内内存结构。
- 原因：项目当前允许单机基线，但不能让业务代码直接绑定到“只能单进程工作”的具体容器实现。
- 结果：后续接入 Redis / PubSub / 共享限流存储时，Gateway 与 Router 只替换基础设施实现，不改业务规则与协议层。

## ADR-018：服务端时间统一使用 timezone-aware UTC，应用生命周期使用 lifespan

- 状态：Accepted
- 决策：服务端运行时与持久化默认使用 timezone-aware UTC 时间；禁止继续写入 `datetime.utcnow()`。应用启动初始化使用 FastAPI lifespan，而不是遗留 `on_event` 钩子。
- 原因：aware UTC 是 Python 与数据库交互里更成熟、常见且更少歧义的方案；lifespan 是 FastAPI 当前正式生命周期入口。
- 结果：时间比较统一通过 UTC helper 处理；启动初始化不再依赖已弃用 API。

## ADR-019：上传链路使用结构化异常与归一化 payload

- 状态：Accepted
- 决策：`HTTPClient.upload_file` 与普通 HTTP 请求一样，失败时抛结构化异常，不返回 `None`；`FileService` 负责把上传返回归一化为带 `url` 的正式 payload。Controller / Manager 再根据业务场景决定是提示错误、标记失败还是继续重试。
- 原因：上传失败语义如果靠 `None` / 空 dict 传播，会把协议错误、鉴权错误、网络错误、响应格式错误混成一类，既不成熟也不利于排错。
- 结果：上传链路的错误处理边界清晰，聊天附件、头像更新、失败重试可以共享同一套失败模型。

## ADR-020：`SessionManager` 通过 `SessionService` 访问远程会话 HTTP 能力

- 状态：Accepted
- 决策：会话详情拉取、会话列表刷新、未读统计拉取、私聊会话创建等远程 HTTP 能力统一收敛到 `SessionService`；`SessionManager` 只编排本地状态、缓存与 EventBus。
- 原因：Manager 直接依赖 `HTTPClient` 会让核心状态机和传输细节耦合，既不符合既有分层，也不利于后续测试和协议演进。
- 结果：会话远程访问边界与聊天消息远程访问边界保持一致；后续如果需要增加缓存策略、灰度接口、批量接口，只改 `SessionService` 即可。

## ADR-021：UI Controller 的远程操作统一通过 Service 边界发起

- 状态：Accepted
- 决策：`AuthController`、`ContactController`、`DiscoveryController` 等 UI controller 不直接发 HTTP 请求；认证、用户资料、联系人、发现页等远程能力分别收敛到 `AuthService`、`UserService`、`ContactService`、`DiscoveryService`。
- 原因：Controller 直接依赖 `HTTPClient` 会把视图编排、协议细节和远程接口耦在一起，既偏离分层设计，也让测试替身和后续接口演进变得困难。
- 结果：Controller 负责参数整理、结果归一化和交互编排；Service 负责远程 API；后续替换接口、增加缓存或灰度逻辑时，优先落到 Service，而不是回流到 Controller。

## ADR-022：`ConnectionManager` 通过 `AuthService` 读取认证状态

- 状态：Accepted
- 决策：`ConnectionManager` 构造带 token 的 WS URL、发送 WS `auth` 命令时，只通过 `AuthService` 读取当前 access token，不直接依赖 `HTTPClient`。
- 原因：连接状态机需要认证状态，但不应知道底层 HTTP client 的实现细节；通过 `AuthService` 读取认证状态，边界更稳定，也更利于测试替身与后续替换认证实现。
- 结果：客户端分层里 `HTTPClient` 只留在 Service / Network 层；实时连接层只依赖认证边界与 WebSocket transport。

## ADR-023：本地搜索查询通过 Storage 公共 API 暴露

- 状态：Accepted
- 决策：消息搜索等本地缓存查询通过 `Database.search_messages()` 这类公共 storage API 暴露；Manager 不直接写 SQL，也不调用 `Database._row_to_message()` 等私有 helper。
- 原因：Manager 直接依赖 SQL 语句和 storage 私有实现会让查询语义、SQLite 细节和业务编排耦在一起，也会让 LIKE 转义、索引优化和返回模型演进变得分散。
- 结果：搜索语义、SQLite 兼容和结果解码统一留在 storage 层；Manager 只处理业务编排与高亮、排序、选择等 UI 相关逻辑。


## ADR-024：Legacy Chat HTTP 兼容入口已移除

- 状态：Accepted
- 决策：历史 /api/chat/* HTTP 兼容入口不再保留；服务端只维护正式 /api/v1/* API 边界。
- 原因：当前客户端与测试基线已经收敛到正式 API，继续保留未使用的 legacy HTTP 入口只会制造文档和实现双重维护成本。
- 结果：不再通过重复 router 挂载制造 /api/api/chat/* 这类二次别名，也不再维护额外的 chat HTTP 兼容层。
## ADR-025：Legacy Chat HTTP Sync 不再单独保留

- 状态：Accepted
- 决策：历史 POST /api/chat/sync 兼容入口不再保留；断线补偿只通过正式实时链路的 session_cursors + event_cursors 语义维护。
- 原因：未启用的兼容同步入口会持续误导文档、测试夹具和调用方，对正式一致性模型没有额外价值。
- 结果：当前代码基线不再维护额外的 legacy HTTP sync 语义，也不再提供按 session_id 的兼容快照 fallback。
## ADR-026：聊天 WebSocket 正式入口收敛到 /ws

- 状态：Accepted
- 决策：/ws 作为唯一正式聊天 WebSocket 入口；历史 /ws/chat 兼容 alias 不再保留。
- 原因：成熟且低耦合的入口策略应该让真实可用入口与文档、测试完全一致，而不是长期保留未使用的兼容别名。
- 结果：客户端、测试与文档统一把 /ws 视为唯一 canonical endpoint；后续不再围绕 /ws/chat 维护兼容逻辑。
## ADR-027：配置读取使用运行时快照，不在类定义或路由装饰期冻结

- 状态：Accepted
- 决策：`Settings` 通过 `field(default_factory=...)` 在实例化时读取环境变量；应用入口通过 `create_app(settings)` 使用一份显式配置快照；需要随环境重载时，通过 `reload_settings()` 清理缓存后重建。
- 原因：把环境变量读取放在 dataclass 类定义期，或在路由装饰/模块导入期直接固化配置，会让测试、兼容开关和部署参数形成隐式冻结边界，难以验证也不利于后续退役 legacy 入口。
- 结果：配置边界变成“可重建的 settings snapshot + app factory + 动态依赖”；限流等需要读取当前配置的依赖不再在导入期固化具体数值。
## ADR-028：数据库 runtime 通过显式配置函数绑定，不在模块导入时冻结 engine

- 状态：Accepted
- 决策：数据库层提供 `configure_database(settings)` 与 `get_engine()`；`SessionLocal` 保持为稳定的 session factory，由 runtime 配置绑定具体 engine；`init_db(settings)` 也基于传入的 settings snapshot 运行。
- 原因：如果在模块导入时直接创建全局 engine，会让测试环境、app factory、自定义部署参数和后续多实例演进都受隐式冻结影响，数据库边界也会和应用配置边界错位。
- 结果：engine 生命周期与 app/config 生命周期对齐；调用方仍可复用稳定的 `SessionLocal` 接口，但底层绑定来自显式 runtime 配置，而不是导入副作用。
## ADR-029：认证、文件与限流依赖通过 app settings snapshot 读取配置

- 状态：Accepted
- 决策：HTTP Request 通过 `get_request_settings()` 从 `request.app.state.settings` 读取配置；WebSocket 通过 `get_websocket_settings()` 从 `websocket.app.state.settings` 读取配置；认证 token 解码、文件服务、动态限流都优先消费这份显式 snapshot。
- 原因：如果依赖在请求链路里回退到 `get_settings()` 全局缓存，就会让 app factory、自定义 secret、临时兼容开关和测试 app 之间再次出现隐式耦合。
- 结果：`create_app(settings)` 真正成为运行时配置边界；HTTP、WS、Service 和 dependency 共享同一份配置快照，而不是各自读取全局状态。

## ADR-030：文件与媒体存储通过显式 `MediaStorage` 边界与规范附件元数据建模

- 状态：Accepted
- 决策：服务端上传链路通过 `MediaStorage` 抽象承载，默认实现为 `LocalMediaStorage`；上传成功后统一返回 `storage_provider`、`storage_key`、`url`、`mime_type`、`original_name`、`size_bytes`、`checksum_sha256` 等规范媒体元数据。`files` 表保存存储真相；消息附件通过 `messages.extra` 持久化可展示、可回放的远端媒体元数据。`local_path`、`uploading` 等本地状态只允许存在于客户端。
- 原因：只存裸 `file_url`，或者把本地临时路径混入服务端消息，会让上传、历史回放、断线补偿和后续对象存储扩展全部耦在一起。
- 结果：客户端保留本地重试状态，服务端只保存 shareable metadata；后续接入 S3 / OSS / MinIO 时，只需要新增 `MediaStorage` 实现与公共 URL 策略，而不需要重写消息模型。

## ADR-031：生产环境传输链路统一收敛到 HTTPS / WSS

- 状态：Accepted
- 决策：生产环境中的后端 API 与实时链路统一通过 `HTTPS` 与 `WSS` 提供；开发环境可以保留 `HTTP` / `WS` 作为本地调试基线，但不作为正式部署默认值。
- 原因：认证 token、实时命令、通话 signaling 与文件上传都属于敏感链路，只靠应用层 token 而不收敛传输层安全是不完整的设计。
- 结果：客户端配置与部署文档都应把 TLS 视为正式基线；通话、E2EE 密钥交换与普通聊天消息在生产环境里都默认跑在 TLS 保护之上。

## ADR-032：1:1 语音 / 视频通话使用 WebRTC 媒体链路，信令复用聊天 WebSocket

- 状态：Accepted
- 决策：1:1 语音与视频通话的媒体层统一使用 WebRTC；来电、接听、拒绝、挂断、offer / answer / ICE 等 signaling 继续复用 AssistIM 现有 WebSocket 协议与鉴权链路。
- 原因：WebRTC + DTLS-SRTP 是音视频实时通信里成熟、常见且经过验证的方案；把 signaling 留在现有 WebSocket 中，可以最大限度复用已有会话权限、在线状态与实时基础设施。
- 结果：WebSocket 只承载通话信令，不传输音视频帧；服务端需补充 STUN / TURN 配置分发与活跃通话状态边界，客户端需引入 `CallManager` 统一维护通话状态机。

## ADR-033：私聊端到端加密采用设备模型与 Double Ratchet 路线，AI 会话保持服务端可见

- 状态：Accepted
- 决策：端到端加密首先只适用于 `private` 会话，并采用“设备身份密钥 + prekey + Double Ratchet”的成熟路线；`AI` 会话明确保持 `server_visible_ai`，不默认继承普通私聊的 E2EE 策略。
- 原因：私聊 E2EE 与 AI 会话的服务端可见明文需求天然冲突；把两者混成一套默认策略会同时破坏安全边界与 AI 产品能力。
- 结果：E2EE 私聊中服务端只路由密文与附件加密元数据，不依赖明文执行业务；AI 会话仍允许服务端与 provider 获取明文内容；群聊 E2EE 作为独立后续主题处理，不在本阶段与 1:1 私聊共用简化假设。

## ADR-034：E2EE 私聊的本地缓存优先持久化密文，数据库落盘加固通过 SQLCipher 演进

- 状态：Accepted
- 决策：启用 E2EE 的私聊在客户端本地优先持久化密文，解密后的明文默认仅保留在内存态或受保护的本地密钥缓存中；桌面端数据库落盘保护后续通过 `SQLite + SQLCipher` 演进，并使用系统安全存储保护 DB key。
- 原因：如果 E2EE 明文仍长期写回普通 SQLite，本地缓存会显著削弱端到端加密的实际收益；但 `SQLCipher` 接入涉及驱动、打包、迁移与 FTS 兼容，不适合作为第一阶段前置条件。
- 结果：E2EE 私聊的本地搜索能力允许在 MVP 阶段降级或关闭；数据库加固作为独立后续阶段推进，不阻塞通话与私聊 E2EE 主链路落地。当前实现已经先落地 `messages.is_encrypted` / `messages.encryption_scheme` 显式列，以及 `db_encryption_mode=plain|sqlcipher_pending` 的本地状态管理；同时 DB key 材料已迁移到数据库外部的 DPAPI 保护 sidecar 元数据，避免未来 SQLCipher 落地时出现“密钥与数据库互相依赖”的死锁设计。为后续真实驱动接入与打包验收，当前状态还会显式暴露 `requested_provider/runtime_provider/provider_match`，用来区分配置错误、缺驱动和已接入可用 runtime。

