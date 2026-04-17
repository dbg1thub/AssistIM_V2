# AssistIM 文档索引

本文档集用于约束 AssistIM 的产品边界、系统架构、UI 设计系统、编码规范与 AI 生成代码行为。

文档整理目标只有四条：

- 设计要成熟、常见、可扩展、低耦合
- 文档必须能指导后续重构，而不是重复代码现状中的历史问题
- 文档之间不要重复描述同一条规则，也不要互相冲突
- 架构变化、协议变化、UI 设计系统变化都必须同步更新文档

## 1. 推荐阅读顺序

1. [project_context.md](./project_context.md)
   了解项目目标、系统边界、核心能力与非目标。
2. [architecture.md](./architecture.md)
   了解客户端总体架构、协议边界、消息一致性模型与 UI 性能要求。
3. [backend_architecture.md](./backend_architecture.md)
   了解服务端分层、领域模型、实时链路、一致性规则与演进路径。
4. [realtime_protocol.md](./realtime_protocol.md)
   了解当前 WebSocket 实时协议、通话 signaling 扩展与 E2EE 消息 envelope。
5. [ui_guidelines.md](./ui_guidelines.md)
   了解 QFluentWidgets 组件选型、CardWidget 规则、Acrylic 规则、Tooltip 规则与 QSS 规范。
6. [design_decisions.md](./design_decisions.md)
   查看关键设计决策（ADR）与其适用范围。
7. [code_style.md](./code_style.md)
   查看代码风格、async 规范、错误与日志规范、测试与文档更新要求。
8. [ai_rules.md](./ai_rules.md)
   查看 AI / Cursor / Copilot 修改代码时必须遵守的硬约束。
9. [templates.md](./templates.md)
   查看常用代码骨架与推荐写法。
10. [pitfalls.md](./pitfalls.md)
   查看需要主动规避的反模式与历史问题。
11. [chat_e2ee_calls_design.md](./chat_e2ee_calls_design.md)
   查看聊天端到端加密与 1:1 语音 / 视频通话的增量设计草案。
12. [code_review_guide.md](./code_review_guide.md)
   查看针对当前项目的 code review 关注点、检查顺序与结论输出格式。
13. [review_findings_grouped.md](./review_findings_grouped.md)
   查看按根因与业务闭环合并去重后的 review 结论整理版，适合排优先级与定修复批次。
14. [review_findings.md](./review_findings.md)
   查看基于当前仓库快照整理的原始 findings 台账，保留逐条编号、证据与时间顺序。

## 2. 文档优先级

当多个文档描述同一主题时，优先级如下：

1. [design_decisions.md](./design_decisions.md)
   这是不可随意绕过的架构决策记录。
2. [architecture.md](./architecture.md)、[backend_architecture.md](./backend_architecture.md)、[ui_guidelines.md](./ui_guidelines.md)
   这是系统设计与组件边界的主说明文档。
3. [code_style.md](./code_style.md)
   这是代码形态与工程实践约束。
4. [ai_rules.md](./ai_rules.md)
   这是 AI 生成代码时的执行规则，不应覆盖更高层文档。
5. [templates.md](./templates.md)
   这是示例模板，只提供推荐结构，不是强制替代架构说明。
6. [code_review_guide.md](./code_review_guide.md)、[review_findings_grouped.md](./review_findings_grouped.md)、[review_findings.md](./review_findings.md)
   这是 review 辅助文档。前者提供检查框架；`review_findings_grouped.md` 提供合并整理后的问题簇视图；`review_findings.md` 保留原始审查台账。三者都不覆盖 ADR 和架构文档。

## 3. 当前状态与目标状态

本文档集区分两件事：

- 当前可运行基线：项目已经具备单机可运行的客户端与服务端能力
- 目标设计状态：项目应逐步收敛到成熟、常见、可扩展、低耦合的实现方式

如果当前代码与目标设计不一致：

- 先修正文档中的错误设计与错误表述
- 再按照文档继续重构代码
- 不允许继续把历史兼容写法当成长期设计

## 4. 文档维护规则

出现以下变化时，必须同步更新文档：

- WebSocket 协议字段变化
- 消息一致性模型变化，例如 `msg_id`、`session_seq`、`event_seq`、`session_cursors`、`event_cursors`、已读模型
- 服务端领域模型变化，例如 `session_members`、群成员、文件存储、权限模型
- UI 设计系统变化，例如 QFluentWidgets 选型、CardWidget 规则、Tooltip 规则、QSS token
- AI 代码生成约束变化

建议遵守同一提交原则：

- 改架构，连同文档一起改
- 改协议，连同测试与文档一起改
- 改 UI 设计系统，连同示例与规范一起改

## 5. 关键术语

- `msg_id`：客户端发起命令时使用的幂等键，用于 ACK、重发、去重和日志追踪
- `session_seq`：单个会话内的新消息顺序号，用于会话内排序和读指针推进
- `event_seq`：单个会话内的状态事件顺序号，用于回放已读、编辑、撤回、删除等变化
- `session_cursors`：客户端按会话维护的新消息同步高水位
- `event_cursors`：客户端按会话维护的状态事件同步高水位
- `last_read_seq`：会话成员的已读游标，不写回消息主表全局状态
- `EventBus`：客户端内部的通知总线，用于把状态变化广播给 UI，而不是做跨层命令调用
