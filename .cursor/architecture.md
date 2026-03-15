# AI增强即时通讯桌面客户端架构说明

## 1 项目简介

本项目是一个 AI增强即时通讯桌面客户端。

系统支持以下核心功能：

- 实时聊天
- 朋友圈
- 好友系统
- 聊天会话管理
- AI助手对话
- AI流式输出
- 聊天记录存储
- 断线消息同步

客户端采用 **分层架构 + 事件驱动设计**，实现高可维护性和低耦合。

---

# 2 技术栈

## 客户端

- PySide6
- PySide6-Fluent
- qasync
- asyncio
- aiohttp
- websockets

## 服务端

- FastAPI
- WebSocket
- REST API

---

# 3 客户端架构分层

客户端遵循五层架构设计：

UI Layer  
↓  
Manager Layer  
↓  
Service Layer  
↓  
Network Layer  
↓  
Protocol Layer  

各层职责如下。

---

## UI Layer

UI层负责：

- 界面展示
- 用户交互
- 监听事件并更新界面

UI层 **不直接访问 Network 或 Service**。

---

## Manager Layer

Manager层负责：

- 客户端状态管理
- 业务流程控制

主要模块：

SessionManager  
MessageManager  
ConnectionManager  

---

## Service Layer

Service层负责：

- 调用服务器 API
- AI请求
- 封装业务逻辑接口

---

## Network Layer

Network层负责：

- HTTP请求
- WebSocket连接
- 网络通信

---

## Protocol Layer

Protocol层负责：

- WebSocket消息结构
- 消息编码与解析

---

# 4 客户端目录结构

```
client/

core/
    日志
    配置
    事件总线

network/
    HTTP客户端
    WebSocket客户端

protocol/
    WebSocket消息协议

services/
    后端API调用
    AI服务

providers/
    AI模型提供者

managers/
    客户端状态管理

sync/
    消息同步模块

storage/
    本地数据库

models/
    数据结构定义

ui/
    PySide6界面
```

---

# 5 WebSocket通信流程

客户端启动流程：

客户端启动  
→ 建立WebSocket连接  
→ 发送认证消息  
→ 进入消息收发循环  

---

## 消息发送流程

UI  
→ MessageManager  
→ WebSocketClient  
→ Server  

---

## 消息接收流程

Server  
→ WebSocketClient  
→ MessageManager  
→ EventBus  
→ UI  

---

# 6 AI消息流程

AI消息支持 **流式输出**。

完整流程：

用户发送消息  
→ ChatService  
→ AIService  
→ Server  
→ AI流式返回  

服务器发送事件：

ai_stream_start  
ai_stream_chunk  
ai_stream_end  

客户端按 chunk 实时更新 UI。

---

# 7 消息同步机制

当客户端断线重连时：

客户端发送：

```
last_received_seq
```

服务器返回：

```
missing_messages
```

客户端补充缺失消息。

---

# 8 客户端状态管理

客户端状态由 Manager层统一维护。

主要模块：

SessionManager  
MessageManager  
ConnectionManager  

规则：

- UI 不直接修改状态
- UI 通过 Manager 调用业务逻辑
- UI 通过 EventBus 更新界面

---

# 9 事件系统

系统使用 EventBus 实现事件驱动架构。

常见事件：

message_received  
message_sent  
session_updated  
ai_stream_chunk  
connection_state_changed  

UI只监听事件。

---

## EventBus 示例实现

```
from collections import defaultdict

class EventBus:

    def __init__(self):
        self.listeners = defaultdict(list)

    def subscribe(self, event, callback):
        self.listeners[event].append(callback)

    def emit(self, event, data=None):
        for cb in self.listeners[event]:
            cb(data)

event_bus = EventBus()
```

---

# 10 本地存储

客户端使用 SQLite 存储数据。

存储内容：

- 聊天记录
- 会话信息
- 未发送消息

存储模块：

```
storage/
```

---

# 11 UI实现示例

下面给出一个简化聊天界面示例。

## ChatView

```
from PySide6.QtWidgets import QWidget, QVBoxLayout
from core.event_bus import event_bus

class ChatView(QWidget):

    def __init__(self, controller):
        super().__init__()

        self.controller = controller
        self.layout = QVBoxLayout(self)

        event_bus.subscribe("message_received", self.on_message_received)

    def send_message(self, text):
        self.controller.send_message(text)

    def on_message_received(self, message):
        print("收到消息:", message)
```

---

## ChatController

```
from managers.message_manager import message_manager

class ChatController:

    def send_message(self, text):
        message_manager.send_message(content=text)
```

---

## MessageManager

```
class MessageManager:

    async def send_message(self, content):

        msg = {
            "type": "chat_message",
            "content": content
        }

        await ws_client.send(msg)
```

---

# 12 UI开发完整流程示例

完整调用链：

```
用户输入
↓
ChatView
↓
ChatController
↓
MessageManager
↓
WebSocketClient
↓
Server
↓
EventBus
↓
UI更新
```

---

## 示例目录结构

```
ui/
    chat/
        chat_view.py
        chat_controller.py

managers/
    message_manager.py

network/
    websocket_client.py

core/
    event_bus.py
```

---

## ChatView 示例

```
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLineEdit
from core.event_bus import event_bus

class ChatView(QWidget):

    def __init__(self, controller):
        super().__init__()

        self.controller = controller

        self.layout = QVBoxLayout(self)

        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)

        self.input_box = QLineEdit()
        self.input_box.returnPressed.connect(self._on_send)

        self.layout.addWidget(self.chat_area)
        self.layout.addWidget(self.input_box)

        event_bus.subscribe("message_received", self._on_message_received)

    def _on_send(self):

        text = self.input_box.text()

        if not text:
            return

        self.controller.send_message(text)

        self.input_box.clear()

    def _on_message_received(self, message):

        self.chat_area.append(
            f"{message.sender_id}: {message.content}"
        )
```

---

# 13 AI流式UI更新示例

服务器发送：

```
ai_stream_start
ai_stream_chunk
ai_stream_end
```

客户端监听：

```
event_bus.subscribe("ai_stream_chunk", self.on_ai_chunk)
```

UI更新：

```
def on_ai_chunk(self, data):

    text = data["content"]

    self.ai_message.append(text)
```

---

# 14 系统整体数据流

```
用户输入
↓
UI
↓
Manager
↓
Network
↓
Server
↓
EventBus
↓
UI更新
```

---

# 15 UI开发规则（重要）

UI层必须遵守以下规则：

1. UI只负责界面展示  
2. UI不直接访问Network  
3. UI不直接访问Service  
4. UI通过Manager调用业务逻辑  
5. UI通过EventBus接收事件  

推荐模式：

```
UI → Controller → Manager → Network
```

禁止模式：

```
UI → WebSocket
UI → API
```

---

# 16 总结

本客户端采用：

- 分层架构
- 事件驱动
- WebSocket实时通信
- AI流式输出

核心设计目标：

- 模块解耦
- 易维护
- 易扩展
- 支持AI能力集成