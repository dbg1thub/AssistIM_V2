# 推荐代码模板

本文档提供与当前架构一致的推荐代码骨架。模板是参考，不代表可以跳过 [architecture.md](./architecture.md) 与 [backend_architecture.md](./backend_architecture.md) 的边界约束。

## 1. Controller 模板

```python
class ChatController:
    """Receive UI input and delegate business actions to managers."""

    def __init__(self, message_manager: MessageManager):
        self._message_manager = message_manager

    async def send_text(self, session_id: str, content: str) -> ChatMessage:
        return await self._message_manager.send_message(session_id, content)
```

## 2. Manager 模板

```python
class MessageManager:
    """Own message state, orchestration and EventBus notifications."""

    def __init__(
        self,
        conn_manager: ConnectionManager,
        chat_service: ChatService,
        database: Database,
        event_bus: EventBus,
    ) -> None:
        self._conn_manager = conn_manager
        self._chat_service = chat_service
        self._db = database
        self._event_bus = event_bus

    async def send_message(self, session_id: str, content: str) -> ChatMessage:
        ...
```

## 3. Service 模板

```python
class ChatService:
    """Wrap backend HTTP APIs without owning UI state."""

    def __init__(self, http_client: HTTPClient) -> None:
        self._http = http_client

    async def fetch_history(self, session_id: str, limit: int = 50) -> list[MessageDTO]:
        payload = await self._http.get(
            "/sessions/{session_id}/messages",
            params={"limit": limit},
        )
        return [MessageDTO.from_dict(item) for item in payload]
```

## 4. Repository 模板

```python
class MessageRepository:
    """Persist and query messages; business policy stays in services."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, message_id: str) -> Message | None:
        return self.db.get(Message, message_id)
```

## 5. WebSocket Gateway 模板

```python
async def handle_chat_message(websocket: WebSocket, payload: dict) -> None:
    with SessionLocal() as db:
        service = MessageService(db)
        saved, created = service.send_ws_message(...)
    await send_ack(...)
    if created:
        await broadcast(...)
```

要求：

- Gateway 只做协议适配
- 业务规则走 Service
- ACK 与广播使用 Service 返回的权威结果

## 6. QFluentWidgets 卡片模板

```python
class ProfileSummaryCard(CardWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProfileSummaryCard")

        self.title_label = SubtitleLabel("Profile", self)
        self.edit_button = TransparentToolButton(FluentIcon.EDIT, self)
        self.edit_button.setToolTip("Edit profile")
        self.edit_button.installEventFilter(
            AcrylicToolTipFilter(self.edit_button)
        )
```

要求：

- 容器默认 `CardWidget`
- Tooltip 优先 Acrylic 方案
- 样式通过 objectName + 共享 QSS 管理

## 7. 同步游标模板

```python
sync_message = {
    "type": "sync_messages",
    "msg_id": f"sync_{int(time.time() * 1000)}",
    "data": {
        "session_cursors": session_cursors,
        "event_cursors": event_cursors,
    },
}
```

规则：

- 不用时间戳做正式补偿依据
- `session_cursors` 只表示新消息高水位
- `event_cursors` 只表示状态事件高水位
- 服务端应分别返回 `history_messages` 与 `history_events`

## 8. 事件对象模板

```python
@dataclass(slots=True)
class MessageReceivedEvent:
    message: ChatMessage
    session_id: str
```

推荐：

- EventBus 传 typed event 或清晰结构化 payload
- 不要在 UI 层到处猜 dict 里到底有哪些字段