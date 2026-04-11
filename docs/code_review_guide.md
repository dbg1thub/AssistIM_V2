# Code Review 指南

## 1. 目的

本指南用于统一 AssistIM 的 code review 视角，避免 review 只停留在“代码风格”和“局部写法”层面，而忽略：

- 是否偏离正式文档设计
- 业务流程是否合理
- 设计是否成熟、稳定、经过验证
- 性能、冗余判断与重复实现

同时，本指南补充若干在当前项目中同样高优先级的 review 主题。

## 2. Review 总原则

- 先看正式设计，再看代码现状，不把历史实现自动等同于目标设计
- 先看主链路和真相边界，再看局部写法
- 优先指出会造成错误业务语义、状态漂移、恢复失败和兼容失控的问题
- 将“已确认 bug / 偏离”与“风险点 / 需继续验证项”分开记录
- 结论必须尽量落到具体模块、接口、字段和业务流，不写空泛意见

## 3. 建议检查顺序

### 3.1 文档与架构对齐

先对照以下文档确认“代码应该长成什么样”：

- [architecture.md](./architecture.md)
- [backend_architecture.md](./backend_architecture.md)
- [realtime_protocol.md](./realtime_protocol.md)
- [design_decisions.md](./design_decisions.md)
- [pitfalls.md](./pitfalls.md)

重点检查：

- UI -> Controller -> Manager -> Service -> Network 是否仍然成立
- Router / WebSocket Gateway 是否只做协议适配，业务规则是否仍在 Service
- `session_members` 是否仍是聊天权限和已读真相
- `msg_id`、`session_seq`、`event_seq`、`last_read_seq` 是否仍按正式模型工作
- 兼容入口、兼容脚本、兼容字段是否仍在受控边界内

### 3.2 业务流程正确性

从真实业务流出发检查，而不是只按文件结构检查：

- 登录 / refresh / logout / force logout
- 私聊 / 群聊建会话
- 发消息 / ACK / 重试 / delivered
- 已读推进 / 断线补偿 / edit / recall / delete
- 好友请求归一化
- 文件上传 / 附件消息 / 重试
- AI 会话
- 通话 signaling
- E2EE 文本 / 附件 / 设备状态

要重点问：

- 是否有重复真相
- 是否有跨层绕过
- 是否把历史兼容写法渗进了主流程
- 是否存在用户表面可用、但状态模型不闭环的实现

### 3.3 必须按业务链路审到底

当前项目不适合继续按“看到一个文件就记一个问题”的方式 review。

更稳妥的方式是：一次只沿一条业务链路走到底，直到这条链路的入口、权威状态、实时事件、断线补偿、失败分支、跨页状态都审完，再切下一条。

这样做的原因：

- 当前仓库存在大量跨层异步任务、缓存和旁路入口，零散 review 很容易在不同链路间跳来跳去
- 很多问题不是单点 bug，而是整条业务链路的正式语义没有收口
- 同一根因会在多个文件里重复出现，如果不按链路看，很容易重复记问题而看不出真正的前置根因

### 3.4 推荐 review 链路与顺序

#### 3.4.1 认证与运行时生命周期

建议先看这条，因为它会污染全局，后续所有链路都会受影响。

范围：

- 启动 `restore_session`
- 登录 `login/register`
- 正常退出 `logout`
- 强制下线 `force_logout`
- 切账号 / relogin
- HTTP token refresh
- WS auth / reconnect

本链路要回答的核心问题：

- 项目是否真的存在 per-account authenticated runtime
- runtime 在何时创建、冻结、销毁
- HTTP auth-loss、WS auth-loss、force logout 是否属于同一状态机
- clear local state 与 teardown task 的先后顺序是否正确

建议重点模块：

- `client/main.py`
- `client/ui/controllers/auth_controller.py`
- `client/network/http_client.py`
- `client/managers/connection_manager.py`

#### 3.4.2 会话生命周期

范围：

- 打开会话
- 建私聊 / 建群
- 会话列表刷新
- 删除 / 隐藏会话
- 搜索命中后打开会话
- 全量刷新与增量事件的交界

本链路要回答的核心问题：

- “删除会话”在产品、客户端、服务端是否是同一语义
- authoritative session snapshot 与本地缓存、窗口状态是否一致
- 会话从快照里消失后，是否还能被搜索、warmup、旁路 fetch 复活

建议重点模块：

- `client/managers/session_manager.py`
- `client/ui/windows/chat_interface.py`
- `client/ui/widgets/session_panel.py`
- `client/managers/search_manager.py`
- `server/app/services/session_service.py`

#### 3.4.3 消息主链路

范围：

- 发消息
- ACK / 重试
- 历史同步
- edit / recall / delete
- read / typing
- 搜索定位消息

本链路要回答的核心问题：

- 正式入口到底是 HTTP、WS，还是两者并存
- 请求级幂等、错误返回、广播、补偿是否是一套统一模型
- optimistic local state 与服务端权威状态谁覆盖谁
- edit / recall / delete / read / typing 是否都能断线补偿

建议重点模块：

- `client/managers/message_manager.py`
- `client/managers/connection_manager.py`
- `server/app/websocket/chat_ws.py`
- `server/app/services/message_service.py`
- `server/app/api/v1/messages.py`

#### 3.4.4 联系人与群主链路

范围：

- 加好友 / 好友请求
- 联系人详情
- 建群
- 群成员变更
- 群角色 / 转让
- 联系人搜索 / 群搜索 / 请求搜索
- 联系人缓存刷新

本链路要回答的核心问题：

- 联系人域是否有 authoritative cache contract
- friends / requests / groups 三条分支是否用同一套同步语义
- 搜索结果是否依赖过期缓存
- 群成员与群角色变化是否进入正式实时 / 补偿模型

建议重点模块：

- `client/ui/windows/contact_interface.py`
- `client/ui/controllers/contact_controller.py`
- `client/managers/search_manager.py`
- `server/app/api/v1/friends.py`
- `server/app/api/v1/groups.py`
- `server/app/services/group_service.py`

#### 3.4.5 E2EE 链路

建议放在消息主链路之后看，不要把“消息一致性问题”和“加密问题”混在一起。

范围：

- 会话是否启用 E2EE
- direct / group 收发加密
- 多设备收发
- 本地明文缓存
- attachment metadata 缓存
- 设备注册 / trust
- history recovery
- reprovision

本链路要回答的核心问题：

- `encryption_mode` 是否是服务端权威真相
- 多设备直聊是否成立
- 本地明文缓存是否已经变成第二真相
- recovery / reprovision 的边界到底是 session 级还是 device 级

建议重点模块：

- `client/services/e2ee_service.py`
- `client/managers/message_manager.py`
- `client/managers/session_manager.py`
- `server/app/services/message_service.py`
- `server/app/api/v1/keys.py`

#### 3.4.6 语音 / 视频通话链路

建议最后看，因为它依赖 auth、session、direct session、WS control plane。

范围：

- 发起通话
- 来电提醒
- ringing
- accept / reject
- offer / answer / ice
- 媒体建立
- hangup / busy / timeout / failure
- 重连 / 异常退出

本链路要回答的核心问题：

- 是否存在正式 call state machine
- accept 前能否发送 signaling、打开媒体
- 错误归因是“单条 signaling 失败”还是“整通电话失败”
- completed / timeout / busy / rejected 是否由服务端权威定义

建议重点模块：

- `client/managers/call_manager.py`
- `client/ui/windows/chat_interface.py`
- `client/ui/windows/call_window.py`
- `client/call/aiortc_voice_engine.py`
- `server/app/services/call_service.py`
- `server/app/realtime/call_registry.py`
- `server/app/websocket/chat_ws.py`

### 3.5 每条业务链路里的固定检查模板

无论审哪条链路，都建议按同一模板走，避免再次散掉：

1. 产品语义
2. 正式入口
3. 权威数据源
4. 本地缓存与内存态
5. 实时事件
6. 断线补偿
7. 失败与重试
8. 幂等与并发
9. 跨页 / 跨设备一致性
10. 测试覆盖缺口

如果一条链路还没有按上面 10 项走完，就不要切去下一条链路。

### 3.6 每条链路里的具体开展顺序

建议固定为：

1. 先写清楚这条链路的产品语义和正式设计
2. 再找入口：UI / HTTP / WS / 后台任务
3. 再找权威真相：服务端状态、本地数据库、内存缓存谁说了算
4. 再找增量事件与全量刷新如何收口
5. 再看断线重连、补偿、失败回滚
6. 最后再看性能、冗余判断和测试缺口

如果 review 过程中已经发现一组问题都指向同一个根因，应优先收成一个“问题簇”，不要继续按单条零散记录。

### 3.7 推荐实际执行顺序

建议 review 按以下顺序推进：

1. 认证与运行时生命周期
2. 会话生命周期
3. 消息主链路
4. 联系人与群主链路
5. E2EE 链路
6. 语音 / 视频通话链路

其中：

- 第 1 条通常是全局前置条件
- 第 2、3 条是聊天主产品骨架
- 第 4 条是联系人与群域收口
- 第 5、6 条应建立在前面边界已经相对稳定的基础上再看

### 3.8 建议输出方式

如果按链路 review，建议每轮输出也按链路写，而不是按文件写：

- 本轮审的是哪条业务链路
- 这条链路的正式语义是什么
- 当前发现的问题簇是什么
- 哪些是已确认问题，哪些只是风险
- 修复建议应该先动哪一层

这样更容易直接转成修复批次，也更容易和 [review_findings_grouped.md](./review_findings_grouped.md) 对齐。

### 3.9 设计成熟度与演进性

重点检查设计是否符合“成熟、常见、可扩展、低耦合”的目标：

- 是否使用常见、经过验证的状态机和边界抽象
- 是否为了“兼容未来”在主路径埋了大量 if/else
- 是否把具体基础设施实现泄漏到业务层
- 是否存在难以测试、难以替换、难以观测的隐式耦合

### 3.10 性能与重复逻辑

重点关注：

- 长列表是否仍优先增量更新，而不是频繁 reset
- AI streaming 是否有节流
- 是否存在重复查询、重复序列化、重复状态判断
- 同一业务规则是否在 UI / Manager / Service 多处重复实现
- 是否存在大规模 OR 查询、全量刷新、全量扫描等扩展性风险

## 4. 需要额外补充关注的主题

除了上面的四个主主题，当前项目 review 还应固定补充以下六类检查。

### 4.1 一致性与可靠性

重点看：

- ACK 是否形成闭环
- 重发是否复用同一个 `msg_id`
- `session_seq` 与 `event_seq` 是否严格分离
- 已读是否仍是成员游标，而不是消息全局状态
- 断线补偿是否仍使用 `session_cursors + event_cursors`

### 4.2 单一真相与边界污染

重点看：

- 是否在多个层同时维护会话、未读、成员、权限、附件、加密状态
- UI 是否直接触碰 HTTP / WS / SQLite
- Manager 是否直接依赖 SQL 或 storage 私有 helper
- EventBus 是否被反向用作命令总线

### 4.3 并发与异步正确性

重点看：

- 后台任务是否可追踪、可取消
- 是否吞掉 `CancelledError`
- 重连、关闭、切换账号时是否能正确收束任务和状态
- qasync / asyncio / Qt 主线程边界是否清晰

### 4.4 兼容层与历史债务

重点看：

- legacy route / legacy payload / schema compat 是否还在扩大影响面
- 兼容逻辑是否已经和主链路分叉
- 文档里宣称保留的兼容边界是否仍真实存在
- 运行时是否存在“读路径修数据”“业务请求顺便补历史数据”的写法

### 4.5 安全与隐私边界

重点看：

- 内外部 HTTP 请求是否正确隔离鉴权
- 敏感链路是否按正式 TLS / WSS 基线收口
- 本地临时字段是否被错误上传或持久化
- E2EE 会话是否把明文重新写回不该写的位置
- AI 会话是否错误继承普通私聊的安全语义

### 4.6 可测试性与可观测性

重点看：

- 关键链路是否有测试抓手
- 日志是否能串起 `user_id / session_id / message_id / msg_id / call_id / device_id`
- 错误是否能定位到边界，而不是最终只剩一个“请求失败”

## 5. 建议输出格式

review 结论建议分三层输出：

### 5.1 已确认问题

必须满足至少一个条件：

- 与文档 / ADR / 协议存在明确冲突
- 存在确定的错误行为、错误边界或错误状态模型
- 已能明确描述影响路径和触发条件

### 5.2 风险点

用于记录：

- 当前暂未直接触发错误，但设计脆弱
- 规模扩大后可能出现明显性能或维护问题
- 代码与文档之间存在“很可能继续漂移”的边界

### 5.3 待验证问题

用于记录：

- 当前证据不足
- 需要跑集成测试、压测或多端验证
- 需要和产品规则再对齐

## 6. 当前仓库推荐优先检查模块

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
- `server/app/services/friend_service.py`
- `server/app/services/call_service.py`
- `server/app/repositories/message_repo.py`
- `server/app/repositories/session_repo.py`

## 7. 与当前快照配套的 findings

本指南只定义 review 框架，不记录具体问题。

当前代码快照的已确认问题与风险点见：

- [review_findings.md](./review_findings.md)
