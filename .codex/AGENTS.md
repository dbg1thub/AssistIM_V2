# Cursor 规则 —— AI 即时通讯桌面客户端（工业级）

## 项目背景

本项目是一个 **AI增强的即时通讯桌面应用**。

在修改代码前，请先阅读以下文档：

- docs/architecture.md
- docs/design_decisions.md
- docs/code_style.md
- docs/pitfalls.md
- docs/templates.md
- docs/project_context.md
- docs/ai_rules.md

客户端技术栈：

* PySide6
* PySide6-Fluent
* qasync
* asyncio
* aiohttp
* websockets

服务端技术栈：

* FastAPI
* WebSocket
* REST API

系统功能包括：

* 实时聊天
* 好友系统
* 会话管理
* AI 助手对话
* 聊天记录
* AI 流式输出
* 断线消息同步

Cursor 在生成或修改代码时 **必须遵守以下规则**。

---

# 1 架构设计规则

项目必须遵循 **清晰分层架构（Clean Architecture）**。

推荐目录结构：

```id="m5ym4o"
client/
│
├── core/
│   ├── event_bus.py
│   ├── config.py
│   ├── logger.py
│   └── lifecycle.py
│
├── network/
│   ├── http_client.py
│   └── websocket_client.py
│
├── protocol/
│   ├── message_types.py
│   └── message_protocol.py
│
├── services/
│   ├── auth_service.py
│   ├── chat_service.py
│   ├── contact_service.py
│   └── ai_service.py
│
├── providers/
│   ├── openai_provider.py
│   ├── ollama_provider.py
│   └── local_llm_provider.py
│
├── managers/
│   ├── session_manager.py
│   ├── message_manager.py
│   └── connection_manager.py
│
├── sync/
│   ├── message_sync.py
│   └── session_sync.py
│
├── storage/
│   ├── database.py
│   ├── message_repo.py
│   └── session_repo.py
│
├── models/
│   ├── user.py
│   ├── message.py
│   ├── session.py
│   └── ai_message.py
│
├── ui/
│   ├── windows/
│   └── widgets/
│
└── main.py
```

规则：

* UI 不允许直接调用 HTTP API
* UI 不允许直接操作 WebSocket
* Service 不允许依赖 UI
* Manager 负责客户端状态管理

禁止创建 **God Object（万能类）**。

---

# 2 PySide6 + qasync 规则

qasync 会把 asyncio 事件循环挂载到 Qt 主线程。

因此 **async 协程本身就在 Qt 主线程运行**。

禁止在 async 函数中使用：

```id="mt4y0c"
QMetaObject.invokeMethod(...)
```

正确做法：

```id="7yqpy4"
self.signal.emit()
```

只有在真正跨线程时才使用 invokeMethod。

---

# 3 asyncio 任务管理

所有 asyncio Task **必须有明确归属和生命周期**。

禁止：

```id="rcm94r"
asyncio.ensure_future(...)
```

必须：

```id="qrdhr9"
self._task = asyncio.create_task(...)
```

组件必须维护：

```id="82smqf"
self._tasks: set[asyncio.Task]
```

所有任务必须：

* 可取消
* 在程序关闭时 await
* 出现异常时可被监控

所有循环任务必须支持取消。

---

# 4 WebSocket 状态机

WebSocket 客户端必须实现明确状态机。

状态包括：

DISCONNECTED（未连接）
CONNECTING（连接中）
CONNECTED（已连接）
RECONNECTING（重连中）

状态转换：

DISCONNECTED → CONNECTING
CONNECTING → CONNECTED
CONNECTED → DISCONNECTED
CONNECTED → RECONNECTING
RECONNECTING → CONNECTED

UI 只能监听状态变化，不能直接控制状态。

---

# 5 WebSocket 任务结构

WebSocket 客户端必须拆分为多个协程任务：

connect_loop
receive_loop
heartbeat_loop
reconnect_loop

任务必须保存引用：

```id="0bdfgr"
self._connect_task
self._receive_task
self._heartbeat_task
```

断开连接时必须：

* cancel 所有任务
* await 任务结束

---

# 6 主动断开与异常断开

必须区分：

主动断开
网络异常断开

需要标志位：

```id="v5q1dz"
self._intentional_disconnect
```

重连逻辑：

```id="nmxrpa"
if not intentional_disconnect:
    reconnect
```

用户主动断开 **绝不能自动重连**。

---

# 7 WebSocket 消息协议

所有 WebSocket 消息必须使用统一结构：

```json id="q8x19e"
{
  "type": "message_type",
  "seq": 123,
  "msg_id": "uuid",
  "timestamp": 123456,
  "data": {}
}
```

字段含义：

type：消息类型
seq：消息序号
msg_id：唯一消息ID
timestamp：时间戳
data：消息内容

---

# 8 消息ID设计

每条消息必须拥有唯一 ID。

推荐：

UUID4 或 UUIDv7。

用途：

* 消息去重
* 离线同步
* 防止重复发送

---

# 9 消息可靠性

即时通讯系统必须实现 **ACK确认机制**。

流程：

客户端发送 → 服务端接收 → 返回 ACK。

ACK 消息：

message_ack

客户端必须维护：

```id="9omjvd"
pending_messages
```

如果超时未收到 ACK：

重新发送消息。

---

# 10 消息同步

客户端重连后必须同步丢失消息。

流程：

1 重连 WebSocket
2 发送 last_received_seq
3 服务端返回遗漏消息

模块：

```id="zv3v03"
sync/message_sync.py
```

用途：

* 补偿丢失消息
* 恢复会话状态

---

# 11 心跳机制

禁止使用顺序 sleep 实现心跳。

禁止：

```id="ry41hr"
sleep(interval)
send_ping()
sleep(timeout)
```

正确方式：

```id="uzlozl"
await asyncio.wait_for(...)
```

心跳必须能快速检测断线。

---

# 12 重连策略

必须使用 **指数退避算法**。

示例：

1s → 2s → 4s → 8s → 16s → 最大 30s

防止重连风暴。

---

# 13 WebSocket 发送安全

发送消息失败不能静默。

失败必须通知 UI。

示例：

```id="zc82g9"
message_send_failed.emit(msg_id)
```

---

# 14 HTTP客户端规则

所有 HTTP 请求必须统一走：

```id="9zrrn8"
_request()
```

该方法必须处理：

* HTTP状态码
* JSON解析
* 业务code
* token注入
* token刷新
* 异常转换

API方法只返回：

```id="pfscsq"
data
```

---

# 15 Token 生命周期

客户端必须支持：

access_token
refresh_token

当 HTTP 返回 401 时：

1 自动刷新 token
2 重试原请求
3 刷新失败则强制退出登录

UI 不应处理 token 刷新。

---

# 16 Token 安全

禁止明文保存 token。

禁止：

```id="j6ydt4"
auth.json
```

推荐使用：

```id="ykhrz9"
keyring
```

或系统凭据管理器。

---

# 17 文件路径规则

禁止使用硬编码相对路径。

推荐使用：

```id="c6j4qc"
appdirs
```

将数据存储在系统标准目录。

---

# 18 AI 流式输出架构

AI响应必须支持 **流式输出**。

消息类型：

ai_stream_start
ai_stream_chunk
ai_stream_end

流程：

start → 逐步追加 token → end

UI 必须支持实时显示。

---

# 19 AI UI性能优化

禁止每个 token 更新 UI。

建议：

每 **30–50ms 批量更新一次 UI**。

防止界面卡顿。

---

# 20 AI 推理安全

AI推理绝不能阻塞 UI。

禁止：

```id="4c5y82"
await model.generate()
```

正确方式：

```id="d1zzvo"
loop.run_in_executor(...)
```

---

# 21 本地存储

客户端必须使用本地数据库缓存。

推荐：

```id="3cfq92"
SQLite
```

用途：

* 聊天记录
* 未发送消息
* 会话缓存

---

# 22 会话管理

必须实现 **SessionManager**。

职责：

* 会话列表
* 未读计数
* 会话排序

UI 不允许直接管理这些状态。

---

# 23 事件驱动 UI

UI 通信必须使用 **事件机制**。

推荐：

EventBus。

事件示例：

message_received
message_sent
session_updated
friend_added
ai_stream_chunk
connection_state_changed

UI 只监听事件。

---

# 24 异常体系

禁止抛出裸 Exception。

必须定义异常体系：

APIError
NetworkError
AuthExpiredError
ServerError

抛出异常必须保留原始堆栈：

```id="gyy9m5"
raise NetworkError(...) from e
```

---

# 25 日志规则

必须记录：

* WebSocket 连接
* 断开
* 重连
* 心跳超时
* 消息发送
* 消息接收
* Token刷新

日志必须包含：

user_id
session_id
message_id

---

# 26 应用关闭流程

程序关闭必须执行：

1 断开 WebSocket
2 cancel 所有任务
3 关闭 aiohttp session
4 flush 本地存储

绑定：

```id="lps8r6"
QApplication.aboutToQuit
```

---

# 27 Cursor 代码生成规则

Cursor 生成代码时必须优先保证：

* async安全
* 任务生命周期清晰
* 服务层解耦
* 类型安全
* 状态可观测

避免生成：

* 巨型管理类
* fire-and-forget任务
* 阻塞代码
* 重复API逻辑
* 隐式副作用

---

# 28 Cursor 修改代码规则

修改现有代码时：

必须：

* 保持架构不被破坏
* 不引入阻塞代码
* 不产生循环依赖
* 不破坏 async 生命周期
* 不增加隐藏后台任务
