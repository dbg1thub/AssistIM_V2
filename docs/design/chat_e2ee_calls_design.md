# 聊天端到端加密与 1:1 通话路线图（草案）

## 1. 文档定位

本文档只保留以下内容：

- 增量范围
- 设计取舍
- 尚未收口的开放问题
- 分阶段落地顺序
- 每阶段验收口径

本文档不是正式协议，也不是正式架构说明。已经收口的内容应分别回填到：

- [design_decisions.md](../architecture/design_decisions.md)
- [architecture.md](../architecture/architecture.md)
- [backend_architecture.md](../architecture/backend_architecture.md)
- [realtime_protocol.md](../protocols/realtime_protocol.md)

如果某条规则已经进入上述文档，本文档不再重复定义字段、表结构或 payload 细节。

## 2. 本阶段目标

本路线图只关注四项能力：

- `private` 会话的文本 E2EE
- `private` 会话的附件 E2EE
- `private` 会话的 1:1 语音通话
- `private` 会话的 1:1 视频通话

目标不是引入第二套架构，而是在现有分层、同步模型和实时链路上增量落地。

## 3. 范围与非目标

### 3.1 本阶段范围

- `private` 会话的设备注册、公钥分发与 prekey claim
- `private` 会话文本消息加密
- `private` 会话附件加密上传与下载后解密
- 1:1 通话 signaling、WebRTC 媒体链路与桌面端通话状态机
- E2EE 会话的基础安全提示、身份确认、恢复动作入口

### 3.2 本阶段非目标

以下能力明确不在这一轮里同时推进：

- 群聊 E2EE
- 群语音 / 群视频
- AI 会话默认启用 E2EE
- E2EE 私聊的服务端全文搜索
- 多设备完全自动的历史密钥同步
- 为了兼容旧实现而长期双写“明文 + 密文”两套真相

原因：

- 群聊 E2EE 和群通话都属于复杂度更高的独立主题
- AI 会话需要服务端或 provider 看到明文，和默认 E2EE 目标冲突
- 多设备自动恢复会显著放大设备 claim、密钥扇出和历史恢复复杂度

## 4. 已经收口的基线

以下方向已经作为正式基线存在，本文件只保留引用：

### 4.1 传输与通话基线

- 生产环境使用 `HTTPS` / `WSS`
- 通话 signaling 继续复用聊天 WebSocket
- 媒体层统一使用 `WebRTC`
- STUN / TURN 通过后端显式分发

对应主文档：

- [design_decisions.md](../architecture/design_decisions.md) 中的 `ADR-031`、`ADR-032`
- [architecture.md](../architecture/architecture.md) 中的“1:1 通话”
- [backend_architecture.md](../architecture/backend_architecture.md) 中的“通话 signaling”
- [realtime_protocol.md](../protocols/realtime_protocol.md) 中的“新增通话 signaling”

### 4.2 私聊 E2EE 基线

- E2EE 首先只对 `private` 会话启用
- AI 会话明确保持 `server_visible_ai`
- 服务端只路由密文与加密元数据，不依赖明文执行业务
- 本地缓存优先持久化密文，不默认长期写回明文
- 本地数据库加固通过 `SQLCipher` 演进，但不是第一阶段前置条件

对应主文档：

- [design_decisions.md](../architecture/design_decisions.md) 中的 `ADR-033`、`ADR-034`
- [architecture.md](../architecture/architecture.md) 中的“1:1 私聊 E2EE”
- [backend_architecture.md](../architecture/backend_architecture.md) 中的“端到端加密边界”
- [realtime_protocol.md](../protocols/realtime_protocol.md) 中的“私聊 E2EE 消息 envelope”

## 5. 仍需收口的开放问题

### 5.1 通话多设备路由

当前最需要先收口的是 device-scoped 通话模型，而不是继续堆 UI。

必须先明确：

- 来电是 fanout 给用户全部在线设备，还是先 claim 一个主处理设备
- `call_ringing`、`call_accept`、`call_hangup` 是否需要 sender 当前设备 echo
- 同账号多设备在线时，哪些设备允许 surface 完整来电 UI，哪些只能镜像状态
- busy / reject / accept 的 authoritative actor 到底是 user 还是 device

如果这些问题不先收口，后续最容易出现：

- 重复响铃
- 多设备同时接听
- 被动镜像设备误播放音效
- 一通电话被多个设备重复推进状态机

### 5.2 E2EE 多设备恢复边界

本阶段不做“全自动多设备同步”，但必须先把最小恢复语义讲清楚：

- 新设备首次登录时，允许恢复什么
- 哪些历史消息可以通过恢复包解开，哪些不承诺
- `reprovision_device`、`switch_device`、`trust_peer_identity` 各自触发条件是什么
- 恢复失败时，是阻塞发送、阻塞查看历史，还是只给提示

这部分要先定义产品语义，再补界面与导入导出细节。

### 5.3 身份验证 UX

当前已经有基础 trust state 和验证入口，但正式产品语义还需要继续收口：

- 什么状态只提示，什么状态阻塞发送
- “未验证”和“身份变更”各自的 UI 等级是否一致
- 用户验证一次后，信任是按设备、按用户还是按会话生效
- 时间线、验证码、指纹信息里哪些属于主视图，哪些属于高级信息

### 5.4 附件预览与缩略图策略

附件 E2EE 的关键不是“能不能发”，而是“预览链路是否还保持同一套真相”。

需要明确：

- 缩略图是否只在客户端本地生成
- 服务端是否完全不参与任何依赖明文的派生文件生成
- 下载失败、解密失败、密钥缺失时如何区分 UI 状态
- 图片 / 视频 / 文件三类附件是否共用同一套 envelope 与下载边界

### 5.5 可观测性与故障诊断

E2EE 和通话都很容易变成“只能靠猜”的黑盒链路，因此必须先定义可观测性边界：

- 记录哪些结构化日志而不泄漏明文
- 哪些状态进入 `security_summary` / `diagnostics`
- 通话链路的关键时间点和设备标识如何打点
- 恢复失败、prekey claim 失败、媒体下载失败是否都有统一诊断入口

## 6. 分阶段落地顺序

### Phase 1：传输与通话骨架

目标：

- 生产基线统一到 `https/wss`
- 补齐 STUN / TURN 分发
- 聊天页与联系人页通话入口接入真实 manager，而不是占位按钮

完成标准：

- 通话入口不再依赖 placeholder
- 生产部署不再把纯 `http/ws` 当默认方案
- ICE 配置走正式后端边界

### Phase 2：1:1 通话主链路

目标：

- 打通 `call_invite -> call_hangup`
- 先收口语音通话
- 再扩到视频通话

完成标准：

- 双端能完成来电、接听、拒绝、挂断
- 典型 NAT 场景下语音可稳定建立
- 视频开关、静音、设备切换不破坏同一套通话状态机
- 多设备路由规则已经明确，不再出现重复来电 UI 和重复终态音效

### Phase 3：设备密钥基础设施

目标：

- 设备注册、公钥分发、prekey claim 进入正式 API / Service 边界
- 客户端具备最小可用的设备身份状态和信任状态

完成标准：

- 新设备能完成注册
- 对端能拉取 prekey bundle 并开始建链
- prekey claim、设备撤销和信任状态变更都有可诊断结果

### Phase 4：私聊文本 E2EE

目标：

- 文本消息发送前加密、接收后解密
- 服务端和远端持久化只看到密文及元数据
- E2EE 会话具备基础身份验证和恢复提示

完成标准：

- 服务端消息持久化不再保存私聊明文正文
- 双端文本收发、已读、编辑、撤回继续沿用现有一致性模型
- `unverified`、`identity_changed`、恢复缺失等状态都有明确 UI 语义

### Phase 5：附件 E2EE

目标：

- 文件先加密再上传
- 下载后本地解密
- 图片 / 视频 / 文件统一进入规范附件边界

完成标准：

- 服务端只持久化密文文件和密文附件元数据
- 接收端能稳定下载、解密和预览
- E2EE 附件失败态可区分为上传失败、下载失败、解密失败、密钥缺失

### Phase 6：本地数据库加固与恢复体验

目标：

- 数据库落盘保护进入正式迁移阶段
- 恢复包、设备迁移、历史恢复体验从“可用”收口到“可解释”

完成标准：

- `sqlcipher` 模式具备稳定迁移路径
- 历史恢复行为有明确产品语义和诊断说明
- 启动安全预检、运行时安全诊断和会话级安全摘要保持同一口径

## 7. 每阶段的文档回填规则

为了避免本文件再次膨胀，后续实现落地时必须按以下规则回填：

- 正式协议字段进入 [realtime_protocol.md](../protocols/realtime_protocol.md)
- 正式客户端边界进入 [architecture.md](../architecture/architecture.md)
- 正式服务端边界进入 [backend_architecture.md](../architecture/backend_architecture.md)
- 已接受且长期有效的方向进入 [design_decisions.md](../architecture/design_decisions.md)
- 当前文件只保留尚未完全收口的取舍、风险和 rollout 计划

不允许继续把这些内容长期留在“草案文档”里：

- 完整 payload 字段清单
- 完整表结构建议
- 已经正式落地的模块 inventory
- 带有强烈当前快照色彩的“当前代码已经怎样”列表

## 8. 风险与取舍

### 8.1 E2EE 与搜索

- E2EE 私聊如果只持久化密文，本地全文搜索天然会降级
- 本阶段接受“E2EE 私聊默认不可搜索”的取舍

### 8.2 E2EE 与 AI

- AI provider 需要明文
- 本阶段接受“AI 会话不默认继承私聊 E2EE”的取舍

### 8.3 E2EE 与多设备

- 多设备自动恢复会显著放大复杂度
- 本阶段接受“先做主设备优先 + 显式恢复动作”的取舍

### 8.4 WebRTC 与桌面工程化

- Python WebRTC 依赖、设备兼容和 Windows 打包都有工程风险
- 本阶段接受“先语音后视频、先收状态机再扩展能力”的取舍

## 9. 明确不建议的做法

- 不要在 WebSocket 上传输音视频帧
- 不要手写自定义密码学原语或自定义棘轮协议
- 不要为了兼容旧入口而长期双写明文与密文两套真相
- 不要把群聊 E2EE 和群通话一起塞进这一轮
- 不要让服务端依赖明文生成 E2EE 附件缩略图或派生文件
- 不要把 local-only 恢复状态、预览状态、临时文件路径混入服务端正式 payload

## 10. 下一步

下一步优先级应继续保持：

1. 先收口多设备通话路由和通话状态机口径
2. 再收口 E2EE 恢复语义与身份验证 UX
3. 然后推进附件 E2EE 的统一下载 / 预览边界
4. 最后再把数据库加固和多设备恢复体验做成稳定产品能力
