# 项目背景（Project Context）

本项目是一个 **AI增强即时通讯桌面客户端**。

客户端允许用户：

* 与其他用户聊天
* 与 AI 助手聊天
* 实时接收消息
* 查看聊天历史
* 使用 AI 进行流式对话

客户端采用 **桌面 GUI + WebSocket 实时通信 + HTTPS API** 的架构。

---

# 技术栈

客户端技术栈：

Python
PySide6（桌面 GUI）
asyncio（异步 IO）
aiohttp（HTTP 客户端）
WebSocket（实时通信）
SQLite（本地存储）

服务器技术栈：

FastAPI
WebSocket
REST API

---

# 客户端架构

客户端采用严格分层架构：

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

每一层职责如下：

UI
负责界面显示与用户输入。

Controller
连接 UI 与业务逻辑。

Manager
负责客户端核心业务逻辑和状态管理。

Service
封装 HTTP API 或 AI 服务调用。

Network
负责网络通信（HTTP / WebSocket）。

Protocol
定义 WebSocket 消息结构。

---

# 核心模块

客户端主要模块：

UI 模块

ui/

负责：

* 主窗口
* 聊天窗口
* 消息显示
* 用户输入

---

Controller 模块

controllers/

负责：

* 接收 UI 输入
* 调用 Manager

---

Manager 模块

managers/

负责客户端核心逻辑：

ConnectionManager

管理 WebSocket 连接与重连。

MessageManager

负责：

发送消息
接收消息
处理 ACK
触发 UI 更新事件。

SessionManager

负责：

聊天会话
当前会话状态
未读消息

---

Service 模块

services/

ChatService

封装聊天相关 HTTP API。

AIService

封装 AI 对话接口。

支持 **流式 AI 输出**。

---

Network 模块

network/

HTTPClient

封装 aiohttp。

WebSocketClient

负责：

建立 WebSocket 连接
发送消息
接收消息
自动重连
心跳检测

---

Events 模块

events/

EventBus

用于解耦 UI 与业务逻辑。

Manager 通过 EventBus 向 UI 发送事件。

例如：

MessageReceivedEvent
MessageSentEvent
ConnectionStateEvent
AIStreamChunkEvent

---

Models 模块

models/

定义客户端数据模型：

ChatMessage
User
Session

全部使用 dataclass。

---

Protocol 模块

protocol/

定义 WebSocket 消息结构。

标准格式：

{
"type": "message_type",
"seq": 123,
"msg_id": "uuid",
"timestamp": 123456,
"data": {}
}

---

Storage 模块

storage/

使用 SQLite 保存：

聊天记录
会话列表
未发送消息

---

Core 模块

core/

提供基础设施：

config
logging

---

# 消息发送流程

用户发送消息时流程：

UI
↓
ChatController
↓
MessageManager
↓
WebSocketClient
↓
Server

Server 返回 ACK。

MessageManager 更新消息状态。

UI 通过 EventBus 更新。

---

# 消息接收流程

服务器发送消息：

Server
↓
WebSocketClient
↓
MessageManager
↓
EventBus
↓
UI

UI 更新聊天窗口。

---

# AI 对话流程

用户发送 AI 消息：

UI
↓
ChatController
↓
MessageManager
↓
AIService
↓
AI Provider

AI 通过 **streaming 返回 token**。

AIService 触发：

AIStreamChunkEvent

UI 实时更新聊天内容。

---

# 设计原则

客户端遵循以下原则：

1 分层架构
2 UI 与业务逻辑解耦
3 使用 EventBus 进行事件通信
4 网络层不包含业务逻辑
5 所有网络 IO 使用 async

---

# AI 代码生成要求

当 AI 生成代码时必须：

遵守 architecture.md
遵守 ai_rules.md
遵守 code_style.md

并保持：

模块职责清晰
避免跨层依赖
代码结构可维护
