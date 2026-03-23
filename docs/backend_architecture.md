# 服务端架构说明

## 1. 适用范围

本文档描述服务端的目标架构、部署基线、领域模型、一致性规则、实时链路、存储与演进方式。

本文档强调两件事：

- 先定义成熟、常见、可扩展、低耦合的目标设计
- 再让代码逐步向目标设计收敛，而不是把历史实现直接等同于最终架构

## 2. 部署基线与演进路径

### 2.1 当前可运行基线

当前项目优先保证单机可运行，因此可以接受以下基线：

- 单个 FastAPI 应用进程
- 单个 SQL 数据库
- 本地文件上传目录
- 进程内 `RealtimeHub` 默认实现（连接注册表 / presence / fanout）
- 进程内 `RateLimitStore` 默认实现
- 测试环境可使用 SQLite，生产目标优先 PostgreSQL

### 2.2 目标演进路径

后续扩展时，服务端应沿着以下方向演进，而不破坏上层接口：

- Presence / Fanout 通过 `RealtimeHub` 从进程内实现外置到 Redis / PubSub
- 文件存储从本地目录切换到对象存储
- 后台任务从进程内执行演进到 worker / queue
- 历史兼容脚本逐步收敛为标准 migration 流程

原则：

- 先通过边界抽象保证可替换性
- 不为了“可能扩容”过早拆分微服务
- 不把横向扩展需求写死到业务层判断里

## 3. 分层结构

服务端采用如下分层：

```text
HTTP Router / WebSocket Gateway
            -> Service
            -> Repository
            -> Database
```

### 3.1 Router / Gateway 层

职责：

- HTTP 请求校验
- WebSocket 鉴权、收包、发包
- 错误转换
- 协议适配

禁止：

- 在 Router / Gateway 内实现业务规则
- 在 WebSocket handler 中直接绕过 Service 修改数据库
- 在多个入口分别复制权限判断逻辑

### 3.2 Service 层

职责：

- 业务规则
- 权限校验
- 跨聚合协调
- 一致性约束
- 序列化为 API / WS 输出模型

Service 是真正的业务边界，HTTP 与 WebSocket 都必须复用同一套 Service 规则。

### 3.3 Repository 层

职责：

- 数据读写封装
- 持久化查询
- 最小必要的数据库事务辅助

规则：

- Repository 不做业务策略裁决
- Repository 不应成为“第二套 Service”
- 跨领域一致性由 Service 协调，不由多个 Repository 各自猜测

## 4. 核心领域模型

### 4.1 ChatSession

会话是聊天的核心聚合根，负责承载：

- 会话基本信息
- 会话类型（私聊 / 群聊 / AI 等）
- 会话消息高水位 `last_message_seq`
- 会话事件高水位 `last_event_seq`

### 4.2 SessionMember

`session_members` 是会话成员关系的正式真相来源。

它负责表达：

- 谁属于该会话
- 成员何时加入
- 成员自己的已读游标 `last_read_seq`
- 成员自己的 `last_read_message_id / last_read_at`

设计要求：

- 权限判断以 `session_members` 为准
- 群组域模型不能绕开 `session_members` 单独作为聊天权限真相
- 运行时不应依赖“读路径修复成员关系”来维持正常业务
- 历史漂移由启动期兼容迁移一次性回填，不在业务请求中隐式修复

### 4.3 Group / Friend / Moment / File

这些模型分别承载各自业务域，但都不应破坏聊天主链路的一致性边界。

示例：

- Group 表达群组业务元数据
- Friend / FriendRequest 表达好友关系与申请历史
- File 表达上传文件元数据
- Moment 表达朋友圈内容

好友请求规则：

- 同一对用户同一时刻最多只有一个有效 `pending` 请求
- 同方向重复发送按幂等处理，返回现有请求
- 发现反向 `pending` 请求时，直接接受已有请求并建立好友关系
- 已经是好友时不再创建新请求

## 5. 消息一致性规则

### 5.1 `msg_id` 是命令幂等键

所有会改变消息状态的客户端命令，都必须带唯一 `msg_id`。

用途：

- ACK 匹配
- 客户端自动重发
- 服务端幂等去重
- 日志追踪

规则：

- 同一逻辑消息重发时复用相同 `msg_id`
- 服务端必须拒绝“同一 `msg_id` 对应不同逻辑消息”的冲突写入

### 5.2 `session_seq` 是会话内消息顺序号

服务端必须为每个会话分配单调递增的 `session_seq`。

规则：

- 不能再用 `max(session_seq) + 1` 这种并发不安全写法
- 正式设计应使用会话级高水位原子递增
- `session_seq` 只表示会话内消息顺序，不表示全局事件顺序

### 5.3 已读模型使用成员游标

正式设计：

- 已读是“成员读到哪一条”的游标模型
- 群聊不能把一条消息写成全局 `read`
- `message.status` 不表达群聊已读
- `read_count`、`read_target_count` 基于成员游标计算

### 5.4 断线补偿使用 `session_cursors + event_cursors`

服务端补偿同步规则：

- 输入：客户端的 `session_cursors` 与 `event_cursors`
- 输出：`history_messages` 中返回 `session_seq > cursor` 的遗漏消息
- 输出：`history_events` 中返回 `event_seq > cursor` 的遗漏事件
- 不以时间戳作为正式补偿依据

规则：

- `session_seq` 只补偿新消息
- `event_seq` 补偿 `read`、`message_edit`、`message_recall`、`message_delete` 等状态变更
- 事件流与消息流分离，避免把不同语义强行塞进同一个序列

### 5.5 SessionEvent 是独立事件流

当前事件流承载：

- `read`
- `message_edit`
- `message_recall`
- `message_delete`

设计要求：

- 事件按会话维度单调递增 `event_seq`
- 事件可独立于消息回放
- 删除消息后仍允许回放关联事件，因此事件记录不能依赖消息实体继续存在

## 6. WebSocket 实时链路

### 6.1 连接阶段

- 连接建立
- 通过 token 认证
- 绑定用户与连接
- 进入消息收发循环

### 6.2 发送阶段

- 客户端发送带 `msg_id` 的命令
- 服务端执行业务校验与落库
- 返回 `message_ack`
- 对其他会话成员做广播

### 6.3 状态变更阶段

消息撤回、编辑、删除、已读等行为必须遵守：

- 先走 Service 规则
- 再广播结果
- 不允许在 Gateway 内仅做“会话成员校验后直接广播”

## 7. Presence 与广播设计

当前基线可以使用进程内连接管理器，但架构上应保证它是可替换的。

正式设计原则：

- Presence 状态缓存与 WS 连接管理解耦
- 广播接口抽象为可替换的 fanout 通道
- 不让业务 Service 直接依赖某种具体广播存储实现

## 8. 数据库与迁移策略

### 8.1 生产目标

- PostgreSQL 是生产数据库优先选择
- SQLAlchemy 是 ORM 边界
- Alembic 是正式 migration 机制

### 8.2 测试与兼容

- SQLite 可作为测试与轻量本地运行基线
- `schema_compat.py` 只用于历史漂移与测试启动兼容，不应替代正式 migration 策略

## 9. 文件与媒体设计

### 9.1 存储边界

- 服务端上传能力通过 `MediaStorage` 抽象承载，默认实现为 `LocalMediaStorage`
- `MediaStorage` 负责真正的落盘或对象存储写入，并返回统一 `StoredMediaObject`
- `StoredMediaObject` 至少包含：`storage_provider`、`storage_key`、`public_url`、`original_name`、`content_type`、`size_bytes`、`checksum_sha256`
- `media_public_base_url` 负责把存储 key 映射为正式公开 URL；本地磁盘与未来对象存储都遵循同一接口

### 9.2 服务端持久化模型

- `files` 表保存存储真相，包括 `storage_provider`、`storage_key`、`file_url`、`file_type`、`size_bytes`、`checksum_sha256`
- 上传接口和文件列表接口统一返回规范媒体元数据，而不是只返回一个 `file_url` 字符串
- 消息附件通过 `messages.extra` 持久化远端附件元数据，确保历史消息、断线补偿和兼容 sync 都能回放同一份附件信息
- 服务端不持久化 `local_path`、`uploading` 之类客户端临时状态

### 9.3 客户端职责边界

- `FileService` 负责把上传响应归一化成稳定媒体描述，不把后端字段差异泄漏给 Controller / Manager
- `build_attachment_extra()` 用于构建本地附件状态，可带 `local_path`、`uploading` 等仅客户端可见字段
- `sanitize_outbound_message_extra()` 在真正发消息前移除本地临时字段，只把 shareable metadata 发给服务端
- 重试时如果远端 URL 尚不存在，客户端先重传媒体，再复用同一 `msg_id` 发送消息

### 9.4 可扩展性要求

- 不允许把“当前是本地磁盘存储”写死到消息协议和业务层判断里
- 新增对象存储实现时，应优先新增 `MediaStorage` 子类，而不是修改 Controller / Manager / Router 逻辑
- 上传返回字段和消息附件字段必须保持兼容，避免文件列表、聊天消息、历史回放各自发明不同格式

## 10. 可观测性与测试

关键链路必须可验证：

- WS 认证
- `msg_id` 幂等
- ACK / 重发
- `session_seq` 分配
- 已读游标推进
- 断线补偿（消息游标 + 事件游标）
- 编辑 / 撤回 / 删除权限

日志至少应能关联：

- `user_id`
- `session_id`
- `message_id` / `msg_id`
- endpoint / ws event


## 11. 兼容入口策略

- 正式 API 入口保持 /api/v1/* 与 /api/* 两层。
- 历史 chat HTTP 兼容入口只保留单一显式前缀 /api/chat/*。
- 不通过重复 router 挂载制造 /api/api/chat/* 这类二次别名。
- POST /api/chat/sync 优先复用 session_cursors + event_cursors，返回 {messages, events}；仅对极旧调用方保留 session_id 快照 fallback。
- /ws 是正式聊天 WebSocket 入口；历史 /ws/chat 只作为显式兼容 alias 保留，并可通过配置单独关闭。
## 12. 配置加载策略

- 服务端配置通过 `Settings` 运行时快照读取，不在 dataclass 类定义时冻结环境变量。
- 应用入口通过 `create_app(settings)` 组装，兼容开关和部署参数由 app factory 显式决定。
- 数据库 engine 通过 `configure_database(settings)` 在 runtime 绑定；`SessionLocal` 作为稳定工厂保留，但不在模块导入时提前冻结具体连接。
- 需要读取当前限流阈值等运行时配置的依赖，应通过动态 dependency 获取，不在路由装饰期固化具体数值。

