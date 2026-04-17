# AI 代码修改规则

本文件只描述 AI 在 AssistIM 项目中改代码时必须额外遵守的执行规则。

本文件不重新定义系统架构、UI 设计系统或代码风格；相关内容分别以 [architecture.md](../architecture/architecture.md)、[backend_architecture.md](../architecture/backend_architecture.md)、[ui_guidelines.md](../ui/ui_guidelines.md)、[code_style.md](./code_style.md) 为准。

## 1. 文档优先级

AI 修改代码前，必须遵守以下优先级：

1. [design_decisions.md](../architecture/design_decisions.md)
2. [architecture.md](../architecture/architecture.md)
3. [backend_architecture.md](../architecture/backend_architecture.md)
4. [realtime_protocol.md](../protocols/realtime_protocol.md)
5. [ui_guidelines.md](../ui/ui_guidelines.md)
6. [code_style.md](./code_style.md)
7. [pitfalls.md](./pitfalls.md)

如果多个文档冲突，按上述顺序处理，不允许 AI 自行臆断覆盖高优先级文档。

## 2. 改动前检查

AI 在开始修改前，至少要先确认：

- 这次改动属于哪个业务域和哪条正式链路
- 当前规则由哪份主文档定义
- 是否会影响协议字段、缓存模型、权限模型、E2EE / 通话状态、UI 公共行为
- 是否需要同步补测试和文档

如果主文档已经定义了边界，AI 不得自创第二套实现方式。

## 3. 改动硬约束

AI 改代码时必须保持以下约束：

- 不跨层直连，不绕过正式边界
- 不把临时兼容写法扩散成长期设计
- 不把本地缓存当作服务端业务真相
- 不把 viewer-scoped / local-only 状态混进 shared payload
- 不用时间戳替代正式同步游标
- 不让 HTTP 与 WebSocket 分别维护两套业务规则
- 不把外部第三方 HTTP 请求混入应用内部鉴权链路

如果需要参考写法，使用 [code_style.md](./code_style.md) 里的推荐骨架；如果需要排查反模式，优先查看 [pitfalls.md](./pitfalls.md)。

## 4. 异常处理原则

AI 默认遵循 `let it crash`：

- 开发阶段不要为了压住报错而随手包一层宽泛 `try/except`
- 未知异常、协议不匹配、状态机错误、空值假设错误，应优先直接暴露，便于尽早修复
- 只有明确的边界层允许做异常转换或用户提示，例如应用入口、后台任务边界、HTTP / WebSocket 入口、最终 UI 反馈层
- 稳定后如果需要补异常处理，必须针对明确失败模式精确捕获，禁止使用“先吞掉再说”的兜底写法

## 5. 测试与文档要求

AI 生成涉及以下内容的改动时，必须同步补测试并更新文档：

- 协议字段
- ACK / 重试逻辑
- 断线补偿逻辑
- 已读模型
- 权限和安全逻辑
- UI 设计系统公共规范
- 任何主文档里明确承诺的边界或 contract

## 6. 明确拒绝的模式

AI 不得生成以下实现：

- UI 里直接 `await http_client.post(...)`
- Controller 里直接 `await http_client.get(...)` / `post(...)`
- Manager 里直接拼 SQL 或调用 storage 私有 helper
- Widget 里直接读写数据库
- Service 里发 Qt Signal 更新界面
- Repository 里写业务策略判断
- 通过复制一段旧逻辑来“修”另一条正式链路
- 让外部 AI / Ollama / 第三方 HTTP 请求误带应用 Bearer token，或在外部 401 上触发应用 refresh
