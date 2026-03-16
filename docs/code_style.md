# 代码风格规范（Code Style）

本项目使用 Python 编写，包含 PySide6 GUI、FastAPI 服务通信、asyncio 异步编程以及 WebSocket 实时通信。

Cursor 在生成或修改代码时必须遵循以下代码风格。

---

# 1 Python 基础风格

遵循：

PEP8
PEP484（类型注解）

代码必须包含类型提示。

示例：

```python
def get_user(user_id: str) -> User:
    ...
```

禁止省略返回值类型。

---

# 2 命名规范

类名：

使用 PascalCase。

示例：

UserService
WebSocketClient
SessionManager

函数名：

使用 snake_case。

示例：

send_message
get_chat_history

变量名：

使用 snake_case。

示例：

user_id
message_list

常量：

使用 UPPER_CASE。

示例：

MAX_RECONNECT_DELAY

---

# 3 文件命名

Python 文件必须使用 snake_case。

示例：

http_client.py
websocket_client.py
session_manager.py

禁止：

CamelCase 文件名。

---

# 4 模块职责

每个模块必须职责单一。

禁止：

一个文件包含多个不相关类。

示例：

正确：

chat_service.py
contact_service.py

错误：

api_manager.py（包含所有 API）

---

# 5 类结构规范

类结构推荐顺序：

属性
构造函数
公共方法
私有方法

示例：

```python
class ExampleService:

    def __init__(self, http_client: HTTPClient):
        self.http = http_client

    async def get_data(self):
        return await self._fetch()

    async def _fetch(self):
        ...
```

私有方法必须使用 `_` 前缀。

---

# 6 asyncio 编码规范

所有网络或 IO 操作必须使用 async。

示例：

```python
async def send_message(self, msg: ChatMessage) -> None:
    ...
```

禁止：

同步网络请求。

示例：

requests.get()

---

# 7 asyncio Task 创建

禁止：

asyncio.ensure_future

必须：

asyncio.create_task

示例：

```python
task = asyncio.create_task(self._receive_loop())
```

任务必须保存引用。

---

# 8 asyncio 异常处理

必须正确处理 CancelledError。

示例：

```python
try:
    await task
except asyncio.CancelledError:
    raise
```

禁止吞掉 CancelledError。

---

# 9 Logging 规范

项目必须统一使用 logging。

禁止：

print()

示例：

```python
import logging

logger = logging.getLogger(__name__)

logger.info("WebSocket connected")
logger.error("Message send failed")
```

日志级别：

debug
info
warning
error

---

# 10 WebSocket 日志

WebSocket 客户端必须记录：

连接
断开
重连
心跳
发送消息
接收消息

日志示例：

```python
logger.info("WebSocket connected")
logger.warning("WebSocket reconnecting")
```

---

# 11 PySide6 信号规范

Signal 必须定义在类顶部。

示例：

```python
class WebSocketClient(QObject):

    connected = Signal()
    disconnected = Signal()
```

Signal 名称使用 snake_case。

---

# 12 UI 与业务逻辑分离

UI 文件只负责：

界面
用户交互

禁止：

UI 中直接调用 HTTP 或 WebSocket。

UI 必须通过：

Manager 或 EventBus。

---

# 13 数据模型规范

所有数据模型必须使用：

dataclass 或 pydantic。

示例：

```python
from dataclasses import dataclass

@dataclass
class ChatMessage:

    id: str
    sender_id: str
    content: str
    timestamp: int
```

禁止返回 dict。

---

# 14 API 返回值规范

API 方法返回 **模型对象**，而不是 dict。

示例：

```python
async def get_user(self, user_id: str) -> User:
    ...
```

---

# 15 异常规范

禁止：

raise Exception()

必须使用项目异常体系。

示例：

```python
raise NetworkError("Connection failed")
```

---

# 16 注释规范

复杂逻辑必须添加说明注释。

示例：

```python
# retry message if ack not received
```

禁止无意义注释。

---

# 17 Import 顺序

import 必须分组：

标准库
第三方库
项目模块

示例：

```python
import asyncio
import logging

from PySide6.QtCore import QObject

from client.models import ChatMessage
```

---

# 18 常量定义

所有常量集中定义。

示例：

```python
HEARTBEAT_INTERVAL = 30
RECONNECT_MAX_DELAY = 30
```

禁止魔法数字。

---

# 19 函数长度

函数应保持简短。

推荐：

不超过 40 行。

复杂逻辑应拆分私有函数。

---

# 20 类职责

类必须遵守单一职责原则。

示例：

AuthService
ChatService
ContactService

禁止：

AllInOneManager

---

# 21 typing 规范

推荐使用：

Optional
list[str]
dict[str, Any]

示例：

```python
def find_user(name: str) -> Optional[User]:
```

---

# 22 文档字符串

公共类和方法必须包含 docstring。

示例：

```python
async def send_message(self, msg: ChatMessage) -> None:
    """
    Send chat message via websocket.
    """
```

---

# 23 WebSocket 消息处理

消息处理函数必须拆分。

示例：

handle_message
handle_ack
handle_system

禁止在一个函数中处理所有消息。

---

# 24 AI streaming 代码

AI streaming 必须使用 generator 或 async generator。

示例：

```python
async def stream_chat(self):
    yield token
```

---

# 25 Cursor 代码生成原则

Cursor 生成代码时必须：

保持代码简洁
保证类型安全
遵循模块职责
避免重复逻辑
避免隐藏副作用

# 26 模块依赖规则

模块依赖必须遵循架构分层：

UI
↓
Manager
↓
Service
↓
Network
↓
Protocol

禁止跨层依赖。

错误示例：

UI → Network  
UI → Protocol  

Manager → Protocol  

正确示例：

UI → Manager  
Manager → Service  
Service → Network

# 27 全局对象规范

禁止在模块中创建业务单例：

错误：

message_manager = MessageManager()

正确：

通过依赖注入或应用初始化传递实例。

# 28 async 函数命名规范

async 函数必须表示异步行为。

推荐：

async def send_message(...)
async def fetch_history(...)

禁止：

async def do(...)
async def run(...)
