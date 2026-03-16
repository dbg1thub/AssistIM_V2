# 设计决策说明（Design Decisions）

本文档记录项目中的关键架构决策以及设计原因。

Cursor 在生成或修改代码时必须尊重这些设计决策，避免破坏已有架构。

---

# 1 使用 PySide6 + qasync

决策：

客户端使用 **PySide6 + qasync + asyncio** 作为 GUI 与异步框架。

原因：

* PySide6 提供成熟稳定的 Qt GUI 组件
* PySide6-Fluent 提供现代化 UI 风格
* qasync 可以将 asyncio 事件循环集成到 Qt 主事件循环中
* 避免传统 PyQt 多线程编程复杂度

设计原则：

* 所有 async 协程运行在 Qt 主线程
* 不使用 QThread 处理网络逻辑
* UI 与网络通过 async + signal 通信

禁止：

在 async 代码中使用 QMetaObject.invokeMethod。

---

# 2 使用 WebSocket 实现实时通信

决策：

客户端使用 **WebSocket** 进行即时通讯。

原因：

* 即时通讯需要实时双向通信
* WebSocket 延迟低
* 可以减少 HTTP 轮询

通信模式：

客户端保持长连接：

connect
→ auth
→ receive_loop

消息通过统一协议发送。

---

# 3 使用 FastAPI 作为后端

决策：

服务端框架为 **FastAPI**。

原因：

* 原生支持 async
* 性能优秀
* 与 WebSocket 集成良好
* 类型提示支持完善

系统通信方式：

HTTPS API：

登录
注册
好友系统
聊天记录

WebSocket：

实时聊天
系统通知
AI streaming

---

# 4 使用统一消息协议

决策：

所有 WebSocket 消息使用统一结构：

```
{
  "type": "message_type",
  "seq": 123,
  "msg_id": "uuid",
  "timestamp": 123456,
  "data": {}
}
```

原因：

* 统一协议方便扩展
* 支持消息确认机制
* 支持断线同步
* 支持日志追踪

---

# 5 使用 ACK 确认机制

决策：

所有消息必须支持 **ACK 确认**。

流程：

客户端发送
→ 服务器处理
→ 返回 message_ack

原因：

* 防止消息丢失
* 支持重发机制
* 提升 IM 可靠性

客户端维护：

pending_messages

---

# 6 使用消息序列号同步

决策：

客户端维护：

last_received_seq

重连时：

客户端发送 last_received_seq
服务器返回遗漏消息。

原因：

* 支持断线恢复
* 避免消息丢失

---

# 7 使用 EventBus 实现 UI 解耦

决策：

UI 与业务逻辑之间使用 **EventBus**。

原因：

* 减少 UI 与 Service 的耦合
* 便于扩展
* 便于测试

通信方式：

Service
→ EventBus
→ UI

UI 不直接调用 Service。

---

# 8 使用 Manager 层管理客户端状态

决策：

客户端状态统一由 Manager 管理。

核心 Manager：

SessionManager
MessageManager
ConnectionManager

原因：

* 避免状态分散
* UI 不直接管理状态
* 保证数据一致性

---

# 9 使用 SQLite 作为本地存储

决策：

客户端使用 **SQLite** 存储本地数据。

存储内容：

聊天记录
会话列表
未发送消息

原因：

* 支持离线访问
* 提高启动速度
* 减少服务器请求

---

# 10 AI 采用流式输出

决策：

AI 响应使用 **流式输出（Streaming）**。

消息类型：

ai_stream_start
ai_stream_chunk
ai_stream_end

原因：

* 提升用户体验
* 减少等待时间
* 支持长文本输出

UI 实时追加 token。

---

# 11 AI 推理不阻塞 UI

决策：

AI 推理必须运行在后台线程。

实现方式：

asyncio.run_in_executor

原因：

* 防止 UI 卡顿
* 保证界面流畅

禁止：

在 UI coroutine 中执行阻塞 AI 推理。

---

# 12 WebSocket 重连策略

决策：

WebSocket 使用 **指数退避重连策略**。

示例：

1s
2s
4s
8s
16s
最大 30s

原因：

* 防止重连风暴
* 提升系统稳定性

---

# 13 Token 自动刷新

决策：

客户端支持：

access_token
refresh_token

流程：

HTTP 401
→ refresh token
→ retry request

原因：

* 避免用户频繁重新登录
* 提升用户体验

---

# 14 Token 安全存储

决策：

Token 不允许明文存储。

使用：

keyring 或系统凭据管理器。

原因：

* 防止凭证泄露
* 提升安全性

---

# 15 事件驱动 UI

决策：

UI 更新必须由事件驱动。

事件示例：

message_received
message_sent
session_updated
ai_stream_chunk
connection_state_changed

原因：

* 降低模块耦合
* 提高可维护性

---

# 16 异常体系

决策：

项目使用统一异常体系：

APIError
NetworkError
AuthExpiredError
ServerError

原因：

* UI 可以精确处理错误
* 方便调试

禁止：

直接抛出 Exception。

---

# 17 日志策略

决策：

所有网络行为必须记录日志：

WebSocket连接
WebSocket断开
重连
消息发送
消息接收
Token刷新

日志必须包含：

user_id
session_id
message_id

原因：

* 方便调试 IM 系统问题
* 方便定位消息问题

# 18 消息ID设计

所有聊天消息必须包含唯一 msg_id。

推荐：

UUIDv4

示例：

{
  "msg_id": "550e8400-e29b-41d4-a716-446655440000"
}

原因：

- 支持 ACK
- 防止重复消息
- 支持断线重发
- 支持日志追踪