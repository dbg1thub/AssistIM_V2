# Code Review 指南

## 1. 目标

本指南用于统一 AssistIM 的 review 方式，避免 review 只停留在“代码写法”层面，而忽略：

- 是否偏离正式文档
- 业务链路是否闭环
- 权威真相是否唯一
- 实时事件、补偿、缓存、跨页状态是否一致
- E2EE / 通话 / 本地数据库这类高风险链路是否仍可恢复、可诊断

本指南定义的是 review 方法，不记录具体问题。当前问题台账见：

- [review_findings_grouped.md](./review_findings_grouped.md)
- [review_findings.md](./review_findings.md)

## 2. Review 基本原则

- 先看正式设计，再看代码现状，不把历史实现自动当成目标设计
- 先看业务链路和权威真相，再看局部写法
- 先找根因，再记单点问题；同一根因不要拆成几十条重复 finding
- 先分清“已确认 bug”“设计风险”“待验证项”
- 结论尽量落到具体模块、接口、字段和状态机，不写空泛意见

正式文档优先级：

1. [design_decisions.md](./design_decisions.md)
2. [architecture.md](./architecture.md)
3. [backend_architecture.md](./backend_architecture.md)
4. [realtime_protocol.md](./realtime_protocol.md)
5. [ui_guidelines.md](./ui_guidelines.md)
6. [code_style.md](./code_style.md)
7. [pitfalls.md](./pitfalls.md)

## 3. Review 方法

当前仓库不适合继续按“扫到一个文件就记一个问题”的方式 review。更稳妥的方式是：

1. 先选一条业务链路
2. 找它的正式入口
3. 找它的权威真相
4. 找它的实时事件和断线补偿
5. 找它的失败分支、重试、跨页状态和跨设备行为
6. 审完一整条链路再切下一条

无论审哪条链路，都建议固定回答这 10 个问题：

1. 产品语义是什么
2. 正式入口是什么
3. 权威数据源是什么
4. 本地缓存和内存态各承担什么职责
5. 实时事件怎么传播
6. 断线补偿怎么补
7. 失败和重试怎么收口
8. 幂等与并发是否成立
9. 跨页 / 跨设备是否一致
10. 测试和日志是否足够

## 4. 推荐检查顺序

### 4.1 认证与运行时生命周期

这条通常是全局前置条件，建议最先看。

核心问题：

- 是否真的存在 per-account authenticated runtime
- login / restore / relogin / logout / force logout 是否属于同一状态机
- HTTP auth-loss、WS auth-loss、主窗口退出是否都走统一 teardown
- 后台任务、数据库、WebSocket、controller / manager / service singleton 是否会跟着 runtime 一起退休

重点模块：

- `client/main.py`
- `client/ui/controllers/auth_controller.py`
- `client/network/http_client.py`
- `client/managers/connection_manager.py`

这个项目特有的高风险点：

- 旧 runtime 在切账号或强制下线后是否还残留后台任务
- token refresh、WS auth、main window close 是否会打出分叉语义
- startup preflight、DB encryption self-check、authenticated warmup 是否会污染后续主流程

### 4.2 会话生命周期

核心问题：

- 删除会话、本地隐藏、重新打开、联系人页发消息，是否是同一套语义
- authoritative session snapshot 与本地缓存、搜索结果、当前页面状态是否一致
- 会话从快照里消失后，是否还能被旁路 fetch、warmup、旧缓存复活
- group / direct 的名字、成员预览、badge、call capability 是否来自同一份权威数据

重点模块：

- `client/managers/session_manager.py`
- `client/ui/windows/chat_interface.py`
- `client/ui/widgets/session_panel.py`
- `client/managers/search_manager.py`
- `server/app/services/session_service.py`

这个项目特有的高风险点：

- 本地删除后 reopen 语义是否会影响对端
- hidden tombstone、history cutoff、remote refresh 三者是否冲突
- group session 的 `members`、preview sender、display name 是否会退回 uuid

### 4.3 消息主链路

核心问题：

- 发送、ACK、重试、history sync、edit / recall / delete / read 是否仍是一套正式模型
- `msg_id`、`session_seq`、`event_seq` 是否仍按正式一致性规则工作
- optimistic local state 与服务端权威状态冲突时谁覆盖谁
- typing、contact_refresh、profile update 这类 side event 是否进入了正确边界

重点模块：

- `client/managers/message_manager.py`
- `client/managers/connection_manager.py`
- `server/app/websocket/chat_ws.py`
- `server/app/services/message_service.py`
- `server/app/api/v1/messages.py`

这个项目特有的高风险点：

- `history_messages` 和 `history_events` 是否仍严格分离
- 是否还有入口绕过 `Service` 直接广播 mutation
- 消息附件、本地上传状态、服务端正式附件元数据是否被混成一份 payload

### 4.4 联系人与群主链路

核心问题：

- friend / request / group 三条分支是否共享 authoritative refresh 语义
- 群成员变化、群角色变化、联系人变化是否进入正式实时模型
- 搜索结果、联系人缓存、会话侧成员快照是否会互相漂移

重点模块：

- `client/ui/windows/contact_interface.py`
- `client/ui/controllers/contact_controller.py`
- `client/managers/search_manager.py`
- `server/app/api/v1/friends.py`
- `server/app/api/v1/groups.py`
- `server/app/services/group_service.py`

这个项目特有的高风险点：

- `contact_refresh` 是否只是提示，还是 authoritative invalidation
- group 生命周期变化是否真的会收口到会话侧
- 群资料和群成员更新是否仍夹带 viewer-scoped 字段

### 4.5 E2EE 链路

建议放在消息链路之后看，不要把“消息一致性问题”和“加密问题”混在一起。

核心问题：

- `encryption_mode` 是否以后端 authoritative session snapshot 为准
- trust state、identity review、history recovery、reprovision 是否是同一套安全模型
- 本地缓存是否仍优先持久化密文，而不是把明文写成第二真相
- attachment E2EE 是否和文本 E2EE 共享一套正式 envelope 与诊断口径

重点模块：

- `client/services/e2ee_service.py`
- `client/managers/message_manager.py`
- `client/managers/session_manager.py`
- `client/ui/widgets/chat_panel.py`
- `server/app/services/message_service.py`
- `server/app/api/v1/keys.py`
- `server/app/services/device_service.py`

这个项目特有的高风险点：

- 会话 badge 是否只是 UI 漏显示，还是 `security_summary` / `session_crypto_state` 根本没收口
- prekey claim、identity change、history recovery 导入导出是否有明确失败语义
- 本地数据库加密状态、sidecar key、`sqlcipher_pending` 是否会和启动流程冲突

### 4.6 语音 / 视频通话链路

建议最后看，因为它依赖 auth、session、direct visibility、WS control plane 和 UI current-device guard。

核心问题：

- 是否存在正式 call state machine，而不是各页面各维护一套状态
- signaling 是按 user 路由还是按 device 路由
- sender echo、mirror device、busy / reject / timeout / disconnect 的 authoritative actor 是谁
- 什么时候允许 start media，什么时候只允许更新控制面状态

重点模块：

- `client/managers/call_manager.py`
- `client/ui/windows/chat_interface.py`
- `client/ui/windows/call_window.py`
- `client/call/aiortc_voice_engine.py`
- `server/app/services/call_service.py`
- `server/app/realtime/call_registry.py`
- `server/app/websocket/chat_ws.py`

这个项目特有的高风险点：

- 多设备下是否会重复响铃、重复接听、重复播放 connected / ended 音效
- 空 `call_id` / 晚到 signaling / 其他设备镜像事件能否污染当前 active call
- `call_accept` 之后媒体建立是否仍受 current-call / current-device guard 保护

## 5. 本项目固定要补的专项检查

除了按链路 review，当前仓库每轮都建议固定补这几项：

### 5.1 单一真相

重点看：

- `session_members` 是否仍是聊天权限和已读真相
- viewer-scoped / local-only 字段是否混进 shared payload
- 本地 SQLite 是否被错误拿来做最终业务判断

### 5.2 一致性与补偿

重点看：

- `msg_id` 是否形成完整幂等闭环
- `session_seq` 与 `event_seq` 是否严格分离
- `history_messages` / `history_events` 是否仍按正式 contract 消费
- 全量刷新与增量事件是否会相互打架

### 5.3 异步与并发

重点看：

- 后台任务是否可追踪、可取消、可清理
- 是否吞掉 `CancelledError`
- 跨线程 future、Qt 主线程更新、qasync 任务边界是否清晰
- 本地数据库批量写是否还会出现嵌套事务或竞态写入

### 5.4 安全与隐私

重点看：

- 内部 API 和外部 HTTP 请求是否正确隔离鉴权
- E2EE 明文是否重新写回本地普通缓存
- 本地临时字段、`local_path`、预览状态是否被错误上传
- AI 会话是否错误继承了普通私聊的安全语义

### 5.5 可观测性

重点看：

- 日志是否能串起 `user_id / session_id / msg_id / message_id / call_id / device_id`
- 错误是否在边界层被正确分类，而不是最终只剩一个“请求失败”
- 诊断对象是否统一，例如 `security_summary`、startup preflight、session diagnostics

## 6. 建议输出格式

每轮 review 建议按链路输出，而不是按文件输出：

### 6.1 已确认问题

满足以下任一条件即可：

- 与文档 / ADR / 正式协议明确冲突
- 存在确定错误行为
- 已能描述清楚触发条件、影响路径和根因

### 6.2 风险点

用于记录：

- 当前暂未直接触发错误，但设计脆弱
- 规模扩大后大概率出现性能或维护问题
- 当前靠局部假设勉强成立，后续容易继续漂移

### 6.3 待验证项

用于记录：

- 当前证据不足
- 需要多端复现、集成测试或压测
- 需要先和产品语义再对齐

## 7. 当前仓库优先检查模块

客户端优先：

- `client/managers/connection_manager.py`
- `client/managers/message_manager.py`
- `client/managers/session_manager.py`
- `client/managers/call_manager.py`
- `client/ui/controllers/*`
- `client/storage/database.py`

服务端优先：

- `server/app/websocket/chat_ws.py`
- `server/app/services/message_service.py`
- `server/app/services/session_service.py`
- `server/app/services/device_service.py`
- `server/app/services/group_service.py`
- `server/app/services/call_service.py`
- `server/app/repositories/message_repo.py`
- `server/app/repositories/session_repo.py`

## 8. Review 结论的落点

如果一轮 review 最后只得到“风格一般”“建议重构”“这里可以更优雅”，说明这轮 review 还没有真正碰到这个项目最重要的问题。

更有价值的结论，通常会落到这些句式：

- 哪条正式链路分叉了
- 哪个 authoritative source 不再唯一
- 哪个事件流或补偿模型失效了
- 哪个 local-only 状态污染了 shared truth
- 哪个多设备 / 跨页场景会把当前状态机打穿
