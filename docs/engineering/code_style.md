# 工程实践与代码风格规范

本文档描述工程实践、代码风格、async / 异常 / 日志要求，以及与当前架构一致的推荐代码骨架。

本文档不重复定义系统架构边界。分层与设计边界请查看：

- [architecture.md](../architecture/architecture.md)
- [backend_architecture.md](../architecture/backend_architecture.md)
- [ui_guidelines.md](../ui/ui_guidelines.md)

## 1. 通用要求

- 使用 Python 3 的现代写法与类型提示
- 默认遵循 PEP 8、PEP 484、PEP 604、PEP 681 等常见工程实践
- 内部业务对象优先使用 dataclass / typed model，而不是裸 dict
- 模块职责单一，函数和类名表达真实语义
- 示例代码只能作为推荐骨架，不能绕过主架构文档

## 2. 命名规范

- 类名：`PascalCase`
- 函数、方法、变量、模块：`snake_case`
- 常量：`UPPER_CASE`
- 私有辅助函数 / 方法：使用 `_` 前缀

避免模糊命名：

- `data_manager`
- `common_utils`
- `api_manager`
- `handle_data`

## 3. 类型提示规范

所有公共函数、关键私有函数、跨层接口都应显式写出类型提示。

示例：

```python
async def send_message(self, session_id: str, content: str) -> ChatMessage:
    ...
```

以下情况必须有明确返回类型：

- Service 接口
- Manager 接口
- Repository 接口
- WebSocket / HTTP 关键入口

## 4. 文件与类组织

推荐顺序：

1. imports
2. 常量 / dataclass / enum
3. 主类
4. 辅助私有函数

类内部推荐顺序：

1. 类常量
2. `__init__`
3. property
4. 公共方法
5. 私有方法

## 5. async 与任务管理规范

- 网络、磁盘、数据库等 IO 必须使用 async 接口
- 创建后台任务使用 `asyncio.create_task`
- 所有长期任务都必须保存引用并在关闭时取消 / await
- 必须正确处理 `CancelledError`

禁止：

- `asyncio.ensure_future`
- fire-and-forget 但不保存任务引用
- 在 async 函数里执行长时间阻塞操作

## 6. 错误与异常规范

错误必须使用明确异常类型，不允许到处直接抛裸 `Exception`。

要求：

- 外层统一转换为可处理的错误对象
- UI 能区分网络错误、鉴权错误、服务端错误、业务错误
- Service / Network 层要保留足够的错误语义

开发阶段额外原则：

- 默认遵循 `let it crash`
- 开发初期不要为了“看起来稳定”而随手加大面积 `try/except`
- 如果错误意味着真实 bug、状态不一致、协议不满足预期，就应当直接暴露并尽快修复，而不是吞掉异常后继续运行
- 只有在明确的边界层才适合做异常转换或兜底，例如进程入口、任务调度边界、HTTP / WebSocket 边界、面向用户的最终提示边界
- 项目进入稳定阶段后，才针对已经识别清楚的失败模式补充精确、收敛的 `try/except`，禁止用宽泛捕获掩盖未知错误

## 7. Logging 规范

项目统一使用 `logging`，禁止在正式代码中使用 `print()` 代替日志。

关键链路日志至少应覆盖：

- WebSocket 连接 / 断开 / 重连
- HTTP 请求失败
- Token 刷新
- 消息发送 / ACK / 重发 / 失败
- 同步补偿与游标推进

日志字段尽量带上：

- `user_id`
- `session_id`
- `message_id` / `msg_id`

## 8. PySide6 / QFluentWidgets 规范

- UI 类只负责视图与交互，不写业务流程
- Signal 使用清晰语义命名
- Tooltip、容器、样式遵循 [ui_guidelines.md](../ui/ui_guidelines.md)
- 不在 widget 内直接写 HTTP / WebSocket / SQLite 调用

## 9. Repository / Service / Manager 工程约束

### 9.1 Repository

- 只做数据访问
- 不做策略判断
- 方法名直接表达查询 / 更新语义

### 9.2 Service

- 只暴露稳定业务接口
- 不混入 UI / Widget 语义
- 不直接更新 EventBus 到 UI

### 9.3 Manager

- 管理状态与流程
- 不直接拼接视图逻辑
- 需要发事件时统一通过 EventBus / Signal

## 10. 测试规范

以下改动至少补一类测试：

- 协议变更
- ACK / 重试变更
- 已读模型变更
- 同步游标变更
- 权限与安全逻辑变更
- UI 设计系统公共行为变更

## 11. 文档更新规范

改动以下内容时，必须同一提交更新文档：

- 架构边界
- 协议字段
- 关键设计决策
- UI 设计系统规则
- AI 生成约束

## 12. 推荐代码骨架

以下模板只提供推荐结构，不替代架构说明。

### 12.1 Controller 模板

```python
class ChatController:
    """Receive UI input and delegate business actions to managers."""

    def __init__(self, message_manager: MessageManager):
        self._message_manager = message_manager

    async def send_text(self, session_id: str, content: str) -> ChatMessage:
        return await self._message_manager.send_message(session_id, content)
```

### 12.2 Manager 模板

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

### 12.3 Service 模板

```python
class ChatService:
    """Wrap backend HTTP APIs without owning UI state."""

    def __init__(self, http_client: HTTPClient) -> None:
        self._http = http_client

    async def fetch_history(self, session_id: str, limit: int = 50) -> list[MessageDTO]:
        payload = await self._http.get(
            f"/sessions/{session_id}/messages",
            params={"limit": limit},
        )
        return [MessageDTO.from_dict(item) for item in payload]
```

### 12.4 Repository 模板

```python
class MessageRepository:
    """Persist and query messages; business policy stays in services."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, message_id: str) -> Message | None:
        return self.db.get(Message, message_id)
```

### 12.5 WebSocket Gateway 模板

```python
async def handle_chat_message(websocket: WebSocket, payload: dict) -> None:
    with SessionLocal() as db:
        service = MessageService(db)
        dispatch = service.send_websocket_message(...)
    await send_ack(...)
    if dispatch["created"]:
        await broadcast(...)
```

要求：

- Gateway 只做协议适配
- 业务规则走 Service
- ACK 与广播使用 Service 返回的权威结果

### 12.6 QFluentWidgets 卡片模板

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

### 12.7 同步游标模板

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

### 12.8 事件对象模板

```python
@dataclass(slots=True)
class MessageReceivedEvent:
    message: ChatMessage
    session_id: str
```

推荐：

- EventBus 传 typed event 或清晰结构化 payload
- 不要在 UI 层到处猜 dict 里到底有哪些字段
