# 仓库常见陷阱与反模式

本文档只记录这个仓库里反复出现、且容易在重构或补功能时再次踩到的坑。

它不是主规范来源；正式边界仍以 [design_decisions.md](../architecture/design_decisions.md)、[architecture.md](../architecture/architecture.md)、[backend_architecture.md](../architecture/backend_architecture.md) 和 [realtime_protocol.md](../protocols/realtime_protocol.md) 为准。

## 1. 在多个地方维护同一份业务真相

典型表现：

- 同时依赖多套成员关系判断聊天权限
- UI 自己维护未读、排序、会话状态真相
- 本地缓存和服务端权限混在一起判断

为什么危险：

- 写路径复杂
- 读路径开始补洞
- 状态会长期漂移

收敛方向：

- 会话权限与已读真相统一落到 `session_members`
- 客户端状态统一由 Manager 管理
- 本地缓存只做恢复与展示，不做最终权限真相

## 2. 用时间戳代替正式同步游标

典型表现：

- 用 `created_at` 或 `last_timestamp` 拉缺失消息
- 认为“时间更大就是更晚的权威状态”

为什么危险：

- 时间精度、时钟漂移、写入重排都会破坏正确性
- 很难同时兼容消息补偿和状态事件补偿

收敛方向：

- 新消息补偿使用 `session_cursors`
- 状态事件补偿使用 `event_cursors`
- 会话顺序使用 `session_seq`

## 3. 混用消息流与状态事件流

典型表现：

- 试图通过 `session_seq` 推断 `read/edit/recall/delete`
- 把所有状态变更混进消息补偿

为什么危险：

- 新消息与状态变更不是同一类数据
- 客户端很难处理“没有新消息，但旧消息状态变了”的场景

收敛方向：

- 新消息走 `history_messages`
- 状态事件走 `history_events`
- `event_seq` 单独推进

## 4. 让 HTTP 与 WebSocket 各自维护一套业务规则

典型表现：

- HTTP 走 Service，WebSocket 直接广播或直接写库
- 两个入口各自做一套权限和状态判断

为什么危险：

- 会出现同一业务在两个入口下语义不同
- 后续 bug 会集中出现在“只有 WS 出问题”或“只有 HTTP 出问题”的分叉场景

收敛方向：

- Router / Gateway 只做协议适配
- 业务规则统一收敛到 Service

## 5. 把本地状态或 viewer-scoped 字段混进 shared payload

典型表现：

- 会话或群组列表里直接内联 self-scoped 字段
- local-only 状态和远端正式字段混在同一个结构里

为什么危险：

- formal payload 漂移
- 不同入口返回 shape 不一致
- 多端或后续扩展时很难做 canonical contract

收敛方向：

- shared payload 只放共享真相
- viewer-scoped / local-only 状态留在本地模型或单独接口

## 6. 把本地缓存当成服务端权限真相

典型表现：

- 用本地 SQLite 判断会话是否还能发送
- 读路径里偷偷“修复”服务端缺失的成员关系

为什么危险：

- 会让离线恢复、权限校验和历史兼容纠缠在一起
- 客户端一旦缓存脏了，就会产生错误业务判断

收敛方向：

- 本地缓存只做恢复、展示、重试
- 最终权限与业务规则仍以后端为准

## 7. 把本地临时字段透传到远端

典型表现：

- 附件 `extra` 里混入 `local_path`、`uploading`、本地预览状态
- UI 临时状态直接进远端消息 payload

为什么危险：

- 消息 contract 被本地实现污染
- 多端消费时拿到无意义字段

收敛方向：

- 远端只保留 shareable 媒体元数据
- 本地临时状态留在本地模型

## 8. UI 页面自己维护业务状态机

典型表现：

- 页面切换、会话切换、通话状态、发送状态分别由多个 widget 自己维护
- UI 通过局部变量“猜”当前业务状态

为什么危险：

- 页内一致性很容易漂移
- 页面之间切换时最容易出现重复动画、幽灵状态、错误提示

收敛方向：

- 业务状态由 Manager 统一维护
- UI 只订阅状态并渲染

## 9. 未追踪后台任务，或吞掉 `CancelledError`

典型表现：

- fire-and-forget 任务不保存引用
- 关闭流程里没有显式 cancel / await
- 用宽泛异常捕获把 `CancelledError` 一起吞掉

为什么危险：

- 容易造成退出卡死、重复任务、脏状态
- 调试时很难定位是谁还在跑

收敛方向：

- 长期任务必须保存引用
- 关闭时显式 cancel / await
- `CancelledError` 单独处理

## 10. 把外部 HTTP 请求混入应用内部鉴权链路

典型表现：

- 外部绝对 URL 也自动带应用 Bearer token
- 外部 401 误触发应用 refresh

为什么危险：

- 会把应用鉴权泄漏到第三方服务
- 错误语义会被完全污染

收敛方向：

- 内部 API 走相对路径并继承应用鉴权
- 外部服务走绝对 URL，不继承应用鉴权

## 11. 为了兼容历史问题，到处散落条件分支

典型表现：

- 每个入口都多写一段 legacy fallback
- 新逻辑继续依赖 placeholder 字段或重复字段

为什么危险：

- 兼容层会扩散到整个系统
- 长期看比直接收口边界更难维护

收敛方向：

- 先收口正式边界
- 兼容逻辑集中在明确边界或迁移路径

## 12. 把草案文档当成正式规范

典型表现：

- 直接按设计草案里的候选字段实现
- 把路线图阶段内容当成已经承诺的 contract

为什么危险：

- 草案通常同时包含“已确定”和“待决策”内容
- 很容易让实现跑在正式协议前面

收敛方向：

- 已落地 contract 回填到主文档
- 草案只保留取舍、开放问题和 rollout 计划
