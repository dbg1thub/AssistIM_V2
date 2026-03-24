# 客户端总体架构说明

## 1. 适用范围

本文档描述客户端的目标架构、模块边界、协议约束、消息一致性模型、缓存策略与 UI 性能原则。

如果某段代码与本文档冲突，优先检查 [design_decisions.md](./design_decisions.md)；若 ADR 没有特殊说明，则按本文档收敛代码。

## 2. 总体设计目标

客户端架构的核心目标有五个：

- 明确边界：UI、业务、网络、存储、协议职责分开
- 可恢复：连接波动、ACK 超时、断线重连后状态可恢复
- 可演进：可以继续扩展更多事件类型、横向扩展、更多 AI provider
- 可测试：关键流程可以做单测、集成测试与回归测试
- 可维护：避免同一条规则散落在 UI、Manager、Service 多处重复实现

## 3. 分层模型

客户端采用如下层次关系：

```text
UI -> Controller -> Manager -> Service -> Network
                         \-> Storage
Manager -> EventBus -> UI
```

### 3.1 UI Layer

职责：

- 组件渲染
- 用户交互
- 视图状态展示
- 订阅 EventBus / Signal 并刷新界面

禁止：

- 直接请求 HTTP API
- 直接操作 WebSocket
- 直接读写数据库
- 直接维护业务真相

### 3.2 Controller Layer

职责：

- 承接 UI 输入
- 做轻量参数整理和交互编排
- 调用对应 Manager

Controller 不是业务层，不承担状态管理，不做网络访问。

正式要求：

- Controller 发起远程操作时，只调用对应 Service
- Controller 可以做轻量 payload 归一化与界面交互编排
- Controller 不直接依赖 `HTTPClient` 发请求

### 3.3 Manager Layer

职责：

- 管理客户端核心状态
- 编排消息、会话、连接、已读、缓存等业务流程
- 协调 Service、Storage、ConnectionManager
- 向 EventBus 发出状态变化通知

规则：

- 除 `ConnectionManager` 外，Manager 不应直接依赖底层 `WebSocketClient`
- 其他 Manager 与实时链路交互时，应通过 `ConnectionManager` 暴露的接口完成
- Manager 可以依赖 Storage，因为本地缓存属于客户端状态的一部分
- Manager 访问远程 HTTP 能力时，应通过对应 Service，而不是直接拿 `HTTPClient`
- `ConnectionManager` 读取 access token 时，也通过 `AuthService` 等认证边界完成，而不是直接拿 `HTTPClient`

### 3.4 Service Layer

职责：

- 封装后端 HTTP API
- 封装 AI Provider 调用
- 提供稳定的远程能力接口

规则：

- Service 不依赖 UI
- Service 不直接更新 UI
- Service 不持有界面状态
- Service 只关心远程请求，不负责本地会话状态真相
- `FileService` 返回规范媒体描述；消息附件发给服务端前必须剥离本地临时字段
- 典型例子包括 `AuthService`、`UserService`、`ChatService`、`FileService`、`SessionService`、`ContactService`、`DiscoveryService`

### 3.5 Network Layer

职责：

- HTTP 传输
- WebSocket 传输
- Token 附带、错误转换、连接生命周期等底层通信细节

规则：

- Network 层不包含业务判断
- Network 层不直接更新 UI
- Network 层不决定“某条消息是否应该重发、是否已读、是否属于当前会话”

### 3.6 Storage Layer

职责：

- SQLite 本地缓存
- App state 持久化
- 离线数据恢复所需的最小本地状态

Storage 由 Manager 驱动，不直接暴露给 UI。

规则：

- Manager 可以依赖 Storage，但应调用公开的 storage API
- Manager 不直接写 SQL，不依赖 storage 私有 helper
- 与 SQLite 方言相关的查询语义和结果解码统一留在 storage 层

## 4. 横切机制

### 4.1 EventBus

EventBus 是通知通道，不是命令总线。

推荐方向：

```text
Manager -> EventBus -> UI
```

禁止方向：

```text
UI -> EventBus -> Manager
Network -> EventBus -> UI（绕过 Manager）
```

### 4.2 Typed Models

客户端内部业务对象应使用 dataclass / typed model 表达，而不是在多个层之间直接传裸 dict。

- Network 可以收发 dict
- Service / Manager / UI 之间应尽快收敛为 typed model

## 5. HTTP 与 WebSocket 的职责划分

### 5.1 HTTP 负责

- 登录、注册、鉴权刷新
- 会话列表与历史记录拉取
- 文件上传
- 好友、群组、朋友圈等非实时业务
- 关键状态的最终持久化补写

### 5.2 WebSocket 负责

- 实时聊天消息
- ACK / delivered / read 事件
- typing、presence、`contact_refresh` 等实时通知
- 断线重连后的补偿同步

设计原则：

- HTTP 负责“最终查询和最终持久化”
- WebSocket 负责“低延迟实时通知”
- 同一业务不能在 UI 层同时直接拼接两套链路判断

## 6. WebSocket 消息协议

统一外层结构：

```json
{
  "type": "message_type",
  "seq": 0,
  "msg_id": "uuid-or-empty",
  "timestamp": 0,
  "data": {}
}
```

协议解释：

- `type`：消息类型
- `msg_id`：客户端命令幂等键；对会改变状态的客户端命令必须存在
- `timestamp`：发送时间或兼容字段，不作为断线补偿主依据
- `seq`：服务端回传的顺序字段；对状态事件表示 `event_seq`，对普通消息不能替代 `session_seq`
- `data`：业务负载

重要规则：

- 会话消息顺序使用 `data.session_seq`，不使用外层 `seq`
- 状态变更事件顺序使用独立 `event_seq`，在外层 `seq` 与 `data.event_seq` 中回传
- 断线补偿同时使用 `session_cursors` 与 `event_cursors`，不使用时间戳
- 不能用 `session_seq` 补偿 `read`、`message_edit`、`message_recall`、`message_delete` 等非消息事件

## 7. 消息一致性模型

### 7.1 `msg_id` 负责幂等

`msg_id` 是客户端命令 ID，用于：

- ACK 匹配
- 自动重发
- 服务端幂等去重
- 日志追踪

同一个逻辑消息在重发时必须复用同一个 `msg_id`。

### 7.2 `session_seq` 负责会话内顺序

服务端为每个会话分配单调递增的 `session_seq`。

用途：

- 会话内消息排序
- 已读游标推进
- 断线补偿高水位同步

### 7.3 已读模型使用游标，不写全局 `read` 状态

正式设计：

- `message.status` 只表示消息生命周期，例如 `sent`、`failed`、`edited`、`recalled`
- 已读状态由会话成员自己的 `last_read_seq` 表达
- 群聊展示为 `read_count / read_target_count`
- 私聊可显示“对方已读”

### 7.4 断线补偿使用双游标

客户端维护：

```json
{
  "session_cursors": {
    "session_id": 12
  },
  "event_cursors": {
    "session_id": 5
  }
}
```

重连后：

- 客户端发送 `session_cursors` 与 `event_cursors`
- 服务端返回 `history_messages`：各会话中 `session_seq > cursor` 的遗漏消息
- 服务端返回 `history_events`：各会话中 `event_seq > cursor` 的遗漏事件
- 客户端分别推进消息高水位与事件高水位，并按事件类型回放本地状态

当前纳入 `event_seq` 的事件包括：

- `read`
- `message_edit`
- `message_recall`
- `message_delete`

## 8. 本地缓存策略

客户端使用 SQLite 做本地缓存，主要保存：

- 会话列表
- 消息列表
- 本地 app_state
- 断线补偿高水位（消息游标 + 事件游标）

规则：

- 本地缓存是客户端状态恢复基础，不是业务权限判断依据
- 消息游标与事件游标都应持久化，不能仅靠内存
- 高水位不能只从“当前还存在的消息列表”临时推导，尤其不能试图从消息列表反推事件游标

## 9. UI 列表与性能原则

消息列表、会话列表、联系人列表必须遵守以下原则：

- 优先增量更新 `insert / remove / dataChanged`
- 非必要不使用 `beginResetModel()` / `modelReset()`
- 长列表不能依赖全量重建刷新
- AI 流式输出要做节流或批量刷新，不能每个 token 触发一次重绘
- Tooltip、Flyout、菜单、卡片样式应通过统一设计系统实现，见 [ui_guidelines.md](./ui_guidelines.md)

## 10. AI 会话架构

AI 能力通过 Service / Provider 体系接入，目标是：

- Provider 可替换
- 流式输出统一接口
- UI 不直接持有 provider 客户端
- AI 会话与普通 IM 会话共享尽可能一致的数据结构与视图层能力

## 11. 设计演进保留位

为了保持可扩展性，当前架构预留以下演进方向：

- 扩展更多 session event：例如 system / membership / pin / moderation events
- Presence / fanout 外置：当前通过 `RealtimeHub` 暴露，后续可从进程内实现扩展到 Redis / PubSub
- Rate limit state 外置：当前通过 `RateLimitStore` 暴露，后续可从进程内计数扩展到共享存储
- 文件存储切换：从本地目录扩展到对象存储
- 更细粒度的 UI 设计系统：在不破坏 CardWidget / Acrylic / Tooltip 统一规范的前提下演进



