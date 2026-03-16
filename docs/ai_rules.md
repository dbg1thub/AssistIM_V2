# AI 代码生成规则（AI Rules）

本文件用于约束 AI（Cursor / Copilot / ChatGPT）生成代码时遵守项目架构。

AI 在生成或修改代码时必须遵守以下规则。

违反这些规则的代码 **必须被拒绝**。

---

# 1 架构分层规则（最重要）

系统采用严格分层架构：

UI  
↓  
Controller  
↓  
Manager  
↓  
Service  
↓  
Network  
↓  
Protocol  

AI 生成代码时 **必须遵守依赖方向**。

允许依赖：

UI → Controller  
Controller → Manager  
Manager → Service  
Service → Network  

禁止依赖：

UI → Network  
UI → Protocol  
UI → Service  

Controller → Network  

Manager → UI  

Network → Manager  

---

# 2 UI 层规则

UI 只负责：

- 界面显示
- 用户输入
- 监听事件

UI **禁止做以下事情**：

❌ 调用 HTTP API  
❌ 调用 WebSocket  
❌ 操作数据库  
❌ 管理业务状态  

UI 只能：

```
UI → Controller
```

UI 更新必须来自：

- EventBus
- Qt Signal

---

# 3 Controller 层规则

Controller 负责：

- 接收 UI 输入
- 调用 Manager
- 进行简单参数处理

Controller **不负责业务逻辑**。

禁止：

❌ 调用 Network  
❌ 调用 HTTP  
❌ 调用数据库  

Controller 只允许：

```
Controller → Manager
```

---

# 4 Manager 层规则

Manager 是客户端业务核心层。

职责：

- 管理客户端状态
- 业务流程控制
- 调用 Service 或 Network

Manager 可以：

```
Manager → Service
Manager → Network
```

Manager 不允许：

❌ 依赖 UI  
❌ 更新 UI  

UI 更新必须通过：

EventBus

---

# 5 Service 层规则

Service 负责：

- HTTP API
- AI 请求
- 后端业务接口

Service 不允许：

❌ 依赖 UI  
❌ 依赖 Manager  

Service 只允许：

```
Service → Network
```

---

# 6 Network 层规则

Network 层负责：

- HTTP Client
- WebSocket Client

Network 层：

❌ 不允许包含业务逻辑  
❌ 不允许更新 UI  

Network 只负责：

- 网络通信
- 数据发送
- 数据接收

---

# 7 EventBus 使用规则

UI 与业务逻辑之间 **必须通过 EventBus 解耦**。

允许：

```
Manager → EventBus → UI
Service → EventBus → UI
```

禁止：

```
Manager → UI
Service → UI
Network → UI
```

---

# 8 数据模型规则

AI 生成的数据结构 **必须使用 dataclass 或 pydantic**。

禁止：

```
dict 作为业务对象
```

正确示例：

```
@dataclass
class ChatMessage:

    id: str
    sender_id: str
    content: str
    timestamp: int
```

---

# 9 WebSocket 消息规则

所有 WebSocket 消息必须遵循统一结构：

```
{
  "type": "message_type",
  "seq": 123,
  "msg_id": "uuid",
  "timestamp": 123456,
  "data": {}
}
```

禁止：

- 随意定义 WebSocket 数据结构
- 直接发送字符串

---

# 10 asyncio 规则

所有网络 IO 必须使用 async。

禁止：

```
requests.get()
time.sleep()
```

必须：

```
aiohttp
asyncio
await
```

创建任务必须使用：

```
asyncio.create_task()
```

---

# 11 UI 性能规则

AI streaming 更新 UI 时：

禁止：

每个 token 更新 UI。

必须：

使用缓冲刷新 UI。

推荐：

```
30ms 批量刷新
```

---

# 12 日志规则

AI 生成代码时必须包含日志。

网络行为必须记录：

- WebSocket连接
- WebSocket断开
- 消息发送
- 消息接收

示例：

```
logger.info("WebSocket connected")
logger.info("Message sent", extra={"msg_id": msg_id})
```

---

# 13 异常规则

禁止：

```
raise Exception()
```

必须使用项目异常体系：

```
APIError
NetworkError
AuthExpiredError
ServerError
```

---

# 14 任务管理规则

所有 asyncio task 必须：

- 保存引用
- 支持取消
- 程序退出时清理

禁止：

fire-and-forget 任务。

---

# 15 AI 代码生成原则

AI 生成代码必须满足：

- 遵守架构分层
- 避免跨层依赖
- 使用类型注解
- 避免全局状态
- 避免重复逻辑

---

# 16 当规则冲突时

优先级：

1 architecture.md  
2 design_decisions.md  
3 ai_rules.md  
4 code_style.md  
5 templates.md  

AI 必须遵守高优先级规则。