# AssistIM 文档总览

本文档集用于约束 AssistIM 的产品边界、系统架构、实时协议、UI 设计系统与工程实践。

整理目标只有四条：

- 设计要成熟、常见、可扩展、低耦合
- 文档必须指导后续收敛，而不是重复历史实现
- 同一条规则只在一个主文档里定义，其余文档只做引用
- 架构、协议、UI 设计系统和工程规则变化时必须同步更新文档

## 1. 项目定位与范围

AssistIM 是一个 AI 增强即时通讯桌面应用，目标是把“即时通讯”和“AI 助手能力”放在同一个桌面客户端里，并保持清晰分层、稳定实时链路和可维护的 UI 体系。

系统由三部分组成：

- Desktop Client
- Backend API + WebSocket Gateway
- External AI Providers / File Storage

当前核心能力包括：

- 私聊与群聊
- 消息发送、接收、ACK、重试、断线补偿
- 已读回执与未读统计
- 好友、群组、朋友圈、文件上传
- AI 会话与流式输出
- 本地缓存与离线浏览基础能力

当前交付基线要求：

- 单机可运行
- 可调试
- 可测试

在此前提下，文档保留后续演进路径：

- 服务端从单实例演进到多实例
- 文件存储从本地目录迁移到对象存储
- Presence / Fanout 从进程内结构迁移到 Redis / PubSub
- 离线补偿从消息补偿继续演进到事件流补偿

以下内容不作为当前文档集的设计目标：

- 为了“未来可能扩容”而过早拆成微服务
- 在 UI 层直接拼接网络或数据库逻辑
- 用多个来源重复维护同一份业务真相
- 用演示型临时方案长期替代正式一致性模型

## 2. 文档使用原则

本文档集区分两件事：

- 当前可运行基线：项目已经具备单机可运行的客户端与服务端能力
- 目标设计状态：项目应逐步收敛到成熟、常见、可扩展、低耦合的实现方式

如果当前代码与目标设计不一致：

- 先修正文档中的错误设计与错误表述
- 再按照文档继续重构代码
- 不允许继续把历史兼容写法当成长期设计

## 3. 推荐阅读顺序

1. [architecture.md](./architecture/architecture.md)
   了解客户端总体架构、协议边界、消息一致性模型与缓存策略。
2. [backend_architecture.md](./architecture/backend_architecture.md)
   了解服务端分层、领域模型、实时链路、一致性规则与演进路径。
3. [realtime_protocol.md](./protocols/realtime_protocol.md)
   了解当前 WebSocket 实时协议、通话 signaling 与 E2EE envelope。
4. [ui_guidelines.md](./ui/ui_guidelines.md)
   了解 QFluentWidgets 组件选型、CardWidget 规则、Acrylic 规则与 QSS 规范。
5. [design_decisions.md](./architecture/design_decisions.md)
   查看关键设计决策（ADR）与其适用范围。
6. [code_style.md](./engineering/code_style.md)
   查看工程实践、代码风格与推荐代码骨架。
7. [ai_rules.md](./engineering/ai_rules.md)
   查看 AI 修改代码时必须遵守的额外执行规则。
8. [pitfalls.md](./engineering/pitfalls.md)
   查看本仓库反复出现的反模式与历史坑位。
9. [chat_e2ee_calls_design.md](./design/chat_e2ee_calls_design.md)
   查看聊天端到端加密与 1:1 语音 / 视频通话的增量设计草案与路线图。
10. [ai_feature_detailed_design.md](./design/ai_feature_detailed_design.md)
    查看本地 GGUF 模型、AI 输入辅助、私聊推荐回复与 AI 会话的详细落地设计。
11. [code_review_guide.md](./engineering/code_review_guide.md)
    查看当前项目的 code review 检查顺序与输出格式。
12. [review_findings_grouped.md](./reviews/review_findings_grouped.md)
    查看按问题簇归并后的 review 结论与修复优先级。
13. [review_findings.md](./reviews/review_findings.md)
    查看原始 findings 台账与逐条证据。

## 4. 文档职责划分

为了避免继续重复，每份主文档只承担一类职责：

- [architecture.md](./architecture/architecture.md)
  客户端分层、状态模型、缓存边界、客户端职责划分。
- [backend_architecture.md](./architecture/backend_architecture.md)
  服务端分层、领域模型、部署基线、服务端一致性边界。
- [realtime_protocol.md](./protocols/realtime_protocol.md)
  WebSocket 外层结构、事件类型、字段 contract 与兼容规则。
- [ui_guidelines.md](./ui/ui_guidelines.md)
  客户端设计系统、组件选型、QSS / Acrylic / Tooltip 规则。
- [design_decisions.md](./architecture/design_decisions.md)
  已接受且长期有效的架构决策，不重复写实现细节。
- [code_style.md](./engineering/code_style.md)
  工程实践、代码风格、异常 / 日志 / 测试要求，以及推荐代码骨架。
- [ai_rules.md](./engineering/ai_rules.md)
  AI 改代码时的额外执行规则，不重新定义架构本身。
- [pitfalls.md](./engineering/pitfalls.md)
  仓库里反复出现的历史坑位与反模式，不作为主规范来源。
- [chat_e2ee_calls_design.md](./design/chat_e2ee_calls_design.md)
  E2EE / 1:1 通话的增量方案、取舍、开放问题和分阶段落地顺序。
- [ai_feature_detailed_design.md](./design/ai_feature_detailed_design.md)
  本地 GGUF 模型、AI 输入辅助、私聊推荐回复和 AI 会话的详细工程设计。
- [code_review_guide.md](./engineering/code_review_guide.md)
  review 执行方法，不定义正式架构。
- [review_findings_grouped.md](./reviews/review_findings_grouped.md)、[review_findings.md](./reviews/review_findings.md)
  review 结果台账，不覆盖 ADR 和主架构文档。

## 5. 文档优先级

当多个文档描述同一主题时，优先级如下：

1. [design_decisions.md](./architecture/design_decisions.md)
   不可随意绕过的架构决策记录。
2. [architecture.md](./architecture/architecture.md)、[backend_architecture.md](./architecture/backend_architecture.md)、[realtime_protocol.md](./protocols/realtime_protocol.md)、[ui_guidelines.md](./ui/ui_guidelines.md)
   系统设计、协议和 UI 边界的主说明文档。
3. [code_style.md](./engineering/code_style.md)
   工程实践与代码形态约束。
4. [ai_rules.md](./engineering/ai_rules.md)
   AI 执行规则，只能细化上层要求，不能覆盖上层文档。
5. [pitfalls.md](./engineering/pitfalls.md)
   反模式清单，用于提醒，不是正式规范来源。
6. [code_review_guide.md](./engineering/code_review_guide.md)、[review_findings_grouped.md](./reviews/review_findings_grouped.md)、[review_findings.md](./reviews/review_findings.md)
   review 辅助材料，不覆盖 ADR 和主设计文档。

## 6. 文档维护规则

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

## 7. 关键术语

- `msg_id`：客户端发起命令时使用的幂等键，用于 ACK、重发、去重和日志追踪
- `session_seq`：单个会话内的新消息顺序号，用于会话内排序和读指针推进
- `event_seq`：单个会话内的状态事件顺序号，用于回放已读、编辑、撤回、删除等变化
- `session_cursors`：客户端按会话维护的新消息同步高水位
- `event_cursors`：客户端按会话维护的状态事件同步高水位
- `last_read_seq`：会话成员的已读游标，不写回消息主表全局状态
- `EventBus`：客户端内部的通知总线，用于把状态变化广播给 UI，而不是做跨层命令调用
