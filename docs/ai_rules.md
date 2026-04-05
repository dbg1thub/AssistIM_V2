# AI 代码生成规则

本文件用于约束 Cursor / Copilot / ChatGPT 等 AI 在 AssistIM 项目中生成或修改代码时的行为。

## 1. 文档优先级

AI 修改代码前，必须遵守以下优先级：

1. [design_decisions.md](./design_decisions.md)
2. [architecture.md](./architecture.md)
3. [backend_architecture.md](./backend_architecture.md)
4. [ui_guidelines.md](./ui_guidelines.md)
5. [code_style.md](./code_style.md)
6. [templates.md](./templates.md)
7. [pitfalls.md](./pitfalls.md)

如果多个文档冲突，按上述顺序处理，不允许 AI 自行臆断覆盖高优先级文档。

## 2. 分层硬约束

AI 生成代码时必须保持以下边界：

- UI 不直接访问 HTTP / WebSocket / SQLite
- Controller 不直接访问 Network / Database
- Manager 不直接访问 `HTTPClient`，远程 HTTP 能力先收敛到 Service
- `ConnectionManager` 读取认证状态时也走 `AuthService`，不要直接取 `HTTPClient.access_token`
- Service 不直接更新 UI
- Gateway / Router 不直接写业务策略
- Repository 不承担策略层职责

## 3. 实时链路硬约束

AI 不得生成以下错误设计：

- 用时间戳代替正式断线补偿游标
- 把群聊消息写成全局 `read`
- 用新的 `msg_id` 重发同一逻辑消息
- 在 WebSocket 入口绕过 Service 直接广播状态变更
- 用 `max(session_seq) + 1` 分配会话消息序号

## 4. 网络边界硬约束

AI 不得把外部 provider / 第三方 HTTP 请求混入应用内部鉴权链路。

必须遵守：

- 内部后端 API 使用相对路径，通过统一 `HTTPClient` 继承应用鉴权
- 外部 AI / Ollama / 第三方服务使用绝对 URL，默认不继承应用 access token，也不触发应用 refresh
- 并发 401 场景下只能存在一条 refresh in-flight，其他请求等待同一 refresh 结果
- Network / Service 层失败使用结构化异常传播，不使用 `None` / 空 dict 猜测失败语义

## 4.1 异常处理原则

AI 默认遵循 `let it crash`：

- 开发初期不要为了压住报错而随手包一层宽泛 `try/except`
- 未知异常、协议不匹配、状态机错误、空值假设错误，应优先直接暴露，便于尽早修复
- 只有明确的边界层允许做异常转换或用户提示，例如应用入口、后台任务边界、HTTP / WebSocket 入口、最终 UI 反馈层
- 稳定后如果需要补异常处理，必须针对明确失败模式精确捕获，禁止使用“先吞掉再说”的兜底写法

## 5. UI 设计系统硬约束

AI 在新增 UI 时必须优先遵守：

- 有现成 QFluentWidgets 组件时先复用
- 容器类业务 widget 默认使用 `CardWidget`
- Tooltip 默认使用 Acrylic 方案，并通过 Filter 机制设置
- 页面样式复用共享 QSS / token，不到处内联 setStyleSheet

## 6. 数据模型硬约束

AI 不应在内部业务层大量传裸 dict 充当正式业务对象。

推荐：

- 消息附件 extra 只持有 shareable 远端媒体元数据；`local_path`、`uploading` 等本地状态不能发到服务端
- dataclass
- pydantic schema
- 明确的 typed payload model

## 7. 测试与文档硬约束

AI 生成涉及以下内容的改动时，必须同步补测试并更新文档：

- 协议字段
- ACK / 重试逻辑
- 断线补偿逻辑
- 已读模型
- 权限和安全逻辑
- UI 设计系统公共规范

## 8. 拒绝生成的典型模式

- UI 里直接 `await http_client.post(...)`
- Controller 里直接 `await http_client.get(...)` / `post(...)`
- Manager 里直接 `await db.execute(...)` 或调用 `db._row_to_message(...)`
- Widget 里直接读写数据库
- Service 里发 Qt Signal 更新界面
- Repository 里实现“如果你是发送者就允许撤回”之类的业务规则
- 为现成 QFluentWidgets 组件重新写一套基础按钮、卡片、tooltip
- 让 OpenAI / Ollama / 第三方 HTTP 请求误带应用 Bearer token，或在外部 401 上触发应用 refresh

