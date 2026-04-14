# Review Findings（合并整理版）

## 1. 说明

本文档是对 [review_findings.md](./review_findings.md) 的合并整理版。

- 目标：把重复问题、同一根因导致的问题、同一业务闭环上的问题合并，方便排优先级和制定修复计划
- 口径：本页是“问题簇视图”，原始编号、原始时间顺序、逐条证据仍保留在 [review_findings.md](./review_findings.md)
- 建议用法：先看本页确定修复批次，再回原始台账按编号追证据
- 当前 review 状态：6 条主业务链路已完成尾扫，问题簇已基本收满
- 当前建议：停止继续散扫，直接按 `G-01` 到 `G-08` 制定修复批次

### 1.0 当前收口状态

当前 6 条主业务链路的 review 进度已经收口为：

1. 认证与运行时生命周期：`100%`
2. 会话生命周期：`100%`
3. 消息主链 / 正式协议边界：`100%`
4. 联系人与群主链：`100%`
5. E2EE：`100%`
6. 语音/视频通话：`100%`

说明：

- 这里的 `100%` 指“基于当前仓库快照的 review 尾扫已收口”
- 不表示问题已经修复
- 后续如果代码继续变化，应增量回写 raw 台账和问题簇视图

### 1.0.1 业务链路与问题簇映射

后续按业务链路修复时，建议直接用下面这张映射表：

1. 认证与运行时生命周期
   - 对应：`G-03`
   - 建议批次：`P0`
2. 会话生命周期
   - 对应：`G-02`
   - 建议批次：`P0`
3. 消息主链 / 正式协议边界
   - 对应：`G-01`
   - 建议批次：`P0`
4. 联系人与群主链
   - 对应：`G-04`、`G-05`
   - 建议批次：`P1` 到 `P2`
5. E2EE
   - 对应：`G-08`
   - 建议批次：`P1`
6. 语音/视频通话
   - 对应：`G-07`
   - 建议批次：`P1`
7. 页内 UI 状态机和本地缓存体验
   - 对应：`G-06`
   - 建议批次：`P2`

### 1.1 问题簇状态口径

后续更新 grouped findings 时，问题簇建议只使用以下四种状态：

- `open`：问题簇已确认，尚未进入修复
- `active_remediation`：已经开始修复，但根因尚未收口
- `partially_contained`：部分问题已修，影响面已缩小，但问题簇仍未关闭
- `closed`：这一簇的共同根因已经收口

### 1.2 问题簇归档规则

问题簇不因为修掉一个 `F-xxx` 就关闭。

只有在以下条件基本同时满足时，才建议把对应 `G-xx` 标成 `closed`：

- 正式语义已经收口
- 关键代码路径已经改完
- 至少有定向验证
- 相关文档已经同步

如果只是修掉问题簇里的若干个单点，但共同根因仍成立，应保留为 `active_remediation` 或 `partially_contained`。

## 2. 已修复项

以下问题已经修复，不再纳入当前优先级：

- `F-001` 通话 signaling 字段命名与协议文档不一致
- `F-002` 兼容入口文档与当前实现不一致
- `F-003` 会话默认加密模式把所有 direct / group 会话都视为 E2EE
- `F-004` 消息发送路径是否加密只按会话类型判断

## 3. 合并后的问题簇

### G-01：服务端权威真相与正式协议边界没有收口

状态：closed（2026-04-14）

修复进展：

- `F-529` / `F-549` 已把客户端可发送 message_type 收口为 `text/image/file/video/voice`，HTTP/WS 均拒绝 `system`
- `F-530` 已为附件型消息建立 payload gate，非加密附件必须提供 url/name/type/size 元数据，加密附件继续走 envelope 校验
- `F-531` / `F-532` 已为 edit 建立文本类型 gate 和 sent/edited 状态 gate
- `F-533` 已为 recall 建立 sent/edited 状态 gate 和用户态消息类型 gate
- `F-534` 到 `F-538` 已把 E2EE envelope 必填字段收口为非空字符串，direct/group text、attachment 和 fanout 不再接受 dict/list 伪标量
- `F-550` 已为 HTTP edit schema 补齐 `extra=forbid`，未知字段不再静默吞掉
- `F-592` / `F-593` 已把 message create/edit 的内容长度和非空白约束下沉到 schema
- `F-590` / `F-591` 已把 member mention 绑定到当前 session member 集，并拒绝重复/重叠 mention span
- `F-667` 到 `F-670` 已把 message edit/recall/delete/read 的 committed mutation 与 realtime fanout 解耦，fanout 失败不再导致 HTTP 500
- `F-617` / `F-618` / `F-624` 已从 file upload/list 响应和聊天附件 extra 中移除内部存储字段 `storage_provider/storage_key/checksum_sha256`
- `F-622` 已为 `GET /files` 增加 `limit` 数量边界并下推到数据库查询
- `F-620` 已为通用文件上传建立扩展名与 MIME allowlist，非法类型在落盘前返回 422
- `F-623` 已为通用上传和自定义头像上传建立落盘后 DB 失败补偿，避免残留孤儿文件
- `F-621` / `F-727` 已把上传 MIME 改为服务端派生，并收口上传显示名的可打印字符与长度边界
- `F-619` 已移除 upload_dir 的 StaticFiles 公开挂载，`/uploads/...` 改为受认证下载路由
- `F-740` / `F-741` / `F-742` 已把文件公开响应和 FileOut 收口为单一 canonical 字段集，并移除 media 嵌套镜像
- `F-747` 已拆分文件列表 summary 与上传结果 output，list 不再复用 upload-result detail shape
- `F-743` / `F-744` 已为 moments like/unlike 回显 liked/changed，明确 no-op 语义
- `F-702` 到 `F-707` 已把 moment/comment 输入 schema、moments feed 分页 envelope、summary/detail 边界和 liker roster 可见性收口到正式 contract
- `F-748` 已为 direct session create 回显 created/reused，区分新建和复用旧私聊
- `F-749` / `F-750` 已为好友请求创建回显 request_created/request_reused/friendship_created，区分 no-op 和自动接受
- `F-745` / `F-746` 已把 moment/comment 作者 payload 收口为统一 author 子结构
- `F-569` / `F-570` 已把建私聊“恰好一个参与者”和 extra forbid 收口到 schema
- `F-571` / `F-572` 曾把 HTTP typing 请求收口到 `SessionTypingRequest` / `StrictBool` schema；后续 `R-005` 已进一步删除 HTTP typing 入口，typing 只保留聊天 WS 正式入口
- `F-760` 已把建私聊 `participant_ids` 的 item 级 strip / 非空 / 长度 / 去重和“恰好一个参与者”下沉到 schema
- `F-761` / `F-762` / `F-763` 已把 group member id、transfer owner id 和成员角色枚举约束下沉到 schema
- `F-573` / `F-575` 到 `F-580` 已把 group create/member/role/transfer/profile schema 的冲突字段和 extra forbid 收口
- `F-554` / `F-555` / `F-556` / `F-752` 已把 `/groups/{id}/me` 收口为 self-scoped canonical payload，空/no-op 请求不再写 member profile、不再 touch shared session，群昵称变更也不再扇出 shared `group_profile_update`
- `F-753` 已把群公告副作用纳入 `PATCH /groups/{id}` 正式响应，返回 `{group, announcement}` 并保留公告 message id / created / participant_count meta
- `F-754` 部分收口：`DELETE /messages/{id}` 已从 `204` 改为返回 committed `message_delete` event payload；send/list 与 edit/recall 的主 contract 仍待统一
- `F-755` / `F-756` 已把 read batch 成功响应收口为稳定 `{status, session_id, message_id, last_read_seq, user_id, read_at, advanced, noop, event_seq}` shape，并显式区分 no-op
- `F-757` / `F-758` 已为 `MessageReadBatch` 增加 extra forbid、strip、非空和长度约束
- `F-759` 已把 `GroupCreate.member_ids/members` item 级 strip、非空、长度和去重下沉到 schema
- `F-567` / `F-581` / `F-582` / `F-585` 已把 friend request target、extra forbid 和 message 长度约束收口到 schema
- `F-764` 已把 `DeviceKeysRefreshRequest` 的 key material 必填约束下沉到 schema
- `F-767` 曾把 HTTP typing ack 对齐到 realtime canonical event payload；后续 `R-005` 已进一步删除 HTTP typing ack，typing 只保留聊天 WS 正式入口
- `F-564` 已把群公告消息广播改为按每个 viewer 单独序列化，不再复用第一个收件人的 viewer-specific payload
- `F-783` 已把 session `unread_count` 接到服务端权威未读计数
- `F-784` / `F-785` 已移除服务端 session/message payload 中没有权威语义的 `session_crypto_state` / `is_ai` dummy 字段
- `F-777` 已移除 message payload 顶层 `timestamp` 同义字段，时间语义统一到 `created_at` / `updated_at`
- `F-778` / `F-779` 已把 message read/viewer 派生字段从 `extra` 移出，只保留在顶层 canonical 字段
- `F-786` / `F-787` 已把 recalled session preview / message content 从空字符串收口为稳定 formal 占位
- `F-565` / `F-566` 已把 session `last_message` preview 收口为 formal 输出，加密文本返回密文占位，附件返回类型化占位
- `F-788` 已把单会话历史分页从 `created_at` cursor 收口为 `before_seq` / `session_seq` cursor，并同步客户端远端回拉与恢复补偿
- `F-789` 已把缺失消息补偿排序改为同一会话内 `session_seq` 优先
- `F-793` 到 `F-797` 已把公开用户摘要、avatar 字段语义、friend request participant contract 和 `user_profile_update` user-scoped realtime payload 收口
- `F-765` 已把 user route 家族拆成 collection envelope、public user detail 和 `/auth/me` self detail 三套正式 contract
- `F-751` 已把群 mutation route 家族统一到 `{group, mutation}` contract，删除/离群/成员变更不再混用裸 group、`status` 或 `204`
- `F-087` 到 `F-096` 已收缩 presence/JSON heartbeat 死路径，补齐 `error`、`force_logout`、`contact_refresh` 与 profile update 的正式实时协议文档，并为联系人域补 reconnect authoritative reload
- `R-003` 已把 WS `chat_message` 主链路收敛到 `MessageService.send_websocket_message()` 单一编排入口，gateway 不再重复查 session/member/message
- `R-004` 已把已读主路径收敛为 HTTP `/messages/read/batch`，删除客户端 WS `read_ack` 发送入口，服务端 WS 对 `read_ack/read` 统一返回 unsupported
- `R-005` 已删除 HTTP typing route 和 `SessionTypingRequest`，typing 只保留聊天 WS 正式入口
- `R-007` 已让离线 `history_events` 的 edit/recall 回放不再依赖本地已有原消息，缺失缓存时按 event 生成本地权威占位消息
- `R-008` 已把 HTTP edit/recall 的 sender-side 边界收口为“HTTP 响应更新本地、realtime fanout 只发其它成员”，避免 actor 用户重复处理回广播
- `R-027` 已把 `_fetch_remote_messages()` 从逐条 `get_message()` 改为批量 `get_messages_by_ids()`，并把整页重写收口为 delta write
- `R-059` 已为 E2EE envelope 增加 sender/recipient active device 绑定校验，并要求 group fanout 的 sender device/key 与顶层 envelope 一致
- `R-060` 已把 `MessageSendQueue.stop()` 从直接取消改为先 drain，超时取消时对 in-flight / queued 消息显式回传失败
- `R-061` 已随 `R-027` 关闭：远端历史页本地 existing-message 查询改为批量 `get_messages_by_ids()`
- `R-064` / `R-065` 已把 `get_messages()` 回源条件改为显式 freshness 策略：`force_remote` / `before_seq` / 本地不足页才回源，首屏满页不再固定请求远端
- `R-078` / `R-079` 已把缺失消息和缺失事件补偿查询从按 session 拼 `OR` 改为 `session_id.in_(...)` + `CASE` cursor 表达式
- `R-096` 已随 `F-783` / `F-784` / `F-785` 关闭：formal payload 不再暴露 `session_crypto_state` / message `is_ai` dummy，占位 `unread_count` 已替换为权威未读计数
- `R-097` 已随 `F-788` / `F-789` / `R-078` 关闭：历史分页和 reconnect 缺失消息补偿收口到 `session_seq` authoritative order
- G-01 已关闭：HTTP/WS 正式入口、mutation output、E2EE envelope、文件/用户/relationship 与 reconnect/history 边界已按本簇范围收口或补记为关闭

合并范围：

- `F-005`
- `F-006`
- `F-008`
- `F-011`
- `F-015`
- `F-017`
- `F-023`
- `F-269`
- `F-270`
- `F-298`
- `F-389`
- `F-390`
- `F-391`
- `F-392`
- `F-393`
- `F-394`
- `F-395`
- `F-396`
- `F-399`
- `F-400`
- `F-401`
- `F-402`
- `F-403`
- `F-404`
- `F-405`
- `F-406`
- `F-407`
- `F-408`
- `F-409`
- `F-410`
- `F-411`
- `F-412`
- `F-418`
- `F-419`
- `F-420`
- `F-421`
- `F-422`
- `F-423`
- `F-424`
- `F-425`
- `F-426`
- `F-427`
- `F-428`
- `F-429`
- `F-443`
- `F-444`
- `F-445`
- `F-446`
- `F-447`
- `F-458`
- `F-459`
- `F-517`
- `F-518`
- `F-519`
- `F-520`
- `F-529` 到 `F-538`
- `F-549`
- `F-550`
- `F-569`
- `F-570`
- `F-571`
- `F-572`
- `F-590`
- `F-591`
- `F-592`
- `F-593`
- `F-617` 到 `F-635`
- `F-667` 到 `F-670`
- `F-712` 到 `F-717`
- `F-721` 到 `F-727`
- `F-728` 到 `F-747`
- `F-751`
- `F-753` 到 `F-758`
- `F-760`
- `F-764`
- `F-765`
- `F-767`
- `F-783` 到 `F-789`
- `F-793` 到 `F-797`
- `F-702` 到 `F-707`
- `F-564`
- `F-565`
- `F-566`
- `F-087` 到 `F-096`
- `R-027`
- `R-003`
- `R-004`
- `R-005`
- `R-007`
- `R-008`
- `R-064`
- `R-065`
- `R-059`
- `R-060`
- `R-061`
- `R-078`
- `R-079`
- `R-096`
- `R-097`

共同根因：

- HTTP / WS 两套入口长期并存，但没有清晰的“谁是正式入口”
- 请求级幂等、ACK、错误返回、事件补偿、控制消息这些正式协议要素没有统一建模
- 部分真实主链路事件已经被客户端和服务端依赖，但文档仍停留在旧协议面

典型表现：

- G-01 已关闭：HTTP / WS 正式入口、mutation output、E2EE envelope、文件/用户/relationship、reconnect/history 边界已按本簇范围收口。
- 后续若引入服务端 sender-key registry 或设备级 signaling，会作为新的问题簇继续跟踪，不再阻塞本次 G-01 关闭。

建议优先动作：

- 先明确“消息与控制面”的正式协议边界：哪些只能走 WS，哪些允许 HTTP。
- 再统一请求级幂等键、错误返回模型、实时 fanout 和 reconnect 补偿模型。
- 文档、服务端、桌面端必须一起收口，不要继续接受“协议里一种、实现里另一种”的状态。

### G-02：会话删除 / 本地隐藏 / 全量刷新三套语义分裂

状态：closed（2026-04-14）

关闭说明：

- 客户端已把 session tombstone、authoritative upgrade、startup history warmup、sidebar/search reopen、current-session active、删除后的消息/附件/E2EE/sync cursor/runtime cache 清理收口到同一套 contract
- fallback session 现在可以被 authoritative snapshot 升级；self-sent direct fallback 不再退化成“只有自己”的 participant 集，也不会再把缺失 lifecycle 时间伪装成有效活动
- 服务端已移除 `DELETE /api/v1/sessions/{session_id}` 硬删除入口；`create_private(existing)`、call signaling、message/sync visibility、session list group metadata 都改为复用统一的 authoritative visibility / membership / bulk-load contract
- `ChatInterface` 的通话结果消息 dedupe 状态改成有 TTL 和容量上限的有界缓存，不再是进程级只增不减集合
- 回归已覆盖：
  - `client/tests/test_service_boundaries.py`
  - `client/tests/test_ui_boundaries.py`
  - `server/tests/test_session_service.py`
  - `server/tests/test_call_api.py`
  - `server/tests/test_message_service.py`
  - `server/tests/test_chat_api.py`

合并范围：

- `F-012`
- `F-025` 到 `F-041`
- `F-259` 到 `F-263`
- `F-264` 到 `F-266`
- `F-267`
- `F-268`
- `F-370` 到 `F-373`
- `F-354` 到 `F-364`
- `F-307`
- `F-308`
- `F-311`
- `F-312`
- `F-313`
- `F-314`
- `F-584`
- `F-324`
- `F-659`
- `F-660`
- `F-661`
- `F-748`
- `F-074`
- `F-075`
- `F-077`
- `F-304`
- `F-305`
- `F-539` 到 `F-542`
- `F-718`
- `F-800`
- `F-801`
- `F-808`
- `F-809`
- `F-810`
- `F-812`
- `F-814`
- `F-817`
- `F-818`
- `F-819`
- `F-822`
- `F-835`
- `R-009`
- `R-010`
- `R-011`
- `R-012`
- `R-049`
- `R-050`
- `R-076`

共同根因：

- 产品语义已经把“删除会话”定义成“本地隐藏 / 清除本地记录”
- 但客户端数据库、窗口内存缓存、后台任务、同步游标、附件缓存、E2EE 材料并没有围绕这个语义统一清理
- 同时 `ensure_remote_session()`、`ensure_direct_session()`、history replay 这些旁路还会绕开 tombstone 语义，直接把会话重新 unhide / add 回本地 cache
- 连 `refresh_remote_sessions()` 和 `add_session()` 这两个核心入口本身，也没有把“authoritative refresh 失败”和“会话可见性 gate”收成统一 contract
- UI startup warmup 也没有跟 authoritative session snapshot 绑定，旧 prefetch task 可以继续给已移除会话回填 history cache
- 消息侧 fallback session 一旦先落进 `_sessions`，后续 `ensure_remote_session()` / `ensure_direct_session()` 又会直接短路，临时 session 没有 authoritative 升级路径
- self-sent direct fallback session 甚至可能把成员列表退化成“只有当前用户自己”，从而连按对端重新发现、发加密消息、发起直接通话这些主路径都一起带坏
- fallback session 还会直接把首条消息时间伪装成 `created_at/updated_at`，继续污染会话生命周期排序
- 同时服务端仍保留全局硬删除 direct 会话接口

典型表现：

- 删除后会话、消息、附件、草稿、滚动状态、history cache、read cache、prefetch task 还能复活
- 全量刷新移除会话时，消费者收不到等价删除语义
- 本地隐藏 tombstone 会被后续资料更新、搜索结果、远端 fetch 等旁路重新翻出来
- 侧边栏搜索、托盘跳转、联系人发起聊天、history sync 都能绕过 tombstone，直接复活本地已删会话
- live message 和 history sync 现在都会先 `unhide_session()`，把“补消息”直接变成“取消本机隐藏”
- `/sessions/unread` 也没有复用 direct 可见性 gate；已被 visibility 模型隐藏的异常私聊仍可能继续贡献 ghost unread
- `/messages/unread` 的全局总未读也没有复用同一套 gate，隐藏异常直聊还能继续贡献 badge total
- `add_session()` 本身也没有 hidden/tombstone gate，任何后台 fetch/build 只要拿到 session 对象都能重新写回本地
- `ensure_remote_session()` 命中已有 cache 后会直接短路，fallback/stale session 并不会自动升级成 authoritative snapshot
- direct session create 自身的 contract 也不稳定：请求里带的 `name` 在“命中已有私聊并复用返回”这条正式路径上会被静默忽略
- 同时这条 `name` 在“真正创建新直聊”时又会被直接写成 shared `session.name`；direct display 和 shared session naming 语义并没有正式收口
- 命中既有 direct session 时，create-direct 返回值还会直接信任这次请求归一化出来的 `participant_ids`，而不是重新读取现存 session 的 authoritative membership
- 命中既有 direct session 时也没有 `created/reused` 语义；“新建成功”和“只是返回已有对象”仍共用同一种成功 contract
- self-sent fallback direct session 会稳定退化成泛化标题，直到 authoritative 会话快照到达前都无法显示真实对端名称
- 客户端本地 `SessionEvent.CREATED` 还会把“按需 fetch 回旧会话”伪装成“正式创建了一个新会话”
- 侧边栏 full reload 连空 authoritative snapshot 都收不进去，ghost sessions 会继续残留
- 重复的本地 `SessionEvent.CREATED` 还会把同一个 session 直接插成多行
- 单纯 `select_session()` 就会清掉 `@我` 标记，而不要求会话真的前台可读
- unread snapshot 缺项会被直接当成 `0`，把“未知”和“已读完”混成一类
- `refresh_remote_sessions()` 失败时还会把 stale 本地 sessions 冒充成新 snapshot，未读数端点失败甚至会把整轮 refresh 直接打断
- `refresh_remote_sessions()` 还会把“单条 session payload 解析失败”直接折叠成“这条会话不在 authoritative snapshot 里了”，随后把本地现有会话静默移出
- 全量 refresh 的 normalize pipeline 还有确定性的重复工作：
  - `_build_session_from_payload()` 逐条先做 members decorate / crypto annotate / display normalize
  - `_replace_sessions()` 随后又对整批 session 再做一遍同样的工作
- 这条重复 pipeline 还会把 E2EE 本地状态查询放大成 N+1：
  - `get_local_device_summary()`
  - direct peer identity summary
  - group sender-key reconcile
  都会先按单条 session 跑一遍，再在 batch replace 里重复
- 同一条 pipeline 还会把联系人 overlay 查询放大成按 session 的重复 contacts cache lookup
- direct 可见性 contract 到消息链也还是分裂的：
  - `list_messages()` 只看 membership，不复用 `_is_visible_private_session()`
  - `sync_missing_messages()` / `sync_missing_events()` 也会继续把已被 direct 可见性模型隐藏的会话拉进补偿
- HTTP typing 正式入口已在 `G-01` 收口时删除，typing 只保留聊天 WS 入口
- 消息和已读 mutation 链的 private-session visibility gate 已在 `G-01` 收口：
  - `send_message()` / `send_websocket_message()` 复用 visible session membership
  - `read_message_batch()` 复用 visible session membership，WS `read_ack` 已删除
  - `edit()` / `recall()` / `delete()` 复用 visible session membership
- 通话 mutation / signaling 链也还没复用同一套 visibility gate：
  - `call_invite`
  - `accept/reject/hangup`
  - `offer/answer/ice`
  仍允许已被 visibility 模型隐藏的异常直聊继续产出 ghost call lifecycle
- private session 的 visibility gate 在 session service 正式入口上也还没贯穿：
  - `get/list` 会把异常直聊当成 404 / 不可见
  - `delete_session()` 却仍允许继续 mutation
  - `create_private(existing)` 也还会把同一条异常直聊重新取回
- `DELETE /sessions/{id}` 也和群删除一样，只回 `204`，没有任何 authoritative session removal / tombstone payload
- startup history warmup 是一次性批次；任务运行期间出现的新高优先级会话不会被重新排入
- startup history warmup 还是 fail-fast 的，一条坏 session 会把整批预热直接打断
- current session active 的异步更新不带 session_id，晚到任务会把 unread/read 状态打到别的会话上
- `add_session()` 自己不做 visible/tombstone gate，导致任何新调用点都可能再次绕开本地删除语义
- 启动期 history prefetch 不会随着最新 session snapshot 重排，旧会话还能继续被后台预热
- manager 还允许把一个并不存在的 session_id 设成 current selection，后续 read/unread 逻辑会围着 ghost session 继续跑
- `open_session()` / `open_direct_session()` 遇到“manager cache 里已有 session、sidebar model 里没有”的漂移时，也不会主动把该 session 重新 upsert 回 UI 模型
- authoritative session list 自身在 group session 分支上也仍保留 per-session group/member/avatar 回查

建议优先动作：

- 先决定“删除会话”的正式语义，只保留一种
- 再把数据库、内存缓存、异步任务、游标、附件文件、E2EE 材料统一收口到同一套删除 contract
- 不要再允许搜索、refresh、warmup、prefetch、ensure、history replay 这些旁路把已删会话复活
- 把“本地 cache add”和“正式会话生命周期创建”拆成不同事件语义
- `refresh_remote_sessions()` 必须显式区分“刷新成功”“附属 unread 降级”“刷新失败仍在用 stale cache”
- 把 visible/tombstone 判断下沉到统一 add/remember path，避免继续依赖调用方自觉
- UI warmup / history prefetch 也必须挂到当前 authoritative session set 上，不能再预热已经被移除的会话

### G-03：authenticated runtime 没有真正按账号隔离，logout / relogin / restore 全部依赖局部手工清理

状态：已修复（2026-04-13）

修复进展：

- `F-044` 到 `F-086`、`F-191` 到 `F-258` 已把 logout、auth-loss、restore、relogin、startup preflight、runtime ready、transport close、auth commit boundary、UI transient 等主链路分阶段收口。
- `F-673` / `F-674` / `F-675` 已把服务端 auth mutation 与 realtime 副作用边界收口：logout 提交后断连/广播失败不再把已生效 logout 改成 500，force login 先断旧 runtime 再旋转新 session 版本，注册链用户创建/默认头像/session version 已统一为单事务。
- `F-719` / `F-720` 已把 username identity 的大小写语义收口：注册/登录/查重统一走 lowercase canonical username，数据库侧新增 `uq_users_username_lower` 表达式唯一索引。
- `R-091` / `R-092` / `R-093` 已收口服务端 auth 侧横切风险：限流 key 纳入请求主体维度，默认 rate limit store 改为共享数据库计数，默认 CORS 不再使用 `* + credentials=True`。
- `R-014` 到 `R-026` 已完成尾部架构项收口：顶层 lifecycle state/runtime generation guard 成为 runtime 推进边界；logout/auth-loss/relogin 使用 quiescent teardown；账号域 controller/manager/service singleton 在 close 后退休并由下一代 runtime 重建；ChatController ICE/TURN 缓存、sync cursor batch、E2EE local bundle batch、shell UI task quiesce 都已补回归测试。

合并范围：

- `F-042` 到 `F-086`
- `F-191` 到 `F-258`
- `F-673` 到 `F-679`
- `F-688` 到 `F-691`
- `F-719`
- `F-720`
- `R-014` 到 `R-026`
- `R-091`
- `R-092`
- `R-093`

关闭结果：

- G-03 推荐顺序中的五步已经闭合：顶层 lifecycle state/runtime generation guard、auth commit boundary、quiescent teardown、统一 bootstrap contract、app-level transient 清理均已在本簇内完成一轮实现和回归覆盖。
- 普通 logout、auth-loss forced logout、logout relogin、cold start restore 都走统一的 auth/runtime lifecycle：旧 shell 先进入 runtime transition，旧 runtime generation 失效并 quiescent，auth/session 清理完成后才允许下一代 authenticated runtime bootstrap。
- authenticated runtime 对象图不再依赖关闭后原地复用：Chat/Message/Session/Connection/WebSocket/Sound/Call/Search/Auth 及 AuthController 持有的 auth/e2ee/user/file service singleton 会在 close 后退休，下一账号重新创建对象。
- 本地 per-account 状态边界已补齐：ChatController 的 ICE/TURN 缓存会随 close 清空，sync cursor 通过 `replace_app_state()` 一次 batch 保存，E2EE reprovision 会一次替换本地 device bundle 并删除旧 group/history/trust 材料。
- async teardown 已升级：ConnectionManager 的跨线程 future、WebSocketClient 的 queued callback/worker cleanup、Application 的核心 component close gate、MainWindow 的 `quiesce_async()` 都纳入旧 runtime 退场边界。
- 验证：`client/tests` 完整通过 `376 passed`；服务端 auth 相关尾部修复完成后 `server/tests` 通过 `155 passed`。
### G-04：联系人域与本地搜索缓存没有统一 authoritative cache contract

状态：closed（2026-04-14）

修复记录：

- 客户端联系人域已收口到 controller authoritative cache：`ContactController` 新增 `persist_contacts_cache()`，联系人/请求/群三条 slice 的 realtime refresh 被拆成独立 authoritative refresh，self profile 变更会统一刷新 contacts/groups/requests。
- `AddFriendDialog` 与两处 sidebar grouped search 已补 generation guard、空关键词/失败清空旧结果、overlay 与关键词生命周期解耦；联系人详情 moments 回填改为按当前选中记录重新解析，不再复用旧快照 payload。
- 本地搜索 contract 已统一：contacts LIKE fallback 与 highlight 纳入 `display_name`，群成员预览索引改为 remark/group_nickname/username/user_id/region 的去重原始 token，不再把 `地区:` 本地化文案写入索引；message-only search 与 aggregate search 不再共享同一 mutable result 槽位。
- SQLite 搜索层已补正式自愈边界：contacts/groups/message FTS 从“只看行数”改为 `row count + integrity-check`，message FTS 不再在每次连接初始化时整表 `delete-all + reinsert`。
- 服务端联系人/用户正式入口已重构：friend request 只接受 canonical `target_user_id`，附言统一 strip，`DELETE /friends/{id}` 返回 committed payload + `changed` 语义；`GET /friends`、`GET /friends/requests`、`/users`、`/users/{id}`、`/users/search` 全部收口到 public summary contract。
- 服务端批量/事务边界已补齐：friends/requests 列表改为 bulk user load，request expiry 不再发生在纯读路径，accept/reject/auto-accept 合并为单事务提交；`/users/search` 仅匹配 `username/nickname` 且拒绝空关键词。
- avatar compat 已退出 user/friend/session/message 正式读路径；profile update route 增加 no-op 抑制，event generation 改为 bulk member lookup 后再写 session events。

合并范围：

- `F-057`
- `F-069`
- `F-098`
- `F-271`
- `R-029`
- `F-104` 到 `F-165`
- `F-749`
- `F-750`
- `F-315`
- `F-316`
- `F-317`
- `F-319`
- `F-320`
- `F-323`
- `F-342`
- `F-348`
- `F-352`
- `F-374`
- `F-375`
- `F-376`
- `F-362`
- `F-417`
- `F-431`
- `F-432`
- `F-437`
- `F-450`
- `F-451`
- `F-452`
- `F-453`
- `F-490`
- `F-491`
- `F-492`
- `F-567`
- `F-568`
- `F-581`
- `F-582`
- `F-583`
- `F-585`
- `F-586`
- `F-587`
- `F-588`
- `F-589`
- `F-598`
- `F-602` 到 `F-613`
- `F-671`
- `F-672`
- `F-684` 到 `F-687`
- `F-697` 到 `F-701`
- `F-512`
- `F-513`
- `F-514`
- `F-543`
- `F-544`
- `F-336`
- `R-028`
- `R-034`
- `R-036`
- `R-051`
- `R-052`
- `R-053`
- `R-054`
- `R-044`
- `R-046`
- `R-047`
- `R-067`
- `R-073`
- `R-074`
- `R-077`
- `R-080`
- `R-081`
- `R-082`
- `R-083`

共同根因：

- 联系人页、联系人详情、请求页、全局搜索、群搜索、本地缓存表都各自维护一份局部状态
- 连 `ContactController` 自己也不是 authoritative cache owner；很多 mutation 完成后是否写缓存仍取决于页面有没有在线补丁
- 增量更新、全量 reload、页外变更、搜索结果、弹窗快照之间没有统一缓存协议
- 很多逻辑仍然建立在“联系人页当前正开着并在线消费事件”的前提上
- 群成员本地搜索索引也没有正式 contract：remark、group_nickname、username、region 展示文本被随意裁剪、拼接和落盘

典型表现：

- 联系人 / 群 / 请求三条分支的新鲜度不一致
- controller 发起 mutation 后，本地 contacts/groups cache 仍可能完全不更新
- 联系人域大多数 realtime mutation 仍会退化成整页 full reload，而不是 slice-level authoritative refresh
- 搜索结果依赖过期缓存，资料更新后不自动重跑
- Add Friend / Create Group / 群成员管理 / 私聊建群等弹窗都把候选快照冻结成打开时刻
- Add Friend 自己的搜索链也没有 generation guard，晚到旧结果仍可能覆盖当前关键词结果
- Add Friend 搜索失败或空关键词时也不会清空旧结果，错误态和上一轮结果会一起残留
- 联系人页的选中态、详情态、reload、tab 切换、in-flight detail task 之间经常相互覆盖
- requests 分支本身还夹着逐用户补资料的 N+1 网络路径
- 好友请求 / 删除好友这两条正式入口本身的 target / success contract 也不清晰：
  - friend request payload 同时接受 `receiver_id` 和 `user_id`，冲突时会静默偏向一个
  - remove_friend 即使本来就不存在 friendship，也会返回成功并广播 removal realtime
- send-request 自身也没有把 mutation 结果类型收口：
  - 命中已有 outgoing pending 时仍伪装成普通成功
  - 命中 incoming pending 时会直接 auto-accept，但公开响应仍继续复用 request payload
- friend request schema 自己也还没有把“target 必填”和“禁止未知字段”建在入口层
- friend request 域自己的 mutation boundary 也还没收口：
  - request `message` 没有正式长度边界
  - `GET /friends/requests` 会在读路径里直接把 pending 改成 expired
  - 这类读路径过期又不会配套 `contact_refresh`
  - auto-accept / manual accept 还都把“request accepted”和“friendship created”拆成多个 repo 级提交
  - send-request preflight 也会先顺手改旧请求状态
- friend route 还继续把 mutation success 和 `contact_refresh` side-channel fanout 绑在一起：
  - `send_request()` 已提交 request/auto-accept 后，fanout 失败仍会报 500
  - `accept_request()` / `reject_request()` / `remove_friend()` 也都是先 commit、后 fanout
  - `GET /friends` 还会把 email / phone / birthday / signature / status 这类更接近完整 profile 的字段直接暴露给所有好友
  - `GET /friends` 与 `GET /friends/requests` 都会在纯读路径里触发 avatar backfill 写库
  - `GET /friends/requests` 也没有分页边界，仍是 sent/received 全历史一把返回
  - friend request `message` 还没有 strip/empty-to-none 归一化，纯空白附言会被当成正式内容保存
  - `/friends`、`/friends/check`、request mutation、`DELETE /friends/{id}` 也继续各自长出一套不同返回风格，relationship formal contract 没有统一
- user discovery / user profile 这条正式边界同样没收口：
  - `/users/search`、`/users`、`/users/{id}` 都直接暴露完整 profile，而不是 public summary
  - search 还接受空关键词枚举目录，并把 `email/phone` 纳入匹配字段
  - `/users` 甚至没有分页或 size 边界
- user/profile 读路径还夹着 avatar compat 写操作：
  - `list/search/get user`
  - `friend/session/message` 序列化
  - 都可能在读路径里触发 `backfill_user_avatar_state()`
  - 这条 compat 迁移已经扩散成多条正式 read path 的写放大
- profile update event generation 也还不成熟：
  - no-op `PUT /users/me` 仍会广播 `user_profile_update`
  - event 构造会按 session 数量 N+1 回查成员
  - 同一份 profile payload 也会按 session 数量重复写入 event 流
- profile mutation route 也还是“先 commit、后 fanout”的 split contract：
  - `update_me()` 已提交资料后，profile fanout 失败仍会把 HTTP 请求打成 500
  - `upload_me_avatar()` / `reset_me_avatar()` 也是在 avatar state 和群头像 side effect 成功后，再因为 fanout 失败把请求报成失败
- 客户端联系人域还会把这些完整 profile 继续落本地：
  - contacts cache 会把完整好友 payload 原样塞进 `extra`
  - requests 补名又会逐个拉完整 `/users/{id}` profile
  - `_load_request_user_names()` 还是无上限并发 fanout
- 当前用户资料变化后，联系人页实际上只刷新 groups slice，outgoing requests 等 self-facing 视图仍会停在旧资料
- realtime request upsert 也没有统一排序 contract，新请求和状态更新都可能把 requests 页顺序打乱
- request 详情在 `counterpart_id` 缺失时还会把全局 moments 时间线错贴到该请求上
- 联系人搜索的计数和可渲染结果也不是同一口径，count 能算出来，UI 却可能一条都画不出来
- grouped message search 每个会话只保留第一条命中卡片，后续更好的命中只会涨计数不更新代表性 snippet
- grouped message search 还会先按 raw message 条数限流，再按 session 聚合；一个会话 hits 太多时，其它命中会话会在聚合前就被截掉
- `AddFriendDialog` 的搜索摘要还会把“Already Friends”这类禁用结果一起算进“找到 N 个用户”
- 联系人本地搜索在 FTS、LIKE fallback、highlight、section total、最终 card 渲染几层之间字段集合都不一致
- contact LIKE fallback 现在仍漏掉 `display_name`
- 群搜索命中 `member_search_text` 时，manager 还会把真实命中的成员文本退化成 `Group member match` 这种占位文案，高亮元数据也随之失真
- 群搜索即使命中的是群名，card 也会把命中信息藏掉，只显示成员数摘要
- 群成员搜索索引只保留一个首选展示字段，成员 remark、group_nickname、username/user_id 会因为别的展示名存在而被直接丢掉
- 群成员 region 还会把本地化展示字样直接混进 `member_search_text`，导致索引语义和当前 UI 语言绑定
- 联系人搜索区块的 `more(count)` 也可能大于最终可渲染条目数，展开后依旧看不全
- 全局搜索 overlay 的 `more(count)` 现在也只会展开当前内存页，不会真正增量拉取 `count` 所暗示的剩余结果
- Add Friend 这类 mutation 弹窗一旦在请求提交后被关闭，本地 requests/sidebar 更新还会直接丢失
- 联系人页的 full reload 和 incremental patch 也没有 generation / sequencing 约束，晚到任务仍可能互相覆盖
- 两侧边栏的 grouped search 还没有 generation guard；同关键词的旧任务只要晚到，就还能把新结果冲回去
- 全局搜索 overlay 自己也没有正式的 loading/close state reset contract；旧关键词和旧结果快照会在组件内部残留
- message search 还会把 recall notice 当普通文本内容入索引，用户能搜到大量“消息已撤回”占位文案
- `SearchManager.search_all()` 会顺手改写 `_current_results`；aggregate search 和 message-only search 继续共用一份 singleton 可变状态
- aggregate search 输入空关键词时也会直接清整个 singleton 的缓存槽位，不区分当前 consumer
- `highlight_ranges` 现在仍是原文坐标，而 `matched_text` 早已被裁成 snippet；这套高亮 metadata 自身就是失真的
- contacts/groups FTS 的自愈又只看 row count，message FTS 则反过来在 startup/connect 时每次都整表重建，搜索层既不稳也不省

建议优先动作：

- 定义联系人域 authoritative cache：谁负责持久化，谁负责增量更新，谁负责 reload
- 把 contacts/groups cache owner 从页面逻辑收回到 controller/domain 层
- 把 `contact_refresh` 至少拆成 contacts / requests / groups 三个 slice 的正式 refresh contract
- 搜索结果必须绑定缓存更新与重新计算，不要继续依赖页面是否在线
- 明确联系人/群搜索的正式索引字段 contract，不要再让 display field、remark、group_nickname、username、region 标签各自随缘入索引
- 把弹窗候选集和详情页状态从“一次性快照”改成可刷新数据源
- 群成员管理窗口也应提供正式 retry / refresh 路径，避免一次失败就整窗报废
- requests 列表接口和客户端补资料逻辑也要一起收口，避免继续用 N+1 网络补全基础展示字段

### G-05：群/会话生命周期和成员变更没有进入正式实时/补偿模型

合并范围：

- `F-099`
- `F-100`
- `F-101`
- `F-102`
- `F-117`
- `F-118`
- `F-272`
- `F-273`
- `F-274`
- `F-275`
- `F-306`
- `F-321`
- `F-343`
- `F-344`
- `F-515`
- `F-516`
- `F-551` 到 `F-563`
- `F-761`
- `F-762`
- `F-763`
- `F-751`
- `F-752`
- `F-753`
- `F-759`
- `F-614`
- `F-615`
- `F-653` 到 `F-658`
- `F-662` 到 `F-666`
- `F-798`
- `F-799`
- `F-803`
- `F-804`
- `F-806`
- `F-811`
- `F-821`
- `F-823`
- `F-825`
- `F-826`
- `F-829`
- `F-833`
- `F-834`
- `F-836`
- `F-837`
- `F-838`
- `F-842`
- `F-843`
- `F-637` 到 `F-650`
- `F-599`
- `F-600`
- `F-601`
- `F-329` 到 `F-338`
- `R-038`
- `R-075`
- `R-084`
- `R-085`
- `R-086`
- `R-087`
- `R-088`
- `R-094`

共同根因：

- 当前只有消息和少数资料更新进入了正式 realtime / history_events 模型
- 群成员、群角色、所有权、建群、删群、建私聊、删会话这些真正的领域生命周期动作没有正式事件
- 于是很多页面只能靠发起端 HTTP 返回值或联系人页在线刷新来本地 patch
- 群成员管理弹窗上的“批量加人”“踢人后补拉快照”“窗口内权限判断”也都建立在一次性快照和局部补丁之上，没有正式 authoritative contract

典型表现：

- 群成员变化、角色变化、所有权转移在其它设备和其它在线成员侧都没有正式收口
- 建群 / 删群 / 建私聊 / 删会话在跨设备和断线重连场景下没有生命周期补偿
- 聊天页做的群操作是否能同步回联系人域，还依赖联系人页是否恰好在线
- 群资料 / self-profile 正式边界本身也没有收口：
  - 建群和共享资料更新都允许空群名
  - shared no-op PATCH 仍会照样发 shared realtime 事件
- 建群入口自身的 payload contract 仍有剩余分裂：
  - `member_ids` 和 `members` 两个入口名仍同时存在，虽然 schema 已拒绝冲突 payload
  - 空成员集仍能建出“只有自己”的群
- self-only group profile 语义和 shared group profile 语义还在互相污染：
  - shared `members[]` 甚至会把每个成员的私有 `group_nickname` 一起广播出去
  - shared `group_profile_update` payload 里甚至仍保留 `group_note/my_group_nickname` 这种 self-scoped 字段，只是当前退化成空字符串
  - shared profile update 也还会在每次 name/announcement 变更时内联完整 `members[]` roster，把 profile delta 和成员快照混成一条事件
- group profile / self-profile 的 canonical snapshot 也没有定格：
  - `update_group_profile()` 先向 HTTP 调用方返回一份 group snapshot
  - route 随后又重新序列化一次当前 group，单独生成 `group_profile_update` event payload
  - `update_my_group_profile()` 已改为 self payload，但 self-profile HTTP response 与 history/realtime event 仍是 route 层分步构造
  - 同一次 mutation 的 HTTP response、history event、realtime fanout 不保证描述的是同一份状态
- 同一次 `update_group_profile()` 里，群公告消息广播和 `group_profile_update` 还会各自使用不同时间点取得的 participant roster；两条 realtime 链甚至可能打到不同成员集
- 群公告消息现在还会先于 `group_profile_update` 发出；客户端公告 banner / viewed-version 状态却只会在 session 侧公告 metadata 到达后更新，公告内容和公告版本因此继续分裂
- `update_group_profile()` 给 actor 的 route response 还继续复用 viewer-scoped `serialize_group(..., current_user_id=current_user.id)`
- `create_group()` 作为 shared create mutation，也从第一份正式返回开始就直接复用 viewer-scoped `serialize_group(..., current_user_id=current_user.id)`
- 同一次 shared mutation 的 HTTP 返回与 shared event payload 因此连视角都不一致：前者夹带 actor 的 `group_note/my_group_nickname`，后者则是 `current_user_id=None` 的 shared 视图
- 这类 actor-view response 漂移也不只存在于 `PATCH /groups/{id}`：
  - `add_member()`
  - `update_member_role()`
  - `transfer_ownership()`
  这三条 shared mutation 也继续直接返回 `serialize_group(..., current_user_id=current_user.id)`，把 shared lifecycle mutation 和 actor-only detail 混在同一份正式输出里
- 连 `GET /groups/{id}` 这条 detail route 也不是纯 shared detail：当前详情 payload 仍直接夹带 `group_note/my_group_nickname`
- `GET /sessions/{id}` 这条 session detail route 也一样继续夹带 `group_note/my_group_nickname`，session detail 与 group detail/self-detail 的边界并没有真正分层
- shared `members[]` 本身也没有单独的 canonical member-summary contract：
  - `serialize_group().members[]` 直接带 `username/nickname/avatar/gender/region/role/joined_at`
  - `serialize_session().members[]` 又是另一套 `username/nickname/avatar/gender/role/joined_at`
  - `/groups`、`/groups/{id}`、`/sessions`、`/sessions/{id}` 和多条 shared mutation 现在都在复用这两套漂移中的成员资料切片
- group authoritative snapshot 也还在掩盖 group/session membership drift：
  - 群鉴权只看 `SessionMember`
  - 缺失 `GroupMember` 时会在 shared payload 里伪造默认 role
  - `member_count` 也继续按 `SessionMember` 计算
- 用户资料变化对群共享视图的影响也没有进入正式模型：
  - 普通 profile edit 不会刷新依赖成员头像/昵称的 generated group avatar
  - avatar upload/reset 虽然会改 group/session avatar，但不会配套广播 `group_profile_update`
  - avatar 变更还会同步重建该用户参与的全部 generated group avatar，profile mutation path 继续夹着重型群侧 side effect
- 群/会话/消息三条序列化链对用户 avatar 的 authoritative 口径仍然不一致：
  - `serialize_session()` 会在成员列表和 counterpart 摘要里直接 `backfill_user_avatar_state()`
  - `serialize_message()` 也会在 sender profile 读路径里直接 backfill
  - `serialize_group()` 却只对原始 user 调 `resolve_user_avatar_url()`，不先规范化
  - 生成 group avatar 时 `_group_member_avatar_payload()` 也还是直接吃原始 user 视图
- 群与会话序列化读路径自己也还在做写操作：
  - `serialize_group()` / `serialize_session()` 会在普通 GET/list 时调用 `ensure_group_avatar()`
  - `ensure_group_avatar()` 又会把 `session.avatar` 镜像写回数据库
- 普通读请求因此会夹带 group avatar 生成、文件 I/O 和 DB flush
- 写路径里的群生命周期 mutation 也还继续夹带同类 cross-resource side effect：
  - `create_group()`
  - `add_member()`
  - `remove_member()`
  - `leave_group()`
  这些事务动作里都会直接 `ensure_group_avatar()`
- 反过来 `delete_group()` 又完全没有对应的 avatar/file 资源清理 contract；删群后 custom/generate group avatar 资产都可能变成 orphan
- `create_group()` / `add_member()` / `leave_group()` 同一次请求里还会重复跑两遍 `ensure_group_avatar()`：事务动作里先做一次，返回 `serialize_group()` 时又立刻再做一次
- generated group avatar 版本文件也没有回收策略；每次 `avatar_version` bump 都会留下新的 `..._vN.png`，历史版本长期残留
- 于是 group membership DB mutation 和 avatar 文件生成/会话镜像更新继续被绑在同一事务动作里，但并没有统一原子边界
- group avatar 文件生成本身也没有正式并发边界：
  - `build_group_avatar()` 直接覆盖目标 PNG
  - 没有临时文件 + 原子替换
  - 也没有文件锁或生成幂等保护
- 这些读路径写入还不是稳定的写事务边界：
  - `serialize_group()` / `serialize_session()` 只是在外层已有事务时顺手改内存对象
  - 真正何时 `commit()` 取决于后面是否还有别的写路径
  - 同样一次 GET/list，是否真的把 avatar 镜像写回库并不确定
- `session.updated_at` 在群生命周期上也已经失去 authoritative 语义：
  - `update_avatar()` 不推进 `updated_at`
  - add/remove/leave 不推进 `updated_at`
  - role/transfer 也不推进 `updated_at`
- 这意味着 `session.updated_at` 已经不能可靠表达“群共享视图有没有变化”：
  - 群头像、成员、角色、owner 变化都可能不推进 freshness
  - 但普通 GET/list 又会因为生成头像在读路径里偷偷改写 session
- `GroupRepository.update_member_role()` / `update_member_profile()` 仍会在“更新”路径里自动补建缺失的 `GroupMember`
- `remove_member()` / `leave_group()` 也不会检查 group/session 两侧删除结果；group drift 会被静默当成成功路径
- `update_member_role()` / `transfer_ownership()` 也会借 repo 自动补建逻辑把 group drift 静默修回去
- group profile / self-profile event 现在还是“先 append+commit，再 route 层 websocket fanout”的 split-phase 结构
- 群公告消息和 `group_profile_update` 也不是一个原子广播步骤
- `group_member_version` / `member_version` 现在只按 user id 集合哈希，role / owner 变化不会推进版本
- 而且这些“成员版本”和成员时间线本身也还没绑定真正的 group authoritative 成员表：
  - `serialize_group()` 的 `member_version/group_member_version` 仍按 `SessionMember` 计算
  - `serialize_session()` 的 `group_member_version` 也按 session membership 计算
  - `serialize_group().members[].joined_at` 也取自 `SessionMember`，不是 `GroupMember`
- group profile / self-profile 的 HTTP route 也还是“先 commit、后 fanout”的 split contract：
  - `update_group_profile()` 已提交后，公告广播或 `group_profile_update` 任一步失败都会把请求打成 500
  - `update_my_group_profile()` 也会在 self/shared fanout 失败时把已成功 mutation 报成失败
- 群 formal route output 也没有统一：
  - 有的直接回 `group`
  - 有的回 `{\"status\",\"group\"}`
  - 有的只回 `{\"status\"}`
  - 有的直接 `204`
- `remove_member()` 现在只回 `204`，actor 端 authoritative 收口被迫依赖第二次 `fetch_group()`
- `leave_group()` 也只回 `{\"status\":\"left\"}`，客户端只能本地删 session 再手工刷新联系人页补闭环
- `delete_group()` 同样只回 `204`，没有任何 authoritative tombstone / removal payload
- 桌面端甚至没有 `delete_group` 的 service/controller/UI 边界；服务端 destructive route 继续处于游离状态
- 群成员管理窗口里的“批量加人”并不是原子操作；中途失败会留下部分成功、当前窗口却还是旧快照
- 群成员管理窗口在打开期间不会跟随权威 group 变化，成员列表和 owner/admin 权限会逐步过期
- 群成员管理窗口连好友候选加载失败都只会落日志，关键入口缺少正式错误反馈
- 群成员管理窗口里的好友候选缓存还是一次性快照，后续甚至会错误提示“没有更多好友可添加”
- 添加成员 picker 还绑定在顶层窗口上，源管理弹窗关闭后 picker 仍可能继续悬挂
- busy 状态也没有锁住成员行操作；第二个 mutation 点击还能直接 cancel 第一个 in-flight mutation
- 两条建群弹窗的默认群名 contract 已经分裂：一条只把默认名放在 placeholder，另一条甚至始终提交空 name
- 建群弹窗 in-flight 时仍允许改选成员，完成后本地 preview 还能和真正提交成员集错位
- `CreateGroupDialog` 甚至直接把 `set` 转成 member_ids，请求顺序并不稳定
- 建群 / 加好友 / 群成员管理这些 mutation 弹窗都把“关窗口”当成“取消业务”，但服务端 side effect 并不会因此回滚
- 建群弹窗内的本地过滤字段也不一致，`CreateGroupDialog` 连 `assistim_id` 都不支持
- 群成员管理窗口 refresh 失败后还会重新放开旧成员/旧权限快照上的操作入口
- add/remove/transfer 这些群成员 mutation 的正式返回语义也不稳：
  - 重复 add_member 仍会报成功并推进 avatar version
  - 移除不存在成员也会走成功路径并推进 avatar version
  - add-member payload 对外暴露 `role`，但服务端正式能力却只允许 `member`
  - role PATCH 空请求会静默降权成 `member`
  - transfer ownership 甚至允许 self-transfer 走一遍伪成功 no-op
- 群列表 authoritative snapshot 也还没脱离 N+1 序列化路径，群一多会继续放大成员/用户查询成本

建议优先动作：

- 为群生命周期、群成员变更、会话生命周期补正式事件
- 这些事件要么进入统一 realtime+history_events 模型，要么有明确的 authoritative refresh 边界
- 不要继续依赖发起端页面本地 merge 充当正式同步模型
- 群成员管理这类 mutation-heavy 界面不要再用“串行单成员 side effect + 本地补拉”的临时批处理模型

### G-06：聊天页与联系人页的 UI 入口和本地状态机有大量页内一致性缺口

合并范围：

- `F-119` 到 `F-158`
- `F-309`
- `F-310`
- `F-318`
- `F-322`
- `F-325` 到 `F-328`
- `F-339`
- `F-340`
- `F-341`
- `F-346`
- `F-415`
- `F-416`
- `F-493`
- `F-494`
- `F-495`
- `F-496`
- `F-509`
- `F-510`
- `F-511`
- `R-035`
- `R-037`
- `R-039`
- `R-063`

共同根因：

- 页内状态机和业务语义没有收口，很多入口直接复用“最容易接上的动作”，而不是符合当前页面语义的动作
- 失败回滚、空态切换、详情定位、搜索结果定位、当前页保持等行为没有统一约束

典型表现：

- 请求详情和联系人详情的展示语义经常错位
- 联系人页顶部搜索命中后直接跳聊天，不定位详情
- 聊天页和联系人页里的若干入口会先切页再执行，失败后不会回退
- 一些按钮是否可用、空态是否切换、选中项是否清理都依赖偶然的页面状态
- 会话页和联系人页的搜索 flyout 只要被外部关闭，就会直接清掉用户关键词
- 这两个 flyout 甚至会因为窗口 move/resize 这种纯几何事件被关闭，并顺带破坏搜索输入
- 会话搜索结果在导航成功前就会先把查询和结果清空
- 聊天页侧边栏搜索结果打开链路没有 latest-wins 约束，连续点击会让旧目标反扑
- 联系人页的 `restore_selection(full_reload=False)` 只恢复左侧高亮，不恢复右侧 detail payload
- 本地聚合搜索每次输入都会触发一整组结果查询 + 计数查询，属于高频交互里的结构性冗余
- 本地消息搜索的 query / grouping / counting / rendering 也不在同一层 contract 上：raw message limit、distinct session total、卡片命中数彼此分裂
- 搜索 manager 还在返回失效的 `highlight_ranges`，UI 则完全不消费这套 metadata，manager/UI 的高亮 contract 已经分裂
- `search_all()` 的 section total 和实际渲染列表也不是同一个本地快照
- 群搜索命中 `member_search_text` 时，结果卡片还会把真实命中成员退化成泛化占位文案
- 本地消息搜索对附件也没有统一 contract，连非加密附件的可见文件名都进不了索引
- AddFriendDialog 的用户搜索失败、空关键词和新搜索 loading 态都会继续保留上一轮可点击结果
- AddFriendDialog 也没有正式 keyword generation guard，late result 是否覆盖当前结果仍依赖任务取消碰巧生效
- AddFriendDialog 的搜索摘要还会把禁用结果一起算进主结果数
- AddFriendDialog 在请求提交途中被关闭时，本地 follow-up 还会直接丢失
- SessionPanel 自己的 grouped search teardown 也没有像联系人页那样补 destroyed guard，晚到结果仍可能把 flyout 再拉起来

建议优先动作：

- 先把“联系人页搜索”“请求详情”“联系人详情”“聊天页跳转”四条主链路做成严格状态机
- UI 入口必须遵循当前页面语义，不要默认跳到别的 domain 去规避未实现问题
- 所有“先切页后执行”的入口都要补失败回滚

### G-07：通话 signaling、状态机、媒体时序仍不成熟

合并范围：

- `F-014`
- `F-016`
- `F-019`
- `F-166` 到 `F-169`
- `F-171`
- `F-174`
- `F-179`
- `F-180`
- `F-182`
- `F-183`
- `F-184`
- `F-189`
- `F-190`
- `F-282`
- `F-283`
- `F-284`
- `F-285`
- `F-286`
- `F-287`
- `F-288`
- `F-289`
- `F-290`
- `F-291`
- `F-292`
- `F-293`
- `F-294`
- `F-295`
- `F-296`
- `F-345`
- `F-349`
- `F-350`
- `F-351`
- `F-353`
- `F-365`
- `F-366`
- `F-367`
- `F-368`
- `F-369`
- `F-377`
- `F-378`
- `F-379`
- `F-380`
- `F-381`
- `F-382`
- `F-708` 到 `F-711`
- `F-790` 到 `F-792`
- `F-802`
- `F-805`
- `F-807`
- `F-813`
- `F-815`
- `F-816`
- `F-820`
- `F-824`
- `F-827`
- `F-828`
- `F-830`
- `F-831`
- `F-832`
- `F-839`
- `F-841`
- `F-844`
- `F-433`
- `F-434`
- `F-435`
- `F-448`
- `F-449`
- `F-456`
- `F-457`
- `F-499`
- `F-500`
- `F-501`
- `F-502`
- `F-503`
- `F-504`
- `F-505`
- `F-506`
- `F-507`
- `F-508`
- `F-525`
- `F-526`
- `F-527`
- `F-528`
- `F-545`
- `F-546`
- `F-547`
- `F-548`
- `F-594`
- `F-595`
- `F-596`
- `F-597`
- `F-651`
- `F-652`
- `R-006`
- `R-010`
- `R-032`
- `R-033`
- `R-013`
- `R-019`
- `R-040`
- `R-041`
- `R-042`
- `R-043`
- `R-045`
- `R-048`
- `R-055`
- `R-056`
- `R-057`
- `R-070`
- `R-071`
- `R-095`

共同根因：

- 通话控制面还没有成熟的正式状态机，signaling 时序、错误归因、终态判定、超时收口都没有统一建模
- 当前实现混用了“客户端自报”“服务端广播”“本地引擎状态文案”三套口径
- 通话基础设施仍紧耦合进程内单例和页面生命周期
- 客户端 `CallManager` 还是单槽 `_active_call` 模型，本地没有严格的 call_id 代际保护和终态幂等
- 通话窗口层自己也没有把“隐藏预热窗口”“当前活动窗口”“旧窗口已失效”拆成正式状态

典型表现：

- accept 前就开始完整 WebRTC signaling 和本地媒体预热
- invite / ringing / accept / offer / answer / ice / hangup 缺角色和阶段约束
- signaling 还强依赖底层 direct session 仍存在且仍是双人成员；会话漂移会直接把 call control 打断
- 任意 signaling 报错都可能把整通电话判 failed
- 来电侧没有 unanswered timeout，服务端也没有可靠的 disconnect cleanup
- 外呼 timeout 到点后也只是尝试发送一次 `hangup(timeout)`；本地并没有 authoritative timeout 终态兜底
- 只要出现 `answered_at`，系统消息就可能把通话记成 completed，即使媒体根本没接通
- 晚到旧 invite/state/terminal 可以直接覆盖或清掉当前 `_active_call`
- `CallManager` 的本地 outbound control 入口也还没有 current-call guard：
  - accept / reject / hangup / offer / answer / ice 只校验 `call_id` 非空
  - `_handle_invite()` 也会无条件覆盖当前 `_active_call`
- `_merge_state()` 甚至会把别的 `call_id` 的不完整 payload 和当前通话残留字段拼成一条假状态
- 本地 accept/reject/hangup/offer/ice 入口不会校验当前 call_id 或阶段是否合法
- aiortc 预接听信令缓存无上限，close 也不是 quiescent teardown
- 通话窗口会在程序化 close 和 `closeEvent()` 上重复触发 engine close
- 手动关闭窗口会先 teardown 本地媒体/UI，再异步发送 hangup
- 重复 `accepted/ringing/inviting` 会把已连通窗口打回 `Connecting...`
- accept 会被强制 ICE 刷新阻塞；来电预热和正式接听还会重复刷新一次 ICE 配置
- 服务端允许客户端自带 `call_id`，registry 可被同名通话直接覆盖
- registry 自己的 authoritative 约束也还不完整：
  - `create()` 没有 `call_id` 冲突保护
  - `get_for_user()` 也不校验映射到的 call 是否真的包含该 user
- `call_id` 一旦被复用，旧用户的 busy 索引还可能直接指到新通话
- 晚到 signaling 只要还能命中 `active_call`，就能把用户已经关掉的通话窗口重新建出来
- 不同 `call_id` 的 signaling 甚至会先关掉当前窗口，再切到新的 window path
- `_merge_state()` 还会把不同 `call_id` 的半残 payload 和当前通话残留字段拼成假状态
- `_close_call_window()` 会先丢掉 tracked reference，再尝试真正 close；close path 一旦抛错就会留下 orphan window
- End 按钮只发 hangup、不做本地 ending/close，重复点击还能继续排队多次 hangup
- 通话窗口发出的 hangup / offer / answer / ice 也没有 current-call guard，旧窗口仍能继续向外发控制消息
- 来电流程会先向对端发 `call_ringing`，再尝试本地 surface 来电 UI；对端视图和本地 UI 可见性并不一致
- 没有音频输出设备时，远端媒体已到达也会长期卡在 `Connecting...`
- 通话窗口现在也不会正式展示“无麦克风 / 无摄像头 / 已退化成 receive-only”这类真实媒体退化原因
- 无效 SDP / ICE payload 在客户端侧仍会被静默忽略，不会升级成正式 failed / diagnostics 事件
- 远端音频轨如果恰好在“当前无输出设备”时到达，本地播放任务会直接退出；之后再插设备也不会恢复
- 麦克风/摄像头 availability 恢复还会覆盖用户原本的 mute / camera-off 偏好
- `call_ringing` 现在只回给主叫，被叫的其它在线设备拿不到 authoritative ringing 状态
- 同一条 invite 发到被叫账号全部在线设备后，每台设备还都会自动回一次 `call_ringing`；caller 会收到重复 ringing fanout
- 来电本身也没有 callee primary-device claim；被叫账号所有在线设备都会同时 surface 来电 toast、响铃和隐藏窗口预热
- 同一次来电也会在被叫账号每台在线设备上都强制刷新 ICE 并预热隐藏通话窗口，一条 invite 被放大成多路 prewarm 任务
- 同账号被叫其它在线设备在第一台设备 accept 之后，仍可再次发送 `call_accept`；服务端没有 accepter-device claim
- 但现有的 `call_ringing` fanout 到主叫全部在线设备后，主叫被动镜像设备又会仅凭单条 ringing payload 直接 materialize 本地 outgoing call，并弹 ringing UI
- caller 侧对 `call_ringing` 也没有幂等消费；重复 ringing event 仍会反复重放 ringing UI 和 signaling 激活动作
- `call_accept` 现在会 fanout 给双方全部在线设备，而客户端收到 accepted 后又会无条件 `start_media`
- 被叫只在一台设备上接听时，双方其它在线设备也可能被动拉起窗口和媒体初始化
- 同一条 accepted mirror 还会让 passive device 一样播放 connected 音效并弹 accepted 提示
- participant-scoped terminal event 也还会让主叫其它在线设备各自满足“outgoing + initiator”，从而重复发送本地 call result system message
- `_call_result_messages_sent` 只是单进程去重，完全不能解决多设备重复写入
- 同一批 participant-scoped terminal event 还会让 passive mirror device 一样播放结束音、弹终态 InfoBar
- speaker enabled 的默认值也直接取自“当前是否有输出设备”，不是独立用户偏好
- 来电 toast 会在 accept/reject 成功前就先被本地关闭
- `CallWindow.showEvent()` 还会在每次 re-show 时强制重新居中，窗口不具备稳定位置语义
- `start_media()/prepare_media()` 对底层同步异常没有 UI 侧回滚，缺 loop 等边界会把窗口留在半启动态
- 音频通话把“是否已连通”绑到了本地 speaker 开关上；用户关扬声器后，首个远端音频帧都不能把通话判成 connected
- 如果远端音频轨到达时本机暂时没有输出设备，音频消费任务会直接退出，之后再插设备也不会恢复
- 媒体层 `disconnected/failed/closed` 只会改状态文案，不会正式收口窗口和 call state
- `CallWindow.start_media()` 在引擎真正启动前就先锁死 `_media_started`，一次失败会把后续重试入口烧掉
- 通话窗口和 aiortc 引擎都把设备能力建模成一次性启动快照，而不是运行期状态
- 远端音频 sink 只绑定第一次播放时的默认输出设备，中途切换系统默认扬声器不会重绑
- 通话时长显示还会从权威 `answered_at` 被本地“首帧媒体到达时间”重置
- aiortc close 依赖当前 loop，且只是 cancel 任务不等待真正静默；预接听 ICE 缓冲也没有上限
- `on_track` 没有去重，重复 track/重协商可能直接拉起多条并发远端媒体消费者
- 本地预接听 signaling 队列也没有任何上限，offer/ICE 可以在 accept 前持续堆积
- `call_busy` 事件没有单一 canonical payload：attempted call、blocking active call 和 busy user 被拆成多套字段，而客户端主模型只吸收了其中一部分
- `call_invite` 自己的 formal contract 也还没收口：
  - 只 fanout 给被叫，不镜像到主叫自己的其它在线设备
  - 发起连接也收不到 sender-side canonical ACK / echo
  - `call_id` 还会偷偷回退到 outer `msg_id`
  - `media_type` 也会在 route 层静默默认成 `voice`
- `call_offer/call_answer/call_ice` 这三条真正的 WebRTC signaling 也还没有成熟 contract：
  - 当前仍按 user fanout，而不是 device-scoped routing
  - peer 的所有在线设备都会收到同一份 signaling
  - sender 当前连接也拿不到 canonical echo
  - payload 里还同时保留 `actor_id`、`from_user_id`、`to_user_id` 三套 actor/recipient 表示
- call state/control payload 也仍只有 `actor_id=user_id`，没有任何 `actor_device_id / ringing_device_id / accepted_device_id / active_media_device_id`
- 服务端下行的 `call_invite/ringing/accept/reject/hangup/offer/answer/ice` 外层 envelope 也统一复用 `msg_id=call_id`；整场通话的多条 control/signaling event 没有独立 transport id
- 忙线分支还会把“本次尝试的 media_type”错当成当前占线通话的 media type 返回
- `call_busy` payload 也没有和其它 call event 对齐到统一 contract：
  - 缺少 `initiator_id / recipient_id / status / created_at / answered_at` 这类 canonical call 字段
  - `busy_user_id / active_call_id` 又只存在于忙线分支特有 payload
  - 客户端主模型因此无法仅靠 `call_busy` 恢复出完整的 blocking call 上下文
- busy UI 还会直接忽略 `busy_user_id`，把“自己忙线”也固定渲染成“对方忙线”
- `call_busy` fanout 到主叫全部在线设备后，主叫被动镜像设备也会仅凭单条 busy payload 直接走 busy 终态 UI，甚至写本地结果系统消息
- busy 分支的基础字段校验顺序也是反的，空 `call_id` 的非法 invite 在忙线场景下会被直接折叠成 `call_busy`
- call private-session gate 也还在用和 session visibility 不同的成员口径：只校验 `len(member_ids) == 2`，不校验“两位不同成员”
- 客户端入站 call 状态机连最基础的 payload identity gate 都还没补上：
  - `call_invite` 对空 `call_id/session_id` 也会直接创建本地 ghost active call
  - `call_ringing/call_accept/call_reject/call_hangup/call_busy` 对空 `call_id` 也会继续 merge，终态分支甚至会直接清掉当前 `_active_call`
- 来电窗口在接听前手动关闭会走 `hangup`，不是 `reject`；主叫侧结果因此可能被错误记成 `failed`
- 通话结果系统消息按 `(call_id, outcome)` 去重，不是按 `call_id` authoritative 收口；晚到终态下仍可能写出多条矛盾结果
- call error routing 继续硬耦合在 outer `msg_id == call_id` 上，而不是正式绑定 payload `call_id`
- 服务端 `reject` 仍没有 pre-answer 状态约束，被叫在 accepted 之后依然能发出 `call_reject`
- 一旦底层 direct session 漂移或不再满足双人成员，连 hangup/cleanup 都可能被服务端拒绝，registry busy 状态会残留
- 麦克风 availability 恢复会覆盖用户原本的 mute 选择；speaker availability 则根本没有进入正式窗口状态机

建议优先动作：

- 先补一份正式 call state machine：invite -> ringing -> accepted -> connected -> ended/failed/busy/rejected/timeout
- 再把 signaling 时序、错误归因、超时策略、服务端权威终态全部挂到这套状态机上
- 通话页面和 aiortc 引擎只消费正式状态机，不直接拿引擎零散状态当业务终态
- 给客户端 call_id 事件处理补严格的 current-call 校验和终态幂等，避免单槽状态机被晚到事件打穿
- 把 hidden prewarm window 和 visible active window 拆开，不要继续共用一个 `_call_window` 槽位

### G-08：E2EE 设备恢复模型、本地缓存模型和多设备模型没有收口

合并范围：

- `F-170`
- `F-173`
- `F-175`
- `F-176`
- `F-177`
- `F-178`
- `F-181`
- `F-185`
- `F-186`
- `F-187`
- `F-188`
- `F-276`
- `F-277`
- `F-278`
- `F-279`
- `F-280`
- `F-281`
- `F-297`
- `F-299`
- `F-300`
- `F-301`
- `F-302`
- `F-303`
- `F-347`
- `F-356`
- `F-357`
- `F-358`
- `F-359`
- `F-360`
- `F-383`
- `F-413`
- `F-414`
- `F-384`
- `F-385`
- `F-386`
- `F-387`
- `F-397`
- `F-398`
- `F-430`
- `F-436`
- `F-438`
- `F-439`
- `F-440`
- `F-441`
- `F-442`
- `F-460`
- `F-461`
- `F-462`
- `F-463`
- `F-464`
- `F-465`
- `F-466`
- `F-467`
- `F-468`
- `F-469`
- `F-470`
- `F-471`
- `F-472`
- `F-473`
- `F-474`
- `F-475`
- `F-476`
- `F-477`
- `F-478`
- `F-479`
- `F-480`
- `F-481`
- `F-482`
- `F-483`
- `F-484`
- `F-485`
- `F-486`
- `F-487`
- `F-488`
- `F-489`
- `F-497`
- `F-498`
- `F-521`
- `F-522`
- `F-523`
- `F-524`
- `F-636`
- `F-680` 到 `F-683`
- `F-692` 到 `F-696`
- `F-454`
- `F-455`
- `R-012`
- `R-089`
- `R-090`
- `R-030`
- `R-031`
- `R-021`
- `R-066`
- `R-058`
- `R-062`
- `R-068`
- `R-072`

共同根因：

- 当前 E2EE 同时存在“设备级恢复”“会话级恢复”“本地明文缓存”“history recovery package”四套机制
- 这些机制之间没有清晰边界：哪些是 device-global，哪些是 session-local，哪些只是缓存，哪些是权威恢复材料
- 多设备直聊模型和 history recovery 的账号边界也没有完全收口
- 重试、群 fanout、媒体预取、本地搜索这些后续链路也没有围绕同一套 E2EE contract 收口
- device registry、本地 runtime 和 prekey bootstrap 这三层也还没有单一真相：
  - 设备删除不会使该设备现有 auth/runtime 失效
  - register_device 会 destructive replace 全部 one-time prekeys
  - signed prekey 注册/刷新也没有任何密码学验证
  - device/key schema 仍只有 `min_length`，没有结构和上限约束
  - prekey bundle / claim 的正式结果也还是 partial-success contract：
    - `exclude_device_id` 仍是调用方可控的任意设备过滤器
    - bundle 列表会静默跳过缺 signed prekey 的活跃设备
    - claim 会静默跳过不存在、inactive 或缺 signed prekey 的设备
    - one-time prekey 耗尽时仍返回普通成功，只把 `one_time_prekey=None` 混进结果
    - `device_ids` 的 strip/去空/去重还停留在 service 层偷偷做

典型表现：

- direct E2EE 只加密给一个目标设备
- session 级恢复实际执行的是 device-global reprovision
- history recovery 支持跨账号导出/导入
- `local_plaintext/local_metadata` 会长期压过当前密文版本
- 本地已经解密出的 `local_plaintext` 又不会进入消息搜索，导致 E2EE 会话在搜索能力上直接隐身
- 加密消息 retry 会复用旧 ciphertext，并绕过当前身份审查 gate
- direct E2EE 的 identity review 待确认只覆盖文本，不覆盖附件
- `security_pending` 横幅只看当前 chat panel 已加载的消息模型；未加载的待确认消息会被静默隐藏
- `security_pending` 的 release / discard 也只扫描最近 200 条本地消息；更早的待确认消息会直接漏处理
- `security_pending` 的 release / discard 还会按最近消息倒序处理，不是真正的 FIFO 待发送队列
- `security_pending` 的 release / discard 也没有 in-progress guard，同一会话可以并发触发多次消费
- `security_pending` 还继续复用 `MessageEvent.SENT`：本地待确认、真正释放发送、甚至本地加密失败都会挤进 sent 生命周期
- session 级安全确认因此不是真正的 session authoritative 动作，UI 可能显示已确认，但更早 pending message 仍残留
- 聊天页的 confirm / discard 反馈也没有 no-op contract：命中 0 条时要么继续弹 success，要么直接静默返回
- `send_message_to()` 也会把这些“尚未真正发送 / 只是在本地失败”的消息直接推进成 session 最新预览
- 删除加密媒体消息时不会取消后台预取 / 下载，晚到任务还能把消息重新写回本地
- 删除消息也不会清理已经下载到本机的附件明文文件
- 撤回加密文本时，客户端还会把原本的本地加密态和密文直接抹掉，只留下 recall notice
- 媒体 retry 会先上传、再入队；入队失败会留下孤儿上传，并把失败消息改写成半成功的“已上传”形态
- 后续媒体 retry 还会因为已有 remote URL 而跳过重新加密，继续复用旧附件密文
- 群聊 E2EE 会在部分成员 bundle 拉取失败时静默退化成 partial fanout
- history sync 会直接触发加密媒体后台下载，而且没有任务并发上限
- `history_messages` 还会把整批 sync completion 串行阻塞在本地逐条解密上
- 被撤回的加密附件和已删会话的 sender-key 仍可能保留在本地
- 即使加密附件已经本地解密出 `local_metadata`，搜索链路也仍把它当成完全不可见
- 消息侧 fallback session 还会把 `encryption_mode`、`session_crypto_state` 和 call 能力当成本地默认值写进缓存，并直接影响后续 send/edit 的 E2EE 决策
- direct fallback session 一旦丢了 `counterpart_id`，identity verification / trust peer 这类安全动作也会被错误卡死
- `RECOVERED` 事件在生产链路里还是死事件，恢复完成后聊天页和会话预览不会正式收口
- `recover_session_messages()` 自己的 result/event contract 也还是分裂的：`count/updated`、`message_ids`、`remote_messages`、`recovery_stats` 描述的不是同一批“已恢复消息”
- 当前会话恢复只覆盖“最近 N 条本地消息 + 最多 N 页远端历史”，并且远端部分失败后仍会继续发 `RECOVERED`
- `import_history_recovery_package()` 的返回 contract 也还是混合对象：
  - 一部分字段是本次 import delta（`imported_*`）
  - 一部分字段又是导入后的全局 diagnostics（`primary_source_*`、`source_devices[]`、`source_device_count`）
  - import result 和 global recovery snapshot 不是同一 scope
  - controller 层还会再追加一份嵌套的 `history_recovery_diagnostics`，把同一份全局 recovery state 重复编码成两套 shape
- `export_history_recovery_package()` 的 controller 返回也一样继续把：
  - 单次 export result（`target_*` + `package`）
  - 全局 `history_recovery_diagnostics`
  混成同一份对象
- `history_recovery_diagnostics.primary_source_*` 也不是正式主来源关系，只是把 `source_devices[]` 按 `imported_at/exported_at/source_device_id` 排序后取第一项
- `recover_session_messages()` 还会把“恢复可读性”动作顺带变成加密媒体预取下载
- 远端消息恢复分页只靠 timestamp 推进，时间戳碰撞时会提前截断恢复窗口
- group E2EE 的接收方集合和 `member_version` 现在仍可由本地 session cache 临时推导甚至本地伪造，不是权威群成员快照
- 本地群成员缓存一旦为空、残缺或过时，群文本 / 群附件 E2EE 发送要么会直接硬失败，要么会静默遗漏合法接收方
- group recipient bundle 拉取还是逐成员串行网络链路，群越大发送越慢
- `apply_group_session_fanout()` 也没有把 inner payload 和 outer envelope 绑死：`session_id / owner_device_id / sender_key_id / member_version` 都允许内层值覆盖外层
- fanout payload 缺 `owner_user_id` 时，接收端还会把 inbound sender key 错记到本地接收者自己名下
- inbound sender key 当前只按 `owner_device_id` 保留一份，新 fanout 会覆盖同设备旧 key；removed member 的 inbound key 也可能因为 member list 缺失而长期残留
- group 附件 decryption diagnostics 还会在“只有 fanout、sender key 尚未装入”时提前报 `READY`
- group 文本 / 附件解密路径现在都带持久化 side effect：只要读到 matching fanout，就会在读取过程中直接安装 sender key
- group 文本解密甚至不会按 `sender_key_id` 取 key；同一设备轮换过 sender key 时，当前消息可能先拿到错误的那把 key
- `apply_group_session_fanout()` 还能把缺 `sender_key` / 缺 `sender_key_id` 的半残 fanout 直接落进本地 state
- 旧 fanout 目前没有 monotonic install guard，晚到旧 payload 也能把较新的 inbound key 覆盖回去
- history recovery 的 sender-key fallback 还没有正式 provenance / recency contract：查找顺序取决于导入顺序，live decrypt 也会透明吃 imported material
- history recovery package 导入对 signed prekey / one-time prekey / group sender key 都是按 key id 直接覆盖，旧包可以回滚同一 source device 的较新恢复状态
- history recovery import 目前还只按 `source_device_id` 建 recovery state 主键，不会把该 source device 和经过验证的 `sender_identity_key_public` 绑定成同一正式身份
- history recovery export 入口本身也还没有 source identity binding：
  - `source_user_id` 仍是调用方可传、可空的自报字段
  - inner payload 和 outer package 都直接信这份自报值
  - export 自己就在继续生产可伪造、可缺省的 source identity
- inbound key 记录里的 `sender_identity_key_public` 仍是 envelope 自报值，本地安装时没有再和最终 owner device / owner user 正式绑定
- 设备与 prekey 正式服务链本身还有明显的查询放大：
  - `count_available_prekeys()` 用全表加载再 `len()` 计数
  - `list_my_devices()` / `list_prekey_bundles()` / `claim_prekeys()` 都存在 per-device N+1 计数与 signed-prekey 查询

建议优先动作：

- 先重新定义 E2EE 三个层次：设备状态、会话状态、本地缓存
- 对 history recovery 强制收口到“同账号设备迁移”
- 本地明文缓存与 metadata cache 必须降级成严格受版本约束的性能缓存，而不是第二真相
- 把 retry、群 fanout、媒体预取、本地搜索都挂到同一套 E2EE 语义上，不要再各自实现一套“能跑就行”的旁路

## 4. 推荐修复顺序

### P0：先收口根因，不要先修单点

1. `G-03` authenticated runtime 生命周期
2. `G-01` 服务端权威真相与正式协议边界
3. `G-02` 会话删除 / 隐藏 / 全量刷新语义

### P1：再收口高风险业务域

4. `G-07` 通话状态机与 signaling
5. `G-08` E2EE 恢复模型、本地缓存模型和多设备模型
6. `G-05` 群/会话生命周期正式事件

### P2：最后处理页内一致性和缓存体验

7. `G-06` 聊天页 / 联系人页 UI 状态机

## 5. 使用建议

- 要排修复批次：看本页
- 要追单条证据：回 [review_findings.md](./review_findings.md)
- 要写修复方案：一律按“问题簇”拆，不建议继续按单条 `F-xxx` 零散修
