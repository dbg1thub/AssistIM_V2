# 代码模板规范

Cursor 在生成代码时应尽量遵循以下模板结构。

---

# Service 模板

```python
class ExampleService:

    def __init__(self, http_client):
        self.http = http_client

    async def example_api(self, param: str):
        data = await self.http._request(
            "GET",
            "/example",
            params={"param": param},
        )
        return data
```

规则：

Service 不允许依赖 UI。

---

# WebSocket Client 模板

```python
class WebSocketClient(QObject):

    connected = Signal()
    disconnected = Signal()

    def __init__(self):
        super().__init__()

        self._tasks = set()
        self._intentional_disconnect = False

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def _receive_loop(self):
        pass

    async def _heartbeat_loop(self):
        pass
```

规则：

必须保存任务引用。

---

# Manager 模板

```python
class SessionManager:

    def __init__(self):
        self.sessions = {}

    def add_session(self, session):
        self.sessions[session.id] = session
```

规则：

Manager负责状态管理。

---

# Model 模板

推荐使用 dataclass：

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

# EventBus 模板

```python
class EventBus:

    def __init__(self):
        self._listeners = {}

    def emit(self, event, data):
        pass

    def subscribe(self, event, callback):
        pass
```

UI通过事件通信。

---

# HTTP Client 模板

```python
class HTTPClient:

    async def _request(self, method, path, **kwargs):

        response = await self.session.request(method, path, **kwargs)

        data = await response.json()

        if data["code"] != 0:
            raise APIError(data["message"])

        return data["data"]
```

---

# AI Provider 模板

```python
class AIProvider:

    async def stream_chat(self, messages):
        yield "token"
```

AI必须支持流式输出。

---

# WebSocket Message 模板

```python
{
  "type": "message",
  "seq": 123,
  "msg_id": "uuid",
  "timestamp": 123456,
  "data": {}
}
```

---

# 异常模板

```python
class APIError(Exception):
    pass


class NetworkError(APIError):
    pass
```

禁止直接使用 Exception。

# Controller 模板

```python
class ChatController:

    def __init__(self, message_manager):
        self.message_manager = message_manager

    def send_message(self, text: str):

        self.message_manager.send_message(
            content=text
        )
```

规则：

Controller 只负责：

UI输入

调用Manager

# Event 数据结构

推荐使用 dataclass 定义事件。

```python
from dataclasses import dataclass

@dataclass
class MessageReceivedEvent:

    message_id: str
    sender_id: str
    content: str
```

UI 接收事件对象，而不是 dict。
