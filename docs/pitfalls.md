# 常见陷阱与反模式（Pitfalls）

本文档记录项目中需要避免的常见错误模式。

Cursor 在生成或修改代码时必须避免这些问题。

---

# 1 WebSocket 无限重连

问题：

当 WebSocket 连接断开时，如果没有区分 **主动断开** 与 **异常断开**，客户端可能进入无限重连循环。

错误示例：

WebSocket关闭
→ 抛出异常
→ reconnect
→ 再次关闭
→ 无限循环

正确设计：

客户端必须维护标志：

self._intentional_disconnect

重连逻辑：

如果 intentional_disconnect 为 true
→ 不执行重连

必须实现 **指数退避重连策略**。

---

# 2 asyncio Task 泄漏

问题：

如果使用 fire-and-forget 方式创建任务：

asyncio.create_task()

但没有保存引用。

任务可能：

* 无法取消
* 无法监控异常
* 在程序退出时产生警告

错误示例：

create_task(...)
不保存引用。

正确做法：

所有任务必须保存引用：

self._tasks.add(task)

并在关闭时：

cancel
await

---

# 3 UI线程阻塞

问题：

在 PySide6 + qasync 项目中，如果在 async 函数中执行 **阻塞操作**，会导致 UI 卡死。

常见原因：

AI推理
文件IO
数据库操作

错误示例：

await model.generate()

如果 generate 是同步函数。

正确做法：

使用：

loop.run_in_executor(...)

或使用真正的 async API。

---

# 4 WebSocket 消息静默丢失

问题：

如果发送消息使用 fire-and-forget：

asyncio.create_task(ws.send())

当连接断开时：

消息可能直接丢失。

UI 不会收到任何错误。

正确做法：

发送失败必须通知 UI。

例如：

message_send_failed(msg_id)

---

# 5 心跳机制误判断线

错误设计：

sleep(interval)
send_ping()
sleep(timeout)

这种顺序 sleep 容易造成误判。

如果网络延迟较高：

客户端可能错误判断连接断开。

正确方式：

使用：

asyncio.wait_for()

等待 pong。

---

# 6 aiohttp ClientSession 未关闭

问题：

如果 aiohttp.ClientSession 没有正确关闭：

程序退出时会出现：

Unclosed client session

正确设计：

在应用关闭时：

await session.close()

关闭时机：

QApplication.aboutToQuit

---

# 7 消息重复发送

问题：

如果消息没有唯一 ID：

在重连重发时可能产生重复消息。

正确设计：

每条消息必须包含：

msg_id

推荐：

UUID。

服务器根据 msg_id 去重。

---

# 8 UI 更新过于频繁（AI streaming）

问题：

AI streaming 如果每个 token 更新 UI：

界面会严重卡顿。

错误示例：

token
→ update UI

正确做法：

使用缓冲：

每 30ms 批量刷新 UI。

---

# 9 聊天会话状态分散

问题：

如果 UI 自己维护：

聊天列表
未读数
会话排序

会导致状态不同步。

正确设计：

所有会话状态由：

SessionManager

统一管理。

UI 只读取状态。

---

# 10 Token 过期导致连接异常

问题：

如果 WebSocket 连接使用过期 token：

服务器会直接关闭连接。

客户端可能不断 reconnect。

正确设计：

连接前检查 token 是否有效。

HTTP 请求 401 时：

refresh token
retry request

---

# 11 相对路径存储问题

问题：

使用：

Path("data/file")

如果用户从不同目录启动程序：

会生成多个 data 文件夹。

正确做法：

使用：

appdirs.user_data_dir()

---

# 12 直接抛出 Exception

问题：

如果代码直接：

raise Exception

UI 无法区分错误类型。

正确设计：

使用统一异常体系：

APIError
NetworkError
AuthExpiredError
ServerError

---

# 13 WebSocket 状态管理混乱

问题：

如果 WebSocket 没有明确状态：

可能出现：

重复连接
重复关闭
任务重复启动

正确设计：

WebSocketClient 必须维护状态机：

DISCONNECTED
CONNECTING
CONNECTED
RECONNECTING

---

# 14 未处理 asyncio CancelledError

问题：

在取消任务时，如果代码捕获所有异常：

except Exception

可能会吞掉 CancelledError。

导致任务无法正确退出。

正确设计：

必须显式处理：

CancelledError

并重新抛出。

---

# 15 程序关闭时仍有后台任务

问题：

如果程序关闭时还有未完成任务：

可能出现：

Task was destroyed but it is pending

正确做法：

关闭流程必须：

disconnect websocket
cancel tasks
await tasks
close session

# 16 UI线程更新问题

问题：

如果在非 UI 线程更新 Qt UI，
程序可能崩溃。

错误示例：

worker thread
→ update widget

正确方式：

UI 更新必须在 Qt 主线程执行。

推荐：

通过 EventBus 或 Signal 通知 UI。

# 17 WebSocket消息乱序

问题：

网络延迟可能导致消息顺序错乱。

解决方案：

使用 seq 字段排序。

客户端必须维护：

last_received_seq
