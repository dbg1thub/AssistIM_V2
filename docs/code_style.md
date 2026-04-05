# 代码风格规范

本文档只描述代码形态、工程实践、async 规范、日志与异常规范，不重复定义架构分层。分层与设计边界请查看：

- [architecture.md](./architecture.md)
- [backend_architecture.md](./backend_architecture.md)
- [ui_guidelines.md](./ui_guidelines.md)

## 1. 通用要求

- 使用 Python 3 的现代写法与类型提示
- 默认遵循 PEP 8、PEP 484、PEP 604、PEP 681 等常见工程实践
- 内部业务对象优先使用 dataclass / typed model，而不是裸 dict
- 模块职责单一，函数和类名表达真实语义

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
- 只有在明确的边界层才适合做异常转换或兜底：例如进程入口、任务调度边界、HTTP / WebSocket 边界、面向用户的最终提示边界
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
- Tooltip、容器、样式遵循 [ui_guidelines.md](./ui_guidelines.md)
- 不在 widget 内直接写 HTTP / WebSocket / SQLite 调用

## 9. Repository / Service / Manager 代码风格要求

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
