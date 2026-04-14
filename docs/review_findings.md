# 当前 Review Findings

## 1. 说明

本文档记录基于当前仓库快照的 code review 结论。

- 审查时间：2026-04-06 至 2026-04-08
- 结论类型分为：已确认问题、风险点
- 本文档是 review 快照，不替代 [design_decisions.md](./design_decisions.md) 与架构文档
- 本文档保留原始编号与时间顺序，用作追溯台账；合并去重后的整理版见 [review_findings_grouped.md](./review_findings_grouped.md)
- 当前 review 状态：6 条主业务链路已完成尾扫，后续不建议继续散扫，应按问题簇进入修复阶段
- 当前原始台账覆盖范围：
  - 已确认问题：`F-001` 到 `F-855`
  - 风险点：`R-001` 到 `R-097`

### 1.0 使用方式

- 要追单条证据、原始发现顺序、单条修复回写：看本页
- 要排修复批次、看共同根因、避免重复修：看 [review_findings_grouped.md](./review_findings_grouped.md)
- 当前更适合按：
  - `G-01` 到 `G-08`
  分批修，不建议继续按 `F-xxx` 零散推进

推荐阅读顺序：

1. 先看 [review_findings_grouped.md](./review_findings_grouped.md) 的：
   - 当前收口状态
   - 业务链路与问题簇映射
   - 推荐修复顺序
2. 再回本页按：
   - `F-xxx`
   - `R-xxx`
   追单条证据和修复回写

### 1.1 单条 Finding 状态口径

后续更新 raw findings 时，优先使用以下生命周期状态：

- `open`：已确认，尚未处理
- `in_progress`：正在修复
- `fixed_pending_verify`：代码已改，但尚未完成回归验证
- `fixed_verified`：已修复且已验证
- `closed_by_merge`：不再单独追踪，已被更大修复批次或问题簇吸收

说明：

- 历史条目里已经出现的“已确认 / 已修复”先继续保留，不强行全量改写
- 新增或后续回写修复结果时，优先按上面的状态口径更新

### 1.2 单条 Finding 归档规则

修复一个 `F-xxx / R-xxx` 时，不删除编号，不调整顺序，只更新原条目。

建议最少补齐三项：

- 修复日期
- 修复结果
- 对应文件 / 测试

如果一个问题已被更大的修复批次顺带收口，不单独保留 active 状态时，标记为 `closed_by_merge` 即可。

## 2. 已确认问题

### F-001：通话 signaling 字段命名与协议文档不一致

状态：已修复（2026-04-06）

修复结果：

- 协议文档与设计草案已经统一使用 `initiator_id`、`recipient_id`、`actor_id`
- 文档已补充说明：客户端发起 `call_invite` 时仍可附带 `target_user_id` 作为目标用户提示

对应文件：

- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2\docs\realtime_protocol.md)
- [D:\AssistIM_V2\docs\chat_e2ee_calls_design.md](D:\AssistIM_V2\docs\chat_e2ee_calls_design.md)

### F-002：兼容入口文档与当前实现不一致

状态：已修复（2026-04-06）

修复结果：

- 文档已明确当前唯一正式聊天 WebSocket 入口为 `WS /ws`
- 文档已明确当前未保留 `/ws/chat`、`/api/chat/*` 与 `POST /api/chat/sync` 兼容入口
- ADR 与后端架构说明已收敛到当前真实实现边界

对应文件：

- [D:\AssistIM_V2\docs\backend_architecture.md](D:\AssistIM_V2\docs\backend_architecture.md)
- [D:\AssistIM_V2\docs\design_decisions.md](D:\AssistIM_V2\docs\design_decisions.md)

### F-003：会话默认加密模式把所有 direct / group 会话都视为 E2EE

状态：已修复（2026-04-06）

修复结果：

- 服务端和客户端的默认 `encryption_mode` 已改为：AI 会话默认 `server_visible_ai`，其他会话默认 `plain`
- 会话刷新不再因为 `direct` / `group` 类型自动触发对端身份检查或群 sender-key 协调

对应文件：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2\server\app\services\session_service.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)
- [D:\AssistIM_V2\client\models\message.py](D:\AssistIM_V2\client\models\message.py)
- [D:\AssistIM_V2\server\tests\test_session_service.py](D:\AssistIM_V2\server\tests\test_session_service.py)
- [D:\AssistIM_V2\client\tests\test_service_boundaries.py](D:\AssistIM_V2\client\tests\test_service_boundaries.py)

### F-004：消息发送路径是否加密，当前只按会话类型判断，不按显式加密模式判断

状态：已修复（2026-04-06）

修复结果：

- 文本与附件发送现在都通过 `session.uses_e2ee()` 决定是否进入 E2EE 路径
- 直聊身份审查阻断逻辑只对真正启用 E2EE 的直聊会话生效

对应文件：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)
- [D:\AssistIM_V2\client\tests\test_service_boundaries.py](D:\AssistIM_V2\client\tests\test_service_boundaries.py)

### F-005：服务端仍未把 `encryption_mode` 作为权威会话属性持久化，也没有按该模式约束消息加密入站

状态：已修复（2026-04-12）

现状：

- 服务端对外 schema 暴露了 `encryption_mode`
- 但 `sessions` 模型当前没有对应持久化字段
- `MessageService._validate_message_encryption()` 只按 `session_type` 与 `is_ai_session` 校验 envelope，不校验会话当前是否真的启用了 `e2ee_private` / `e2ee_group`

证据：

- [D:\AssistIM_V2\server\app\models\session.py](D:\AssistIM_V2\server\app\models\session.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2\server\app\services\session_service.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2\server\app\services\message_service.py)
- [D:\AssistIM_V2\server\app\schemas\session.py](D:\AssistIM_V2\server\app\schemas\session.py)

影响：

- 当前“会话是否启用 E2EE”仍主要由客户端派生，服务端没有真正形成单一真相
- 即使当前默认模式已经改回 `plain`，旧客户端或手工请求仍可能在 plain 会话上发送被服务端接受的加密 envelope；现有 [D:\AssistIM_V2\server\tests\test_e2ee_edits.py](D:\AssistIM_V2\server\tests\test_e2ee_edits.py) 就直接在默认 `plain` 的 direct 会话上成功发送了加密文本与附件 envelope
- 这会让文档中的显式 `encryption_mode` 语义在服务端边界失效，后续很难稳定演进私聊 / 群聊 E2EE 策略

建议：

- 把 `encryption_mode` 变成服务端权威会话属性，并明确其迁移与默认值策略
- `MessageService` 与附件上传链路都应按该属性做服务端校验，而不只按 `session_type` 放行

### F-006：HTTP 发消息入口缺少请求级幂等键，且不会对在线成员做实时广播

状态：已修复（2026-04-12）

修复记录：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_quiesce_authenticated_runtime()` 现在会先调用主窗口 `quiesce()`，在 `clear_session()` 之前提前冻结联系人/搜索页的在途任务。
- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 会把 `contact/chat/discovery/profile` 子壳层一起 quiesce；[contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 不再等到 `destroyed` 才取消加载/搜索/详情任务。
- [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `load_contacts()/load_groups()/persist_groups_cache()` 已增加 runtime user guard，登出或切号后的晚到结果不会再 `replace_contacts_cache()/replace_groups_cache()`。
- 回归测试覆盖 stale auth context 下 contacts/groups cache 不再被旧账号回写。

现状：

- 架构文档、协议文档和 ADR 都要求会改变状态的客户端命令必须带请求级幂等键；在当前 WS 协议中该字段名为外层 `msg_id`
- 但 HTTP `POST /api/v1/sessions/{session_id}/messages` 使用的 `MessageCreate` schema 当前既不包含外层 `msg_id`，也不包含任何等价的请求级幂等键
- 该 HTTP 路由当前只返回同步响应，不像 WS `chat_message` 那样向其他在线成员广播 `chat_message`
- 同一“发送消息”能力因此出现了 HTTP 与 WS 两套不一致的状态模型

证据：

- [D:\AssistIM_V2\docs\architecture.md](D:\AssistIM_V2\docs\architecture.md)
- [D:\AssistIM_V2\docs\design_decisions.md](D:\AssistIM_V2\docs\design_decisions.md)
- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2\docs\realtime_protocol.md)
- [D:\AssistIM_V2\server\app\schemas\message.py](D:\AssistIM_V2\server\app\schemas\message.py)
- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2\server\app\api\v1\messages.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2\server\app\websocket\chat_ws.py)

影响：

- HTTP 入口请求侧无法遵守正式的幂等重发模型；虽然响应对象会返回 canonical `message_id`，但那不是请求级幂等键，也不能替代 ACK 语义
- 如果调用方通过 HTTP 发消息，其他在线成员不会收到实时消息广播，行为与 WS 主链路明显不一致
- 这会让“发送消息”能力在不同入口下表现不同，削弱正式一致性模型的可信度

建议：

- 二选一收口：要么把 HTTP 发消息明确降级为非实时/仅测试入口并在文档中声明，要么补齐 `msg_id`、幂等与实时广播语义
- 若保留正式 HTTP 发消息入口，应补和 WS 主链路等价的边界测试

### F-007：typing 事件会被回发到发送者侧连接，UI 又没有按 `user_id` 过滤，导致错误“对方正在输入”提示

状态：已修复（2026-04-12）

修复记录：

- [user_profile_flyout.py](/D:/AssistIM_V2/client/ui/widgets/user_profile_flyout.py) 新增 `quiesce()`，logout 进入时会先取消 `_save_task` 和 flyout 级 UI task。
- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `update_profile()` 已收口到 runtime user guard：旧账号保存结果若在 clear/relogin 边界晚到，不再重新 `_apply_runtime_context()`、落盘 `user_profile` 或刷新会话快照。
- 回归测试覆盖“资料保存返回前 auth context 被清空”时不会持久化 profile，也不会触发 `refresh_sessions_snapshot()`。

现状：

- WS `typing` 广播当前只排除发送该命令的 `connection_id`，不会排除同一用户的其他连接
- HTTP `POST /api/v1/sessions/{session_id}/typing` 更是直接向全部 `member_ids` 广播，不排除发送者自己的连接
- 客户端 `ChatInterface._on_typing_event()` 只按 `session_id` 判断当前会话，不校验 `user_id != current_user`

证据：

- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2\server\app\websocket\chat_ws.py)
- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2\server\app\api\v1\sessions.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client\ui\windows\chat_interface.py)

影响：

- HTTP typing 入口下，发送者自己的在线客户端也可能直接看到“对方正在输入”
- WS typing 入口下，同一账号的其他在线设备也可能看到错误 typing 提示
- 这属于可直接推出的错误业务表现，不只是实现风格问题

建议：

- typing fanout 应明确只发给“其他参与者”，不要把发送者自身连接包含进去
- UI 侧也应以 `user_id != current_user` 作为最后一道保护，避免错误提示直接显示
### F-008：编辑 / 撤回命令的正式入口语义已经分叉，协议写 WS，桌面端实际走 HTTP

状态：已修复（2026-04-12）

修复记录：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 在 logout quiesce 时会提前取消安全动作所在的 `_ui_tasks`，不再依赖窗口真正销毁。
- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `execute_session_security_action()/trust_session_identities()/recover_session_crypto()/ _refresh_cached_session_crypto_state()/ _record_session_message_recovery()` 已增加 runtime user guard。
- 旧账号安全动作在 logout 后即使晚到完成，也不会继续 `replace_sessions()` 或发出 `SessionEvent.UPDATED`。
- 回归测试覆盖会话安全动作跨过 logout 边界后不再污染本地 sessions 表和事件流。

现状：

- 协议文档把 `message_recall` / `message_edit` / `message_delete` 定义为客户端经 WebSocket 发送的状态命令
- `ConnectionManager` 也保留了 `send_recall()` / `send_edit()` 等 WS helper
- 但桌面端 `MessageManager` 实际调用的是 HTTP `POST /messages/{message_id}/recall` 与 `PUT /messages/{message_id}`
- 当前 `ConnectionManager` 中对应 WS helper 处于“存在但未走主链路”的状态

证据：

- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2\docs\realtime_protocol.md)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2\client\managers\connection_manager.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)
- [D:\AssistIM_V2\client\services\chat_service.py](D:\AssistIM_V2\client\services\chat_service.py)
- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2\server\app\api\v1\messages.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2\server\app\websocket\chat_ws.py)

影响：

- 文档、基础设施 helper 与桌面端真实主链路不一致，后续维护者很容易误判正式入口
- 编辑 / 撤回当前没有沿用 WS 命令侧的 ACK / 重试模型，而是单独依赖 HTTP 请求成功与否
- 同一类“状态命令”在发送、编辑、撤回、已读之间已经分裂成多种入口模型，进一步削弱了一致性边界

建议：

- 明确编辑 / 撤回 / 已读的正式命令入口，到底统一走 WS 还是统一走 HTTP
- 移除未使用的一侧 helper，或者把桌面端主链路改回与正式协议一致
### F-009：桌面端 `delete_message()` 只是本地删除，和协议/服务端的广播型 `message_delete` 语义脱节，且会在历史回拉后复活

状态：已修复（2026-04-12）

修复记录：

- [session_panel.py](/D:/AssistIM_V2/client/ui/widgets/session_panel.py) 新增 `quiesce()`，logout 进入时会先取消会话菜单和搜索任务。
- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `remove_session()/ _hide_session()/ _save_hidden_sessions()` 已增加 runtime user guard，晚到删除不会再把 `chat.hidden_sessions` 重新写回。
- 回归测试覆盖 `remove_session()` 跨过 logout 边界时不再回写 tombstone，也不会继续删会话或发删除事件。

现状：

- 协议文档与服务端都把 `message_delete` 视为会进入 `event_seq` 的正式状态变更
- 服务端存在 HTTP `DELETE /messages/{message_id}` 与 WS `message_delete` 处理链路
- 但桌面端 `MessageManager.delete_message()` 当前只调用本地 SQLite 删除，没有走 HTTP 或 WS，也没有本地 tombstone 防止远端消息重新回灌
- `get_messages()` / `_fetch_remote_messages()` 会在后续历史拉取时重新保存服务端返回的同一条消息

证据：

- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2\docs\realtime_protocol.md)
- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2\server\app\api\v1\messages.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2\server\app\websocket\chat_ws.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client\storage\database.py)

影响：

- 用户在桌面端执行“删除消息”后，行为实际上只是本地临时隐藏，不是正式状态变更
- 一旦再次拉历史、切会话或断线补偿，消息会被服务端重新同步回来
- 这会让 UI 文案、用户预期和协议语义全部错位

建议：

- 如果产品语义是“对所有人删除”，桌面端应接入正式 `message_delete` 入口
- 如果产品语义只是“本地隐藏”，则需要独立 tombstone / hide 模型，不能直接复用正式 `message_delete` 命名
### F-010：通话 signaling 的 SDP / ICE payload 结构仍与协议文档不一致

状态：已修复（2026-04-12）

修复记录：

- [discovery_interface.py](/D:/AssistIM_V2/client/ui/windows/discovery_interface.py) 新增 `quiesce()`，logout 时会提前取消发现页加载/发布/点赞/评论任务并关闭相关对话框。
- [discovery_controller.py](/D:/AssistIM_V2/client/ui/controllers/discovery_controller.py) 增加 per-account cache scope、runtime user guard 和 `close()`；晚到旧账号结果不再写 `_user_cache/_comment_cache/_like_*`。
- [main.py](/D:/AssistIM_V2/client/main.py) 的 authenticated runtime teardown 现在会关闭 `DiscoveryController`，旧单例会退役并清空缓存，下一次登录重新建实例。
- 回归测试覆盖 discovery stale result 丢弃与 controller close 清缓存/清 singleton。

现状：

- 客户端与服务端当前都把 `call_offer` / `call_answer` 中的 `sdp` 作为对象透传，至少包含 `type` 与 `sdp`
- `call_ice` 当前也把 ICE 信息放在嵌套 `candidate` 对象中，内部字段使用 `sdpMid` / `sdpMLineIndex` 等 WebRTC 常见命名
- 但协议文档仍把 `sdp` 写成纯字符串，把 `candidate` / `sdp_mid` / `sdp_mline_index` 写成顶层扁平字段

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2\client\managers\call_manager.py)
- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2\client\call\aiortc_voice_engine.py)
- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2\server\app\services\call_service.py)
- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2\docs\realtime_protocol.md)
- [D:\AssistIM_V2\docs\chat_e2ee_calls_design.md](D:\AssistIM_V2\docs\chat_e2ee_calls_design.md)

影响：

- 新客户端、联调脚本或测试夹具如果按文档实现，会直接发出错误结构的 offer / answer / ice payload
- 这属于协议层面的文档漂移，影响比普通实现细节更大

建议：

- 统一文档到当前真实 payload 结构，或者反过来把实现收敛到文档定义
- 如果保留对象型 `sdp` 与嵌套 `candidate`，应把最小必填字段和命名规范明确写清楚
### F-011：HTTP 发消息 schema 中的 `session_id` 字段是误导性残留，路由会静默忽略它

状态：已修复（2026-04-12）

修复记录：

- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 新增 `quiesce()`，logout/auth-loss 进入时会先取消 `_contact_open_task/_ui_tasks`，并向 chat/contact/discovery/profile 子壳层下推 quiesce。
- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_quiesce_authenticated_runtime()` 现在显式先 quiesce 主窗口，再 teardown runtime；旧 contact/search jump 不再有机会跨过 clear 继续打开聊天。
- 回归测试覆盖 `Application` quiesce 会先触发主窗口 quiesce，以及 shell widget 已具备 logout quiesce contract。

现状：

- `MessageCreate` schema 当前仍声明了可选 `session_id`
- 但 `POST /api/v1/sessions/{session_id}/messages` 实际只使用路径参数中的 `session_id`
- 请求体里的 `payload.session_id` 没有参与任何校验，也不会覆盖路径值

证据：

- [D:\AssistIM_V2\server\app\schemas\message.py](D:\AssistIM_V2\server\app\schemas\message.py)
- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2\server\app\api\v1\messages.py)

影响：

- 调用方如果在 body 中传了冲突的 `session_id`，服务端会静默忽略，接口行为和 schema 表达不一致
- 这会增加联调歧义，也不利于后续把 HTTP 发消息真正收口为正式或非正式入口

建议：

- 如果路由只接受路径级 `session_id`，应从 `MessageCreate` 中移除该字段
- 如果希望支持 body 里的 `session_id`，则应明确校验它必须和路径参数一致

### F-012：服务端仍公开“全局硬删除 direct 会话”接口，但客户端与 UI 已把删除会话定义为本地隐藏

状态：已修复（2026-04-14）

修复说明：

- `MessageManager._fetch_remote_messages()` 现在先收集远端页里的 canonical `message_id`，再通过 `Database.get_messages_by_ids()` 批量读取本地已有消息
- 远端页仍完整返回给调用方，避免破坏 recovery 翻页对整页消息和 `session_seq` 的依赖
- 本地落盘改为 delta write：只保存新增消息或与本地缓存存在 authoritative 字段差异的消息
- `Database.get_messages_by_ids()` 已补批量查询入口，避免 `_fetch_remote_messages()` 对每条远端消息逐个 `get_message()`
- 已补 `test_message_manager_remote_history_uses_batch_existing_lookup_and_delta_write`

原状态：已确认

现状：

- 桌面端 `SessionManager.remove_session()` 的注释、隐藏 tombstone 逻辑和多语言 UI 文案都把“删除会话”定义为“仅从当前设备移除并清除本地记录”
- 但服务端仍公开 `DELETE /api/v1/sessions/{session_id}`，并在 `SessionService.delete_session()` 中直接调用仓储层硬删除整个会话
- `SessionRepository.delete_session()` 会级联删除 `SessionEvent`、`UserSessionEvent`、`SessionMember`、`MessageRead`、`Message` 和 `ChatSession`
- 现有服务端测试也把这一路径视为正确行为，并显式断言 direct 会话及其消息、已读、成员、事件都被全局删空

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)
- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2\client\ui\widgets\session_panel.py)
- [D:\AssistIM_V2\client\resources\i18n\zh-CN.json](D:\AssistIM_V2\client\resources\i18n\zh-CN.json)
- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2\server\app\api\v1\sessions.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2\server\app\services\session_service.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2\server\app\repositories\session_repo.py)
- [D:\AssistIM_V2\server\tests\test_chat_api.py](D:\AssistIM_V2\server\tests\test_chat_api.py)

影响：

- 这和当前桌面端产品语义直接冲突：同样叫“删除会话”，客户端是本地隐藏，服务端 API 却是对所有参与者的全局硬删除
- 任何外部调用方、未来客户端或误用该接口的内部代码，都可能在 direct 会话里把双方消息和事件直接删掉
- 这说明“会话删除”还没有成熟稳定的领域模型，目前同时混着本地隐藏、服务端硬删除两种完全不同的语义

建议：

- 明确 `delete session` 的正式产品语义；如果期望是“仅当前用户隐藏会话”，服务端应改为成员级 tombstone / archive / hide 模型，而不是删除 `ChatSession`
- 如果确实需要管理员级或系统级硬删除，应改成单独的受限管理入口，不要复用用户侧 `DELETE /sessions/{session_id}`

### F-013：typing 的 `typing=false` 停止语义在服务端已暴露，但桌面端既不会发送也不会消费

状态：已修复（2026-04-14）

修复说明：

- `MessageService` 已接入 `DeviceRepository`，E2EE envelope 不再只做 opaque 字段存在性校验
- direct text / attachment envelope 的 `sender_device_id` 必须是当前 sender 用户的 active registered device
- direct envelope 的 `recipient_user_id` 必须是当前会话内的另一名成员，`recipient_device_id` 必须是该成员的 active registered device
- group text / attachment envelope 的顶层 `session_id` 必须匹配消息 session，`sender_device_id` 必须属于当前 sender 用户
- group fanout item 的 `recipient_user_id/recipient_device_id` 必须绑定到其它会话成员的 active registered device，fanout 内的 `sender_device_id/sender_key_id` 必须与顶层 envelope 一致
- 当前服务端尚无独立 sender-key 代际 registry；本次将 `sender_key_id` 收口为 sender-device scoped key id，并要求顶层 envelope 与 fanout item 一致，不再接受 fanout 自由自报另一套 sender key
- 已补 `test_direct_text_encryption_requires_sender_device_belong_to_actor`

原状态：已确认

现状：

- HTTP `POST /api/v1/sessions/{session_id}/typing` 已经接受并广播 `typing` 布尔值，默认 `true`
- 但桌面端 `ConnectionManager.send_typing()` 和 `ChatController.send_typing()` 当前只会发送一个不带 `typing` 字段的“正在输入”脉冲
- `MessageManager._process_typing()` 收到事件后只保留 `session_id` 和 `user_id`，会直接丢弃 `typing` 字段
- `ChatInterface._on_typing_event()` 也只会显示 typing indicator 并启动定时器，无法根据显式 `typing=false` 立即清除状态

证据：

- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2\server\app\api\v1\sessions.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2\client\managers\connection_manager.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2\client\ui\controllers\chat_controller.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client\ui\windows\chat_interface.py)

影响：

- 外部调用方或未来客户端如果发送 `typing=false`，当前桌面端不会按协议立即隐藏 typing 状态，只会继续走本地定时器
- 这说明 typing 目前并不是一个真正闭环的协议状态，而只是“收到一次开始输入脉冲后定时隐藏”的近似实现
- 在已经存在 HTTP / WS 双入口分叉的前提下，这会进一步放大联调和后续演进成本

建议：

- 明确 typing 的正式语义：要么定义为显式状态并把 `typing` 字段贯穿 WS / Client / UI，要么收口成无状态 pulse 模型并移除 HTTP 侧 `typing=false`
- 为 typing 补边界测试，至少覆盖“停止输入事件是否会立即清除 UI 状态”

### F-014：通话 signaling 对非法 `sdp` / `candidate` 不做失败校验，而是静默转发空 payload

状态：已修复（2026-04-14）

修复说明：

- `CallService.relay_offer()` / `relay_answer()` / `relay_ice()` 已在服务端边界校验 SDP/ICE 最小 contract：offer/answer 必须带匹配的 `sdp.type` 和非空 `sdp.sdp`，ICE 必须带非空 `candidate.candidate`
- 非法 signaling payload 会通过 WS `error` 返回 `INVALID_REQUEST`，不再把空字典转发给对端
- `AiortcVoiceEngine` 收到非法 ICE candidate 时会显式上报 `Invalid ICE candidate`，不再静默忽略
- 已补 `test_call_service_requires_accept_before_signaling_and_validates_payload`

原状态：已确认

现状：

- WebSocket Gateway 处理 `call_offer` / `call_answer` / `call_ice` 时，如果 `sdp` 或 `candidate` 不是字典，会直接把它们归一成空字典
- `CallService.relay_offer()` / `relay_answer()` / `relay_ice()` 只负责透传，不校验最小字段是否存在
- 客户端 `AiortcVoiceEngine` 在收到缺失 `sdp.type` / `sdp.sdp` 或缺失 `candidate.candidate` 的 payload 时，只会返回 `None` 或直接忽略
- 结果不是“请求被拒绝并返回错误”，而是“坏包被对端静默忽略”，联调时只会表现为通话无响应

证据：

- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2\server\app\websocket\chat_ws.py)
- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2\server\app\services\call_service.py)
- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2\client\call\aiortc_voice_engine.py)

影响：

- 非法 signaling payload 不会在服务端边界被尽早阻断，而会以“对端不响应”的形式外显，排障成本很高
- 这说明通话协议边界目前缺少成熟的输入验证，不符合“正式实时协议”的稳定性要求
- 在前面已经存在 payload 文档漂移的情况下，这类静默吞错会进一步放大联调失败概率

建议：

- `call_offer` / `call_answer` 至少应校验 `sdp.type` 与 `sdp.sdp`；`call_ice` 至少应校验 `candidate.candidate`
- 对非法 payload 应直接返回 `error` / `INVALID_REQUEST`，不要把空字典继续转发给对端
- 为通话 signaling 增加负面测试，覆盖非法 `sdp` / `candidate` 的拒绝行为

### F-015：桌面端多个 WebSocket 命令仍发送空 `msg_id`，不符合正式幂等协议

状态：已修复（2026-04-14）

修复说明：

- 已随 `R-027` 一并修复
- `_fetch_remote_messages()` 现在通过 `Database.get_messages_by_ids()` 批量读取本地已有消息，不再逐条 `get_message()`
- 已补 `test_message_manager_remote_history_uses_batch_existing_lookup_and_delta_write`

原状态：已确认

现状：

- 架构文档、协议文档和 ADR 都已经把 `msg_id` 定义为客户端命令幂等键，并明确要求对会改变状态的命令必须存在
- 但桌面端 `ConnectionManager.send_read_ack()`、`send_recall()`、`send_edit()` 当前都发送空 `msg_id`
- `send_typing()` 也发送空 `msg_id`；即使把 typing 视作瞬时状态而非持久化命令，这也会削弱日志追踪和错误回包关联
- 当前消息发送主链路只有 `send_chat_message()` 明确带了非空 `msg_id`

证据：

- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2\client/managers/connection_manager.py)
- [D:\AssistIM_V2\docs\architecture.md](D:\AssistIM_V2\docs/architecture.md)
- [D:\AssistIM_V2\docs\design_decisions.md](D:\AssistIM_V2\docs/design_decisions.md)
- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2\docs/realtime_protocol.md)

影响：

- 如果这些 WS helper 重新成为正式主链路，就天然不满足 ACK / 重试 / 幂等去重模型
- 服务端错误包或日志无法稳定关联到具体命令，排障成本会显著升高
- 这说明当前“只有消息发送真正遵守 `msg_id` 协议”，而其他命令还停留在半收口状态

建议：

- 只要保留这些 WS 命令，就应统一为每次请求生成稳定 `msg_id`，并在需要重试时复用
- 如果某些 helper 已不再作为正式入口，应尽快移除，避免未来调用方误以为它们已符合协议要求

### F-016：通话出站层把 `call_id` 复用为所有 signaling 命令的 `msg_id`

状态：已修复（2026-04-14）

修复说明：

- 服务端下行 `call_*` event envelope 已改为每次 fanout 生成独立 `msg_id`，不再整场通话复用 `msg_id=call_id`
- 客户端 call signaling 发送入口已补 current-call 和 accepted-stage guard；同一 `call_id` 下的 offer/answer/ICE 不再被当作可无条件复用的外层命令
- `call_id` 只作为业务级通话实例 ID 保留在 payload 内，transport/event id 与业务 id 已拆开
- 已补 `test_call_service_requires_accept_before_signaling_and_validates_payload` 与通话 WS 回归测试

原状态：已确认

现状：

- `CallManager.start_call()`、`accept_call()`、`reject_call()`、`hangup_call()`、`send_ringing()` 都直接把 `call_id` 作为 `msg_id`
- `_send_signal_payload()` 也会把同一个 `call_id` 继续用于 `call_offer`、`call_answer`、`call_ice`
- 这意味着同一场通话里的多条不同命令，甚至多条 ICE candidate，都会共享同一个外层命令幂等键
- 但文档已经把 `call_id` 定义为“这场通话的稳定 ID”，把 `msg_id` 定义为“这次客户端命令的幂等键”，两者语义并不相同

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2\client\managers\call_manager.py)
- [D:\AssistIM_V2\docs\architecture.md](D:\AssistIM_V2\docs/architecture.md)
- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2\docs/realtime_protocol.md)

影响：

- 如果服务端未来把通话命令也纳入统一幂等/日志模型，不同 signaling 命令会因为共享 `msg_id` 而无法被正确区分
- 多条 `call_ice` 复用同一个 `msg_id` 尤其危险，因为它们天然是多条不同命令，不应该互相覆盖或被视为同一次请求
- 这说明当前通话链路虽然复用了统一外层协议，但还没有真正对齐统一命令模型

建议：

- `call_id` 继续作为通话实例 ID 保留在 `data.call_id`
- 每次 signaling 命令单独生成自己的 `msg_id`；只有同一命令的重试才应复用同一个 `msg_id`
- 为通话 signaling 增加测试，显式覆盖“同一 call_id 下多条 ICE candidate 的 msg_id 不能相同”

### F-017：客户端处理 `message_edit` 时会丢弃服务端返回的顶层 read/session 元数据

状态：已修复（2026-04-14）

修复说明：

- `get_messages()` 不再把“本地页已满”伪装成 freshness 判断
- stale / authoritative refresh 由显式 `force_remote=True` 或 `before_seq` cursor 触发
- 非满页仍会自动回源补足历史页
- Chat/Message controller 已透传 `force_remote` 参数，避免上层只能借助页长旁路表达 freshness
- 已补 `test_message_manager_get_messages_uses_explicit_remote_freshness`

原状态：已确认

现状：

- 服务端 `MessageService.edit()` 会在 `message_edit` payload 顶层返回最新的 `session_seq`、`read_count`、`read_target_count`、`read_by_user_ids`
- 但客户端 `MessageManager._process_edit()` 没有复用统一的 `_normalize_loaded_message()` 入口，而是手工构造 `ChatMessage`
- 这段逻辑只会合并 `data.extra`，不会把顶层 `session_seq` / `read_count` / `read_by_user_ids` 等字段并回 `message.extra`
- 当前测试也只覆盖了编辑/撤回事件的基本更新，没有覆盖编辑后 read metadata 是否保持权威一致

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2\server\app\services\message_service.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)
- [D:\AssistIM_V2\client\tests\test_message_manager.py](D:\AssistIM_V2\client\tests\test_message_manager.py)

影响：

- 如果消息在被编辑前后 read cursor 已经推进，客户端可能继续保留旧的 read metadata，而不是服务端返回的权威值
- 这会让编辑后的消息已读状态、read badge 或后续状态推导出现滞后或回退
- 这类问题隐蔽性很高，因为普通“编辑成功”路径看起来仍然可用

建议：

- `message_edit` 应统一走 `_normalize_loaded_message()`，或者至少把顶层 `session_seq` / `read_count` / `read_target_count` / `read_by_user_ids` / `is_read_by_me` 全量并回 `extra`
- 为编辑事件补测试，覆盖“编辑后的消息仍保留最新 read metadata”

### F-018：会话列表“标为未读/已读”只是本地临时值，会被后端 authoritative unread 重新覆盖

状态：已修复（2026-04-14）

修复说明：

- `MessageRepository.list_missing_messages_for_user()` 不再为每个 session 构造一支 `OR`
- 当前查询改为先批量加载用户可见 `session_id`，再用 `Message.session_id.in_(...)` 限定范围，并通过 `CASE WHEN Message.session_id == ... THEN cursor ELSE 0 END` 表达每个 session 的 cursor
- 已用 websocket sync cursor 回归测试覆盖查询行为不变

原状态：已确认

现状：

- 会话列表右键菜单提供了“标为未读 / 标为已读”操作
- `SessionManager.mark_session_unread()` 只是直接修改本地 `session.unread_count` 和 SQLite
- 但 `SessionManager._reconcile_unread_counts()`、`refresh_remote_sessions()`、`_on_history_synced()` 又会从 `/sessions/unread` 拉取后端 authoritative unread 并覆盖本地值
- 当前服务端 unread 模型只表达真实未读游标，不表达用户手动“稍后再看”的本地标记

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2\client\ui\widgets\session_panel.py)
- [D:\AssistIM_V2\client\ui\controllers\session_controller.py](D:\AssistIM_V2\client\ui\controllers\session_controller.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)
- [D:\AssistIM_V2\client\services\session_service.py](D:\AssistIM_V2\client\services\session_service.py)
- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2\server\app\api\v1\sessions.py)

影响：

- 用户手动“标为未读”后，只要发生一次会话刷新、历史同步或重连补偿，这个状态就可能被后端真实未读数立即覆盖
- 功能表面上存在，但没有稳定领域模型支撑，属于典型的“看起来有，实际上不可靠”的实现
- 这也进一步说明客户端当前同时混着“本地 UI 状态”和“后端权威未读状态”，边界不清晰

建议：

- 如果产品要支持“标为未读/稍后处理”，应单独建立本地或服务端的 `manual_unread` / `needs_attention` 语义，而不是直接改写 authoritative unread count
- 如果不打算支持稳定的手动未读状态，应移除该入口，避免误导用户

### F-019：服务端通话状态没有断连/超时清理，异常退出后可能长期卡成 busy

状态：已修复（2026-04-14）

修复说明：

- `InMemoryCallRegistry` 增加终态 snapshot 与 `end_for_offline_user()`，active call 被结束时会释放双方 busy 映射
- `chat_ws.py` 在用户最后一条 WS 连接断开时会结束该用户占用的 active call，并向参与方广播 `call_hangup(reason=disconnect)`
- 客户端 unanswered timeout 仍保留为本地 UX 兜底，但服务端不再完全依赖客户端正常发送 `hangup` 才释放 busy 状态
- 已补通话 WS 回归，并保留 `test_private_call_signaling_preserves_timeout_reason`

原状态：已确认

现状：

- 服务端当前通过进程内 `InMemoryCallRegistry` 维护活跃通话，并在发起新通话时通过 `get_for_user()` 做 busy 判断
- 但 WebSocket 断连收尾只会做连接注销和 offline 广播，不会结束该用户相关的活跃通话
- `InMemoryCallRegistry` 本身也没有 TTL/过期清理逻辑
- 当前唯一的 unanswered timeout 在桌面端 `CallManager` 本地；如果客户端崩溃、断网或进程被杀，没有任何服务端兜底去释放这条通话状态

证据：

- [D:\AssistIM_V2\server\app\realtime\call_registry.py](D:\AssistIM_V2\server\app\realtime\call_registry.py)
- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2\server\app\services\call_service.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2\server\app\websocket\chat_ws.py)
- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2\client\managers\call_manager.py)

影响：

- 一旦发起方或接收方在未正常发送 `call_hangup` 的情况下异常退出，服务端仍可能保留这条活跃通话
- 后续新的来电会被 `busy` 检查挡住，直到进程重启或有人手动把旧通话结束
- 这说明当前通话状态机还不具备成熟系统应有的服务端自愈能力

建议：

- 服务端应为活跃通话增加 TTL / 心跳过期清理，不能只依赖客户端本地超时
- WebSocket 断连时至少应评估是否结束该用户唯一活跃的 pending call，并向对端广播明确终止原因
- 为“异常断开后 busy 是否自动释放”补集成测试

### F-020：会话最后一条本地消息被删除后，预览时间仍保留旧值，列表排序会出现“空会话假活跃”

状态：已修复（2026-04-14）

修复说明：

- 该项已由 `F-783` / `F-784` / `F-785` 的代码修复共同关闭
- session `unread_count` 已接入服务端权威未读计数，不再固定返回 dummy `0`
- session `session_crypto_state` 已从服务端 session formal payload / `SessionOut` 移除
- message `is_ai` 已从服务端 message formal payload / `MessageOut` 移除，AI 会话语义保留在已有 `is_ai_session`
- 当前 G-01 文档补记该项关闭状态

原状态：已确认

现状：

- `SessionManager.refresh_session_preview()` 在本地已无消息时，会把 `preview_time` 回退成现有 `session.last_message_time`
- `_apply_last_message_preview(session, None, ...)` 虽然会清空 `last_message` 和相关 extra，但不会修正这个时间
- 会话排序又是按 `last_message_time` 倒序，因此“最后一条消息已删除、预览已空”的会话仍可能保持原先的高排序位置

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)

影响：

- 用户删除本地最后一条消息或收到删除事件后，左侧会话列表可能出现“预览为空但仍像最近活跃”的错乱排序
- 这会让会话列表的活跃度排序不再反映真实本地状态

建议：

- 当 `get_last_message(session_id)` 为空时，`last_message_time` 应回退到 `created_at` 或显式清空，而不是继续沿用旧的 `last_message_time`
- 为“删除最后一条消息后会话排序是否更新”补一条 UI/manager 边界测试

### F-021：桌面端本地禁止二次编辑消息，但服务端规则并没有这条限制

状态：已修复（2026-04-14）

修复说明：

- 该项已由 `F-788` / `F-789` 以及 `R-078` 的代码修复共同关闭
- 单会话历史分页入口已从时间戳 cursor 收口到 `before_seq`
- `MessageRepository.list_session_messages()` 使用 `Message.session_seq < before_seq` 翻页，并按 `session_seq DESC, created_at DESC` 取页后反转
- reconnect 缺失消息补偿已按 `session_id, session_seq, created_at, id` 输出，同一会话内以 `session_seq` 为 authoritative order
- 当前 G-01 文档补记该项关闭状态

原状态：已确认

现状：

- 服务端 `MessageService.edit()` 只校验“发送者本人”和“编辑时间窗口”，没有禁止同一条消息被再次编辑
- 但桌面端 `MessageManager.edit_message()` 在本地看到 `message.status == edited` 就直接拒绝，连请求都不会发出去
- 这意味着同一条消息在服务端语义上仍可编辑时，桌面端主链路已经提前把它封死

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2\server\app\services\message_service.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)

影响：

- 桌面端用户无法在时间窗口内连续修正同一条消息，而其他调用方或服务端接口仍可能允许
- 这是明确的前后端业务规则分叉，会导致“文档/接口允许，但桌面端做不到”的用户体验问题

建议：

- 如果产品语义允许多次编辑，桌面端应移除这条本地硬限制
- 如果产品语义只允许一次编辑，就应把这条规则提升为服务端权威校验，并补充正式文档与测试

### F-022：实时 `user_profile_update` 不会推进客户端事件游标，重连后会重复补偿

状态：已修复（2026-04-14）

修复说明：

- `add_member/remove_member/leave_group` 已接入服务端 `group_profile_update` lifecycle event；成员移除/离群同时向不可见目标发送 `contact_refresh` tombstone，客户端会刷新 authoritative session snapshot。

现状：

- 服务端 `user_profile_update` 会写入 `session_events`，带正式 `event_seq`，并且也会通过 `history_events` 做离线补偿
- 但客户端 `ConnectionManager._on_message()` 当前只对 `message_edit`、`message_recall`、`message_delete`、`read`、`group_profile_update`、`group_self_profile_update` 推进 `event_sync_cursors`
- `user_profile_update` 被漏掉了：实时收到时不会推进本地 `event_seq` 高水位
- 一旦之后发生重连或断线补偿，请求仍可能带着旧游标，把同一条 `user_profile_update` 再次作为离线事件回放回来

证据：

- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2\client\managers\connection_manager.py)
- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2\server\app\api\v1\users.py)
- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2\server\app\services\user_service.py)
- [D:\AssistIM_V2\server\tests\test_chat_api.py](D:\AssistIM_V2\server\tests\test_chat_api.py)

影响：

- 用户资料变更事件在实时收到后，后续重连仍可能被重复补偿
- 这会带来重复 UI 刷新、重复数据库写入和更复杂的事件去重路径

建议：

- 把 `user_profile_update` 纳入 `ConnectionManager` 的 event cursor 推进集合
- 为“实时收到后重连不应重复回放同一 profile event”补一条连接层测试

### F-023：协议文档仍低估了 `event_seq/history_events` 的正式事件集合

状态：已修复（2026-04-14）

修复说明：

- `update_member_role()` / `transfer_ownership()` 现在写入并广播 `group_profile_update` shared event，事件 payload 携带统一 `mutation`，离线重连可通过 `history_events` 回放。

现状：

- 服务端当前已经把 `user_profile_update`、`group_profile_update`、`group_self_profile_update` 写入 `session_events`，并通过 `history_events` 做离线补偿
- 但协议文档和架构文档里列举的“当前纳入 `event_seq` 的事件”仍主要只写了 `read`、`message_edit`、`message_recall`、`message_delete`
- 这会让实现、测试夹具和后续 review 很容易低估 profile/group 元数据事件在补偿模型中的正式地位

证据：

- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2\server\app\api\v1\users.py)
- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2\server\app\services\user_service.py)
- [D:\AssistIM_V2\server\tests\test_chat_api.py](D:\AssistIM_V2\server\tests\test_chat_api.py)
- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2\docs\realtime_protocol.md)
- [D:\AssistIM_V2\docs\architecture.md](D:\AssistIM_V2\docs\architecture.md)
- [D:\AssistIM_V2\docs\backend_architecture.md](D:\AssistIM_V2\docs\backend_architecture.md)

影响：

- 新调用方或测试如果按文档理解 event 模型，容易漏掉这些 profile/group 事件的补偿与 cursor 处理
- 这会继续放大实现和文档的分叉，也会让像 `F-022` 这种 cursor 漏推问题更难被及时发现

建议：

- 把所有当前正式进入 `history_events` 的事件类型在文档里完整列出来
- 文档中应明确区分“正式 event_seq 事件”和“非补偿型瞬时通知”，避免继续混淆

### F-024：会话刷新主链路对 unread 拉取失败没有降级处理，会直接崩掉整次 refresh

状态：已修复（2026-04-14）

修复说明：

- `POST /sessions/direct` 新建会话后广播 `contact_refresh(reason=session_lifecycle_changed)`；客户端 `SessionManager` 收到 lifecycle invalidation 后刷新远端 authoritative session snapshot。未接入的 `DELETE /sessions/{id}` 仍保持 405。

现状：

- `SessionManager.refresh_remote_sessions()` 会先拉会话列表，再调用 `_fetch_remote_unread_counts()`
- `_fetch_remote_unread_counts()` 在请求失败时会记录 warning 并返回 `None`
- 但 `refresh_remote_sessions()` 随后仍直接执行 `unread_count_map.get(session.session_id, 0)`，没有处理 `None`
- 结果是一旦 `/sessions/unread` 请求失败，即使会话列表已经成功返回，整次刷新仍会抛异常

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)

影响：

- 启动后的远端会话刷新、手动刷新或其他依赖 `refresh_remote_sessions()` 的主链路，会因为 unread 接口失败而整体失败
- 这和 `_reconcile_unread_counts()` 已经做了 `None` 降级处理形成明显不一致，说明刷新主路径还没完全稳态化

建议：

- `refresh_remote_sessions()` 应在 unread 拉取失败时降级为默认 `0` 或保留已有本地 unread，而不是让整次会话刷新失败
- 为“会话列表成功但 unread 拉取失败”的场景补一条边界测试

### F-025：会话全量刷新把管理器当前会话清空后，聊天窗体自己的 `_current_session_id` 不会同步失效

状态：已修复（2026-04-14）

修复说明：

- `POST /groups` 现在写入 `group_profile_update` create event 并 fanout 给群成员；`DELETE /groups/{id}` 返回 tombstone mutation，并向原成员广播 `contact_refresh(reason=group_deleted)`。

现状：

- `SessionManager._replace_sessions()` 在全量远端刷新后，如果当前 `self._current_session_id` 已经不在新的会话集合里，会主动把管理器侧 `current_session_id` 置空
- 但桌面端 `ChatInterface` 还维护了另一份 `_current_session_id`；`_on_session_event()` 只有在收到 `SessionEvent.DELETED` 这种“单会话删除事件”时才会清空它
- 对于 `refresh_remote_sessions()` 触发的 `SessionEvent.UPDATED {"sessions": ...}`，`ChatInterface._on_session_event()` 只是重新取一次 session；若当前会话已经不存在，它既不会清空 `_current_session_id`，也不会切回 welcome
- 后续 typing、文件发送、截图发送、静音/置顶等多个 UI 动作仍然先读 `ChatInterface._current_session_id`，会继续尝试按这个 stale session id 发起操作

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client\ui\windows\chat_interface.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client\main.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2\client\ui\controllers\chat_controller.py)

影响：

- 如果当前会话因为远端刷新被过滤掉，例如成员关系变化、可见性变化或隐藏 tombstone 生效，聊天主窗体可能继续显示旧会话内容，而不是切回欢迎页
- 此时部分动作会悄悄失效，部分动作会继续带着陈旧 `session_id` 往下走，形成明显的 UI/状态不同步
- 这属于典型的双写状态漂移：管理器和窗口各维护一份“当前会话”，但失效条件没有统一

建议：

- 让 `ChatInterface` 在收到全量 `sessions` 更新且当前会话已不存在时，也同步清空 `_current_session_id` 并切回 welcome
- 更稳的方案是收口“当前会话”单一真相，避免窗口层和 `SessionManager` 分别维护一份可失步的 state

### F-026：会话全量刷新移除会话时不会发出等价删除语义，托盘提醒等只订阅 `DELETED` 的消费者会残留陈旧状态

状态：已修复（2026-04-14）

修复说明：

- `GroupCreate.name` 改为必填非空；客户端两个建群入口会提交冻结成员集对应的默认群名，服务端不再接收 unnamed group。

现状：

- `SessionManager._replace_sessions()` 在全量远端刷新时会直接清空 `_sessions` 并写入新快照；对“这次刷新里消失的会话”不会逐个发 `SessionEvent.DELETED`
- `SessionPanel` 因为直接吃 `SessionEvent.UPDATED {"sessions": ...}` 的全量列表，所以视觉上能跟着重建
- 但 [main_window.py](D:\AssistIM_V2\client\ui\windows\main_window.py) 的托盘提醒删除逻辑只订阅 `SessionEvent.DELETED`
- `MainWindow._on_tray_session_updated()` 处理全量 `sessions` 更新时，只会同步仍然存在于列表中的 `session_id`；对“这次快照里已经不存在”的旧 tray entry 不会清理

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2\client\ui\windows\main_window.py)
- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2\client\ui\widgets\session_panel.py)

影响：

- 如果某个会话因为全量刷新被过滤掉，例如成员关系变化、可见性变化或本地隐藏 tombstone 生效，托盘里旧的未读提醒可能继续残留
- 这说明 `SessionEvent.UPDATED {"sessions": ...}` 和 `SessionEvent.DELETED` 之间缺少统一的语义边界，不同消费者需要自己猜“全量替换”是否包含删除

建议：

- 选一种模型收口：要么在 `_replace_sessions()` 里为消失的会话补发 `DELETED`，要么明确定义“全量 `sessions` 更新等价于 authoritative replace”，并让托盘等消费者按 diff 主动清理缺失会话
- 为“全量刷新后会话消失”补 UI/事件边界测试，至少覆盖 chat 窗口和 tray alert 这两个消费者

### F-027：会话列表的全量刷新快照没有包含头像字段，avatar-only 变化会被错误跳过

状态：已修复（2026-04-14）

修复说明：

- `GroupProfileUpdate.name` 现在拒绝空白值；有效 diff 才会写回 `groups/sessions`。

现状：

- [session_panel.py](D:\AssistIM_V2\client\ui\widgets\session_panel.py) 用 `_session_snapshot()` 判断一次全量 `sessions` 更新是否值得重建列表
- 这个 snapshot 当前只包含 `session_id`、显示名、最后一条消息、时间、未读、置顶、@我、静音、草稿预览等字段，没有把 `avatar` / `display_avatar()` 算进去
- 因此如果一次全量会话刷新只改变了头像，而名称、预览、未读等字段都没变，`_load_all_sessions_safe()` 会直接 `return`，列表模型不会更新
- 启动后的远端 warmup 正是正式触发点之一：本地数据库先加载旧会话，再由 `refresh_remote_sessions()` 用服务端快照覆盖；如果这次只带来了新的头像，列表仍会继续显示旧头像

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2\client\ui\widgets\session_panel.py)
- [D:\AssistIM_V2\client\models\session_model.py](D:\AssistIM_V2\client\models\session_model.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client\main.py)

影响：

- 用户头像、群头像在“全量刷新但没有对应单会话增量事件”的场景下可能长期停留在旧值
- 这属于典型的 presentation cache 漏字段：为了省一次列表重建，把实际展示字段排除在比较签名之外

建议：

- 把 `avatar` 或 `display_avatar()` 纳入 `_session_snapshot()`，确保 avatar-only 变化也能触发列表刷新
- 为“本地缓存旧头像，远端全量刷新只更新头像”的场景补 UI 边界测试

### F-028：全量远端刷新不会搬运本地 `draft_preview`，侧边栏草稿预览会被静默抹掉

状态：已修复（2026-04-14）

修复说明：

- `update_group_profile()` 会先计算 shared diff；无变化时返回 `changed=false` 且路由不再写入/广播 `group_profile_update`。

现状：

- 聊天窗体把未发送草稿正文保存在 [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_composer_drafts` 中，并把简短预览写到当前 `Session` 对象的 `draft_preview`
- `SessionManager._replace_sessions()` 在远端全量刷新时会创建新的 `Session` 对象，再通过 `_carry_local_session_state()` 搬运本地状态
- 但 `_carry_local_session_state()` 当前只保留了置顶、静音、群昵称显示、announcement viewed、crypto/call 状态等字段，没有保留 `draft_preview`
- 结果是只要发生一次 `refresh_remote_sessions()`，非当前会话的侧边栏草稿预览就会消失；真正的草稿正文仍留在 `_composer_drafts`，只有重新点回该会话后才会再次写回预览

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client\ui\windows\chat_interface.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)

影响：

- 用户会看到左侧列表里的“草稿”提示在登录 warmup、重连刷新或手工刷新后无故消失
- 这类问题很隐蔽，因为真正的草稿内容并没有丢，只是列表预览和本地状态搬运不一致

建议：

- 把 `draft_preview` 纳入 `_carry_local_session_state()`，或在全量刷新后由 `ChatInterface` 重新把 `_composer_drafts` 投影回所有 session preview
- 为“存在本地草稿时触发 `refresh_remote_sessions()`”补 UI 边界测试

### F-029：本地隐藏会话不会清空聊天窗体内存缓存，后续会话复活时可能重新贴回已删除的本地状态

状态：部分修复（2026-04-14）

修复说明：

- `serialize_group()` 的 shared 视图不再向其它成员广播成员私有 `group_nickname`；`serialize_session()` 的成员切片仍保留既有 self-facing 字段，后续若要彻底分层需另开 session-detail contract。

现状：

- `SessionManager.remove_session()` 会删除本地数据库里的 `sessions/messages/session_read_cursors`，并把该会话记成隐藏 tombstone
- 但 [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 维护的 `_history_page_cache`、`_session_view_state`、`_composer_drafts` 在会话删除时不会同步清空
- `ChatInterface._on_session_event()` 对 `SessionEvent.DELETED` 只会在“当前正打开的就是这个会话”时清掉可见面板，并不会清除这些缓存字典
- 一旦该会话因为新消息或后续刷新重新出现，再次点开时 `_on_session_selected()` 会优先恢复 `_session_view_state` 和 `_composer_drafts`，把之前本应被本地删除的旧消息视图、滚动状态和草稿重新贴回去

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client\storage\database.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client\ui\windows\chat_interface.py)

影响：

- “删除会话并清除本地记录”当前只清掉了数据库，不清内存缓存；同一次应用会话内仍可能看到旧历史和旧草稿回流
- 这会让本地隐藏语义进一步不稳定，也会让后续会话复活时呈现出和数据库状态不一致的旧 UI

建议：

- 在会话删除/隐藏时同步清除 `ChatInterface` 的该会话历史缓存、view state 和草稿缓存
- 为“本地删除会话后，同一进程内再次收到该会话并重新打开”的场景补 UI 边界测试

### F-030：聊天窗体的 read-receipt 去重缓存不会随会话删除/复活清理，可能跳过本应重新发送的已读

状态：部分修复（2026-04-14）

修复说明：

- `serialize_group()` 的 `member_version/group_member_version` 已改按 `GroupMember` authoritative roster 计算，并纳入 role、owner 和 joined_at；`serialize_session()` 的版本口径仍需在 session contract 单独收口。

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 用 `_last_read_receipts` 和 `_pending_read_receipts` 做本地已读去重
- 这两个缓存会在 `_schedule_read_receipt()` / `_send_read_receipt_for()` 里读写，但当前没有按 `session_id` 清理的路径；搜索结果只看到初始化、读取和写入
- `SessionManager.remove_session()` 会删除本地数据库里的消息和 read cursor，但不会通知 `ChatInterface` 清除这两份内存去重缓存
- 一旦同一会话在同一进程内再次出现，且最新可读消息 `message_id` 与删除前一致，`_schedule_read_receipt()` 会因为 `_last_read_receipts[session_id] == message_id` 直接跳过发送

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client\ui\windows\chat_interface.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client\storage\database.py)

影响：

- 用户在本地删除/隐藏会话后，如果该会话很快因已有未读消息重新出现，客户端可能不会再次发送应有的 read receipt
- 这会让服务端 authoritative unread 与客户端当前可见状态继续分叉，且问题只会出现在“同一进程内复活”的边界场景，比较难排查

建议：

- 在会话删除/隐藏以及全量会话替换移除会话时，按 `session_id` 清理 `_last_read_receipts` 和 `_pending_read_receipts`
- 为“本地删除会话后重新打开同一未读消息”补已读补发测试

### F-031：会话删除后不会取消该会话的后台历史加载任务，已删除会话的缓存可能被异步重新种回内存

状态：已修复（2026-04-14）

修复说明：

- `add_member()` 现在先检查 `SessionMember/GroupMember` 是否已存在；重复添加返回 409，不再 bump 群头像版本。

现状：

- `ChatInterface` 会为会话启动 `_load_task`、`_history_load_task` 和 `_history_page_tasks`，并通过 `_prime_history_page()` / `_load_history_page()` 把历史页缓存到 `_history_page_cache`
- 但在收到 `SessionEvent.DELETED` 时，`_on_session_event()` 只会清当前会话显示，不会按 `session_id` 调用 `_invalidate_session_caches()`，也不会取消对应的 `_history_page_tasks`
- 因此如果删除会话时后台仍有 warm/history load 在跑，这些任务完成后仍会把该 `session_id` 的历史页重新写回 `_history_page_cache`
- 这和 `SessionManager.remove_session()` / `database.delete_session()` 已经把本地数据库记录删掉的语义直接冲突

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client\ui\windows\chat_interface.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client\storage\database.py)

影响：

- 即使修掉静态缓存残留，删除动作发生时正在进行的异步历史任务仍可能把会话缓存“复活”回来
- 这会放大 `F-029` 的表现，让“清除本地记录”在同一进程内更难真正成立

建议：

- 在会话删除/隐藏时按 `session_id` 调用 `_invalidate_session_caches(session_id)`，并取消对应 `_history_page_tasks`
- 为“删除会话时后台 history warm/load 尚未完成”的场景补回归测试

### F-032：全量会话刷新移除当前会话时没有同时清掉 `current_session_active`，后续选中新会话会错误清空未读

状态：已修复（2026-04-14）

修复说明：

- `remove_member()` / `leave_group()` 现在校验 group/session 两侧成员记录，缺失时返回明确错误，不再静默成功或推进 avatar/version。

现状：

- `SessionManager._replace_sessions()` 在当前会话不再存在时只执行 `self._current_session_id = None`
- 但同一个管理器里，`select_session()` 会在 `self._current_session_active` 为真时立即对新选中的会话执行 `clear_unread(session_id)`
- 当前实现没有在 `_replace_sessions()` 里同步把 `_current_session_active` 置回 `False`
- 因此如果旧会话在“前台可读”状态下被全量刷新移除，管理器侧会留下 `current_session_active=True` 但 `current_session_id=None` 的不一致状态；之后第一次 `select_session(new_id)` 会把新会话当成“已处于前台激活状态”，直接清零未读

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)

影响：

- 这会让某些新选中的会话在 UI 还没真正进入前台活跃状态前就被错误标记为已读
- 问题根源是同一套“当前会话激活态”没有在 full snapshot replace 时完成原子失效

建议：

- 在 `_replace_sessions()` 因会话消失而清空 `current_session_id` 时，也同步把 `_current_session_active` 置回 `False`
- 为“当前活跃会话在全量刷新中消失，然后切到另一个会话”的 unread 边界补测试

### F-033：删除后残留的 `_session_view_state` 会让复活会话跳过正式历史加载，直接显示过期缓存

状态：已修复（2026-04-14）

修复说明：

- `GroupMemberAdd.role` schema 收口为 `Literal["member"]`，请求仍保留字段名但正式能力只允许默认成员角色。

现状：

- `ChatInterface._on_session_selected()` 选中会话时，如果 `_session_view_state[session_id]` 已存在，会先 `_restore_session_view_state()`，然后只调用 `_select_session_only(session_id)`
- `_select_session_only()` 只做 `select_session()` 和 active 状态同步，不会触发 `_load_session_messages()` 或远端历史回拉
- 但当前删除会话路径不会清掉 `_session_view_state[session_id]`，这在 `F-029` 已经确认
- 因此一旦同一会话后来重新出现在列表里，第一次重新打开时会优先恢复旧的可见消息切片和滚动状态，并跳过正式历史加载

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client\ui\windows\chat_interface.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)

影响：

- 用户重新打开“已删除后复活”的会话时，可能直接看到删除前的旧消息视图，而不是当前数据库/服务端的权威历史
- 这不是单纯的缓存残留，而是恢复分支本身把正式加载链路短路了

建议：

- 删除/隐藏会话时必须同步清除 `_session_view_state`
- 或者在 `_on_session_selected()` 中为“本地会话刚复活”增加校验，不允许仅因存在 cached_state 就跳过正式消息加载

### F-034：全量会话刷新不会按 diff 驱逐已消失会话的窗口级缓存，后续会话回流时仍会复用旧本地状态

状态：已修复（2026-04-14）

修复说明：

- `GroupMemberRoleUpdate.role` 改为必填字段，空 PATCH 返回 422，不再隐式降权为 `member`。

现状：

- `ChatInterface` 的 `_history_page_cache`、`_session_view_state`、`_composer_drafts`、`_last_read_receipts` 都是按 `session_id` 建索引的本地状态
- 但 `SessionManager._replace_sessions()` 发出的只是 `SessionEvent.UPDATED {"sessions": ...}`；`ChatInterface._on_session_event()` 对这类全量更新不会计算“哪些 session 从列表里消失了”，也不会按 diff 清理这些缓存
- 当前只有消息/已读/编辑等增量事件会调用 `_invalidate_session_caches(session_id)`；全量 session snapshot replace 不会
- 因此只要会话因为成员关系、可见性、隐藏 tombstone 或远端过滤而从列表中消失，对应窗口级缓存就会继续滞留，直到该 `session_id` 未来再次回流时被复用

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client\ui\windows\chat_interface.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)

影响：

- 这会让“full snapshot replace 是权威替换”在聊天窗口层失效；列表虽然已经收敛到远端真相，窗口缓存却仍保留旧本地态
- 后续一旦同一 `session_id` 回来，就可能直接继承旧历史缓存、旧草稿、旧已读去重状态，形成一连串复合问题

建议：

- 对 `SessionEvent.UPDATED {"sessions": ...}` 建立 diff 逻辑，按“旧集合 - 新集合”批量清理窗口级 per-session 缓存
- 为“会话从全量快照中消失，再次回流”的场景补缓存驱逐测试

### F-035：本地删除会话不会清理已下载附件文件，`清除本地记录` 语义只删了数据库没删磁盘

状态：已修复（2026-04-14）

修复说明：

- `transfer_ownership()` 现在拒绝 `new_owner_id == current_user.id`，self-transfer 返回 409。

现状：

- 下载附件时，[message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 会把文件落到 `%TEMP%\\assistim_downloads\\{message_id}_{file_name}`，并把路径写入消息 `extra.local_path`
- 但 `SessionManager.remove_session()` 最终只调用 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `delete_session(session_id)`，该方法只删除 `messages / session_read_cursors / sessions` 三张表记录
- 当前删除会话链路里没有任何按 `local_path` 删除本地附件文件的逻辑

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client/storage/database.py)

影响：

- UI/文案和产品语义都在强调“仅当前设备移除并清除本地记录”，但已下载的附件明文/解密文件仍会残留在磁盘临时目录
- 这不仅是语义不一致，也带来本地隐私残留和磁盘泄漏风险

建议：

- 删除/隐藏会话时应遍历该会话消息里的 `extra.local_path` 并清理对应本地附件文件
- 至少为“删会话后附件文件是否被删除”补一条本地存储边界测试

### F-036：显式 `remove_session()` 删除当前会话时同样不会清掉 `current_session_active`

状态：已修复（2026-04-14）

修复说明：

- `serialize_group()` 改用 `AvatarService.resolve_group_avatar_url()`，普通 group 读取不再调用 `ensure_group_avatar()` 或回写 `session.avatar`。

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `remove_session()` 在删除当前会话时只做了 `self._current_session_id = None`
- 它没有像 `clear_current_session()` 那样同步把 `self._current_session_active = False`
- 因此如果用户在前台激活状态下显式删除当前会话，管理器会留下 `current_session_active=True` 但 `current_session_id=None` 的不一致状态
- 后续第一次 `select_session(new_id)` 时，会命中 `select_session()` 里“如果 `_current_session_active` 为真就立刻 `clear_unread(new_id)`”的分支

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)

影响：

- 这会让用户删除当前会话后，下一次点开的任意会话都可能被错误地立即清空未读
- 问题和 `F-032` 类似，但这是更直接的显式删除链路，不依赖 full snapshot replace

建议：

- 在 `remove_session()` 删除当前会话时，同步把 `_current_session_active` 置回 `False`
- 为“删除当前激活会话后再选择另一会话”的 unread 边界补测试

### F-037：删除会话时未取消附件预取任务，运行中的预取可能把已删消息重新写回数据库

状态：已修复（2026-04-14）

修复说明：

- `serialize_session()` 的 group avatar 分支改为只读解析 URL，不再在 session 列表/详情读取时触发 `ensure_group_avatar()`。

现状：

- `MessageManager` 会为加密图片/视频启动 `_media_prefetch_tasks[message_id]`，后台执行 `_prefetch_encrypted_media()`
- 该任务内部先通过 `download_attachment(message_id)` 读取消息、下载文件，并在完成后调用 `self._db.save_message(message)` 把 `local_path` 写回数据库
- 而 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `save_message()` 使用的是 `INSERT OR REPLACE INTO messages`
- 当前删除会话链路没有取消这些 `_media_prefetch_tasks`；如果任务在删除前已经拿到了 `message` 对象，删除后仍可能继续执行 `save_message(message)`，把刚删掉的消息行重新插回本地库

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client/storage/database.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)

影响：

- “删除会话并清除本地记录”当前不仅可能留下内存缓存和附件文件，甚至可能在后台任务完成后把消息记录重新写回数据库
- 这会让问题从 presentation 层扩大到本地持久化层，直接破坏删除动作的可靠性

建议：

- 删除/隐藏会话时按 `session_id` 取消相关附件预取任务，或让 `download_attachment/save_message` 在写回前再次确认消息/会话仍有效
- 为“删除会话时附件预取仍在进行”补数据库回归测试

### F-038：删除会话不会取消待 ACK / 待重试的出站消息状态，后台仍可能继续发送并重写本地消息

状态：已修复（2026-04-14）

修复说明：

- `SessionRepository.update_avatar()` 现在会同步推进 `session.updated_at`；该方法也已从普通读路径剥离。

现状：

- `MessageManager` 用 `_pending_messages`、`_ack_check_task` 和 `MessageSendQueue` 跟踪待 ACK、待重试的 websocket 出站消息
- `SessionManager.remove_session()` / `database.delete_session(session_id)` 不会通知 `MessageManager` 按 `session_id` 清理这些 pending 状态，也不会从发送队列里剔除对应消息
- 后续 `_check_pending_messages()` 仍会对这些 pending 项执行 `_enqueue_pending_message()` 重发
- 如果最终失败，`_finalize_pending_failure()` 还会再次 `save_message(pending.message)`；而 `save_message()` 使用 `INSERT OR REPLACE INTO messages`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client/storage/database.py)

影响：

- 用户删除/隐藏会话后，之前已经进入发送中的本地消息仍可能继续发往服务端
- 即使网络失败，这些 pending 消息也可能被失败回写重新插回本地数据库，继续破坏“清除本地记录”的语义
- 这说明删除会话当前没有形成真正的“按 session_id 取消消息生命周期”边界

建议：

- 删除/隐藏会话时按 `session_id` 清理 `_pending_messages`，并让发送队列/ACK 重试链路跳过已删除会话
- 为“删除会话时存在 sending/awaiting-ack 消息”的场景补发送与数据库回归测试

### F-039：本地删除会话不会清理重连同步游标，会话回流后可能直接跳过应补的历史

状态：已修复（2026-04-14）

修复说明：

- `add_member/remove_member/leave_group` 写路径现在在真实成员变更后调用 `touch_without_commit()`，让群成员生命周期进入 session freshness。

现状：

- `ConnectionManager` 用 `_session_sync_cursors` / `_event_sync_cursors` 记录每个 `session_id` 的 reconnect cursor，并持久化到 `app_state`
- 登录 warmup 会通过 `reload_sync_timestamp()` 重新加载这些游标，后续 sync 请求也会把它们原样带给服务端
- 但 `SessionManager.remove_session()` / `database.delete_session(session_id)` 只删除本地 session、message、read cursor，不会按 `session_id` 清理这些 reconnect cursor
- 因此同一会话如果之后重新出现，客户端仍会带着旧的高水位 `session_seq/event_seq` 发起同步；而本地数据库已经被删空，服务端又会认为这些历史早就补过，从而不再回放较早消息/事件

证据：

- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2\client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client/storage/database.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)

影响：

- 这会让“本地删除后重新出现”的会话直接丢失应补历史，不只是 UI 缓存问题，而是 reconnect 一致性模型本身被破坏
- 问题根源是“本地删除会话”只清了一半本地状态：数据库游标删了，但连接层 authoritative reconnect cursor 没删

建议：

- 删除/隐藏会话时按 `session_id` 同步清理 `_session_sync_cursors`、`_event_sync_cursors` 及其持久化 app state
- 为“删会话后重新收到同一 session 的历史同步”补断线补偿回归测试

### F-040：删除会话不会取消 in-flight 的远端 session fetch，完成后可能把刚删除的会话重新加回列表

状态：已修复（2026-04-14）

修复说明：

- `update_member_role()` 在有效角色变更时推进 `session.updated_at`；`transfer_ownership()` 也会推进 session freshness。

现状：

- `SessionManager._ensure_session_exists()` 会为缺失会话创建并复用 `_session_fetch_tasks[session_id]`
- fetch 完成后，只要当前 `_sessions` 里还没有这个 `session_id`，就会直接 `add_session(session)`，中间不会检查该会话是否刚被用户本地隐藏/删除
- `remove_session()` 只会把会话从 `_sessions` 弹出并记录 hidden tombstone，不会取消同一 `session_id` 的 `_session_fetch_tasks`
- 因此如果用户在一次消息接收/历史同步触发的 session fetch 还没完成时删除会话，任务完成后仍可能把该会话重新写回本地列表和数据库

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)

影响：

- 这会让“删除会话=仅当前设备隐藏”的语义在并发场景下失效，会话可能在同一轮异步任务完成后立即复活
- 问题不依赖后续真的有新消息，只要旧的 fetch 已经在路上，就可能把用户刚做的本地隐藏操作覆盖掉

建议：

- 删除/隐藏会话时取消对应 `session_id` 的 `_session_fetch_tasks`，或在 `add_session()` / `_ensure_session_exists()` 末尾检查 hidden tombstone 再决定是否真正落地
- 为“删会话时存在 in-flight session fetch”的并发场景补回归测试

### F-041：本地删除会话不会失效当前侧边栏搜索结果，已删会话仍可在搜索面板里继续被点开

状态：已修复（2026-04-14）

修复说明：

- `GroupRepository.update_member_role()` 不再自动补建缺失成员；缺失时抛出错误，由 service 暴露为 drift/冲突语义。

现状：

- `SearchManager.search_all()` 会把当前搜索结果缓存到 `_last_catalog_results` / `_current_results`
- `SessionPanel` 在收到 `SessionEvent.DELETED` 时只会把会话从列表模型移除，不会清空或重算当前搜索结果
- 当前已打开的全局搜索面板会继续展示旧的 message/group 命中项；点击后会直接走 `ChatInterface._open_sidebar_search_result() -> open_session() -> ensure_session_loaded()`
- 对于“仅本地隐藏”的会话，这条路径会重新从后端拉会话并再次打开它

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2\client/managers/search_manager.py)
- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2\client/ui/widgets/session_panel.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2\client/ui/widgets/global_search_panel.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2\client/ui/controllers/chat_controller.py)

影响：

- 用户刚在当前设备删除/隐藏的会话，在同一时刻的搜索面板里仍然可见且可点击，产品语义不一致
- 这不只是显示陈旧数据，点击动作还会直接把本地刚隐藏的会话重新拉回 UI

建议：

- 会话删除/隐藏时同步失效当前搜索结果，或至少在激活搜索结果前校验该 `session_id` 是否仍处于隐藏 tombstone
- 为“搜索面板打开状态下删除会话再点结果”的交互场景补 UI 回归测试

### F-042：登出/切账号不会清本地 E2EE 状态，新账号会直接复用上一账号的本地 device bundle 和恢复材料

状态：已修复（2026-04-14）

修复说明：

- `GroupRepository.update_member_profile()` 不再自动创建 `GroupMember`；self-profile 更新要求成员 profile 已存在。

现状：

- `AuthController.clear_session()` 会在登出、token 失效、恢复会话失败以及新登录前执行，但它只调用 `_reset_local_chat_state()` 和 `_clear_persisted_auth_state()`
- `_reset_local_chat_state()` 当前只会执行 `db.clear_chat_state()` 和 `ConnectionManager.reset_sync_state()`；`clear_chat_state()` 只删除聊天缓存与 sync marker，不会删除任何 `e2ee.*` app_state
- `E2EEService.ensure_registered_device()` 在下一次登录时会先调用 `get_or_create_local_bundle()`，直接读取已有 `e2ee.device_state`
- 而 `_generate_local_bundle()` 生成的本地 bundle 本身不绑定 `user_id`；同时 `e2ee.group_session_state`、`e2ee.history_recovery_state`、`e2ee.identity_trust_state` 也都是独立持久化状态

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2\client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client/storage/database.py)
- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 同一台设备登出账号 A 再登录账号 B 时，客户端可能直接复用账号 A 的本地 E2EE device bundle，而不是为账号 B 重新建立本地身份
- 历史恢复 diagnostics、identity trust、群 sender-key 等本地安全状态也会跨账号残留，形成明显的账号边界污染
- 这已经不是“聊天缓存没清干净”的级别，而是本地安全身份和恢复材料的 ownership 被混淆

建议：

- 在 `clear_session()` / 切账号前显式调用 `E2EEService.clear_local_bundle()`，或者至少按当前账号建立独立命名空间的 E2EE 本地状态
- 为“账号 A 登出后账号 B 登录”的场景补安全回归测试，验证不会复用上一账号的本地 device id、history recovery 和 identity trust 状态

### F-043：登出/清空本地聊天状态不会清理已下载附件文件，上一账号的附件明文仍留在临时目录

状态：已修复（2026-04-14）

修复说明：

- `remove_member()` 先校验 `GroupMember` 与 `SessionMember` 均存在，删除过程中也检查两侧返回值，drift 会返回明确错误。

现状：

- `MessageManager.download_attachment()` 会把下载后的附件写到 `%TEMP%\\assistim_downloads`
- `AuthController.clear_session()` / logout 流程里的 `_reset_local_chat_state()` 最终调用 `Database.clear_chat_state()`
- `clear_chat_state()` 当前只删除数据库里的消息、会话、联系人、群缓存和少量 app_state，同步 marker 清掉后就结束，不会清理 `assistim_downloads` 目录里的本地文件

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2\client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client/storage/database.py)

影响：

- 用户登出或切换账号后，上一账号下载过的附件明文文件仍会留在本机临时目录
- 这不仅和“清空本地聊天状态”的语义不一致，也会把账号边界上的本地隐私残留扩大到磁盘文件层

建议：

- 在 logout / clear_chat_state 流程中一并清理 `assistim_downloads` 目录下的可归属缓存文件
- 为“下载附件后 logout / 切账号”的场景补本地文件清理回归测试

### F-044：`force_logout(session_replaced)` 不会像正常 logout 一样 teardown 运行态，旧账号聊天 UI 在关窗前仍然可见且可交互

状态：已修复（2026-04-12）

现状：

- 正常 logout 流程会走 `_perform_logout_flow() -> _teardown_authenticated_runtime()`，显式关闭 `ChatController / MessageManager / SessionManager / ConnectionManager` 并销毁主窗口
- 但服务端 `force_logout` 的 `session_replaced` 分支只调用 `AuthController.clear_session()` 和 `ConnectionManager.close()`，随后直接让现有主窗口弹一个 3 秒倒计时 warning
- `show_session_replaced_warning()` 本身不会禁用窗口、不会清空 `ChatInterface`，也不会 teardown 任何聊天 controller/manager
- 因此在窗口真正关闭前，旧账号的会话列表、消息视图和本地缓存内容仍保留在 UI 上

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2\client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2\client/ui/windows/main_window.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client/ui/windows/chat_interface.py)

影响：

- 这会让“账号已被顶下线”的安全边界和 UI 真实状态不一致：用户在倒计时关窗前仍能看到上一账号的本地聊天内容，且部分本地交互仍可触发
- 正常 logout 和 forced logout 的运行态清理模型明显分叉，也会增加后续排障复杂度

建议：

- 让 forced logout 复用正常 logout 的 teardown 路径，至少先禁用/清空主窗口聊天 UI，再进入退出或重新认证流程
- 为“收到 session_replaced 后窗口仍存在数秒”的场景补 UI/安全回归测试

### F-045：`DiscoveryController` 的进程级缓存不会随 logout/切账号清空，下一账号可能继承上一账号的 moments 本地态

状态：已修复（2026-04-14）

修复说明：

- `leave_group()` 与移除成员共用双表一致性检查；缺失任一侧成员关系时不再静默成功。

现状：

- `DiscoveryController` 是全局单例，内部维护 `_user_cache`、`_comment_cache`、`_like_state_cache`、`_like_count_cache`
- logout teardown 当前不会关闭或重建 `DiscoveryController`
- `load_moments()` / `_normalize_moment()` 会优先用 `_like_state_cache`、`_like_count_cache` 和 `_comment_cache` 覆盖或扩展服务端返回结果
- 因此同一进程里如果账号 A 登出、账号 B 登录，而 feed 中碰巧出现相同 `moment_id`，账号 B 会直接继承账号 A 在本地缓存里的点赞状态、点赞数或补发评论

证据：

- [D:\AssistIM_V2\client\ui\controllers\discovery_controller.py](D:\AssistIM_V2\client/ui/controllers/discovery_controller.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)
- [D:\AssistIM_V2\client\ui\windows\discovery_interface.py](D:\AssistIM_V2\client/ui/windows/discovery_interface.py)

影响：

- 这会把上一账号的 discovery 本地交互状态带进下一账号，造成明显的账号边界污染
- 问题不止是缓存脏数据，`is_liked` 这类当前用户相关字段会被直接本地覆盖，表现上更像真实业务错误

建议：

- 把 `DiscoveryController` 纳入 logout teardown，或至少在切账号时清空这些 per-user/per-moment 本地缓存
- 为“账号 A 点赞/评论后切换到账号 B”的场景补 discovery 回归测试

### F-046：`SessionManager.close()` 不会重置 `_current_session_active`，下一账号第一次选中会话时可能被误判为前台激活并直接清未读

状态：已修复（2026-04-12）

现状：

- `SessionManager.close()` 会清 `_sessions` 和 `_current_session_id`，但不会把 `_current_session_active` 置回 `False`
- logout teardown 会显式调用 `SessionManager.close()`，而单例实例会在下一次登录后复用
- 下一账号重新初始化后，如果用户第一次选中某个会话，`select_session()` 会看到 `old_id != session_id` 且 `_current_session_active` 仍为 `True`，于是直接执行 `clear_unread(session_id)`
- 这和本地删除会话场景里的 `F-032/F-036` 属于同一类状态残留，只是触发条件换成了 logout/切账号

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)

影响：

- 如果用户在账号 A 退出前正停留在聊天页，账号 B 登录后的第一次会话选择可能会把本不该清的未读直接清零
- 这会把上一账号的前台 UI 状态泄漏到下一账号的会话语义里

建议：

- 在 `SessionManager.close()` 中显式重置 `_current_session_active = False`，并同步审视其它会话选择态字段是否也应在 close 时清零
- 为“聊天页前台状态下 logout，再登录新账号后首次选中会话”的场景补回归测试

### F-047：forced logout 会先清本地聊天状态，但不停止仍在运行的 session/message 后台任务，已清空的本地状态可能被异步重新写回

状态：已修复（2026-04-12）

现状：

- `session_replaced` 分支当前只调用 `AuthController.clear_session()` 和 `ConnectionManager.close()`，不会像正常 logout 一样执行 `_teardown_authenticated_runtime()`
- `clear_session()` 会提前调用 `Database.clear_chat_state()` 清空本地聊天数据库
- 但此时 `MessageManager`、`SessionManager` 仍然存活，已有的后台任务不会被取消；例如：
  - `MessageManager` 的附件预取任务完成后仍会 `save_message()`
  - `SessionManager` 的 `_session_fetch_tasks` 完成后仍可能 `add_session()`
- 正常 logout 之后还会再走一次 teardown + `db.clear_chat_state()` 兜底，而 forced logout 没有这层收口

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2\client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)

影响：

- 被挤下线后，即使本地聊天数据库刚被清空，仍在运行的后台任务也可能把旧账号的消息、会话或附件状态重新写回本地
- 这会让 forced logout 的本地清理语义比正常 logout 更弱，进一步放大账号边界和隐私残留问题

建议：

- 让 forced logout 先走和正常 logout 一致的 runtime teardown，再清本地状态或在 teardown 后追加一次兜底清理
- 为“收到 session_replaced 时存在 media prefetch / session fetch / pending send”这类并发路径补回归测试

### F-048：logout/切账号不会取消 HTTP token refresh task，晚到的 refresh 结果可能把旧账号 token 重新写回内存

状态：已修复（2026-04-12）

现状：

- `HTTPClient` 用 `_refresh_task` 做 token refresh single-flight，`_perform_token_refresh()` 在开始时捕获当前 `refresh_token`
- `AuthController.clear_session()` 只会调用 `_clear_http_tokens()`，不会取消 `HTTPClient._refresh_task`
- 如果 logout/forced logout/切账号时刚好有一个 refresh 请求已经在路上，成功返回后 `_perform_token_refresh()` 仍会执行 `self.set_tokens(...)`
- 由于 `AuthController` 在 app 生命周期内持续挂着 token listener，这个晚到结果会把旧账号 token 重新写回 HTTP client 的运行态；而这件事发生在本地 auth/chat 状态已经被清掉之后

证据：

- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2\client/network/http_client.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2\client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)

影响：

- 被清掉的运行态 token 可能被旧账号 refresh 结果“复活”，导致 logout 语义在内存层失效
- `clear_session()` 当前还是先 `_clear_http_tokens()`、后 `_current_user = None`；如果 refresh 恰好在这两步之间返回，`AuthController` 的 token listener 甚至可能把旧账号 token 和用户资料重新持久化回 `app_state`
- 如果用户紧接着登录另一个账号，旧 refresh 结果还可能和新登录写入的 token 发生竞态，造成跨账号鉴权状态污染

建议：

- 在 logout/clear_session 过程中显式取消或失效当前 `_refresh_task`，并让 refresh 结果在提交前校验当前 auth generation
- 为“401 触发 refresh 时同时 logout / relogin”的场景补鉴权竞态回归测试

### F-049：`clear_session()` 会触发 `SessionManager` 的 identity refresh，而该后台任务可能在清库后把旧 session 重新写回数据库

状态：已修复（2026-04-12）

现状：

- `AuthController.clear_session()` 会调用 `chat_controller.set_user_id("")`
- 这会进一步触发 `SessionManager.set_user_id("")`，而 `set_user_id()` 会调用 `_schedule_identity_refresh()`
- `_refresh_cached_preview_state_for_identity()` 会基于当前内存中的 `self._sessions` 遍历旧会话，并在 preview 有变化时执行 `db.save_session(session)`
- 但 `clear_session()` 随后又会执行 `_reset_local_chat_state() -> db.clear_chat_state()`；如果 identity refresh 任务在清库后继续跑完，就可能把旧账号的 session 行重新写回本地数据库
- 正常 logout 后续还有一次 teardown + `db.clear_chat_state()` 兜底，forced logout 则没有

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2\client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2\client/ui/controllers/chat_controller.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)

影响：

- 这说明即使不考虑 message prefetch / session fetch，`clear_session()` 自己也会启动一个可能回写旧 session 的后台任务
- 在 forced logout 场景下，这条链路足以让刚清空的本地会话列表再次被旧账号数据污染

建议：

- 在 `clear_session()` 期间禁止 `SessionManager.set_user_id("")` 触发 identity refresh，或先 teardown `SessionManager` 再清本地状态
- 为“logout/forced logout 期间 identity refresh 仍在运行”的场景补数据库回归测试

### F-050：正常 logout 期间，WS 入站消息仍可能在 `clear_chat_state()` 之后继续落库，而且会按 `user_id=""` 被错误归类

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的正常 logout 流程是先 `await auth_controller.logout()`，后 `await _teardown_authenticated_runtime()`
- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `logout()` 会先执行 `clear_session()`，其中 `_reset_local_chat_state()` 会提前清空本地消息库
- 但在 `_teardown_authenticated_runtime()` 之前，[ConnectionManager](D:\AssistIM_V2\client\managers\connection_manager.py) 仍保持连接，[MessageManager](D:\AssistIM_V2\client\managers\message_manager.py) 也仍在监听 WS 入站
- 此时 `clear_session()` 又已经把 `MessageManager._user_id` 置成了空字符串；而 `_process_incoming_message()` / `_normalize_loaded_message()` 仍会继续根据当前 `_user_id` 计算 `is_self/status/read metadata` 并 `save_message()`

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2\client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

影响：

- 这会让“logout 已经清空本地聊天状态”的语义失效：在断开旧账号 WS 之前，晚到的旧账号实时消息仍可能重新写回本地数据库
- 而且这些消息会在 `user_id=""` 的上下文里被归类，`is_self`、默认 `status`、`is_read_by_me` 等派生字段都可能和真实账号身份不一致
- 它不是 forced logout 专属边界，而是正常 logout 的正式流程里就存在的竞争窗口

建议：

- 正常 logout 应优先 quiesce/close `ConnectionManager` 和 `MessageManager`，至少先阻断旧账号 WS 入站，再清本地聊天状态
- 若暂时不调整顺序，也应在 `MessageManager` 增加“closing/cleared session”短路，避免 logout 期间继续接受并落库旧账号消息

### F-051：正常 logout 期间，ACK 和历史补偿响应同样可能在清库后回写本地数据库

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 logout 顺序仍然是先 `clear_session()`，后关闭 `ConnectionManager` / `MessageManager`
- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `_process_ack()` 会从 `_pending_messages` 取出仍在飞行中的旧消息，然后直接 `save_message()`
- 同文件的 `_process_history_messages()` 会把晚到的 `history_messages` 批量 `save_messages_batch()`
- `_process_history_events()` 又会继续把离线 mutation event 递归回放到 `_handle_ws_message()`，使 edit/recall/delete/delivered 等处理器在 logout 窗口里继续改写本地消息

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

影响：

- `F-050` 不是只影响实时 `chat_message`；旧账号的 ACK、历史补偿和离线 mutation 响应都可能在本地清库后继续把消息状态重新写回来
- 这会让 logout 后的本地库出现“被清空后又被旧账号 ACK/补偿恢复”的状态抖动，排障时会非常难定位
- 对已发消息来说，用户甚至可能在 logout 后看到旧账号消息又被标成 `sent/failed/recalled/edited`

建议：

- 在清本地聊天状态之前，先停止 `MessageManager` 对 WS 的消费，并让 in-flight ACK / history sync 在 closing 状态下直接丢弃
- 为“logout 时 ACK 晚到”“logout 时 history_messages/history_events 晚到”的场景补回归测试

### F-052：logout 时先 `reset_sync_state()` 也不稳，旧连接晚到的 WS 包仍可把 session/event cursor 重新写回 `app_state`

状态：已修复（2026-04-12）

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `clear_session()` 会调用 `ConnectionManager.reset_sync_state()`，先清空内存和 `app_state` 里的 sync cursor
- 但在 [main.py](/D:/AssistIM_V2/client/main.py) 后续真正关闭 `ConnectionManager` 之前，旧 WebSocket 连接还活着
- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 `_on_message()` 会对 `history_messages`、`history_events`、`chat_message`、`message_ack`、`message_edit`、`message_recall`、`message_delete`、`read`、`group_profile_update`、`group_self_profile_update` 等包继续推进 `_session_sync_cursors/_event_sync_cursors`
- 只要 cursor 前进了，`_on_message()` 就会立刻调 `_save_sync_state()`，把这些旧账号的 cursor 再次写回 `app_state`

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2\client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2\client/managers/connection_manager.py)

影响：

- 这说明 logout 的“清 sync cursor”并不是稳定动作；只要旧连接还没停，晚到的包就能把 cursor 复活
- 下一次 runtime 初始化或重新登录时，这些 stale cursor 可能再次被 `ConnectionManager` 读取并作为 sync 起点使用，导致本应从空状态/低水位重新补偿的历史被直接跳过
- 它和 `F-050/F-051` 组合起来，会同时污染“本地消息内容”和“后续补偿起点”

建议：

- 先停止旧连接收包，再执行 `reset_sync_state()`；或者给 `ConnectionManager` 增加 closing generation，让 logout 之后到达的旧包不再允许推进和持久化 cursor
- 为“logout 时 history/chat/ack 晚到导致 sync cursor 复活”的场景补 reconnect/sync 回归测试

### F-053：`_forced_logout_in_progress` 没有复位路径，同一进程里第二次 `session_replaced` 会被直接吞掉

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 在 `Application.__init__()` 里把 `_forced_logout_in_progress` 初始化为 `False`
- 收到 `force_logout(reason=session_replaced)` 时，`_handle_transport_message()` 先检查该标志，随后立即把它置为 `True`
- 但当前代码里没有任何地方会在 forced logout 完成、重新登录成功、或 runtime 重建后把这个标志恢复为 `False`

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)

影响：

- 同一进程生命周期内，只要发生过一次 `session_replaced`，后续再次收到同类强制下线消息就会在入口处被 `return`
- 这会让“首次强制下线后重新登录，再被别处顶下线”的正式场景失效，用户端不再响应第二次 session replacement
- 这是典型的状态机未闭合问题，不依赖竞态，复现条件也明确

建议：

- 在 forced logout 流程真正完成后，或在下一次认证/主运行态重建时，显式复位 `_forced_logout_in_progress`
- 为“同一进程内连续两次 `session_replaced`”补回归测试

### F-054：logout 期间如果旧 WS 认证握手仍在飞，晚到的 `auth_ack` 还能再次触发旧账号 `sync_messages`

状态：已修复（2026-04-12）

现状：

- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 在收到 `auth_ack` 后，只要 `success=true`，就会把 `_ws_authenticated` 置真并立即调 `_send_sync_request()`
- 这个处理不校验当前 logout/clear-session 状态，也不校验这次 `auth_ack` 是否仍属于当前有效 auth generation
- 而正常 logout 流程里，[main.py](/D:/AssistIM_V2/client/main.py) 是先 `auth_controller.logout() / clear_session()`，后关闭 `ConnectionManager`
- 因此如果用户在旧连接刚发出 WS `auth`、但 `auth_ack` 尚未返回时触发 logout，晚到的旧 `auth_ack` 仍可能在 teardown 前触发一次新的 `sync_messages`

证据：

- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2\client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)

影响：

- 这会把 `F-052` 再往前推一步：不仅旧的 history/chat/ack 包会在 logout 后继续推进 cursor，连一次新的旧账号 sync 请求都可能被重新发起
- 如果此时 cursor 已经被 `reset_sync_state()` 清空，旧连接甚至可能按“从头同步”的方式把旧账号历史重新补回来
- 这属于明确的连接状态机漏洞，而不是单纯的后台任务收尾不及时

建议：

- logout 进入后应立即使 `ConnectionManager` 进入禁止握手完成/禁止发送 sync 的 closing 状态
- 至少让 `auth_ack -> _send_sync_request()` 这条链路带上 auth generation 或 teardown guard，避免旧连接在退出流程中重新启动补偿

修复记录：

- [main.py](/D:/AssistIM_V2/client/main.py) 的普通 logout / auth-loss 路径已改为先 quiesce authenticated runtime，关闭 `ConnectionManager` / `WebSocketClient` 后再清 auth/chat state。
- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 已用 `_callback_generation` 和 `_closing` guard 包住 websocket callback；close 后旧 generation 的 `auth_ack` 不会再进入 `_on_message()`，也不会触发 `_send_sync_request()`。
- 回归测试覆盖 close 后旧 generation `auth_ack(success=true)` 不会发送 `sync_messages`。

### F-055：晚到的 mutation event 会先推进 `event_seq`，再因本地消息已清空而被客户端跳过，导致下次重连也不会再补回来

状态：已修复（2026-04-12）

现状：

- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 `_on_message()` 对 `message_edit`、`message_recall`、`message_delete`、`read`、`group_profile_update`、`group_self_profile_update` 会先推进 event cursor，并在有变化时立即 `_save_sync_state()`
- 然后它才调用 `_notify_message()` 把包交给下游处理
- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 对 `message_edit` / `message_recall` 需要先 `get_message(message_id)`；若 logout 已执行 `clear_chat_state()`，这里会直接记录 warning 然后 `return`
- 结果就是：event cursor 已经被推进并持久化，但真正的 mutation 并没有应用到任何本地消息

证据：

- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2\client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

影响：

- 这比 `F-051/F-052` 更严重：晚到的旧账号 mutation event 不只是“这次没处理好”，而是会因为 cursor 已前进而在后续 reconnect/sync 中被永久视为“已经消费”
- 对 edit/recall 这类依赖原消息存在的事件，logout 清库窗口会形成不可恢复的丢事件效果
- 同类模式也解释了之前 `R-007` 的根因：当前事件补偿模型默认客户端本地仍持有可应用 mutation 的原消息

建议：

- mutation/event 类消息不应在“客户端成功应用”之前就推进并持久化 event cursor，至少在 logout/clearing 状态下要禁止这类推进
- 为“logout 时晚到 `message_edit/message_recall`，随后重新登录并补偿”的场景补回归测试，确认不会因 cursor 先行前进而永久漏补

修复记录：

- logout/auth-loss 进入后先关闭连接层 callback generation；旧 generation 的 `message_edit/message_recall/message_delete/read` 不再能进入 `ConnectionManager._on_message()`。
- close 后旧 generation mutation event 不会推进 `_event_sync_cursors`，也不会持久化 `last_sync_event_cursors`。
- 回归测试覆盖 close 后旧 generation `message_edit` 不会通知下游、不会推进或保存 event cursor。

### F-056：晚到的群资料事件也会先推进 `event_seq`，再因本地 session 已清空而被跳过，导致后续不会重放

状态：已修复（2026-04-12）

现状：

- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 会对 `group_profile_update` 和 `group_self_profile_update` 先推进并持久化 event cursor
- 然后消息才会经由 [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 发成 `MessageEvent.GROUP_UPDATED / GROUP_SELF_UPDATED`
- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_on_group_updated()` / `_on_group_self_updated()` 最终都会走 `apply_group_payload()`
- 但 `apply_group_payload()` 明确要求本地 `self._sessions` 里还存在该 `session_id`，否则直接 `return None`
- logout 清库或本地会话状态已被清空时，这类群资料事件就会在“cursor 已前进”的情况下被静默跳过

证据：

- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2\client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)

影响：

- 群名称、群头像、群公告、群备注、我的群昵称等资料更新，在 logout 清库窗口里可能被永久视为“已经消费过”
- 重新登录后即使恢复了该群会话，本地仍可能停留在旧资料状态，直到未来有新的同类事件或主动刷新覆盖
- 这说明 `F-055` 不是 message mutation 的孤例，而是 event 补偿模型对“本地对象必须先存在”的普遍假设

建议：

- 群资料事件不应在本地 session 不存在时直接丢弃，至少应延迟到会话恢复后再应用，或在应用失败时不要推进 event cursor
- 为“logout 时晚到 `group_profile_update/group_self_profile_update`，重登后群资料仍应最终一致”的场景补回归测试

修复记录：

- logout/auth-loss 进入后先关闭连接层 callback generation；旧 generation 的 `group_profile_update/group_self_profile_update` 不再能进入 `ConnectionManager._on_message()`。
- close 后旧 generation group profile event 不会推进 `_event_sync_cursors`，也不会持久化 `last_sync_event_cursors`。
- 回归测试覆盖 close 后旧 generation `group_profile_update` 不会通知下游、不会推进或保存 event cursor。

### F-057：logout 清空本地通讯录缓存之后，`ContactInterface` 的在途加载任务仍可能把旧账号 `contacts/groups` 重新写回数据库

状态：已修复（2026-04-14）

修复说明：

- `_ensure_group_member()` 现在同时要求 `SessionMember` 和 `GroupMember` 存在；角色更新不再借 repo 自动补建缺失行。

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `clear_session()` 会调用 `db.clear_chat_state()`，其中明确删除 `contacts_cache` 和 `groups_cache`
- 但正常 logout 流程里，[main.py](/D:/AssistIM_V2/client/main.py) 是先执行 `auth_controller.logout()/clear_session()`，后面才在 `_teardown_authenticated_runtime()` 中销毁主窗口
- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的异步 `_load_task` / `_keyed_ui_tasks` 只会在 `destroyed` 时取消
- 同时 [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `load_contacts()` / `load_groups()` 在请求完成后会调用 `_persist_contacts_cache()` / `_persist_groups_cache()`，把结果重新写入数据库

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2\client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2\client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2\client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client/storage/database.py)

影响：

- 这会让“logout 已清空本地联系人/群组缓存”的语义失效：晚到完成的旧账号通讯录加载任务仍可能把 `contacts_cache/groups_cache` 重新种回库
- 它也会进一步污染后续本地搜索，因为 `SearchManager` 的联系人/群组搜索正是基于这两张缓存表
- 这说明 logout 时序问题并不只影响聊天域，通讯录域同样存在“先清库、后停 UI/后台任务”的结构性漏洞

建议：

- logout 进入后，应先取消 `ContactInterface` 相关在途加载任务，或让 `ContactController` 在 cleared/closing 状态下拒绝持久化旧结果
- 为“logout 时通讯录/群组列表请求晚到完成”的场景补缓存回归测试

### F-058：logout 期间在途的资料保存任务仍可能把旧账号 `user_profile` 和会话快照重新写回本地

状态：已修复（2026-04-14）

修复说明：

- 群主转让路径同样经过双表成员校验，并且 repo 不再自动补建缺失 `GroupMember`。

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的正常 logout 仍是先 `await auth_controller.logout()`，后面才进入 `_teardown_authenticated_runtime()` 销毁主窗口
- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 里的 `UserProfileCoordinator` 挂在主窗口上；它的 `_save_task` 只会在 `closeEvent()` 里取消
- 这意味着 profile 保存请求如果在 logout 前已经发出，在 `clear_session()` 之后、主窗口真正销毁之前，这个任务仍可继续运行
- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `update_profile()` 在请求返回后会重新 `_apply_runtime_context(user)`、`_persist_user_profile(user)`，并继续 `refresh_sessions_snapshot()`
- [user_profile_flyout.py](/D:/AssistIM_V2/client/ui/widgets/user_profile_flyout.py) 的 `_save_profile_async()` 成功后还会继续 `profileChanged.emit(...)`，把这份旧账号资料再广播回 UI

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2\client/ui/windows/main_window.py)
- [D:\AssistIM_V2\client\ui\widgets\user_profile_flyout.py](D:\AssistIM_V2\client/ui/widgets/user_profile_flyout.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2\client/ui/controllers/auth_controller.py)

影响：

- logout 刚清掉的 `auth.user_profile/auth.user_id` 可能被晚到完成的旧账号资料保存重新写回，导致本地“已退出”语义失效
- `update_profile()` 还会顺手触发 `refresh_sessions_snapshot()`，所以它不只会污染 auth profile，还可能把旧账号会话快照重新拉回 runtime
- 这说明 logout 的竞争窗口已经覆盖到“资料变更”这类非聊天链路，根因仍是“先 clear，再 teardown”

建议：

- logout 进入后，应先取消 `UserProfileCoordinator` 的在途保存任务，或给 `AuthController.update_profile()` 增加 auth-generation / shutting-down 防护，拒绝在 cleared runtime 上继续回写
- 为“资料保存进行中点击 logout”的场景补回归测试，至少覆盖 `user_profile` 持久化和 `refresh_sessions_snapshot()` 不得在旧 runtime 上继续执行

### F-059：logout 期间在途的会话安全动作仍可能继续改写 `SessionManager` 和本地会话库

状态：部分修复（2026-04-14）

修复说明：

- fanout 失败不会再把已提交 mutation 打成 HTTP 500，且所有群 lifecycle 已进入 history event；仍未引入持久 outbox/retry，因此保留为部分修复。

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 会把“确认安全前置动作并释放待发消息”等操作放进自己的 `_ui_tasks`
- 这些任务只会在 `ChatInterface.destroyed` 时统一取消；正常 logout 仍是 [main.py](/D:/AssistIM_V2/client/main.py) 先 `clear_session()`，后 `_teardown_authenticated_runtime()` 销毁主窗口
- 也就是说，如果安全动作在 logout 前已经发出，`clear_session()` 之后它仍可能继续跑完
- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `execute_session_security_action()` 会继续进入 `trust_session_identities()` / `recover_session_crypto()`
- 这两条分支都会在完成后 `db.replace_sessions(...)` 并发出 `SessionEvent.UPDATED`；恢复链路还会继续刷新本地 message recovery 状态

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)

影响：

- logout 刚清掉的本地会话快照，可能被晚到完成的旧账号安全动作再次写回
- 由于这些动作直接改 `SessionManager` 的 authoritative session state，它会和前面消息、游标、profile 那几条一起，形成更完整的“旧 runtime 在 logout 后继续复活状态”问题
- 如果后续立即 relogin，新账号初始化阶段还可能接到这些旧账号的 `SessionEvent.UPDATED`

建议：

- logout 进入后，应优先取消 `ChatInterface` 的在途安全动作任务，或在 `SessionManager.execute_session_security_action()` / `_refresh_cached_session_crypto_state()` 增加 runtime generation 校验
- 为“安全动作执行中点击 logout”的场景补回归测试，重点验证本地 `sessions` 表和 `SessionEvent.UPDATED` 不会被旧账号晚到结果污染

### F-060：logout 清空 `chat.hidden_sessions` 之后，晚到的本地删除会话任务仍可能把隐藏 tombstone 重新写回 `app_state`

状态：部分修复（2026-04-14）

修复说明：

- self-profile fanout 失败不会覆盖已提交 mutation；可靠 outbox/retry 仍未引入，因此保留为部分修复。

现状：

- [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `clear_chat_state()` 会删除 `app_state["chat.hidden_sessions"]`
- 但正常 logout 流程里，[main.py](/D:/AssistIM_V2/client/main.py) 仍是先 `clear_session()`，后面才销毁主窗口
- [session_panel.py](/D:/AssistIM_V2/client/ui/widgets/session_panel.py) 的会话菜单操作任务只会在 `destroyed` 时取消；如果用户在 logout 前刚触发“删除会话”，对应的 `remove_session()` 仍可能在 clear 之后继续完成
- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `remove_session()` 即使此时本地 `self._sessions` 里已经拿不到该会话，也会走 `_hide_session(session_id, hidden_at=time.time())`
- `_hide_session()` 会重新 `set_app_state("chat.hidden_sessions", ...)`，把刚被清掉的隐藏 tombstone 再写回数据库

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client/storage/database.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)
- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2\client/ui/widgets/session_panel.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)

影响：

- logout 后本应被清空的本地隐藏会话 tombstone 可能被旧账号晚到任务重新种回 `app_state`
- 由于 `chat.hidden_sessions` 是进程/数据库级 app state，而不是 per-account 隔离状态，这会把旧账号的本地隐藏语义带进下一次登录
- 下个账号初始化 `SessionManager` 时会重新加载这份 tombstone，导致远端会话被错误地继续隐藏

建议：

- logout 进入后，应先取消 `SessionPanel` 的在途会话菜单任务，或让 `SessionManager.remove_session()` 在 cleared runtime 上拒绝继续写 `_hidden_sessions`
- 同时考虑把 `chat.hidden_sessions` 收口为 per-account 状态，避免单个晚到任务直接跨账号污染下一次登录

### F-061：logout 不会关闭进程级 HTTP client，旧账号的 in-flight token refresh 仍可能在退出后改写内存 token

状态：已修复（2026-04-12）

现状：

- [http_client.py](/D:/AssistIM_V2/client/network/http_client.py) 的 `_refresh_access_token()` 会启动单例 `_refresh_task`
- 这个 task 完成后会直接 `self.set_tokens(...)`；失败时则会 `self.clear_tokens()`
- 但正常 logout 的 `_teardown_authenticated_runtime()` 并不会关闭 [HTTPClient](/D:/AssistIM_V2/client/network/http_client.py)；[main.py](/D:/AssistIM_V2/client/main.py) 只有应用整体退出时才会 `await http.close()`
- 同时客户端所有 service 都复用同一个 `get_http_client()` 单例，下一次重新登录前不会重建

证据：

- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2\client/network/http_client.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\services\auth_service.py](D:\AssistIM_V2/client/services/auth_service.py)

影响：

- 如果旧账号在 logout 前刚好触发了一次 401 refresh，晚到完成的 `_refresh_task` 仍可能在 `clear_session()` 之后把旧账号 token 重新塞回进程级 HTTP client
- 更糟的是，这个 refresh task 没有 auth-generation 校验；如果用户已经重新登录新账号，旧 task 仍可能在稍后 `set_tokens(...)` 或 `clear_tokens()`，直接覆盖或清空新账号 token
- 这说明 logout/relogin 竞争窗口不只影响本地数据库和 UI 状态，连最底层的进程级认证状态也没有真正隔离

建议：

- logout 时应显式取消并关闭 HTTP client 的 `_refresh_task`，或至少给 token refresh 引入 auth-generation 校验，禁止旧账号 refresh 修改当前进程 token
- 更稳的方案是在每次 logout/relogin 时重建 per-account HTTP runtime，而不是复用进程级单例

### F-062：`clear_session()` 自己会触发一次 `SessionManager` 的 identity-refresh 任务，并可能在清库后把会话预览重新写回数据库

状态：已修复（2026-04-12）

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `clear_session()` 会先调用 `self._chat_controller.set_user_id("")`
- [chat_controller.py](/D:/AssistIM_V2/client/ui/controllers/chat_controller.py) 的 `set_user_id("")` 又会继续调用 `SessionManager.set_user_id("")`
- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `set_user_id()` 在用户 id 变化时会立即 `_schedule_identity_refresh()`
- 但这时 `clear_session()` 还没有 teardown `SessionManager`，而 `_reset_local_chat_state()` 已经把本地 `sessions/messages` 清掉
- 晚到执行的 `_refresh_cached_preview_state_for_identity()` 会遍历仍在内存里的 `self._sessions`，重新计算 preview，并对变更项 `db.save_session(session)`

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- logout 刚清掉的本地 `sessions` 表，可能因为这条由 `clear_session()` 自己触发的后台任务被重新写回一批旧账号会话行
- 这不是“用户刚好点了某个按钮”的旁路竞态，而是正常 logout 正式流程里自带的一条自触发回写链路
- 它还会发出 `SessionEvent.UPDATED`，进一步把旧账号会话状态重新广播给仍未完全销毁的 UI

建议：

- `clear_session()` 不应通过 `set_user_id("")` 触发 identity refresh；至少需要先把 `SessionManager` 标记为 shutting down，再禁止 `_schedule_identity_refresh()`
- 为“正常 logout 不做任何额外操作”补回归测试，验证 `clear_chat_state()` 之后不会被 identity-refresh 再次写回 session 记录

### F-063：旧账号的晚到 token refresh 如果发生在新账号已登录之后，可能把“旧 token + 新 user_profile”错误持久化到 auth 状态

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 logout/relogin 流程会复用同一个 `AuthController` 和同一个进程级 `HTTPClient`
- 前一条 `F-061` 已经确认：旧账号的 in-flight `_refresh_task` 不会在 logout 时被立即关闭
- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `_on_tokens_changed()` 在 `access_token && refresh_token && self._current_user` 时，会直接调 `_persist_auth_state(access_token, refresh_token, self._current_user)`
- 因此，一旦旧账号 refresh 晚到完成，而此时 `self._current_user` 已经是新账号，后台 token listener 就会把“旧账号 token + 新账号 user profile”一起写入本地持久化 auth 状态

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)

影响：

- 本地持久化的 `auth.access_token/auth.refresh_token/auth.user_profile` 可能出现跨账号错配，下一次应用冷启动恢复 session 时会进入不可预测状态
- 这比单纯“内存里短暂带着旧 token”更严重，因为错误状态会落盘，并持续影响后续 restore
- 它说明当前 auth 持久化模型默认假设“token 变化一定属于当前 `_current_user`”，但 logout/relogin 并没有建立任何 generation 隔离

建议：

- 给 token listener 和 `_persist_auth_state()` 增加 auth-generation 校验，确保只有当前登录代的 token 变化才能落盘
- 同时在 logout 时取消/关闭旧 HTTP refresh task，避免它跨越 relogin 边界再触发 `_on_tokens_changed()`

### F-064：logout 期间在途的 Moments 任务仍可能继续修改全局 `DiscoveryController` 缓存，并跨账号污染下一次登录

状态：已修复（2026-04-14）

修复说明：

- 群公告更新现在先广播 `group_profile_update` 再广播公告消息，确保公告 metadata 先进入 session/group 状态。

现状：

- [discovery_interface.py](/D:/AssistIM_V2/client/ui/windows/discovery_interface.py) 自己维护 `_load_task/_publish_task/_keyed_ui_tasks/_ui_tasks`，这些任务只会在 `destroyed` 时取消
- 但正常 logout 仍是 [main.py](/D:/AssistIM_V2/client/main.py) 先 `clear_session()`，后面才销毁主窗口
- 同时 [DiscoveryController](/D:/AssistIM_V2/client/ui/controllers/discovery_controller.py) 是进程级单例，logout teardown 并不会关闭或重建它
- 旧任务一旦在 clear 之后完成，`load_moments()` 仍会继续填充 `_user_cache`，`set_liked()` 会改 `_like_state_cache/_like_count_cache`，`add_comment()` 会改 `_comment_cache`

证据：

- [D:\AssistIM_V2\client\ui\windows\discovery_interface.py](D:\AssistIM_V2/client/ui/windows/discovery_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\discovery_controller.py](D:\AssistIM_V2/client/ui/controllers/discovery_controller.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 旧账号晚到完成的 Moments 请求仍可能把作者信息、点赞态、评论缓存重新写进全局 `DiscoveryController`
- 由于这份 controller 会跨 relogin 继续复用，下一账号打开发现页时可能直接继承上一账号的本地 like/comment/user cache
- 这说明 `F-045` 不是只有“缓存没清”这么静态，而是 logout 时仍有活跃任务继续往这份缓存里写

建议：

- logout 进入后，应先取消 `DiscoveryInterface` 的在途任务，或给 `DiscoveryController` 增加 clear/close 并在 teardown 中显式调用
- 如果继续保留进程级单例，至少需要给 discovery 请求结果加 auth-generation 校验，避免旧账号晚到结果落到当前缓存

### F-065：正常 logout teardown 从不关闭 `AuthController`，导致 token listener 和后台 auth 持久化逻辑跨 relogin 持续存活

状态：已修复（2026-04-12）

修复记录：

- logout/auth-loss 在 auth state 清理完成后会调用 `_close_auth_controller_after_auth_clear()`，关闭旧 `AuthController`，取消后台 auth persistence/E2EE bootstrap task，并移除 token listener。
- `AuthController.close()` 会在关闭当前全局单例时把 `_auth_controller` 置回 `None`，下一次认证会创建新的 auth controller，不再复用 closed controller。
- 回归测试覆盖 logout/auth-loss 关闭 auth controller，以及 `AuthController.close()` 清理全局 singleton。

原现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 明确提供了 `close()`：它会把 `_closed = True`、移除 token listener，并取消 `_token_state_task`
- 但正常 logout 的 `_teardown_authenticated_runtime()` 并没有调用 `peek_auth_controller()`；只有应用整体退出时，[main.py](/D:/AssistIM_V2/client/main.py) 的 `shutdown()` 才会真正 `await peek_auth_controller().close()`
- 因此，在 logout/relogin 之间，同一个 `AuthController` 单例会一直保持活跃，`_closed` 仍是 `False`，token listener 仍然挂在进程级 `HTTPClient` 上

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 前面 `F-061/F-063` 那些“旧 refresh 改写 token / 错配持久化 auth 状态”的问题，不是单个遗漏分支，而是因为 logout 根本没有把 auth controller 从运行时里拆下来
- 这也意味着后续任何来自 `HTTPClient` 的 token 变动，只要发生在同一进程生命周期内，都会继续经过旧的 `AuthController._on_tokens_changed()` 逻辑
- 当前 logout 和 app shutdown 的 teardown 覆盖面明显不一致：真正会清 listener 的路径只有整体退出，没有普通切账号

建议：

- 在 `_teardown_authenticated_runtime()` 中显式关闭 `AuthController`，并在下一次登录前按新的 authenticated runtime 重新初始化它
- 如果继续复用单例，也至少要在 logout 时把 `_closed`/listener/token task 状态收口，避免 auth 层后台逻辑跨账号持续存活

### F-066：主窗口展示后启动的 `_warm_authenticated_runtime()` 在普通 logout 不会被取消，可能在 teardown 后重新拉起旧 runtime

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 在 `show_main_window()` 末尾通过 `self.create_task(self._warm_authenticated_runtime())` 启动后台 warmup
- 这条任务会继续执行 `_synchronize_authenticated_runtime()` 和 `start_background_services()`，也就是 `reload_sync_timestamp()`、`refresh_remote_sessions()`、`connect()`
- 但普通 logout 的 `_perform_logout_flow()` / `_teardown_authenticated_runtime()` 并不会取消 `Application._tasks`
- `Application._tasks` 只会在应用整体 `shutdown()` 时统一 cancel

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 如果用户在主窗口刚打开后很快就 logout，这条 warmup task 仍可能在 `clear_session()` 或 teardown 之后继续完成
- 它会把旧账号的远端会话刷新和 WebSocket 连接重新拉起来，直接和当前 logout/relogin 流程打架
- 这不是某个 manager 内部的旁路任务，而是 `Application` 顶层自己创建的后台任务，所以影响范围更大，也更难靠局部修补兜住

建议：

- 把 `Application._tasks` 中属于 authenticated runtime 的任务纳入普通 logout teardown，一进入 logout 就先 cancel
- 至少要给 `_warm_authenticated_runtime()` 和 `start_background_services()` 增加 generation / shutdown guard，禁止旧登录代的 warmup 在 teardown 之后继续执行

### F-067：主窗口的“联系人/搜索结果跳转聊天”任务在 logout 前已发出时，仍可能在 clear 后重新打开并拉回会话

状态：已修复（2026-04-14）

修复说明：

- `serialize_group()` / `serialize_session()` / message session metadata 读取都改为只调用 `resolve_group_avatar_url()`；group avatar 生成只保留在写路径。

现状：

- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 的 `_open_contact_target()` 由 `_contact_open_task` 跟踪，但这类任务只会在 `destroyed` 时取消
- 正常 logout 里，[main.py](/D:/AssistIM_V2/client/main.py) 先 `clear_session()`，后面才 `deleteLater()` 主窗口
- 因此，如果用户在 logout 前刚从联系人页、群组页或搜索结果触发一次“打开聊天”，对应任务仍可能在 clear 之后继续完成
- 这条任务最终会调用 [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `open_direct_session()/open_group_session()/open_session()`
- 而这些入口又会继续走 `ensure_direct_session()` / `ensure_session_loaded()`，把会话重新从 manager/远端拉回本地

证据：

- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)

影响：

- logout 刚清掉的本地会话/消息状态，可能被这类晚到的 contact-jump 任务重新拉回
- 它还会把 UI 焦点切回聊天页，导致“已经退出账号”与“窗口仍在打开旧会话”同时出现
- 这再次说明当前 UI 层大量异步任务都依赖“窗口销毁时统一取消”，而 logout 的实际顺序又晚于 clear

建议：

- logout 进入后，应先取消主窗口的 `_contact_open_task/_ui_tasks`，不要等到 `destroyed`
- 同时给 `open_direct_session()/open_session()` 增加 shutdown/generation guard，避免旧登录代的 UI 跳转在 clear 后继续拉会话

### F-068：forced logout 不会取消顶层 `_warm_authenticated_runtime()`，`session_replaced` 之后仍可能再次发起旧 runtime 的同步与连接

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 在 `show_main_window()` 末尾通过 `self.create_task(self._warm_authenticated_runtime())` 启动顶层 warmup 任务
- 这条任务会继续执行 `_synchronize_authenticated_runtime()` 和 `start_background_services()`，也就是 `reload_sync_timestamp()`、`refresh_remote_sessions()`、`connect()`
- 但 `force_logout(reason=session_replaced)` 分支当前只执行 `AuthController.clear_session()` 与 `ConnectionManager.close()`，随后弹出 3 秒 warning，并不会取消 `Application._tasks`
- `Application._tasks` 只会在应用整体 `shutdown()` 时统一 cancel，因此 forced logout 的 warning 窗口里这条顶层 warmup 仍可能继续跑完

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client\main.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2\client\ui\controllers\auth_controller.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2\client\managers\connection_manager.py)

影响：

- 即使 forced logout 已经清掉本地状态并关闭当前连接，晚到的顶层 warmup 任务仍可能再次触发旧 runtime 的游标加载、远端会话刷新和连接尝试
- 这会把 `session_replaced` 之后的 3 秒 warning 窗口变成一个真实的竞态区，而不是纯 UI 倒计时
- 这说明 forced logout 现在不仅没 teardown 各个 manager，连 `Application` 自己创建的顶层 authenticated-runtime 任务也没有被冻结

建议：

- forced logout 进入后，应和普通 logout 一样先取消 `Application._tasks` 中属于 authenticated runtime 的任务
- 至少给 `_warm_authenticated_runtime()`、`_synchronize_authenticated_runtime()` 和 `start_background_services()` 增加 generation / forced-logout guard，避免旧登录代任务在 `session_replaced` 后继续执行

### F-069：通讯录/群搜索缓存是全局表且不带 `user_id` 作用域，logout 后晚到的旧账号缓存回写会直接污染下一账号的本地搜索

状态：已修复（2026-04-12）

修复记录：

- `contacts_cache` / `groups_cache` 已重构为按 `owner_user_id` 分区的复合主键缓存表；旧全局表会在连接阶段直接重建，不再保留“整表无账号作用域”的旧 schema。
- `replace_contacts_cache()` / `replace_groups_cache()` 现在只替换当前 owner 分区，`search_contacts()` / `search_groups()` / `list_contacts_cache_by_ids()` 也按当前 `auth.user_id` 过滤。
- 回归测试覆盖同一 `contact_id/group_id` 在不同账号下并存搜索，以及目录缓存替换中途失败时整批回滚。

现状：

- [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `load_contacts()/load_groups()` 完成后会调用 `_persist_contacts_cache()` / `_persist_groups_cache()`
- 这两条持久化路径最终调用 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `replace_contacts_cache()` / `replace_groups_cache()`
- 但本地 `contacts_cache` / `groups_cache` 表结构本身不带 `user_id`，而且 `replace_*_cache()` 的实现是先整表 `DELETE`，再把当前结果整批 `INSERT OR REPLACE`
- 因此前面 `F-057` 里那些 logout 后仍在飞的旧账号通讯录任务，一旦晚到完成，不是“补几条旧缓存”，而是会把下一账号的整份本地联系人/群搜索缓存直接替换成旧账号快照

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 这会把跨账号污染从“内存态/UI 怪异”直接升级为“下一账号本地搜索和侧边栏目录结果错误”
- 因为缓存表没有用户作用域，问题并不依赖两个账号数据正好重叠；只要旧账号晚到任务先落库，下一账号的本地联系人/群搜索基线就已经被替换
- 这说明联系人域的本地缓存模型还没有按账号收口，当前实现不算成熟稳定

建议：

- 给 `contacts_cache` / `groups_cache` 增加 `owner_user_id` 作用域，或在更高层正式保证“切账号前绝不允许旧任务继续写库”
- 同时为“logout 后旧通讯录任务晚到完成，再登录新账号并使用本地搜索”的路径补回归测试

### F-070：普通 logout 后重登会把应用级 E2EE diagnostics 写成自相矛盾的状态

状态：已修复（2026-04-12）

修复记录：

- 顶层登录/重登流程已拆成 pre-auth `initialize()` 和 authenticated runtime bootstrap，logout/relogin 成功后不再重新执行 pre-auth `initialize()` 覆盖 E2EE diagnostics。
- 回归测试覆盖普通 logout 先 quiesce runtime、清 auth 后只进入重新认证路径。

原现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的普通 logout 重登路径是 `_perform_logout_flow() -> authenticate() -> initialize() -> show_main_window()`
- `authenticate()` 成功后，会先通过 `_update_startup_security_status(auth_controller=...)` 和 `_update_e2ee_runtime_diagnostics(auth_controller=...)` 把 `Application` 的 app 级诊断缓存更新为“已认证的新账号”
- 但紧接着 `initialize()` 又会无条件把 `_e2ee_runtime_diagnostics` 重置成顶层 `authenticated=False / user_id=\"\" / current_session_security=\"authentication required\"`
- 同时，这次重置里嵌套的 `runtime_security` 却是通过 `self.get_startup_security_status()` 取值，而 `startup_security_status` 此时仍保留着刚刚认证成功的新账号信息
- 结果就是：同一份 `get_e2ee_runtime_diagnostics()` 返回值里，顶层字段显示“未认证”，嵌套 `runtime_security` 却显示“已认证且 user_id=新账号”

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 这不是抽象架构风险，而是一个确定的内存态不一致：同一份 app 级 diagnostics 在普通重登后会出现互相矛盾的认证状态
- 当前即使主要是 `Application` 自己和测试在消费这份数据，它也已经不满足“稳定、可验证的诊断快照”要求
- 后续只要有 UI、守卫逻辑或日志把它当成权威状态使用，就会出现误判和排障歧义

建议：

- 让普通重登路径和初次启动路径共享同一套 boot 顺序，避免 `authenticate()` 的结果被随后 `initialize()` 局部覆盖
- 如果保留现有顺序，至少不要在 `initialize()` 里重置 `_e2ee_runtime_diagnostics`，或在 `initialize()` 之后立刻重新按当前认证态完整刷新一次 diagnostics
- 为“logout -> relogin 后 app.get_e2ee_runtime_diagnostics() 仍自洽”补回归测试

### F-071：本地快照替换接口不是原子操作，并发写入时可能产出混合的 session/contacts/groups 快照

状态：已修复（2026-04-12）

修复记录：

- `replace_sessions()` 先前已收口为事务化替换；本轮继续把 `replace_contacts_cache()` / `replace_groups_cache()` 也改成 `BEGIN -> scoped DELETE -> full INSERT -> COMMIT` 的单事务路径。
- 目录缓存写入失败时会 `ROLLBACK`，不会留下“旧快照已删半截、新快照只写一部分”的混合状态。
- 回归测试覆盖联系人/群缓存替换过程中第二条插入失败时，旧快照仍完整保留。

现状：

- [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `replace_sessions()`、`replace_contacts_cache()`、`replace_groups_cache()` 都采用“先 `DELETE`，再逐条 `INSERT OR REPLACE`，最后 `commit()`”的实现
- 这些方法内部包含多次 `await self._db.execute(...)`，因此在 asyncio 调度下并不是一个不可分割的原子替换
- 前面的 `F-057/F-062/F-066/F-069` 已经确认 logout/relogin 边界上确实会存在旧账号与新账号的并发刷新/回写任务
- 在这种前提下，如果两个替换任务交错执行，结果不只是“谁后写谁覆盖”，而是可能出现 `DELETE(old) -> INSERT old row1 -> DELETE(new) -> INSERT new rowA -> INSERT old row2 ...` 这种混合快照

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 这会把前面那些“旧账号晚到任务回写”问题进一步放大成数据库层的一致性问题：本地会话列表、联系人缓存、群缓存都可能短时间内变成新旧账号数据混合的非权威快照
- 即使最终某一方再次覆盖，混合窗口也足以让 UI、本地搜索和后续增量同步读取到脏基线
- 这说明当前本地快照替换实现不够成熟稳定，缺少最基本的原子边界

建议：

- 把这类整表替换收口成单事务原子操作，至少在同一个事务里完成 `DELETE + 全量 INSERT + COMMIT`
- 更进一步，应避免旧登录代与新登录代并发触发同一类 replace；即使保留并发，也要有 generation guard 或 owner_user_id 作用域
- 为“旧账号和新账号并发 replace_*_cache/replace_sessions”补数据库级并发回归测试

### F-072：logout 会先清空 runtime 用户，再延后删除持久化 auth state；manager 回退逻辑会在这段窗口里继续把旧账号当成当前用户

状态：已修复（2026-04-12）

修复记录：

- `AuthController.clear_session()` 已调整为先事务化删除持久化 `auth.*` snapshot，再清 HTTP token/runtime user，最后执行本地 chat-state 清理。
- 回归测试覆盖 clear session 的顺序：先删 auth snapshot，再清 HTTP token，再清本地 chat state。

原现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `clear_session()` 会先把 `_current_user = None`，再调用 `message_manager.set_user_id(\"\")`、`chat_controller.set_user_id(\"\")`
- 但它直到 `_reset_local_chat_state()` 之后，才会进入 `_clear_persisted_auth_state()` 删除 `auth.user_profile` / `auth.user_id`
- 与此同时，[session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_get_current_user_context()` 和 [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的同名 helper，在 runtime 用户为空时都会回退去读 `auth.user_profile` / `auth.user_id`
- `MessageManager._apply_current_user_sender_profile()`、`SessionManager` 的多条会话归一化/预览路径都会依赖这份“当前用户上下文”
- 结果是：在 logout 那个“runtime 已清空、持久化 auth 还没删”的窗口里，晚到任务仍会继续把旧账号识别成当前用户

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 这会把前面那些 logout 期间的晚到 ACK/history/session refresh 问题再放大一层：不仅任务还在继续跑，而且它们读取“当前用户”的方式本身就会回退到旧账号
- 因此一些本该在 logout 后失效的 sender-profile stamping、会话名归一化、counterpart 判断、预览生成，仍可能按旧账号身份继续执行
- 这说明“当前用户上下文”的单一真相还没有收口，runtime 状态和持久化回退状态在退出窗口里同时生效

建议：

- logout 应先阻断这些 manager 的 persisted-auth fallback，或先删掉 `auth.user_profile/auth.user_id` 再清理 runtime 相关任务
- 更稳妥的做法是给这类 helper 增加 generation / logout guard，在退出流程里禁止再把 app_state 里的旧 auth 当成当前用户
- 为“logout 期间 runtime user 已清空，但 persisted auth 尚未删除”的路径补回归测试，覆盖消息 hydration 和会话预览归一化

### F-073：持久化 `auth.*` 会话快照不是原子更新，旧/新账号竞争时会把 token、user_id、profile 写成混合状态

状态：已修复（2026-04-12）

修复记录：

- `Database` 新增 `set_app_states()` / `delete_app_states()`，`AuthController` 写入和删除 `auth.access_token/auth.refresh_token/auth.user_id/auth.user_profile` 时走单事务。
- `restore_session()` 现在要求四个 `auth.*` 键组成完整 snapshot；部分缺失会清理 snapshot，不再继续使用混合状态。
- 回归测试覆盖 login auth snapshot 在 destructive chat reset 前一次性提交，以及持久化失败会回滚 auth runtime。

原现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `_persist_auth_state()` 会依次写 `auth.access_token`、`auth.refresh_token`、`auth.user_id`、`auth.user_profile`
- `_clear_persisted_auth_state()` 也会按同样方式逐 key 删除这几项
- 底层 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `set_app_state()` / `delete_app_state()` 每写或每删一个 key 都会立刻单独 `commit()`
- 这意味着 `auth.*` 并不是一个原子会话快照；在前面已经确认存在的旧/新账号并发 token 持久化、logout 清理、late refresh 竞争下，这四个键完全可能交错成“旧 token + 新 user_profile”或“新 token + 旧 user_id/profile”的混合状态

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 这不只是前面 `F-063` 那种单一竞争场景的副作用，而是 auth 持久化模型本身没有原子边界
- `restore_session()`、manager 的 persisted-auth fallback，以及任何读取 `auth.*` 的逻辑，都可能在窗口期看到一份自相矛盾的认证快照
- 从设计成熟度看，这说明“当前登录会话”在本地存储里还不是一个经过验证的单一真相对象

建议：

- 把 `auth.*` 四个键收口成单条原子会话记录，或至少在同一事务里完成整组写入/整组删除
- 同时给持久化写入增加 generation guard，禁止旧登录代的 token/profile 持久化覆盖新登录代
- 为“旧账号 token refresh 与新账号登录并发发生”补持久化一致性回归测试，直接校验 `auth.*` 快照不会混写

### F-074：全量远端会话替换只清 `sessions` 不清 `messages`，已从快照消失的会话仍会残留在本地消息搜索里

状态：已修复（2026-04-12）

修复记录：

- `Database.replace_sessions()` 已改为在同一事务里替换 session snapshot，并删除不在新 snapshot 里的 `messages`。
- 回归测试覆盖全量替换后 orphan session 的消息不会继续残留在本地搜索基础表中。

原现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `refresh_remote_sessions()` 会把后端返回的最新快照交给 `_replace_sessions()`
- 而底层 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `replace_sessions()` 只会 `DELETE FROM sessions` 再写回新的会话行，不会清理那些已从快照消失会话对应的本地 `messages`
- 同时本地搜索 [search_manager.py](/D:/AssistIM_V2/client/managers/search_manager.py) 是直接查 `messages` 表；即使某个 `session_id` 已经不在 `sessions` 表里，消息命中仍会被保留
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 处理 sidebar message-search 命中时，又会按 `session_id` 继续走 `open_session() -> ensure_session_loaded()`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 如果某个会话因为远端快照变化而从当前账号会话列表中消失，本地消息搜索仍可能继续把它翻出来
- 这会让“当前 authoritative session snapshot”和“本地可搜索/可重新打开的历史”出现分裂，用户看到的是已消失会话仍可从搜索侧门进入
- 在某些场景下，这条搜索命中还会通过 `ensure_session_loaded()` 重新把会话拉回 UI，进一步放大快照替换和本地残留之间的边界不一致

建议：

- 明确“会话从 authoritative snapshot 消失”时，本地历史是否还应保留和可搜索；如果不应保留，应同步清理对应 `messages`
- 如果历史允许保留，也应在搜索/打开路径上区分“历史命中”与“当前可访问会话”，不要直接复用 `open_session()`
- 为“会话从 refresh_remote_sessions() 快照消失后，本地消息搜索如何表现”补回归测试

### F-075：全量会话替换不会清理已消失会话的 `session_read_cursors`，会话复活后会套用旧已读状态

状态：已修复（2026-04-12）

修复记录：

- `Database.replace_sessions()` 会同步删除不在新 snapshot 里的 `session_read_cursors`，per-session read cursor 跟随 authoritative session lifecycle 清理。
- 回归测试覆盖被移除会话的 read cursor 在 snapshot 替换后被删除。

原现状：

- [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `replace_sessions()` 只会清空 `sessions` 表，不会清理那些已从快照消失会话对应的 `session_read_cursors`
- 而 `get_message()`、`get_messages()`、`get_last_message()` 在读取消息时，都会先 `_load_session_read_cursors(session_id)`，再 `_overlay_read_cursors_on_message(...)`
- 这意味着某个会话即使已经从当前 authoritative snapshot 消失，只要它后续通过搜索、旁路打开或远端重新下发被复活，本地历史消息会立刻重新叠上旧的 per-reader 已读游标
- 这条残留和前面的 `F-074` 是串起来的：快照替换只删会话行，不删历史消息，也不删该会话的读游标

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 已消失会话一旦被重新打开，本地历史会直接继承一份可能属于旧快照甚至旧账号窗口期的 read 状态
- 这会让“会话当前是否存在”和“会话历史上的 reader cursor 是否仍有效”两个边界继续分裂
- 从一致性角度看，这说明 per-session 附属状态没有跟随 authoritative session lifecycle 一起收口

建议：

- 如果会话从当前 authoritative snapshot 消失，应明确是否同时清理对应 `session_read_cursors`
- 如果历史允许保留，也至少应在会话复活时重新校验这些本地 read cursor 是否仍然有效
- 为“会话从快照消失后再复活，历史消息 read 状态如何恢复”补回归测试

### F-076：`restore_session()` 在网络错误时会直接信任 `stored_profile`，不会校验它是否与当前 token 属于同一账号

状态：已修复（2026-04-12）

修复记录：

- `restore_session()` 的离线/瞬时失败 fallback 只接受同时满足 `auth.user_id`、`auth.user_profile.id`、access token `sub`、refresh token `sub` 一致的本地快照。
- cached profile 缺失、无 `id` 或与 token/user_id 不一致时会清理 persisted auth snapshot 并清空内存 token。
- 回归测试覆盖 cached profile 与 token snapshot 混用时 restore 失败并清空状态。

原现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `restore_session()` 会先读取并解密持久化的 access/refresh token，同时独立读取 `auth.user_profile`
- 如果 `fetch_current_user()` 因 `NetworkError` 失败，只要 refresh token 本地未过期，代码就会直接 `json.loads(stored_profile)`，然后 `_apply_runtime_context(cached_user)` 并返回
- 这个离线回退路径并不会校验 `stored_profile` 与当前 token 是否属于同一账号，也不会比对 `auth.user_id`
- 前面的 `F-073` 已经确认 `auth.*` 持久化快照本身可能被写成混合状态，因此这里不是抽象担忧，而是一个可达的错误恢复路径

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 一旦本地 `auth.*` 因竞争窗口混成“某账号 token + 另一账号 profile”，`restore_session()` 在网络错误时就可能把错误的 cached profile 直接恢复成当前运行态用户
- 这会让客户端在离线或弱网恢复场景下把“当前身份”建立在一份未经校验的本地 profile 上，而不是正式认证结果
- 这已经偏离了成熟登录态设计应有的边界：离线回退不能绕过账号一致性校验

建议：

- 离线回退至少要验证 `stored_profile.id` 与 `auth.user_id` 一致，并尽量与 token payload 的 subject 对齐
- 如果无法验证一致性，应拒绝恢复本地 profile，而不是直接 `_apply_runtime_context(cached_user)`
- 为“token/profile 混写 + restore_session 遇到网络错误”的路径补回归测试，确保不会恢复出错误账号身份

### F-077：会话从远端快照消失后，本地 reconnect cursor 不会被修剪，后续 sync 请求会长期携带 orphan `session_id`

状态：已修复（2026-04-12）

修复记录：

- `ConnectionManager.prune_sync_state()` 会按 authoritative session id 集合修剪 message/event reconnect cursors，并持久化修剪后的 `app_state`。
- `SessionManager._replace_sessions()` 在刷新远端 authoritative snapshot 后会调用现有 ConnectionManager 修剪 sync state。
- 回归测试覆盖 ConnectionManager cursor 修剪，以及 SessionManager refresh 后把当前 session snapshot 传给连接层修剪。

原现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_replace_sessions()` / `refresh_remote_sessions()` 会替换本地会话快照，但不会联动清理 reconnect 相关状态
- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 会把 `last_sync_session_cursors` / `last_sync_event_cursors` 持久化到 `app_state`，后续重启或重连时再原样加载回来
- 如果持久化 session cursor 为空，它还会退回 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `get_session_sync_cursors()`，而这个方法是直接扫描 `messages` 表里的 `session_seq`，并不关心该 `session_id` 是否仍存在于 `sessions` 表
- 结果是：某个会话即使已经从当前 authoritative session snapshot 里消失，只要本地还残留消息或旧 cursor，这个 `session_id` 就会继续出现在后续 `sync_messages` 请求里

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 这会让 reconnect 恢复点持续携带一批已经不属于当前会话快照的 orphan `session_id`，形成状态漂移和 payload 冗余
- 在最保守的情况下，它会增加 sync 请求和本地恢复状态的噪音；在更差的情况下，如果服务端仍按当前 membership 为这些会话返回增量，就会让“已从快照消失的会话”继续从补偿链路旁路回流
- 这说明 reconnect cursor 没有跟随 authoritative session lifecycle 一起收口

建议：

- 在会话从 authoritative snapshot 中移除时，同步修剪对应的 message/event reconnect cursor
- `get_session_sync_cursors()` 也应只对仍然存在于当前 session snapshot 的 `session_id` 产出游标
- 为“会话从快照消失后，后续 reconnect sync 请求不再携带该 session_id”补回归测试

### F-078：`restore_session()` 失败回到登录界面时不会回滚内存 token，auth 窗口后续请求仍会带旧 `Authorization`

状态：已修复（2026-04-12）

修复记录：

- `restore_session()` 在已装载 HTTP token 后，只要判定本地 snapshot 无效或不可恢复，就会走 `clear_session(clear_local_chat_state=False)` 清空 HTTP token 和 runtime user，不再把登录窗口留在旧 Authorization 下。
- 回归测试覆盖网络错误加无效 cached profile 时 restore 返回 `None` 且 HTTP token 被清空。

原现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `restore_session()` 会在真正向后端校验前，先 `_set_http_tokens(access_token, refresh_token)`
- 如果随后 `fetch_current_user()` 命中 `NetworkError`，且本地 `stored_profile` 不可用或解析失败，函数会直接 `return None`
- 这条失败分支不会调用 `clear_session()`，也不会 `_clear_http_tokens()`
- [main.py](/D:/AssistIM_V2/client/main.py) 的 `authenticate()` 在拿到 `None` 后会直接弹出登录窗口
- 但 [auth_service.py](/D:/AssistIM_V2/client/services/auth_service.py) 的 `login()` / `register()` / `fetch_current_user()` 仍然走相对路径请求，而 [http_client.py](/D:/AssistIM_V2/client/network/http_client.py) 默认会对所有相对路径自动附带当前 `_access_token`

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\services\auth_service.py](D:\AssistIM_V2/client/services/auth_service.py)
- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)

影响：

- 一旦 session restore 失败但没有走到 `clear_session()`，应用会处在“UI 认为未认证，但 HTTP client 仍带旧账号 token”的分裂状态
- 随后登录窗口发出的 `/auth/login`、`/auth/register`、`/auth/me` 之类请求会继续带旧 `Authorization` 头，未认证入口被旧认证态污染
- 即使服务端当前大概率忽略这些头，这仍然说明“恢复失败后回到未认证态”的边界没有真正收口；后续任何依赖相对路径默认鉴权的 auth/boot 请求都可能受到影响

建议：

- 把 `restore_session()` 改成只有在 `fetch_current_user()` 或本地离线恢复真正成功后，才提交内存 token 到 HTTP client
- 或者至少在 `NetworkError` 且未成功恢复本地用户时，显式 `_clear_http_tokens()` 回滚到真正未认证态
- 补一条回归测试，验证“restore 失败后弹登录窗口”场景里，auth 相关请求不会继承旧账号 `Authorization`

### F-079：登录窗口里的 `/auth/login` 失败会先触发旧账号 token refresh，再重试登录请求

状态：已修复（2026-04-12）

修复记录：

- `AuthService.login()` / `register()` 已显式使用 `use_auth=False` 和 `retry_on_401=False`，认证入口不会继承旧账号 Authorization，也不会先触发旧 token refresh。
- 回归测试覆盖 login/register 请求参数不会带旧 app auth。

原现状：

- 前一条 `F-078` 已确认：`restore_session()` 失败回到登录界面时，HTTP client 里可能仍保留旧账号 `access_token/refresh_token`
- [auth_interface.py](/D:/AssistIM_V2/client/ui/windows/auth_interface.py) 的 `_perform_login()` 会调用 [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `login()`
- 该调用最终落到 [auth_service.py](/D:/AssistIM_V2/client/services/auth_service.py) 的 `POST /auth/login`，而 [http_client.py](/D:/AssistIM_V2/client/network/http_client.py) 对相对路径默认 `use_auth=True`
- 一旦 `/auth/login` 返回 401，`HTTPClient._handle_response()` 会先走 `_refresh_access_token()`，成功后再自动重试原始 `/auth/login`
- 服务端 [auth.py](/D:/AssistIM_V2/server/app/api/v1/auth.py) / [auth_service.py](/D:/AssistIM_V2/server/app/services/auth_service.py) 明确把“用户名或密码错误”定义成 401 `INVALID_CREDENTIALS`

证据：

- [D:\AssistIM_V2\client\ui\windows\auth_interface.py](D:\AssistIM_V2/client/ui/windows/auth_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\services\auth_service.py](D:\AssistIM_V2/client/services/auth_service.py)
- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)
- [D:\AssistIM_V2\server\app\api\v1\auth.py](D:\AssistIM_V2/server/app/api/v1/auth.py)
- [D:\AssistIM_V2\server\app\services\auth_service.py](D:\AssistIM_V2/server/app/services/auth_service.py)

影响：

- 这意味着“恢复失败后停在登录窗口”并不是真正的未认证态；用户只要输错一次密码，客户端就可能先拿旧 refresh token 去轮转上一账号会话
- 如果 refresh 成功，客户端会在登录窗口阶段静默更新内存 token，并用这份刚刷新的旧账号认证态重试新的 `/auth/login`
- 即使 refresh 失败，它也会在未认证 auth flow 里触发一次与旧账号相关的 token 清理/变更，说明 auth 窗口和上一登录代的认证状态还没有隔离干净

建议：

- 对 `/auth/login`、`/auth/register`、`/auth/refresh`、`/auth/me` 这类未认证/认证恢复入口显式禁用默认 app auth 继承与 401 refresh 重试
- 或者在 auth 恢复失败后立刻清空 HTTP client token，确保 auth 窗口阶段不再可能触发旧账号 refresh
- 补一条回归测试，验证“restore 失败后在登录窗口输错密码”不会调用 `_refresh_access_token()`，也不会重试带旧认证态的 `/auth/login`

### F-080：`restore_session()` 只校验 access token 对应的 `/auth/me`，不会验证 refresh token 是否属于同一账号/同一 session

状态：已修复（2026-04-12）

修复记录：

- `restore_session()` 在 `/auth/me` 成功后会校验 refresh token payload 的 `sub` 与当前用户一致，并在 access/refresh 都带 `session_version` 时要求版本一致。
- refresh token 属于其它账号或其它 session version 时会清理 persisted auth snapshot 并拒绝恢复。
- 回归测试覆盖 refresh token 指向不同用户时 restore 失败且不启动 E2EE bootstrap。

原现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `restore_session()` 会同时解密并装载持久化的 `access_token` 和 `refresh_token`
- 但它真正向后端做的校验只有一次 `fetch_current_user()`，也就是用当前 access token 调 `GET /auth/me`
- 只要这次 `/auth/me` 成功，`restore_session()` 就会把 `self._auth_service.refresh_token or refresh_token` 原样再次持久化，并把 `/auth/me` 返回的 `user` 作为当前 runtime 用户
- 它没有检查 refresh token 的 `sub/session_version` 是否和 access token 对应的用户一致
- 之后如果这份 refresh token 参与自动刷新，[http_client.py](/D:/AssistIM_V2/client/network/http_client.py) 会按 refresh token 自身的 `sub/session_version` 向 [auth_service.py](/D:/AssistIM_V2/server/app/services/auth_service.py) 取回新 token；而 [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 token listener 又会用“新 token + 旧 `_current_user`”去持久化 auth 状态

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)
- [D:\AssistIM_V2\server\app\services\auth_service.py](D:\AssistIM_V2/server/app/services/auth_service.py)

影响：

- 在前面已确认的 `F-073`“auth.* 多 key 混写”前提下，只要本地出现 `access_token=A`、`refresh_token=B` 的混合快照，而 access token 仍可用，`restore_session()` 就会把用户 A 当作当前登录态恢复成功
- 这会把“当前 UI/runtime 用户”和“后续自动 refresh 将要续约的账号”拆成两条不同身份
- 一旦后续发生 401 自动刷新，客户端就可能拿到用户 B 的新 token，同时仍把用户 A 当作 `_current_user` 和持久化 profile 的来源，形成更严重的认证态分裂

建议：

- `restore_session()` 不应只验证 `/auth/me`；至少要在本地校验 refresh token 的 `sub/session_version` 与 access token / `user.id` 一致
- 更稳妥的做法是把持久化 auth 快照收口成一个原子对象，并在 restore 时整体验证，而不是分别相信 access、refresh、profile
- 补一条“access/refresh 来自不同账号或不同 session_version”的回归测试，验证 restore 会拒绝进入已认证 runtime

### F-081：离线 `restore_session()` 只要返回非空 `stored_profile` 就会被当作登录成功，哪怕 profile 根本没有 `id`

状态：已修复（2026-04-12）

修复记录：

- 离线 cached profile fallback 已收口到 `_load_cached_user_profile()`，只接受 dict 且必须带非空 `id`，并要求 `id` 等于持久化 `auth.user_id`。
- 回归测试覆盖非空但缺 `id` 的 cached profile 不再被视为登录成功。

原现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `restore_session()` 在 `NetworkError` 分支里，只要 `stored_profile` 存在且 refresh token 未过期，就会 `json.loads(stored_profile)`、`_apply_runtime_context(cached_user)` 并直接 `return cached_user`
- 这条离线 fallback 没有校验 `cached_user` 是否是 dict 且带有效 `id`
- [main.py](/D:/AssistIM_V2/client/main.py) 的 `authenticate()` 只判断 `if restored_user:`；任何非空 dict 都会被视为 restore 成功，并继续进入主窗口
- 但与此同时，[auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `get_runtime_security_status()` / `get_e2ee_diagnostics()` 又都是按 `current_user.id` 判断 authenticated
- 所以一旦 `stored_profile` 是一个非空但无 `id` 的对象，应用会进入“启动流程判定已登录成功，但 runtime diagnostics 仍判定未认证”的自相矛盾状态

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 这不是单纯的数据洁癖问题，而是 restore 成功的正式契约本身不完整：进入 authenticated runtime 的条件和 runtime 自身判断 authenticated 的条件并不一致
- 在 auth 快照混写、旧版本残留或本地状态损坏场景下，应用可能直接打开主窗口，但随后各类必须要求 `current_user.id` 的功能又会把当前 runtime 当成未认证
- 这会进一步放大前面 `F-070/F-076/F-080` 那组 auth 恢复问题，使“已登录/未登录”的边界在启动阶段就分裂

建议：

- `restore_session()` 的所有成功返回路径都应显式验证 `user.id`，不满足就视为 restore 失败并清理本地 auth 状态
- `authenticate()` 也不应只看对象 truthiness，应以 `restored_user.id` 是否有效作为成功条件
- 补一条回归测试，验证“离线 stored_profile 非空但缺少 id”不会进入主窗口

### F-082：`/auth/me` 的瞬时 5xx 会被 `restore_session()` 误判成 session 失效，并直接清空本地登录态

状态：已修复（2026-04-12）

修复记录：

- `restore_session()` 已在 `APIError` 之前单独捕获 `ServerError`，5xx 被视为瞬时服务端错误，不再直接当作 session 失效清理登录态。
- 5xx 场景只有在本地 cached profile 与 token snapshot 一致时才允许离线恢复。
- 回归测试覆盖 `/auth/me` 503 时使用一致 cached profile 恢复，并保留 HTTP token/runtime user。

原现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `restore_session()` 在把持久化 token 装进 HTTP client 后，会调用 `fetch_current_user()` 校验当前 session
- 它只捕获了 `AuthExpiredError`、`APIError` 和 `NetworkError`
- 但 [http_client.py](/D:/AssistIM_V2/client/network/http_client.py) 对所有 5xx 响应都会抛出 `ServerError`
- [exceptions.py](/D:/AssistIM_V2/client/core/exceptions.py) 里，`ServerError` 继承自 `APIError`
- 因此 `/auth/me` 的 5xx 会落进 `except (AuthExpiredError, APIError)` 分支，被记录成 “Stored auth session is no longer valid”，随后直接 `clear_session()`

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)
- [D:\AssistIM_V2\client\core\exceptions.py](D:\AssistIM_V2/client/core/exceptions.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 这意味着只要应用带着本地持久化 session 启动，而服务端 `/auth/me` 恰好返回一次瞬时 5xx，客户端就会把“服务端暂时错误”误当成“本地 session 已失效”
- 用户会被直接登出，本地持久化 auth 状态和本地聊天缓存清理流程都会被触发，影响明显大于一次暂时性的后端故障
- 这说明 `restore_session()` 目前把“认证失效”和“服务端暂时不可用”混成了一类恢复结果

建议：

- 把 `restore_session()` 的校验结果至少拆成“认证失效”和“服务端暂时错误”两类，不要再统一走 `clear_session()`
- 对 `/auth/me` 的 5xx 应明确选择降级策略：保留本地 session 等待重试、回到登录窗口但不清持久化状态，或进入受限离线模式
- 补一条回归测试，验证“持久化 session 启动时 `/auth/me` 返回 500”不会直接清空本地登录态

### F-083：WebSocket 重连只用 access token 做认证，token 过期后不会自动 refresh，实时链路会卡在“已连接但未认证”

状态：已修复（2026-04-12）

修复记录：

- `HTTPClient` / `AuthService` 已暴露标准 single-flight `refresh_access_token()`。
- `ConnectionManager` 在首次 WS auth 401/40101/403 时不会立刻把错误上抛到应用层，而是先刷新 access token 并重发 WS auth；刷新失败或重发失败才把终态错误交给顶层 auth-loss。
- 回归测试覆盖 WS auth 过期后 refresh 成功会重发 auth 且不触发 auth-loss，以及 refresh 失败才上抛终态错误。

原现状：

- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 `_authenticate_websocket[_nowait]()` 只会把当前 `access_token` 发给 WS `auth`
- 如果服务端返回认证错误，[chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 只会回一个应用层 `error`，不会断开 socket
- 客户端 [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 收到这类 `error` 时，只会在 `_ws_auth_in_flight` 为真时把标志清掉；它不会尝试 refresh token，也不会重新发送 WS auth
- 由于 `_ws_authenticated` 仍是 `False`，后续 `sync_messages` 会被直接跳过
- 与此相对，[http_client.py](/D:/AssistIM_V2/client/network/http_client.py) 的 token refresh 只存在于 HTTP 401 路径；WebSocket 认证失败本身不会触发这条链

证据：

- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\server\app\websocket\auth.py](D:\AssistIM_V2/server/app/websocket/auth.py)

影响：

- 只要发生“WS 重连时 access token 已过期，但 refresh token 仍可用”的场景，客户端就会进入一个稳定的半死状态：WebSocket 传输层已连接，但业务层始终未认证，历史补偿和实时消息都不会恢复
- 这不只影响离线 restore；机器休眠恢复、长时间挂起后的自动重连、网络闪断后的重连都可能触发
- 用户通常必须先碰一次会触发 HTTP 401 refresh 的接口，或者重新登录，实时链路才会被间接救活；这说明 WS 认证和 HTTP 认证并没有形成完整一致的恢复模型

建议：

- 在 WS auth 返回 401/unauthorized 错误时，显式走一次 refresh token 流程，成功后立即重发 WS auth
- 或者在 WebSocket 握手前先确保 access token 新鲜，避免让 WS 自己承担过期 token 恢复逻辑
- 补一条回归测试，验证“access token 过期 + refresh token 有效 + WebSocket 重连”场景下，客户端能自动恢复到 `ws_authenticated=True`

### F-084：HTTP refresh 失败后只会清空 token 持久化，不会退出当前 authenticated runtime

状态：已修复（2026-04-12）

修复记录：

- `HTTPClient` 已提供 auth-loss listener，refresh 被拒绝时会 `clear_tokens()` 并通知顶层 `refresh_rejected`。
- `Application.initialize()` 订阅 HTTP auth-loss，统一进入 `_handle_auth_lost()`：先 quiesce authenticated runtime，再 `clear_session(clear_local_chat_state=False)`，随后重新认证。
- 回归测试覆盖 refresh rejected 走单一 auth-loss flow，且不会把本地聊天缓存当作普通 logout 一样 purge。

原现状：

- [http_client.py](/D:/AssistIM_V2/client/network/http_client.py) 的 `_perform_token_refresh()` 在 refresh 失败或异常时会直接 `clear_tokens()`
- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 监听 token 变化；当 `access_token` 变成空时，`_on_tokens_changed()` 只会异步执行 `_clear_persisted_auth_state()`
- 这条路径不会调用 `clear_session()`，不会清 `_current_user`，也不会触发 logout / 关闭主窗口 / 回到登录界面
- 结果是：运行中的 UI、`SessionManager`、`ChatController` 仍会保留上一账号的 authenticated runtime 状态，但 HTTP client 已经没有 token；后续 WebSocket 重连也会因为“no access token present”而跳过认证

证据：

- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)

影响：

- 一旦运行中发生“access 401 且 refresh 失败”，客户端不会像真正 session 失效那样收口到未认证态，而是停留在“主窗口还在、当前用户还在、但传输层已失去认证能力”的分裂状态
- 这会让用户继续看到旧账号会话、联系人和资料，但新的 HTTP 请求会持续 401，后续 WS 重连也会稳定卡在未认证
- 这说明“token 不存在”与“当前 runtime 已失效”在客户端里不是同一个状态机事件，认证边界仍然分裂

建议：

- 把 refresh 失败后的 token 清空升级为正式的 runtime auth-loss 事件，统一收口到 `clear_session()` / 强制回登录态
- 至少在 token listener 里把“access_token cleared”区分为一次真正的会话失效，而不是只删持久化快照
- 补一条回归测试，验证“运行中 refresh 失败”会退出当前 authenticated runtime，而不是只清空 `auth.*`

### F-085：WebSocket 认证失效不会触发正式 auth-loss 流程，应用顶层只处理 `force_logout(session_replaced)`

状态：已修复（2026-04-12）

修复记录：

- `Application._handle_transport_message()` 已处理 WS `auth_ack(success=false)` 和 WS auth `error(code=401/40101)`，统一调度 `_on_auth_loss()`。
- 业务 forbidden（例如非会话成员 403）不会被误判为 auth-loss。
- 回归测试覆盖 WS auth error 触发 auth-loss，业务 forbidden 不触发 auth-loss。

原现状：

- 服务端 [auth.py](/D:/AssistIM_V2/server/app/websocket/auth.py) 会把 WS token 缺失、无效、session 过期都明确归类成 401 `UNAUTHORIZED`
- [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 对这类错误的处理是发送应用层 `error` 包，而不是关闭 socket 或发送统一的 auth-loss 事件
- 客户端 [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 收到 `type == "error"` 时，如果只是 WS auth in-flight，只会把 `_ws_auth_in_flight` 清掉；不会 refresh token、不会重新认证、不会向上报告“当前认证态已失效”
- 应用顶层 [main.py](/D:/AssistIM_V2/client/main.py) 的 `_handle_transport_message()` 又只处理 `force_logout`，而且仅当 `reason == "session_replaced"` 时才触发正式退场
- 结果是：普通的 WS unauthorized / session expired 与前一条 `F-084` 里的 HTTP auth-loss 一样，都不会被收口成统一的 runtime 认证丢失事件

证据：

- [D:\AssistIM_V2\server\app\websocket\auth.py](D:\AssistIM_V2/server/app/websocket/auth.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 当前只有“被别处顶掉登录”的一种场景会触发正式退场；而 token 过期、session 失效、WS unauthorized 等更常见的认证丢失路径都会静默留在旧 runtime 里
- 这会让 HTTP、WS、force logout 三条认证失效链路各自表现不同，用户看到的症状也不一致：有时被强退，有时主窗口还在但实时链路死掉，有时只是 auth 快照被删
- 这说明客户端还没有一个成熟的统一 auth-loss 状态机

建议：

- 把 HTTP refresh 失败、WS unauthorized/session expired、force_logout 等事件统一收口成同一个 app-level auth-loss 入口
- 不要再让 `main.py` 只识别 `force_logout(session_replaced)`；普通 transport 级认证失效也应能触发正式 teardown / 重新认证
- 补回归测试，覆盖 HTTP auth-loss、WS auth-loss、session_replaced 三条路径在应用层的统一行为

### F-086：服务端正式发送的 `force_logout(reason=logout)` 会被客户端应用层直接忽略

状态：已修复（2026-04-12）

修复记录：

- `Application._handle_transport_message()` 已接受 `force_logout(reason=logout)` 和 `force_logout(reason=session_replaced)` 两种服务端正式控制语义，并统一进入 auth-loss flow。
- forced logout 现在复用 `_handle_auth_lost("force_logout:<reason>")`，退出后会清掉 `_forced_logout_in_progress`。
- 回归测试覆盖 `force_logout(reason=logout)` 会进入顶层 auth-loss flow。

原现状：

- 服务端 [auth.py](/D:/AssistIM_V2/server/app/api/v1/auth.py) 在 `DELETE /auth/session` 成功后，会对该用户所有在线连接发送 `force_logout`，其 payload 明确是 `{\"reason\": \"logout\"}`
- 但客户端 [main.py](/D:/AssistIM_V2/client/main.py) 的 `_handle_transport_message()` 只在 `reason == "session_replaced"` 时才触发正式 forced logout 流程
- 其它 `force_logout` reason 会被直接忽略
- 这意味着服务端已经定义并发送的“logout”控制语义，在客户端应用层没有任何正式处理路径

证据：

- [D:\AssistIM_V2\server\app\api\v1\auth.py](D:\AssistIM_V2/server/app/api/v1/auth.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 如果同一账号在别处触发正式 logout，当前客户端会收到服务端明确的 `force_logout(reason=logout)`，但应用层不会清本地 auth 状态、不会关主窗口、也不会回到登录页
- 后续连接大概率只会表现成 socket 被服务器踢下线，再配合前面的 `F-083/F-085` 落入“runtime 还在、但实时认证已失效”的僵尸状态
- 这说明客户端不仅缺少统一 auth-loss 状态机，连服务端已经正式定义的控制消息枚举都没有完整实现

建议：

- 把 `force_logout` 作为正式控制命令完整建模，不要只特判 `session_replaced`
- 至少补齐 `reason=logout` 的应用层处理，使其与其它认证丢失路径一起收口到统一 teardown / re-auth 流程
- 补回归测试，验证“另一端执行 logout 后，本端收到 `force_logout(reason=logout)`”会正式退出当前 authenticated runtime

### F-087：协议已把 `online/offline/presence` 定义为当前事件，但桌面端主链路没有任何 consumer

状态：已修复（2026-04-14）

修复说明：

- 已选择收缩边界：桌面端不接入 presence consumer，协议文档不再把 `online/offline/presence` 列为当前正式事件
- 服务端已移除主 `/ws` 的 `online/offline` fanout 和独立 `/ws/presence` 子协议
- 架构文档已把该层改写为连接注册 / fanout 边界，而不是桌面端 presence 功能

现状：

- [realtime_protocol.md](/D:/AssistIM_V2/docs/realtime_protocol.md) 明确把 `online`、`offline`、`presence` 列为“当前已存在的事件”
- 服务端 [presence_ws.py](/D:/AssistIM_V2/server/app/websocket/presence_ws.py) 和 [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 也会实际发送 `online` / `offline` / `presence` / `pong`
- 但客户端代码里没有任何 `/ws/presence`、`presence_query`、`online_users` 的使用入口，也没有任何针对 `online/offline/presence` 的消息消费分支
- 应用顶层 [main.py](/D:/AssistIM_V2/client/main.py) 的 transport bypass 只处理 `force_logout`
- [message.py](/D:/AssistIM_V2/client/models/message.py) 虽然仍保留 `UserStatus` 模型，但桌面主链路并没有用实时 presence 去驱动联系人或会话 UI

证据：

- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2/docs/realtime_protocol.md)
- [D:\AssistIM_V2\server\app\websocket\presence_ws.py](D:\AssistIM_V2/server/app/websocket/presence_ws.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\models\message.py](D:\AssistIM_V2/client/models/message.py)

影响：

- 这不是简单的“某个事件暂时没用上”，而是协议和服务端都已经把 presence 当正式能力，但桌面端主链路根本没实现
- 结果是 presence 相关消息持续占用协议面和服务端 fanout，但对桌面产品没有任何实际效果，属于明确的文档/实现漂移
- 如果团队以协议文档为依据继续叠加在线状态功能，很容易误以为客户端已经具备基础消费能力

建议：

- 要么把 presence 明确降级为“服务端保留能力、桌面端暂未接入”，同步收缩协议文档
- 要么补齐桌面端的正式 consumer 和 UI 更新链路，不要继续维持“协议已定义、实现未接”的半完成状态
- 补回归测试或集成检查，确保协议文档里列为“当前事件”的类型在桌面端至少存在一个正式消费入口

### F-088：协议文档把 `ping/heartbeat/pong` 列为当前聊天 WS 事件，但桌面端真实主链路并不使用这套 JSON 保活

状态：已修复（2026-04-14）

修复说明：

- 协议文档已明确桌面端主链路使用 WebSocket transport ping frame，不使用 JSON `ping/heartbeat/pong`
- 服务端聊天 WS 已移除 JSON `ping/heartbeat` 的 `pong` 分支，未支持命令统一走 `error`
- 已更新幂等消息测试，确认 `heartbeat` 不再被当作正式应用层保活事件

现状：

- [realtime_protocol.md](/D:/AssistIM_V2/docs/realtime_protocol.md) 在“3.1 连接与保活”里把 `auth`、`ping`、`heartbeat`、`pong` 列为当前聊天 WebSocket 协议的一部分
- 服务端 [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) / [presence_ws.py](/D:/AssistIM_V2/server/app/websocket/presence_ws.py) 也确实保留了对 JSON `ping` / `heartbeat` 的处理，并返回应用层 `pong`
- 但桌面端 [websocket_client.py](/D:/AssistIM_V2/client/network/websocket_client.py) 的保活实现用的是底层 websocket ping frame：`self._ws.ping()`
- 客户端代码里也没有任何发送 JSON `ping` / `heartbeat` 的入口，更没有任何针对应用层 `pong` 的消费逻辑

证据：

- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2/docs/realtime_protocol.md)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\server\app\websocket\presence_ws.py](D:\AssistIM_V2/server/app/websocket/presence_ws.py)
- [D:\AssistIM_V2\client\network\websocket_client.py](D:\AssistIM_V2/client/network/websocket_client.py)

影响：

- 这已经不是“未来可能会用”的协议预留，而是文档把一套当前桌面端根本不用的 JSON 保活机制写成了正式现行协议
- 结果是文档读者会误以为客户端和服务端都在依赖应用层 `ping/pong`，而真实实现依赖的是 websocket transport 自带的 ping frame
- 这类漂移会直接误导后续诊断和联调，例如有人去追 `pong` 消费链路时会发现桌面端根本没有这条路径

建议：

- 要么把协议文档里的当前保活机制改成“桌面端主链路使用 websocket ping frame，JSON `ping/heartbeat/pong` 仅为服务端兼容入口/保留能力”
- 要么让客户端真正接入并使用文档声明的 JSON 保活协议，但不要继续维持“两套保活模型并存，文档只写其中一套”的状态
- 补一个最小的协议一致性检查，确保文档列为“当前保活事件”的消息类型在桌面端确实存在发送或消费入口

### F-089：协议已把 `error` 列为正式返回事件，但桌面端除通话和 WS auth in-flight 外几乎没有任何 consumer

状态：已修复（2026-04-14）

修复说明：

- `MessageManager` 已增加正式 `error` consumer，按 `msg_id` 关联 pending outbound message
- WS 命令失败会立即移除 pending、标记本地消息 `FAILED` 并发出 `MessageEvent.FAILED`，不再只依赖 ACK 超时
- 已补 `test_message_manager_marks_pending_message_failed_on_ws_error`

现状：

- [realtime_protocol.md](/D:/AssistIM_V2/docs/realtime_protocol.md) 在“3.1 连接与保活”里把 `error` 列为当前服务端返回事件
- 服务端 [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 也大量使用 `_send_app_error()` 返回应用层错误，覆盖 WS auth、sync、chat_message、typing、read、edit、recall、delete、通话 signaling 等多类命令失败
- 但客户端 [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `_handle_ws_message()` 并没有 `error` 分支，最终只会把它当成 unknown message type
- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 对 `error` 的唯一特殊处理，只是在 WS auth in-flight 时把 `_ws_auth_in_flight` 清掉
- [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 是唯一把 `error` 当正式业务事件消费的 manager，而且只处理 `msg_id == active_call.call_id` 的通话错误

证据：

- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2/docs/realtime_protocol.md)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- 这意味着除通话和 WS auth 这两个特例外，服务端通过 WS 返回的正式命令错误基本不会被桌面端主链路消化
- 对发消息、typing、read、sync 等 WS 命令来说，失败通常只能退化成“没有后续 ACK/广播”或超时重试，而不是立即把权威错误反馈给上层
- 这已经偏离了协议文档把 `error` 定义成正式返回事件的语义，也让很多故障只能以超时/静默失败的形式暴露

建议：

- 把 `error` 收口成正式的 transport/control 事件，在桌面端建立统一 consumer，而不是只让 CallManager 和 WS auth 特判
- 对需要用户感知或状态机回滚的命令，优先在收到权威 `error` 时立即处理，不要退化成 ACK 超时兜底
- 补协议一致性测试，确保文档列为正式返回事件的 `error` 在桌面端存在明确消费路径

### F-090：协议和客户端保留了失败 ACK 语义，但服务端真实实现里 `auth_ack/message_ack` 只会发送成功分支

状态：已修复（2026-04-14）

修复说明：

- 协议文档已明确 `auth_ack/message_ack` 只表示成功提交，失败统一走同 `msg_id` 的 `error`
- `MessageManager` 已移除 `message_ack(success=false)` 的失败处理语义，非成功 ACK 会被视为协议异常并忽略
- 失败消息处理迁移到正式 `error` consumer，并由新测试覆盖

现状：

- [realtime_protocol.md](/D:/AssistIM_V2/docs/realtime_protocol.md) 把 `auth_ack` 和 `message_ack` 都写成带 `success` 字段的正式返回事件
- 客户端 [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 会读取 `auth_ack.data.success`
- 客户端 [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 也明确实现了 `message_ack(success=false)` 的拒绝分支，会把消息标成 `FAILED`
- 但服务端 [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 里，`auth_ack` 只在认证成功时发送 `{\"success\": true, \"user_id\": ...}`；认证失败统一走 `error`
- 同样地，`message_ack` 只在发送成功时发送 `{\"msg_id\": ..., \"success\": true, \"message\": ...}`；发送失败统一走 `error`
- 仓库里没有任何 `auth_ack(success=false)` 或 `message_ack(success=false)` 的服务端发送点

证据：

- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2/docs/realtime_protocol.md)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)

影响：

- 这意味着协议文档和桌面端都还保留着“失败 ACK”这套语义，但真实服务端已经把失败语义收口到了 `error`
- 对桌面端来说，`message_ack(success=false)` 这条正式失败路径实际上是死分支；真实失败只能落入前一条 `F-089` 所说的“error 基本没人接”或 ACK 超时兜底
- 这是一种很典型的半重构状态：语义已经换轨，但协议文档和客户端分支还没一起收口

建议：

- 明确二选一：要么正式保留失败 ACK，并让服务端真的发送 `success=false`；要么把失败统一收口到 `error`，同步删掉文档和客户端里的失败 ACK 语义
- 如果选择统一 `error`，应把 `MessageManager` 的拒绝处理迁到正式 `error` consumer，而不是继续保留死的 `message_ack(false)` 分支
- 补协议一致性检查，确保文档声明的返回事件分支在服务端至少有一个真实发送点

### F-091：服务端维护了一条独立 `/ws/presence` 子协议，但桌面端根本不会连接这条通道

状态：已修复（2026-04-14）

修复说明：

- 已下线独立 `/ws/presence` 子协议并删除 `presence_ws.py`
- app route 边界测试已改为断言 `/ws/presence` 不再公开
- 架构文档已同步说明桌面端当前不公开独立 presence socket

现状：

- 服务端 [presence_ws.py](/D:/AssistIM_V2/server/app/websocket/presence_ws.py) 单独公开了 `/ws/presence`，支持 `presence_query` 并返回 `presence { online_users: [...] }`
- 但客户端配置 [config_backend.py](/D:/AssistIM_V2/client/core/config_backend.py) 里唯一的 WebSocket 入口是 `ws_url -> /ws`
- 全仓客户端代码也没有任何 `/ws/presence`、`presence_query`、`online_users` 的引用或连接入口
- 与此同时，主聊天 socket [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 又自己承担了 `online/offline/pong` 这部分 presence/control fanout

证据：

- [D:\AssistIM_V2\server\app\websocket\presence_ws.py](D:\AssistIM_V2/server/app/websocket/presence_ws.py)
- [D:\AssistIM_V2\client\core\config_backend.py](D:\AssistIM_V2/client/core/config_backend.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)

影响：

- 这说明服务端当前实际上维护了两套 presence/control 边界：一套是独立 `/ws/presence` 子协议，一套是混在主 `/ws` 里的 `online/offline/pong`
- 对桌面端而言，前者是完全的死路径；协议能力和服务端复杂度都已经超出了真实客户端使用面
- 这会持续制造认知负担：读代码的人会误以为 presence 是一个正式独立子协议，但桌面主产品根本没有这条连接模型

建议：

- 如果桌面端不打算接入独立 presence socket，就应考虑下线 `/ws/presence` 或至少把它明确标记成未使用/保留接口
- 如果要保留独立 presence 子协议，就需要补齐桌面端连接与消费模型，而不是继续依赖主 `/ws` 里的部分 presence 广播
- 同步收口协议和架构文档，避免继续把“桌面未使用的子协议”描述成当前正式能力

### F-092：服务端 `online` 广播按“每条新连接”触发，而 `offline` 只按“最后一条连接断开”触发，presence 语义前后不对称

状态：已修复（2026-04-14）

修复说明：

- 已移除 `online/offline` 用户级 presence fanout，不再保留前后不对称的半实现边沿语义
- 登录替换 / logout 继续通过正式 `force_logout` 控制事件完成运行时切换，不再额外广播未消费的 offline 事件
- 相关协议文档已从 presence 能力改为连接注册 / fanout 基础设施边界

现状：

- [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 在每条连接首次 `auth` 成功时，只要当前连接之前还没认证过，就会广播一次 `online`
- [presence_ws.py](/D:/AssistIM_V2/server/app/websocket/presence_ws.py) 也会在每条 `/ws/presence` 连接成功绑定用户后立即广播一次 `online`
- 但底层 [hub.py](/D:/AssistIM_V2/server/app/realtime/hub.py) 对 `offline` 的定义却是“用户最后一条连接消失时才返回 `became_offline=True`”，随后服务端才广播 `offline`
- 也就是说，`online` 不是按“用户首次上线”广播，而是按“每新增一条连接”广播；`offline` 却是按“最后一条连接离线”广播

证据：

- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\server\app\websocket\presence_ws.py](D:\AssistIM_V2/server/app/websocket/presence_ws.py)
- [D:\AssistIM_V2\server\app\realtime\hub.py](D:\AssistIM_V2/server/app/realtime/hub.py)

影响：

- 只要一个用户打开第二个连接、重连，或未来同时接入 `/ws` 与 `/ws/presence`，其它订阅方就会收到重复 `online` 边沿
- 但对应的 `offline` 只有在最后一条连接断开时才会出现，导致 presence 事件语义天然不平衡
- 这会让任何真正消费 `online/offline` 的客户端都更难正确维护在线态，也说明这套 presence 设计还没有经过成熟验证

建议：

- 把 `online` 也收口成“用户从无连接到有连接”的首次上线广播，和 `offline` 保持同一层级的边沿语义
- 如果确实需要“新连接建立”语义，应单独定义连接级事件，不要复用用户级 `online`
- 在保留 `/ws/presence` 的前提下补测试，覆盖多连接/重连场景下 `online/offline` 的边沿一致性

### F-093：`contact_refresh` 已经是正式实时事件，但协议文档完全没建模，且它走的是一套旁路语义

状态：已修复（2026-04-14）

修复说明：

- `contact_refresh` 已补入 `realtime_protocol.md` 当前事件清单和 payload contract
- 文档明确它是联系人域刷新提示，不进入 `history_events`
- `F-096` 同步补了 reconnect 后联系人域权威 reload，补齐断线窗口补偿策略

现状：

- 服务端 [friends.py](/D:/AssistIM_V2/server/app/api/v1/friends.py) 会在好友申请创建、接受、拒绝、删除等动作后广播 `contact_refresh`
- 桌面端 [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 也有正式 consumer：收到后发出 `ContactEvent.SYNC_REQUIRED`
- 但 [realtime_protocol.md](/D:/AssistIM_V2/docs/realtime_protocol.md) 完全没有列出 `contact_refresh`
- 这条事件使用的也不是文档当前强调的 `session_seq/event_seq` 模型，而是直接构造 `{\"type\": \"contact_refresh\", \"seq\": 0, ...}` 的旁路 payload

证据：

- [D:\AssistIM_V2\server\app\api\v1\friends.py](D:\AssistIM_V2/server/app/api/v1/friends.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2/docs/realtime_protocol.md)

影响：

- 这说明当前实时协议已经不只是“文档列了但客户端没接”，还存在反过来的情况：真实主链路已经依赖的事件，协议文档根本没描述
- 对维护者来说，联系人域的实时刷新目前是一条 undocumented side channel，很容易在后续收口 WebSocket/事件模型时被遗漏
- 它也进一步说明当前 WS 事件没有统一的正式分类边界：聊天/会话事件走一套、联系人刷新又旁路走一套

建议：

- 把 `contact_refresh` 明确纳入实时协议文档，说明它属于联系人域旁路刷新事件，还是要收口进更正式的事件模型
- 如果它会长期保留，应给出稳定字段契约和是否进入补偿模型的明确说明
- 否则就应考虑把联系人域实时刷新统一并入现有事件建模，而不是继续维持 undocumented transport event

### F-094：`force_logout` 已经是正式控制事件，但协议文档完全没建模，而应用顶层又明确依赖它

状态：已修复（2026-04-14）

修复说明：

- `force_logout` 已补入实时协议文档，包含 `session_replaced/logout` reason 枚举和客户端 auth-loss 行为
- 服务端改为直接使用共享 `ws_message()` 构造控制事件，不再从 presence helper 旁路引入
- 架构文档已把强制退出列为 WebSocket 控制事件

现状：

- 服务端 [auth.py](/D:/AssistIM_V2/server/app/api/v1/auth.py) 会在 `session_replaced` 和 `logout` 两种场景下向在线连接发送 `force_logout`
- 客户端应用顶层 [main.py](/D:/AssistIM_V2/client/main.py) 也专门旁路消费 `force_logout`，并把它当作会打断 authenticated runtime 的 transport control message
- 但 [realtime_protocol.md](/D:/AssistIM_V2/docs/realtime_protocol.md) 完全没有列出 `force_logout`
- [architecture.md](/D:/AssistIM_V2/docs/architecture.md) / [backend_architecture.md](/D:/AssistIM_V2/docs/backend_architecture.md) 也只泛泛提“实时通知”，没有把这类跨账号/跨会话的强制退出控制消息建成正式协议能力

证据：

- [D:\AssistIM_V2\server\app\api\v1\auth.py](D:\AssistIM_V2/server/app/api/v1/auth.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2/docs/realtime_protocol.md)
- [D:\AssistIM_V2\docs\architecture.md](D:\AssistIM_V2/docs/architecture.md)
- [D:\AssistIM_V2\docs\backend_architecture.md](D:\AssistIM_V2/docs/backend_architecture.md)

影响：

- 这说明应用顶层当前已经依赖一个 undocumented control event 来驱动最关键的认证态切换之一
- 后续任何人只看协议文档，都不会知道 `force_logout` 是一个必须兼容、必须消费的正式消息类型
- 这也会直接放大前面 `F-085/F-086` 的问题，因为现在不仅实现没收口，连协议边界本身都没被正式记录

建议：

- 把 `force_logout` 明确纳入实时协议文档，说明 payload、reason 枚举、客户端预期行为以及是否属于 auth-loss 状态机的一部分
- 同时把 `session_replaced`、`logout` 等 reason 收口成正式枚举，不要继续让控制语义散落在实现代码里
- 补协议一致性检查，确保应用顶层依赖的 transport control event 都在文档中有正式定义

### F-095：`user_profile_update / group_profile_update / group_self_profile_update` 已经是当前实时事件，但协议文档没有显式事件定义

状态：已修复（2026-04-14）

修复说明：

- 三类 profile update 已补入 `realtime_protocol.md` 当前事件清单和 payload 示例
- 文档已区分 `user_profile_update` 的 `profile_event_id` 与 group profile event 的 `event_seq/history_events` 语义
- 说明已与本轮 `F-793` 到 `F-797` 的 user-scoped profile payload 保持一致

现状：

- 服务端 [users.py](/D:/AssistIM_V2/server/app/api/v1/users.py) 会广播 `user_profile_update`
- 服务端 [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 会广播 `group_profile_update` 和 `group_self_profile_update`
- 桌面端 [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 已经把这三类事件作为正式输入处理，并继续桥接到会话 UI 和联系人 UI
- 但 [realtime_protocol.md](/D:/AssistIM_V2/docs/realtime_protocol.md) 的“3.2 在线状态”和“3.5 状态事件”都没有把这三类类型列为当前事件，也没有给出 payload 结构

证据：

- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2/server/app/api/v1/users.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\docs\realtime_protocol.md](D:\AssistIM_V2/docs/realtime_protocol.md)

影响：

- 这三类事件已经不是实现细节，而是桌面端当前会话显示、群资料显示、联系人视图同步的正式实时输入
- 协议文档缺失它们，会直接误导后续联调、测试和重构，因为维护者看不到这些事件的存在和字段契约
- 它也说明协议文档当前“当前已存在的事件”清单已经明显落后于真实实现

建议：

- 把这三类事件正式补进协议文档，至少定义 type、核心 payload 字段、是否进入 `event_seq/history_events` 模型
- 同时把它们放回“当前已存在的事件”清单，而不是只在实现代码和 tests 里隐式存在
- 补协议一致性检查，确保桌面端正式消费的实时事件类型都能在协议文档中找到定义

### F-096：联系人域实时刷新没有补偿模型，`contact_refresh` 在断线窗口里丢失后只能靠手动 reload 恢复

状态：已修复（2026-04-14）

修复说明：

- `ContactInterface` 已订阅 `ConnectionManager` 状态变化，连接从非 connected 回到 `CONNECTED` 后自动触发联系人域 `reload_data()`
- 文档已明确 `contact_refresh` 不写入 `history_events`，断线窗口由 reconnect 后权威 reload 补偿
- 已补 UI 边界测试覆盖联系人页 reconnect reload 绑定

现状：

- 服务端 [friends.py](/D:/AssistIM_V2/server/app/api/v1/friends.py) 的联系人变更只广播即时 `contact_refresh`，没有像聊天/群资料那样写入 `history_events`
- 客户端 [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 收到 `contact_refresh` 后，只是发一个 `ContactEvent.SYNC_REQUIRED`
- 真正消费这条事件的只有 [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py)；它会在事件到达时调用 `reload_data()`
- 但联系人页本身没有任何连接状态监听，也没有 reconnect 后自动 reload 逻辑；断线期间错过的 `contact_refresh` 不会通过 `history_events` 回放，也不会在重连后自动补一次
- 联系人页切换标签只会重建当前内存列表，不会自动重新拉远端；真正的全量刷新只能靠显式 `reload_data()`

证据：

- [D:\AssistIM_V2\server\app\api\v1\friends.py](D:\AssistIM_V2/server/app/api/v1/friends.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 如果用户在联系人页打开期间经历一次断线，而这段时间恰好发生好友申请、好友关系变更等联系人域实时事件，联系人页会继续停留在旧状态
- 这类遗漏不会像消息/群资料那样在 reconnect 补偿后自动修正，除非用户手动触发联系人页 reload
- 这说明联系人域当前还没有成熟稳定的“实时通知 + 离线补偿”闭环，只是一条在线时尽力触发刷新、离线时放弃的一次性 side channel

建议：

- 要么把联系人域变更纳入正式补偿模型，至少为关键 friend-request / friendship 事件提供 reconnect replay
- 要么在重连成功后统一触发联系人域 authoritative reload，避免打开中的联系人页长期停留在断线前快照
- 补回归测试，覆盖“联系人页打开时断线，断线期间发生好友关系变更，重连后无需手动刷新即可恢复”的场景

## 3. 风险点

### R-001：设置快照边界仍然存在回退到全局 `get_settings()` 的口子

状态：已修复（2026-04-14）

修复说明：

- `MessageService.send_websocket_message()` 已成为 WS `chat_message` 的单一发送编排入口
- 该入口一次性完成 session 可见性校验、成员加载、message create、sender ACK 视图和 recipient 视图序列化
- `chat_ws` 不再先查 `member_ids`、再调用发送 service、再按 `message_id` 回查消息
- WS message payload 直接使用 service canonical `created_at/updated_at` 字段，不再由 gateway 补旧 `timestamp` 同义字段

原状态：风险

现状：

- 文档已经要求 HTTP / WebSocket 请求链路优先读取 `app.state.settings`
- 但多个 service 构造器仍保留 `settings or get_settings()` 回退
- 目前仍有调用点直接实例化 `AuthService(db)`、`CallService(db)`、`AvatarService(db)` 而未显式传入 request / websocket settings

证据：

- [D:\AssistIM_V2\server\app\services\auth_service.py](D:\AssistIM_V2\server\app\services\auth_service.py)
- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2\server\app\services\call_service.py)
- [D:\AssistIM_V2\server\app\services\file_service.py](D:\AssistIM_V2\server\app\services\file_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2\server\app\services\avatar_service.py)
- [D:\AssistIM_V2\server\app\api\v1\auth.py](D:\AssistIM_V2\server\app\api\v1\auth.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2\server\app\websocket\chat_ws.py)

风险：

- 当前部分路径虽然尚未立刻出错，但会持续放大“配置快照”和“全局缓存设置”混用的风险
- 一旦后续这些 service 新增更多依赖配置的行为，就容易重新引入 app factory 配置穿透失败问题

建议：

- 对需要运行时配置的 service，优先去掉隐式全局 fallback
- 在 HTTP / WS 入口统一显式传递 settings snapshot

### R-002：断线补偿查询按会话逐个拼接 OR 条件，扩展性风险较高

状态：已修复（2026-04-14）

修复说明：

- 客户端 `MessageManager._process_edit()` / `_process_recall()` 不再要求本地 DB 已经存在原消息
- 当离线 `history_events` 只回放 mutation event、没有本地原消息缓存时，客户端会按 event 中的 `session_id/message_id/user_id/content/status/session_seq` 构造本地权威占位消息并继续落库
- recall 事件会在缺失原消息时生成 viewer-specific recall notice，而不是直接 warning 后丢弃
- 已补 `test_message_manager_replays_history_mutations_without_cached_message`

原状态：风险

现状：

- `MessageRepository.list_missing_messages_for_user()` 会为每个会话拼一段 `session_id = ? AND session_seq > ?`
- `MessageRepository.list_missing_events_for_user()` 对共享事件和私有事件也采用类似做法
- 当前单机和中小数据量下可以工作，但 SQL 规模会随会话数线性膨胀

证据：

- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2\server\app\repositories\message_repo.py)

风险：

- 会话数量增加时，SQL 文本长度、执行计划复杂度和数据库优化难度都会上升
- 这类实现通常在功能验证阶段可接受，但不适合作为长期稳定方案

建议：

- 后续可以考虑把游标输入正规化为临时表、CTE、VALUES 表达式或更明确的 join 方案
- 至少应把这类查询标记为“当前基线可接受，但需在规模增长前收口”的性能债务

### R-003：WebSocket 发送主链路存在重复查会话、重复校验成员和重复取消息的冗余查询

状态：已修复（2026-04-14）

修复说明：

- HTTP edit / recall 成功后，发起端仍以 HTTP 响应作为本地权威更新来源
- 服务端 `/messages/{message_id}` edit 与 `/messages/{message_id}/recall` fanout 已改为排除 actor 用户，只广播给其它成员
- 这样发起者当前设备不会再收到同一 edit/recall 的完整回广播并重复走 `_process_edit()` / `_process_recall()`
- 已补 `test_http_edit_and_recall_do_not_broadcast_back_to_actor_user`

原状态：风险

现状：

- `chat_ws` 在处理 `chat_message` 时，会先调用一次 `get_session_member_ids()`
- 随后原 `MessageService.send_ws_message()` 又会检查 session 是否存在、再次校验 membership，并在 `_normalize_message_extra()` 中再次读取 session
- 消息创建后，WebSocket 层又重新按 `message_id` 回查一次消息，再为每个接收者序列化视图

证据：

- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2\server\app\websocket\chat_ws.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2\server\app\services\message_service.py)

风险：

- 当前实现逻辑正确，但每条 WebSocket 消息都会多次命中 session / member / message 查询
- 这会直接增加发送延迟和数据库负载，也让发送主链路更难继续演进到高频消息场景

建议：

- 把“加载 session、校验 membership、取 member_ids、创建 message、产出收件人视图”收敛到单个 service 编排入口
- 避免 WebSocket Gateway 和 Service 同时做相同的存在性与权限判断

### R-004：已读回执在客户端同时走 HTTP 持久化和 WS `read_ack`，实现重复且语义不统一

状态：已修复（2026-04-14）

修复说明：

- 客户端 `MessageManager.send_read_receipt()` 已收敛为只调用 HTTP `/messages/read/batch`
- `ConnectionManager.send_read_ack()` 已删除
- 服务端聊天 WebSocket 不再接受 `read_ack/read`，这类消息统一返回 `unsupported message type`
- `/messages/read/batch` 继续负责持久化 read cursor 并广播 canonical `read` event
- `docs/realtime_protocol.md` 已明确“已读持久化只走 HTTP，聊天 WS 不接受 `read_ack/read`”

原状态：风险

现状：

- 客户端 `MessageManager.send_read_receipt()` 会先调用 HTTP `/messages/read/batch`
- 随后同一逻辑又发送一次 WebSocket `read_ack`
- 但 HTTP 路径本身已经会持久化已读并广播 `read` 事件
- 同仓库内，消息发送走 WS，编辑 / 撤回走 HTTP，已读又走 HTTP + WS 双通道，实时命令边界不一致

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)
- [D:\AssistIM_V2\client\services\chat_service.py](D:\AssistIM_V2\client\services\chat_service.py)
- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2\server\app\api\v1\messages.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2\server\app\websocket\chat_ws.py)

风险：

- 每次已读都会产生两次网络请求和两条服务端处理链路，属于明确的冗余实现
- HTTP 与 WS 两条路径的广播、错误处理和可观测性并不完全对齐，后续继续演进时更容易出现行为漂移
- 这类“双写式实时命令”会增加排障成本，也会模糊正式的一致性边界

建议：

- 二选一收口已读主路径：要么 HTTP 持久化并负责广播，要么统一走 WS `read_ack` 再由服务端持久化 + 广播
- 为已读链路补“单通道主实现”的边界测试，避免再次出现双通道并存

### R-005：typing 入口仍存在 HTTP / WS 双实现，边界不统一

状态：已修复（2026-04-14）

修复说明：

- 已删除 HTTP `POST /api/v1/sessions/{session_id}/typing`
- 已删除 `SessionTypingRequest`，typing 正式入口收敛为聊天 WebSocket `typing`
- 服务端 WS `typing` 仍由同一处负责成员解析和排除发送连接 fanout
- `docs/realtime_protocol.md` 已明确 typing 只属于聊天 WebSocket 客户端发送命令

原状态：风险

现状：

- WS `typing` 广播会排除当前连接
- HTTP `POST /api/v1/sessions/{session_id}/typing` 与 WS `typing` 仍然是两套实现路径
- 两条路径的 fanout 和排除规则不在同一处收口

证据：

- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2\server\app\websocket\chat_ws.py)
- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2\server\app\api\v1\sessions.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client\ui\windows\chat_interface.py)

风险：

- typing 能力在 HTTP / WS 两条入口下仍然维护两套逻辑，后续很容易继续漂移
- 当前已确认的“回发给发送者”问题只是其中一处外显症状

建议：

- typing 最好收敛到单一正式入口，由同一处负责成员解析与 fanout
- 如果 HTTP typing 只是过渡入口，应在文档或代码中明确其边界，避免新调用方误用

### R-006：通话状态基础设施仍直接绑定进程内单例实现，和文档期望的“可替换边界”还有距离

状态：风险

现状：

- 架构文档已经明确要求活跃通话状态通过可替换基础设施边界承载，不应把“谁正在通话”写死在某个 WS handler 私有结构中
- 但当前实现仍是 `server/app/realtime/call_registry.py` 里的进程内全局单例 `InMemoryCallRegistry`
- `CallService` 虽然支持注入 `registry`，但默认仍直接取全局 `get_call_registry()`，仓库里也没有第二种实现或统一抽象接口

证据：

- [D:\AssistIM_V2\server\app\realtime\call_registry.py](D:\AssistIM_V2\server\app\realtime\call_registry.py)
- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2\server\app\services\call_service.py)
- [D:\AssistIM_V2\docs\backend_architecture.md](D:\AssistIM_V2\docs\backend_architecture.md)

风险：

- 当前单机基线能工作，但多实例、热重启、独立 worker 或外部 signaling 扩展时会很难平滑演进
- 这类“已经在文档里承诺可替换、实现却仍是全局单例”的状态，后续最容易演化成技术债务

建议：

- 至少先把 call registry 抽到正式接口边界，并把默认内存实现作为其中一个 provider
- 在服务层和网关层避免继续直接依赖 `get_call_registry()` 这种全局单例入口

### R-007：离线 `history_events` 回放对本地消息缓存存在隐式依赖

状态：风险

现状：

- 服务端断线补偿测试已经覆盖“`history_messages` 为空，但 `history_events` 仍返回 `message_recall` / `message_delete`”的场景
- 客户端 `MessageManager._process_recall()` / `_process_edit()` 当前要求本地数据库里先存在原消息；找不到就直接记录 warning 并返回
- 当前客户端测试只覆盖了“本地已有原消息时”的回放路径，没有覆盖“只有 mutation event、没有本地消息缓存”时应如何恢复权威状态

证据：

- [D:\AssistIM_V2\server\tests\test_chat_api.py](D:\AssistIM_V2\server\tests\test_chat_api.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)
- [D:\AssistIM_V2\client\tests\test_message_manager.py](D:\AssistIM_V2\client\tests\test_message_manager.py)

风险：

- 如果本地缓存被清理、裁剪或不完整，mutation event 可能无法把本地状态恢复到服务端权威结果
- 这类问题平时不容易暴露，但一旦出现，会直接体现在离线回放、重连恢复和预览状态错乱上

建议：

- 明确 mutation event 回放是否允许依赖本地已有原消息；如果不允许，就需要补“缺失原消息时的回退恢复”策略
- 为 `history_events` 增加负面测试，覆盖“无本地原消息缓存”的 edit / recall / delete 回放行为

### R-008：HTTP 编辑/撤回对发送者侧形成“本地 optimistic 更新 + 服务端回广播”的双处理链路

状态：风险

现状：

- 桌面端 `MessageManager.edit_message()` / `recall_message()` 在 HTTP 请求成功后，会先直接更新本地数据库并发出本地 `MessageEvent`
- 服务端 HTTP `/messages/{message_id}` 与 `/messages/{message_id}/recall` 又会向会话成员广播 `message_edit` / `message_recall`
- 发送者自己的在线客户端因此会再次收到同一变更，并再走一遍 `_process_edit()` / `_process_recall()`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)
- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2\server\app\api\v1\messages.py)

风险：

- 当前看起来大多是幂等的，但会带来重复数据库写入、重复 UI 刷新和更复杂的排障路径
- 这和已读链路的双通道问题本质相似，说明“谁负责本地确认、谁负责广播回显”的边界还没完全收口

建议：

- 明确发送者侧到底采用“HTTP 响应即权威结果”还是“统一等服务端广播回显”其中一种
- 若保留 optimistic 更新，应至少避免把同一变更再次完整回广播给原发送者，或在客户端做更明确的去重

### R-009：本地隐藏会话的 tombstone 把 `updated_at` 也视为活动时间，远端资料变更可能在下次刷新时把会话误复活

状态：风险

现状：

- 桌面端 `SessionManager.remove_session()` 会把当前会话的 `_session_activity_timestamp(session)` 记为本地 `hidden_at`
- `_session_activity_timestamp()` 当前取 `last_message_time`、`updated_at`、`created_at` 的最大值；`refresh_remote_sessions()` 重新拉远端会话后，只要新的活动时间大于 `hidden_at`，就会把该会话重新放回列表并清掉隐藏 tombstone
- 服务端群资料更新链路里，`update_my_group_profile()` 会在只修改 `group_note` / `my_group_nickname` 时调用 `SessionRepository.touch_without_commit(group.session_id)`，直接推进会话 `updated_at`，但这并不是新的聊天消息
- `refresh_remote_sessions()` 又是登录后 warmup 和手工“刷新会话快照”的正式入口，因此这种 metadata-only 更新会在下次远端刷新时生效

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client\managers\session_manager.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client\main.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2\client\ui\controllers\chat_controller.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2\server\app\services\group_service.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2\server\app\repositories\session_repo.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2\server\app\services\session_service.py)

风险：

- “删除会话=仅当前设备隐藏”本来已经和服务端全局删除语义分叉；如果本地 tombstone 还会因为备注、群昵称、群资料等非消息变更失效，用户会看到会话无缘无故重新出现
- 这会让“什么算新的会话活动”继续漂移：当前既不是严格按新消息恢复，也不是显式按服务端成员级 hide/archive 模型恢复

建议：

- 明确本地隐藏会话的复活条件；如果产品语义是“有新消息再回来”，tombstone 应只和消息时间或 `session_seq/event_seq` 对齐，不应直接把 `updated_at` 当作恢复依据
- 若保留“任何会话活动都可复活”的设计，应至少把这一点写进产品/架构文档，并补针对 group profile / self profile 更新的边界测试

### R-010：通话结果消息去重集合 `_call_result_messages_sent` 是进程级只增不减的状态

状态：closed（2026-04-14）

修复记录：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 已把 `_call_result_messages_sent` 改成带 TTL 和容量上限的 `OrderedDict`
- `_schedule_call_result_message()` 发送前会先执行 `_prune_call_result_messages_sent()`，长期运行时不会再无限累积通话结果去重状态

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 用 `_call_result_messages_sent: set[tuple[str, str]]` 避免同一通话结果系统消息重复发送
- 当前逻辑只会 `add(dedupe_key)`，没有按 `call_id`、时间窗口或会话生命周期回收的路径
- 对话窗口销毁前，这个集合会随通话次数持续增长

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client\ui\windows\chat_interface.py)

风险：

- 单次增长很小，但这是典型的“进程级 dedupe 状态无淘汰”实现，长时间运行后会持续累积
- 如果将来通话结果消息种类增多、桌面端长期不重启，排障时也会更难区分“正常去重”与“历史状态残留”

建议：

- 至少按 `call_id` 终态收敛后清理 dedupe 项，或给该集合加一个合理的容量/时间窗口淘汰策略
- 为通话系统消息去重补生命周期测试，避免它继续演化成隐性常驻状态

### R-011：入站消息去重缓存不按会话清理，删除后短时间回流的同一 `message_id` 可能被静默丢弃

状态：closed（2026-04-14）

修复记录：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `_recent_incoming_message_ids` 已改成记录 `(timestamp, session_id)`
- `remove_session_local_state(session_id)` 现在会按 `session_id` 清理 inflight/recent incoming dedupe、发送队列和附件预取状态

现状：

- `MessageManager` 用 `_incoming_message_inflight` 和 `_recent_incoming_message_ids` 对实时 `chat_message` 做 300 秒去重
- 这两份状态当前只在 `MessageManager.close()` 时整体清空，没有按 `session_id` 的清理路径
- 如果本地删除/隐藏会话后，服务端在短时间内又把同一条消息以实时 `chat_message` 形式重新投递，`_reserve_incoming_message()` 会直接返回 `False`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

风险：

- 平时不容易触发，但在断线重连、服务端重投递或本地删会话后短时间回流的边界场景下，客户端可能把应重新接收的消息静默当作“最近已处理过”
- 这类风险和 `F-029/F-034` 一样，本质上都来自“会话生命周期变化时，本地 per-message/per-session 状态没有同步驱逐”

建议：

- 删除/隐藏会话时至少清理该会话已知消息的入站去重状态，或缩小去重作用域，避免跨会话生命周期保留
- 为“本地删会话后短时间实时回流同一消息”的场景补边界测试

### R-012：本地删除会话不会清理 E2EE group sender-key 状态，历史恢复导出仍可能携带已删会话的密钥材料

状态：closed（2026-04-14）

修复记录：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 删除会话时已联动调用 `E2EEService.remove_session_local_state(session_id)`
- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 会同步清理 `e2ee.group_session_state` 和 history recovery 中该 `session_id` 的 group sender-key 状态

现状：

- `SessionManager.remove_session()` 当前只负责隐藏会话并删除本地 session/message/read-cursor 数据，没有和 `E2EEService` 做任何按 `session_id` 的状态清理联动
- `E2EEService` 会把群聊 sender-key 状态持久化到 `app_state` 的 `e2ee.group_session_state`，键就是 `session_id`
- 后续 `export_history_recovery_package()` 会遍历全部 `group_session_state`，把每个 `session_id` 关联的 sender keys 都打进导出包
- 这意味着用户在当前设备“删除会话/清除本地记录”后，该会话的群聊 sender-key 仍可能继续留在本地，并被后续恢复导出流程带出

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)
- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

风险：

- 这会让“清除本地记录”的实际边界继续漂移：数据库消息虽然删了，但与该会话绑定的本地密钥材料仍保留并可被导出
- 如果产品语义本来希望“删除会话只隐藏列表但保留安全状态”，那就需要明确写清；否则这会形成隐私预期和真实本地残留之间的偏差

建议：

- 明确本地删除会话是否应该一并清理 `group_session_state` 中该 `session_id` 的 sender-key 材料
- 如果决定保留这些密钥状态，应在文档中说明“删除会话不等于清理 E2EE 恢复材料”，并补对应的边界测试

### R-013：`CallManager` 的 `_timing_origins` 在 manager close 时不会兜底清理，异常退出的 in-flight call 可能残留 timing 状态

状态：closed（2026-04-14）

修复记录：

- `CallManager.close()` 已清空 `_timing_origins`
- terminal/busy/failed 仍按 `call_id` 即时清理，close 作为 logout/shutdown 的兜底
- 已补 `test_call_manager_close_clears_authenticated_user_context`

现状：

- `CallManager` 用 `_timing_origins: dict[str, float]` 给每个 `call_id` 记录日志时间基线
- 正常终态事件当前已经会在 `_handle_terminal_event()` / `_handle_busy()` 里按 `call_id` 清理这份 map
- 但 `CallManager.close()` 只会清 `_active_call` 和 timeout task，不会清 `_timing_origins`
- 因此如果应用在 still-active / still-ringing 的通话过程中 logout、forced logout 或直接关闭 runtime，对应 `call_id` 的 timing 状态仍会留在进程内

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2\client/managers/call_manager.py)

风险：

- 当前风险主要集中在异常生命周期上，而不是每个正常结束的通话都会泄漏
- 但它仍然属于“进程级 timing 状态缺少 close 兜底”的实现，异常退出路径一多，就会积累难以追踪的残留状态

建议：

- 在 `CallManager.close()` 里补一层 `_timing_origins.clear()` 或按当前 active call 做定向清理
- 为“通话进行中 logout / forced logout / runtime teardown”的路径补 timing 状态回归测试

### R-014：authenticated runtime 依赖进程级单例原地复用，logout 正确性建立在“每个组件都手工清干净”之上

状态：已修复（2026-04-13）

修复记录：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 authenticated teardown 现在覆盖 chat/message/session/discovery/connection/websocket/sound/call/search 等账号域组件；相关 controller/manager/service 的 `close()` 会在成功关闭后退休模块级 singleton，下一次登录会创建新的 runtime 对象。

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_teardown_authenticated_runtime()` 会调用若干组件的 `close()`，但并不会把这些模块级单例重置为 `None`
- `ChatController`、`ConnectionManager`、`MessageManager`、`SessionManager`、`AuthController` 等都采用 `get_*()` 返回模块级 `_instance` 的模式；`close()` 后下一次登录仍会复用同一个 Python 对象
- 还有一些全局对象甚至没有正式 teardown 钩子，例如 [discovery_controller.py](/D:/AssistIM_V2/client/ui/controllers/discovery_controller.py) 的 `DiscoveryController` 和 [search_manager.py](/D:/AssistIM_V2/client/managers/search_manager.py) 的 `SearchManager`
- 这意味着“退出当前账号”并不是销毁一整套用户运行态，而是让旧对象继续活着，再靠各自的 `clear()/close()/set_user_id("")` 去尽量擦除旧状态

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2\client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2\client/ui/controllers/chat_controller.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2\client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2\client/managers/search_manager.py)
- [D:\AssistIM_V2\client\ui\controllers\discovery_controller.py](D:\AssistIM_V2\client/ui/controllers/discovery_controller.py)

风险：

- 这是一个架构层风险，而不是单点 bug；它会持续放大 logout/切账号边界上的遗漏成本
- 当前已经暴露出来的 `F-045/F-046/F-047/F-048/F-049` 本质上都和这件事有关：只要某个单例少清一个缓存、一个任务、一个 listener，下一账号就会继承上一账号状态
- 这会让“设计是否成熟、稳定、可验证”这一条打折，因为正确性依赖分散在许多 `close()/clear_session()/set_user_id()` 细节里，而不是靠更强的生命周期边界保证

建议：

- 明确区分真正允许进程级复用的基础设施和必须按账号重建的 authenticated runtime
- 对后者，优先考虑在 logout 后直接重置模块级单例并在下次登录时重建对象图，而不是长期沿用“关闭后复用同一实例”的模式
- 至少先把没有 teardown 钩子但持有用户态缓存的单例统一纳入 logout 审计清单，并补“切账号后不得保留上一账号内存态”的回归测试

### R-015：正常 logout 的流程顺序是“先 clear_session 清本地状态，再 teardown runtime”，会把后台任务竞争窗口带进正式支持路径

状态：已修复（2026-04-13）

修复记录：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 logout/auth-loss flow 已改成先 `quiesce_authenticated_runtime()`，取消 warmup、让 shell 进入 runtime transition、关闭 runtime 组件，再执行 auth/session 清理；本地 chat-state 不再在旧 runtime 仍活跃时先被清空。

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_perform_logout_flow()` 会先执行 `await auth_controller.logout()`，然后才执行 `_teardown_authenticated_runtime()`
- 而 [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `logout()` 在 `finally` 里一定会调用 `clear_session()`
- `clear_session()` 会立即执行 `_reset_local_chat_state()`，也就是先清本地数据库和 sync cursor
- 但此时 `SessionManager`、`MessageManager`、`ConnectionManager`、`ChatController` 等 authenticated runtime 组件还没有被关闭；它们要等下一步 `_teardown_authenticated_runtime()` 才停止

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2\client/ui/controllers/auth_controller.py)

风险：

- 这会把“清库之后，后台任务又把旧状态写回来”的竞争窗口变成正常 logout 的正式流程问题，而不只是 forced logout 的边界问题
- 现有的 [F-047](D:\AssistIM_V2\docs\review_findings.md)、[F-048](D:\AssistIM_V2\docs\review_findings.md)、[F-049](D:\AssistIM_V2\docs\review_findings.md) 已经分别证明了 message/session/http refresh 这些链路在 clear 之后仍可能继续运行
- 也就是说，当前 logout 顺序本身就在放大这些问题，而不是只被个别实现细节偶然触发

建议：

- 把正常 logout 的顺序调整为“先阻断/关闭 authenticated runtime，再清持久化聊天状态”，至少要先停掉会继续写库或继续收包的后台组件
- 如果必须先 clear_session，也应先进入更强的全局 quiesce 状态，确保后续没有 runtime 任务还能继续落库或刷新 auth/session 状态

### R-016：普通 logout 与应用 shutdown 的 teardown 覆盖面不一致，多个进程级单例会跨切账号原地存活

状态：已修复（2026-04-13）

修复记录：

- 普通 logout 与 shutdown 已共享同一组账号域 close contract：AuthController、DiscoveryController、SearchManager、CallManager、Chat/Message/Session/Connection/WebSocket/Sound 等会在普通 runtime teardown 中关闭并退休 singleton；AuthController close 也会退休其持有的 auth/e2ee/user/file service singleton。

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的普通 `_teardown_authenticated_runtime()` 只关闭了 chat/message/session/connection/websocket/sound 这批组件
- 但应用整体 `shutdown()` 还会额外关闭 `AuthController` 和 `HTTPClient`
- 同时代码里仍有多类进程级单例不会在普通 logout 时被重建或清理，例如 [AuthController](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py)、[HTTPClient](/D:/AssistIM_V2/client/network/http_client.py)、[DiscoveryController](/D:/AssistIM_V2/client/ui/controllers/discovery_controller.py)、[SearchManager](/D:/AssistIM_V2/client/managers/search_manager.py)
- 这意味着“退出账号”和“退出应用”在 runtime 隔离层面并不是同一个 teardown 模型

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)
- [D:\AssistIM_V2\client\ui\controllers\discovery_controller.py](D:\AssistIM_V2/client/ui/controllers/discovery_controller.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

风险：

- 只要“切账号”不等价于“销毁并重建 authenticated runtime”，后续就会不断出现某个域忘记 clear、某个 listener 没摘、某个后台任务晚到回写的问题
- 这也是为什么目前 findings 会同时覆盖聊天、会话、通讯录、Moments、auth token 和本地 app_state，多域同时失稳并不是巧合
- 从设计成熟度看，这说明 runtime 生命周期模型还没有收口成一套可验证、可复用的正式边界

建议：

- 把“authenticated runtime”提升成显式对象边界，普通 logout 时直接整组销毁并在 relogin 后整组重建
- 在文档和代码里统一普通 logout、forced logout、shutdown 三种路径的 teardown contract，避免继续出现覆盖面不一致

### R-017：手动 logout 与 `session_replaced` forced logout 缺少顶层互斥，两个生命周期流程可能并发推进

状态：已修复（2026-04-13）

修复记录：

- [main.py](/D:/AssistIM_V2/client/main.py) 已把 logout、auth-loss、`session_replaced` forced logout 收口到顶层互斥路径：logout task、auth-loss task 和 forced-logout guard 会互相避让，旧流程不会与另一条生命周期 flow 并发重建 runtime。

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 里，用户手动退出会通过 `_on_logout_requested()` 启动一个 `_logout_task = create_task(_perform_logout_flow())`
- 但 `force_logout(reason=session_replaced)` 分支只检查 `_forced_logout_in_progress`，不会查看或取消已有 `_logout_task`
- 反过来，`_perform_logout_flow()` 也不会检查 `_forced_logout_in_progress`；它在 `auth_controller.logout()` 和 `_teardown_authenticated_runtime()` 之后仍会继续执行 `authenticate()`、`initialize()`、`show_main_window()`
- 这意味着如果“本地手动 logout”和“服务端 session_replaced”在时间上重叠，当前并没有一个统一的顶层状态机来保证只保留一条流程继续执行

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

风险：

- 两条生命周期流程可能出现一条尝试关窗退出、另一条又继续重建认证态或重新展示窗口的竞态
- 即使这个窗口较窄，它也说明当前 logout/forced logout 还没有形成成熟稳定的单一状态机，只是几条异步路径并排存在
- 这类顶层流程竞态通常很难靠局部修补兜住，后续继续加入口时还会放大复杂度

建议：

- 把普通 logout、forced logout、shutdown 收口到同一个顶层生命周期状态机，进入任一终止流时先取消其它 in-flight 顶层任务
- 至少给 `_perform_logout_flow()` 增加 forced-logout guard，并在 `session_replaced` 到来时显式取消 `_logout_task`

### R-018：初次启动与 logout 后重登的 boot 顺序不一致，`initialize()` 在重登路径上会回写一份未认证的应用级诊断快照

状态：已修复（2026-04-13）

修复记录：

- 冷启动、logout relogin、auth-loss reauth 已统一走 `authenticate() -> _continue_authenticated_runtime()`；`initialize()` 只保留 pre-auth 初始化，且不会在已有 authenticated startup security snapshot 时重置 E2EE runtime diagnostics。

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的初次启动路径是 `initialize() -> preflight -> authenticate() -> show_main_window()`
- 但普通 logout 后的重登路径是 `_perform_logout_flow() -> authenticate() -> initialize() -> show_main_window()`
- 而 `initialize()` 内部会把 `Application._e2ee_runtime_diagnostics` 直接重置为 `authenticated=False / user_id=\"\" / current_session_security=\"authentication required\"` 的默认值
- 这意味着同样是“进入一个新的 authenticated runtime”，启动与重登两条路径对应用级缓存快照的写入顺序并不一致

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2\client\main.py)

风险：

- 即使当前这份 app 级诊断快照主要被 `Application` 自己和测试使用，这种顺序分叉也会让后续任何依赖这些缓存快照的诊断 UI、守卫逻辑或启动检查变得不稳定
- 它也说明“重建 authenticated runtime”目前并没有一条单一、可验证的正式 boot contract，而是启动和重登各走一套顺序
- 这类顶层顺序分叉通常会继续滋生“某个缓存先被认证更新，随后又被初始化默认值覆盖”的问题

建议：

- 统一初次启动与重登的 boot contract，避免一条路径 `authenticate` 在前、一条路径 `initialize` 在前
- 如果保留当前结构，至少要避免 `initialize()` 在重登路径上覆盖已认证后的应用级诊断缓存，并补一条“relogin 后 app 级 diagnostics 仍与当前账号一致”的回归测试

### R-019：`ChatController` 会跨账号保留上一登录代的 ICE/TURN 缓存，通话运行态边界没有真正按账号收口

状态：已修复（2026-04-13）

修复记录：

- [chat_controller.py](/D:/AssistIM_V2/client/ui/controllers/chat_controller.py) 的 `close()` 现在会关闭 CallManager、清空 `_call_service`、把 `_call_ice_servers` 还原到本地 fallback 并将 `_call_ice_servers_loaded=False`；回归测试覆盖切账号 close 后不会保留上一账号 TURN 凭据缓存。

现状：

- [chat_controller.py](/D:/AssistIM_V2/client/ui/controllers/chat_controller.py) 会在内存里缓存 `_call_ice_servers` 和 `_call_ice_servers_loaded`
- `refresh_call_ice_servers(force_refresh=False)` 在缓存已加载后会直接返回内存值，不再重新请求服务端
- 但 `ChatController.close()` 当前只关闭 `CallManager`，不会重置 `_call_ice_servers`、`_call_ice_servers_loaded` 或 `_call_service`
- 服务端 [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `/calls/ice-servers` 响应本身又是按认证用户生成的；在 shared-secret TURN 模式下，用户名直接编码了 `expires_at:user_id`
- 同时 [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 创建 `CallWindow` 时会直接消费 `get_call_ice_servers()` 返回的当前缓存

证据：

- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server\app\services\call_service.py)

风险：

- 当前主链路里的发起/接听大多会 `force_refresh=True`，所以这还不是一个已证实的直接用户可见 bug
- 但从 runtime 边界看，上一账号的 TURN 凭据和 ICE 配置确实会在 logout 后继续留在 `ChatController` 内存里，直到后续某条通话路径显式强刷
- 这说明通话运行态还没有真正按账号隔离；未来只要有任何非强刷的通话入口或恢复路径读到这份缓存，就会把跨账号凭据残留变成真实问题

建议：

- 在 `ChatController.close()` 或 logout teardown 中显式清空 `_call_ice_servers`、`_call_ice_servers_loaded` 和 `_call_service`
- 为“切账号后第一次进入通话 UI/恢复通话窗口”补回归测试，确保不会复用上一账号的 ICE/TURN 缓存

### R-020：本地 sync cursor 快照按多 key 分开提交，message/event 游标不是一个原子恢复点

状态：已修复（2026-04-13）

修复记录：

- [database.py](/D:/AssistIM_V2/client/storage/database.py) 新增 `replace_app_state()` 事务入口；[connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 `_save_sync_state()` 现在一次性写入 message/event reconnect cursors 并删除 legacy timestamp，回归测试覆盖同一 batch 保存。

现状：

- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 `_save_sync_state()` 会分别写 `last_sync_session_cursors` 和 `last_sync_event_cursors`
- 底层 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `set_app_state()` / `delete_app_state()` 又是逐 key 单独 `commit()`
- 这意味着 reconnect 所依赖的 message cursor 和 event cursor 在本地存储里并不是一个原子快照，而是两份独立提交的状态
- 前面已经确认 logout/relogin 边界和旧连接晚到响应会并发改写这些键，这会进一步放大“恢复点不一致”的风险

证据：

- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

风险：

- 一旦写入在两份 cursor 之间被打断、交错或被旧/新登录代竞争覆盖，下次恢复时就可能拿到不属于同一时刻的 message/event 游标组合
- 这会让断线补偿从一开始就站在一个不自洽的恢复点上，后续更容易触发漏补、重复补或 mutation event 与 base message 不匹配的问题
- 这说明 reconnect cursor 现在还不是一个成熟稳定的“单一恢复点”设计

建议：

- 把 reconnect cursor 收口成单条原子快照记录，至少在同一事务里完成 message/event cursor 的整组写入与删除
- 同时补“旧连接与新连接并发保存 cursor”以及“中途故障后的 cursor 恢复一致性”回归测试

### R-021：E2EE 本地持久化状态被拆成多个独立 `app_state` 键，设备重置与恢复过程缺少原子边界

状态：已修复（2026-04-13）

修复记录：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `clear_local_bundle()` 已改为一次删除整组 E2EE app_state key；`reprovision_local_device()` 会先完成远端注册，再用 `replace_app_state()` 原子替换本地 device bundle 并删除 group/history/trust 旧材料，回归测试覆盖该 batch 边界。

现状：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 把本地 E2EE 持久化状态拆成 `e2ee.device_state`、`e2ee.group_session_state`、`e2ee.history_recovery_state`、`e2ee.identity_trust_state` 四个独立键
- `clear_local_bundle()` 会按顺序逐个删除这四个键；`reprovision_local_device()` 又会在清空后先保存新的 `device_state`，再继续走远端注册
- 底层 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `set_app_state()` / `delete_app_state()` 每次都是单 key `commit()`
- 因此“当前设备身份 + 群 sender-key + history recovery + identity trust”并不是一个原子持久化对象，而是一组会在多个提交点之间过渡的状态片段

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

风险：

- 一旦设备重置、恢复导入、logout 清理或异常中断发生在这些多 key 更新中间，本地 E2EE 状态就可能落在一个“不完整但可读”的过渡状态
- 这会增加后续诊断和恢复复杂度，例如设备 bundle 已切换，但 group/history/trust 仍残留旧状态，或者反过来 bundle 已清空但恢复材料尚未一起清掉
- 这说明 E2EE 本地状态目前还不是一个成熟稳定的单一真相对象

建议：

- 把 E2EE 本地持久化收口成更少的原子对象，或至少在单一事务里完成相关 key 的整组更新/删除
- 为“reprovision/clear/import 中途失败或被打断”的路径补恢复一致性测试，验证不会留下半新半旧的本地 E2EE 状态

### F-097：通话域实时状态没有重连补偿模型，断线期间错过的终态/信令不会恢复，`active_call` 还能长期残留

状态：已修复（2026-04-14）

修复说明：

- 普通 group/session/message 序列化不再通过 `ensure_group_avatar()` 触发 `commit=False` 的 session avatar mirror 写入。

现状：

- 服务端 [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 当前对 `call_invite`、`call_ringing`、`call_accept`、`call_reject`、`call_hangup`、`call_offer`、`call_answer`、`call_ice` 全部只做即时 WebSocket fan-out
- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 也只是读取/修改进程内 [call_registry.py](/D:/AssistIM_V2/server/app/realtime/call_registry.py) 并返回 outbound payload，没有把任何通话状态写进 `history_events`，也没有提供“当前活跃通话快照”查询接口
- 客户端 [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 只通过 `_handle_ws_message()` 消费这些 live event，自身没有任何 `ConnectionManager` 状态监听、重连后 resync、或 transport 断开后的 call-state 收口逻辑
- `CallManager._active_call` 只会在收到 `call_reject` / `call_hangup` / `call_busy` / matching `error`，或主动 `close()` / `set_user_id("")` 时才被清掉；已接通通话也没有类似未应答超时那样的兜底收尾
- 上层 [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的通话窗体和 call UI 又完全依赖 `CallEvent.*` 这条 live event 流驱动

证据：

- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\server\app\realtime\call_registry.py](D:\AssistIM_V2/server/app/realtime/call_registry.py)
- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 只要 `call_hangup` / `call_reject` / `call_busy` 或关键 SDP/ICE 信令发生在断线窗口里，客户端重连后就没有任何正式补偿路径把这段状态追回来
- 这会导致本地 `active_call`、会话侧 `call_state`、通话窗体三者继续停留在旧状态；尤其是已接通或已进入 signaling 阶段的通话，没有自动超时兜底，残留时间可以非常长
- 这说明通话域目前仍然是“纯在线 live channel”，还没有达到消息域那种可恢复、可验证的一致性模型

建议：

- 明确通话域的 authoritative 恢复策略：要么把关键终态/必要 state 纳入可补偿模型，要么在 reconnect/auth-loss 时显式 fail/teardown 本地活跃通话
- 不要再让 `CallManager` 只靠 live event 驱动；至少补连接断开/重连后的 call-state 收口逻辑和对应回归测试

### F-098：联系人/群搜索缓存的实时新鲜度依赖联系人页是否开着，页外发生的联系人变更不会自动刷新本地搜索结果

状态：已修复（2026-04-14）

修复说明：

- 群成员、角色、所有权和 avatar mirror 写路径统一推进 `session.updated_at`；读路径不再偷偷改写 freshness。

现状：

- 服务端联系人域变更当前只会通过 `contact_refresh` 这类 live event 通知客户端，客户端 [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 收到后只是发出 `ContactEvent.SYNC_REQUIRED`
- 这条事件在桌面端真正的 consumer 只有 [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py)；联系人页如果没开、已销毁，或者当前没有走到 `reload_data()`，就不会触发后续 `load_contacts()` / `load_groups()`
- 而本地全局搜索 [search_manager.py](/D:/AssistIM_V2/client/managers/search_manager.py) 查的却是落盘后的 `contacts_cache` / `groups_cache`
- 这些缓存的正式刷新入口在 [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 里，只有 `load_contacts()` / `load_groups()` 才会重新 `replace_contacts_cache()` / `replace_groups_cache()`
- 也就是说，联系人域实时事件并不会直接更新搜索缓存；缓存是否变新，取决于联系人页是否恰好在线并完成一次 reload

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- 好友申请、好友备注/资料变化、群资料变化、群成员变化之后，联系人页之外的本地搜索结果可能长期停留在旧缓存
- 用户即使已经在聊天页或全局搜索面板里，也不一定能看到最新的联系人/群名称、头像、成员预览或搜索命中
- 这说明联系人域当前没有真正的“后台 authoritative cache refresh”机制，而是把全局缓存一致性绑在某个具体页面是否处于活动状态上

建议：

- 把联系人域缓存刷新从 `ContactInterface` 页面逻辑里剥离出来，收口成 controller/manager 级后台同步能力
- 至少保证 `ContactEvent.SYNC_REQUIRED` 能在无页面场景下也更新 `contacts_cache` / `groups_cache`，让搜索结果和联系人主数据保持一致
- 为“联系人页未打开时收到 `contact_refresh` / `group_profile_update`”补回归测试，验证全局搜索缓存也会更新

### F-099：群成员变更根本没有进入正式实时/补偿模型，跨端和页外视图只能靠手工刷新纠正

状态：部分修复（2026-04-14）

修复说明：

- 群 lifecycle event 已进入 history 补偿，fanout 失败不影响已提交 mutation；持久 outbox/retry 仍未引入。

现状：

- 服务端 [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 只有群资料修改会调用 `_broadcast_group_profile_update()` / `_broadcast_group_self_profile_update()`
- 但 `add_member()`、`remove_member()`、`leave_group()` 这三条正式成员变更入口当前都只是直接调用 [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 改库后返回，没有任何 realtime 广播，也没有追加 `history_events`
- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 虽然会更新成员关系、`member_version` 和群头像版本，但没有像群资料修改那样生成 `group_profile_update` 事件
- 客户端目前唯一会在 leave group 后触发联系人侧刷新的是 [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 里本端成功调用 `leave_group()` 后手工发出的 `ContactEvent.SYNC_REQUIRED(reason=\"group_membership_changed\")`
- 这意味着这条“刷新信号”既不是服务端权威广播，也不会覆盖其它设备、其它在线成员，甚至本端如果不是走这条 UI 路径也收不到

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 群加人、踢人、成员自行退群后，其它在线成员的联系人页、群列表、群成员预览、搜索缓存、会话侧成员信息都不会实时更新
- 断线期间发生的群成员变更也没有离线补偿；因为这类动作根本没进 `history_events`
- 当前群成员变化的“最新状态”实际上只能依赖后续手工 reload、重新拉群详情或某次全量快照刷新，明显偏离了项目文档强调的正式事件模型

建议：

- 把群成员变更收口成正式事件类型，至少让 `add_member/remove_member/leave_group` 和群资料更新一样进入 realtime + offline compensation 模型
- 不要再依赖 `ChatInterface` 本端手工发 `ContactEvent.SYNC_REQUIRED` 这种页面内旁路补丁来兜底领域一致性
- 补回归测试，覆盖“其它设备在线时成员变化”“断线期间成员变化后重连”两类场景

### F-100：群角色变更和所有权转移也没有正式事件，当前只有发起端页面会立即看到新角色

状态：已修复（2026-04-14）

修复说明：

- session 成员摘要不再调用 `backfill_user_avatar_state()`；读路径只用 `resolve_user_avatar_url()` 解析当前 avatar。

现状：

- 服务端 [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `update_member_role()` 和 `transfer_ownership()` 只改数据库并返回最新群快照，没有追加 `history_events`
- 对应路由 [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 也没有像群资料更新那样调用任何 `_broadcast_group_profile_update()` 或其它实时广播
- 客户端群管理主链路 [group_member_management_dialogs.py](/D:/AssistIM_V2/client/ui/windows/group_member_management_dialogs.py) 在成功后会拿 HTTP 返回值直接 `_apply_group_record(record)`，因此发起端当前页面会立刻看到角色/owner 变化
- 但这条更新是纯 request-response 本地修补；其它在线成员、本账号其它设备，以及未打开该群管理页的其它 UI 都不会收到正式实时事件

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)
- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)

影响：

- 群 owner 转移、管理员升降级之后，只有操作发生的那个客户端页面会立即变对；其它设备和其它成员的群成员列表、owner/admin 标识、可执行权限入口都会继续停留在旧状态
- 断线期间发生的角色/owner 变化也没有离线补偿，因为这类动作根本没进 `history_events`
- 这说明群治理相关动作目前仍不是正式事件模型的一部分，而是靠发起端 HTTP 返回值做局部修补

建议：

- 把角色变更和 owner 转移也纳入正式群事件模型，至少与群资料更新共享同一套 realtime + offline compensation 边界
- 不要让“发起端当前页面自己 patch 成功返回值”代替服务端权威广播
- 补回归测试，覆盖“其它在线成员看到 owner/admin 变化”和“断线重连后恢复最新角色状态”

### F-101：会话生命周期动作没有服务端正式事件，`SessionEvent.CREATED/DELETED` 当前只是本地 UI 事件名

状态：已修复（2026-04-14）

修复说明：

- direct counterpart 摘要同样只解析 avatar URL，不再在会话读取时回写对端用户 avatar 状态。

现状：

- 服务端 [sessions.py](/D:/AssistIM_V2/server/app/api/v1/sessions.py) 的 `POST /sessions/direct` 和 `DELETE /sessions/{session_id}` 都只是同步返回/执行结果，没有任何 realtime 广播，也没有写入 `history_events`
- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `create_private()` / `delete_session()` 也只是改库并返回，完全不生成类似 `session_created` / `session_deleted` 的正式事件
- 客户端 [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 里虽然会发 `SessionEvent.CREATED` / `SessionEvent.DELETED`，但它们分别来自 `add_session()` / `remove_session()` 这样的本地缓存变更，不是服务端协议下行
- 私聊创建主链路 [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `ensure_direct_session()` 也是拿 HTTP 返回值本地 `_remember_session()`；本地删除则是 `remove_session()` 直接删缓存并发本地 `SessionEvent.DELETED`

证据：

- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2/server/app/api/v1/sessions.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\services\session_service.py](D:\AssistIM_V2/client/services/session_service.py)

影响：

- 创建私聊后，其它在线设备或对端用户不会收到“新会话出现”的正式实时信号，只能靠后续发消息、手工刷新或全量快照刷新才看见
- 在当前服务端仍保留“全局硬删除 direct 会话”语义的前提下，删除动作更危险：其它在线成员和其它设备也不会收到正式删除事件，容易继续保留陈旧会话视图，直到下一次手工/全量同步
- 这说明“会话生命周期”现在还没有进入项目文档强调的正式事件模型，客户端 `SessionEvent.*` 和服务端协议事件是两套互不对应的概念

建议：

- 明确建模会话生命周期事件，不要再让 `SessionEvent.CREATED/DELETED` 只代表本地缓存操作
- 至少让建私聊、删会话这类正式后端动作进入统一的 realtime + compensation 边界，或明确规定它们必须通过 authoritative snapshot 拉平
- 补回归测试，覆盖“其它设备在线时建私聊/删会话”和“断线期间发生会话生命周期变化后重连”两类场景

### F-102：群生命周期动作也没有正式事件，建群当前主要靠发起端页面本地 merge 收口

状态：已修复（2026-04-14）

修复说明：

- direct counterpart 摘要已收口到 `resolve_user_avatar_url()` 只读路径，不再在会话读取中回写用户 avatar 状态。

现状：

- 服务端 [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `POST /groups` 和 `DELETE /groups/{group_id}` 都只是同步返回/执行结果，没有任何 realtime 广播，也没有把“新群出现/群被删除”写入 `history_events`
- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `create_group()` / `delete_group()` 也只是改库；和群资料修改不同，它们不生成任何正式事件
- 客户端建群主链路 [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 在 `_on_group_created()` 里是直接把 HTTP 返回值 `merge_group_record()` 进本地列表、更新缓存、随后跳转聊天
- [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `create_group()` 也只是封装这条 HTTP 返回值，没有额外的 authoritative refresh

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)

影响：

- 新群创建后，被拉入的其它在线成员和本账号其它设备不会收到“群已出现”的正式实时信号，只能靠后续手工刷新、全量拉群列表或某次会话快照刷新才看见
- 群删除同样没有正式下行事件；即使当前桌面端还没有完整 owner 删除主入口，服务端语义已经存在，但其它设备/成员没有对应 lifecycle 通知
- 这说明“群对象的出现/消失”当前并不在正式事件模型里，而是由发起端页面用 HTTP 返回值做局部本地收口

建议：

- 把群创建/删除纳入正式 lifecycle 事件模型，不要再让发起端页面本地 merge 代替服务端权威事件
- 至少补 authoritative snapshot 刷新策略或 realtime + compensation 之一，确保其它成员和其它设备能收敛到同一群列表状态
- 补回归测试，覆盖“建群后其它成员在线”“断线期间建群/删群后重连”的场景

### F-103：Moments 在发现页和联系人详情页之间没有共享更新通道，同一条动态的点赞/评论会跨页面失步

状态：已修复（2026-04-14）

修复说明：

- 消息 sender profile 序列化已去掉 `backfill_user_avatar_state()` 读路径写入，历史消息和 sync 返回不再顺手改用户表。

现状：

- 发现页 [discovery_interface.py](/D:/AssistIM_V2/client/ui/windows/discovery_interface.py) 自己维护一份 `_moments` 和 `_cards`，点赞/评论成功后只更新当前页卡片与本页列表
- 联系人详情页 [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 也单独维护 `detail_panel.moments_panel` 的 `_moments`，点赞/评论成功后只更新详情页 moments panel
- 两边虽然共用 [discovery_controller.py](/D:/AssistIM_V2/client/ui/controllers/discovery_controller.py) 做 HTTP 调用和少量缓存，但代码里没有任何事件总线、共享 observable、或统一的 controller-level mutation fanout 来把一次操作同步到另一块 UI
- `DiscoveryController.set_liked()` / `add_comment()` 只改 controller 内部 cache；真正把 UI 状态改掉的逻辑分别散落在两个页面自己的 success callback 里

证据：

- [D:\AssistIM_V2\client\ui\windows\discovery_interface.py](D:\AssistIM_V2/client/ui/windows/discovery_interface.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\discovery_controller.py](D:\AssistIM_V2/client/ui/controllers/discovery_controller.py)

影响：

- 用户如果先在发现页给某条动态点赞/评论，再切到联系人详情页查看同一作者动态，详情页仍可能显示旧的点赞数、评论数和评论列表；反过来也一样
- 这不是跨设备同步问题，而是同一进程、同一账号下多个 UI surface 之间都没有共享更新通道
- 说明 Moments 域目前主要是“页面各自 patch 自己的视图”，没有收口成成熟的单一前端状态模型

建议：

- 把 Moments 变更收口成 controller-level 统一更新事件，或让 controller 返回并维护一份可共享的 authoritative in-memory snapshot
- 不要再让发现页和联系人详情页各自手工 patch 自己的局部 UI
- 补回归测试，覆盖“发现页点赞/评论后联系人详情页同步变化”和反向路径

### F-104：联系人页即使在线消费了 `user_profile_update`，也不会把更新后的联系人/群头像写回本地搜索缓存

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_apply_profile_update_payload()` 会在收到 `user_profile_update` 后更新内存里的 `_contacts`、`_groups`、`_requests`，也会刷新当前页可见 item 和 detail panel
- 但这段增量更新结束后，并没有调用 [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `_persist_contacts_cache()` 或 `persist_groups_cache()`
- 与之相对，群资料类 realtime 更新走 `_apply_group_update_payload()` / `_apply_group_self_profile_update_payload()` 时，至少还会 `_schedule_groups_cache_persist()`
- 全局搜索 [search_manager.py](/D:/AssistIM_V2/client/managers/search_manager.py) 查的却仍然是落盘后的 `contacts_cache` / `groups_cache`

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- 即使联系人页正开着、并且已经把某个用户的新昵称/头像实时显示出来，本地全局搜索里这个联系人仍可能继续显示旧名字或旧头像
- `user_profile_update` 里顺带带来的 `session_avatar` 变化也只会更新联系人页内存里的 `_groups` 和可见 group item，不会同步回 `groups_cache`，因此群搜索结果同样可能继续陈旧
- 这说明联系人域当前不仅“缓存刷新依赖页面是否在线”，而且“页面在线消费成功”也不等于搜索缓存跟着变新

建议：

- 在 `_apply_profile_update_payload()` 完成联系人/群增量更新后，把对应 `contacts_cache` / `groups_cache` 一并持久化
- 收口成 controller/manager 级缓存同步，不要让 UI 层增量 patch 和搜索缓存更新脱节
- 补回归测试，覆盖“联系人页在线收到 `user_profile_update` 后，全局搜索立即命中新昵称/新头像”

### F-105：联系人域的增量更新缓存策略本身不一致，只有 group 分支会补写缓存，contact/request 分支长期只改内存

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 对 `group_profile_update` / `group_self_profile_update` 的增量处理会在更新 `_groups` 后调用 `_schedule_groups_cache_persist()`
- 但同一个文件里的 `_upsert_contact_record()`、`_upsert_request_record()`、`_apply_profile_update_payload()` 等 contact/request 增量路径，都只更新内存数组和当前可见 UI，不会触发任何 cache 持久化
- [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 也没有对应的 `persist_contacts_cache()` / request cache 持久化接口被这些增量路径调用；联系人缓存只在 `load_contacts()` 全量加载时重写
- 结果是联系人域当前形成了三套不同步策略：group 增量更新会补写搜索缓存，contact 增量更新不会，request 增量更新则连正式本地 cache 层都没有

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 联系人域不同子对象在经历相似的 realtime 增量更新后，会落到不同的新鲜度层级：群搜索可能是新的，联系人搜索还是旧的，请求列表则完全没有统一的本地 cache 收口
- 这会让“联系人页在线消费过实时事件”这件事本身都不再可靠，因为不同分支对本地 authoritative cache 的影响不一致
- 说明联系人域当前缺的不是某一个持久化调用，而是整体缓存同步 contract 还没有统一

建议：

- 明确联系人域的统一 cache contract：哪些对象需要本地 cache，哪些增量更新必须同步落盘，哪些只允许依赖全量 reload
- 不要让 group/contact/request 三条分支各自实现不同步的缓存策略
- 补回归测试，覆盖 contact/group/request 三类增量更新后的本地 cache 一致性

### F-106：`DiscoveryController` 会把本地评论缓存重新并回服务端快照，导致服务端已不存在的评论仍可能被客户端复活

状态：已修复（2026-04-14）

现状：

- [discovery_controller.py](/D:/AssistIM_V2/client/ui/controllers/discovery_controller.py) 的 `add_comment()` 会把新评论追加进 `_comment_cache[moment_id]`
- 后续每次 `load_moments()` 都会在 `_normalize_moment()` 里先采用服务端返回的 `comments`，再把 `_comment_cache` 中“ID 不在当前服务端列表里”的评论继续 `extend()` 回去
- 这意味着客户端并没有把服务端返回的 `comments` 当作 authoritative snapshot，而是在本地再做一次“并集”
- 代码里又没有任何 `_comment_cache` 失效、重建或按服务端快照修剪的逻辑

证据：

- [D:\AssistIM_V2\client\ui\controllers\discovery_controller.py](D:\AssistIM_V2/client/ui/controllers/discovery_controller.py)
- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)

影响：

- 只要服务端快照里某条评论后来不再存在，客户端 reload 后仍可能把本地缓存里的旧评论重新显示出来
- 这会让发现页和联系人详情页都偏离服务端 authoritative 评论列表，形成“客户端把旧评论复活”的错误状态
- 问题不在某个具体删除入口，而在于客户端对服务端快照做了方向错误的合并策略

建议：

- 把服务端返回的 `comments` 视为 authoritative snapshot，不要再把 `_comment_cache` 中服务端未返回的评论并回去
- 如果确实需要本地暂存未同步评论，应显式区分 optimistic/local-only comment，而不是直接混进正式列表
- 补回归测试，验证 reload 后不会把服务端已移除的评论重新显示

### F-107：发现页点赞状态会被本地 `_like_state_cache/_like_count_cache` 永久压过服务端权威值，reload 也无法纠正

状态：已修复（2026-04-14）

现状：

- [discovery_controller.py](/D:/AssistIM_V2/client/ui/controllers/discovery_controller.py) 的 `set_liked()` 成功后会把 `moment_id -> liked` 和可选 `like_count` 写进 `_like_state_cache/_like_count_cache`
- 后续 `_normalize_moment()` 在每次 `load_moments()` 时，只要看到这两个 cache 有值，就直接覆盖服务端 payload 里的 `is_liked` / `like_count`
- 这两个 cache 当前没有任何按 reload、服务端快照、时间窗口或成功回读的失效逻辑
- 服务端 [moment_service.py](/D:/AssistIM_V2/server/app/services/moment_service.py) 明明每次 `list_moments()` 都会返回新的 `like_count/is_liked/liked_user_ids`

证据：

- [D:\AssistIM_V2\client\ui\controllers\discovery_controller.py](D:\AssistIM_V2/client/ui/controllers/discovery_controller.py)
- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)

影响：

- 另一设备点赞/取消点赞、服务端修正计数、甚至同设备后续 reload，都无法把这条动态拉回服务端真实点赞状态
- 用户看到的 `is_liked` 和 `like_count` 会长期受本地进程内缓存支配，而不是由服务端快照决定
- 这说明 Moments 域现在没有 authoritative reload 语义，reload 只是把本地旧状态再套回新 payload

建议：

- 不要在 reload 归一化阶段无条件用 `_like_state_cache/_like_count_cache` 覆盖服务端值
- 如果这些 cache 只是短期 optimistic 状态，应在成功回读后清掉，或仅在明确的 in-flight 窗口内生效
- 补回归测试，验证“另一设备改动点赞后，本端 reload 能恢复服务端真实计数和状态”

### F-108：Moments 域完全没有正式实时/补偿模型，当前所有新增、点赞、评论都只能靠当前页面本地 patch 或手工 reload

状态：已修复（2026-04-14）

现状：

- 服务端 [moments.py](/D:/AssistIM_V2/server/app/api/v1/moments.py) 只提供纯 HTTP 的 `list/create/like/unlike/comment` 路由，没有任何 `connection_manager.send_json_to_users()` 或 `history_events` 记录
- 服务端 [moment_service.py](/D:/AssistIM_V2/server/app/services/moment_service.py) 也没有构建任何 realtime/control 事件
- 客户端 [discovery_interface.py](/D:/AssistIM_V2/client/ui/windows/discovery_interface.py) 和 [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 对 Moments 的更新都只发生在“当前页面发起成功后”的本地 patch，或者依赖手工 `reload_data()`
- 断线期间发生的 Moments 变化、另一设备发起的点赞评论、同账号其它页面做出的操作，都没有正式 transport-level 补偿入口

证据：

- [D:\AssistIM_V2\server\app\api\v1\moments.py](D:\AssistIM_V2/server/app/api/v1/moments.py)
- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)
- [D:\AssistIM_V2\client\ui\windows\discovery_interface.py](D:\AssistIM_V2/client/ui/windows/discovery_interface.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- Moments 域现在和消息域、群资料域相比，明显缺少成熟的跨页面、跨设备、断线恢复一致性模型
- 用户在别的设备/页面做出的 Moments 变更，不会自动出现在当前页面；只有主动 reload 才有机会看见
- 这也解释了前面一系列 Moments 局部状态失步问题为什么容易持续出现

建议：

- 明确 Moments 域是否需要正式 realtime 能力；如果需要，就不要继续停留在“页面各自 HTTP patch”的阶段
- 至少补 authoritative refresh contract，明确何时自动 reload、何时必须手工刷新，以及断线重连后如何收敛
- 补回归测试，覆盖“另一设备点赞/评论/发动态后，本端如何收敛”的主路径

### F-109：联系人详情页加载 Moments 的异步任务会在完成时用旧 payload 重刷 detail panel，可能把较新的资料更新覆盖回去

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_select_friend()` / `_select_request()` 会把当时选中的 `ContactRecord/FriendRequestRecord` 作为 `payload` 传给 `_load_detail_moments_async()`
- 这个异步任务在 await `load_moments()` 结束后，只检查 `_selected_key` 是否还是同一项，然后就直接 `detail_panel.set_contact(payload, moments)` / `set_request(payload, ..., moments)`
- 同一期间，`_apply_profile_update_payload()`、`_upsert_request_record()` 等 realtime/incremental 更新路径又可能已经把 detail panel 刷成了更新后的资料
- 由于 `_load_detail_moments_async()` 不比较对象版本、不重新取当前最新记录，晚到的 moments 任务完成后会把旧 `payload` 再次刷回 detail panel

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 当联系人资料实时更新或请求状态更新恰好发生在详情页异步加载 moments 的窗口里，detail panel 可能先变成新的，再被晚到的旧 payload 覆盖回旧名字/旧头像/旧请求状态
- 这属于典型的异步 stale overwrite，不需要跨设备就能在同一进程内发生
- 说明联系人详情页当前没有统一的“最新 detail model”来源，异步任务仍在携带过时对象回写 UI

建议：

- `_load_detail_moments_async()` 完成后不要再直接使用入参 `payload` 重刷 detail panel，而应重新从当前 `_contacts/_requests` 里取最新记录
- 或者给详情选择增加 generation/version 校验，避免晚到任务覆盖较新的资料状态
- 补回归测试，覆盖“资料实时更新与 detail moments 异步加载并发”场景

### F-110：好友请求接受后，新好友不会立即写入本地 `contacts_cache`，全局搜索在 reload 前仍然搜不到

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_accept_request_async()` 成功后会调用 `_upsert_contact_record(..., select_after_upsert=True)`，把新好友加入内存 `_contacts` 和当前页面 UI
- 但这条路径不会调用 [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `_persist_contacts_cache()`
- 全局搜索 [search_manager.py](/D:/AssistIM_V2/client/managers/search_manager.py) 的 `search_contacts()` 查的却是数据库 `contacts_cache`
- 底层 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `replace_contacts_cache()` 目前只会在 `load_contacts()` 全量拉取时被调用

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 用户在联系人页刚刚接受一个好友请求后，当前页里已经能看到这个新好友，但全局搜索仍然搜不到，直到下一次联系人全量 reload
- 这是非常直接的“可见 UI 已更新，但本地 authoritative 搜索缓存还是旧的”问题
- 也说明联系人域目前还没有把“好友关系建立”这类核心动作同步落盘到统一 cache

建议：

- 在 `_accept_request_async()` 成功并 `_upsert_contact_record()` 后，立即同步持久化 `contacts_cache`
- 收口成 controller/manager 级缓存更新，不要让好友接受这种核心动作依赖下一次全量 reload 才进入搜索索引
- 补回归测试，验证“接受好友请求后，无需 reload 即可在全局搜索中搜到新好友”

### F-111：发现页不会响应任何资料变更事件，动态作者信息在资料更新后只能靠手工 reload 才会变新

状态：已修复（2026-04-14）

现状：

- [discovery_interface.py](/D:/AssistIM_V2/client/ui/windows/discovery_interface.py) 当前没有订阅任何 `profileChanged`、`ContactEvent.SYNC_REQUIRED`、`MessageEvent.PROFILE_UPDATED` 之类的事件
- 顶层 [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 在收到 [user_profile_flyout.py](/D:/AssistIM_V2/client/ui/widgets/user_profile_flyout.py) 的 `profileChanged` 后，只同步 user card，并调用 `contact_interface.refresh_groups_after_profile_change()`
- 也就是说，无论是当前用户自己编辑资料，还是聊天域里已经能收到的 `user_profile_update`，发现页和其中的作者/评论展示都没有自动收口路径

证据：

- [D:\AssistIM_V2\client\ui\windows\discovery_interface.py](D:\AssistIM_V2/client/ui/windows/discovery_interface.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)
- [D:\AssistIM_V2\client\ui\widgets\user_profile_flyout.py](D:\AssistIM_V2/client/ui/widgets/user_profile_flyout.py)

影响：

- 用户自己改昵称/头像后，发现页里自己已发布动态的作者头部不会自动更新
- 其它用户资料变化即使已经通过聊天域同步到了联系人/会话页，发现页里的旧昵称、旧头像也会一直保留到手工刷新
- 这说明发现页当前完全游离在项目已有的资料更新传播链路之外

建议：

- 给发现页补统一的资料变更收口入口，至少消费当前用户 `profileChanged` 和聊天域现有的 `user_profile_update`
- 不要让 Moments 作者信息只能依赖手工 reload 才收敛
- 补回归测试，覆盖“修改资料后发现页作者头部自动更新”的路径

### F-112：`DiscoveryController` 把一次用户资料拉取失败永久缓存成空对象，后续不会重试

状态：已修复（2026-04-14）

现状：

- [discovery_controller.py](/D:/AssistIM_V2/client/ui/controllers/discovery_controller.py) 的 `_ensure_user_loaded()` 在 `fetch_user()` 失败时，会直接执行 `self._user_cache[user_id] = {}`
- 同一个方法开头又写了 `if not user_id or user_id in self._user_cache: return`
- 这意味着某个用户只要有一次资料补充请求失败，这个 `user_id` 之后在当前进程里就再也不会重试拉取

证据：

- [D:\AssistIM_V2\client\ui\controllers\discovery_controller.py](D:\AssistIM_V2/client/ui/controllers/discovery_controller.py)

影响：

- 一次暂时的网络抖动或服务端错误，就可能让某个作者/评论者在当前进程生命周期里一直停留在“缺少补充资料”的状态
- 后续即使用户手工刷新发现页，也不会再次尝试补拉这个人的资料
- 这属于非常典型的“把瞬时失败写成永久负缓存”问题

建议：

- 不要把失败结果以空对象写成长期缓存；至少要区分成功缓存和失败重试状态
- 给补充资料加 TTL、重试或显式失效机制
- 补回归测试，验证一次 `fetch_user()` 失败后，后续 reload 仍会重试

### F-113：发现页的用户资料缓存对非当前用户没有刷新路径，手工 reload 也无法修正补充字段

状态：已修复（2026-04-14）

现状：

- 服务端 [moment_service.py](/D:/AssistIM_V2/server/app/services/moment_service.py) 返回的 moment/comment payload 只自带 `username/nickname/avatar`，并不带 `gender`
- 客户端 [discovery_controller.py](/D:/AssistIM_V2/client/ui/controllers/discovery_controller.py) 又把 `gender` 等补充字段完全寄托在 `_user_cache`
- 但 `_ensure_user_loaded()` 对已经出现过的 `user_id` 会直接跳过，不会在后续 `load_moments()` 时重新拉取该用户资料
- 因此非当前用户的补充资料一旦进入 `_user_cache`，后续手工 reload 也不会再刷新

证据：

- [D:\AssistIM_V2\client\ui\controllers\discovery_controller.py](D:\AssistIM_V2/client/ui/controllers/discovery_controller.py)
- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)

影响：

- 对于没有显式头像、依赖 gender/fallback avatar 渲染的作者或评论者，发现页可能长期显示旧的补充资料
- 即使用户已经手工刷新发现页，补充字段仍然可能是旧的，因为 reload 根本不会再次拉取这些人的资料
- 这说明发现页现在不仅缺 realtime，连 manual reload 都不是完整的 authoritative refresh

建议：

- 给 `_user_cache` 增加刷新/失效策略，至少不要让 reload 永久沿用第一次拉到的补充资料
- 明确哪些字段以 moments payload 为准，哪些字段需要独立刷新
- 补回归测试，验证他人资料补充字段变化后，手工 reload 能够生效

### F-114：联系人页的群详情仍展示 Moments 面板，但这条路径根本没有任何加载实现，属于死功能入口

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的群详情 `set_group()` 会正常渲染一个 moments panel，并给出“暂无群动态”的文案
- 但 `_select_group()` 只会 `detail_panel.set_group(selected, [])`，并不会像 friend/request 那样调用 `_load_detail_moments()`
- 当前 [discovery_service.py](/D:/AssistIM_V2/client/services/discovery_service.py) / [moments.py](/D:/AssistIM_V2/server/app/api/v1/moments.py) 也只支持按 `user_id` 过滤 moments，没有任何 group moments 查询入口

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\services\discovery_service.py](D:\AssistIM_V2/client/services/discovery_service.py)
- [D:\AssistIM_V2\server\app\api\v1\moments.py](D:\AssistIM_V2/server/app/api/v1/moments.py)

影响：

- 群详情页里的 moments 面板当前不只是“暂时为空”，而是根本没有任何数据来源，永远只会显示空态
- 这会误导用户和后续开发者，以为系统已经存在“群动态”能力，只是当前群没有内容
- 属于典型的半实现 UI 暴露到了主路径

建议：

- 在真正支持 group moments 之前，移除或隐藏群详情里的 moments 面板
- 或明确补上 group moments 的正式数据接口和加载链路，不要保留死入口
- 补边界测试，确保不再把无后端能力支撑的面板暴露给用户

### F-115：发现页只在第一次显示时自动加载一次，之后再次切回页面不会自动刷新，动态内容会长期停留在旧快照

状态：已修复（2026-04-14）

现状：

- [discovery_interface.py](/D:/AssistIM_V2/client/ui/windows/discovery_interface.py) 的 `showEvent()` 只在 `_initial_load_done` 为 `False` 时触发 `reload_data()`
- 一旦第一次加载完成，后续用户在不同导航页之间切换，再回到发现页时不会自动 reload
- 前面已经确认 Moments 域没有 realtime/补偿模型，所以这里也不存在其它自动收口路径

证据：

- [D:\AssistIM_V2\client\ui\windows\discovery_interface.py](D:\AssistIM_V2/client/ui/windows/discovery_interface.py)

影响：

- 用户切到聊天/联系人页期间发生的动态新增、点赞、评论，回到发现页后仍会看到旧快照，除非手工点刷新
- 这让发现页在实际使用中很容易长期处于陈旧状态
- 结合 Moments 域缺少 realtime 的现状，这已经是明确的产品行为问题，不只是刷新策略偏好

建议：

- 给发现页补明确的刷新 contract，例如每次重新进入页面时按节流策略自动 reload
- 如果不想每次都全量拉取，至少要有可验证的脏标记或最近失效时间窗口
- 补回归测试，覆盖“离开发现页后发生动态变化，再切回时自动收敛”的路径

### F-116：群成员管理弹窗把好友候选集缓存成一次性快照，打开期间新增好友不会出现在“添加成员”候选里

状态：已修复（2026-04-14）

现状：

- [group_member_management_dialogs.py](/D:/AssistIM_V2/client/ui/windows/group_member_management_dialogs.py) 的 `_ensure_contacts_cache()` 只在 `_contacts_cache is None` 时调用一次 `load_contacts()`
- 同一个弹窗实例后续每次打开“添加成员”都直接复用这份缓存
- 当前弹窗内部也没有订阅任何联系人域变更事件来失效这份缓存

证据：

- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)

影响：

- 用户如果先打开群成员管理，再在别处接受好友请求或新增好友，不重新关掉这个弹窗的话，新好友不会出现在“添加成员”候选列表里
- 这是聊天页群管理主路径上的实际行为问题，不是单纯的缓存优化
- 会让“为什么刚加的好友这里选不到”变成稳定可复现的 UI 不一致

建议：

- 不要把候选好友集缓存成整个弹窗生命周期的一次性快照
- 至少在每次打开“添加成员”前重新拉取一次好友列表，或在联系人域变更后失效 `_contacts_cache`
- 补回归测试，覆盖“弹窗打开期间新增好友后，再次点添加成员能看到新好友”的路径

### F-117：聊天页发起的群成员/角色/转让操作，只会在联系人页已挂载时更新本地群搜索缓存

状态：已修复（2026-04-14）

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_apply_group_management_record()` 在聊天页群管理成功后，只会：
  1. 更新当前聊天会话的 group payload
  2. 发一个本地 `ContactEvent.SYNC_REQUIRED(reason="group_profile_update")`
- 仓库里这个事件当前唯一的订阅者是 [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py)
- 而真正把最新群快照落进 `groups_cache` 的逻辑，也是在联系人页的 `_apply_group_update_payload() -> _schedule_groups_cache_persist()` 里

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\events\contact_events.py](D:\AssistIM_V2/client/events/contact_events.py)

影响：

- 如果联系人页当前没有创建或没有挂着，聊天页里做的加成员、踢成员、改管理员、转让群主这些动作，不会把最新群成员快照写回本地 `groups_cache`
- 全局搜索和联系人页下次首次打开前看到的仍可能是旧的群成员搜索文本、旧 member_count 或旧群资料
- 这说明聊天页群管理当前仍依赖“联系人页在线消费本地事件”才能闭环，不是独立稳定的正式实现

建议：

- 不要把 `groups_cache` 的更新责任挂在联系人页是否存在上
- 在聊天页群管理成功后直接更新正式缓存，或把这类群变更纳入统一的服务端 realtime / reconnect 模型
- 补回归测试，覆盖“联系人页未打开时，从聊天页管理群成员后，全局搜索立即反映最新群信息”的路径

### F-118：从聊天页退群后，群列表/群搜索的本地收口同样依赖联系人页是否在线

状态：已修复（2026-04-14）

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_leave_group_async()` 在成功后只做三件事：
  1. 调服务端 `leave_group`
  2. 从聊天会话列表里 `remove_session`
  3. 发一个本地 `ContactEvent.SYNC_REQUIRED(reason="group_membership_changed")`
- 这个本地事件当前同样只有 [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 在订阅
- 联系人页如果不在线，就不会触发 `reload_data()` 去重写 `groups_cache`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- 用户从聊天页退群后，左侧聊天会话会消失，但本地群目录和群搜索缓存仍可能继续保留这个群
- 这会导致“聊天里已经退了，搜索里还能搜到/点开群”的跨入口不一致
- 本质上还是联系人域 authoritative cache 没有被当前退群主路径直接更新

建议：

- 退群成功后直接修剪 `groups_cache`，不要把这个职责留给联系人页是否刚好在线
- 或把群成员关系变化纳入正式 realtime / 补偿模型，确保搜索和联系人页都能在不依赖页面实例的情况下收敛
- 补回归测试，覆盖“联系人页未打开时，从聊天页退群后，本地群搜索立即不再命中该群”的路径

### F-119：联系人页的好友请求详情忽略了请求自带头像和性别，始终退化成字母占位头像

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的请求列表项 `RequestListItem` 会使用 `request.counterpart_avatar()` 和 `request.counterpart_gender()` 正常渲染头像
- 但当前正式详情面板 `GalleryContactDetailPanel.set_request()` 里只调用了 `self.avatar.set_avatar(fallback=counterpart_name)`，没有把请求里的头像和 gender 传进去

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 同一个好友请求在左侧列表里能看到真实头像，但点进右侧详情后会退化成缩写头像
- 这是联系人页当前主路径上的直接视觉回退，不需要任何异常条件就能出现
- 也会让用户误以为请求详情拿到的是另一份不完整数据

建议：

- 请求详情面板应和请求列表使用同一套 counterpart avatar / gender 渲染来源
- 不要在详情页无故丢掉已经存在于 `FriendRequestRecord` 里的头像信息
- 补 UI 回归测试，覆盖“请求列表头像与详情头像一致”的路径

### F-120：联系人页全量 reload 失败时会留下“内存已更新、界面未重建”的半刷新状态

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_reload_data_async()` 会先后直接赋值：
  - `self._contacts = await load_contacts()`
  - `self._groups = await load_groups()`
  - `self._requests = await load_requests()`
- 但只有三段都成功后，才会统一 `_build_*_page()` 和 `_restore_selection()`
- 中途任何一步抛错，方法就直接 `return`，不会回滚前面已经改掉的内存快照

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 例如好友列表已经更新到新快照，但群组/请求加载失败时，当前可见 UI 仍停留在旧页面，而内存里的 `self._contacts` 已经是新的
- 后续一旦再触发局部 rebuild、选择恢复或增量 patch，页面就会从这个混合快照继续演化，行为会变得不一致且难以解释
- 这属于典型的“非原子 reload”问题，尤其容易在弱网和接口部分失败时暴露

建议：

- 把三段数据先读到局部临时变量里，全部成功后再一次性替换 `self._contacts/_groups/_requests`
- 或给失败路径补明确回滚，避免留下半刷新内存状态
- 补回归测试，覆盖“contacts 成功、groups 或 requests 失败”时联系人页不会进入混合快照

### F-121：已接受的好友请求仍停留在“请求详情”语义里，用户无法直接从该详情页发消息

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_build_requests_page()` 会把 pending / accepted / rejected 全部请求都继续渲染在 requests 页
- 同文件的 `_accept_request_async()` 接受好友请求后，会更新 request 记录，但并不会把它从 requests 域移除
- 而两个详情面板的 `set_request()` 都会强制 `self._entity = None`，并把 `message_button` 置灰

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户在“新的朋友”里重新点开一条已经 accepted 的请求时，右侧仍是“请求详情”，而不是可直接发消息的联系人详情
- 这会形成非常别扭的语义分裂：左侧这条记录已经代表一个已建立好友关系的人，但右侧仍然完全不可交互
- 属于联系人页当前主路径上的明确行为缺口

建议：

- 对 accepted 请求，要么从 requests 页正式移出，要么详情页直接桥接到联系人详情/可发消息状态
- 不要继续把已经建立好友关系的对象锁死在 `_entity = None` 的只读请求详情里
- 补回归测试，覆盖“请求 accepted 后，从 requests 页再点开该人时仍能进入可聊天状态”的路径

### F-122：好友请求详情把“对方昵称”当成了 `AssistIM ID` 展示

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 里两个 `set_request()` 实现，都会把 `counterpart_name` 直接塞进 `AssistIM ID` 这一行
- 但 `counterpart_name()` 返回的是展示名，不是 id/username/assistim_id

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 请求详情会把“昵称/显示名”错误标成 `AssistIM ID`
- 这不是文案问题，而是字段语义错了；用户会直接看到一行标题正确、值却不是 ID 的信息
- 联系人页当前已经在别处区分了 `display_name` 和 `assistim_id/username`，这里属于明显回退

建议：

- 请求详情应展示真正的可识别账号字段，拿不到就显示 `-`，不要把昵称伪装成 ID
- 如果当前请求 payload 不含正式账号字段，就在模型层明确区分“显示名”和“账号标识”
- 补 UI 回归测试，验证请求详情的 `AssistIM ID` 行不会再显示昵称

### F-123：联系人详情页把语音/视频按钮做成可点击主按钮，但实际仍是占位提示

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的两个联系人详情面板都会在 `set_contact()` 时启用 `voice_button` / `video_button`
- 但这两个按钮始终只连到 `_show_unavailable()`，点击后只弹一个“UI placeholders for now”的提示
- 同时聊天页 [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 已经有正式通话入口和完整通话链路

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 联系人页现在把“语音通话/视频通话”呈现成正式可用按钮，但点击后是死入口
- 因为应用本身已经支持通话，这会更容易让用户认为这是 bug，而不是产品未实现
- 这属于典型的半实现能力直接暴露到了主界面

建议：

- 要么把联系人页通话按钮真正接到现有 chat/call flow
- 要么在能力未接通前隐藏或禁用这些按钮，不要保留可点击主按钮再弹占位提示
- 补回归测试，覆盖联系人详情页的通话入口要么可用、要么不可见/不可点击

### F-124：聊天页顶部“聊天记录”入口已经挂在正式按钮上，但实际仍是占位提示

状态：已修复（2026-04-14）

现状：

- [chat_panel.py](/D:/AssistIM_V2/client/ui/widgets/chat_panel.py) 的 `chat_header.history_clicked` 已经正式连接到 `chat_history_requested`
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 也正式消费了这个信号
- 但 `_on_chat_history_requested()` 当前只弹一个 “will be connected next” 的 InfoBar

证据：

- [D:\AssistIM_V2\client\ui\widgets\chat_panel.py](D:\AssistIM_V2/client/ui/widgets/chat_panel.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 用户在聊天页头部点击“聊天记录”会进入死入口
- 这不是隐藏的未实现能力，而是已经暴露在主路径的正式 header action
- 会直接削弱聊天页“搜索/历史/会话管理”这组能力的可信度

建议：

- 在真正接通聊天记录页前，移除或隐藏这个 header action
- 或尽快接到已有本地搜索/历史加载能力，不要让正式入口只剩占位提示
- 补 UI 回归测试，确保顶部 action 不再暴露死入口

### F-125：聊天信息抽屉里的“查找聊天内容”和“清空聊天记录”都是正式入口，但当前都只是占位提示

状态：已修复（2026-04-14）

现状：

- [chat_info_drawer.py](/D:/AssistIM_V2/client/ui/widgets/chat_info_drawer.py) 已经把 `searchRequested`、`clearRequested` 接到抽屉内正式行项/按钮
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 也分别实现了 `_on_chat_info_search_requested()` 和 `_on_chat_info_clear_requested()`
- 但这两个 handler 现在都只弹 “will be connected next / reserved” 的 InfoBar，没有任何正式业务流

证据：

- [D:\AssistIM_V2\client\ui\widgets\chat_info_drawer.py](D:\AssistIM_V2/client/ui/widgets/chat_info_drawer.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 聊天信息抽屉里当前至少有两条已经暴露给用户的死入口
- 这会让用户误以为“聊天搜索”和“清空聊天记录”已经存在，只是当前数据异常
- 对 code review 来说，这说明聊天页外围管理功能还存在明显的半实现 UI 泄漏

建议：

- 在功能真正落地前，把这两个入口从抽屉里移除或禁用
- 或优先把它们接到现有历史/删除模型上，哪怕先做受限版本，也不要保留死入口
- 补 UI 回归测试，验证抽屉里不再出现仅弹占位提示的正式 action

### F-126：会话侧边栏搜索框已经绕开了本地会话过滤模型，输入关键词不会真正过滤会话列表

状态：已修复（2026-04-14）

现状：

- [session_panel.py](/D:/AssistIM_V2/client/ui/widgets/session_panel.py) 里保留了一整套 `SessionFilterProxyModel`，支持按会话名、最新预览、draft 预览过滤
- 但真实输入路径 `_on_search_text_changed()` 每次都会把 `self._proxy_model.set_filter_text("")` 直接清空
- 仓库里也没有任何其它地方再给这个 proxy model 传入用户输入关键词

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2/client/ui/widgets/session_panel.py)

影响：

- 用户在会话侧边栏输入关键词时，左侧会话列表并不会按关键词真正收窄
- 这不是交互偏好，而是现有本地过滤实现已经被输入链路完全绕开
- 结果会让“看上去像搜索会话”的输入框，实际退化成只弹一个旁路搜索面板

建议：

- 明确侧边栏搜索的正式 contract：如果它是会话过滤框，就把关键词真正交给 `SessionFilterProxyModel`
- 如果产品决定只做全局搜索，就移除这套未生效的本地会话过滤实现，避免继续误导
- 补回归测试，覆盖“输入会话名后左侧列表确实收窄”的路径

### F-127：会话侧边栏搜索当前根本不搜索“会话”本身，只搜索消息/联系人/群缓存

状态：已修复（2026-04-14）

现状：

- [session_panel.py](/D:/AssistIM_V2/client/ui/widgets/session_panel.py) 的 `_run_global_search()` 固定调用 `search_all()`
- [search_manager.py](/D:/AssistIM_V2/client/managers/search_manager.py) 的 `SearchCatalogResults` 只包含 `messages / contacts / groups`
- 也就是说，会话侧边栏当前搜索结果根本没有“session”这一域

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2/client/ui/widgets/session_panel.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- 一个没有命中消息内容、也不在联系人/群缓存里的会话，即使它真实存在于左侧列表里，也不会被搜索结果返回
- 尤其是新建但还没消息的 direct/group 会话，当前搜索框几乎等于搜不到
- 这和“会话侧边栏搜索”这个位置给用户的心理预期明显不一致

建议：

- 如果这个入口属于会话搜索，就应该把 `session` 作为正式搜索域纳入结果模型
- 至少要保证“按会话名/会话预览搜会话”这条最基本路径成立
- 补回归测试，覆盖“空白新会话仅凭会话名也能被侧边栏搜索找到”的路径

### F-128：联系人页共用搜索框不覆盖请求域，在 requests 页输入关键词也搜不到好友请求

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的搜索框在 friends / groups / requests 三个页签上共用
- 但 `_run_global_search()` 同样固定调用 `search_all()`
- [search_manager.py](/D:/AssistIM_V2/client/managers/search_manager.py) 的聚合搜索域只有 `messages / contacts / groups`，没有 request/friend_request 域

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- 用户切到“新的朋友”页签后，在同一个搜索框里输入发起人名字或请求备注，搜索弹层不会返回任何请求结果
- 这会让 requests 页上的搜索框语义变得很怪：它摆在请求列表上方，却完全不搜请求
- 属于联系人页主路径上的明确域模型缺口

建议：

- 要么给联系人页搜索补 request 域
- 要么在 requests 页切换成真正针对请求列表的本地过滤，不要继续复用一个不覆盖该域的搜索实现
- 补回归测试，覆盖“在 requests 页按对方名称能搜到对应请求”的路径

### F-129：联系人页搜索弹层在资料增量更新后不会自动重跑，当前可见结果会停留在旧快照

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_on_contact_sync_required()` 对 `user_profile_update / group_profile_update / group_self_profile_update` 只会做局部内存 patch
- 这些分支都不会重新触发 `_trigger_global_search()`，也不会在关键词保持不变时重跑 `_run_global_search()`
- 因此搜索弹层如果此时正开着，结果项会继续停留在更新前的快照

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 例如联系人昵称、群名或群头像已经在列表/详情里更新了，但搜索弹层仍显示旧标题、旧命中片段或旧头像
- 这会让联系人页同一时刻出现“左边列表是新的，搜索弹层还是旧的”的并存状态
- 问题不在缓存持久化，而在当前可见搜索结果没有被增量更新链路收口

建议：

- 当搜索框非空且弹层打开时，资料增量更新后应主动重跑当前关键词搜索
- 至少要给当前可见的搜索结果补一条 refresh 路径，不要让它长期停留在旧快照
- 补回归测试，覆盖“搜索弹层打开时收到 profile/group update，结果即时更新”的路径

### F-130：聊天输入区的语音/视频按钮没有按会话类型收口，群聊和 AI 会话里也会进入错误流

状态：已修复（2026-04-14）

现状：

- [message_input.py](/D:/AssistIM_V2/client/ui/widgets/message_input.py) 会在 session active 时统一启用 `voice_button / video_button`
- `set_session()` 只更新 mention candidates，并没有按 `session_type / is_ai_session` 调整这两个按钮的可用性
- 最终 [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_start_current_session_call()` 又会在非 direct 会话里报错 “Open one direct chat before starting a call.”

证据：

- [D:\AssistIM_V2\client\ui\widgets\message_input.py](D:\AssistIM_V2/client/ui/widgets/message_input.py)
- [D:\AssistIM_V2\client\ui\widgets\chat_panel.py](D:\AssistIM_V2/client/ui/widgets/chat_panel.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 用户在群聊或 AI 会话里也能点到语音/视频按钮，但点击后只会进入错误提示
- 这不是占位功能，而是按钮作用域没有按业务规则正确收口
- 会让聊天输入区在不同会话类型下暴露出错误的可操作 affordance

建议：

- 在 composer/chat panel 层就按 `session_type` 和 `is_ai_session` 收口通话按钮的可见性或可用性
- 不要把“不支持通话”的判断推迟到点击后的错误流
- 补回归测试，覆盖“群聊/AI 会话不暴露 direct-call 按钮”的路径

### F-131：好友请求转联系人时把“显示名”误当成了 `username/assistim_id`

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_contact_record_from_request()` 会把 `request.sender_name / request.receiver_name` 当作 `raw_username`
- 但 [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `load_requests()` 里，`sender_name / receiver_name` 本身已经是“昵称优先，其次 username”的显示名字段
- 结果就是一旦对方有昵称，accepted 后本地新建出来的 `ContactRecord.username / assistim_id` 就会被写成昵称而不是真实账号标识

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)

影响：

- 新接受的好友在本地联系人详情、搜索缓存、侧边栏展示里，会出现“昵称被当成 AssistIM ID / username”的错字段
- 这个问题会直接污染后续本地搜索和详情展示，不只是一次性的 UI 文案错误
- 也会让 accepted-request 路径和正常 `load_contacts()` 拿到的联系人模型不一致

建议：

- 不要用 `sender_name / receiver_name` 反推 username
- 请求模型里应保留真实 username/assistim_id 与 display name 的分离字段，accepted 后直接用正式账号字段构造 `ContactRecord`
- 补回归测试，覆盖“对方有 nickname 时，accepted 后联系人的 assistim_id 仍是真实账号而不是昵称”的路径

### F-132：好友请求缺资料时只补“名字”不补“头像/性别”，请求列表和详情会长期停留在占位头像

状态：已修复（2026-04-14）

现状：

- [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `load_requests()` 在请求 payload 缺显示名时，会额外调用 `_load_request_user_names()`
- 但这个补拉逻辑只返回 `dict[user_id -> name]`，不会补 avatar、gender 或其它资料
- 因此初始请求 payload 一旦没带头像/性别，即使客户端已经为该用户发起了额外 `fetch_user()`，请求列表和详情里仍只会继续显示占位头像

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 请求列表项和请求详情会长期停留在不完整资料态
- 这不是后端没能力，而是前端已经发起了补拉，却只消费了其中最窄的一部分字段
- 会让请求域和联系人域对同一用户的展示完整度不一致

建议：

- 把请求补拉从“只补 name”改成“补一份最小完整 profile”，至少包含 avatar 和 gender
- 或者在请求模型里显式区分“缺省字段待补齐”，不要让请求域永远停在半空模型
- 补回归测试，覆盖“请求 payload 缺 avatar/gender 时，补拉后列表和详情能更新头像”的路径

### F-133：会话侧边栏搜索弹层在会话更新后不会自动重跑，当前可见结果会停留在旧快照

状态：已修复（2026-04-14）

现状：

- [session_panel.py](/D:/AssistIM_V2/client/ui/widgets/session_panel.py) 会订阅 `SessionEvent.CREATED/UPDATED/DELETED/MESSAGE_ADDED/UNREAD_CHANGED` 并即时更新左侧列表
- 但这些事件处理分支都不会在搜索框非空、搜索弹层已打开时重跑 `_run_global_search()`
- 因此搜索弹层和左侧列表会在同一时刻各自持有不同版本的 session/message/contact/group 快照

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2/client/ui/widgets/session_panel.py)

影响：

- 会话标题、最新预览、未读、头像已经在列表里更新了，搜索弹层却仍显示旧标题、旧命中片段或旧统计
- 这会让聊天主界面同时出现“列表是新的、搜索结果还是旧的”的不一致状态
- 问题不是搜索缓存设计，而是当前可见搜索结果没有挂到 session 增量更新链路上

建议：

- 当搜索框非空且弹层打开时，`SessionEvent` 更新后应主动重跑当前关键词搜索
- 至少要让当前可见搜索结果跟着 session authoritative state 一起刷新
- 补回归测试，覆盖“搜索弹层打开时收到 session update/message added，结果即时更新”的路径

### F-134：聊天记录搜索结果点击后只会打开会话，完全忽略命中的 `message_id`

状态：已修复（2026-04-14）

现状：

- [global_search_panel.py](/D:/AssistIM_V2/client/ui/widgets/global_search_panel.py) 的消息结果 payload 明确带了 `message_id`
- 但 [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 的 `_open_contact_target()` 在 `target_type == "message"` 分支里只取 `session_id`，随后直接 `open_session(session_id)`
- 这条链路完全没有使用 payload 里的 `message_id`

证据：

- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)

影响：

- 用户从“聊天记录”搜索命中某条消息后，点击结果并不会跳到那条消息，只是泛泛地打开该会话
- 对多命中长会话来说，这基本等于搜索结果无法真正定位
- 这会让当前消息搜索只剩“告诉你在哪个会话里有命中”，而不是可操作的定位能力

建议：

- 打通“打开会话并定位到 message_id”的正式链路
- 如果短期内做不到定位，至少在 UI 上不要把它包装成消息级结果点击
- 补回归测试，覆盖“点击消息搜索结果后会滚动/聚焦到对应 message_id”的路径

### F-135：联系人页的群列表全量刷新后，当前选中的群详情可能继续停留在旧快照

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_refresh_groups_only()` 会重新 `load_groups()`、重建 groups 页，再调用 `_restore_selection(full_reload=False)`
- 但 `_restore_selection(full_reload=False)` 在选中项仍存在时，只会重新高亮 item 并 `show_detail_panel()`，不会把新的 `GroupRecord` 重新 `set_group()` 到详情面板
- 这意味着列表已经换成新的 authoritative groups 快照，右侧详情却可能继续显示旧对象

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 群列表的成员数、名称、头像等已经刷新成新值，但右侧当前选中群详情仍可能停留在旧数据
- 这个问题在 `refresh_groups_after_profile_change()` 这类 authoritative reload 路径上最容易出现
- 会让联系人页同屏出现“列表新、详情旧”的典型双真相问题

建议：

- 在 `_restore_selection(full_reload=False)` 命中当前选中群时，也要用最新对象重新渲染详情面板
- 或让这类 authoritative reload 统一走 `full_reload=True` 的重选路径
- 补回归测试，覆盖“groups reload 后当前选中群详情同步刷新”的路径

### F-136：在 requests 页接受“第一个好友”后，联系人页可能切到 friends 但仍停留在空态

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_accept_request_async()` 会在 accept 成功后调用 `_upsert_contact_record(..., select_after_upsert=True)`
- 但 `_upsert_contact_record()` 只有在 `self._friend_items` 已非空，或当前页本来就是 `friends` 时，才会真正插入 sidebar friend item
- 如果用户当时停在 requests 页，且这正好是本地第一个好友，那么 `_friend_items` 为空、`_current_page != "friends"`，新好友不会被插入左侧列表；随后代码又会 `_activate_page("friends")`

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户在“新的朋友”页接受首个好友后，页面会切到 friends，但左侧仍可能保持空列表/欢迎态
- 这不是服务端没返回，而是本地 accept 收口顺序有问题：先决定“是否插入 item”，后切页
- 会让“accept 成功”后的第一时间体验直接出错，尤其是新账号或空联系人账号

建议：

- `select_after_upsert=True` 的路径不要依赖当前页与旧 `_friend_items` 状态来决定是否插入 friend item
- 或者在切到 friends 后统一走一次最小重建，而不是复用当前这条增量插入分支
- 补回归测试，覆盖“requests 页接受第一个好友后，friends 列表立即出现该联系人”的路径

### F-137：好友请求 accepted 后会先生成一份“半空联系人模型”，当前设备详情会直接显示不完整资料

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_contact_record_from_request()` 会把 accepted request 直接转换成本地 `ContactRecord`
- 这条转换只带上 `id / name / username / nickname / avatar / gender` 之类最小字段，`region / signature / email / phone / birthday / status / extra` 都被写成空值
- `_accept_request_async()` 和 `_on_friend_request_sent(status=accepted)` 都会直接用这份 synthetic record 更新并选中联系人，没有先做一次 authoritative `load_contacts()` 或 `fetch_user()`

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户刚接受好友请求后，当前设备右侧联系人详情会立即展示一张“半空资料卡”，哪怕服务端其实已有更完整的资料
- 这会让 accepted-request 路径得到的联系人模型与正式 `load_contacts()` 路径不一致
- 问题不只是展示短暂变旧，因为这份半空 record 还会继续参与本地排序、搜索标题和详情渲染

建议：

- accepted 后不要直接把 request payload 映射成联系人权威模型
- 至少补一条最小 authoritative fetch，再决定当前设备如何插入/选中联系人
- 补回归测试，覆盖“accept 后当前联系人详情字段不退化成半空模型”的路径

### F-138：联系人本地搜索根本不覆盖 `username` 字段，按账号名搜索好友可能直接搜不到

状态：已修复（2026-04-14）

现状：

- [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `replace_contacts_cache()` 会把 `username` 正式落盘
- 但 `search_contacts()` 的 LIKE 分支只搜 `nickname / remark / assistim_id / region`
- 同文件的 `contact_search_fts` 也只索引 `display_name / nickname / remark / assistim_id / region`，没有 `username`
- 上层 [search_manager.py](/D:/AssistIM_V2/client/managers/search_manager.py) 的高亮分支同样不处理 `username`

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- 联系人页和聊天页共用的本地搜索，按真实 `username`/账号名搜索好友时，可能直接没有结果
- 这和 Add Friend 流程、联系人详情、副标题里对 `username` 的正式展示是冲突的
- 属于联系人搜索域模型的明显缺口，不是排序或命中高亮的小问题

建议：

- 把 `username` 纳入 contacts cache 的 LIKE 与 FTS 搜索字段
- 搜索结果高亮与 subtitle 也要同步支持 `username`
- 补回归测试，覆盖“按 username 能在本地搜索命中联系人”的路径

### F-139：FTS 已经能按 `display_name` 命中联系人，但结果会在高亮层被直接丢弃

状态：已修复（2026-04-14）

现状：

- [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `contact_search_fts` 已把 `display_name` 建进正式索引
- `_search_contacts_fts()` 也会把这些命中行返回给上层
- 但 [search_manager.py](/D:/AssistIM_V2/client/managers/search_manager.py) 的 `_highlight_contact_match()` 只尝试高亮 `nickname / assistim_id / region / remark`
- 如果关键词只命中了 `display_name`，这一步会返回 `None`，随后该联系人结果被整个列表推导式静默丢掉

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- 联系人标题本身明明显示的是 `display_name`，但用户按这个可见标题搜索时，FTS 命中仍可能出现在 count 里、却不出现在最终结果列表里
- 这会造成“搜索总数和结果卡片不一致”或“明明可见名字匹配却搜不到”的体验
- 问题不在数据库，而在 search manager 自己把已经命中的结果过滤掉了

建议：

- `_highlight_contact_match()` 必须覆盖 `display_name`，并与底层索引字段保持一致
- 不要让高亮层再承担“裁掉已命中的结果”这种二次筛选职责
- 补回归测试，覆盖“按 display_name 搜索联系人能稳定显示结果卡片”的路径

### F-140：Add Friend 弹窗把“已有好友”候选集冻结成创建时快照，打开期间新增好友仍会显示可继续添加

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 在打开 `AddFriendDialog` 时，只把当时的 `{item.id for item in self._contacts}` 传进去
- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `AddFriendDialog` 内部把这份 `existing_ids` 保存成 `_existing_ids`
- 后续 `_render_search_results()` 只用这份静态集合决定按钮是否显示为 “Already Friends”，弹窗打开期间不会随联系人增量更新而刷新

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 如果弹窗打开后，用户通过其它入口刚好新加了某人，搜索结果里这个人仍会继续显示可点击的 “Add Friend”
- 这会把联系人主真相和 Add Friend 候选态拆成两份，形成重复申请/重复操作入口
- 问题不在服务端幂等，而在联系人页弹窗把好友关系判断冻结在了打开瞬间

建议：

- Add Friend 弹窗应订阅联系人变化，或在每次渲染搜索结果时读取最新好友集合
- 不要把“是否已是好友”的判断固化成打开瞬间的一次性快照
- 补回归测试，覆盖“弹窗打开期间联系人集合变化后，搜索结果按钮状态同步更新”的路径

### F-141：联系人页顶部搜索框实际上是跨域全局搜索，好友/群页里也会弹出“聊天记录”结果

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_run_global_search()` 固定调用 `search_all(keyword, ...)`
- [search_manager.py](/D:/AssistIM_V2/client/managers/search_manager.py) 的 `search_all()` 正式聚合了 `messages / contacts / groups`
- [global_search_panel.py](/D:/AssistIM_V2/client/ui/widgets/global_search_panel.py) 也会在联系人页搜索弹层里直接渲染“聊天记录”分组，并允许点击后跳去聊天页

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- 用户明明在联系人页的 friends/groups/requests 侧边栏上方输入关键词，弹层却会混入聊天记录结果
- 这会让联系人页搜索框的业务语义非常不稳定：它看起来在搜联系人目录，实际却会旁路跳去聊天页
- 属于联系人主界面的明确域边界污染，不是单纯“多一个结果分组”

建议：

- 联系人页搜索要么明确收口成 contact/group/request 域
- 要么在 UI 上明确标识这是全局搜索，而不是放在联系人侧栏里假装是目录过滤
- 补回归测试，覆盖“联系人页搜索不再无意混入聊天记录域”的路径

### F-142：联系人详情里的 in-flight Moments 加载会把较新的联系人/请求资料重新覆盖回旧快照

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_select_friend()` / `_select_request()` 会先把当前 `ContactRecord/FriendRequestRecord` 传给详情面板，再异步启动 `_load_detail_moments(..., payload)`
- `_load_detail_moments_async()` 完成后，会直接用启动时捕获的旧 `payload` 再次 `set_contact(payload, moments)` 或 `set_request(payload, ..., moments)`
- 同时，`_apply_profile_update_payload()` 又可能在任务飞行期间把当前选中联系人的详情更新成更新后的新资料

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 如果联系人/请求资料在 Moments 加载期间发生更新，详情面板会先显示新资料，随后又被晚到的旧 payload 覆盖回去
- 这会造成明显的“资料闪回旧值”问题，尤其是昵称、头像、状态这类高频可见字段
- 本质上是详情渲染和 moments 异步加载共享了两份不同时间点的对象快照

建议：

- Moments 加载完成后不要再信任启动时捕获的旧 payload
- 应当按当前 `selected_key` 从最新 `_contacts/_requests` 里重新取对象，再和 moments 一起渲染
- 补回归测试，覆盖“资料更新发生在 moments load 期间时，详情不会回滚到旧快照”的路径

### F-143：联系人资料增量更新时会保留旧的 `assistim_id`，用户名变化后详情和搜索缓存会继续显示旧账号

状态：已修复（2026-04-14）

现状：

- [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的正式 `load_contacts()` 路径里，`assistim_id` 就是 `username`
- 但 [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_apply_profile_update_payload()` 在处理 `user_profile_update` 时，只更新 `name / username / nickname`
- 同一段代码里却把 `assistim_id` 固定保留为 `contact.assistim_id`，不会随新的 `profile.username` 一起更新

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 如果用户名发生变化，联系人详情副标题、AssistIM ID 展示以及依赖该字段的本地缓存都会继续保留旧账号值
- 这会让增量 `user_profile_update` 路径和正式 `load_contacts()` 路径得出两套不同的联系人模型
- 也是联系人页“显示名新了，但账号标识还是旧的”的直接来源

建议：

- 在 `user_profile_update` 合并路径里同步更新 `assistim_id`
- 账号标识字段如果和 `username` 是同一真相，就不应该在增量路径上分叉
- 补回归测试，覆盖“username 更新后联系人详情和本地搜索缓存一起收口到新账号”的路径

### F-144：Add Friend 弹窗完全不感知“已发出待处理好友请求”，同一用户仍会继续显示可添加

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 打开 `AddFriendDialog` 时只传入了当前好友 `existing_ids`
- `AddFriendDialog._render_search_results()` 也只用 `user.id in self._existing_ids` 决定是否展示 “Already Friends”
- 整条链路没有接入当前 `_requests`，也没有识别 pending/accepted/rejected 的请求状态

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 对已经发过待处理好友请求的用户，Add Friend 搜索结果仍会继续展示可点击的 “Add Friend”
- 这会让联系人主真相和加好友入口对“当前关系状态”的理解不一致
- 即使服务端最终做了幂等拒绝，前端也仍然把用户引导进了一条错误操作流

建议：

- Add Friend 弹窗在渲染候选结果时应同时考虑好友关系和 friend request 状态
- 至少要把待处理请求收口成 disabled/已发送态，不要继续暴露可重复发送按钮
- 补回归测试，覆盖“已有 pending request 的用户在 Add Friend 搜索里不可再次发送”的路径

### F-145：联系人页的建群弹窗把好友列表冻结成打开时快照，弹窗期间新增好友不会出现在候选里

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 打开 `CreateGroupDialog` 时，直接把当时的 `self._contacts` 传进去
- [group_creation_dialogs.py](/D:/AssistIM_V2/client/ui/windows/group_creation_dialogs.py) 的 `CreateGroupDialog` 在构造时把它保存为 `self._contacts = list(contacts)`
- 后续 `_rebuild_member_list()` 只在这份静态快照上做本地过滤，弹窗打开期间不会再读取联系人主列表的更新

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)

影响：

- 如果建群弹窗打开后，用户刚好新增了好友，新好友不会出现在建群成员候选里
- 这会让联系人主列表和“基于当前好友建群”的弹窗候选出现双真相
- 属于联系人页建群主路径的状态冻结问题，不是单纯的搜索体验问题

建议：

- Create Group 弹窗应在打开期间感知联系人列表变化，或至少支持手动 refresh
- 不要把“当前好友集合”固化成打开瞬间的一次性快照
- 补回归测试，覆盖“建群弹窗打开期间新增好友后，候选成员列表可见该好友”的路径

### F-146：从 Add Friend 弹窗发出“第一条好友请求”后，联系人页可能切到 requests 但仍停留在空态

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_on_friend_request_sent()` 会先 `_upsert_request_record(request)`，然后在 `status != accepted` 时 `_activate_page("requests")`
- 但 `_upsert_request_record()` 只有在 `self._request_items` 已非空，或当前页本来就是 `requests` 时，才会真正插入 request item
- 如果用户原本停在 friends 页，且这是当前设备第一条 request，那么 `_request_items` 为空、`_current_page != "requests"`，请求不会被插入；随后代码再切到 requests 页

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户刚从 Add Friend 弹窗发送第一条好友请求后，页面会跳到“新的朋友”，但左侧仍可能保持空列表/欢迎态
- 这和 `F-136` 是同一类收口缺口，只是发生在“发出首条请求”而不是“接受首个好友”这条路径上
- 会让联系人页最基本的 request 主流程在空数据账号上直接失效

建议：

- request 增量插入不要依赖旧 `_request_items` 或旧页签状态
- 进入 requests 页前，应确保新 request 已经被插入或执行最小重建
- 补回归测试，覆盖“friends 页发出第一条请求后，requests 列表立即出现该请求”的路径

### F-147：“新的朋友”页签和请求计数实际混入了历史/已处理请求，不是待处理新请求视图

状态：已修复（2026-04-14）

现状：

- 服务端 [friend_service.py](/D:/AssistIM_V2/server/app/services/friend_service.py) 的 `list_requests()` 返回当前用户所有 request，并不只限 pending
- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_build_requests_page()` 也会把 `incoming / outgoing / unknown` 的全部 request 都渲染出来
- 同页的 `_update_summary_counts()` 又直接把 `len(self._requests)` 写到 summary 里；空态文案却仍是 “No new friend requests”，页签文案也是 “New Friends”

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- “新的朋友”页签实际会混入 accepted / rejected / expired / outgoing 等历史记录，不再是真正的待处理请求视图
- 页签名称、空态文案、顶部 summary 与真实业务语义不一致
- 用户会把一个“好友请求历史页”误以为是“新请求 inbox”，这会直接影响请求处理心智

建议：

- 明确决定 requests 页到底是“待处理 inbox”还是“完整历史”
- 如果要保留历史，请改文案和计数语义；如果要做“新的朋友”，就把页面和计数收口到 pending/new 请求
- 补回归测试，覆盖“requests 页计数和列表语义与产品定义一致”的路径

### F-148：聊天页从私聊发起“建群”时，当前对话对象会被错误排除在新群之外

状态：已修复（2026-04-14）

现状：

- [chat_group_flow.py](/D:/AssistIM_V2/client/ui/windows/chat_group_flow.py) 的 `show_start_group_dialog()` 先解析当前 direct chat 的 `counterpart_id`
- 同文件 `_merge_group_picker_contacts()` 会把这个 `counterpart_id` 从好友候选里排除
- [group_creation_dialogs.py](/D:/AssistIM_V2/client/ui/windows/group_creation_dialogs.py) 的 `StartGroupChatDialog` 又再次用 `excluded_contact_id` 把对方过滤掉
- 最终 `_create_group_async()` 只把当前选中的 `_selected_contacts()` 传给 `create_group()`；当前私聊对象根本不会自动加入新群

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_group_flow.py](D:\AssistIM_V2/client/ui/windows/chat_group_flow.py)
- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)

影响：

- 用户在某个私聊里点“开始群聊/添加成员”时，最终创建出来的新群可能根本不包含当前聊天对象
- 这会让“从当前私聊发起建群”的业务语义彻底走偏
- 连新群的 member preview 也会随之缺少当前对话对象，形成完整链路上的错误结果

建议：

- 当前 direct chat 的 counterpart 应被视为隐式已选成员，而不是直接从候选和最终 `member_ids` 里剔除
- 如果产品真想做“只从当前页再选别的人”，也必须在 UI 上明确说明“当前对象会自动加入”
- 补回归测试，覆盖“从私聊发起建群后，新群成员包含当前私聊对象”的路径

### F-149：聊天页的私聊建群选择器把好友快照冻结在打开瞬间，弹窗期间好友变化不会同步

状态：已修复（2026-04-14）

现状：

- [chat_group_flow.py](/D:/AssistIM_V2/client/ui/windows/chat_group_flow.py) 打开 `StartGroupChatDialog` 前只会加载一次 `load_contacts()`
- [group_creation_dialogs.py](/D:/AssistIM_V2/client/ui/windows/group_creation_dialogs.py) 的 `StartGroupChatDialog` 构造时把这份列表固化进 `self._contacts`
- 后续 `_rebuild_member_list()` 只会在这份静态快照上本地过滤，弹窗打开期间不会再感知联系人主列表的变化

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_group_flow.py](D:\AssistIM_V2/client/ui/windows/chat_group_flow.py)
- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)

影响：

- 如果弹窗打开后新加了好友、删了好友，或联系人资料发生变化，建群候选仍会停留在旧快照
- 这会让聊天页里的“从当前关系网选人建群”能力和联系人主真相出现双轨
- 属于聊天页群组创建主流程的状态冻结问题

建议：

- `StartGroupChatDialog` 应支持在打开期间 refresh 联系人候选，或订阅联系人变化后增量更新
- 不要把“当前好友集合”冻结成打开瞬间的一次性快照
- 补回归测试，覆盖“私聊建群弹窗打开期间联系人变化后，候选列表同步更新”的路径

### F-150：聊天页的私聊建群入口没有并发/单实例保护，重复点击可同时打开多个建群弹窗

状态：已修复（2026-04-14）

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_chat_info_add_requested()` 每次点击都会直接 `schedule_ui_task(self._group_flow.show_start_group_dialog(...))`
- [chat_group_flow.py](/D:/AssistIM_V2/client/ui/windows/chat_group_flow.py) 没有任何 in-flight guard，也没有检查是否已有 `StartGroupChatDialog` 打开
- `_show_dialog()` 只是把 dialog 放进 `_dialog_refs` 保活，并不会阻止重复打开

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\windows\chat_group_flow.py](D:\AssistIM_V2/client/ui/windows/chat_group_flow.py)

影响：

- 用户连续点击“加人/开始群聊”时，可以同时弹出多个建群选择器
- 这会带来重复请求、重复建群和多个旧快照并存的问题
- 属于聊天页主入口缺少最基本的 lifecycle/并发保护

建议：

- 给私聊建群入口加单实例或 in-flight 防抖保护
- 在已有 dialog 打开或 contacts 正在加载时，不应继续创建新的同类窗口
- 补回归测试，覆盖“连续点击建群入口时最多只会存在一个选择器”的路径

### F-151：联系人页侧栏 summary 文案被永久隐藏，计数更新逻辑实际对用户完全不可见

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 在 `_setup_ui()` 里创建了 `self.summary_label`
- 同一段代码里立刻调用了 `self.summary_label.hide()`
- 后续虽然有多处 `_update_summary_counts()`、`reload_data()`、请求/好友增量更新都在持续改这个 label 的文本，但仓库里没有任何再把它 `show()` 回来的路径

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 联系人页上方“friends/groups/requests 计数”这条信息实际上始终不可见
- 当前代码持续维护它的文案和数值，但用户侧拿不到这条状态反馈
- 这属于明确的 UI 状态收口断裂，不是样式偏好问题

建议：

- 如果这条 summary 仍是正式设计的一部分，就应该在 sidebar 中真实显示出来
- 如果产品已经决定不要它，就删除对应的持续更新逻辑，避免维护一条永远不可见的状态
- 补回归测试或 UI smoke，至少验证联系人页计数状态要么可见，要么不再被无效维护

### F-152：联系人页从 Add Friend 发出首条请求后，requests 页可能会切过去但列表仍保持空态

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_on_friend_request_sent()` 在 `status != accepted` 时，会先 `_upsert_request_record(request)`，然后 `_activate_page("requests")`
- 但 `_upsert_request_record()` 只有在 `self._request_items` 已非空，或当前页本来就是 `requests` 时，才会真正插入 request item
- 如果用户原本停在 friends 页，且这恰好是本地第一条 request，那么 `_request_items` 为空、`_current_page != "requests"`，新 request 不会被插入；随后代码再切到 requests 页

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户从 Add Friend 弹窗发出第一条好友请求后，页面会跳到“新的朋友”，但左侧仍可能显示空列表/欢迎态
- 这是联系人请求主流程在空数据账号上的直接错误表现
- 本质上和 `F-136` 是同一类问题，只是发生在“发送第一条请求”而不是“接受第一个好友”

建议：

- request 增量插入不要依赖旧 `_request_items` 或旧页签状态
- 切到 requests 页前，应确保对应 request item 已经插入，或者执行一次最小重建
- 补回归测试，覆盖“friends 页发出第一条请求后，requests 列表立即出现该请求”的路径

### F-153：“新的朋友”页签和计数实际混入了 accepted/rejected/expired 历史记录，不是待处理新请求视图

状态：已修复（2026-04-14）

现状：

- 服务端 [friend_service.py](/D:/AssistIM_V2/server/app/services/friend_service.py) 的 `list_requests()` 会返回当前用户所有 request，而不只是 pending
- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_build_requests_page()` 会把这些请求全部渲染出来
- 同页 `_update_summary_counts()` 又直接把 `len(self._requests)` 写到 requests 计数；但页签文案仍叫 “New Friends”，空态文案也还是 “No new friend requests”

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 当前 requests 页实际是“好友请求历史页”，而不是“新的朋友/待处理 inbox”
- 页签名称、空态文案、顶部计数和真实业务语义已经分叉
- 用户会把一个历史列表误解成待处理新请求视图，进而影响处理预期

建议：

- 明确 requests 页到底是“pending inbox”还是“完整历史”
- 如果保留历史，就改文案和计数语义；如果产品定义是“新的朋友”，就把页面和计数收口到 pending/new 请求
- 补回归测试，覆盖“requests 页文案、计数和数据范围一致”的路径

### F-154：从私聊发起“开始群聊”时，当前对话对象会被从成员候选和最终新群成员里一并排除

状态：已修复（2026-04-14）

现状：

- [chat_group_flow.py](/D:/AssistIM_V2/client/ui/windows/chat_group_flow.py) 会先解析当前 direct chat 的 `counterpart_id`
- 同文件 `_merge_group_picker_contacts()` 先把这个 `counterpart_id` 从好友候选里剔除
- [group_creation_dialogs.py](/D:/AssistIM_V2/client/ui/windows/group_creation_dialogs.py) 的 `StartGroupChatDialog` 构造时又再次用 `excluded_contact_id` 把对方过滤掉
- 最终 `_create_group_async()` 只把当前 `_selected_contacts()` 传给 `create_group()`；当前私聊对象不会自动加入新群

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_group_flow.py](D:\AssistIM_V2/client/ui/windows/chat_group_flow.py)
- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 用户在某个私聊里点“开始群聊/加人”时，创建出来的新群可能根本不包含当前聊天对象
- 这会让“从当前私聊衍生成群聊”这条最核心的业务语义直接走偏
- 不只是 UI 误导，最终传给服务端的 `member_ids` 本身就错了

建议：

- 当前 direct chat 的 counterpart 应被视为隐式成员，而不是直接从候选和最终 `member_ids` 里剔除
- 如果产品另有设计，UI 必须明确说明“当前对象会/不会自动加入”
- 补回归测试，覆盖“从私聊发起建群后，新群成员包含当前私聊对象”的路径

### F-155：当用户除了当前私聊对象外没有别的好友时，“开始群聊”入口会被错误卡成不可用

状态：已修复（2026-04-14）

现状：

- [chat_group_flow.py](/D:/AssistIM_V2/client/ui/windows/chat_group_flow.py) 在加载完 contacts 后，会先 `_merge_group_picker_contacts(contacts, counterpart_id)` 把当前对话对象排除掉
- 如果联系人列表里只剩当前私聊对象，那么过滤后 `contacts` 为空
- 代码会直接弹出 `There are no additional contacts available to add.` 并中止，不会打开 `StartGroupChatDialog`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_group_flow.py](D:\AssistIM_V2/client/ui/windows/chat_group_flow.py)

影响：

- 对“只有一个好友且正和他私聊”的账号来说，聊天页的“开始群聊”入口会直接变成死路
- 这和 `F-154` 是同一根因的另一个直接用户表现：不仅最终成员错了，连入口可达性都被错误削掉了
- 也说明当前 flow 把“当前私聊对象”完全当成了应排除的对象，而不是群聊起点的一部分

建议：

- 如果当前私聊对象应隐式加入新群，就不应该在 `contacts` 为空时直接阻断整个 flow
- 至少要让 dialog 能打开，并明确显示当前对话对象已被包含或作为固定成员
- 补回归测试，覆盖“仅有当前私聊对象时，开始群聊入口仍能正确进入创建流程”的路径

### F-156：联系人页顶部搜索命中联系人后，不会定位联系人详情，而是直接跳去聊天并可能创建新私聊

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_on_search_result_activated()` 无论命中什么类型，都直接 `message_requested.emit(payload)`
- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 的 `_open_contact_target()` 对 `type == "contact"` 会直接走 `chat_interface.open_direct_session(...)`
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `open_direct_session()` 在本地没有现成 direct session 时，会继续调用 `ensure_direct_session()` 去创建后端会话

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 用户在“联系人”页搜索并点击一个联系人，预期通常是查看或定位联系人详情；当前实现却会直接切去聊天页
- 如果该联系人还没有私聊，会额外产生“创建 direct session”的副作用
- 这使联系人页搜索不只是导航错误，还会改变后端会话状态

建议：

- 联系人页内的联系人搜索结果应优先定位到联系人页自身的详情选择流
- 只有明确的“发消息”动作才应走 `open_direct_session()`
- 补回归测试，覆盖“联系人页搜索命中联系人后不会隐式创建私聊”的路径

### F-157：联系人页顶部搜索命中群后，不会定位群详情，而是直接跳去群聊

状态：已修复（2026-04-14）

现状：

- [global_search_panel.py](/D:/AssistIM_V2/client/ui/widgets/global_search_panel.py) 给群搜索结果构造的是 `{"type": "group", "data": group}`
- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 激活结果后仍统一转发到 `message_requested`
- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 对 `type == "group"` 会直接调用 `chat_interface.open_group_session(...)`，而不是切回联系人页当前群详情

证据：

- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)

影响：

- 联系人页的群搜索结果不能完成“定位群资料/群详情”这个联系人域最直接的导航需求
- 用户一点击就被带去聊天页，联系人页上下文被打断
- 联系人与聊天两个领域的导航边界被混在了一起

建议：

- 联系人页里的群搜索结果应优先选中左侧群项并展示右侧详情
- “进入群聊”应该作为详情里的明确动作，而不是搜索结果的唯一去向
- 补回归测试，覆盖“联系人页搜索命中群后优先定位群详情”的路径

### F-158：联系人页发起聊天时会先切到聊天页，失败后仍停在旧聊天界面

状态：已修复（2026-04-14）

现状：

- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 的 `_open_contact_target()` 一开始就 `switchTo(self.chat_interface)`
- 后续才去 `open_session/open_group_session/open_direct_session`
- 如果打开失败，只会弹一个 warning，但不会回退到原来的联系人页

证据：

- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 一旦聊天打开失败，用户会被留在聊天页，并看到旧会话或空态，而不是原来的联系人上下文
- 对联系人页搜索结果、联系人详情里的“Message”按钮、群详情跳转都成立
- 失败路径的 UI 状态不自洽，属于明确的导航错误

建议：

- 先完成目标会话解析/打开，再切换顶层页面
- 或者在失败时显式回退到原来的联系人页
- 补回归测试，覆盖“联系人页跳转聊天失败后仍留在联系人页”的路径

### F-159：联系人页“添加好友”入口没有单实例保护，可同时打开多个 Add Friend 窗口

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_show_add_placeholder()` 在 `friends` 页每次点击都会新建一个 `AddFriendDialog`
- 同文件 `_show_dialog()` 只负责保活引用，不做复用、去重或前置已有窗口
- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `AddFriendDialog` 又会把 `existing_ids` 冻结为打开当时的一次性快照

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户连续点几次“添加”就能同时打开多个 Add Friend 窗口
- 这些窗口各自持有不同时间点的好友快照，会把“是否已是好友/是否还可添加”的判断搞成多份不一致状态
- 在实际使用上很容易演变成重复搜索、重复发送请求和脏窗口残留

建议：

- Add Friend 应改成单实例窗口，已有窗口存在时直接激活它
- 至少需要把“已有好友/待处理请求”判断做成打开时和发送前的双重校验
- 补回归测试，覆盖“重复点击添加按钮不会打开多个好友申请窗口”的路径

### F-160：联系人页“创建群聊”入口没有单实例保护，可同时打开多个 Create Group 窗口

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_show_add_placeholder()` 在 `groups` 页每次点击都会新建一个 `CreateGroupDialog`
- 同文件 `_show_dialog()` 仍只保活引用，不做窗口复用
- [group_creation_dialogs.py](/D:/AssistIM_V2/client/ui/windows/group_creation_dialogs.py) 的 `CreateGroupDialog` 会在构造时冻结 `contacts` 快照；虽然单个 dialog 内部有 `_create_task` 防重复提交，但多个窗口之间互不感知

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)

影响：

- 用户可以同时打开多个建群窗口，并在不同窗口里基于不同好友快照做选择
- 这会带来重复建群、候选成员不一致、窗口间状态分裂等实际问题
- 当前“只防同一窗口重复提交，不防多窗口并发”的边界不完整

建议：

- 联系人页的 Create Group 应收口为单实例入口，已有窗口时直接激活
- 如果保留多窗口，也需要在提交前重新校验当前好友快照并做重复建群防护
- 补回归测试，覆盖“重复点击建群入口不会同时打开多个建群窗口”的路径

### F-161：联系人页切换 tabs 时不会清掉 `_selected_key`，隐藏选中态会跨页残留

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_switch_page()` 只会 `_activate_page(key)` 然后 `_rebuild_current_page()`
- `_restore_selection(full_reload=False)` 在 category 与当前页不一致时，只 `_clear_selection()` 和 `_show_welcome_panel()`，不会把 `_selected_key` 置空
- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_clear_selection()` 也只是取消左侧高亮，不会清理选择状态

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户从 friends 切到 groups/requests 时，旧的 friend/request/group 选择只是“视觉上被藏起来”，并没有真正失效
- 后续很多逻辑仍会把那条旧选择当成当前有效目标
- 这会成为联系人页一串跨页状态错乱问题的根因

建议：

- 切换 tabs 时应显式清空 `_selected_key`，或者把选中态改成按页面独立维护
- 让“当前可见页无选中项”成为正式状态，而不是只隐藏 UI
- 补回归测试，覆盖“切页后旧选择不会继续影响后续刷新和异步回调”的路径

### F-162：联系人页在其它 tab 上执行 full reload 时，会把隐藏的旧详情重新弹回来

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_reload_data_async()` 完成后总会调用 `_restore_selection(full_reload=True)`
- `full_reload=True` 分支不会看 `self._current_page`，只要 `_selected_key` 还指向某个存在的 friend/group/request，就会直接 `_select_friend/_select_group/_select_request`
- 结合 `F-161` 的残留 `_selected_key`，这意味着用户明明已经切到了别的 tab，full reload 仍可能把旧页详情重新选回来

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户停在 groups 或 requests 页时，只要触发一次联系人域 full reload，就可能突然看到之前 friends 页的详情重新出现
- 右侧详情和左侧当前 tab 会脱节
- 这会让“当前到底选中了什么对象”变得不可预测

建议：

- full reload 恢复选择时必须受当前 tab 约束
- 或者按页分别保存/恢复选中项，而不是用一个全局 `_selected_key`
- 补回归测试，覆盖“在 groups/requests 页 reload 后不会恢复 friend 详情”的路径

### F-163：联系人页切页时不会取消 in-flight 的详情 moments 加载，旧详情会异步回弹

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_select_friend()` / `_select_request()` 会启动 `_load_detail_moments(...)`
- 用户切到别的页时，`_restore_selection(full_reload=False)` 在 category mismatch 分支不会调用 `_cancel_moment_load()`
- 同文件 `_load_detail_moments_async()` 完成后只检查 `_selected_key == (kind, selection_id)`；而 `F-161` 里这个 key 又没有被切页清掉，所以旧任务仍会 `detail_panel.set_contact(...)` / `set_request(...)`

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户从 friend/request 详情切到别的 tab 后，旧的 moments 异步请求回来时，右侧详情可能自己跳回原联系人/请求
- 这是一个明确的异步正确性 bug，不需要 full reload 也会发生
- 页面会出现“刚切页又被旧详情抢回来”的错误表现

建议：

- 离开 friend/request 详情时应立即取消 `_moment_load_task`
- 详情异步回调还应额外校验当前 tab 和当前显示实体，而不只是 `_selected_key`
- 补回归测试，覆盖“切页后晚到的 moments 响应不会恢复旧详情”的路径

### F-164：联系人页搜索结果会在跳转成功前先清空关键词和结果，失败后无法直接重试

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_on_search_result_activated()` 先 `clear_search()`，再 `message_requested.emit(payload)`
- `clear_search()` 会直接 `search_box.clear()` 并关闭结果 flyout
- 如果后续 [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 的 `_open_contact_target()` 打开失败，用户已经丢掉了原来的搜索上下文

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)

影响：

- 一旦搜索结果跳转失败，用户既看不到原结果，也保不住原关键词
- 想重试只能重新输入整段搜索词
- 这会把联系人页搜索和聊天跳转错误叠加成更差的失败体验

建议：

- 应在目标打开成功后再清空搜索框和结果
- 或至少在失败时恢复原关键词和结果面板
- 补回归测试，覆盖“联系人页搜索跳转失败后仍保留可重试的搜索状态”的路径

### F-165：联系人页首次展示到首次 reload 完成之间，Add Friend 仍可能把当前用户自己当成可添加对象

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 初始化时 `_current_user_id = ""`，首次 `showEvent()` 只是在 80ms 后 `QTimer.singleShot(..., self.reload_data)`
- 这段窗口内，`friends` 页的加号仍可立即打开 `AddFriendDialog`，而 `_show_add_placeholder()` 传进去的 `current_user_id` 还是空字符串
- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `AddFriendDialog._search_async()` 仅用 `user.id != self._current_user_id` 过滤自己；当 `_current_user_id == ""` 时，这个过滤失效
- 服务端 [user_repo.py](/D:/AssistIM_V2/server/app/repositories/user_repo.py) 的 `search_users()` 也没有排除当前用户

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\server\app\repositories\user_repo.py](D:\AssistIM_V2/server/app/repositories/user_repo.py)

影响：

- 在联系人页初次打开且数据还没拉完时，用户搜索自己会被当成普通可添加对象展示出来
- 后续只能依赖后端再拒绝“加自己”为非法请求
- 这说明 Add Friend 的前置用户态依赖没有真正收口

建议：

- 在 `current_user_id` 尚未就绪前禁用 Add Friend，或延迟到首次 reload 完成后再允许打开
- 搜索结果层也应增加“当前用户绝不显示为可添加对象”的兜底过滤
- 补回归测试，覆盖“联系人页初次展示阶段不会把自己显示成可添加好友”的路径

### F-166：来电接受路径存在 ICE/TURN 刷新竞态，通话窗口可能用旧 ICE 配置启动整场通话

状态：已修复（2026-04-14）

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_invite_received()` 收到来电后，会异步调度 `_prepare_incoming_call_window()`
- `_prepare_incoming_call_window()` 里先 `await self._chat_controller.refresh_call_ice_servers(force_refresh=True)`，然后才 `_ensure_call_window(call, reveal=False)`
- 但用户可以在这之前立即点 toast 接听；随后 `_on_call_accepted()` 会直接 `_ensure_call_window(call, start_media=True)`
- [call_window.py](/D:/AssistIM_V2/client/ui/windows/call_window.py) 构造时会把 `ice_servers` 一次性传进 `AiortcVoiceEngine`
- [aiortc_voice_engine.py](/D:/AssistIM_V2/client/call/aiortc_voice_engine.py) 没有任何“运行中替换 ICE server”能力

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 如果 accepted 事件先创建了 `CallWindow`，而 ICE 刷新稍后才回来，这个窗口整场通话都会沿用旧的 ICE/TURN 配置
- 一旦旧缓存恰好过期、缺 TURN credential，来电路径会比去电路径更容易出现“已接听但媒体打不通”
- 这是明确的初始化竞态，不是体验细节

建议：

- 接听路径应先拿到新的 ICE payload，再允许创建/启动 `CallWindow`
- 或给 `CallWindow/AiortcVoiceEngine` 增加“尚未 start 前可更新 ICE server”的正式入口
- 补回归测试，覆盖“来电秒接时仍使用最新 ICE/TURN 配置”的路径

### F-167：来电预热任务不会在拒接/挂断后取消，晚到任务仍可为已结束通话重新创建隐藏窗口并预开媒体

状态：已修复（2026-04-14）

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_invite_received()` 会无条件调度 `_prepare_incoming_call_window(active_call)`
- `_prepare_incoming_call_window()` 内没有检查当前 `active_call` 是否还存在，也没有核对 call 是否已进入 `rejected/ended/busy`
- 用户如果很快拒接，或对端很快挂断，`_on_call_rejected()` / `_on_call_ended()` 只会关闭当前窗口，不会取消这条已排队的预热任务
- 这条晚到任务随后仍会 `_ensure_call_window(call, reveal=False)` 并 `prepare_media(is_caller=False)`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 已经结束的来电仍可能在后台重新创建一个隐藏 `CallWindow`
- 麦克风/摄像头预热也可能在用户已经拒接后继续发生
- 这属于明确的异步生命周期泄漏

建议：

- 为每个来电预热任务建立可取消句柄，并在 reject/hangup/busy/failed 分支统一取消
- `_prepare_incoming_call_window()` 执行前后都应再校验当前 active call 是否仍匹配
- 补回归测试，覆盖“拒接或未接后不会再创建隐藏通话窗口/预开媒体”的路径

### F-168：通话 UI 只有在收到首个远端媒体帧时才算“已连通”，静音/单向场景会长期卡在 Connecting

状态：已修复（2026-04-14）

现状：

- [call_window.py](/D:/AssistIM_V2/client/ui/windows/call_window.py) 的 `_mark_call_connected()` 只会在 `_on_engine_state_changed("In call")` 时触发
- [aiortc_voice_engine.py](/D:/AssistIM_V2/client/call/aiortc_voice_engine.py) 发出 `"In call"` 的条件是：收到第一帧远端音频，或收到第一帧远端视频
- 同文件里的 `"Connection connected"` / `iceConnectionState in {"connected","completed"}` 只会把 UI 文字维持在 `"Connecting..."`，不会启动 duration timer

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 对端一旦处于静音、无摄像头、仅接通未出媒体，当前 UI 会一直显示 `Connecting...`
- 通话时长也不会开始计时，直到首个远端媒体帧真正到达
- 这会把“媒体暂未输出”和“连接尚未建立”混成一个状态

建议：

- 应把 transport/media 层“已连通”与“已收到首帧媒体”拆成两个状态
- 至少在 `connectionState=connected` 或 accepted 后成功完成媒体协商时进入正式通话态
- 补回归测试，覆盖“对端静音/无媒体输出时，通话仍会进入已连接状态并开始计时”的路径

### F-169：通话引擎后台任务失败不会走正式失败事件，而是从 done callback 抛未处理异常

状态：已修复（2026-04-14）

现状：

- [aiortc_voice_engine.py](/D:/AssistIM_V2/client/call/aiortc_voice_engine.py) 的 `_launch()` 会把协程塞进 task，并在 `add_done_callback()` 里调用 `_finalize_task()`
- `_finalize_task()` 捕获异常后直接 `raise RuntimeError(...)`
- 同文件虽然定义了 `error_reported = Signal(str)`，但当前既没有 emit，也没有任何 UI/manager consumer
- [call_window.py](/D:/AssistIM_V2/client/ui/windows/call_window.py) 只订阅了 `state_changed`、`signal_generated` 和若干设备可用性信号，没有任何正式错误桥接

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)
- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 打开麦克风、打开摄像头、创建 answer/offer 等任一步骤失败时，错误不会变成 `CallEvent.FAILED`
- 失败会退化成事件循环里的未处理 callback 异常，而不是用户可见的正式通话失败状态
- 这会让通话失败链路既不稳定也不可观测

建议：

- 不要在 task done callback 里重新抛异常；应统一发出正式错误信号并上抛到 `CallManager/ChatInterface`
- 把 `error_reported` 真正接入 call failure 状态机，收口到已有的 `CallEvent.FAILED`
- 补回归测试，覆盖“麦克风/摄像头/aiortc 初始化失败会稳定变成通话失败 UI”的路径

### F-170：direct E2EE 只会加密给对方的一个设备，收件人多设备会稳定出现“只有一台能解密”

状态：已修复（2026-04-14）

现状：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `_claim_or_fetch_recipient_bundle()` 会从 `fetch_prekey_bundle(user_id)` 返回的设备列表里直接拿 `bundles[0]`
- `encrypt_text_for_user()` 和 `encrypt_attachment_for_user()` 都只用这一台设备的 prekey/material 产出单个 `recipient_device_id`
- 同文件 `decrypt_text_content()` / `decrypt_attachment_metadata()` 又明确按 envelope 里的单个 `recipient_device_id` 与 `recipient_prekey_id` 解密

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)

影响：

- 对方账号如果同时在线两台设备，direct E2EE 文本和附件只会有其中一台能正常解密
- 另一台设备即使收到同一条消息，也只会落到 `not_for_current_device` / `missing_private_key` 一类状态
- 这不是偶发问题，而是当前 direct E2EE envelope 模型天然只支持单目标设备

建议：

- direct E2EE 需要正式收口成“每个收件人设备一份 envelope”的多设备 fan-out 模型
- 在模型升级前，至少不要把 direct E2EE 宣称成已支持稳定多设备
- 补回归测试，覆盖“同一收件账号多设备同时在线时，两台设备都能解密 direct E2EE 文本/附件”的路径

### F-171：来电方会在对端尚未接听前就发送 offer/ICE，未接听阶段已经进入完整 WebRTC signaling

状态：已修复（2026-04-14）

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_invite_sent()` 在 invite 发出后立刻 `window.prepare_media(...)`，随后马上 `window.activate_signaling()`
- [aiortc_voice_engine.py](/D:/AssistIM_V2/client/call/aiortc_voice_engine.py) 的 `_prepare(is_caller=True)` 会直接创建 local offer 并 `_emit_local_description("call_offer")`
- `activate_signaling()` 会把这批 pending signaling 立即 flush 出去，所以 caller 在对端还没 accept 前就已经发送了 `call_offer`
- 同一个 engine 后续也会继续发送 `call_ice`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 当前“未接听”阶段并不只是一个 invite/ringing 状态，而是已经提前进入 SDP/ICE 交换
- 后续一旦 reject/busy/hangup，前面这批 signaling 仍然已经发出并可能被对端消费
- 这会把“用户是否同意接听”和“媒体协商何时开始”混成一条链

建议：

- 把 `offer/ice` 的正式起点收口到 `call_accept` 之后
- caller 侧可以预热媒体，但不应在 accept 前把 signaling flush 到传输层
- 补回归测试，覆盖“未接听阶段不会发送 `call_offer/call_ice`”的路径

### F-172：来电预热会在用户接听前直接打开本地麦克风/摄像头

状态：已修复（2026-04-14）

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_prepare_incoming_call_window()` 会在用户尚未点 Accept 时就 `window.prepare_media(is_caller=False)`
- [call_window.py](/D:/AssistIM_V2/client/ui/windows/call_window.py) 的 `prepare_media()` 直接调用 engine 的 `prepare()`
- [aiortc_voice_engine.py](/D:/AssistIM_V2/client/call/aiortc_voice_engine.py) 的 `_prepare(is_caller=False)` 会执行 `_ensure_local_audio_capture()`；视频通话还会执行 `_ensure_local_video_capture()`
- 这两条路径都会真正打开本地音视频设备，只是尚未 attach 到 sender

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 用户还没明确同意接听时，本地麦克风/摄像头已经可能被打开
- 即使后面选择拒接，设备预热也已经发生过
- 这不只是性能优化，而是用户同意边界被提前穿透

建议：

- 来电预热最多只应完成窗口和 ICE 准备，不应在 accept 前打开本地音视频采集设备
- 真正的 `_ensure_local_audio_capture/_ensure_local_video_capture` 应延后到接听确认之后
- 补回归测试，覆盖“收到来电但未接听时，不会打开本地麦克风/摄像头”的路径

### F-173：session 级“恢复加密”动作实际会执行全设备 reprovision，并清空所有会话共享的本地 E2EE 状态

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `recover_session_crypto(session_id)` 是按单个 session 暴露的恢复动作
- 但它真正调用的是 [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `reprovision_local_device()`
- `reprovision_local_device()` 内部先 `clear_local_bundle()`，而 `clear_local_bundle()` 会一次性删除 `e2ee.device_state`、`e2ee.group_session_state`、`e2ee.history_recovery_state`、`e2ee.identity_trust_state`
- 随后 `recover_session_crypto()` 只会对当前这个 session 调一次 `recover_session_messages(session_id)`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)
- [D:\AssistIM_V2\client\tests\test_service_boundaries.py](D:\AssistIM_V2/client/tests/test_service_boundaries.py)

影响：

- 用户在某一个 session 上点“恢复加密”，实际会清掉整台设备共享的 sender-key、history recovery、identity trust
- 但 UI/返回值仍把它包装成“当前 session 的恢复动作”
- 这会把一个 session 级入口变成全局破坏性操作，而且只对当前 session 做后续修复

建议：

- 明确把这个动作建模成设备级恢复，而不是 session 级恢复
- 如果必须保留 session 入口，至少要把影响范围和后续全局重建过程显式暴露给用户
- 补回归测试，覆盖“恢复一个 session 不会静默清掉其它 session 共享的本地 E2EE 状态”或改成正式设备级语义

### F-174：服务端没有对通话 offer/answer/ice 做角色和阶段约束，任一参与者都能在 accept 前后任意发送

状态：已修复（2026-04-14）

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `relay_offer()`、`relay_answer()`、`relay_ice()` 都只调用 `_require_participant_call(call_id, user_id)`
- `_require_participant_call()` 只校验“这个 user 是否属于这通 call”，并不会校验当前 call status，也不会校验 caller/callee 角色
- 这意味着 initiator/recipient 任一方都可以调用 offer、answer、ice，只要这通 call 还在 registry 里
- 再结合 `F-171`，当前 caller 也确实会在 accept 前就发 `call_offer/call_ice`

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 通话 signaling 当前缺少“谁在什么阶段可以发什么”的正式边界
- caller 可以在 accept 前发 offer/ice；callee 理论上也可以在错误阶段发 answer/offer
- 协议已经不再是成熟的状态机，而是“只要是参与者就能转发”

建议：

- 服务端应把 signaling 角色和状态机收口成正式约束
- 至少限制为：caller 才能发 offer，callee 才能发 answer，ICE 只能在 accepted/negotiating 阶段转发
- 补回归测试，覆盖错误角色/错误阶段的 signaling 会被明确拒绝

### F-175：设备 reprovision 先删旧设备和本地状态，后注册新设备；中途失败会把本地恢复到半破坏状态

状态：已修复（2026-04-14）

现状：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `reprovision_local_device()` 会先尝试 `delete_device(previous_device_id)`
- 然后立即 `clear_local_bundle()` 清掉本地 `device/group/history_recovery/identity_trust` 四类状态
- 之后才 `_generate_local_bundle()`、`_save_local_bundle(new_bundle)`，最后再 `_register_bundle(new_bundle)`
- 如果 `_register_bundle()` 在最后一步失败，前面的远端删除和本地清空已经发生，函数也没有回滚路径

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)

影响：

- 一次 reprovision 失败，可能直接把旧远端设备删掉，同时把本地 sender-key/history recovery/identity trust 一并清空
- 失败后客户端只剩一份尚未成功注册的新 bundle，整体状态处于明显的半破坏态
- 这会把本应用于恢复的动作本身变成新的数据丢失入口

建议：

- reprovision 应改成“先注册并验证新设备，再切换并清理旧状态”的两阶段流程
- 至少需要本地回滚或失败后可恢复的临时 staging 机制
- 补回归测试，覆盖“新设备注册失败时，不会丢掉旧远端设备和本地恢复材料”的路径

### F-176：导入 history recovery package 后不会刷新会话安全状态，也不会重试当前缓存消息解密

状态：已修复（2026-04-14）

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `import_history_recovery_package()` 只调用 `E2EEService.import_history_recovery_package()`，然后附加一份 diagnostics 返回
- 这条路径没有像 `recover_session_crypto()` 那样走 `_finalize_session_crypto_recovery()`，也不会 `refresh_sessions_snapshot()`
- 同时它也不会像 [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `recover_session_crypto()` 那样触发 [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `recover_session_messages(session_id)`

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\tests\test_e2ee_auth.py](D:\AssistIM_V2/client/tests/test_e2ee_auth.py)

影响：

- 用户成功导入历史恢复包后，当前 session 的 `session_crypto_state` 仍可能继续显示旧的 `reprovision_device/missing_private_key`
- 已缓存的加密消息和附件也不会被立即重试解密，界面会继续停留在 placeholder
- 功能上“恢复包已经导入成功”，但聊天页和会话安全 UI 不会立即收口

建议：

- 导入 recovery package 后应统一走一条正式的“刷新 session crypto state + 重试本地消息解密”闭环
- 至少要对当前打开的 E2EE session 立即重跑 `recover_session_messages()` 和会话安全摘要
- 补回归测试，覆盖“导入恢复包后，当前加密会话会立即从 recovery required 收口到 ready”的路径

### F-177：history recovery 导出目标没有被限制为当前账号，当前实现允许把恢复包导出给任意用户设备

状态：已修复（2026-04-14）

修复说明：

- 用户、会话、消息和群成员头像现在统一通过 `resolve_user_avatar_url()` 输出，只读序列化不再混入兼容写操作。

修复说明：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 现在在导出 recovery package 前强制 `target_user_id == current_user_id`。
- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 也要求 `target_user_id == source_user_id` 且 `source_user_id` 非空，history recovery package 不再能导出给其它账号设备。
- 已补 `test_auth_controller_export_history_recovery_package_rejects_cross_account_target` 和 `test_e2ee_service_history_recovery_rejects_cross_account_export`。

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `export_history_recovery_package()` 接口允许传入可选 `target_user_id`
- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `export_history_recovery_package(target_user_id, target_device_id, ...)` 也直接接受任意目标用户
- 服务端 [keys.py](/D:/AssistIM_V2/server/app/api/v1/keys.py) 的 `/keys/prekey-bundle/{user_id}` 和 `/keys/prekeys/claim` 都没有把目标限制为“当前账号的其它设备”
- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `list_prekey_bundles()` / `claim_prekeys()` 也只是校验设备存在，不校验目标 user 与当前 user 的关系

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)
- [D:\AssistIM_V2\server\app\api\v1\keys.py](D:\AssistIM_V2/server/app/api/v1/keys.py)
- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)

影响：

- 当前“历史恢复包”本该是同账号设备迁移材料，但实现上可以导出到任意目标用户设备
- 这会把设备恢复边界从“我的旧设备 -> 我的新设备”扩大成“任意用户 -> 任意设备”
- 设计语义和安全边界都没有收口

建议：

- history recovery 正式语义应限制为“同一账号设备间迁移”，服务端和客户端都要强制校验
- 导出前至少验证 `target_user_id == current_user_id`
- 补回归测试，覆盖“尝试把恢复包导出给别的账号设备会被拒绝”的路径

### F-178：history recovery 导入不校验 source_user，任意加密到当前设备的恢复包都会被本地持久化

状态：已修复（2026-04-14）

修复说明：

- generated group avatar 的成员输入同样走 `resolve_user_avatar_url()`，与其它端点共用当前 avatar state 的只读解析口径。

修复说明：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 调用导入时会把当前账号作为 `expected_source_user_id` 传入 E2EE service。
- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 会校验 inner/outer `source_user_id`、`recipient_user_id` 和当前账号一致，跨账号 package 会被拒绝。
- 已补 `test_e2ee_service_history_recovery_rejects_cross_account_import` 覆盖 recipient/source user 不一致场景。

现状：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `import_history_recovery_package()` 只校验 `scheme`、`recipient_device_id`、以及当前设备是否拥有对应 private prekey
- 解包后它直接把 `payload.source_user_id` 和 `payload.source_device_id` 写入本地 `history_recovery_state`
- 整条链路没有任何“source_user 必须等于当前账号”的校验
- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `import_history_recovery_package()` 也只要求“当前已认证”，没有额外约束

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)

影响：

- 任何只要成功加密到当前设备的 recovery package，都会被当作合法 source device 写入本地恢复状态
- 这会让 `history_recovery_diagnostics` 和本地 key store 混入外部账号来源的 source device 记录
- 再结合 `F-177`，当前跨账号 recovery package 的导出/导入链路实际上是闭合的

建议：

- 导入 recovery package 时必须显式校验 `source_user_id == current_user_id`
- diagnostics 和本地恢复状态不应接收外部账号 source device
- 补回归测试，覆盖“导入来自其它账号的 recovery package 会被拒绝”的路径

### F-179：通话状态机允许 accepted 再被 replay 回 ringing，重复 accept 还会重写 answered_at

状态：已修复（2026-04-14）

现状：

- [call_registry.py](/D:/AssistIM_V2/server/app/realtime/call_registry.py) 的 `mark_ringing()` 不看当前状态，拿到 call 就直接 `status = "ringing"`
- 同文件 `mark_accepted()` 也不看当前状态，重复 accept 会再次 `status = "accepted"` 并重写 `answered_at = utcnow()`
- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `ringing()` / `accept()` 只校验参与者身份，不校验阶段合法性

证据：

- [D:\AssistIM_V2\server\app\realtime\call_registry.py](D:\AssistIM_V2/server/app/realtime/call_registry.py)
- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)

影响：

- 一条晚到或重复的 `call_ringing` 可以把已经 accepted 的通话重新打回 `ringing`
- 一条重复的 `call_accept` 会刷新 `answered_at`，直接影响客户端通话时长和结果消息
- 这说明通话状态机目前不是单向收敛，而是可被 replay/out-of-order 消息回退

建议：

- 服务端应对 `ringing/accept` 建立严格的前置状态约束
- `mark_accepted()` 不应在重复 accept 时重写 `answered_at`
- 补回归测试，覆盖“accepted 后的重复 ringing/accept 不会回退或改写通话时长起点”的路径

### F-180：通话 hangup reason 完全由客户端自报，任何参与者都可以伪造 timeout/busy 等系统终态

状态：已修复（2026-04-14）

现状：

- [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 会把客户端传入的 `data.reason` 原样交给 `CallService.hangup(...)`
- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `hangup()` 只是把 `reason` 归一成小写字符串，然后原样广播给双方
- 客户端 [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_call_end_outcome()` / `_call_end_infobar_text()` 又会按 `call.reason` 把终态解释成 `timeout/cancelled/completed`

证据：

- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 任一参与者都可以主动发送 `call_hangup(reason="timeout")` 或其它系统终态字符串
- 对端 UI 和本地 call result system message 会把这类客户端自报值当成权威结果展示
- 当前“无人接听/已取消/正常结束”并不是服务端权威判断，而是客户端可伪造字段

建议：

- `hangup reason` 应拆成“客户端请求原因”和“服务端权威终态”
- 像 `timeout/busy/rejected` 这类系统终态不应允许由普通客户端直接自报
- 补回归测试，覆盖“客户端伪造 timeout/busy 等 reason 会被服务端拒绝或重写”的路径

### F-181：加密消息更新后如果新密文暂时无法解密，客户端会把旧的本地明文缓存重新贴回去

状态：已修复（2026-04-14）

现状：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `_process_edit()` 会先基于服务端新 payload 构造 `updated_message`
- 然后它先跑 `_decrypt_message_for_display(updated_message)`，如果当前设备暂时解不开新密文，`updated_message.content` 会退回 placeholder
- 紧接着 `_merge_local_encryption_cache(message, updated_message)` 又会把旧消息上的 `local_plaintext/local_metadata` 无条件拷回新消息，只要 `message_id` 相同且 incoming 还是加密消息
- 这条逻辑没有校验新旧 `content_ciphertext`、`recipient_device_id`、`sender_key_id` 或附件 metadata 是否还是同一版本

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 一条已经被编辑成“新密文”的加密消息，只要当前设备暂时缺 key，UI 仍可能继续显示旧版本明文
- 加密附件也会继续复用旧的 `local_metadata/name/file_type/size`
- 这会把“当前拿不到新密文的解密能力”伪装成“看起来还能正常读旧内容”，属于明确的一致性错误

建议：

- 只有在确认新旧密文版本等价时，才允许复用本地 `local_plaintext/local_metadata`
- 对 edit/refresh 路径至少增加 `content_ciphertext`、`sender_key_id`、`recipient_device_id` 等字段比对
- 补回归测试，覆盖“编辑后的新密文解不开时不会把旧明文重新贴回 UI”的路径

### F-182：未接听阶段的早到 signaling 可能直接把来电窗口弹出来，绕过原本的隐藏预热路径

状态：已修复（2026-04-14）

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_invite_received()` 只是用 `QTimer.singleShot(0, ...)` 异步调度 `_prepare_incoming_call_window()`
- 真正的隐藏预热窗口是在 `_prepare_incoming_call_window()` 里通过 `_ensure_call_window(call, reveal=False)` 创建
- 但同一个文件的 `_on_call_signal()` 如果先收到 `call_offer/call_ice`，而此时 `_call_window` 还没来得及建出来，就会直接走 `_ensure_call_window(active_call, start_media=False)` 
- 这条分支没有传 `reveal=False`，默认会把窗口 show/raise/activate

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 由于当前 caller 本来就会在 accept 前发送 `offer/ice`，callee 侧一旦出现这类竞态，来电窗口就可能在用户点“接听”前自己弹出
- 这会破坏原本“toast 先提示，窗口只做隐藏预热”的交互边界
- 也说明当前 pre-answer signaling 和 UI 生命周期已经耦合出顺序依赖

建议：

- incoming call 的 pre-answer signaling 不应触发可见窗口创建
- `_on_call_signal()` 在 incoming + 未 accepted 阶段应强制复用隐藏窗口，或只缓存 signaling
- 补回归测试，覆盖“offer/ice 早到时不会在接听前自动弹出通话窗口”的路径

### F-183：任意一条通话 signaling 命令报错，客户端都会把整通电话直接判成 failed

状态：已修复（2026-04-14）

现状：

- [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 发送 `call_invite/call_accept/call_offer/call_answer/call_ice/call_hangup` 时都复用同一个 `msg_id=call_id`
- 服务端 [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 又是按入站 `msg_id` 回 `error`
- 客户端 `CallManager._handle_error_message()` 只要发现 `message.msg_id == active_call.call_id`，就会把整条 `active_call` 直接置成 `FAILED` 并清空
- 它并不知道失败的是 invite、accept，还是某一条单独的 ICE/answer/hangup

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)

影响：

- 一条局部的 `call_ice` 或 `call_answer` 错误，也会让整通电话在客户端 UI 上被判成“通话失败”
- 这会把局部 signaling 错误和整通电话失败混成同一个状态机事件
- 再结合当前通话命令统一复用 `msg_id=call_id`，错误归因会长期失真

建议：

- 通话控制面需要为 invite/accept/hangup 和 offer/answer/ice 拆开独立的请求标识与错误归因
- `_handle_error_message()` 不应仅靠 `call_id` 直接把整通电话判 failed
- 补回归测试，覆盖“单条 ICE/answer 报错不会把整通话直接清成 failed”的路径

### F-184：来电侧没有 unanswered timeout，本地会一直保持响铃/待接听直到外部事件来收口

状态：已修复（2026-04-14）

现状：

- [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 只有 `start_call()` 会 `_arm_unanswered_timeout(call_id)`
- `_handle_invite()` 对 incoming call 只会设置 `_active_call` 并发 `INVITE_RECEIVED`，不会启动任何本地超时任务
- 当前客户端也没有别的 incoming timeout 兜底；如果 caller 侧异常退出，或者服务端/网络没有及时把终态送达，callee 侧 toast 和待接听状态就会一直留着

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 来电方一旦在 invite 后异常消失，callee 侧没有本地 unanswered 收口路径
- 通话 toast、响铃和隐藏预热窗口都可能长期停留在待接听状态
- 这和前面已经确认的服务端 disconnect cleanup 缺口叠在一起时，用户侧会直接看到“永远响铃”的僵尸来电

建议：

- incoming call 也应有本地 unanswered timeout，且和服务端权威终态保持一致
- 至少在 callee 侧补一条“超时后自动 reject/close UI”的兜底路径
- 补回归测试，覆盖“来电后对端消失时，本地不会无限期保持响铃”的场景

### F-185：被撤回的加密附件仍然保留本地下载/打开链路，撤回后依旧可能被继续访问

状态：已修复（2026-04-14）

现状：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `_process_recall()` 只会把消息改成 `RECALLED`，并调用 `_drop_encryption_state()` 删除文本 `encryption`
- 但 `_drop_encryption_state()` 不会清 `attachment_encryption`、`local_metadata`、`local_path`，也不会删本地已下载文件
- 聊天 UI [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_open_message()` / `_open_file_attachment()` 以及 [chat_panel.py](/D:/AssistIM_V2/client/ui/widgets/chat_panel.py) 的 `handle_message_click()` / `open_message_attachment()` 也都没有按 `message.status == RECALLED` 做拦截
- `download_attachment()` 只按 `message_type` 判断是否可下载，同样不看撤回状态

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\widgets\chat_panel.py](D:\AssistIM_V2/client/ui/widgets/chat_panel.py)

影响：

- 一条已经撤回的加密图片/视频/文件，客户端仍可能保留可点击、可下载、可打开的本地链路
- 如果本地已经有 `local_path` 或可继续解密 attachment metadata，撤回后的附件仍可能被继续访问
- 这和“撤回后只保留 notice”语义明显冲突，且对加密附件尤其敏感

建议：

- recall 时应同步清理 `attachment_encryption/local_metadata/local_path`，并收口本地打开链路
- `download_attachment()` 和 UI attachment open callback 都应显式拒绝 `RECALLED` 消息
- 补回归测试，覆盖“撤回后的附件无法再下载、无法再打开”的路径

### F-186：E2EE 本地明文缓存被当成权威数据源，后续解密流程不会再校验当前密文是否匹配

状态：已修复（2026-04-14）

现状：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `decrypt_text_content()` 一进来就优先读取 `encryption.local_plaintext`
- 只要本地 `local_plaintext` 还在，它就直接返回明文，不会再比对 `content_ciphertext/nonce/recipient_device_id`
- 本地数据库 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `_content_for_display()` 也是同一逻辑，加载消息时会直接把 `local_plaintext` 解出来展示
- 这意味着一旦本地缓存和服务端当前密文版本不一致，客户端仍会继续把旧明文当成当前权威内容

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 当前实现没有把“本地明文缓存”和“当前密文版本”绑定起来
- 只要旧 `local_plaintext` 没被清理，后续任何重新加载/重绘都可能继续显示陈旧明文
- 这会把 E2EE 本地缓存从“性能优化”提升成“覆盖权威密文”的第二真相

建议：

- `local_plaintext` 必须绑定到当前 `content_ciphertext` 版本，至少要做版本指纹比对
- 一旦收到新密文或新 nonce，本地旧明文缓存应立即失效
- 补回归测试，覆盖“本地残留旧明文时，不会压过新的加密 payload”的路径

### F-187：E2EE 附件的本地 metadata 缓存也被当成权威数据源，后续不会再校验当前 metadata 密文

状态：已修复（2026-04-14）

现状：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `decrypt_attachment_metadata()` 会优先读取 `attachment_encryption.local_metadata`
- 只要本地 `local_metadata` 存在，它就直接反序列化返回，不会再校验 `metadata_ciphertext/nonce/sender_key_id`
- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `_hydrate_attachment_metadata_for_display()` 又会基于这份 metadata 回填 `name/file_type/size/url/media`
- 这和文本路径一样，把附件本地缓存提升成了另一份权威元数据真相

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 如果附件 metadata 已经在服务端或其它设备上变更，本地仍可能继续展示旧文件名、旧 MIME、旧大小
- 对图片/视频/file 这三类消息，UI 和下载行为都会建立在这份陈旧 metadata 上
- 这和前面的文本缓存问题一样，属于“本地缓存覆盖当前权威密文版本”

建议：

- `local_metadata` 也必须和当前 `metadata_ciphertext` / `sender_key_id` 绑定
- 收到新的附件加密 envelope 后，应优先使旧 metadata cache 失效
- 补回归测试，覆盖“附件 metadata 更新后，旧本地 metadata 不会继续污染展示和打开链路”的路径

### F-188：session 级“恢复加密”执行的是全设备 reprovision，但后续只补救当前一个会话

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `recover_session_crypto(session_id)` 会先调用 `e2ee_service.reprovision_local_device()`
- 这个动作本身是全设备级的，会清空并重建本地 device bundle / recovery / group sender-key 状态
- 但它后面只调用 `message_manager.recover_session_messages(normalized_session_id)`，并只记录当前一个 session 的 `last_message_recovery`
- 代码里没有任何“对其它 E2EE session 统一重试解密/刷新安全状态”的补救路径

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)

影响：

- 用户在某个会话里点“恢复加密”后，实际上影响的是整个设备的 E2EE 运行态
- 但只有当前会话会立即做消息补解密，其它 E2EE 会话会继续停留在旧 placeholder/旧安全摘要
- 这会把一个全局恢复动作包装成“只恢复当前会话”，产品语义和真实副作用不一致

建议：

- 如果恢复动作是 device-global reprovision，后续补救也必须是 device-global
- 至少要对所有 E2EE session 统一刷新 crypto state，并批量重试本地消息解密
- 补回归测试，覆盖“在 A 会话触发恢复后，B/C 等其它加密会话也会同步收口”的路径

### F-189：来电侧没有 unanswered timeout，本地会一直保持响铃/待接听直到外部事件来收口

状态：已修复（2026-04-14）

现状：

- [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 只有 `start_call()` 会 `_arm_unanswered_timeout(call_id)`
- `_handle_invite()` 对 incoming call 只会设置 `_active_call` 并发 `INVITE_RECEIVED`，不会启动任何本地超时任务
- 当前客户端也没有其它 incoming timeout 兜底；来电窗口、toast 和响铃都依赖远端或服务端显式送来 reject/hangup/busy

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 如果 caller 侧在 invite 后异常退出，或者服务端终态没有及时送达，callee 侧会长期停在待接听
- 这会让 toast、响铃和预热窗口一直残留
- 再叠加服务端 disconnect cleanup 缺口时，用户就会直接看到“永远响铃”的僵尸来电

建议：

- incoming call 也要有本地 unanswered timeout，并和服务端权威终态保持一致
- 至少补一条“超时后自动关闭来电 UI / 自动 reject”的兜底逻辑
- 补回归测试，覆盖“来电后对端消失时，本地不会无限期保持响铃”的场景

### F-190：只要通话曾被 accept，客户端最终就可能把它记成“completed”，即使媒体其实从未真正建立成功

状态：已修复（2026-04-14）

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_call_end_outcome()` 只要看到 `call.answered_at is not None`，就会把终态判成 `completed`
- 它并不校验通话是否真的进入过 `In call`，也不看 `CallWindow` 里是否出现过 `connection failed/disconnected`
- [call_window.py](/D:/AssistIM_V2/client/ui/windows/call_window.py) 的 `_on_engine_state_changed()` 只是本地把状态文案切成 `Connection failed/Disconnected`
- 这些引擎层失败状态不会升级成正式 `CallEvent.FAILED`；用户随后一旦挂断，系统消息仍可能按 `completed` 生成

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 一通“已经 accept 但媒体协商始终失败”的电话，最终仍可能被系统消息记成正常完成
- 这会直接污染聊天记录里的通话结果文案和时长统计
- 当前“是否接通”在客户端存在两套口径：一套看 `answered_at`，一套看本地媒体是否真的连通

建议：

- `completed` 不应只靠 `answered_at` 判断，至少要结合正式的 media-connected 状态
- 引擎层 `connection failed/disconnected` 需要升级成正式 call failure/outcome 事件
- 补回归测试，覆盖“accepted 但媒体未建立成功时，不会生成 completed 系统消息”的路径

### F-191：认证失效、restore 失败和正常 logout 都直接绑定到 `clear_chat_state()`，会把本地离线聊天数据一并清空

状态：已修复（2026-04-12）

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `restore_session()` 在 refresh token 过期、token 解密失败、`/auth/me` 返回 `AuthExpiredError/APIError` 时都会直接 `await clear_session()`
- 同文件里的 `logout()` 也在 `finally` 里无条件执行 `clear_session()`，即使后端 logout 因 `NetworkError/APIError` 没完成
- `clear_session()` 会调用 `_reset_local_chat_state()`，而 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `clear_chat_state()` 实际会删除 `messages / sessions / session_read_cursors / contacts_cache / groups_cache / sync cursor / chat.hidden_sessions`

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 当前“认证态失效”和“清除本地离线聊天数据”被硬绑成了同一个动作
- 一次 refresh token 过期、一次 restore 校验失败，甚至一次 logout 请求的网络失败，都会把本地消息、会话、联系人缓存和同步游标一起删掉
- 这会让 auth/runtime 问题直接升级成数据体验问题，也让后续恢复和排障变得更困难

建议：

- 把“认证态收口”和“本地聊天缓存清理”拆成两个正式动作
- auth-loss 默认应先收口 runtime 和传输层，再按产品语义决定是否清本地缓存
- 补回归测试，覆盖“refresh token 失效”“restore 无效”“logout 请求失败”三条路径不会无差别删本地聊天状态

### F-192：authenticated runtime warmup 失败会被静默吞掉，用户会停留在一个没有同步成功的旧壳子里

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `show_main_window()` 会先显示主窗口，再异步 `create_task(self._warm_authenticated_runtime())`
- `_warm_authenticated_runtime()` 里只要 `_synchronize_authenticated_runtime()` 或 `start_background_services()` 抛异常，就会被 `except Exception` 记录日志后直接 `return`
- 这条路径没有任何 InfoBar、没有 retry、也没有回退到 auth 或 loading 态
- 与此同时，[main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 会在构造时立刻 `QTimer.singleShot(0, self.chat_interface.load_sessions)`，先把本地旧快照展示出来

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)

影响：

- 如果启动后 `reload_sync_timestamp()`、`refresh_remote_sessions()` 或后续 warmup 抛错，用户仍会看到一个已经打开的主界面
- 这个界面展示的是本地旧缓存，但没有任何用户可见信号告诉他“同步并没有成功完成”
- 这会把“启动失败/同步失败”伪装成“界面已正常进入”，非常不利于定位问题

建议：

- 把 warmup 明确建成一个可见的 authenticated bootstrap 阶段，不要在失败时静默返回
- 至少补一条用户可见错误和重试入口，必要时回退到 loading / auth-loss 态
- 补回归测试，覆盖“remote session refresh 抛错后，不会留在无提示的 stale shell”路径

### F-193：持久化 auth 快照只剩一半时，`restore_session()` 会直接放过残留的 `auth.user_*`，后续 manager 仍会把它当当前用户上下文

状态：已修复（2026-04-12）

修复记录：

- `restore_session()` 现在要求 `auth.access_token`、`auth.refresh_token`、`auth.user_id`、`auth.user_profile` 四键完整存在；只剩一半时会清理 persisted auth snapshot。
- 这条逻辑复用 auth snapshot 一致性测试，覆盖部分/混合快照不会继续作为当前用户上下文。

原现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `restore_session()` 只要发现 `access_token` 或 `refresh_token` 缺一个，就会直接 `return None`
- 这条返回路径不会清理残留的 `auth.user_id / auth.user_profile`
- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `_get_current_user_context()` 和 [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_get_current_user_context()` 都会回退去读取持久化 `auth.user_profile / auth.user_id`

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 一旦本地 auth 快照落成“token 缺半边、profile 还在”的状态，`restore_session()` 不会主动收口这份残留
- 后续 message/session manager 仍可能把这份旧 `auth.user_*` 当成当前用户上下文，用来补 sender profile、会话展示和 mentions 判断
- 这会让“未恢复成功的认证态”和“仍然存在的当前用户上下文”同时存在

建议：

- `restore_session()` 对半残的 auth 快照不能只返回 `None`，必须主动清理残留 `auth.user_*`
- manager 对持久化 `auth.user_*` 的 fallback 应尽量只在明确 authenticated runtime 下使用
- 补回归测试，覆盖“只有一半 token 留在本地时，不会继续复用旧 user profile”路径

### F-194：离线 `restore_session()` 会直接恢复到已登录主界面，但不会执行 E2EE 设备 bootstrap，也没有后续补跑点

状态：已修复（2026-04-12）

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `restore_session()` 在 `NetworkError` 分支里，只要本地有 `stored_profile` 且 refresh token 未过期，就会 `_apply_runtime_context(cached_user)` 后直接返回
- 这条离线恢复分支不会执行 `_ensure_e2ee_device_registered()`
- 当前仓库里 `ensure_registered_device()` 的正式调用点只有 [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 里的在线 restore 成功路径，以及 login/register 成功路径；没有额外的“联网后补跑”入口

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)

影响：

- 用户在离线场景下可以直接进入已登录主界面，但当前设备的 E2EE 注册态可能并没有完成 bootstrap
- 等网络恢复后，客户端也没有正式的补跑点去补做这一步
- 这会让“已恢复登录”和“已完成加密设备就绪”变成两套不同的 runtime 状态

建议：

- 离线 restore 需要显式标记“auth restored, crypto bootstrap pending”
- 联网恢复后要有正式的补跑 hook，自动补做 `ensure_registered_device()`
- 补回归测试，覆盖“离线恢复启动后重新联网，会补齐设备注册”的路径

### F-195：login/register 的本地状态切换不是 failure-atomic 的，持久化失败会留下“新 token 已进内存、旧本地聊天已被清空”的半登录态

状态：已修复（2026-04-12）

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `_apply_auth_payload(reset_local_chat_state=True)` 会先执行 `_reset_local_chat_state()`，删除本地 chat/session/cache/sync 状态
- 然后它会先 `_set_http_tokens(access_token, refresh_token)`，再去 `_persist_auth_state(...)`
- [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `set_app_state()` 是逐 key 单独 `commit()`，并不是一次事务性提交
- 如果持久化阶段抛错，auth UI 只会在 [auth_interface.py](/D:/AssistIM_V2/client/ui/windows/auth_interface.py) 里展示“登录失败/注册失败”，但不会回滚已经设置到 HTTP client 的新 token，也不会恢复刚刚清掉的本地聊天状态

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\ui\windows\auth_interface.py](D:\AssistIM_V2/client/ui/windows/auth_interface.py)
- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)

影响：

- 只要认证成功后的本地持久化阶段失败，当前进程就可能落进半登录态
- 这时 auth 窗口还在，用户以为登录失败，但 HTTP client 已经带着新 token，旧本地聊天数据却已经被清空
- 这说明登录提交缺少明确的 commit/rollback 边界

建议：

- login/register 成功后的本地状态切换需要有明确事务边界，至少先持久化成功，再切换 runtime
- 如果中途失败，必须同时回滚 HTTP token 和本地 runtime 变更
- 补回归测试，覆盖“persist auth state 失败时，不会留下半登录态”的路径

### F-196：logout 流程会先把主窗口隐藏，再同步等待后端 logout；弱网时用户会看到长时间“窗口消失但没有回到登录页”的停顿

状态：已修复（2026-04-13）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_perform_logout_flow()` 会先 `self.main_window.setEnabled(False)`、`hide()`
- 然后它立刻 `await auth_controller.logout()`
- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `logout()` 会先 `await self._auth_service.logout()`，只有在 `finally` 里才做本地 `clear_session()`
- [http_client.py](/D:/AssistIM_V2/client/network/http_client.py) 的默认请求总超时是 30 秒

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\services\auth_service.py](D:\AssistIM_V2/client/services/auth_service.py)
- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)

影响：

- logout 是一个完全串行的“先藏窗口，再等网络”的链路
- 在弱网、超时或服务端卡顿时，用户会先失去主窗口，但登录页要很久之后才出现
- 从产品感知上看，这和应用卡死几乎没有区别

建议：

- 把“本地退出当前 runtime”和“后端 best-effort logout”拆开，不要让后端请求阻塞 UI 切换
- 至少补一个明确的退出中状态或进度反馈，避免窗口无提示消失
- 补回归测试，覆盖“logout 接口超时/失败时，UI 仍能及时回到登录态”的路径

### F-197：logout 后的 authenticated runtime teardown 是串行 2 秒超时链，单个组件卡住就会把 relogin 路径整体拉长

状态：已修复（2026-04-13）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_teardown_authenticated_runtime()` 会连续调用多个 `_close_optional_component(...)`
- 每个 `_close_optional_component()` 都包了 `asyncio.wait_for(..., timeout=2.0)`
- 这些关闭动作是严格串行执行的，包含 `chat_controller / message_controller / session_controller / message_manager / session_manager / connection_manager / websocket_client / sound_manager`

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 只要有一个或几个组件 close 卡住，整个 relogin 路径就会线性累加等待
- 在最坏情况下，用户会在“主窗口已隐藏、登录页还没回来”的中间态里停留很多秒
- 当前退出链路缺少并发收口和顶层超时预算

建议：

- teardown 应按依赖关系分批并发关闭，而不是逐个串行 `wait_for`
- 给整个 logout/relogin 流程定义一个顶层超时预算，而不是每个组件各等 2 秒
- 补回归测试，覆盖“某个 manager.close() 卡住时，不会把整个 relogin 阻塞太久”的路径

### F-198：启动时只要本地有 token，登录页就会被同步 `restore_session()` 挡住；无缓存资料时，弱网下用户要先等超时才能看到登录页

状态：已修复（2026-04-13）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `authenticate()` 总是先 `await auth_controller.restore_session()`，只有它返回 `None` 后才会创建 `AuthInterface`
- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `restore_session()` 会先走一次 `fetch_current_user()`
- [auth_service.py](/D:/AssistIM_V2/client/services/auth_service.py) 的 `fetch_current_user()` 直接请求 `/auth/me`
- [http_client.py](/D:/AssistIM_V2/client/network/http_client.py) 默认总超时是 30 秒

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\services\auth_service.py](D:\AssistIM_V2/client/services/auth_service.py)
- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)

影响：

- 只要磁盘上还留着 token，应用启动就会先同步等待一次 `/auth/me`
- 如果此时网络很差，而本地又没有可用 `stored_profile`，登录页会被这次 restore 超时硬生生挡住
- 用户在启动阶段既看不到主界面，也看不到登录页，只能等网络超时

建议：

- 把 restore 分成“快速本地判定”和“后台网络验证”两段，不要让 auth UI 被一次远程校验硬阻塞
- 至少为 restore 增加更短的启动超时和可见 loading / fallback 提示
- 补回归测试，覆盖“本地有旧 token、网络超时、没有 cached profile 时，登录页仍能快速出现”的路径

### F-199：即使本地有 cached profile，离线 restore 也要先等 `/auth/me` 超时失败，不能立即进入离线 runtime

状态：已修复（2026-04-13）

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `restore_session()` 只有在 `fetch_current_user()` 抛出 `NetworkError` 之后，才会检查 `stored_profile` 并走离线恢复
- 也就是说 cached profile 不是“先本地恢复、后后台校验”，而是“先网络请求，失败了再本地兜底”
- 当前没有更快的 optimistic local restore 分支

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\services\auth_service.py](D:\AssistIM_V2/client/services/auth_service.py)
- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)

影响：

- 即使设备上已经有可用的 cached profile，离线启动也不会立刻进入本地 runtime
- 用户仍然要先吃完一次网络失败或超时，才能回落到 cached profile
- 这让“离线可恢复启动”在体验上退化成“等远端失败后才能恢复”

建议：

- cached profile restore 应该优先是本地快速路径，远端 `/auth/me` 校验改为后台补证
- 如果坚持网络优先，也至少要给 restore 单独设置更短超时
- 补回归测试，覆盖“有 cached profile 且网络断开时，会立即进入离线主界面”的路径

### F-200：authenticated bootstrap 会重复加载会话列表，两次都走 UI 主链路，属于启动路径上的确定性冗余

状态：已修复（2026-04-13）

现状：

- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 在构造函数里会 `QTimer.singleShot(0, self.chat_interface.load_sessions)`
- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_warm_authenticated_runtime()` 在 `refresh_remote_sessions()` 和 `start_background_services()` 之后，又会再次执行 `self.main_window.chat_interface.load_sessions()`
- 两次调用都发生在正式启动主链路上，而不是一种主路径、一种异常兜底

证据：

- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 启动后会话列表至少会被主动重刷两次
- 在远端快照和本地缓存差异较大时，这会增加不必要的 UI churn 和重绘
- 这也是当前 authenticated bootstrap 缺少单一入口的表现：窗口自己拉一次，app warmup 再拉一次

建议：

- 会话列表加载应收口到一个正式 bootstrap 入口，不要窗口构造和 app warmup 各做一遍
- 如果需要“先本地秒开、后远端刷新”，也应明确分成 preload 和 authoritative refresh 两个阶段
- 补回归测试，覆盖“启动后会话列表只按预期刷新一次 authoritative 结果”的路径

### F-201：冷启动时 `initialize()` 先于认证执行，`SessionManager` 会在 auth 决策前把旧本地会话装进内存

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `run()` 先 `await initialize()`，后 `await authenticate()`
- `initialize()` 里会调用 [chat_controller.py](/D:/AssistIM_V2/client/ui/controllers/chat_controller.py) 的 `initialize()`
- `ChatController.initialize()` 又会进一步调用 [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `initialize()`
- `SessionManager.initialize()` 会执行 `_load_hidden_sessions()` 和 `_load_from_database()`，其中 `_load_from_database()` 会把 `db.get_all_sessions()` 结果直接 `load_sessions(...)` 到内存 `_sessions`

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 在认证是否有效还没判定之前，旧账号本地会话和隐藏会话 tombstone 就已经被装进了当前进程内存
- 如果后续 restore 判定失败，再让用户走登录窗口，这些 pre-auth 会话状态仍然已经存在于 manager 里
- 当前 cold-start login 路径从一开始就不是“空白未认证 runtime”，而是“先加载旧本地会话，再决定认证”

建议：

- 需要把 per-account manager bootstrap 放到认证成功之后，而不是 `initialize()` 阶段一刀切启动
- 至少要把依赖本地会话快照的 `_load_from_database()` 推迟到 authenticated runtime 建立之后
- 补回归测试，覆盖“restore 失败后再登录时，不会先把旧账号会话装进新 runtime”的路径

### F-202：`clear_session()` 只清数据库，不清 `SessionManager` 已加载到内存的 `_sessions`，冷启动 re-auth 时会继续复用旧会话列表

状态：已修复（2026-04-12）

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `clear_session()` 只会 `_reset_local_chat_state()` 和删 `auth.*`
- `_reset_local_chat_state()` 里调用的是 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `clear_chat_state()`，它清的是数据库里的 `messages / sessions / contacts_cache / groups_cache / sync cursor / hidden_sessions`
- 它不会触碰已经初始化过的 [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 内存字段 `_sessions`
- 而冷启动时 `SessionManager.initialize()` 已经先把本地 `sessions` 装进内存

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- restore 失败或登录成功前的 `clear_session()` 只能清掉持久化层，不能清掉当前进程里已经活着的会话列表
- 所以后续 `show_main_window()` 第一次渲染时，仍然可能拿到旧账号 `_sessions`
- 这会把“本地数据已清空”和“内存里仍有旧会话”变成分裂状态

建议：

- `clear_session()` 不能只清 db；至少要同步清理或重建已经初始化过的 session runtime
- 如果继续保留“先 initialize 后 authenticate”的结构，就必须在 auth 失败/切账号时显式 purge manager memory
- 补回归测试，覆盖“restore 失败后登录其它账号时，旧会话不会通过 in-memory `_sessions` 泄漏出来”的路径

### F-203：`clear_session()` 也不会清内存里的 `_hidden_sessions`，本地隐藏策略会跨冷启动 re-auth 暂时泄漏到新 runtime

状态：已修复（2026-04-12）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `initialize()` 会先 `_load_hidden_sessions()`，把 `chat.hidden_sessions` 读到内存 `_hidden_sessions`
- [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `clear_chat_state()` 虽然会删除 app_state 里的 `chat.hidden_sessions`
- 但 [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `clear_session()` 并不会触碰 `SessionManager._hidden_sessions`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)

影响：

- 冷启动时如果先加载了旧账号的本地隐藏 tombstone，再在 auth 过程中清掉数据库，这份隐藏策略仍会留在当前进程内存里
- 后续第一次用这些 in-memory session 做可见性判断时，仍可能按旧账号的本地隐藏策略过滤会话
- 这说明本地 visibility policy 也没有跟着 auth runtime 一起真正销毁

建议：

- `clear_session()` 必须同步清理 `SessionManager` 的内存 tombstone，而不只是删 db
- 更稳妥的做法仍然是认证成功后再构建 session runtime，避免 pre-auth 加载任何 per-account local policy
- 补回归测试，覆盖“旧账号隐藏过的会话，不会在新账号第一次渲染时继续被隐藏”的路径

### F-204：冷启动登录成功后，主窗口第一屏会立刻用 stale session runtime 渲染，并为这些旧会话启动历史预热任务

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的冷启动路径是 `initialize() -> authenticate() -> show_main_window()`
- `show_main_window()` 创建 [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 后，窗口构造函数会 `QTimer.singleShot(0, self.chat_interface.load_sessions)`
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `load_sessions()` 会直接 `list(self._chat_controller.get_sessions())` 渲染左侧会话，并调用 `_schedule_initial_history_prefetch(sessions)`
- `_schedule_initial_history_prefetch()` 又会为前几个 `session_id` 启动 `_warm_history_pages(...)`

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)

影响：

- stale pre-auth session runtime 的影响不只是“会话列表闪一下旧数据”
- 它还会继续触发启动历史预热任务，为这些旧 session_id 做额外的历史加载和缓存准备
- 这意味着错误状态已经进入了 UI 和后台任务两条路径，而不是单纯的视觉抖动

建议：

- 冷启动登录成功后，第一屏渲染前必须先确保 session runtime 已按当前认证态重建
- 历史预热任务不能基于未经认证收口的 session 列表直接启动
- 补回归测试，覆盖“restore 失败后登录新账号时，不会为旧账号 session_id 继续做 startup history prefetch”的路径

### F-205：冷启动登录成功与 logout 后 relogin 走的是两套不同 lifecycle contract，只有后者会在认证后重建 manager runtime

状态：已修复（2026-04-12）

现状：

- 冷启动主路径在 [main.py](/D:/AssistIM_V2/client/main.py) 里是 `initialize() -> authenticate() -> show_main_window()`
- logout 后 relogin 路径则是 `_perform_logout_flow()` 里的 `auth_controller.logout() -> _teardown_authenticated_runtime() -> authenticate() -> initialize() -> show_main_window()`
- 也就是说，只有 relogin 会在认证成功后重新 `initialize()` 一遍 manager/runtime；冷启动登录成功则会直接复用认证前启动好的那些 singleton manager

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 同样是“用户完成一次登录”，冷启动和 relogin 走的是两套不同的 runtime 建立语义
- 前者会复用 pre-auth manager，后者会 rebuild post-auth manager
- 这不仅让行为不一致，也直接解释了为什么冷启动登录成功更容易泄漏 stale local runtime

建议：

- 登录成功后的 authenticated runtime 建立必须只有一套 contract，不能冷启动和 relogin 各走一套
- 更合理的方向是：认证成功后再统一建立 per-account runtime，不在未认证阶段提前把 manager 全部启动起来
- 补回归测试，覆盖“冷启动登录成功”和“logout 后 relogin”两条路径会得到同样的 manager/bootstrap 结果

### F-206：服务端 WebSocket 只在 `auth` 时校验一次 token/session_version，后续整条连接都会被永久信任

状态：已修复（2026-04-13）

现状：

- [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 在 `msg_type == "auth"` 时通过 `_authenticate_connection()` 调用 [auth.py](/D:/AssistIM_V2/server/app/websocket/auth.py) 的 `require_websocket_user_id(...)`
- 这里会校验 access token 和 `session_version`
- 但 auth 成功后，后续所有消息分支都只执行 `_require_authenticated_user(user_id)`，它只是检查闭包里的 `user_id is not None`
- 后续 `sync_messages/chat_message/typing/read/edit/recall/delete/call_*` 都不会再次校验 token 是否过期，也不会重新比对数据库里的 `auth_session_version`

证据：

- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\server\app\websocket\auth.py](D:\AssistIM_V2/server/app/websocket/auth.py)

影响：

- 一旦某条 WS 连接完成过一次 `auth`，服务端后续就会按“这个 connection_id 已经是该用户”持续信任它
- access token 自然过期、refresh 后 token 轮换，甚至 `auth_session_version` 变化，都不会自动让这条已绑定连接失效
- 当前 WS session 的真实有效期，实际上退化成了“连接不断开就一直有效”

建议：

- WS 连接需要有正式的会话有效性模型，不能只在首次 auth 时校验一次
- 至少要在关键命令路径或 heartbeat 上补 session-version revalidation，或者在 session version 变化时主动断开旧连接
- 补回归测试，覆盖“WS auth 成功后，auth_session_version 变化时旧连接不能继续收发业务命令”的路径

### F-207：HTTP auth-loss 不会主动切断当前已认证的 WS 连接，旧 socket 仍会继续接收实时流量

状态：已修复（2026-04-12）

现状：

- [http_client.py](/D:/AssistIM_V2/client/network/http_client.py) 的 `_perform_token_refresh()` 失败后会直接 `clear_tokens()`
- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `_on_tokens_changed()` 在 `access_token` 为空时，只会异步清 `auth.*` 持久化，不会关闭 [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py)
- 客户端也不会在这里把 `_ws_authenticated` 置回 `False`
- 服务端 [realtime/hub.py](/D:/AssistIM_V2/server/app/realtime/hub.py) 的 fanout 是按已绑定的 `connection_id -> user_id` 发的，并不关心客户端内存 token 是否已经清空

证据：

- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\server\app\realtime\hub.py](D:\AssistIM_V2/server/app/realtime/hub.py)

影响：

- 一旦 HTTP refresh 失败，客户端的 HTTP 认证态会丢失，但当前 WS 连接不会被主动收口
- 这条旧 socket 仍然会继续收到聊天消息、已读、群资料更新等实时广播
- 结果就是“HTTP 已失效、WS 仍在线”的分裂态被长期维持

建议：

- token clear / auth-loss 必须升级成顶层事件，同时主动关闭或降级当前 WS session
- 不要再允许 HTTP auth-loss 后继续保留一个业务仍然活着的 WS 通道
- 补回归测试，覆盖“refresh 失败 clear_tokens 后，当前 WS 连接会立刻收口”的路径

修复记录：

- [http_client.py](/D:/AssistIM_V2/client/network/http_client.py) 的 refresh rejected 会通知 auth-loss listener，顶层 [main.py](/D:/AssistIM_V2/client/main.py) 订阅后统一进入 `_handle_auth_lost()`。
- `_handle_auth_lost()` 先 `_quiesce_authenticated_runtime()`，而 `_teardown_authenticated_runtime()` 会关闭 `ConnectionManager` 和底层 `WebSocketClient`，再清 auth runtime。
- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 token listener 在 access token 清空时也会把 `_ws_authenticated/_ws_auth_in_flight` 置回 false，并主动断开当前 websocket。
- 回归测试覆盖 auth-loss 统一 flow、teardown 关闭 connection/websocket，以及 token clear 后连接层主动断开。

### F-208：HTTP auth-loss 后，客户端仍可能继续通过旧 WS 发送业务命令

状态：已修复（2026-04-12）

现状：

- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 `send()` 只检查两件事：底层 `_ws_client.is_connected` 和 `_ws_authenticated`
- 它不会检查当前 `access_token` 是否已经为空，也不会检查 app 是否已经进入 auth-loss / logout 中
- 上一条 `F-207` 里已经确认：`clear_tokens()` 不会主动把 `_ws_authenticated` 清掉，也不会断开现有 WS

证据：

- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)

影响：

- 在 HTTP token 已经失效并被清空之后，聊天发送、typing、已读、编辑、撤回等 WS 命令仍可能继续发出
- 这会让用户处在一个极难理解的状态：HTTP 看起来已掉线，但实时命令仍可能部分可用
- 认证态对外已经不再是单一真相

建议：

- `ConnectionManager.send()` 需要受统一 auth runtime 状态约束，而不只是 `_ws_authenticated`
- 一旦 app-level auth-loss 发生，所有实时业务命令都应立即阻断
- 补回归测试，覆盖“clear_tokens 后不能再通过旧 WS 发送 chat/read/edit/typing”等正式命令的路径

修复记录：

- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 `send()` 对非 auth 消息增加 access token 检查，token 已清空时直接拒绝业务 WS 命令。
- token listener 会在 `clear_tokens()` 后清掉 `_ws_authenticated` 并断开旧 websocket，避免旧 socket 继续承载业务发送。
- 回归测试覆盖 `clear_tokens()` 后 `send_chat_message()` 返回 false、不会写入 websocket send queue，并会触发 disconnect。

### F-209：全仓没有任何消费者订阅 `ConnectionManager` 的 state listener，UI/runtime 根本不知道实时层何时真正断开或恢复

状态：已修复（2026-04-12）

现状：

- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 暴露了 `add_state_listener/remove_state_listener`
- 但当前全仓对 `add_state_listener(` 的搜索结果只有这个方法定义本身，没有任何实际调用点
- 也就是说，主窗口、聊天页、认证控制器、应用顶层都没有正式消费 realtime connection state

证据：

- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)

影响：

- 连接断开、自动重连、transport 已连但 WS 未认证、reconnect 成功等状态变化，当前都只停留在 log 里
- UI 不会据此显示“实时已断开/已恢复”，顶层状态机也不会据此做 auth-loss 或 bootstrap 收口
- 这也是为什么当前很多 transport 问题只能在用户感知成“有些功能突然不工作”之后才暴露

建议：

- realtime connection state 必须进入正式 app/runtime 状态机，至少要有一个顶层消费者
- 主窗口或 Application 应明确消费连接状态，并将其映射成用户可见的 runtime 状态
- 补回归测试，覆盖“reconnect/auth-failed/disconnected”三类状态会被顶层正确感知的路径

修复记录：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 authenticated runtime 初始化现在会调用 `ConnectionManager.add_state_listener()`，由 `Application` 作为顶层消费者接收 realtime state。
- `Application._handle_connection_state_change()` 会记录 `_realtime_connection_state`，并在 `authenticated_ready` 下收到 `DISCONNECTED/RECONNECTING` 时把 lifecycle 降级为 `authenticated_degraded`。
- 回归测试覆盖 authenticated runtime 初始化会订阅 state listener，以及连接从 connected 变为 disconnected 后顶层 lifecycle 降级。

### F-210：authenticated bootstrap 把“transport connect 成功”当成“后台服务已启动”，但它并不等待 WS auth 和首次 sync 完成

状态：已修复（2026-04-13）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `start_background_services()` 只做一件事：`await conn_manager.connect()`
- 之后它就直接记录 `Background services started`
- 但 [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 `connect()` 只保证底层 transport 开始连接
- 真正的 WS 认证是在 `_on_connect()` 后异步 `_authenticate_websocket_nowait()` 里发出的，首次 `sync_messages` 又要等 `auth_ack(success=true)` 才会发

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)

影响：

- 当前 bootstrap 对“实时层是否真的可用”的定义是错位的
- transport 只要连上，app 就认为后台服务已启动；但此时 WS auth 可能还没发、可能失败、首次 sync 也可能还没完成
- 这会让 warmup 结束和 runtime ready 之间出现明显语义空洞

建议：

- authenticated bootstrap 需要区分至少三个阶段：transport connected、ws authenticated、initial sync completed
- 只有到达正式 ready 条件，才能把后台服务视为启动完成
- 补回归测试，覆盖“transport 已连但 auth/sync 未完成时，app 不会误判 runtime ready”的路径

修复记录：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `start_background_services()` 现在先等待 `ConnectionManager.connect()` 完成 WS auth，再等待 `ConnectionManager.wait_for_initial_sync()`，只有完整 initial sync replay 完成后才记录后台服务已启动。
- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 已把 auth 和 sync 拆成正式阶段：`connect()` 不再只表示 transport attempt started，而是等待到 websocket auth 成功、首个 sync request 已正式发出。
- 回归测试覆盖 background services 会在 connect 和 initial sync 两段都完成后才返回。

### F-211：`ConnectionManager.connect()` 和 `start_background_services()` 的返回语义是“已启动尝试”，不是“已连通”，但顶层把它当成功路径使用

状态：已修复（2026-04-12）

现状：

- [websocket_client.py](/D:/AssistIM_V2/client/network/websocket_client.py) 的 `connect()` 只会把状态设成 `CONNECTING`，然后 `self._run_in_worker(self._connect_loop())` 后立刻返回
- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 `connect()` 只是 `await self._ws_client.connect()`，随后直接 `return True`
- [main.py](/D:/AssistIM_V2/client/main.py) 的 `start_background_services()` 则把这一调用包成 `await conn_manager.connect()`，之后立刻记录 `Background services started`

证据：

- [D:\AssistIM_V2\client\network\websocket_client.py](D:\AssistIM_V2/client/network/websocket_client.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 当前 `connect()` 的返回值和 log 都在暗示“连接已成功”，但真实语义只是“后台 worker 已开始尝试连接”
- 顶层 bootstrap 因此拿到了一个过早的“成功”信号
- 这会继续放大前面已经确认的 runtime-ready 错判问题

建议：

- 把 `connect()` 的契约改明确：要么只表示“attempt started”，要么等待到 transport/WS auth 某个正式阶段再返回
- 顶层不要再把当前的 fire-and-forget `connect()` 当作成功收口点
- 补回归测试，覆盖“connect() 返回时尚未真正连通”的契约边界

修复记录：

- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 `connect()` 已改成等待 websocket auth 完成后才返回，不再把“worker 已开始尝试连接”伪装成成功收口。
- transport 已连但 auth 尚未完成时，`connect()` 会继续等待 `auth_ack`；auth timeout、auth rejected、credential clear 或 disconnect 都会让这条等待显式失败。
- 回归测试覆盖 `connect()` 在 transport connect 后仍会停留在 `AUTHENTICATING`，直到 `auth_ack(success=true)` 才返回。

### F-212：`ConnectionState.CONNECTED` 和 `is_connected` 只代表 transport 已连，不代表 WS 已认证，导致连接状态 API 本身失真

状态：已修复（2026-04-12）

现状：

- [websocket_client.py](/D:/AssistIM_V2/client/network/websocket_client.py) 在底层 socket 建立后立刻 `_set_state(ConnectionState.CONNECTED)`
- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 也会在 `_on_connect()` 时马上把自身状态推进到 `CONNECTED`
- 但同一个对象的 `send()` 又要求 `_ws_authenticated` 为真；否则会直接 `Cannot send %s: websocket not authenticated`
- 也就是说，同一时刻 API 可以同时表现成“已连接”和“业务不可发送”

证据：

- [D:\AssistIM_V2\client\network\websocket_client.py](D:\AssistIM_V2/client/network/websocket_client.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)

影响：

- 当前连接状态 API 没法表达“transport connected but ws unauthenticated”这个关键中间态
- 上层如果只看 `state/is_connected`，就会误以为实时层已经可用
- 这不仅影响 bootstrap，也影响 reconnect 后的真实可用性判断

建议：

- 连接状态模型至少要拆成 transport state 和 auth state，或增加正式的 `AUTHENTICATING/AUTHENTICATED` 阶段
- `is_connected` 不能继续承担“业务实时层可用”的含义
- 补回归测试，覆盖“transport connected 但 ws 未认证时，状态 API 不会误报 ready”的路径

修复记录：

- [websocket_client.py](/D:/AssistIM_V2/client/network/websocket_client.py) 的 `ConnectionState` 已增加 `AUTHENTICATING`；[connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 在 transport 建立后先进入该阶段，收到 `auth_ack(success=true)` 后才进入 `CONNECTED`。
- `ConnectionManager.is_connected` 现在只在 websocket 已认证且 state 为 `CONNECTED` 时返回 `True`，不再把“transport 已连、业务未认证”的中间态误报成可用。
- 回归测试覆盖 transport 已连但 auth 未完成时 state 为 `AUTHENTICATING`、`is_connected=False`，收到 `auth_ack` 后才切到 `CONNECTED`。

### F-213：服务端对 WS `auth` 失败只返回应用层 `error`，不会主动关闭 socket，未认证连接会以 transport-connected 形态继续悬挂

状态：已修复（2026-04-12）

现状：

- [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 在 `msg_type == "auth"` 时，如果 [auth.py](/D:/AssistIM_V2/server/app/websocket/auth.py) 的 `require_websocket_user_id()` 抛错，只会 `await _send_app_error(...)` 然后 `continue`
- 它不会关闭当前 websocket，也不会从服务端主动终止这条认证失败的连接
- 客户端侧又已经确认没有把这类 auth error 升级成正式 auth-loss / reconnect 状态机

证据：

- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\server\app\websocket\auth.py](D:\AssistIM_V2/server/app/websocket/auth.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)

影响：

- 一旦 WS 认证失败，系统不会形成一个明确的终态，而是留下一个“底层已连、业务未认证”的悬挂 socket
- 后续客户端和服务端都还要继续为这条死连接维护 transport 生命周期
- 这会把本来应该快速失败收口的 auth 错误拖成长期僵尸态

建议：

- 对明确的 WS auth failure，服务端应主动关闭连接，而不是只发应用层 `error`
- 认证失败的 transport 不应继续以正常连接形态悬挂
- 补回归测试，覆盖“WS auth 失败后连接会被正式收口”的路径

修复记录：

- [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 在处理 `type=auth` 时，如 `_authenticate_connection()` 抛出 `AppError`，现在会先发送应用层 `error`，随后主动 `close(1008)` 并结束该 socket 循环。
- 这让明确的 websocket auth failure 变成一个正式终态，不再允许同一条未认证连接继续存活并等待后续业务消息或再次认证。
- 回归测试覆盖 user-id-only 假认证会先收到 error，再被服务端以 `1008` 正式断开。

### F-214：客户端没有任何 WS auth-handshake timeout/retry 机制，`_ws_auth_in_flight` 可能无限悬挂

状态：已修复（2026-04-12）

现状：

- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 在 `_authenticate_websocket_nowait()` 成功发送 auth 后，只会把 `_ws_auth_in_flight = True`
- 之后只有三种路径会清它：收到 `auth_ack`、收到 `error` 且当前正处于 auth in-flight、或者连接断开
- 当前没有任何 auth-handshake timeout task，也没有“超时后重发 auth / 强制 reconnect”的逻辑

证据：

- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)

影响：

- 如果 auth 包发送后迟迟收不到 `auth_ack/error`，客户端会一直卡在一个未完成的 auth-handshake 中间态
- 这条路径既不会重试，也不会升级成显式失败
- 用户看到的结果通常只是“transport 好像连着，但实时层一直不恢复”

建议：

- 为 WS auth 建立正式的 handshake timeout 和 retry/reconnect 策略
- `_ws_auth_in_flight` 不能继续做一个没有超时边界的布尔标志
- 补回归测试，覆盖“auth 消息发出后服务端无响应时，会触发 timeout 收口”的路径

修复记录：

- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 为每次 websocket auth attempt 增加 `_ws_auth_attempt_id` 和 `WS_AUTH_TIMEOUT_SECONDS` 超时 guard。
- auth 消息发出后如果迟迟没有收到 `auth_ack` 或 auth error，超时任务会清掉 `_ws_auth_in_flight`、发出 `ws_auth_timeout` 错误并主动断开当前 websocket。
- `auth_ack`、auth error、disconnect、token clear 和 close 都会推进 attempt id，使旧超时任务自然失效，不会误伤新一代 auth attempt。
- 回归测试覆盖未响应 auth 会超时断开，以及正常 `auth_ack` 会使 timeout 失效。

### F-215：`MessageEvent.SYNC_COMPLETED` 只表示 `history_messages` 处理完成，不表示 `history_events` 已 replay 完成，sync 完成语义被提前触发

状态：已修复（2026-04-12）

现状：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `_process_history_messages()` 会在处理完消息批后发出 `MessageEvent.SYNC_COMPLETED`
- 但同文件的 `_process_history_events()` 只是顺序 replay event，不会在全部 replay 完成后再发一个更权威的 completion 事件
- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_on_history_synced()` 和 [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_sync_completed()` 都把这条事件当作正式 sync completion 消费

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 当前系统可能在消息批刚落库后就宣布“sync completed”，而 edit/recall/delete/read/group update 这些离线 mutation event 其实还没 replay 完
- 上层一旦把这条事件当成 runtime-ready 或 session-ready，就会基于不完整状态继续往下执行
- 这会让 initial sync 的完成语义天然不可靠

建议：

- 把 initial sync completion 收口成一个正式阶段，至少要覆盖 `history_messages + history_events` 两段都完成
- 现有 `SYNC_COMPLETED` 要么改名为 message-batch completed，要么改成真正的 sync-all completed
- 补回归测试，覆盖“history_events 仍在 replay 时，不会提前宣布 sync completed”的路径

修复记录：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 现在先缓存 `history_messages` 结果，等 `history_events` 全部 replay 完成后才发出 `MessageEvent.SYNC_COMPLETED`；事件 payload 也补上了 `events_replayed`。
- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 inbound message dispatch 已串行化，`wait_for_initial_sync()` 会等到 `history_events` 的 listener 全部处理结束后才返回，不再把“history_events 包已收到”当成 sync 已完成。
- 回归测试覆盖 `history_messages` 单独到达时不会提前发 `SYNC_COMPLETED`，以及 `wait_for_initial_sync()` 会等待 `history_events` listener 实际跑完。

### F-216：`_reset_local_chat_state()` 会重复清理同一组 sync cursor，属于认证收口路径上的确定性冗余

状态：已修复（2026-04-12）

现状：

- [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `clear_chat_state()` 已经会删除 `last_sync_session_cursors / last_sync_event_cursors / last_sync_timestamp`
- 但 [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `_reset_local_chat_state()` 在 `await db.clear_chat_state()` 之后，又会继续调用 [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 `reset_sync_state()`
- `reset_sync_state()` 会再次删除同一组 `last_sync_*` app_state 键

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)

影响：

- auth/runtime 收口路径里对同一批 sync cursor 做了两次持久化删除
- 这虽然不一定造成功能错误，但会增加无意义的数据库写放大和退出路径时延
- 也说明“谁负责 authoritative 清理 sync state”这件事本身没有单一边界

建议：

- sync cursor 的清理由一处 authoritative 路径负责即可，不要同时放在 db.clear_chat_state 和 conn_manager.reset_sync_state 里
- 退出/clear_session 路径应尽量减少重复写库
- 补回归测试，覆盖“clear_session 只执行一次 sync state authoritative cleanup”的路径

修复记录：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `_reset_local_chat_state()` 现在只让 `database.clear_chat_state()` 负责持久化聊天状态与 sync cursor 清理。
- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 增加 `clear_sync_state_memory()`，用于在 durable chat state 已清理后只清空连接层内存 reconnect cursors，不再重复删除 `last_sync_*` app_state。
- 回归测试覆盖 `clear_session()` 只调用一次持久化 chat-state cleanup，以及 `ConnectionManager.clear_sync_state_memory()` 不触碰持久化 cursor。

### F-217：正常 logout 路径会对 `clear_chat_state()` 执行两次，第二次发生在 teardown 末尾，属于重复破坏性清理

状态：已修复（2026-04-12）

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `logout()` 在 `finally` 里会执行 `clear_session()`
- `clear_session()` 内部又会 `_reset_local_chat_state()`，其中包含一次 `db.clear_chat_state()`
- 之后 [main.py](/D:/AssistIM_V2/client/main.py) 的 `_perform_logout_flow()` 还会继续执行 `_teardown_authenticated_runtime()`
- `_teardown_authenticated_runtime()` 末尾再次显式 `await db.clear_chat_state()`

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- logout 主链路对同一批本地聊天状态做了两次全量破坏性清理
- 这会放大退出耗时，也让“到底哪一步才是 authoritative cleanup”变得更模糊
- 结合前面已经确认的大量 race 问题，这种重复 destructive cleanup 只会让状态机更脆弱

建议：

- `clear_chat_state()` 只能留一个 authoritative 调用点
- logout/relogin 流程里先定清楚 teardown contract，再删掉重复的末尾清理
- 补回归测试，覆盖“logout 只会执行一次 chat-state authoritative cleanup”的路径

### F-218：未认证阶段就提前启动了消息发送队列、ACK 检查和通话 WS listener，authenticated-only 子系统被错误前移

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `run()` 在 `authenticate()` 之前先 `initialize()`
- `initialize()` 会调用 [chat_controller.py](/D:/AssistIM_V2/client/ui/controllers/chat_controller.py) 的 `initialize()`
- `ChatController.initialize()` 又会调用 [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `initialize()` 和 [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 的 `initialize()`
- `MessageManager.initialize()` 会启动 `MessageSendQueue`、ACK 检查循环并向 `ConnectionManager` 挂 WS listener
- `CallManager.initialize()` 也会向 `ConnectionManager` 挂 WS listener

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- 当前“未认证启动阶段”并不是一个轻量 auth shell，而是已经把多套 authenticated-only 子系统拉起来了
- 即使用户最终没有恢复登录、甚至直接关掉登录窗口，这些后台对象和任务也已经被创建过
- 这进一步说明 authenticated runtime 没有被建成真正独立的生命周期对象

建议：

- MessageManager / CallManager 这类 authenticated-only 子系统应在认证成功后再初始化
- 未认证启动阶段只保留最小 auth shell 所需对象
- 补回归测试，覆盖“用户未登录前，不会启动发送队列、ACK loop、call WS listener”等后台子系统的路径

### F-219：即使初次 WebSocket 连接同步抛错，`start_background_services()` 仍会无条件记录“Background services started”

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `start_background_services()` 里：
  - 先 `await conn_manager.connect()`
  - 如果抛错，只会 `logger.exception("Initial websocket connect failed")`
  - 然后无论如何都会继续 `logger.info("Background services started")`
- 结合前面已确认的 `connect()` 契约过早返回，这条 started log 的语义更加不可信

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)

影响：

- 这条 log 会把“启动失败”和“后台服务已启动”混成同一个路径
- 在排查 auth/bootstrap 问题时，它会直接误导诊断
- 也说明当前 bootstrap 对失败和成功的正式分支还没有收口

建议：

- `start_background_services()` 必须把失败和成功分成明确分支，不能失败后仍宣称 started
- 如果 connect 只是 attempt started，也应改成更准确的日志和返回语义
- 补回归测试，覆盖“初始 WS connect 失败时，不会记录后台服务已启动”的路径

### F-220：即使用户最终没有登录成功、直接关闭登录窗口，应用也已经提前完成了整套 chat runtime 的初始化和本地状态加载

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `run()` 顺序是 `initialize() -> authenticate()`
- `authenticate()` 如果用户关闭 [auth_interface.py](/D:/AssistIM_V2/client/ui/windows/auth_interface.py) 登录窗口，会直接返回 `False`
- 但在这之前，`initialize()` 已经做完了 database connect、HTTP/WS client 创建、ConnectionManager initialize、MessageManager initialize、SessionManager initialize、ChatController initialize、SoundManager initialize
- 其中 [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 还会从数据库加载本地会话和隐藏状态

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\windows\auth_interface.py](D:\AssistIM_V2/client/ui/windows/auth_interface.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 当前 auth shell 不是“先决定是否登录，再建 authenticated runtime”，而是“先把 authenticated runtime 大半建出来，再问用户要不要登录”
- 如果用户只是打开应用看一眼然后关登录框，也已经付出了整套本地 chat runtime 启动成本
- 这既是性能问题，也是前面诸多 pre-auth stale state 问题的共同根因

建议：

- `initialize()` 需要拆成 unauthenticated bootstrap 和 authenticated runtime bootstrap 两段
- 用户未登录就退出时，不应该提前初始化整套聊天 runtime
- 补回归测试，覆盖“关闭登录窗口退出时，不会预先加载本地会话/发送队列/call listener”的路径

### F-221：`clear_session()` 或 auth-loss 发生后，主窗口用户卡和 profile flyout 没有正式 auth-state 广播，仍会继续展示旧账号身份

状态：已修复（2026-04-12）

修复记录：

- `AuthController` 已增加正式 `auth_state_listener` 广播；`_apply_runtime_context()`、`clear_session()` 和 auth commit 失败回滚都会发出最新 auth snapshot。
- `UserProfileCoordinator` 现在订阅该广播；auth 清空或切号时会主动关闭 profile flyout，并把空用户快照通过 `profileChanged` 推给主窗口用户卡。
- 回归测试覆盖 auth controller 在 login/clear_session 边界都会广播状态变化，shell 身份 UI 不再只能依赖初始化和资料保存事件。

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `clear_session()` 会把 `_current_user` 清空
- 但 [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 里的用户卡只在两处刷新：
  - 初始化时 `self._sync_user_card(self.user_profile.current_user_snapshot())`
  - `user_profile.profileChanged` 信号触发时
- [user_profile_flyout.py](/D:/AssistIM_V2/client/ui/widgets/user_profile_flyout.py) 的 `profileChanged` 只在 coordinator 初始化和用户主动保存资料时发出，不会在 `clear_session()`、token 丢失、forced logout 时自动广播
- 所以只要主窗口没有被立即销毁，侧边栏用户卡和 flyout 就会继续显示旧账号资料

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\ui\widgets\user_profile_flyout.py](D:\AssistIM_V2/client/ui/widgets/user_profile_flyout.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- auth/runtime 当前没有正式的“auth state changed”广播
- 认证已清空、但 shell 仍显示旧账号身份，会直接误导用户
- 这和前面已确认的 `F-084/F-085/F-086` 叠加后，会形成“运行态已失效，但 UI 还看起来像已登录”的僵尸态

建议：

- 建立一条顶层 auth-state 事件，统一广播 authenticated / unauthenticated / auth-loss
- 用户卡、profile flyout、主窗口标题区不要再各自读一次 `current_user` 后长期缓存
- 补回归测试，覆盖 `clear_session()`、forced logout、token loss 后 shell 身份 UI 会同步切到未登录态

### F-222：应用级 startup security / E2EE diagnostics 只在 `initialize()` 和 `authenticate()` 更新，auth 清空后会继续保留“已认证”快照

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_startup_security_status` 和 `_e2ee_runtime_diagnostics` 只在：
  - `initialize()`
  - `authenticate()`
  - `_update_startup_security_status()`
  - `_update_e2ee_runtime_diagnostics()`
 这几条路径里刷新
- 但 [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `clear_session()`、`logout()`，以及 [main.py](/D:/AssistIM_V2/client/main.py) 的 forced logout 处理都不会回写这两份 app 级诊断快照
- 结果是 runtime 已经 `clear_session()` 之后，应用级 diagnostics 仍可能继续暴露 `authenticated=true`、旧 `user_id`、旧 history recovery / current session security 快照

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)

影响：

- 应用内部实际上存在第二套 stale auth state
- 这会让 diagnostics、调试输出、后续安全 UI 判断继续基于旧账号上下文
- 也进一步说明 app-level runtime state 和 auth controller state 没有单一真相

建议：

- auth 切换必须同步刷新 app-level startup security / E2EE diagnostics
- `clear_session()`、forced logout、token loss 都应落到统一的 diagnostics reset 路径
- 补回归测试，覆盖 auth 清空后 diagnostics 会同步切回 unauthenticated 快照

修复记录：

- [main.py](/D:/AssistIM_V2/client/main.py) 增加 `_reset_auth_runtime_snapshots()`，在保留当前 DB security self-check 的同时，把 startup security 和 E2EE runtime diagnostics 重置为 unauthenticated。
- 普通 logout 与 auth-loss flow 在 `clear_session()` 后立即调用该 reset 路径，再关闭旧 `AuthController` 并进入重新认证。
- 回归测试覆盖未认证 auth context 下，旧账号 app-level diagnostics 不会继续保留 `authenticated/user_id/history_recovery/current_session_security`。

### F-223：`force_logout(reason=session_replaced)` 只显示 3 秒 warning，不会冻结主窗口；用户仍可继续操作旧聊天壳子

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_handle_transport_message()` 在收到 `force_logout(session_replaced)` 后会先 `await auth_controller.clear_session()`，再 `await conn_manager.close()`
- 之后如果 `main_window` 还在，只会调用 [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 的 `show_session_replaced_warning()`
- `show_session_replaced_warning()` 只是：
  - `show_from_tray()`
  - 关闭 profile flyout
  - 弹一条 InfoBar
  - 3 秒后 `_request_forced_exit()`
- 这条路径里没有 `main_window.setEnabled(False)`，也没有冻结聊天页/联系人页交互

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)

影响：

- 认证已经清空后，用户仍可在 3 秒窗口里继续浏览甚至点击旧聊天壳子
- 如果主窗口原本在托盘里，这条路径还会主动把旧壳子重新弹出来
- 这会把“账号已被挤下线”的控制事件表现成一个仍可交互的 stale shell

建议：

- forced logout warning 期间必须冻结主窗口交互，或直接切到 dedicated signed-out overlay
- 不要在 auth 已失效后再把旧 main shell 主动 `show_from_tray()`
- 补回归测试，覆盖 session_replaced 后主窗口不可再继续交互

### F-224：`force_logout(session_replaced)` 期间只关闭了 `ConnectionManager`，消息/会话/controller 仍保持存活到窗口真正退出

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 forced logout 处理只做了两件事：
  - `auth_controller.clear_session()`
  - `conn_manager.close()`
- 它不会像正常 logout 那样调用 `_teardown_authenticated_runtime()`
- 所以 [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py)、[session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py)、[chat_controller.py](/D:/AssistIM_V2/client/ui/controllers/chat_controller.py) 等 authenticated runtime 组件都会继续活到主窗口 3 秒后真正关闭

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)

影响：

- forced logout 不是一条真正的 authenticated runtime teardown 路径，只是“先清 auth，再等窗口自己关”
- 这让 stale manager / controller 在 auth 已失效后继续留在内存里
- 也让普通 logout、forced logout、shutdown 三条路径的 teardown contract 进一步分叉

建议：

- forced logout 也应走统一的 authenticated runtime teardown，而不是只关连接
- 至少要在 warning 期间停止 message/session/controller 这类 authenticated-only 子系统
- 补回归测试，覆盖 session_replaced 后 manager/controller 不再继续暴露旧 runtime 状态

### F-225：离线 `restore_session()` 走缓存用户资料成功后，没有任何后续 authoritative profile refresh；主窗口身份 UI 会长期停留在旧快照

状态：已修复（2026-04-13）

修复记录：

- `AuthController.restore_session()` 在走 cached profile fallback 时，现在会标记 `authoritative_profile_refresh_pending`，明确区分“当前只是缓存快照”。
- authenticated runtime warmup 完成后，[main.py](/D:/AssistIM_V2/client/main.py) 会调用 `refresh_current_user_profile_if_needed()`，在网络恢复可用时用 `fetch_current_user()` 把缓存身份快照替换成服务端权威资料并回写本地。
- 回归测试覆盖“离线 restore 用缓存进壳子，随后网络恢复后补刷权威 profile”路径，主窗口身份来源不再长期停留在缓存快照。

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `restore_session()` 在 `fetch_current_user()` 抛 `NetworkError` 时，只要本地 `stored_profile` 可解析，就会直接 `_apply_runtime_context(cached_user)` 并返回成功
- [main.py](/D:/AssistIM_V2/client/main.py) 的后续 warmup 只会：
  - `reload_sync_timestamp()`
  - `refresh_remote_sessions()`
  - `start_background_services()`
- 这里没有任何“联网后再 authoritative 拉一次当前用户资料”的补跑路径
- 仓库里对 `fetch_current_user()` 的调用也只出现在 restore 阶段本身，没有后续 refresh 入口

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\widgets\user_profile_flyout.py](D:\AssistIM_V2/client/ui/widgets/user_profile_flyout.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)

影响：

- 离线 restore 不是“临时用缓存进壳子，稍后自动校正”，而是可能把旧 profile 长期当成当前真相
- 用户卡、profile flyout、依赖 `current_user` 的 UI 都会长期显示旧昵称/头像/资料
- 这说明 auth shell 目前没有“cached profile -> authoritative profile”这一步正式收口

建议：

- 离线 restore 成功后，应在网络恢复或 background services ready 后补一次 authoritative `fetch_current_user()`
- 缓存用户资料只能作为过渡快照，不能长期当真相
- 补回归测试，覆盖“离线 restore -> 网络恢复后，主窗口身份 UI 会自动刷新为服务端权威资料”的路径

### F-226：登录窗的 `closed` 与 `authenticated` 共用同一个 first-win future，关闭窗口与 auth 提交存在竞态，可能把“已提交登录态”误判成取消

状态：已修复（2026-04-12）

修复记录：

- `AuthInterface` 现在显式区分“窗口关闭”和“auth 已提交”：login/register 成功后会先标记 `_auth_committed`，`closeEvent()` 不再把这类关闭继续当成取消。
- `Application.authenticate()` 监听登录窗 `closed` 时也会先检查 `has_committed_auth()`；已提交的 auth shell close 不会再把 `auth_future` 置成失败。
- 回归测试覆盖“登录窗已进入 committed 态时先收到 close，再收到 authenticated”不会把已提交登录误判成取消。

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `authenticate()` 会创建一个 `auth_future`
- 它同时监听 [auth_interface.py](/D:/AssistIM_V2/client/ui/windows/auth_interface.py) 的两个信号：
  - `authenticated` -> `auth_future.set_result(True)`
  - `closed` -> `auth_future.set_result(False)`
- [auth_interface.py](/D:/AssistIM_V2/client/ui/windows/auth_interface.py) 的 `closeEvent()` 无论为何关闭，都会先 `self._cancel_pending_task(self._submit_task)`，然后立刻 `closed.emit()`
- 而 `_perform_login()` / `_perform_register()` 在 `await self._auth_controller.login/register()` 返回后，会同步执行：
  - `last_success_message = ...`
  - `authenticated.emit(user)`
  - `self.close()`
- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `login/register()` 又会在返回前先 `_apply_auth_payload()`，已经把 token / current_user / 持久化 auth state 都写好

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\windows\auth_interface.py](D:\AssistIM_V2/client/ui/windows/auth_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)

影响：

- “窗口被关闭”和“认证被取消”现在不是同一个语义，却被绑到了同一个 first-win future 上
- 一旦用户在 in-flight 登录/注册的边界时刻关闭窗口，应用有可能把这次认证判成取消并走退出路径，但本地 auth payload 已经提交
- 这会把 auth shell 决策和 auth commit 边界打散，留下“应用退出，但下次启动已经带着新登录态”的竞态

建议：

- `authenticate()` 不应直接拿窗口 `closed` 语义当“认证失败/取消”
- 登录提交应有独立的 commit 状态，窗口关闭只能表示“用户请求取消”，不能覆盖已完成的 auth commit
- 补回归测试，覆盖“关闭登录窗与登录请求成功交叉到达时，不会把已提交登录态误判成取消”的路径

### F-227：`session_replaced` warning 期间仍沿用普通窗口关闭语义，用户点关闭或托盘退出会走隐藏/确认分支，而不是强制退出分支

状态：已修复（2026-04-12）

现状：

- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 的 `show_session_replaced_warning()` 只会把 `_force_logout_pending` 置为 `True` 并启动 3 秒 timer
- 但 `closeEvent()` 只看 `_allow_exit` 和托盘可用性，不看 `_force_logout_pending`
- `request_exit()` 也不看 `_force_logout_pending`，仍会弹普通退出确认框
- 所以在 `session_replaced` warning 期间，用户点击窗口关闭按钮时：
  - 有托盘时仍会先 hide to tray
  - 托盘菜单点 Exit 时仍会走普通确认

证据：

- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)

影响：

- server-originated forced logout 被 UI 继续按普通退出流程处理
- 这会让“账号被挤下线”的控制语义和“用户主动退出”的窗口语义继续混在一起
- 也进一步说明 forced logout 没有单独的 shell contract，只是在普通主窗口上临时叠了一层 warning

建议：

- `_force_logout_pending` 应直接接管 closeEvent/request_exit 的分支
- warning 期间所有关闭动作都应统一落到 forced-exit 路径，不再允许 hide to tray 或普通确认框
- 补回归测试，覆盖 `session_replaced` warning 期间点击关闭/托盘退出都只会走强制退出分支

### F-228：`_update_e2ee_runtime_diagnostics()` 在未认证或取诊断失败时会 copy-forward 旧快照，logout 后重新打开登录窗时仍可能保留上一账号的已认证 E2EE 诊断

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_update_e2ee_runtime_diagnostics()` 先读取 `current = self.get_e2ee_runtime_diagnostics()`
- 然后调用 [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `get_e2ee_diagnostics()`
- 只要这一步抛错或返回空，函数就会把 `_e2ee_runtime_diagnostics` 重新写成基于 `current` 的 copy-forward 结果，而不是 unauthenticated reset
- 正常 logout/relogin 路径里，[main.py](/D:/AssistIM_V2/client/main.py) 的 `_perform_logout_flow()` 会在 `authenticate()` 里再次调用 `_update_e2ee_runtime_diagnostics()`，但这时 `auth_controller.clear_session()` 已经执行过、`get_e2ee_diagnostics()` 会因未认证而失败
- 结果就是登录窗重新打开时，app-level `_e2ee_runtime_diagnostics` 仍可能保留上一账号的 `authenticated/user_id/history_recovery/current_session_security`

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)

影响：

- relogin 的 auth shell 不是干净的未认证壳子，而会继续背着上一账号的 E2EE 诊断快照
- 这会把 app-level diagnostics 变成明显的 second truth，并和当前真实 auth state 脱节
- 也解释了为什么前面一批 auth/runtime 问题里，diagnostics 往往比 current_user 更难真正收口

建议：

- `_update_e2ee_runtime_diagnostics()` 在未认证或诊断失败时应显式 reset 到 unauthenticated 默认值，而不是 copy-forward
- logout/relogin 打开 auth shell 前必须完成 app-level diagnostics reset
- 补回归测试，覆盖“logout 后重新出现登录窗时，E2EE diagnostics 不再保留上一账号 authenticated 快照”的路径

修复记录：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_update_e2ee_runtime_diagnostics()` 现在会在 auth controller 没有当前用户时显式走 unauthenticated reset，不再 copy-forward 旧 E2EE 快照。
- logout/auth-loss 清 auth 后也会同步 reset app-level E2EE diagnostics，重新打开 auth shell 前不会携带上一账号诊断状态。
- 回归测试覆盖未认证 auth context 返回旧 authenticated diagnostics 时，应用级快照仍被重置为 unauthenticated。

### F-229：如果 `session_replaced` 控制消息在 auth shell 阶段到达，应用会直接关闭登录窗并退出，而不是保留登录界面

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_handle_transport_message()` 处理 `force_logout(session_replaced)` 时：
  - 先 `clear_session()`
  - 再尝试关闭 `ConnectionManager`
  - 如果 `main_window` 存在，就显示 warning
  - 否则如果 `auth_window` 存在，就直接 `self.auth_window.close(); self.auth_window.deleteLater(); self.auth_window = None`
  - 然后 `self._quit_event.set()`
- 也就是说，只要应用此时处在“只有登录窗、没有主窗口”的 auth shell，收到同样的控制消息不会留在登录界面，而是直接结束整个应用进程

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- `session_replaced` 现在没有统一的“回到未认证壳子”语义，而是根据当前显示哪个窗口决定是 warning 还是直接退出
- 这让 auth shell 和 main shell 对同一条 control event 的收口策略完全不同
- 结合前面已经确认的旧 warmup/旧 transport 竞争问题，这会把“旧代 transport 的控制消息”升级成“直接杀掉当前登录流程”

建议：

- `session_replaced` 应统一收口到 unauthenticated shell，而不是在 auth_window 场景下直接退出应用
- 顶层 control-event 处理要先切 auth state，再决定展示哪个 shell，不要直接以 `main_window/auth_window` 是否存在来分支
- 补回归测试，覆盖“auth shell 阶段收到 session_replaced 时，应用仍留在登录界面而不是直接退出”的路径

### F-230：startup preflight 的 blocking 检查发生在整套 runtime 初始化之后，阻断启动时仍会提前拉起 HTTP/WS/manager/runtime 线程

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `run()` 顺序是：
  - `await initialize()`
  - 再 `preflight = self.get_startup_preflight_result()`
  - 如果 `blocking` 才直接 `return`
- 但 `initialize()` 在这之前已经做完：
  - database connect
  - `get_http_client()`
  - `get_websocket_client()`
  - `ConnectionManager.initialize()`
  - `MessageManager.initialize()`
  - `SessionManager.initialize()`
  - `ChatController.initialize()`
  - `SoundManager.initialize()`
- 其中 [websocket_client.py](/D:/AssistIM_V2/client/network/websocket_client.py) 的 `WebSocketClient.__post_init__()` 还会立即 `_ensure_worker_loop()`，提前拉起专用 WebSocket worker thread

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\network\websocket_client.py](D:\AssistIM_V2/client/network/websocket_client.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- startup preflight 现在不是“最早挡住启动”，而是“整套 runtime 起完后再宣布不能启动”
- 即使本地数据库自检已经决定不能继续，也仍会创建网络 client、后台任务、worker thread、本地会话缓存和 event listener
- 这说明 unauthenticated bootstrap / safety gate / authenticated runtime 三层顺序还没有被顶层严格拆开

建议：

- startup preflight 必须前移到最小 bootstrap 之后、任何 authenticated/runtime-heavy 初始化之前
- preflight blocking 时，不应再创建 WS worker thread、message/session manager 或本地会话缓存
- 补回归测试，覆盖“startup preflight blocked 时，不会初始化 HTTP/WS client、manager、worker thread”的路径

### F-231：顶层缺少 quit/auth-generation guard；一旦 `_quit_event` 或 forced-logout 已经成立，后续 `authenticate()` 仍可能继续成功并把应用推进到下一壳子

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_handle_transport_message()` 在某些分支里会先 `self._quit_event.set()`，或把 `self._forced_logout_in_progress = True`
- 但后续 [main.py](/D:/AssistIM_V2/client/main.py) 的：
  - `authenticate()`
  - `show_main_window()`
  - `_perform_logout_flow()`
  这些顶层状态推进函数都没有检查 `_quit_event.is_set()` 或 `_forced_logout_in_progress`
- `authenticate()` 只要 `restore_session()` 或 auth window 最终返回成功，就会照常返回 `True`
- 上层 `run()` / `_perform_logout_flow()` 也会继续调用 `show_main_window()`

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 应用一旦已经被 control plane 或顶层流程标记为“应当退出/不应继续当前代 runtime”，后续代码仍可能继续推进到下一阶段
- 这会造成 auth shell / main shell 短暂闪现、晚到 success 路径继续落地、旧 quit 决策和新 shell 构建交叉
- 也说明当前顶层 lifecycle 还没有 generation/epoch guard，所有异步分支都在争抢同一条 Application 状态机

建议：

- 在 `authenticate()`、`show_main_window()`、`_perform_logout_flow()` 等顶层推进点统一检查 quit/auth-generation guard
- 任何晚到的 success 路径都不能在旧 generation 上继续构建 shell
- 补回归测试，覆盖“收到 quit / session_replaced 后，晚到的 restore/login 成功不会再推进到 main shell”的路径

### F-232：`show_main_window()` 无条件调度 `_warm_authenticated_runtime()`；即使应用已被标记退出或 forced-logout，仍会再起一轮 sync/connect

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `show_main_window()` 在创建主窗口后，总是执行 `self.create_task(self._warm_authenticated_runtime())`
- 这里没有检查：
  - `_quit_event.is_set()`
  - `_forced_logout_in_progress`
  - 当前 auth generation 是否仍有效
- 而 `_warm_authenticated_runtime()` 会继续：
  - `reload_sync_timestamp()`
  - `refresh_remote_sessions()`
  - `start_background_services()`
- 也就是说，只要某条晚到路径仍成功走到了 `show_main_window()`，就必定再触发一轮 runtime warmup 和 transport connect

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 这会把“已经决定退出的 app”重新拉回一轮 sync/connect/warmup
- 和前面已确认的 `F-066/F-068` 一起看，问题不只是 warmup 不会被取消，而是它在创建时就没有顶层 guard
- 也使得 auth/runtime 的 late-success 路径更容易污染 dead runtime 或下一代 runtime

建议：

- `show_main_window()` 调度 warmup 前必须先检查 quit/auth-generation guard
- authenticated warmup 应和 main shell creation 共享同一个 generation token
- 补回归测试，覆盖“late success path 到达 show_main_window 时，若应用已进入 quit/forced-logout，就不会再起 warmup/sync/connect”的路径

### F-233：顶层 control-event 处理用 `main_window/auth_window` 是否存在来判分支；在 shell 切换空窗期，晚到的 `force_logout` 会直接把应用判成应退出

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_handle_transport_message()` 处理 `force_logout(session_replaced)` 时，核心分支是：
  - `if self.main_window is not None`: 显示 warning
  - `elif self.auth_window is not None`: 关闭登录窗
  - `else`: `self._quit_event.set()`
- 正常 logout / relogin 路径里又存在一个明确的 shell 切换空窗期：
  - `_perform_logout_flow()` 先 `self.main_window.hide()`
  - `_teardown_authenticated_runtime()` 再 `self.main_window.deleteLater(); self.main_window = None`
  - 之后才进入下一轮 `authenticate()`，届时 `auth_window` 才会被创建
- 也就是说，在“旧 main shell 已删、新 auth shell 还没建”的窗口里，如果晚到一个 transport control message，顶层会直接落到 `else -> _quit_event.set()`

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 顶层 control-event 当前不是按 lifecycle state 判定，而是按“此刻哪个窗口对象刚好还在”判定
- 这会让 shell 切换空窗期变成语义错误放大器：同一条 `force_logout` 在这个瞬间会直接杀掉应用，而不是回到正确的 unauthenticated shell
- 也说明 auth/runtime 还没有统一的 shell state machine，窗口存在性被错误拿来当状态机输入

建议：

- control-event 处理应基于正式 lifecycle state，而不是 `main_window/auth_window` 指针是否为空
- logout/relogin 期间应显式建模“transitioning shell”状态，禁止晚到 control message 直接走 `_quit_event.set()`
- 补回归测试，覆盖“shell 切换空窗期收到 session_replaced 时，不会直接退出应用”的路径

### F-234：正常 logout 期间主窗口虽然被 `hide()` 且 `setEnabled(False)`，但 tray 入口仍可把旧壳子重新显示出来

状态：已修复（2026-04-13）

修复：

- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 新增 `begin_runtime_transition()`，logout / auth-loss / quiesce 进入时会冻结 shell restore 路径、关闭 tray attention，并隐藏 tray icon。
- `show_from_tray()` 和 tray alert display gate 现在都会检查 `_shell_transition_active` / `_teardown_started`，runtime teardown 期间不能再把旧主窗口重新拉起。
- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_perform_logout_flow()` / `_handle_auth_lost()` 已统一改为 `self.main_window.begin_runtime_transition()`，不再依赖 `setEnabled(False)+hide()` 这种旁路冻结。

### F-235：logout 后重新登录成功时，auth window 会先关闭，再执行重建 `initialize()`；用户会经历一段没有任何 shell 的空窗期

状态：已修复（2026-04-13）

修复：

- [auth_interface.py](/D:/AssistIM_V2/client/ui/windows/auth_interface.py) 登录/注册成功后不再自行 `close()`；已提交认证时也不再立刻退出 busy state。
- [main.py](/D:/AssistIM_V2/client/main.py) 的 `authenticate()` 在 auth success 后保留当前 auth shell，直到 `show_main_window()` 确认新 main shell 已显示，才统一关闭并释放 auth window。
- relogin 成功到新 runtime bootstrap 完成之间始终还有可见 shell，不再出现 headless gap。

### R-022：应用顶层 lifecycle 没有单一状态源；当前状态被分散编码在窗口存在性、布尔标志、连接态和 auth current_user 里

状态：已修复（2026-04-13）

修复记录：

- [main.py](/D:/AssistIM_V2/client/main.py) 已引入顶层 lifecycle state 与 auth/runtime generation guard，明确区分 unauthenticated、restoring_auth、auth_committing、authenticated_bootstrapping、main_shell_visible、authenticated_ready、authenticated_degraded、auth_lost、tearing_down_runtime、shutting_down 等阶段；晚到 auth/runtime/UI 回调均以 generation/window identity 校验后才能继续推进。

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 同时用这些东西表达“应用当前处于什么阶段”：
  - `self._quit_event`
  - `self._logout_task`
  - `self._forced_logout_in_progress`
  - `self.main_window is not None`
  - `self.auth_window is not None`
- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 又用 `_current_user`、persisted `auth.*`、token listener 表达认证态
- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 还单独维护 `_state`、`_ws_authenticated`、`_ws_auth_in_flight`
- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 则再用 `_force_logout_pending`、`_allow_exit`、tray 可见性表达 shell 可用性

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)

影响：

- 这不是某几个分支漏了判断，而是整个应用没有一个 single-source-of-truth lifecycle state
- 因此任何异步成功/失败/控制消息到来时，都可能命中不同的“局部真相”，继续推进错误分支
- 这正是 `G-03` 里 logout、forced logout、restore、relogin、auth-loss、warmup 反复出现状态裂缝的共同架构根因

建议：

- 引入顶层 `ApplicationLifecycleState + generation token` 作为唯一 authoritative 状态
- 认证态、shell 态、transport ready、teardown in progress 都应统一挂到这套状态机上
- 后续修 `G-03` 时，优先先建这套顶层状态机，再逐条删局部布尔/窗口存在性分支

### F-236：startup preflight 的阻断提示要等 `app.run()` 完整走完 `shutdown()` 之后才显示，用户在失败启动时会先经历一段无反馈等待

状态：已修复（2026-04-13）

修复：

- [main.py](/D:/AssistIM_V2/client/main.py) 新增 `_startup_preflight_is_blocking()`，发现 blocking preflight 时会立刻记录 exit code、写日志并直接调用 `_show_startup_preflight_block_dialog(...)`。
- `run()` 现在在 preflight block 的同一条控制流里立即弹出阻断提示，不再等 `run()` 返回到 `main()` 末尾才显示。
- `main()` 末尾的重复提示入口已删除，避免 shutdown 完成后才补弹一次。

### F-237：logout 后 relogin 的 runtime 重建路径完全绕过了 startup preflight；冷启动和 relogin 不是同一套 safety gate contract

状态：已修复（2026-04-13）

修复：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_continue_authenticated_runtime()` 现在在进入 authenticated runtime bootstrap 之前统一执行 `_startup_preflight_is_blocking()`。
- 冷启动、logout relogin、auth-loss reauth 都会走同一套 preflight gate；一旦 block，会立刻弹出提示、设置 `EXIT_CODE_STARTUP_PREFLIGHT_BLOCKED` 并终止当前 runtime 继续启动。

### F-238：authenticated runtime teardown 通过 `hide()+deleteLater()` 绕开 `MainWindow.closeEvent()`；主窗口的正式关闭语义被顶层生命周期绕开了

状态：已修复（2026-04-13）

修复：

- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 新增 `close_for_runtime_transition()` / `_request_close()`，把“runtime 切换关闭壳子”和“用户请求退出应用”拆成正式 close reason。
- `closeEvent()` 现在统一承接关闭语义；`runtime_transition` 只关闭当前 authenticated shell，不再发 `closed` 去触发 application quit。
- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_teardown_authenticated_runtime()` 已改为调用 `self.main_window.close_for_runtime_transition()` 后再释放窗口对象，不再绕开 `closeEvent()`。

### R-023：`_on_main_window_closed -> _quit_event.set()` 把“主窗口关闭”和“应用生命周期终止”绑成了同一个事件，导致 shell 替换只能走旁路

状态：已修复（2026-04-13）

修复记录：

- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 已将 `runtime_transition` 和 `app_exit` 作为正式 close reason 区分；`close_for_runtime_transition()` 会走 `closeEvent()` 但不会发出 `closed` 触发 `_quit_event`，主窗口替换不再靠 hide/deleteLater 旁路。

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 把 `main_window.closed` 直接连到 `_on_main_window_closed()`
- `_on_main_window_closed()` 的唯一动作就是 `self._quit_event.set()`
- 而 `run()` 顶层又在 `await self._quit_event.wait()`
- 结果是：只要主窗口走正式 closed 语义，整个应用主循环就会结束

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)

影响：

- 应用当前没有“关闭 authenticated shell 但保留进程继续跑 auth shell”的正式一等语义
- 这迫使 logout/relogin/forced logout/runtime rebuild 全部改走隐藏、deleteLater、窗口存在性判分支这类旁路实现
- 从架构上看，这正是前面 `F-233/F-234/F-235/F-238` 一串问题的共同放大器

建议：

- `main_window.closed` 不应直接等价于 application quit；中间至少要经过顶层 lifecycle state 判定
- 顶层应有显式的 shell-transition 事件，例如 `main_shell_closed_for_reauth` / `main_shell_closed_for_exit`
- 修 `G-03` 时，应优先把 `_quit_event` 从“所有主窗口关闭都触发”改成“只有真正 app-exit transition 才触发”

### F-239：`_perform_logout_flow()` 没有顶层异常收口；一旦 reauth/reinitialize/re-show 任何一步抛错，应用会卡成无窗口 headless 状态

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_perform_logout_flow()` 是通过 `self.create_task(...)` 启动的后台 task
- 它在开头就会：
  - `self.main_window.setEnabled(False)`
  - `self.main_window.hide()`
- 但整个函数没有任何最外层 `try/except/finally`
- 后续步骤里这些调用都可能抛异常：
  - `await self.authenticate()`
  - `await self.initialize()`
  - `await self.show_main_window()`
- 如果其中任一步抛错，`Application.create_task()` 的 done callback 只会记录 `Background task crashed` 日志，不会恢复旧窗口、不会显示 auth shell、也不会 `_quit_event.set()`

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- logout/relogin 现在不是 failure-atomic 的顶层状态机
- 旧窗口已经被隐藏，新窗口又没起来时，只要中间一步抛错，应用就会留在无窗口但仍存活的 headless 状态
- 这类问题很难靠单点 bugfix 压住，因为根因是顶层没有“失败后回退到哪个 shell”的正式 contract

建议：

- `_perform_logout_flow()` 必须有最外层异常收口，至少保证失败时能回到 auth shell 或直接进入明确退出路径
- 后台 task 级异常不能只记日志，顶层 lifecycle 转换必须有 user-visible fallback
- 补回归测试，覆盖“relogin 过程中 `authenticate/initialize/show_main_window` 任一步失败时，不会把应用留在无窗口 headless 状态”的路径

### F-240：冷启动主链路对 `authenticate()` / `show_main_window()` 的异常同样没有用户可见收口；启动阶段抛错会直接 shutdown + exit

状态：已修复（2026-04-13）

修复：

- [main.py](/D:/AssistIM_V2/client/main.py) 新增 `EXIT_CODE_STARTUP_RUNTIME_FAILED` 和 `_show_startup_runtime_failure_dialog(...)`。
- `run()` 现在会显式追踪 startup stage；若 `authenticate()` 或 authenticated runtime/bootstrap 阶段抛错，且还没有 live main shell，会立刻弹出用户可见错误提示，再进入明确 shutdown 路径。
- 这样冷启动认证失败或主窗口构建失败不再只是静默 shutdown + exit。

### F-241：`_pending_auth_success_message` 不是 auth-generation scoped；只要 auth 成功后主壳子没真正展示，上一代成功提示就会泄漏到下一代 shell

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 里 `_pending_auth_success_message` 只在两处被处理：
  - `authenticate()` 里的 `_on_authenticated()` 负责写入
  - `show_main_window()` 里 `InfoBar.success(...)` 之后负责清空
- 除此之外：
  - `logout`
  - `forced logout`
  - `authenticate()` 取消
  - `initialize()/show_main_window()` 失败
  - `_quit_event` 进入退出路径
  都不会清这个字段
- 这意味着只要一次 auth 已经成功、但后续没有真正完成 `show_main_window()`，这条 success message 就会继续挂在 `Application` 顶层对象上

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 成功提示会跨 auth generation 泄漏
- 下一次真正展示主窗口时，用户可能看到上一账号、上一轮登录或上一轮注册留下的 welcome / account-created 提示
- 这再次说明顶层 UI transient 不是跟着 auth lifecycle 走，而是挂在进程级 `Application` 对象上裸奔

建议：

- 把成功提示改成 auth-generation scoped transient，而不是全局字符串
- 所有 auth 失败、取消、forced logout、quit、rebuild 失败路径都要统一清理这类 transient
- 补回归测试，覆盖“auth 成功后 `show_main_window()` 没完成时，不会把 success message 泄漏到下一代 shell”的路径

### F-242：关闭登录窗会直接取消 in-flight `login/register` 任务；如果后端已接受认证但本地 commit 尚未完成，应用会把这次登录误当成“取消”

状态：已修复（2026-04-13）

修复：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 把 login/register 拆成了两段：先 `request_*_payload()` 拿远端 auth payload，再 `commit_auth_payload()` 提交本地 auth/runtime 状态。
- [auth_interface.py](/D:/AssistIM_V2/client/ui/windows/auth_interface.py) 新增 `_submit_commit_in_progress`；进入本地 commit 阶段后，`closeEvent()` 会直接 `ignore()`，不再 `cancel task + emit closed`。
- 这样“用户取消输入”和“认证已被远端接受、正在本地提交”被正式拆开，本地 commit 窗口不再误判成 auth cancel。

### F-243：`login/register` 在新 auth context 真正确认前就先做 destructive local reset；中途取消或失败会先清旧本地聊天状态，再丢掉新登录

状态：已修复（2026-04-12）

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `login()/register()` 都走 `_apply_auth_payload(..., reset_local_chat_state=True)`
- `_apply_auth_payload()` 的顺序是：
  - 先 `_reset_local_chat_state()`
  - 再 `_set_http_tokens(...)`
  - 再 `_persist_auth_state(...)`
  - 再 `_apply_runtime_context(...)`
  - 最后 `_ensure_e2ee_device_registered()`
- 也就是说，新账号的本地 auth context 还没正式提交前，旧本地聊天状态就已经先被 destructive reset 了
- 如果这条链在 reset 之后、persist/commit 之前因为取消或异常中断，当前流程就既失去了旧本地聊天状态，也没有建立起完整的新 runtime

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\ui\windows\auth_interface.py](D:\AssistIM_V2/client/ui/windows/auth_interface.py)

影响：

- `login/register` 不是 failure-atomic 的
- 一次中途取消或异常不仅可能留下半登录态，还会先把旧本地聊天缓存、sync cursor 之类的状态清掉
- 这说明 auth commit boundary 目前仍然没收口：真正 destructive 的本地 reset 发生得太早

建议：

- 本地 destructive reset 必须后移到“新 auth context 已经可确认提交”的阶段，或者至少做到可回滚
- 明确定义 `login/register` 的 commit point，不要继续把清旧状态放在 commit 之前
- 补回归测试，覆盖“reset 已发生但 persist/runtime apply 尚未完成时任务被取消”的路径

### F-244：认证成功提示先于 authenticated runtime warmup；即使后续 sync/connect 立即失败，主壳子也会先显示“登录成功”

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `show_main_window()` 在主窗口一显示出来就会：
  - 立刻消费 `_pending_auth_success_message`
  - 立刻 `InfoBar.success(...)`
  - 然后才 `create_task(self._warm_authenticated_runtime())`
- 但 `_warm_authenticated_runtime()` 里实际还要继续：
  - `reload_sync_timestamp()`
  - `refresh_remote_sessions()`
  - `start_background_services()`
  - 也就是首次 sync / connect / background services 启动
- 而这条 warmup 失败路径当前只会记日志并静默返回

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- UI 上的“Authentication success”并不代表 authenticated runtime 真正 ready
- 用户可能先看到欢迎提示，但主界面随后停在旧缓存、未完成 sync、未真正连上 transport 的半完成状态
- 这进一步放大了前面已经确认的 ready 语义漂移：auth commit、shell visible、runtime ready 现在仍被混成一类

建议：

- success feedback 至少要和“auth committed”与“runtime ready”做语义拆分
- 如果仍保留欢迎提示，也应补一个明确的 post-auth bootstrap 状态，不要让成功提示覆盖 warmup 失败
- 补回归测试，覆盖“show_main_window 成功但 warmup 失败”时的 UI 反馈路径

### F-245：`login/register` 会先把 access/refresh token 装进全局 HTTP client，再去持久化本地 auth；一旦持久化失败，auth UI 会显示失败，但进程内其实已经带上新 token

状态：已修复（2026-04-12）

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `_apply_auth_payload()` 顺序是：
  - `_reset_local_chat_state()`
  - `_set_http_tokens(access_token, refresh_token)`
  - `_persist_auth_state(...)`
  - `_apply_runtime_context(...)`
- 也就是说，全局 HTTP client 会先进入“已带新 token”的状态
- 但如果 `_persist_auth_state()` 里的：
  - `SecureStorage.encrypt_text(...)`
  - `db.set_app_state(...)`
  任一步抛错，异常会直接向上冒泡
- [auth_interface.py](/D:/AssistIM_V2/client/ui/windows/auth_interface.py) 的 `_perform_login()` / `_perform_register()` 会把这类异常当成普通失败，只给用户显示错误，不会回滚刚刚写进 HTTP client 的 token

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\ui\windows\auth_interface.py](D:\AssistIM_V2/client/ui/windows/auth_interface.py)
- [D:\AssistIM_V2\client\network\http_client.py](D:\AssistIM_V2/client/network/http_client.py)

影响：

- UI 看到的是“登录失败 / 注册失败”，但进程内传输层已经处于新账号认证态
- 后续相对路径 HTTP 请求会继续继承这组 token
- 这会把“用户以为没登录成功”和“系统内部已经切换到新 token”这两种状态撕开，进一步放大 auth/runtime 的分裂

建议：

- `_set_http_tokens()` 不能早于 durable auth commit，至少要在持久化成功之后再切全局传输态
- 如果保留现顺序，就必须补失败回滚，把 HTTP token 恢复到旧状态或清空
- 补回归测试，覆盖“本地 auth 持久化失败时，不会留下 live token 但 UI 显示失败”的路径

### F-246：relogin 路径里 `authenticate()` 先于 `initialize()`；新账号认证一成功，`AuthController` 就会把 user context 写进一批仍处于 closed 状态的旧 singleton

状态：已修复（2026-04-13）

修复：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `_apply_runtime_context()` 不再把 `user_id` 立即推进到 `MessageManager/ChatController` 这一批 runtime singleton。
- 现在 auth commit 只提交 persisted auth snapshot、HTTP token、`current_user` 和 auth-state broadcast；runtime-scoped `user_id` 推进留在 authenticated runtime 初始化阶段完成。
- 这样 relogin / restore 成功后，在 runtime rebuild 真正确立前，不会再把新账号身份写进刚关闭过的旧 singleton。

### F-247：`MessageManager/SessionManager/CallManager` 的 `close()` 都不会清空 auth-scoped user state；“closed runtime” 仍会携带账号身份

状态：已修复（2026-04-12）

现状：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `close()` 不会清 `self._user_id`
- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `close()` 不会清 `self._current_user_id`
- [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 的 `close()` 不会清 `self._user_id`
- 它们只是把：
  - `_initialized = False`
  - listener / task / active call / sessions
  之类的运行态资源停掉
- 结果是，manager 即使处于 closed 状态，内存里仍残留账号身份字段

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- “closed” 在当前实现里只代表 listener/task 停了，不代表对象已经回到未认证空白态
- 这正是上一条 `F-246` 能成立的放大器：关闭后的 manager 仍然能继续承载旧账号或新账号 user context
- 任何后续 fallback 读取、晚到调用或半重建路径，都可能踩到这层残留身份状态

建议：

- `close()` 必须把 auth-scoped user state 一并清成未认证默认值
- 不要让“关闭运行态”和“清掉账号上下文”分成两套松散操作
- 补回归测试，覆盖“manager.close() 之后对象不再携带旧账号 user_id”的路径

### F-248：`login/register` 会等待 best-effort E2EE device bootstrap 完成后才向 auth shell 报告成功；认证 UX 被非关键 bootstrap 串行阻塞

状态：已修复（2026-04-12）

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `_apply_auth_payload()` 在完成：
  - `_set_http_tokens(...)`
  - `_persist_auth_state(...)`
  - `_apply_runtime_context(...)`
  之后，还会继续 `await self._ensure_e2ee_device_registered()`
- 而 [auth_interface.py](/D:/AssistIM_V2/client/ui/windows/auth_interface.py) 只有在整个 `await self._auth_controller.login()/register()` 返回后，才会：
  - 设置 `last_success_message`
  - `authenticated.emit(user)`
  - `self.close()`
- `ensure_registered_device()` 虽然异常会被吞成 warning，但它本身仍然是一个额外串行等待点

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\ui\windows\auth_interface.py](D:\AssistIM_V2/client/ui/windows/auth_interface.py)

影响：

- 认证成功反馈和 auth shell 关闭时机被一个 best-effort 的 E2EE bootstrap 绑定了
- 用户看到的是“登录按钮一直忙”，但这段时间里 token、auth snapshot、runtime context 其实可能都已经切过去了
- 这会继续放大“auth committed”和“shell visible”之间的语义混乱

建议：

- E2EE device bootstrap 不应该阻塞 auth shell 的成功提交
- 把它降级成 post-auth warmup 的一部分，或者至少在 UI 上明确区分“已登录”和“正在完成安全初始化”
- 补回归测试，覆盖“E2EE bootstrap 慢/卡住时，登录成功反馈不会被无限后置”的路径

### F-249：`Application.initialize()` 和 `ChatController.initialize()` 形成结构性重复初始化；每次 authenticated bootstrap 都会重复走一次 manager init 层

状态：已修复（2026-04-12）

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `initialize()` 已经依次执行：
  - `msg_manager.initialize()`
  - `session_manager.initialize()`
  - `chat_controller.initialize()`
- 但 [chat_controller.py](/D:/AssistIM_V2/client/ui/controllers/chat_controller.py) 的 `initialize()` 自己又会执行：
  - `await self._msg_manager.initialize()`
  - `await self._session_manager.initialize()`
  - `await self._call_manager.initialize()`
- 由于这些 `initialize()` 大多靠 `_initialized` 短路，所以最后不会重复挂 listener，但顶层结构上已经形成了明确的双层初始化依赖

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)

影响：

- authenticated bootstrap 的正式边界不清晰：到底是应用顶层负责 init manager，还是 controller 自己负责 init 子系统
- 这种结构性重复会继续掩盖真正的 boot contract，也让后续 relogin / rebuild 更难收口
- 从性能和可维护性上看，这属于确定性的冗余初始化路径

建议：

- 统一 authenticated bootstrap 的 ownership：manager 初始化要么归 `Application`，要么归 `ChatController`
- 不要继续保留“双层都能初始化同一批子系统”的结构
- 补回归测试，明确“每一层只初始化自己真正拥有的对象”

### F-250：`AuthController` 构造时就会 eager materialize `MessageManager` 和 `ChatController` 单例；仅仅进入 auth 流程就会把聊天 runtime 对象拉进进程

状态：已修复（2026-04-12）

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `__init__()` 会直接：
  - `self._message_manager = get_message_manager()`
  - `self._chat_controller = get_chat_controller()`
- 而 `ChatController.__init__()` 又会继续 materialize：
  - `SessionManager`
  - `CallManager`
  - `FileService`
- 也就是说，`get_auth_controller()` 不只是拿一个 auth facade，而是会连带把聊天 runtime 相关的一串 singleton 一起实例化

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)

影响：

- “auth shell / 未认证态” 和 “chat runtime / 已认证态” 的对象边界在构造层就已经混在一起
- 这也是为什么 authenticated runtime 很难真正按账号销毁重建：auth 入口自己就持有聊天侧 singleton
- 从架构上看，这会持续放大 `G-03` 里的所有生命周期问题

建议：

- `AuthController` 只应依赖认证域所需最小对象，不应在构造时 eager 拉起聊天 runtime 依赖
- 把聊天 runtime 的 materialization 推迟到 authenticated bootstrap
- 补回归测试，确认“仅打开 auth shell 不会实例化聊天 runtime 单例”

### F-251：authenticated teardown 对 close 超时/异常只是记日志后继续往前走；relogin 会直接复用一批“可能还没真正关干净”的 singleton

状态：已修复（2026-04-13）

修复：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_close_optional_component()` 现在会返回关闭是否成功；`_teardown_authenticated_runtime()` 会聚合关闭失败的组件列表。
- 只要 authenticated runtime 任一核心组件 close 超时或抛错，`_teardown_authenticated_runtime()` 就会直接抛出 runtime teardown incomplete 错误。
- logout / auth-loss / relogin 流程因此不会在半关闭 runtime 上继续 `authenticate()/initialize()`，而是走顶层失败收口并退出，避免直接复用不干净的 singleton。

### F-252：`WebSocketClient.close()` 在 teardown/shutdown 中被“有 ConnectionManager 就跳过”的逻辑挡掉；只要 `ConnectionManager.close()` 失败，底层 transport 就没有兜底关闭

状态：已修复（2026-04-12）

修复记录：

- `Application._teardown_authenticated_runtime()` 和 `Application.shutdown()` 已移除 `skip_if=peek_connection_manager`，即使 `ConnectionManager` 单例仍存在，也会继续执行 `WebSocketClient.close()` 兜底关闭。
- `_close_optional_component()` 已删除无调用方的 `skip_if` 分支，关闭语义只取决于目标组件是否存在和 `close()` 是否在超时内完成。
- 回归测试覆盖 shutdown/logout runtime teardown 在 `ConnectionManager` 存在时仍关闭 websocket client。

原现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 在 `_teardown_authenticated_runtime()` 和 `shutdown()` 里关闭 websocket client 时都用了：
  - `peek_websocket_client`
  - `skip_if=peek_connection_manager`
- 这意味着判断条件只是“ConnectionManager singleton 是否存在”
- 它并不关心：
  - `ConnectionManager.close()` 是否已经成功完成
  - 是否超时
  - 是否抛异常后提前返回
- 只要 `ConnectionManager` 对象还存在，`WebSocketClient.close()` 这个兜底分支就完全不会跑

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\network\websocket_client.py](D:\AssistIM_V2/client/network/websocket_client.py)

影响：

- 一旦 `ConnectionManager.close()` 卡住、超时或异常，底层 websocket transport / worker thread 就没有第二道兜底关闭
- 旧 transport 有机会跨 logout/relogin 甚至 shutdown 边界继续存活
- 这会继续放大 auth/runtime 链上的旧连接残留、晚到控制消息和 transport 污染问题

建议：

- websocket client 的兜底 close 条件必须建立在“connection manager close 是否成功”上，而不是“singleton 是否存在”上
- teardown/shutdown 需要区分“manager close 成功”与“manager object 还活着”这两个完全不同的状态
- 补回归测试，覆盖“ConnectionManager.close() 失败时，WebSocketClient 仍会被兜底关闭”的路径

### R-024：当前所谓的 runtime rebuild 实际并不会创建新的 authenticated runtime 对象图，而是在同一批进程级 singleton 上做 close + mutate + reinitialize

状态：已修复（2026-04-13）

修复记录：

- 核心 authenticated runtime singleton 已从“close 后复用”改成“close 后退休”：Chat/Message/Session/Connection/WebSocket/Sound/Call/Search/Auth 及 AuthController 持有的 service singleton 都会在 close 成功后重置模块级实例，下一代 authenticated runtime 会重新创建对象图。

现状：

- 多个核心对象都是模块级 singleton：
  - `AuthController`
  - `ChatController`
  - `ConnectionManager`
  - `MessageManager`
  - `SessionManager`
  - `CallManager`
- 它们的 `close()` 基本只会：
  - 停 listener / task
  - 清部分内存态
  - 把 `_initialized = False`
- 但模块级 `_xxx = None` 并不会在 logout/relogin 时重置
- 下一轮 authenticated bootstrap 还是对同一批 Python 对象继续 `initialize()` / `set_user_id()` / `connect()`

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- 从架构上看，当前没有“runtime generation”的一等概念，只有“同一批 singleton 反复切换状态”
- 这会持续放大跨代残留、半关闭对象复用、晚到任务污染、auth state 与 runtime state 不一致等问题
- 即使单点 bug 修掉一些，根因仍然会反复从别的 singleton 上冒出来

建议：

- `G-03` 最终要真正收口，必须决定：是引入真正的 per-account runtime object graph，还是补一套严格的代际 guard 和硬重置
- 如果继续保留 singleton 方案，至少要把“未认证态”“认证中”“已认证运行态”“销毁中”做成明确代际模型
- 后续修复优先级应把“close 干净”和“重新创建/硬重置”放到比单点 UI 问题更前的位置

### F-253：`WebSocketClient` 的首次 connect 尝试没有被追踪；logout/teardown 期间无法真正取消这次 in-flight 连接，晚到成功仍可能把旧 transport 拉回 `CONNECTED`

状态：已修复（2026-04-12）

修复记录：

- `WebSocketClient.connect()` 已把首次 `_connect_loop()` 的 worker future 保存到 `_connect_future`，并在完成回调中清理句柄和记录异常。
- `disconnect()` / `close()` 会取消并等待 `_connect_future`，teardown 期间不再丢失首次连接阶段的可取消句柄。
- 回归测试覆盖 close 会取消 in-flight connect future。

原现状：

- [websocket_client.py](/D:/AssistIM_V2/client/network/websocket_client.py) 的 `connect()` 只是：
  - `_set_state(CONNECTING)`
  - `_run_in_worker(self._connect_loop())`
- 但它不会把这次初始 `_connect_loop()` 保存到 `self._connect_task`
- `self._connect_task` 只会在 `_handle_disconnect()` 触发自动重连时才被赋值
- 而 `disconnect()/close()/_cleanup()` 真正能取消的任务集合又只包括：
  - `_receive_task`
  - `_heartbeat_task`
  - `_connect_task`
- 结果就是：首次连接阶段如果正在 `await websockets.connect(...)`，teardown 并没有一个直接可取消的句柄

证据：

- [D:\AssistIM_V2\client\network\websocket_client.py](D:\AssistIM_V2/client/network/websocket_client.py)

影响：

- logout / forced logout / shutdown 期间，旧 runtime 的首次 connect 尝试可能继续在后台跑完
- 一旦这次晚到 connect 成功，旧 transport 仍可能把状态重新推进到 `CONNECTED`，再触发后续 auth / sync 链
- 这会直接放大前面一整串“晚到 transport 成功路径继续污染 dead runtime”的问题

建议：

- 首次 connect 尝试也必须成为一个正式可追踪、可取消的任务句柄
- teardown 不能只取消 receive/heartbeat/reconnect，必须能取消所有 in-flight connect 尝试
- 补回归测试，覆盖“首次 connect 还在飞时执行 logout/close，不会晚到进入 CONNECTED”的路径

### F-254：`WebSocketClient.close()` 在 worker thread `join(2s)` 超时后仍会无条件把 `_thread` 置空；旧 worker 线程可能以“孤儿线程”方式继续存活

状态：已修复（2026-04-12）

修复记录：

- `WebSocketClient.close()` 在 `join(2s)` 后会重新检查 worker thread 是否仍存活；超时未退出时保留 `_thread` 引用并记录错误，不再假装关闭成功。
- `_ensure_worker_loop()` 遇到仍存活但 loop 不可用的旧 worker 时会直接拒绝重建，避免并存多条 websocket worker thread。
- 回归测试覆盖卡住 worker thread 不被清空，以及 stuck worker 不会被新 worker 替换。

原现状：

- [websocket_client.py](/D:/AssistIM_V2/client/network/websocket_client.py) 的 `close()` 在 stop worker loop 后会：
  - `await asyncio.to_thread(self._thread.join, 2.0)`
  - 然后无条件 `self._thread = None`
- 它不会在 join 返回后再次检查：
  - `self._thread.is_alive()`
- 也就是说，只要 worker 线程在 2 秒内没完全退出，代码也会把内部引用清空，当作“线程已经关掉”
- 下一次 `_ensure_worker_loop()` 看到 `_thread is None`，就会直接再起一条新的 worker thread

证据：

- [D:\AssistIM_V2\client\network\websocket_client.py](D:\AssistIM_V2/client/network/websocket_client.py)

影响：

- 一旦旧 worker thread 没有在 2 秒内真正退出，客户端就可能进入“旧 worker 还活着，但对象内部已经认为它不存在”的状态
- 后续 reconnect / relogin / reinitialize 再触发 `_ensure_worker_loop()` 时，有机会并存多条 websocket worker thread
- 这类 transport 级孤儿线程会继续放大旧连接残留、晚到回调和跨代污染问题

建议：

- `close()` 不能在 join 超时后直接把 `_thread` 置空，必须区分“已退出”和“仍存活”
- 对 worker thread stop 失败要升级成 lifecycle 级错误，而不是静默进入下一代 runtime
- 补回归测试，覆盖“worker thread 没在 join timeout 内退出时，不会被当成已关闭并继续创建第二条 worker thread”的路径

### F-255：`ConnectionManager` 把 worker-thread 进来的协程用 `run_coroutine_threadsafe()` 直接塞回主循环，但这些任务不进统一 bookkeeping；close 之后仍可能继续跑晚到 sync/save/message handler

状态：已修复（2026-04-12）

现状：

- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 的 `_schedule_message_coroutine()` 在跨线程场景下会：
  - `future = asyncio.run_coroutine_threadsafe(coro, loop)`
  - 只挂一个 `done_callback` 记日志
  - 不会把这个 future 放进 `self._tasks`
- 这条路径会被多个关键点使用：
  - `auth_ack` 后 `_send_sync_request()`
  - cursor 推进后 `_save_sync_state()`
  - `_notify_message()` 里所有 async message listener
- 但 `ConnectionManager.close()` 真正会取消的只有 `self._tasks` 里的本地 task
- 对这些 `run_coroutine_threadsafe()` 派发回主循环的晚到协程，没有任何统一取消或代际 guard

证据：

- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)

影响：

- 即使 `ConnectionManager.close()` 已经开始执行，之前从 worker 线程投递回主循环的：
  - `_send_sync_request()`
  - `_save_sync_state()`
  - `_handle_ws_message()` 派生出的 async listener
  仍可能继续跑
- 这直接放大了 auth/runtime 链里已经确认的一系列“close 之后晚到包继续推进 cursor / sync / 本地状态”的问题
- 从 lifecycle 角度看，连接关闭只停掉了“自己知道的 task”，却没有停掉“自己投递出去的 task”

建议：

- 所有从 worker thread 回投主循环的 transport 协程都必须进统一 bookkeeping，并在 close/shutdown 时可取消
- 至少要补 generation guard，防止旧 connection generation 的晚到协程继续写新 runtime
- 补回归测试，覆盖“connection close 后晚到 `_save_sync_state/_send_sync_request/message listener` 不再继续执行”的路径

### R-025：当前 app-level async bookkeeping 只覆盖 `asyncio.create_task()` 的一部分工作；跨线程 `run_coroutine_threadsafe()` 和 Qt callback queue 基本都游离在生命周期管理之外

状态：已修复（2026-04-13）

修复记录：

- ConnectionManager 已把跨线程 `run_coroutine_threadsafe()` future 纳入 `_thread_futures` close bookkeeping，WebSocketClient close 会清空 Qt queued callbacks 并等待 worker cleanup；Application teardown 对核心组件 close 失败采用严格失败，不再在未知异步残留上继续重建 runtime。

现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 只跟踪 `Application.create_task()` 产生的 task
- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 自己只跟踪 `_create_task()` 产生的 task
- 但 transport 层和 callback marshalling 里还有大量不进这两套台账的异步工作：
  - `asyncio.run_coroutine_threadsafe(...)`
  - [websocket_client.py](/D:/AssistIM_V2/client/network/websocket_client.py) 里的 `signals.queue_callback(...)`
  - worker thread 上直接启动的 `_connect_loop/_cleanup`
- 这些路径大多只有“出错记日志”的 done callback，没有统一的 close/shutdown cancel contract

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\client\network\websocket_client.py](D:\AssistIM_V2/client/network/websocket_client.py)

影响：

- 顶层以为自己已经 shutdown / teardown 完了，但实际上还有一批不在账上的 transport callback 和 cross-thread coroutine 可能继续跑
- 这会让 “close 干净 / shutdown 完成 / 已切到下一代 runtime” 这些 lifecycle 判断长期不可靠
- 这是 `G-03` 里很多晚到任务、transport 污染和半关闭对象复用问题的更底层根因之一

建议：

- 需要一套统一的 async bookkeeping contract，把主循环 task、跨线程 future、Qt callback queue 都纳入 lifecycle 管理
- 如果短期做不到统一纳管，至少要为旧 generation 的回调补统一 guard
- 后续修 `G-03` 时，这条应作为架构级约束纳入，不然单点修补会持续漏边界

### R-026：auth shell 和 main shell 的窗口级 UI task teardown 也不是 quiescent 的；当前只是 `cancel()`，并不等待这些任务真正停下

状态：已修复（2026-04-13）

修复记录：

- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 新增 `quiesce_async()`，顶层 `_quiesce_authenticated_runtime()` 会先取消 shell/page/widget UI tasks，再汇总 main/chat/session/contact/discovery/profile 等 tracked tasks 并 await 到 quiescent，避免窗口级 UI task 只 cancel 不等待。

现状：

- [auth_interface.py](/D:/AssistIM_V2/client/ui/windows/auth_interface.py) 的 `_on_destroyed()` 会遍历 `_ui_tasks` 并 `task.cancel()`，但不会 `await`
- [main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 的 `_on_destroyed()` 也是同样模式：
  - 取消 `_contact_open_task`
  - 遍历 `_ui_tasks` 做 `task.cancel()`
  - 但不等待真正停止
- 这两处窗口级 task 里都包含真实 UI side effect：
  - auth shell 的 auth submit / force-login prompt
  - main shell 的 contact jump / tray session open 等

证据：

- [D:\AssistIM_V2\client\ui\windows\auth_interface.py](D:\AssistIM_V2/client/ui/windows/auth_interface.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)

影响：

- 当前 shell teardown 只能保证“发出了取消信号”，不能保证“窗口相关异步操作已经静默”
- 在 shell 切换、forced logout、shutdown 这种对时序敏感的路径上，晚到 UI task 仍可能在窗口销毁边界附近继续落下一次 side effect
- 这和上面的 transport/bookkeeping 问题是同一类根因：生命周期管理只覆盖了部分异步工作

建议：

- shell teardown 需要区分“请求取消”与“真正 quiescent”两个阶段
- 至少对会改 UI / 会跳页 / 会发 InfoBar 的窗口级 task 增加统一 await 或 generation guard
- 后续修 `G-03` 时，这条可以和 `R-025` 一起作为“异步任务统一纳管”的子目标处理

### F-256：`WebSocketClient.close()` 不会清空 `WebSocketSignals` 的排队回调；close 之后旧 generation 的 Qt queued callback 仍可能继续被 `_dispatch_timer` 放出来

状态：已修复（2026-04-12）

修复记录：

- `WebSocketSignals` 新增 `clear_callbacks()`，`WebSocketClient.close()` 会清空已排队的 Qt callback。
- `queue_callback()` 在 dispatch timer 停止后重新入队时会重启 timer，避免 callback 队列进入不可调度状态。
- 回归测试覆盖 close 会清理 signal callback 队列。

原现状：

- [websocket_client.py](/D:/AssistIM_V2/client/network/websocket_client.py) 的 `WebSocketSignals` 内部维护了：
  - `_pending_callbacks`
  - `_dispatch_timer`
- `_dispatch_to_main()` 在 Qt 可用时，会优先走 `signals.queue_callback(callback)`
- 但 [websocket_client.py](/D:/AssistIM_V2/client/network/websocket_client.py) 的 `close()` 只会：
  - 清 `_main_loop`
  - 清 `_on_connect/_on_disconnect/_on_message/_on_error`
  - `_set_state(DISCONNECTED)`
- 它不会：
  - 清空 `signals._pending_callbacks`
  - 停掉 `signals._dispatch_timer`
  - 或者把 `signals` 置空
- 这意味着，close 前已经排进 Qt 队列的 callback，之后仍会继续被 `_dispatch_timer` 拿出来执行

证据：

- [D:\AssistIM_V2\client\network\websocket_client.py](D:\AssistIM_V2/client/network/websocket_client.py)

影响：

- 即使 transport 已经开始 teardown，旧 generation 的：
  - state_changed
  - connected/disconnected
  - message_received
  - error_occurred
  相关 queued callback 仍可能继续冲到主线程
- 这会直接放大前面已经确认的“close 之后晚到 transport callback 继续污染 lifecycle”的问题
- 说明 transport close 现在不仅没做到 quiescent，连 Qt callback queue 都没有被一并收口

建议：

- `WebSocketClient.close()` 必须同步清空 Qt queued callback 队列，或让这些 callback 携带 generation guard
- transport shutdown 不能只关 worker loop，也要把 main-thread dispatch queue 一并收干净
- 补回归测试，覆盖“close 后旧 websocket queued callback 不再继续触发 UI/main-loop side effect”的路径

### F-257：`Application.shutdown()` 在 teardown 末尾主动 `qt_app.processEvents()`；这会把一批晚到的 Qt queued callback 和 `deleteLater` 副作用再次冲出来，破坏 shutdown quiescence

状态：已修复（2026-04-12）

修复记录：

- `Application.shutdown()` 已移除 teardown 末尾的 `qt_app.processEvents()`，关闭阶段不再主动泵出晚到 Qt queued callback 或 `deleteLater` 副作用。
- shutdown 仍只执行 `qt_app.quit()` 作为退出信号。
- 回归测试覆盖 shutdown 不调用 `processEvents()`。

原现状：

- [main.py](/D:/AssistIM_V2/client/main.py) 的 `shutdown()` 在完成：
  - cancel `_tasks`
  - close controller/manager/http/db
  之后，还会主动调用：
  - `self.qt_app.processEvents()`
  - 然后才 `self.qt_app.quit()`
- 但前面已经确认：
  - websocket transport 有自己的 Qt queued callback 队列
  - auth/main shell 各自也有 `deleteLater()`、`QTimer.singleShot(...)`、窗口级 UI task
- `processEvents()` 会把这批排队中的 Qt 事件再主动冲一次

证据：

- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\network\websocket_client.py](D:\AssistIM_V2/client/network/websocket_client.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)
- [D:\AssistIM_V2\client\ui\windows\auth_interface.py](D:\AssistIM_V2/client/ui/windows/auth_interface.py)

影响：

- shutdown 本来应该是“尽量把系统带到静默态”，但现在末尾又主动 re-enter 了一次 Qt 事件泵
- 这会把旧 generation 的 queued callback、`deleteLater` 连锁副作用、late UI effect 再放一轮
- 对 `G-03` 来说，这相当于在 teardown 最后又人为制造了一次“晚到 side effect 冲刷窗口”

建议：

- `shutdown()` 末尾的 `processEvents()` 需要重新审视；如果只是为了刷 `deleteLater`，也必须配合严格的 generation guard
- 不要在 lifecycle 已经进入终止阶段后，再无差别冲一遍全部 Qt queued event
- 补回归测试，覆盖“shutdown 不会因为 `processEvents()` 再次触发旧 generation 的 queued callback”这条路径

### F-258：`ConnectionManager.close()` 不会清空 `_loop`；旧 generation 的晚到 transport callback 仍可借这条主循环引用继续回投协程

状态：已修复（2026-04-12）

现状：

- [connection_manager.py](/D:/AssistIM_V2/client/managers/connection_manager.py) 在 `initialize()/connect()` 时都会更新 `self._loop`
- `_schedule_message_coroutine()` 后续会依赖这条 `_loop`：
  - 主循环内走 `_create_task()`
  - 跨线程则走 `asyncio.run_coroutine_threadsafe(coro, loop)`
- 但 `close()` 结束时只会清：
  - `_ws_client`
  - listeners
  - `_db`
  - cursors
  - auth flags
  - `_initialized`
- 它不会把 `self._loop` 置空

证据：

- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)

影响：

- 只要旧 generation 的 transport callback 还能碰到 `ConnectionManager` 实例，就仍然握着一条可用的主循环引用
- 这会让晚到的 `_save_sync_state()`、`_send_sync_request()`、async message listener 更容易在 close 之后继续被投递
- 和前面的 `F-255/R-025` 叠加后，说明 connection teardown 不仅没收 task，连“往哪儿投递任务”的能力都没失效

建议：

- `ConnectionManager.close()` 应同步失效 `_loop`，让旧 generation 的 transport callback 无法继续回投主循环
- 更稳妥的方式仍然是 generation guard；但即便不做 generation，也不该让 closed manager 继续持有 live event loop 引用
- 补回归测试，覆盖“connection close 后晚到 callback 不能再借 `_loop` 回投主循环”的路径

### F-259：`ensure_remote_session()` 会无条件清掉本地隐藏 tombstone，搜索/托盘/聊天页旁路打开都能把“已在本机删除”的会话直接复活

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `ensure_remote_session()` 在成功拉到远端 session 后，会先：
  - `await self._unhide_session(session.session_id)`
  - 再 `await self._remember_session(session)`
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `open_session()`、[main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 的托盘/联系人跳转、以及侧边栏全局搜索结果，最后都会走到这条 `ensure_session_loaded() -> ensure_remote_session()` 链
- 这里没有任何“是否存在新活动”“是否高于 tombstone 时间”的判断

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)

影响：

- “删除会话仅当前设备隐藏并清本地记录”的语义被聊天页/搜索/托盘这些旁路直接绕开
- 用户只要点到一条旧入口，哪怕没有任何新消息，这个会话也会被立刻取消隐藏并重新落回本地列表/数据库
- 这说明当前 tombstone 只对 `refresh_remote_sessions()` 主路径有效，对 UI 旁路打开完全无约束力

建议：

- `ensure_remote_session()` 不能在 fetch 成功后无条件 `_unhide_session()`
- 本地删除后的会话是否允许重新出现，必须绑定到正式“复活条件”，例如新消息、新 session lifecycle event，或显式“重新打开旧会话”动作
- 给搜索/托盘/聊天页补回归测试，覆盖“已隐藏会话不会因普通 open flow 被静默复活”

### F-260：`ensure_direct_session()` 会通过 `POST /sessions/direct` 重新取回已存在的私聊，并无条件清 tombstone；从联系人/聊天页重新发起私聊会直接复活本地已删会话

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `ensure_direct_session()` 在本地没找到 direct session 时，会：
  - 调 `SessionService.create_direct_session()`
  - 服务端 [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `create_private()` 如果 direct 已存在，会直接返回旧 session
  - 客户端随后 `await self._unhide_session(session.session_id)` 并 `_remember_session(session)`
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `open_direct_session()`、[main_window.py](/D:/AssistIM_V2/client/ui/windows/main_window.py) 的联系人跳转等都会走这条链

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\services\session_service.py](D:\AssistIM_V2/client/services/session_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)

影响：

- 用户在当前设备删除某个私聊后，只要再次从联系人详情、联系人搜索、聊天页入口对同一个人发起聊天，就会把旧会话直接复活
- 这里甚至不是“新活动触发会话回归”，而是纯本地 open-intent 就足以抹掉 tombstone
- 这和文档中的“删除会话是本地隐藏/清记录”语义不一致，也会让本地删除显得不稳定

建议：

- direct session 的“重新发起聊天”需要先明确语义：是复用旧会话、建新会话入口，还是显式确认恢复旧会话
- 在语义收口前，`ensure_direct_session()` 不应直接 `_unhide_session()`
- 补回归测试，覆盖“本地删除 direct 后，再从联系人页点击聊天不会静默复活旧会话”

### F-261：历史补偿 `_on_history_synced()` 会先清 tombstone 再建会话；只要服务端重放旧历史，本地已删会话也会在重连时被重新拉回

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_on_history_synced()` 对每条历史消息都会先执行：
  - `await self._unhide_session(message.session_id)`
  - `await self._ensure_session_exists(message)`
- 这条路径没有检查这批 message 是“新活动”还是“因本地 cursor 被清空后补回的旧历史”
- 而本地删除会话本来就会删数据库里的 session/messages/read cursor，所以后续 reconnect/sync 很容易把它重新当成缺失历史补回来

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 本地删除会话不只是会被 UI 旁路打开复活，连一次普通重连/历史补偿都可能把它重新拉回
- 这会让“删除会话”的稳定性继续依赖 sync cursor、历史补偿批次和本地库是否被清空
- 会话是否可见不再由 tombstone 和新活动条件决定，而是被历史回放实现细节决定

建议：

- history replay 不应在应用消息前无条件 `_unhide_session()`
- 会话 tombstone 是否解除，必须至少基于“最后活动时间超过 tombstone”这类正式条件
- 补回归测试，覆盖“本地删除后，重连补偿旧历史不会直接把会话重新放回列表”

### F-262：`ensure_remote_session()/ensure_direct_session()` 对“远端已存在但本地缺失”的会话也会发 `SessionEvent.CREATED`，把 cache miss 填充伪装成正式生命周期创建

状态：已修复（2026-04-14）

现状：

- `ensure_remote_session()` 和 `ensure_direct_session()` 最终都会走 [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_remember_session()`
- `_remember_session()` 内部直接调用 `add_session()`
- `add_session()` 无条件发：
  - `SessionEvent.CREATED`
- 但这两条 ensure 路径很多时候只是：
  - 本地没有这个 session
  - 远端其实早就存在
  - 现在只是按需 fetch/create-or-reuse 再灌回本地 cache

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2/client/ui/widgets/session_panel.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 客户端本地 `SessionEvent.CREATED` 更像“缓存里第一次看到这个 session”，而不是“服务端正式创建了一个新会话”
- 这会让侧边栏、聊天页等消费者继续把“旁路 fetch 回来”“重新打开旧 direct”“真正新建会话”混成一种事件
- 也说明当前 `CREATED/DELETED` 作为 lifecycle event 名称本身已经失真

建议：

- 把“本地 cache add”和“正式 session created”拆成不同事件语义
- `ensure_*` 路径最多发 `UPDATED/RESTORED/CACHE_FILLED` 一类本地事件，不应复用 `CREATED`
- 补回归测试，覆盖“按需 fetch 旧 session 不会冒充 session created”

### F-263：UI 侧 `ensure_remote_session()/ensure_direct_session()` 没有使用 `_session_fetch_tasks` 做去重；同一会话被多个入口同时打开时会产生重复 fetch/create 竞态

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 里已经有 `_session_fetch_tasks`
- 但这套 task 去重只用于消息侧 `_ensure_session_exists()` / `_fetch_or_build_session()`
- UI 侧的：
  - `ensure_remote_session()`
  - `ensure_direct_session()`
  都是直接发 HTTP，然后 `_remember_session()`
- 因此托盘、侧边栏搜索、联系人跳转、聊天页跳转如果并发命中同一个缺失 session，会各自发一轮 fetch/create

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)

影响：

- 同一个 session 的 UI open flow 会产生重复网络请求和重复本地 add/normalize/unhide side effect
- 在本地删除/隐藏语义已经脆弱的前提下，这会进一步放大 race：哪条 ensure 先回来、哪条先清 tombstone 都会影响结果
- 这也和消息侧已经存在的 `_session_fetch_tasks` 形成明显分叉

建议：

- UI 侧 `ensure_remote_session()/ensure_direct_session()` 应并入同一套 `_session_fetch_tasks` 去重模型
- 至少要把“同一 session_id / 同一 direct target”的并发打开收口成单飞请求
- 补回归测试，覆盖“多个入口同时打开同一缺失会话，只发生一次远端 ensure/fetch”

### F-264：`refresh_remote_sessions()` 对 unread 端点失败不健壮；会话列表拉成功、未读数接口失败时，这条“会话全量刷新”本身会抛异常中断

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_fetch_remote_unread_counts()` 明确返回 `dict[str, int] | None`
- 失败时它会：
  - 记录 warning
  - `return None`
- 但 `refresh_remote_sessions()` 后面直接执行：
  - `session.unread_count = int(unread_count_map.get(session.session_id, 0))`
- 这里没有处理 `unread_count_map is None`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\services\session_service.py](D:\AssistIM_V2/client/services/session_service.py)
- [D:\AssistIM_V2\client\tests\test_service_boundaries.py](D:\AssistIM_V2/client/tests/test_service_boundaries.py)

影响：

- 只要 `/sessions` 成功、`/sessions/unread` 瞬时失败，这轮全量刷新就不是“未读数降级为 0 或保留旧值”，而是直接抛异常
- 这会让启动 warmup、手工刷新、资料更新后的 snapshot refresh 统统被同一个次要接口拖垮
- 当前测试只覆盖了 unread 成功路径，没有覆盖这个失败分支

建议：

- `refresh_remote_sessions()` 必须把 unread 视为可降级的附属数据，而不是刷新主链路的致命依赖
- 至少要在 `unread_count_map is None` 时使用旧 unread 或默认值继续完成 snapshot replace
- 补回归测试，覆盖“会话列表成功、未读数失败时仍能完成 refresh”

### F-265：`refresh_remote_sessions()` 在远端列表拉取失败时直接返回 `self.sessions`；调用方拿不到“刷新失败”信号，只会把 stale 本地快照当成新的 authoritative snapshot 继续使用

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `refresh_remote_sessions()` 在 `fetch_sessions()` 失败时：
  - 只记一条 warning
  - 然后 `return self.sessions`
- [main.py](/D:/AssistIM_V2/client/main.py) 的 `_synchronize_authenticated_runtime()`、以及 profile-affecting refresh 调用方，都会把这条返回值继续当“刚刷回来的 authoritative session snapshot”
- 这条返回值也没有任何 `from_cache` / `stale` / `refresh_failed` 标记

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)

影响：

- 启动 warmup、重连后的 snapshot 同步、以及用户触发的 refresh 都可能在失败时继续拿旧缓存往下跑
- 上层无法区分“远端真的没变化”和“这次根本没刷成功”
- 这会把 stale session list、stale hidden semantics 和后续 history prefetch 一起伪装成一次成功 refresh

建议：

- `refresh_remote_sessions()` 失败时不应伪装成“成功返回当前 sessions”
- 至少要把失败显式暴露给调用方，或者返回带状态的结果对象
- 补回归测试，覆盖“refresh 失败不会被上层误判成 authoritative snapshot 已更新”

### F-266：`add_session()` 自身不检查 `visible` 和 `hidden tombstone`；会话可见性 contract 现在完全靠调用方自觉遵守

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 里的：
  - `load_sessions()`
  - `_replace_sessions()`
  会检查：
  - `_is_session_visible()`
  - `_should_hide_session()`
- 但底层公共入口 `add_session()` 自己只是直接：
  - `_sessions[session.session_id] = session`
  - `db.save_session(session)`
  - 发 `SessionEvent.CREATED`
- `ensure_remote_session()`、`ensure_direct_session()`、消息侧 `_ensure_session_exists()`、fallback session bootstrap 最终都可能走到 `add_session()`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 会话“是否应该出现在当前设备列表里”没有被封装成 manager 内部统一约束，而是散落在少数调用方里
- 这正是当前 tombstone 被 ensure/history/search 多条旁路绕开的更底层原因
- 只要后续再出现一个新的 `add_session()` 调用点，就还会继续制造同类复活问题

建议：

- 把会话可见性和 tombstone 约束下沉到 `add_session()` / `_remember_session()` 这种统一入口
- 调用方不应决定“这个 session 能不能出现在当前设备列表里”
- 补回归测试，覆盖“隐藏/不可见 session 通过公共 add path 不会直接落入本地 cache”

### F-267：全量会话快照变化后，startup history prefetch 不会重排；旧 prefetch 继续暖旧会话，新 top sessions 反而可能完全不预热

状态：已修复（2026-04-14）

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `load_sessions()` 每次都会调 `_schedule_initial_history_prefetch(sessions)`
- 但 `_schedule_initial_history_prefetch()` 只要发现 `_startup_history_prefetch_task` 还在跑，就直接 `return`
- 这意味着如果：
  - 冷启动时已经为一批旧 sessions 启动了 prefetch
  - 随后 `refresh_remote_sessions()` 又替换了 authoritative snapshot
- 那么旧 prefetch 不会被取消，也不会按新的 top sessions 重排

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\main.py](D:\AssistIM_V2/client/main.py)

影响：

- 刚被 refresh 拉回来的新高优先级会话，可能完全没有拿到启动期 history warmup
- 而已经从最新 session snapshot 消失的旧会话，却还会继续吃这轮预取资源
- 会话 warmup 的效果不再跟 authoritative session list 对齐，而是跟“哪轮 task 先起”对齐

建议：

- session snapshot 变化后，startup prefetch 要么取消并重排，要么至少比较 session_id 集合后决定是否重建任务
- 不要让“第一轮起得早的 prefetch task”长期代表后续所有 snapshot 的 warmup 计划
- 补回归测试，覆盖“refresh 后新 top sessions 能重新获得预热，旧 sessions 不会继续占用启动预取”

### F-268：`_prime_history_page()` / `_load_history_page()` 在预取时不校验 session 仍然存在且可见；stale prefetch 会继续给已移除会话回填 history cache

状态：已修复（2026-04-14）

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 startup prefetch 最终会对每个 session_id 执行：
  - `_chat_controller.load_cached_messages(session_id, ...)`
  - `_load_history_page(session_id, before_timestamp=None)`
  - `_cache_history_page(...)`
- 这条链在预取分支里不会检查：
  - 该 session 是否仍在 `SessionManager.sessions`
  - 是否已经被最新 full snapshot 移除
  - 是否仍被 tombstone 隐藏
- 所以只要有 stale prefetch task 在跑，就能继续把 history page 塞回 `_history_page_cache`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 即便 authoritative session snapshot 已经把某个会话移掉，聊天页内存态仍可能继续为它保留甚至重新生成 history cache
- 这会进一步放大前面“删除/隐藏/旁路复活”的问题，因为 stale prefetch 会把“已不该出现的会话”继续预热成可快速打开状态
- 当前会话生命周期 contract 没有真正控制住 UI warm cache

建议：

- history prefetch 前必须校验 session 仍存在于当前 authoritative session set，且没有 tombstone/visibility 冲突
- 一旦 session 从 full snapshot 消失，相关 prefetch / history cache 也要同步失效
- 补回归测试，覆盖“full snapshot 移除会话后，stale prefetch 不会继续给它回填 history cache”

### F-269：`history_messages` 对已存在 `message_id` 直接跳过，不会用服务端 canonical payload 修正 lost-ACK/reconnect 场景里的本地 optimistic 消息

状态：已修复（2026-04-14）

现状：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `_process_history_messages()` 会先查一批 `existing_ids`
- 只要某条 `message_id` 已经存在本地库里，就直接：
  - `skipped_count += 1`
  - `continue`
- 它不会比较：
  - 本地状态是不是 `SENDING/FAILED`
  - 服务端 payload 是否已经携带 canonical `status/session_seq/read_count/extra`
  - 这条本地消息是不是一次丢失 ACK 后的 optimistic 残留
- 而 WS 发消息本来就把外层 `msg_id` 当 canonical `message_id`；因此 reconnect 后历史里返回“同 id 的权威消息”是正常场景

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\connection_manager.py](D:\AssistIM_V2/client/managers/connection_manager.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)

影响：

- 如果一条自发消息已经被服务端接收，但客户端丢了 `message_ack`，重连后 `history_messages` 会看到同一个 `message_id`
- 当前实现会把这条权威历史直接跳过，导致本地消息继续停留在 `SENDING` 或旧的 optimistic 元数据上
- 这会让 reconnect 补偿失去“修正本地 optimistic 状态”的能力，消息链路对 ACK 单点成功过于依赖

建议：

- `_process_history_messages()` 遇到已存在 `message_id` 时，不能一律跳过；至少要对本地 `SENDING/FAILED` 或 metadata 落后的消息做 canonical merge
- reconnect 补偿必须能把“已被服务端接受但 ACK 丢失”的消息收口成 sent/canonical 状态
- 补回归测试，覆盖“lost ACK 后 reconnect 通过 history_messages 修正本地 optimistic 消息”

### F-270：`retry_message()` 只允许重试 `FAILED`；一旦消息因 `F-269` 卡在 `SENDING`，当前客户端没有正式恢复入口

状态：已修复（2026-04-14）

现状：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `retry_message()` 开头直接限制：
  - `if message.status != MessageStatus.FAILED: return False`
- 但上一条 `F-269` 已经说明：
  - 某些消息在 ACK 丢失 + reconnect 后会继续停留在 `SENDING`
  - 而这类消息并不一定会自然掉进 `_finalize_pending_failure()`
- 结果就是 UI 上会留下“看起来还在发”的消息，但用户没有正式重试路径

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- lost-ACK / reconnect 造成的 stuck `SENDING` 消息，会处在一种既没成功、也没失败、也不能重试的僵持态
- 这会把上一条历史 canonicalization 缺口直接放大成用户可见的不可恢复状态
- 当前消息主链并没有把“发送中超时但未确认的旧消息”收口成正式可恢复状态机

建议：

- 先修 `F-269`，让 reconnect/history 能自动收口这类消息
- 同时给 `retry_message()` 或上层 UI 补一条“超时 stuck sending”的正式恢复入口
- 补回归测试，覆盖“消息卡在 SENDING 时，用户仍有可恢复路径”

### R-027：本地翻页回源 `_fetch_remote_messages()` 是一条明显的 N+1 + 全页重写盘路径

状态：已修复（2026-04-14）

现状：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `_fetch_remote_messages()` 对远端返回页里的每条消息都会先：
  - `await self._db.get_message(message_id)`
- 然后无论这页消息和本地是否真的有差异，最后都会：
  - `await self._db.save_messages_batch(remote_messages)`
- 而 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `save_messages_batch()` 也不是 `executemany()`，而是逐条 `INSERT OR REPLACE` 后再 commit

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 每次打开会话第一页或翻页回源，都会产生一轮“按 message_id 单条查本地 + 整页逐条重写”本地 IO
- 历史页越大、页面切换越频繁，这条链的冗余成本越明显
- 在消息链已经有 optimistic/local cache 的前提下，这种 IO 模式也会放大 UI 翻页抖动和数据库写放大

建议：

- 至少先把现有本地查重从逐条 `get_message()` 收成批量 existing-id 查询
- 再把“无变化也整页 `INSERT OR REPLACE`”改成真正的 delta write
- 如果继续保留 batch save，也应优先改成真正的批量执行而不是逐条 await execute

### F-271：`ContactController` 的 mutation API 本身不维护 authoritative contacts/groups cache；正确性仍依赖某个 UI 页面在线补丁

状态：已修复（2026-04-14）

现状：

- [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 里：
  - `create_group()`
  - `accept_request()`
  - `reject_request()`
  - `remove_friend()`
  - `leave_group()`
  - `add_group_member()`
  - `update_group_member_role()`
  - `transfer_group_ownership()`
  这些 mutation 方法基本都只是调 service 然后返回 payload / record
- controller 真正会写本地 authoritative cache 的路径，仍然只有：
  - `load_contacts() -> _persist_contacts_cache()`
  - `load_groups() -> _persist_groups_cache()`
  - 以及联系人页自己的 `_schedule_groups_cache_persist()` 这类 UI 补丁
- 也就是说，这些 mutation 之后本地 contacts/groups cache 是否更新，仍取决于 [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 当前是否在线并执行了对应页面逻辑

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 联系人域现在没有真正的 domain-level authoritative cache owner；controller 只是“取数据/发请求”，缓存一致性靠页面自己补
- 这正是前面一串“联系人页开着就对、没开就过期”“聊天页发起群管理后搜索缓存不更新”“请求接受后本地搜索还搜不到”的共同根因
- 后续只要再多一个从别的页面触发的联系人/群 mutation，就还会继续制造同类 cache 漂移

建议：

- 把 contacts/groups authoritative cache 的维护责任下沉到 `ContactController` 这一层
- 所有联系人/群 mutation 完成后，都应通过 controller 统一更新并持久化对应 cache，而不是依赖页面自己 patch
- UI 层只消费 controller 产出的最新快照，不要继续承担 cache owner 角色

### R-028：`load_requests()` 对缺失请求方资料走逐用户 `fetch_user`，请求页 reload 是一条明显的 N+1 网络路径

状态：已修复（2026-04-14）

修复说明：

- 消息 session metadata 的 group `session_avatar` 改用 `resolve_group_avatar_url()`，不再直接依赖可能陈旧的 `session.avatar`。

修复说明：

- `ContactController.load_requests()` 已删除缺名 fallback 网络补查，requests 正式入口直接消费服务端返回的 public summary。
- 客户端不再为请求列表逐用户调用 `/users/{id}`。

现状：

- [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `load_requests()` 会把缺失名字的 user id 收集到 `user_ids_to_resolve`
- 后续 `_load_request_user_names()` 直接：
  - `asyncio.gather(*(_fetch_name(user_id) for user_id in user_ids))`
  - 而 `_fetch_name()` 内部又是单个 `user_service.fetch_user(user_id)`
- 也就是说，缺几个用户就发几个独立的 HTTP 请求

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)

影响：

- 请求列表越多、资料缺口越大，请求页 reload 的网络成本越高
- 这也会放大前面“联系人页 reload 不是原子操作”的体验问题，因为 requests 分支本身就带一串额外 fan-out 请求
- 从域建模看，这说明请求列表 payload 仍不够自描述，客户端还在补一层 N+1 用户信息查询

建议：

- 优先让请求列表接口直接返回稳定可展示的对方资料，减少客户端补查
- 如果短期内做不到，客户端至少应提供批量用户资料查询而不是逐用户 `fetch_user`
- 补性能回归或埋点，量化请求页 reload 的 fan-out 成本

### F-272：群成员管理弹窗把一次“添加多名成员”实现成前端串行单成员提交，整次操作不是原子的

状态：已修复（2026-04-14）

现状：

- [group_member_management_dialogs.py](/D:/AssistIM_V2/client/ui/windows/group_member_management_dialogs.py) 的 `_add_members_async()` 会对 `member_ids` 做：
  - `for member_id in member_ids:`
  - `await self._controller.add_group_member(self._group_id, member_id)`
- 而 [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `add_group_member()` 和 [contact_service.py](/D:/AssistIM_V2/client/services/contact_service.py) 对应的服务端入口，本身都只是“单次添加一个成员”
- 也就是说，UI 上一次“选择多名成员并确认添加”，实际被拆成了多次独立 HTTP side effect

证据：

- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)
- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\services\contact_service.py](D:\AssistIM_V2/client/services/contact_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- 用户执行的一次“批量加人”在业务上并不是一个原子动作；中途任一成员添加失败，前面已经成功的成员不会自动回滚
- 这会让群成员变更在用户心智里表现成“一个操作”，在真实实现里却是“多次部分提交”，不利于稳定性和问题排查
- 跨设备和其它在线成员会先后看到一串部分完成的成员变化，而不是一次正式收口的批量变更

建议：

- 要么把“批量加人”收口成服务端正式 batch mutation，并在事务边界内完成
- 要么 UI 明确把它定义成逐个添加流程，不再用一次确认包装成一个看似原子的动作
- 补回归测试，覆盖“多人添加过程中后半段失败”的部分提交场景

### F-273：批量加人时如果后一个成员添加失败，前面已成功的成员不会被本地 canonicalize，当前窗口会继续停留在旧成员列表

状态：已修复（2026-04-14）

现状：

- 同一处 [group_member_management_dialogs.py](/D:/AssistIM_V2/client/ui/windows/group_member_management_dialogs.py) 的 `_add_members_async()` 里，循环过程中只把最后一次成功结果保存在 `latest_record`
- 但 `_apply_group_record(latest_record)` 只在整轮循环完全成功时才执行
- 如果前几个成员已经添加成功、后一个成员抛异常，代码会直接进 `except`，然后只弹错误提示，不会把已成功那部分重新 `fetch_group()` 或应用到本地 `_group_record`

证据：

- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)

影响：

- 服务端群成员可能已经发生了部分变化，但当前成员管理弹窗和聊天页内存态仍停留在旧快照
- 用户会看到“提示失败，但实际上有人已经被加进群里”的分裂状态
- 这会进一步放大前面已经确认过的联系人页/搜索缓存收口问题，因为本地 canonical record 本身就没更新

建议：

- 至少在批量加人出现部分成功后，兜底做一次 authoritative `fetch_group()` 收口当前快照
- 更根本的做法仍然是把这条链改成正式 batch mutation，避免前端自行拼装部分提交流程

### F-274：踢人成功后如果补拉 `fetch_group()` 失败，客户端会把“已成功的变更”误报成失败

状态：已修复（2026-04-14）

现状：

- [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `remove_group_member()` 先调用 `remove_group_member` HTTP `DELETE`
- 然后立即再调用一次 `fetch_group(group_id)`，试图拿最新群快照
- [group_member_management_dialogs.py](/D:/AssistIM_V2/client/ui/windows/group_member_management_dialogs.py) 的 `_remove_member_async()` 则把这整个两步链路包成一个 `try/except`
- 只要后半段 `fetch_group()` 因网络抖动或暂时错误失败，UI 就会直接弹“移除成员失败”

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)

影响：

- 这条 mutation 现在不是 failure-atomic 的：前半段 side effect 可能已经成功，后半段补拉失败却被用户感知成整次失败
- 当前窗口会继续保留旧成员列表，直到下一次手工刷新或重新打开
- 这会让“是否真的移除了成员”变成不确定状态，影响群管理操作的可信度

建议：

- 让服务端 `remove_member` 正式返回最新群快照，避免客户端自行拼“先改再查”
- 如果短期内仍保留两步模式，至少把“mutation 成功但 refresh 失败”单独建模，不要误报成完整失败

### F-275：群成员管理弹窗打开后不会订阅任何权威群更新，窗口停留期间的成员/角色/群主变化都会变成 stale state

状态：已修复（2026-04-14）

现状：

- [group_member_management_dialogs.py](/D:/AssistIM_V2/client/ui/windows/group_member_management_dialogs.py) 的 `showEvent()` 只会在首次显示时触发一次 `_reload_group_async()`
- 后续窗口存活期间，弹窗只会消费“自己发起的 mutation”回来的 `_apply_group_record()`
- 它没有订阅：
  - `ContactEvent.SYNC_REQUIRED`
  - `MessageEvent.GROUP_UPDATED`
  - 或任何别的权威 group refresh 信号
- 因此，只要别的设备、别的成员或别的页面改变了成员列表/角色/所有权，这个弹窗里的 `_group_record` 和权限计算就会继续沿用旧快照

证据：

- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 群成员管理弹窗会在打开期间逐步偏离权威状态，成员列表、owner/admin 权限、可见操作按钮都可能过期
- 比如群主在别处转让所有权后，本窗口仍可能继续展示“Add Members / Set Admin / Remove / Transfer”按钮，直到操作时报错
- 这说明群管理窗口并不是 authoritative 管理界面，而只是一次性快照编辑器

建议：

- 给群成员管理弹窗补正式的权威更新订阅，至少在可见期间消费群资料/成员变化后的 authoritative refresh
- 或者把窗口设计成严格的短生命周期对话框，每次聚焦前都重新拉最新 group snapshot

### R-029：联系人域的 `contact_refresh` 大多数 reason 都会退化成整页 full reload，好友/请求变更也会顺带重拉 groups 并整表重写缓存

状态：已修复（2026-04-14）

修复说明：

- `ContactInterface._on_contact_sync_required()` 已按 `friend_request_created/updated`、`friendship_created/removed` 拆成 requests slice 与 contacts+requests slice 的 authoritative refresh。
- self profile 变更改为统一刷新 contacts/groups/requests，而不是只刷 groups 或直接整页 reload。

现状：

- 服务端 [friends.py](/D:/AssistIM_V2/server/app/api/v1/friends.py) 会发出：
  - `friend_request_created`
  - `friendship_created`
  - `friend_request_updated`
  - `friendship_removed`
  这些 `contact_refresh`
- 但 [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `_on_contact_sync_required()` 只对：
  - `user_profile_update`
  - `group_profile_update`
  - `group_self_profile_update`
  做局部内存 patch
- 其它大多数联系人域 reason 最终都会直接 `reload_data()`
- 而 `reload_data()` 又是完整执行：
  - `load_contacts()`
  - `load_groups()`
  - `load_requests()`
  并重建三页 UI、重写 contacts/groups cache

证据：

- [D:\AssistIM_V2\server\app\api\v1\friends.py](D:\AssistIM_V2/server/app/api/v1/friends.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)

影响：

- 一次好友请求变化或删好友，也会顺带重拉 groups 并整表重写 `contacts_cache/groups_cache`
- 联系人域如果短时间收到多条 `contact_refresh`，页面会进入重复 full reload 和 rebuild 的抖动路径
- 这说明当前联系人域并没有真正的 slice-level refresh contract，很多变更仍在用“整页重载”兜底

建议：

- 按 reason 把联系人域 refresh 至少拆成 `contacts / requests / groups` 三个 slice
- 不要让好友/请求 mutation 默认重拉并重写整个 groups 分支
- 收口 controller 级 authoritative cache 之后，再把这些 full reload 改成正式的增量更新

### F-276：加密消息即使已经本地解密并缓存 plaintext，也完全不会进入本地消息搜索

状态：已修复（2026-04-14）

修复说明：

- [database.py](/D:/AssistIM_V2/client/storage/database.py) 的本地搜索现在会额外扫描 `is_encrypted=1` 且带当前 `local_plaintext_version` 的本地 plaintext / attachment metadata cache。
- 搜索仍不会索引远端密文、附件 URL 或过期版本缓存，只匹配当前设备已成功解密并受版本约束的本地缓存。
- 已补 `test_database_persists_encrypted_message_ciphertext_and_searches_versioned_local_plaintext` 和 `test_database_marks_encrypted_attachments_and_searches_versioned_local_metadata`。

现状：

- [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `save_message()` 对加密消息会把 `content_ciphertext` 落盘，并把 `is_encrypted=1`
- 同文件的 `_content_for_display()` 又明确支持从 `extra.encryption.local_plaintext` 恢复本地显示明文
- 但消息搜索链：
  - `search_messages()`
  - `count_search_message_sessions()`
  - `_search_messages_fts()`
  - 以及相关 FTS trigger
  都统一把 `COALESCE(is_encrypted, 0) != 1` 作为过滤条件，或直接把加密消息的 FTS 文本置空
- 结果就是，只要消息被标记成加密，不管本地是否已经成功解密出 `local_plaintext`，搜索链都不会返回它

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 一旦 direct/group 会话启用 E2EE，本地消息搜索和侧栏全局搜索都会系统性漏掉这些消息
- 当前实现一边维护 `local_plaintext` 作为本地显示缓存，一边又让搜索链彻底忽略它，形成明显的能力分裂
- 这会让用户在“看得见消息内容”但“永远搜不到这条消息”的状态下工作，尤其影响加密会话的可用性

建议：

- 明确产品语义：本地搜索是否允许基于当前设备已解密的 `local_plaintext`
- 如果允许，就要为本地 plaintext cache 建立受控的本地搜索索引，而不是直接全量排除 `is_encrypted=1`
- 如果不允许，也应在 UI 和文档里明确说明“加密消息不参与本地搜索”，避免形成隐式能力缺口

### F-277：失败的加密文本消息手动重试时不会重新加密，而是直接复用旧 ciphertext 和旧 envelope

状态：已修复（2026-04-14）

现状：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `retry_message()` 对文本消息不会重新走 `_prepare_outbound_encryption()`
- 它只是把本地 `message` 重新置成 `SENDING`，然后用：
  - `self._transport_content_for_message(message)`
  - 以及现成的 `message.extra`
  重新构造 pending message
- 对已经带 `extra.encryption` 的失败消息来说，这等于直接复用上一次发送时生成的 `content_ciphertext / recipient_device_id / prekey metadata`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 失败后的手动重试不会根据当前设备列表、当前会话安全状态或新的对端 prekey 重新生成密文
- 如果失败原因正是对端设备变化、bundle 失效、prekey 消耗或身份变化，这次重试仍会沿用旧 envelope，成功率和正确性都不可控
- 这让“重试”在 E2EE 文本消息上退化成“再次发送旧密文”，不是一次新的安全发送

建议：

- 对带 `encryption.enabled` 的文本消息，手动 retry 时应重新走当前会话上下文下的加密流程
- 旧 ciphertext 只能作为历史记录，不应直接充当 retry 的发送载荷

### F-278：失败的加密文本消息手动重试会绕过当前会话的身份审查/安全阻断逻辑

状态：已修复（2026-04-14）

现状：

- 正常文本发送路径在 [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 里会经过：
  - `_pending_outbound_security_review()`
  - `_assert_session_identity_safe_for_outbound()`
  - `_prepare_outbound_encryption()`
- 但 `retry_message()` 对失败文本消息不会重新加载 session，也不会重新检查当前 `session_crypto_state`
- 它会直接把旧消息重新入队发送

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 如果一条消息最初失败后，期间对端身份已变更并进入 review-blocking 状态，手动 retry 仍可能绕过当前安全 gate
- 这让“新发送必须经过身份审查”和“失败重试仍可直接发出”形成两套不同安全语义

建议：

- retry 不应绕过当前 session 的安全门禁；至少要重新加载 session 并重新执行 identity-review gate
- 对已过期的旧加密状态，应强制用户重新确认或重新加密，而不是直接复用旧消息

### F-279：群聊 E2EE 发送在部分成员 bundle 拉取失败时会静默退化成“只发给一部分成员设备”

状态：已修复（2026-04-14）

现状：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `_resolve_group_recipient_bundles()` 会逐个成员 `fetch_prekey_bundle(member_id)`
- 某个成员拉取失败时，只会：
  - `logger.warning(...)`
  - `continue`
- 只要最后 `recipient_bundles` 不是空列表，后续 `encrypt_text_for_group_session()` / `encrypt_attachment_for_group_session()` 就会继续发送

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 群消息/群附件会在本地无提示地退化成“部分成员设备可解密，部分成员设备完全收不到可用 fanout”
- 这不是“整条发送失败”，而是更危险的 silent partial delivery
- 对发送者来说消息看起来发成功了，但群里会出现某些成员长期无法解密的隐蔽分裂状态

建议：

- 群聊 E2EE 至少要能区分“全部 fanout 成功”和“部分成员缺失 bundle”
- 对部分 fanout 场景，应该显式失败或至少给出权威告警，不要静默继续发送

### R-030：群聊 E2EE 每次发送都按成员逐个拉 prekey bundle，是明显的顺序 N+1 网络路径

状态：已修复（2026-04-14）

现状：

- 同一处 `_resolve_group_recipient_bundles()` 是：
  - 逐个 member_id
  - `await fetch_prekey_bundle(member_id)`
  - 再本地组装 `recipient_bundles`
- 没有批量查询，也没有本地短期缓存
- 这条路径同时被文本发送和附件发送复用

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 群越大，单次发送前的前置网络 fan-out 越重
- 在弱网或高延迟环境下，群聊 E2EE 发送会被这条串行依赖直接拉长
- 这也是后续“部分成员 bundle 拉取失败就静默 partial fanout”的性能根因之一

建议：

- 给群成员 bundle 获取补批量接口或短期缓存
- 至少先把逐成员串行 await 收敛成并发批量拉取

### F-280：security-pending 消息的 release/discard 只扫描当前会话最近 200 条，旧的待确认消息会被静默遗漏

状态：已修复（2026-04-14）

现状：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `_collect_security_pending_messages()` 直接调用：
  - `get_messages(session_id, limit=200)`
- 然后只从这 200 条里筛 `MessageStatus.AWAITING_SECURITY_CONFIRMATION`
- `release_security_pending_messages()` 和 `discard_security_pending_messages()` 都依赖这条结果

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 如果一个会话里累计了超过 200 条待安全确认的本地消息，较早那部分将永远不参与 release/discard
- 这会让 session-level “确认后统一发出” 和 “全部丢弃” 都变成不完整批处理

建议：

- security-pending 的收集应走状态过滤查询，而不是借最近 200 条普通消息列表兜底
- 至少要能分页或全量处理该状态的消息

### F-281：history sync 会自动为历史里的加密图片/视频启动后台下载，不需要用户打开消息

状态：已修复（2026-04-14）

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `_process_history_messages()` 在保存完 `saved_messages` 后，会对每条消息调用 `_maybe_schedule_encrypted_media_prefetch()`
- `_maybe_schedule_encrypted_media_prefetch()` 对加密 `IMAGE/VIDEO` 只要有 remote source 就会启动 `_prefetch_encrypted_media()`
- `_prefetch_encrypted_media()` 最终会直接 `download_attachment()`，把远端媒体下载并解密到本地 `%TEMP%\\assistim_downloads`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 只要 reconnect/history sync 拉回历史加密媒体，客户端就可能在后台主动下载并解密它们，即使用户从未点开这些消息
- 这把“浏览历史”隐式扩展成了“主动落地历史媒体明文”，对流量、磁盘和本地隐私边界都更激进

建议：

- 明确产品语义：历史同步是否允许后台自动下载加密媒体
- 如果只是为了 inline preview，至少应把预取收口到“当前视口附近/显式打开后”而不是 history sync 全量触发

### R-031：加密媒体预取没有任何并发上限或背压控制，一次 history sync 可以同时拉起大量后台下载

状态：已修复（2026-04-14）

现状：

- `_process_history_messages()` 对每条新保存的加密图片/视频都可能调用 `_maybe_schedule_encrypted_media_prefetch()`
- `MessageManager` 只用 `_media_prefetch_tasks[message_id]` 防止同一消息重复预取
- 但没有：
  - 全局并发上限
  - 会话级上限
  - 带宽/磁盘背压

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 当一次历史同步带回较多加密图片/视频时，客户端会并发拉起大量下载/解密任务
- 这会放大磁盘写入、网络竞争和本地 CPU 压力，也让前面已经确认的删除/隐藏会话残留问题更难收口

建议：

- 给媒体预取补正式的任务队列和并发限制
- 把“后台预取”从 best-effort task 提升成可控资源策略

### F-282：`CallManager` 收到任意 `call_invite` 都会直接覆盖 `_active_call`，没有本地 busy/late-event 防护

状态：已修复（2026-04-14）

现状：

- [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 的 `_handle_invite()` 不检查：
  - 当前是否已有 `_active_call`
  - 当前 `_active_call` 是否已处于 `inviting/ringing/accepted`
  - payload `call_id` 是否属于本地预期中的当前通话
- 它会直接：
  - `self._active_call = ActiveCallState.from_payload(...)`
  - 然后发 `CallEvent.INVITE_RECEIVED`

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- 只要有第二个 invite、重复 invite 或晚到 invite 进入客户端，本地当前通话就可能被直接覆盖
- 这和服务端 busy 约束是两层不同边界；即使服务端多数时候拦住了新 invite，客户端本地仍缺少最后一道状态机保护

建议：

- `_handle_invite()` 必须先校验当前本地 call state，再决定是忽略、拒绝还是替换
- 不要让任意 invite payload 都成为 `_active_call` 的新单一真相

### F-283：`CallManager` 的状态/终态处理不校验 `payload.call_id == current active_call.call_id`，晚到旧事件能改写当前通话

状态：已修复（2026-04-14）

现状：

- `_handle_state_event()`、`_handle_terminal_event()`、`_handle_busy()` 都直接把 payload 交给 `_merge_state()`
- `_merge_state()` 会基于 payload 新建/覆盖 `_active_call`
- 这条链上没有任何“当前 active_call 的 call_id 必须匹配 payload.call_id”的硬校验

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- 旧通话的 `ringing/accept/reject/hangup/busy` 晚到后，可能直接把当前通话状态改写或清掉
- 这会把客户端变成“谁最后到，谁覆盖”的单槽状态机

建议：

- 对非 invite 的 signaling/state 事件，默认只允许匹配当前 active call_id 的 payload 生效
- 旧 call 的晚到事件应被显式丢弃或记录，而不是继续走当前业务状态机

### F-284：`CallManager` 的本地操作入口不会校验 `call_id` 是否属于当前活跃通话，也不会校验阶段是否合法

状态：已修复（2026-04-14）

现状：

- `accept_call()`、`reject_call()`、`hangup_call()`、`send_ringing()`、`send_offer()`、`send_answer()`、`send_ice_candidate()` 都只校验 `call_id` 非空
- 这些方法不会检查：
  - 本地 `_active_call` 是否存在
  - `call_id` 是否等于当前 `_active_call.call_id`
  - 当前阶段是否允许这条命令

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- 任何持有旧 `call_id` 的本地 UI/任务都可以继续尝试对旧通话发 accept/reject/hangup/offer/ice
- 这把“阶段约束”和“当前通话约束”完全留给了服务端兜底，本地状态机本身没有封口

建议：

- 这些入口至少要先校验 call_id 是否仍是当前 active call
- 再根据当前状态决定是否允许发送相应命令

### F-285：`CallManager` 对终态事件没有本地幂等保护，旧通话的重复终态仍会再次发 UI 终态事件

状态：已修复（2026-04-14）

现状：

- `_handle_terminal_event()` 和 `_handle_busy()` 在处理完 payload 后会：
  - 发 `CallEvent.REJECTED/ENDED/BUSY`
  - 再把 `_active_call = None`
- 但如果旧终态重复到达，而此时 `_active_call` 已经被别的 payload 重建或仍处于另一个 call，前面的 call_id 不匹配保护并不存在

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 聊天页会再次执行：
  - `_close_call_window(...)`
  - `_schedule_call_result_message(...)`
  - terminal InfoBar
- 也就是说，重复终态不只是“多打一条日志”，而是会重复触发 UI 收尾副作用

建议：

- 终态事件必须做本地幂等校验
- 对已结束的 call_id，要么忽略后续重复终态，要么按 call_id 单独去重

### F-286：`CallManager` 只维护一个 `_active_call` 和一个 `_unanswered_timeout_task`，第二个晚到 invite/状态会直接抢走 timeout 所有权

状态：已修复（2026-04-14）

现状：

- `CallManager` 只用一个：
  - `_active_call`
  - `_unanswered_timeout_task`
- `_arm_unanswered_timeout()` 会先 `_cancel_unanswered_timeout()`，再为新的 `call_id` 创建任务
- 一旦 `_handle_invite()` 或其它状态路径把 `_active_call` 改成新的 call，上一通 call 的本地 timeout 跟踪也随之失效

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- 客户端本地的 unanswered timeout 归属会被后来的 payload 抢走
- 这让本地 timeout 收口进一步依赖“绝不出现第二条 call 流”，而这正是前面几条 finding 已经证明并不稳的假设

建议：

- 如果继续坚持单通话模型，至少要把“当前 call_id”和“timeout 所属 call_id”做严格一致性校验
- 更稳妥的做法是把 timeout state 绑定到 call_id，而不是单槽字段

### R-032：aiortc 引擎会在 signaling 未激活时无限累积 `_pending_signals`，pre-accept ICE/offer 没有任何缓存上限

状态：closed（2026-04-14）

修复记录：

- `AiortcVoiceEngine.MAX_PENDING_SIGNALS` 已限制 pre-accept signaling queue
- `_emit_or_queue_signal()` 超限时淘汰最旧 pending signal，不再无限 append
- `ChatInterface` 已移除 invite 阶段 hidden prewarm，pre-accept 队列压力不再由每台被叫设备放大

现状：

- [aiortc_voice_engine.py](/D:/AssistIM_V2/client/call/aiortc_voice_engine.py) 的 `_emit_or_queue_signal()` 在 `_signaling_ready == False` 时会直接：
  - `self._pending_signals.append((event_type, payload))`
- `_pending_signals` 是普通 list，没有任何长度限制
- 而 prewarm/pre-accept 阶段本来就允许本地 offer/ICE 被提前生成并缓存

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 如果未接听阶段持续生成 ICE 或重复触发 offer/answer 预热，缓存会无上限增长
- 这不仅是内存风险，也会在后续 `activate_signaling()` 时把整串历史信令一次性冲出去

建议：

- 给 `_pending_signals` 增加事件类型和数量上限
- 特别是 ICE，应该有去重和背压策略，而不是无限 list append

### R-033：aiortc 引擎 `close()` 只 cancel 背景任务，不等待它们真正静默，通话 teardown 不是 quiescent 的

状态：closed（2026-04-14）

修复记录：

- `AiortcVoiceEngine._close()` cancel 其它 tracked tasks 后会 `await asyncio.gather(..., return_exceptions=True)` 等待它们静默
- `CallWindow` 增加 `_engine_closed`，显式 end 与 Qt closeEvent 不会重复 close engine
- `close()` 在没有 running loop 时会同步释放本地资源并清空 pending state，不再直接跳过收尾

现状：

- [aiortc_voice_engine.py](/D:/AssistIM_V2/client/call/aiortc_voice_engine.py) 的 `close()` 只是：
  - 先 `_release_media_resources()`
  - 再 `_launch(self._close, ...)`
- `_close()` 内部会遍历 `_tasks` 并 `task.cancel()`，但不会等待这些任务真正结束
- 同时 done callback `_finalize_task()` 仍可能在之后继续跑结果处理

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 通话关闭后，旧的媒体/ICE/peer-connection 任务仍可能短时间继续运行并回调 UI/状态信号
- 这和前面 `auth/runtime` 链已经确认的“teardown 不是 quiescent teardown”在通话子系统里是同一个结构性问题

建议：

- 把 aiortc engine 的 close 也收口成 quiescent teardown
- 至少要能等待关键后台任务静默后，再视为通话真正结束

### F-287：`CallWindow.end_call()` 与 `closeEvent()` 会重复触发一次 engine close

状态：已修复（2026-04-14）

现状：

- [call_window.py](/D:/AssistIM_V2/client/ui/windows/call_window.py) 的 `end_call()` 会先 `self._engine.close()`，再 `self.close()`
- 同文件的 `closeEvent()` 又会再次 `self._engine.close()`

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 程序化关窗路径每次都会发起两次媒体 teardown
- 这会放大 aiortc 子系统里原本就存在的“close 不是 quiescent teardown”问题

建议：

- `end_call()` 和 `closeEvent()` 之间只能保留一个真正的 engine close 入口
- 让另一个分支只负责窗口生命周期，不再重复触发媒体 teardown

### F-288：手动关闭通话窗口会先本地销毁媒体/UI，再异步发送 hangup

状态：已修复（2026-04-14）

现状：

- `CallWindow.closeEvent()` 在非程序化关闭时会先 `_emit_hangup()`
- 但同一个 `closeEvent()` 紧接着就会 `self._engine.close()`
- 聊天页的 `_on_call_window_hangup_requested()` 只是异步调度 `hangup_call(call_id)`

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 如果 hangup 发送失败，本地窗口和媒体已经先被销毁
- UI 会表现成“我这边已经挂了”，但服务端和对端可能仍认为通话存活

建议：

- 手动挂断应先进入“正在结束”状态，再等待 hangup 发送结果决定最终收口
- 至少不要在 send path 还没开始前就把本地媒体彻底 teardown

### F-289：重复 `accepted/ringing/inviting` 会把已连通通话回退成预连接 UI

状态：已修复（2026-04-14）

现状：

- `CallWindow.sync_call_state()` 只要收到 `accepted` / `ringing` / `inviting`
- 就会 `self._call_connected = False`，并停止 duration timer

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 晚到或重复的非终态事件会把已进入 `In call` 的窗口重新打回 `Connecting...` / `Ringing...`
- 通话时长也会被本地重置

建议：

- `sync_call_state()` 需要把“已连通”视为更高优先级的本地阶段
- 对重复或回退性的状态更新做幂等保护

### F-290：通话窗口会用本地“首个连通瞬间”覆盖服务端 `answered_at`

状态：已修复（2026-04-14）

现状：

- `CallWindow.sync_call_state()` 会在 payload 带 `answered_at` 时更新 `_call_started_at`
- 但 `_mark_call_connected()` 又会无条件把 `_call_started_at = datetime.now()`

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 通话窗口展示的时长起点不是权威 `answered_at`
- caller 和 callee、以及系统消息里的时长口径会继续分裂

建议：

- 本地“媒体终于连上”应单独记录，不要覆盖服务端 `answered_at`
- duration UI 和结果消息都应统一基于同一个权威起点

### F-291：通话结果系统消息会按“收到终态的当前时间”计算时长

状态：已修复（2026-04-14）

现状：

- `_send_call_result_message()` 在 `completed` 场景会调用 `_call_duration_seconds(call)`
- `_call_duration_seconds()` 直接用 `datetime.now() - answered_at`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 终态广播如果晚到，本地系统消息时长会被系统性高估
- 这让同一通话的“窗口计时”“系统消息时长”“服务端终态时间”三者继续不一致

建议：

- 时长计算应锚定正式结束时间或本地已记录的连通/结束时间点
- 不要在生成结果消息时再临时拿 `now()` 推导

### F-292：接受来电会把 `call_accept` 串行阻塞在一次强制 ICE 刷新之后

状态：已修复（2026-04-14）

现状：

- `ChatController.accept_call()` 先 `await refresh_call_ice_servers(force_refresh=True)`
- 然后才真正发送 `call_accept`

证据：

- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)

影响：

- 用户点击“接听”后，正式 accept 还要再等一次 HTTP
- 网络抖动时会直接增加接听时延，甚至错过对端 timeout/挂断窗口

建议：

- `call_accept` 不应被非关键的 ICE 配置刷新阻塞
- 更稳妥的顺序是先 accept，再在已接受状态内完成媒体配置刷新

### F-293：来电预热和正式接听会重复触发两次强制 ICE 刷新

状态：已修复（2026-04-14）

现状：

- `_prepare_incoming_call_window()` 已经会 `refresh_call_ice_servers(force_refresh=True)`
- 之后真正接听时，`ChatController.accept_call()` 又会再强刷一次

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)

影响：

- 秒接场景会稳定打出两次 `/calls/ice-servers`
- 这既增加接听延迟，也让通话 bootstrap 更依赖一次性网络成功

建议：

- 来电路径只保留一处 ICE refresh owner
- 预热和正式 accept 之间要共享同一份配置，而不是重复强刷

### F-294：来电 toast 会在 accept/reject 发送成功前先被本地关闭

状态：已修复（2026-04-14）

现状：

- `_accept_incoming_call_from_toast()` 和 `_reject_incoming_call_from_toast()`
- 都会先 `_close_incoming_call_toast(call_id)`，再异步调度网络动作

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 一旦 accept/reject 发送失败，用户已经失去了来电 prompt
- UI 会出现“提示先消失，但通话状态并未真正收口”的坏状态

建议：

- 至少在动作成功前保留 pending UI
- 失败时应允许恢复 toast 或给出可重试的来电入口

### F-295：远端音频到达但本机无输出设备时，通话会长期卡在 `Connecting...`

状态：已修复（2026-04-14）

现状：

- `AiortcVoiceEngine._play_remote_audio()` 在 `not is_available()` 时直接返回
- 只发一条 `Remote audio received (no output device)` 状态
- `CallWindow._on_engine_state_changed()` 又把这类状态继续映射成 `Connecting...`

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)
- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 通话其实已经收到了远端媒体，但窗口会永久显示“正在连接”
- 后续即使设备恢复，也没有正式 retry 路径把状态拉回已连通

建议：

- “无输出设备”和“媒体尚未建立”必须拆成不同状态
- 设备恢复后要么自动重试播放，要么至少允许本地重新收口 UI

### F-296：服务端允许客户端自带 `call_id`，registry 会直接覆盖同名现存通话

状态：已修复（2026-04-14）

现状：

- `CallService.invite()` 接受调用方提供的 `call_id`
- `InMemoryCallRegistry.create()` 会直接 `self._calls[call_id] = active_call`
- 同时 `_call_id_by_user_id` 也会被新的同名 call 直接覆盖

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\server\app\realtime\call_registry.py](D:\AssistIM_V2/server/app/realtime/call_registry.py)

影响：

- `call_id` 冲突时，现存 runtime call 会被静默替换
- 这会把无关通话的后续 signaling、busy 检查、terminal 收口全部打乱

建议：

- `call_id` 应由服务端生成或至少在 registry create 前做唯一性校验
- 不能继续允许同名 `call_id` 直接覆盖现存通话记录

### F-297：direct E2EE 的身份审查待确认只覆盖文本，不覆盖附件发送

状态：已修复（2026-04-14）

现状：

- `_pending_outbound_security_review()` 只在文本消息路径生效
- `prepare_attachment_upload()` 对 direct E2EE 会直接 `_assert_session_identity_safe_for_outbound(session)`
- 不满足时直接抛错，不会像文本那样进入 `AWAITING_SECURITY_CONFIRMATION`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 同一会话里，文本会进入“待安全确认”，附件却会直接失败
- 用户体验和正式安全 gate 被拆成了两套不同 contract

建议：

- direct E2EE 的 identity review 应统一覆盖文本和附件
- 不要继续允许附件路径绕开 `security_pending` 队列

### F-298：本地删除消息不会取消该消息的待 ACK / 待重试状态

状态：已修复（2026-04-14）

现状：

- `MessageManager.delete_message()` 只做 `db.delete_message(message_id)`
- 不会同步从 `_pending_messages` 中移除，也不会取消后续 retry/ACK 检查

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 已被本地删除的 failed/sending 消息，后续仍可能被 ACK loop 继续重试、失败回写或状态更新
- 本地“我已经删了”与发送队列“这条还活着”会形成双真相

建议：

- 本地删除消息时，必须同步清理该 message_id 的 pending outbound state
- delete contract 不能只删数据库，不管内存发送状态

### F-299：消息删除不会取消 in-flight 的加密媒体预取，晚到任务仍可把消息重新写回库

状态：已修复（2026-04-14）

现状：

- `_process_delete()` 和 `delete_message()` 都只是删 DB 行
- 但 `_prefetch_encrypted_media()` 会在后台调用 `download_attachment()`，后者又会 `save_message(message)`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 删除消息后，如果该消息的加密图片/视频下载任务尚未结束，晚到任务仍可能把消息重新写回本地库
- UI 还会继续收到 `MEDIA_READY`

建议：

- delete 路径必须同时取消该 `message_id` 的 media prefetch / attachment download
- 后台媒体任务写回前也要再确认消息是否仍存在

### F-300：消息删除不会清理已下载到本地的附件文件

状态：已修复（2026-04-14）

现状：

- `download_attachment()` 会把文件写入 `%TEMP%\\assistim_downloads`
- `delete_message()` / `_process_delete()` / `db.delete_message()` 都不会删除对应文件

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 即使消息被本地删除，附件明文仍会长期残留在本机
- 这对“本地删除消息”的产品语义和隐私边界都不成立

建议：

- delete message 必须补本地附件文件清理
- 至少对 `local_path` 命中的下载缓存做 best-effort 删除

### F-301：媒体消息手动重试会先上传文件，入队失败后留下孤儿上传

状态：已修复（2026-04-14）

现状：

- `retry_message()` 对媒体消息会先 `prepare_attachment_upload()`，再 `upload_chat_attachment()`
- 只有上传成功后才会构建 pending outbound 并尝试 `_enqueue_pending_message()`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 如果上传已经成功，但之后入队失败或 transport queue 失败
- 远端会留下一个没有正式消息引用的孤儿附件对象

建议：

- 媒体 retry 至少要有“上传成功但发送未开始”的回滚策略
- 更稳妥的模型是把上传结果和发送入队做成一条可恢复事务链

### F-302：媒体消息重试会在发送真正开始前，先把失败消息改写成“已上传”形态

状态：已修复（2026-04-14）

现状：

- `retry_message()` 在上传成功后会立即：
  - `message.content = file_url`
  - 重写 `message.extra`
  - `save_message(message)`
- 然后才去构建 pending 并尝试入队

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 一旦后续入队失败，本地失败消息已经被改成“远端文件已准备好”的形态
- 失败态消息会带着半成功的 remote upload 信息继续残留

建议：

- 上传成功后的 remote metadata 应先挂在临时 retry context
- 只有真正重新入队成功后，再 canonicalize 到正式消息记录

### F-303：媒体消息后续重试会复用旧上传和旧加密产物，不会重新加密

状态：已修复（2026-04-14）

现状：

- `_needs_media_upload()` 只要发现已有 `remote_url` 或 `message.content` 已是上传地址，就直接返回 `False`
- 后续 retry 会跳过 `prepare_attachment_upload()`，继续复用旧 `attachment_encryption` 和旧远端文件

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 如果 retry 发生在身份变化、成员变化、加密上下文变化之后，本地不会重新生成新的密文附件
- 媒体 retry 和文本 retry 的安全语义继续分裂

建议：

- 媒体 retry 不能只靠“是否已有 remote_url”判断是否跳过重加密
- 对 E2EE 附件，至少要把当前身份/成员版本纳入 retry 决策

### F-304：`refresh_remote_sessions()` 在 unread 端点失败时会直接打崩整轮刷新

状态：已修复（2026-04-14）

现状：

- `_fetch_remote_unread_counts()` 失败时返回 `None`
- `refresh_remote_sessions()` 却会直接 `unread_count_map.get(...)`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 附属的 unread 端点一旦失败，本应还能继续的 session snapshot refresh 会整体失败
- 这让“会话列表刷新”和“未读数刷新”被错误地绑成了一条 fate-sharing 链

建议：

- `refresh_remote_sessions()` 必须把 unread refresh 视为可降级能力
- unread 失败时应继续完成 snapshot replace，而不是让整轮 refresh 崩掉

### F-305：`refresh_remote_sessions()` 失败时会把 stale 本地 sessions 冒充成 fresh 结果返回

状态：已修复（2026-04-14）

现状：

- `fetch_sessions()` 抛错时，`refresh_remote_sessions()` 只记日志后 `return self.sessions`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 上层调用方拿不到“这次 refresh 其实失败了”的信号
- stale 本地 cache 会被误当成 fresh authoritative snapshot 继续驱动后续 UI 和 warmup

建议：

- refresh API 必须显式区分“刷新成功”和“返回本地旧快照”
- 不要继续用 `list[Session]` 单返回值掩盖 freshness 语义

### F-306：群成员管理窗口在加载好友候选失败时只记日志，不给用户任何错误反馈

状态：已修复（2026-04-14）

现状：

- `_open_add_members_dialog_async()` 会直接 `await self._ensure_contacts_cache()`
- 这条路径没有本地 `try/except`
- 一旦 `load_contacts()` 失败，异常只会落到 `_finalize_ui_task()` 的 logger

证据：

- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)

影响：

- 用户点击“添加成员”后，窗口可能什么都不发生
- 群成员管理的关键 mutation 入口会退化成静默失败

建议：

- 打开候选选择器的路径也要有正式错误反馈
- 不要把“任务失败日志”当作 UI 层的错误处理

### F-307：`SessionPanel` 收到空的全量会话快照时不会清空侧边栏

状态：已修复（2026-04-14）

现状：

- `SessionPanel._on_session_updated()` 只有在 `if sessions:` 为真时才会走 `_load_all_sessions_safe(sessions)`
- authoritative full reload 如果结果是 `[]`，这条分支会被直接跳过

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2/client/ui/widgets/session_panel.py)

影响：

- manager 已经把 authoritative session set 清空了，侧边栏仍会保留旧会话
- stale selection 和 ghost rows 会继续留在 UI 上

建议：

- full reload 必须显式区分“有会话”和“空快照”
- 空快照也要走正式的 model replace / clear 分支

### F-308：重复的 `SessionEvent.CREATED` 会在会话侧边栏里插入重复行

状态：已修复（2026-04-14）

现状：

- `SessionPanel._on_session_created()` 会直接 `_add_session_safe(session)`
- `SessionModel.add_session()` 只按排序插入，不检查 `session_id` 是否已存在

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2/client/ui/widgets/session_panel.py)
- [D:\AssistIM_V2\client\models\session_model.py](D:\AssistIM_V2/client/models/session_model.py)

影响：

- 只要上游重复发一次 `CREATED`，侧边栏就可能出现重复会话项
- model 和 `SessionManager._sessions` 的单一真相会直接分裂

建议：

- `CREATED` 消费前先按 `session_id` 去重
- 或者把新增语义改成“upsert into model”，不要继续盲插入

### F-309：会话搜索弹层被外部关闭时会直接清空用户关键词

状态：已修复（2026-04-14）

现状：

- `SessionPanel._on_search_flyout_closed()` 会直接 `self.search_box.clear()`
- 用户只要点到弹层外面，关键词就会被本地抹掉

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2/client/ui/widgets/session_panel.py)

影响：

- 搜索上下文无法保留
- 用户关闭弹层后没法继续基于原关键词调整或重试

建议：

- 外部关闭 flyout 时只关闭结果层，不要强制清空关键词
- 清空关键词应只发生在显式 clear 操作

### F-310：会话搜索结果点击后会先清空搜索，再尝试打开目标

状态：已修复（2026-04-14）

现状：

- `SessionPanel._on_search_result_activated()` 会先 `clear_search()`
- 然后才 `emit search_result_requested(payload)`

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2/client/ui/widgets/session_panel.py)

影响：

- 如果后续打开会话/联系人/消息失败，用户已经丢失原搜索结果和关键词
- 会话搜索的失败重试体验会明显断裂

建议：

- 搜索结果激活应在导航成功后再清理搜索态
- 至少在失败时保留当前关键词和结果列表

### F-311：`SessionManager.select_session()` 只要选中会话就会清掉 `@我` 标记

状态：已修复（2026-04-14）

现状：

- `select_session()` 一开始就把 `_current_session_id = session_id`
- 如果 `selected_session.extra["last_message_mentions_current_user"]` 为真，会立即置回 `False` 并落库
- 这一步发生在“会话是否真的前台可读”之前

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 只要程序化选中会话，哪怕窗口不在前台、消息也还没加载，`@我` 提醒就会被清掉
- “已选中”和“已读过/已看见”再次混成了一类

建议：

- `@我` 标记应跟真实 foreground-readable 语义绑定
- 不要在单纯 `select_session()` 时就清理 mention state

### F-312：未读数同步把“服务端没返回这个 session”直接当成 `0`

状态：已修复（2026-04-14）

现状：

- `refresh_remote_sessions()` 和 `_reconcile_unread_counts()` 都会用 `unread_count_map.get(session_id, 0)`
- 也就是说，只要 unread snapshot 里缺一条 session，客户端就会把它当成 authoritative `0`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- unread 端点只要返回部分数据，客户端就会把缺失会话的未读数静默清零
- 这会把“快照不完整”和“真实 0 未读”错误地混成一类

建议：

- 缺失项必须视为“未知”，不能默认成 0
- unread refresh 要么要求完整快照，要么对缺失项保持原值

### F-313：启动期 history prefetch 在任务运行期间不会接纳新的高优先级会话批次

状态：已修复（2026-04-14）

现状：

- `ChatInterface._schedule_initial_history_prefetch()` 只要发现 `_startup_history_prefetch_task` 还在跑，就直接返回
- 后续更新过的会话列表不会重新排新的 warm batch

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 如果初始 warmup 正在跑，后面新出现的置顶/最新会话可能一直得不到预热
- startup warmup 的热区会长期停留在旧快照上

建议：

- startup warmup 至少要支持“当前批次结束后按最新 session set 再排一轮”
- 不要把一次性 warmup 任务当成长期正确的 authoritative prefetch 计划

### F-314：当前会话 active 状态的异步更新没有绑定 session_id，晚到任务会打错目标

状态：已修复（2026-04-14）

现状：

- `ChatInterface._set_current_session_active()` 异步调 `chat_controller.set_current_session_active(is_active)`
- 这条调用不带 `session_id`
- `SessionManager.set_current_session_active()` 又是对“当前 `_current_session_id`”生效

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 快速切会话或 hide/show 时，晚到的 active/inactive 任务可能落到另一个 session 上
- 错误 session 的 unread 会被清零，read state 也会跟着错乱

建议：

- active 状态更新必须带上 session_id 或 generation
- 不要再让“当前会话是谁”在异步边界外重新解析

### F-315：当前用户资料变化后，联系人页的 groups-only refresh 失败会静默吞掉

状态：已修复（2026-04-14）

现状：

- `MainWindow._on_profile_changed()` 只会调用 `contact_interface.refresh_groups_after_profile_change()`
- 这条路径最终跑 `_refresh_groups_only()`
- `_refresh_groups_only()` 没有任何 `try/except`

证据：

- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 当前用户资料变更后，只要 groups refresh 失败，联系人页不会给任何用户反馈
- 页面会继续停在旧 groups/self-profile 视图上

建议：

- 这条 profile-change refresh 也要有正式错误反馈
- 不要把关键 UI 同步路径退化成“后台任务失败只记日志”

### F-316：联系人页实时插入新的好友请求时，不会按正式顺序插入

状态：已修复（2026-04-14）

现状：

- `_upsert_request_record()` 对新 request 直接 `self._requests.insert(0, request)`
- 不按 `_ordered_requests()` 或 `created_at` 重新排序

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 新请求的显示顺序会依赖“到达顺序”，而不是页面正式排序规则
- requests 列表容易出现“较旧请求插到最上面”的错序

建议：

- 新 request upsert 后要统一按正式排序规则重排
- 不要继续用 `insert(0, ...)` 充当排序策略

### F-317：联系人页更新已有好友请求时，不会重新计算它在列表中的位置

状态：已修复（2026-04-14）

现状：

- `_upsert_request_record()` 命中已有 request 时，只会原地替换并更新 item view
- 不会重建 `_requests` 的正式排序，也不会移动现有列表项

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 请求从 pending 变 accepted/rejected，或方向/分组语义变化后，仍可能留在旧位置
- requests 页会逐渐偏离它自己的 ordering contract

建议：

- request update 之后也要走统一排序和重定位
- 不要把“更新内容”和“维持顺序”拆成两套不相干逻辑

### F-318：联系人页搜索弹层被外部关闭时也会直接清空关键词

状态：已修复（2026-04-14）

现状：

- `ContactInterface._on_search_flyout_closed()` 会执行 `self.search_box.clear()`
- 用户只要点到 flyout 外面，输入框内容就没了

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 联系人页搜索无法保留上下文
- 用户很难基于原关键词继续 refine 或重试

建议：

- flyout close 和 clear keyword 应该拆成两件事
- 外部关闭结果层时不要自动清输入框

### F-319：好友请求详情在 `counterpart_id` 缺失时会去加载全局 Moments

状态：已修复（2026-04-14）

现状：

- `ContactInterface._select_request()` 会无条件调用 `_load_detail_moments(counterpart_id, ...)`
- 如果 `counterpart_id` 为空字符串，`DiscoveryService.fetch_moments(user_id="")` 会退化成不带 `user_id` 参数的 `/moments`

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\controllers\discovery_controller.py](D:\AssistIM_V2/client/ui/controllers/discovery_controller.py)
- [D:\AssistIM_V2\client\services\discovery_service.py](D:\AssistIM_V2/client/services/discovery_service.py)

影响：

- 缺资料的 request 详情可能展示成“全局 moments 时间线”
- 请求详情和对方资料域会被错误混线

建议：

- request detail 在 `counterpart_id` 缺失时应直接禁用 moments load
- 不要把空 `user_id` 继续透传到 discovery 查询

### F-320：当前用户资料变化后，联系人页只刷新 groups，不刷新 requests 里的“我自己”视图

状态：已修复（2026-04-14）

现状：

- `MainWindow._on_profile_changed()` 只调用 `refresh_groups_after_profile_change()`
- 联系人页并没有对应的 contacts/requests self-profile refresh
- 但 outgoing requests 详情和列表里确实会展示当前用户自己的 sender_name / sender_avatar

证据：

- [D:\AssistIM_V2\client\ui\windows\main_window.py](D:\AssistIM_V2/client/ui/windows/main_window.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 当前用户改昵称/头像后，groups 侧会更新，但 requests 里“我发出的请求”仍可能显示旧资料
- 同一个联系人域内部会出现 self-profile 口径分裂

建议：

- 当前用户 profile change 不能只刷 groups slice
- 至少要把 requests 里 self-facing 文案和头像一起纳入刷新范围

### F-321：群成员管理窗口 busy 时仍允许点击成员操作，第二个动作会取消第一个动作

状态：已修复（2026-04-14）

现状：

- `GroupMemberManagementDialog._set_busy()` 只禁用 `add_button` 和 `search_edit`
- 成员行里的 promote/demote/transfer/remove 按钮不会被禁用
- `_set_mutation_task()` 又会无条件取消旧的 `_mutation_task`

证据：

- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)

影响：

- 用户在一个 mutation 尚未结束时还能点第二个成员动作
- 新动作会直接 cancel 掉前一个 in-flight mutation，留下局部成功/局部失败的混乱状态

建议：

- busy 状态必须覆盖整行成员操作按钮
- mutation task 不应因为新的 UI 点击就被盲取消

### F-322：联系人页的 `restore_selection(full_reload=False)` 只恢复高亮，不恢复 detail payload

状态：已修复（2026-04-14）

现状：

- `restore_selection(full_reload=False)` 在命中当前可见项时，只会：
  - `_clear_selection()`
  - `item.set_selected(True)`
  - `_show_detail_panel()`
- 不会重新 `set_contact/set_group/set_request`

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- slice-only rebuild 后，左侧选中态可能是新的，但右侧 detail 仍是旧 payload
- 这条 helper 会持续制造“列表新、详情旧”的局部 stale state

建议：

- `restore_selection()` 不能只恢复选中高亮
- 命中当前项时必须同步重建 detail payload

### F-323：联系人搜索会出现“总数有命中，但界面一条都不显示”的计数/渲染分裂

状态：已修复（2026-04-14）

现状：

- `count_search_contacts()` 基于 `contact_search_fts` 计数，FTS 表包含 `display_name`
- 但 `SearchManager._highlight_contact_match()` 并不处理 `display_name`
- `GlobalSearchResultsPanel` 又只会在 `results.contacts` 非空时才渲染联系人 section，却继续使用 `contact_total` 作为“查看更多”计数

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- 本地搜索可能已经命中联系人，但 flyout 里联系人 section 仍然直接消失
- 搜索“总数”和“可见结果”不再属于同一个 contract

建议：

- 计数和可渲染结果必须使用同一套匹配口径
- 要么 render 支持 `display_name`，要么 count 也别把它算进去

### F-324：`SessionManager.select_session()` 在 session 不存在时也会把它设成当前会话

状态：已修复（2026-04-14）

现状：

- `select_session()` 一上来就 `self._current_session_id = session_id`
- 之后才去 `_sessions.get(session_id)`
- 即使 `selected_session is None`，也仍会继续发 `SessionEvent.SELECTED`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 晚到的 select task 如果撞上会话已被移除，会把 manager 留在一个 ghost `current_session_id`
- 后续 active/unread/read-receipt 逻辑都会围着一个并不存在的 session 转

建议：

- `select_session()` 应先确认 session 仍存在，再提交 current selection
- 不存在时要么拒绝选择，要么回退到 `None`

### R-034：好友请求补名称仍是无上限并发的 `fetch_user` N+1

状态：已修复（2026-04-14）

修复说明：

- requests 列表不再走 `_load_request_user_names()` 并发补名，客户端已删除这条逐用户 `fetch_user` 路径。

现状：

- `ContactController._load_request_user_names()` 对所有缺名 user_id 直接 `asyncio.gather(*fetch_user(...))`
- 没有并发上限，也没有批量接口

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)

影响：

- request 列表一旦缺资料用户较多，就会瞬时打出一批 `fetch_user`
- 这是明显的性能和后端压力风险

建议：

- 至少加并发上限
- 更好的做法是把 request 列表基础展示字段并回正式接口，不再依赖客户端补资料 N+1

### R-035：本地聚合搜索每次输入都会并发跑 6 条数据库查询，属于结构性冗余

状态：已修复（2026-04-14）

现状：

- `SearchManager.search_all()` 每次关键词变化都会同时跑：
  - message search
  - contact search
  - group search
  - message count
  - contact count
  - group count

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- 本地搜索的每次键入都会触发重复计数/查询工作
- 这对 sidebar 搜索这种高频交互属于明显的性能冗余

建议：

- 先收口“列表结果”和“总数”是否真的都需要实时
- 如果需要，也应尽量复用一次查询结果，而不是每个 domain 再做一条 count

### F-325：会话侧边栏搜索在宿主窗口移动或缩放时会直接清空关键词

状态：已修复（2026-04-14）

现状：

- `GlobalSearchPopupOverlay.eventFilter()` 在 parent 或 anchor `Resize/Move/Hide` 时会直接 `close_overlay()`
- `SessionPanel._on_search_flyout_closed()` 又会在 overlay 关闭时无条件 `search_box.clear()`

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2/client/ui/widgets/session_panel.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- 用户拖动窗口、调整布局、切换可见性时，正在输入的会话搜索会被破坏性清空
- 搜索输入框和结果层的生命周期被错误绑死

建议：

- geometry close 只能关闭 overlay，不应顺带清搜索框
- 只有显式 clear 才应清掉关键词

### F-326：联系人侧边栏搜索在宿主窗口移动或缩放时也会直接清空关键词

状态：已修复（2026-04-14）

现状：

- 联系人页复用了同一个 `GlobalSearchPopupOverlay`
- `ContactInterface._on_search_flyout_closed()` 同样在 overlay close 时直接 `search_box.clear()`

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- 联系人页搜索会因为窗口移动、尺寸变化、anchor 重排而丢失关键词
- 联系人页和聊天页共享了同一种破坏性 close contract

建议：

- 联系人侧边栏也应把“关闭结果层”和“清输入框”拆开
- 外部 close 不应破坏搜索上下文

### F-327：本地消息搜索的“总数”实际是命中会话数，不是命中记录数

状态：已修复（2026-04-14）

现状：

- `SearchManager.search()` 返回的是“按 session 聚合后的消息命中”
- `Database.count_search_message_sessions()` 统计的也是 `COUNT(DISTINCT session_id)`
- 但 UI 文案里仍把它当作“聊天记录”总数来展示

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- 搜索结果里的 message section 会把“会话数”和“消息记录数”混成一类
- “查看更多({count})” 和用户对“聊天记录搜索”的直觉不一致

建议：

- 要么正式声明 message section 是“按会话聚合”
- 要么把计数和文案改成真正的命中消息条数

### F-328：聊天页侧边栏搜索结果打开任务没有串行化，快速连续点击会让旧目标反扑

状态：已修复（2026-04-14）

现状：

- `ChatInterface._on_sidebar_search_result_requested()` 直接 `_schedule_ui_task(_open_sidebar_search_result(...))`
- 这条链路没有像 `MainWindow._set_contact_open_task()` 那样保留“仅最新一次”的任务槽位

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 用户连续点两个搜索结果时，两个 open task 会并发推进
- 晚完成的旧任务仍可能把 UI 拉回前一个目标会话

建议：

- 会话搜索结果打开也应改成 latest-wins 的 keyed task
- 打开链路要么串行，要么加 generation guard

### F-329：`CreateGroupDialog` 的默认群名只放在 placeholder 里，留空提交时不会真的带上

状态：已修复（2026-04-14）

现状：

- `CreateGroupDialog._update_name_placeholder()` 会把选中成员生成的默认群名写进 placeholder
- 但 `_create_group()` 仍然只取 `self.name_edit.text().strip()`
- 输入框留空时，提交给服务端的 `name` 还是空字符串

证据：

- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)

影响：

- UI 暗示“默认群名会生效”，实际提交却是空名
- 建群结果和用户在弹窗里看到的默认命名预期不一致

建议：

- 留空提交时应显式回退到 `_default_group_name()`
- placeholder 不能冒充真正的 submit value

### F-330：`StartGroupChatDialog` 计算了默认群名，但创建时始终提交空字符串

状态：已修复（2026-04-14）

现状：

- `StartGroupChatDialog` 有 `_default_group_name()` / `_default_group_name_preview()`
- 但 `_create_group_async()` 里硬编码 `name = ""`

证据：

- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)

影响：

- 从私聊“开始群聊”时，界面上的默认命名逻辑完全不会进入正式请求
- 这条链路和常规建群弹窗的命名 contract 已经分叉

建议：

- `StartGroupChatDialog` 也应提交实际默认群名
- 两条建群入口要复用同一套 naming contract

### F-331：`CreateGroupDialog` 创建中仍允许改选成员，弹窗发出的本地 group preview 可能和实际提交成员不一致

状态：已修复（2026-04-14）

现状：

- `_create_group_async()` 只禁用了 `create_button`
- 成员列表、搜索框、选中集合仍可继续变化
- 成功后 `group_created.emit(enrich_created_group(group, self._selected_contacts()))` 用的是“完成时的当前选中态”，不是“提交时的成员快照”

证据：

- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)

影响：

- 右侧联系人域收到的新群 preview 可能和服务端真正创建的成员集合不一致
- 用户会看到“提交的是 A+B，回来的本地预览却像 A+B+C”之类的错配

建议：

- 创建开始时就冻结提交成员快照
- in-flight 期间要禁掉成员选择和搜索输入

### F-332：`StartGroupChatDialog` 也允许在创建中改选成员，回写本地 preview 时同样会漂移

状态：已修复（2026-04-14）

现状：

- `StartGroupChatDialog._create_group_async()` 只禁用了 `complete_button`
- 成员列表仍可继续 toggle
- `group_created.emit(...)` 依然读取的是完成时的 `_selected_contacts()`

证据：

- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)

影响：

- 从私聊发起建群时，本地返回的 group preview 也可能和实际请求成员集不一致
- 这会进一步放大聊天页和联系人页对“新群长什么样”的分歧

建议：

- 与 `CreateGroupDialog` 统一，提交开始就冻结成员快照
- in-flight 期间不要再让用户改选

### F-333：`CreateGroupDialog` 提交成员直接来自 `set`，请求中的成员顺序是不稳定的

状态：已修复（2026-04-14）

现状：

- `CreateGroupDialog._create_group_async()` 直接 `list(self._selected_ids)`
- `_selected_ids` 是 `set[str]`

证据：

- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)

影响：

- 同一组选中成员在不同运行次里可能以不同顺序提交
- 如果后端或后续本地 preview/默认群名对成员顺序敏感，就会出现非确定性结果

建议：

- 提交前应基于稳定排序或显式快照生成 member_ids
- 不要直接把 `set` 转成请求 payload

### F-334：`CreateGroupDialog` 在创建过程中关闭弹窗会取消本地 follow-up，但服务端建群可能已经成功

状态：已修复（2026-04-14）

现状：

- `close()/destroy` 会在 `_on_finished()` 里取消 `_create_task`
- 这只是取消客户端 await，不会回滚已经发出的建群请求

证据：

- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)

影响：

- 服务端可能已经创建新群，但本地不会再 `emit group_created`
- 联系人页、聊天页、本地缓存会短时间错过这次 authoritative 变化

建议：

- 建群 in-flight 时不应允许把“关闭窗口”当作取消业务
- 至少要把请求提交后的 authoritative 结果收口完，再允许销毁弹窗

### F-335：`StartGroupChatDialog` 关闭时同样会丢掉已提交建群请求的本地收口

状态：已修复（2026-04-14）

现状：

- `StartGroupChatDialog._on_finished()` 同样会 cancel `_create_task`
- 这条链路没有任何“请求已提交后必须等 authoritative 结果回来”的 guard

证据：

- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)

影响：

- 私聊里发起的建群如果在创建过程中被关掉，服务端可能已成功建群，但本地不会自动打开或并入列表
- 聊天页和联系人页会错过这次建群 side effect

建议：

- “关闭弹窗”不应等价于“取消已发出的建群业务”
- 私聊建群链路也要等 authoritative result 收口

### F-336：`AddFriendDialog` 在发送好友请求过程中关闭窗口，也会丢掉本地 sidebar 更新

状态：已修复（2026-04-14）

修复说明：

- Add Friend 已改成 deferred close：action in-flight 时关闭窗口只会隐藏对话框，等待 committed 请求返回后再销毁窗口并发出本地 sidebar 更新信号。

现状：

- `AddFriendDialog._on_finished()` 会取消 `_action_task`
- 但这同样只是取消客户端 follow-up，不能保证服务端请求没成功

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 好友请求可能已经在服务端创建，但当前设备不会再 `emit friend_request_sent`
- requests 页和本地请求态要等后续 refresh 才能补回来

建议：

- 发送好友请求 in-flight 时，弹窗 close 不应直接当取消业务处理
- 提交成功后的 authoritative sidebar 更新应优先收口

### F-337：群成员管理窗口在 mutation/load 过程中关闭，也会直接丢掉本地 authoritative apply

状态：已修复（2026-04-14）

现状：

- `GroupMemberManagementDialog._on_finished()` 会取消 `_load_task`、`_mutation_task` 和所有 UI tasks
- 这会把 `groupRecordChanged` 后续 fanout 一并切断

证据：

- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 服务端成员变更可能已经成功，但聊天页和联系人页不会再收到本地 authoritative apply
- 群资料、member_count、成员列表会继续停在旧快照

建议：

- mutation 提交后不要再把“关窗口”当作取消 authoritative follow-up
- 至少要让最终 group snapshot fanout 完成

### F-338：`CreateGroupDialog` 的本地过滤不支持 `AssistIM ID`

状态：已修复（2026-04-14）

现状：

- `CreateGroupDialog._rebuild_member_list()` 只按 `display_name/username/signature` 过滤
- 同项目其他联系人搜索入口普遍都把 `assistim_id` 视为正式检索键

证据：

- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 用户在建群弹窗里无法按 AssistIM 号过滤好友
- 同一个联系人域内部，不同入口的搜索 contract 再次分裂

建议：

- 建群筛选至少要覆盖 `assistim_id`
- 联系人域本地过滤字段应统一

### F-339：本地消息搜索把 limit 施加在“原始消息行”上，再做按会话聚合，热门会话会把其它命中会话挤掉

状态：已修复（2026-04-14）

现状：

- `SearchManager.search()` 先 `await _search_messages(..., limit=N)`
- 然后才把返回消息按 `session_id` 聚合成 `SearchResult`

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 一个消息很多的会话可以占满原始前 N 条匹配
- 其它同样命中的会话会被直接挤出搜索结果，哪怕它们本来应该可见

建议：

- 如果 UI 是“按会话聚合”，limit 就应施加在聚合后的 session 结果层
- 不要先按消息截断，再假装自己做的是 session search

### F-340：消息搜索卡片里的“相关记录数”只统计了截断批次里的命中，天然会低报

状态：已修复（2026-04-14）

现状：

- `SearchManager.search()` 的 `match_count` 只是对当前截断批次里的原始消息做累加
- 它不是该 session 在本地的真实总命中数
- 但 UI 卡片直接把它展示成“共 {count} 条相关记录”

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- 搜索卡片会把真实命中数系统性低报
- 用户看到的是“伪权威计数”，不是当前 session 的真实本地搜索结果

建议：

- 卡片计数要么改成真实 total
- 要么明确标成“当前批次命中数”，不要冒充正式总数

### R-036：联系人页的 full reload 和 incremental patch 没有 generation / sequencing 约束

状态：已修复（2026-04-14）

修复说明：

- 联系人页 grouped search 已补 generation guard，reload 后会以新的 generation 重新拉取当前关键词结果。
- 详情页 moments 回填改为按当前选中记录重新解析，晚到任务不再拿旧 payload 覆盖当前详情。

现状：

- `_reload_data_async()` 会整批替换 `_contacts/_groups/_requests`
- `_apply_profile_update_payload()`、`_apply_group_update_payload()`、`_apply_group_self_profile_update_payload()`、`_upsert_*()` 又会在另一条异步路径里直接 patch 同一批内存集合
- 这几条链路之间没有 generation guard，也没有 sequencing contract

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 联系人页会持续存在“晚到 full reload 覆盖较新增量 patch”或“旧增量 patch 覆盖较新 full reload”的可能
- 这会制造 sidebar、detail、cache 之间的 last-writer-wins 混合态

建议：

- 联系人页需要一套正式的 generation / sequencing contract
- full reload 和 incremental patch 不能再裸写同一份内存态

### R-037：两侧边栏搜索把“overlay 生命周期”和“关键词生命周期”绑死，是结构性状态机缺陷

状态：已修复（2026-04-14）

现状：

- session/contact 两个侧边栏都在 `flyout closed -> search_box.clear()`
- overlay 本身又会因为 move/resize/hide 等纯几何事件自动 close

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2/client/ui/widgets/session_panel.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- 搜索状态会持续受到非业务事件干扰
- 这不是单点 bug，而是 sidebar search state machine 本身没有把输入态和结果态拆开

建议：

- query state、results state、overlay state 必须拆成独立状态
- 外部 close 只能影响结果层，不能默认破坏 query

### R-038：联系人/群 mutation 弹窗把“关闭窗口”当成“取消业务”，但服务端 side effect 实际不可撤销

状态：已修复（2026-04-14）

现状：

- `AddFriendDialog`、`CreateGroupDialog`、`StartGroupChatDialog`、`GroupMemberManagementDialog` 都会在 close/destroy 时 cancel 当前 task
- 这些 task 只是客户端 await，不代表服务端 mutation 可回滚

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)
- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)
- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)

影响：

- 任何“提交后关窗”的路径都可能留下 authoritative side effect 已成功、本地 UI 却没收口的 orphan 状态
- 这是联系人域和群域 mutation-heavy UI 的共同结构性风险

建议：

- 提交后要区分“还能取消本地等待”与“不能取消业务语义”
- authoritative follow-up 应独立于弹窗生命周期

### R-039：本地消息搜索当前是“先截断、再聚合、再展示”的结构，排名和覆盖都会系统性偏斜

状态：已修复（2026-04-14）

现状：

- 原始消息查询、聚合会话结果、section total、卡片计数现在不是同一层 contract
- 一部分值是 raw message batch，一部分是 distinct session count，一部分是截断后的 per-session match_count

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- 本地消息搜索的结果覆盖、排序、总数和卡片计数都不再来自单一真相
- 这会持续制造“为什么这个会话没出来 / 为什么显示只有这么几条”的用户困惑

建议：

- 先明确 message search 的正式语义到底是“按消息”还是“按会话”
- 然后把 query、grouping、counting、rendering 全部挂到同一层 contract 上

### F-341：群搜索命中 `member_search_text` 时，结果卡片会退化成泛化占位文案，丢失实际命中的成员身份

状态：已修复（2026-04-14）

现状：

- `SearchManager._highlight_group_match()` 在群名和 `member_previews` 都没命中、但 `member_search_text` 命中时，会把 `matched_text` 固定写成 `Group member match`
- `GlobalSearchResultsPanel._build_group_card()` 又会直接把这段 `matched_text` 当副标题展示

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- 用户只能看到“某个群成员匹配了”，却不知道到底是哪位成员命中了关键词
- 本地 `member_search_text` 已有的搜索信息在展示层被直接丢失

建议：

- 命中 `member_search_text` 时，副标题至少应回显实际命中的成员片段
- 不要把真实命中成员折叠成泛化占位文本

### F-342：`AddFriendDialog` 的搜索摘要会把“已是好友”的禁用结果也算进“{count} users found”

状态：已修复（2026-04-14）

现状：

- `_search_async()` 用 `len(filtered)` 直接更新 summary
- `_render_search_results()` 又会把 `user.id in _existing_ids` 的结果渲染成 disabled `Already Friends`

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户会看到“找到 N 个用户”，但其中一部分甚至全部其实都不可操作
- Add Friend 弹窗的 summary 和可执行结果不再来自同一口径

建议：

- summary 至少区分“总匹配数”和“可添加数”
- 或者只把真正可发送请求的结果计入主摘要

### F-343：群成员管理弹窗把好友候选缓存成一次性快照，后续会错误提示“没有更多好友可添加”

状态：已修复（2026-04-14）

现状：

- `GroupMemberManagementDialog._ensure_contacts_cache()` 只在第一次调用时加载一次联系人列表
- `_open_add_members_dialog_async()` 后续一直基于这份缓存计算候选；如果缓存里没有新增好友，会直接弹出 `There are no additional friends available to add.`

证据：

- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)

影响：

- 弹窗打开期间联系人域发生变化后，当前窗口会错误地把“缓存里没有候选”当成“系统里没有候选”
- “添加成员”入口会被 stale snapshot 直接卡死

建议：

- 打开 picker 前至少允许重新拉取一次 authoritative contacts
- “无候选”结论不能建立在一次性缓存之上

### F-344：`GroupMemberPickerDialog` 的 parent 绑定到主窗口而不是管理弹窗本身，源弹窗关闭后 picker 仍可能悬挂

状态：已修复（2026-04-14）

现状：

- `_open_add_members_dialog_async()` 创建 picker 时使用的是 `GroupMemberPickerDialog(candidates, self.window())`
- 这意味着 picker 跟随的是顶层窗口，而不是当前 `GroupMemberManagementDialog`

证据：

- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)

影响：

- 关闭群成员管理弹窗后，picker 仍可能继续存活
- 用户会在已经失去上下文的情况下继续提交成员变更

建议：

- picker 应明确以管理弹窗自身为 owner
- 关闭源弹窗时要一并收口子弹窗生命周期

### F-345：`CallWindow.start_media()` 在引擎真正启动前就把 `_media_started` 置为 `True`，一次失败会烧掉后续重试入口

状态：已修复（2026-04-14）

现状：

- `start_media()` 先检查 `_media_started`
- 然后在调用 `self._engine.start()` 之前就把 `_media_started = True`

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 如果第一次 `engine.start()` 因设备、loop 或 aiortc 初始化失败而没有真正启动，后续再调 `start_media()` 会直接 no-op
- 通话窗口没有正式的“重新启动媒体”路径

建议：

- 只有在引擎成功进入已启动态后，才能锁定 `_media_started`
- 否则需要显式回滚并允许重试

### F-346：本地消息搜索完全不会索引非加密附件的文件名/类型，用户无法按可见附件名称搜索

状态：已修复（2026-04-14）

现状：

- `message_search_fts` 只索引 `messages.content`
- 附件名、类型、大小等可见信息实际存放在消息 `extra` 里，没有进入搜索索引

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 图片、视频、文件消息即使在 UI 上显示了正式文件名，也无法按文件名搜索
- 本地消息搜索只覆盖文本内容，不覆盖附件这一类正式消息载荷

建议：

- 本地消息搜索索引应明确纳入附件名称和基础 metadata
- 不要让“看得见的文件名”变成“搜不到的数据”

### F-347：加密附件即使已经本地解密出 `local_metadata`，附件名仍不会进入本地消息搜索

状态：已修复（2026-04-14）

现状：

- `MessageManager` 会把成功解密的附件 metadata 写回 `attachment_encryption.local_metadata`
- 但数据库搜索索引只看 `messages.content`，且对 `is_encrypted=1` 的消息直接排除

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 用户已经在本地成功解密出附件名，搜索链路仍把它当成完全不可见
- E2EE 附件会在“能看见、能打开、但永远搜不到”的状态里长期漂移

建议：

- 对已成功本地解密的附件 metadata 建正式索引策略
- “已本地可见”与“可本地搜索”不应继续分裂

### F-348：联系人本地搜索的语义依赖 FTS 是否可用，换台机器同一关键词可能搜得出来也可能搜不出来

状态：已修复（2026-04-14）

现状：

- FTS 路径会搜索 `display_name/nickname/remark/assistim_id/region`
- LIKE fallback 只搜索 `nickname/remark/assistim_id/region`，直接漏掉 `display_name`

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 同一个联系人名称搜索，在启用 FTS 的环境可命中，在 fallback 环境可能直接失效
- 联系人搜索 contract 取决于本机索引能力，而不是业务定义

建议：

- FTS 与 fallback 的字段集合必须统一
- 本地搜索语义不能依赖当前设备碰巧有没有 FTS

### F-349：`CallWindow` 在构造时一次性快照设备可用性和默认设备，热插拔后通话控件状态不会自动刷新

状态：已修复（2026-04-14）

现状：

- `CallWindow.__init__()` 只在构造时读取一次 `QMediaDevices.audioInputs()/audioOutputs()/videoInputs()` 和默认输入设备
- 麦克风、扬声器、摄像头按钮的初始启用态都来自这次快照
- 窗口自身没有订阅任何设备变化事件

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 通话进行中插拔麦克风/摄像头/输出设备后，窗口控件可能继续停留在旧启用态
- UI 会把“一次性开窗快照”误当成运行期权威设备状态

建议：

- 通话窗口不能再用开窗时的设备快照充当运行态真相
- 设备可用性需要正式的 runtime refresh/subscribe 机制

### F-350：远端音频输出 sink 只绑定一次默认输出设备，中途切换系统默认扬声器不会重绑

状态：已修复（2026-04-14）

现状：

- `_QtRemoteAudioOutput._ensure_sink()` 在 `_sink/_io_device/_audio_format` 已存在时直接返回
- 当前 sink 绑定的是创建当下的 `QMediaDevices.defaultAudioOutput()`
- 后续没有任何重建或重绑默认输出设备的逻辑

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 通话中切换系统默认输出设备时，远端音频仍可能继续打到旧设备
- “Speaker on/off” 控件和真实输出路径会逐步脱节

建议：

- 输出设备变化应触发 sink 重建或重绑
- 当前默认音频输出不能只在第一次播放时决定

### F-351：通话时长显示会从权威 `answered_at` 被本地首帧媒体时间重置，计时口径不稳定

状态：已修复（2026-04-14）

现状：

- `sync_call_state()` 收到 `answered_at` 时会先把 `_call_started_at` 设为权威接听时间
- 但 `_mark_call_connected()` 在首个本地判定“已连通”时又无条件写成 `datetime.now()`

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\models\call.py](D:\AssistIM_V2/client/models/call.py)

影响：

- 通话窗口计时会从“服务端/协议接听时间”漂移到“本地首帧媒体到达时间”
- UI 时长、系统消息时长和服务端 answered_at 语义不再一致

建议：

- 先明确通话时长的正式起点到底是 `accepted` 还是“首个媒体帧”
- 一旦选定，就不要在不同层重复改写起点

### F-352：联系人搜索区块的 `total/more(count)` 可能高于实际可渲染条数，用户点展开也看不到计数里的全部结果

状态：已修复（2026-04-14）

现状：

- `search_all()` 的 `contact_total` 来自数据库 count
- 但 contacts 结果集还会再经过 `_highlight_contact_match()` 的二次过滤，未能高亮的记录会被直接丢弃
- `GlobalSearchResultsPanel` 仍会继续使用原始 `contact_total` 渲染区块标题和“查看更多({count})”

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- 联系人搜索区块会承诺一个大于当前可渲染结果的 total
- 用户展开区块后，仍然无法看到计数里宣称存在的全部结果

建议：

- section total 必须和最终可渲染结果来自同一层 contract
- 不要让 post-filter 之后的结果继续复用 pre-filter total

### F-353：`AiortcVoiceEngine` 也把输入设备可用性快照成一次性状态，通话中插拔麦克风/摄像头不会触发重新探测

状态：已修复（2026-04-14）

现状：

- 引擎构造时只按传入的 `audio_input_name/video_input_name` 初始化 `_microphone_available/_camera_available`
- 后续本地采集只会继续尝试打开这两个已选设备名，没有任何设备变化订阅或重新枚举逻辑

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 开始通话后插入新麦克风/摄像头不会被引擎自动感知
- 原设备失效后，引擎也不会自动切换到新的默认输入设备

建议：

- 通话引擎需要正式的设备可用性刷新机制
- 输入设备选择不能继续是“一次构造，整通话固定”

### R-040：`AiortcVoiceEngine.close()` 依赖当前事件循环；close 边界一旦没有 running loop，peer connection 关闭会被直接跳过

状态：closed（2026-04-14）

修复记录：

- `AiortcVoiceEngine.close()` 捕获无 running loop 的 `RuntimeError`，同步释放媒体资源、清空 signaling/ICE 缓存并发出 `Call ended`
- 正常有 loop 的路径继续调度 `_close()`，并在 `_close()` 内等待 tracked tasks 静默
- `CallWindow` 侧通过 `_close_engine()` 保证 close 只执行一次

现状：

- `close()` 先同步 `_release_media_resources()`
- 然后通过 `_launch(self._close, ...)` 把真正的 peer connection close 交给当前 asyncio loop
- `_launch()` 如果没有 running loop，会直接抛 `RuntimeError`

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 一旦 close 发生在 loop teardown 边界，媒体资源会先被释放，但 `RTCPeerConnection.close()` 可能根本没跑
- 这会把通话 close 变成“本地 UI 关了，但底层连接未必关净”的半关闭态

建议：

- 通话 close 不能把 peer connection 关闭完全寄托给“当前一定有活 loop”
- teardown 边界需要可兜底的同步/受控关闭路径

### R-041：`AiortcVoiceEngine._close()` 只 cancel 其它任务，不等待它们真正退出，属于非 quiescent teardown

状态：closed（2026-04-14）

修复记录：

- `_close()` 现在会收集被 cancel 的 tracked tasks，并用 `asyncio.gather(..., return_exceptions=True)` 等待完成
- pending signaling、pending remote ICE 和 remote track 去重状态在 close 后统一清空
- 关闭后的旧任务不再继续保留在通话引擎状态里

现状：

- `_close()` 会遍历 `_tasks`，对未完成任务统一 `task.cancel()`
- 但后续不会等待这些任务真正结束，只是继续往下关 peer connection 和释放媒体资源

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 晚到的 frame/render/playback task 仍可能在 teardown 尾部继续运行
- 通话引擎 close 不是“完全静默后再销毁”，而是“边 cancel 边拆资源”

建议：

- 通话引擎 close 应收口成 quiescent teardown
- cancel 后至少要等待关键媒体任务真正退出

### R-042：预接听阶段的 `_pending_remote_ice` 没有任何上限，异常对端可持续把本地缓存打大

状态：closed（2026-04-14）

修复记录：

- `AiortcVoiceEngine.MAX_PENDING_REMOTE_ICE` 已限制远端 ICE 缓冲
- 远端 description 尚未应用时，超限会淘汰最旧 candidate 后再 append 新 candidate
- 非法 ICE candidate 解析失败会显式上报 `Invalid ICE candidate`，不再静默塞入缓存

现状：

- `_receive_ice_candidate()` 在 `remoteDescription` 未就绪时会直接 `append` 到 `_pending_remote_ice`
- 当前只做少量 timing log，没有容量限制和丢弃策略

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 长时间 pre-answer 或异常 signaling 下，客户端会无限缓存远端 ICE
- 这会把内存增长和通话状态机问题绑定在一起

建议：

- pending ICE 需要正式的上限、过期和丢弃策略
- 不要让预接听缓冲成为无界列表

### R-043：`on_track` 没有任何去重保护，重复 track/重协商可能并行拉起多条远端音频或视频消费任务

状态：closed（2026-04-14）

修复记录：

- `AiortcVoiceEngine` 新增 `_remote_track_keys`
- `on_track` 先按 `(kind, track.id/id(track))` 去重，重复 remote track 不再拉起第二条 audio/video consumer task
- close 时会清空 `_remote_track_keys`，避免跨 call 残留

现状：

- peer connection 的 `on("track")` 每次回调都会直接 `_launch(_play_remote_audio/_render_remote_video)`
- 当前没有按 track kind、track id 或通话阶段做 dedupe

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- duplicate/renegotiated track 事件可能同时拉起多条消费者
- 远端媒体渲染和播放路径会变成“事件触发几次，就开几条任务”

建议：

- 音视频 track 消费需要显式去重和替换语义
- 不要把每次 `on_track` 都当作新建独立消费者

### R-044：联系人本地搜索在 FTS、LIKE fallback、highlight、render 四层使用的是四套不同字段合同

状态：已修复（2026-04-14）

修复说明：

- contacts LIKE fallback、count fallback 与 highlight 现在都纳入 `display_name/nickname/remark/assistim_id/region` 同一字段集。
- 群搜索命中群名时卡片直接展示命中文本；命中成员时优先使用缓存 member preview，不再回退成占位文案。

现状：

- FTS 路径支持 `display_name`
- LIKE fallback 不支持 `display_name`
- `_highlight_contact_match()` 只检查 `nickname/assistim_id/region/remark`
- card 渲染标题又优先展示 `display_name`

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- 同一关键词在“能查到”“能高亮”“能画出来”“卡片怎么显示”四层都可能拿到不同答案
- 联系人搜索缺少单一 authoritative search contract

建议：

- 联系人搜索字段集合必须在 query、count、highlight、render 四层统一
- 不要继续让每一层各自挑字段

### R-045：通话设备可用性当前被建模成一次性启动快照，而不是运行期状态机

状态：已修复（2026-04-14）

现状：

- `CallWindow` 在构造时快照 UI 控件的设备可用性
- `AiortcVoiceEngine` 在构造时快照输入设备名和 `_microphone_available/_camera_available`
- `_QtRemoteAudioOutput` 只在第一次播放时绑定默认输出设备

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 设备插拔、默认设备切换、采集设备失效这类运行期事件都没有正式收口模型
- 通话 UI、引擎状态和真实设备路径会逐步分叉

建议：

- 通话域需要正式的 device-state contract
- UI 控件态、采集态、输出态必须围绕同一套运行期设备状态更新

### R-046：联系人搜索的 section total、展开结果和实际可渲染条目没有单一真相

状态：已修复（2026-04-14）

修复说明：

- Add Friend 搜索现在会先剔除当前用户与已是好友的目标，再按最终可操作结果更新摘要和列表。
- 请求列表 upsert 改为统一排序 contract，requests 页不会再因增量更新打乱顺序。

现状：

- 数据库 count、FTS/LIKE query、highlight 过滤、section `more(count)`、最终 card 渲染现在不是同一层 contract
- 联系人区块的 total 和用户真正能展开看到的条目数之间没有正式一致性保证

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- 联系人搜索区块会持续出现“总数说有这么多，但展开后并没有”的现象
- 搜索 total 不再能被视为可靠的用户可见结果数

建议：

- 联系人搜索需要一套统一的 result contract：query、count、highlight、section total、render 统一产出
- “能显示多少”与“宣称有多少”必须来自同一层

### F-354：`ensure_remote_session()` 发现缓存里已有 session 时会直接返回，消息侧 fallback session 永远得不到 authoritative canonicalize

状态：closed（2026-04-14）

修复记录：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `ensure_remote_session()` 不再把“本地已有同 id session”直接等同于 authoritative 命中
- fallback session 现在通过 `authoritative_snapshot` / `_remember_session()` 显式建模升级关系，显式 open 会优先回源拿 authoritative payload 覆盖旧 fallback

现状：

- `SessionManager.ensure_remote_session()` 一开始就检查 `self._sessions.get(session_id)`
- 只要本地已经有同 id session，就直接返回，不再调用 `fetch_session()`
- 消息侧 `_ensure_session_exists()` / `_build_fallback_session()` 又会先把 fallback session 写进 `_sessions`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 一旦某个会话先被消息侧 fallback bootstrap 进本地缓存，后续显式 `open_session()` 也不会再把它升级成 authoritative session
- fallback session 上的名称、成员、加密模式、通话能力、security state 都可能长期停留在临时值

建议：

- `ensure_remote_session()` 不能把“缓存里有一个对象”直接等同于“已经 authoritative”
- 至少要区分 fallback session 与 canonical session，并允许显式回源修正

### F-355：`ensure_direct_session()` 也会直接复用缓存中的 direct session，消息侧 fallback direct session 不会被 authoritative direct payload 修正

状态：已修复（2026-04-14）

现状：

- `ensure_direct_session()` 先调用 `find_direct_session(user_id)`
- 只要 `_sessions` 里已有一个 direct session 命中该用户，就直接返回，不再走 `create_direct_session()`
- 消息侧 fallback direct session 同样会先进入 `_sessions`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 从联系人页、搜索或聊天页显式打开私聊时，本该顺手拿到的 authoritative direct session 负载会被短路掉
- fallback direct session 的临时字段会一直污染后续 direct-chat 主链路

建议：

- direct session 的“本地命中”与“authoritative direct payload 已确认”需要拆开
- 对 fallback direct session 至少保留一次显式 canonicalize 机会

### F-356：消息侧 fallback session 会把 `encryption_mode` 和 `call_capabilities` 直接写成默认值，而不是 authoritative 会话属性

状态：已修复（2026-04-14）

现状：

- `_build_fallback_session()` 对 `encryption_mode` 调用 `_default_encryption_mode()`
- 对 `call_capabilities` 调用 `_default_call_capabilities()`
- 这条路径完全不依赖服务端 authoritative session payload

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- fallback session 会把“真实会话属性未知”伪装成“明确是 plain / direct-call-capable”
- 后续所有依赖 `session.encryption_mode()` 或 `session.supports_call()` 的逻辑都会被这份默认值带偏

建议：

- fallback session 上的会话能力和加密模式必须显式标记成“未知/未 authoritative”
- 不要继续拿默认值冒充正式会话属性

### F-357：fallback session 不会跑 `_annotate_session_crypto_state()` 和 `_annotate_session_call_state()`，安全态和通话态会长期缺失

状态：已修复（2026-04-14）

现状：

- authoritative session 路径会在 `_build_session_from_payload()` 后调用 `_annotate_session_crypto_state()`
- `_annotate_session_crypto_state()` 内部还会继续调用 `_annotate_session_call_state()`
- 但 `_build_fallback_session()` 只做成员装饰和 display normalize，不会跑这两步

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- fallback session 的 `session_crypto_state`、`security_summary`、`call_state` 都可能长期停留在未初始化或空态
- 会话安全面板和通话能力 UI 会把“还没 authoritative 标注”误当成“没有风险/没有状态”

建议：

- fallback session 至少要有正式的 runtime annotation 路径
- 或者在 authoritative 标注完成前，把这类状态明确标成 unknown

### F-358：direct fallback session 如果是由自己发出的消息触发构建，可能丢失 `counterpart_id`，并把自己的 sender profile 错贴成对端资料

状态：已修复（2026-04-14）

现状：

- `_build_fallback_session()` 在 direct 且 `participant_ids` 缺失时，会回退成 `[current_user_id, message.sender_id]`
- 如果这条消息本来就是当前用户自己发出的，`message.sender_id == current_user_id`，`counterpart_id` 最终可能为空
- 同时 `counterpart_username/avatar/gender` 又直接取自 `message.extra.sender_*`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\models\message.py](D:\AssistIM_V2/client/models/message.py)

影响：

- fallback direct session 会出现“没有 counterpart_id，但 counterpart_username/avatar/gender 是我自己”的错配状态
- direct 会话标题、头像、身份校验入口都会围着这份错误 profile 继续工作

建议：

- direct fallback 不能在缺少 counterpart identity 时直接拿 sender profile 顶替
- 自己发出的消息和对端发出的消息必须分开处理 counterpart 推断

### F-359：fallback direct session 一旦缺失 `counterpart_id`，身份验证和 trust 流程会直接退化成 `missing_counterpart_id`

状态：已修复（2026-04-14）

现状：

- `trust_session_identities()` 和 `get_session_identity_verification()` 都要求 `session.extra["counterpart_id"]`
- fallback direct session 的 `counterpart_id` 在某些自发消息 bootstrap 场景下可能为空

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 明明是 direct session，安全面板却可能直接报告“missing_counterpart_id”
- E2EE identity review / trust peer 入口会被本地 fallback 资料错误卡死

建议：

- 对 direct fallback session 至少要补一条 authoritative counterpart resolve 路径
- 不要让 session 安全面板直接依赖不完整 fallback identity

### F-360：fallback session 的默认 `plain` 加密模式会直接影响后续发送链路，显式发消息前可能跳过本应执行的 E2EE

状态：已修复（2026-04-14）

现状：

- `MessageManager.send_message()` 和 `_prepare_outbound_encryption()` 都先通过 `_load_session_context(session_id)` 读取当前缓存 session
- 发送是否进入加密路径取决于 `session.uses_e2ee()`
- fallback session 的 `encryption_mode` 又来自 `_default_encryption_mode()`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 如果一个实际 E2EE 会话先被 fallback 成 `plain`，用户在 authoritative refresh 到来前主动发送消息，发送链路可能直接跳过加密
- 这已经不只是展示错，而是会影响真正的业务行为

建议：

- fallback session 上的加密决策不能直接参与正式发送链路
- 在 authoritative `encryption_mode` 未确认前，要么阻塞发送，要么强制补一次会话 canonicalize

### F-361：startup history warmup 用 `asyncio.gather()` 直接并发所有 worker，任意一个 session 预热失败都会打断整批 warmup

状态：已修复（2026-04-14）

现状：

- `ChatInterface._warm_history_pages()` 用 `asyncio.gather(*(worker(...)))`
- `worker()` 内部直接 `await self._prime_history_page(session_id)`，没有局部异常隔离

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 只要一个 session 的历史加载失败，后面剩余 session 的 warmup 也会整批取消
- startup prefetch 会从“多 session best effort”退化成“任一失败即批量中断”

建议：

- warmup worker 需要 per-session 错误隔离
- 不要让单个 session 的失败打断整批预热

### F-362：侧边栏搜索只用“关键词是否相同”做 latest-wins 判定，连续两次相同关键词搜索仍可能发生旧结果反扑

状态：已修复（2026-04-14）

现状：

- `SessionPanel._run_global_search()` 和 `ContactInterface._run_global_search()` 完成后只检查 `search_box.text().strip() == keyword`
- 没有 task generation / request token
- 如果两次同关键词搜索前后数据集不同，较早任务晚到时仍可覆盖较新的结果

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2/client/ui/widgets/session_panel.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 侧边栏搜索无法真正做到 latest-wins
- 用户可能看到“同一个关键词，结果又跳回旧快照”的反扑

建议：

- grouped search 需要 generation token
- 不能继续只靠“当前输入框里还是不是这个关键词”来判结果是否过期

### F-363：`open_session()` 遇到“manager 里有 session、但侧边栏 model 里没有”时不会修复这份漂移，导航会直接失败

状态：已修复（2026-04-14）

现状：

- `ChatInterface.open_session()` 先 `focus_session(session_id)`
- 如果 focus 失败，就调用 `ensure_session_loaded()`
- 但 `ensure_session_loaded()` 对已存在于 manager 缓存里的 session 会直接返回现有对象，不会重新 `add_session()` 或重发 update
- 随后 `focus_session()` 再试一次仍然会失败

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 只要 session cache 和 sidebar model 曾发生漂移，搜索/跳转打开会话就会失败
- 这会把“缓存已有、只是 UI 没跟上”的状态误报成“会话打不开”

建议：

- open flow 发现 manager 已有 session 时，也要能修复 sidebar model
- 不要把“session 已缓存”和“session 已出现在列表里”混成一类

### F-364：`open_direct_session()` 对已有 direct session 的处理也依赖 sidebar 已经同步；如果 model 漏掉了该会话，会直接返回失败

状态：已修复（2026-04-14）

现状：

- `open_direct_session()` 先 `find_direct_session(user_id)`
- 命中后直接 `focus_session(session.session_id)`，不会强制 canonicalize 或补一次 sidebar upsert
- 如果列表 model 当前缺这条 session，函数就直接返回 `False`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 联系人页 / 搜索结果跳转到已存在私聊时，可能因为纯粹的 UI 漏同步而打不开
- 这条 direct-chat 主入口对 sidebar/model 漂移没有任何自愈能力

建议：

- `open_direct_session()` 命中已有 session 后也要允许补一条 UI/model repair 路径
- 不要把 `find_direct_session()` 命中直接等同于“可以顺利 focus”

### F-365：`CallWindow.showEvent()` 每次 show 都会强制重新居中，用户手动摆放的窗口位置无法保留

状态：已修复（2026-04-14）

现状：

- `CallWindow.showEvent()` 每次触发都会调用 `_center_on_screen()`
- 这条路径不区分首次展示还是后续 re-show

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 用户只要把通话窗口拖到自己想要的位置，后续再次显示或被重新唤起时就会被强制拉回屏幕中央
- 通话窗口被建模成“临时弹层”，而不是可持续交互的正式窗口

建议：

- 只在首次展示时自动居中
- 后续 re-show 应保留用户自己调整过的位置

### F-366：`CallWindow.start_media()/prepare_media()` 对引擎同步异常没有任何 UI 侧保护，缺 loop 等边界会把窗口留在半启动态

状态：已修复（2026-04-14）

现状：

- `CallWindow.start_media()` 直接调用 `self._engine.start(...)`
- `CallWindow.prepare_media()` 直接调用 `self._engine.prepare(...)`
- `AiortcVoiceEngine._launch()` 在没有 running loop 时会直接抛 `RuntimeError`
- 调用侧没有 `try/except` 或状态回滚

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 一旦 start/prepare 恰好发生在 loop teardown 或异常边界，窗口会先切到 `Connecting...` 或进入预热流程，然后同步抛错
- UI 会留下“看起来正在启动，实际上引擎没起来”的半启动状态

建议：

- 通话窗口调用引擎启动/预热时要有显式异常收口和状态回滚
- 不要让底层 `_launch()` 的同步异常直接穿透到 UI 层

### F-367：音频通话在用户主动关闭扬声器时，首个远端音频帧不会把通话标记为已连通，窗口会长期停在 `Connecting...`

状态：已修复（2026-04-14）

现状：

- `_play_remote_audio()` 只有在 `wrote_audio and self._speaker_enabled and not self._remote_audio_started` 时才会发 `In call`
- 对纯音频通话来说，没有视频帧能补这次“已连通”判定

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)
- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 用户只是本地把 speaker 关掉，通话 UI 就会误判成“媒体还没接通”
- 计时器和连通态会被本地扬声器开关错误绑定

建议：

- 通话连通判定不能依赖扬声器是否开启
- “远端音频已到达”和“本地是否选择播放出来”必须拆开

### F-368：远端音频轨到达时如果本机暂时没有输出设备，音频消费任务会直接退出，之后再插入输出设备也不会恢复

状态：已修复（2026-04-14）

现状：

- `_play_remote_audio()` 开头如果 `not self._remote_audio_output.is_available()`，会直接 `return`
- 这条任务只在 `on_track(audio)` 时启动一次，后面没有重拉起逻辑

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 如果来电时本机恰好没有扬声器/耳机设备，远端音频消费链会当场终止
- 用户之后再插上输出设备，也不会自动恢复播放

建议：

- “当前没有输出设备”不应直接结束整条远端音频消费链
- 至少要允许设备恢复后重新建立播放路径

### F-369：媒体层 `connection failed/disconnected/closed` 只会改状态文案，不会触发正式终态收口，窗口和控制仍会悬挂

状态：已修复（2026-04-14）

现状：

- `CallWindow._on_engine_state_changed()` 对 `connection disconnected/failed/closed` 只会更新状态文字并停计时器
- `ChatInterface` 只有在收到 `CallEvent.ENDED/BUSY/FAILED/REJECTED` 这类 signaling 终态时才会 `_close_call_window()`

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 只要媒体层已经失败，但 signaling 终态没及时到，通话窗口就会以“Disconnected/Connection failed”状态继续悬挂
- 用户仍面对一个未正式结束的窗口和控制面板

建议：

- 媒体层 terminal state 需要和正式 call state machine 收口
- 不能继续要求所有关闭动作都等 signaling 终态来驱动

### R-047：侧边栏 grouped search 缺少 generation guard，重复同关键词搜索的结果会互相覆盖

状态：已修复（2026-04-14）

修复说明：

- 联系人页 grouped search 已补 `_search_generation`，只有当前 generation 的结果才允许写回 overlay。
- 会话侧边栏也同步解耦了 overlay close 与关键词生命周期。

现状：

- session/contact 两个侧边栏的 grouped search 都只保存一个 `_search_task`
- 结果回填时只比对“当前输入框文本是否仍等于 keyword”
- 对相同 keyword 的重复搜索没有 request generation

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2/client/ui/widgets/session_panel.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 同关键词的旧任务只要晚到，就还能覆盖更新后的搜索结果
- 侧边栏搜索没有真正的 latest-wins 保障

建议：

- grouped search 结果回填必须带 generation / request token
- 不能继续只靠 keyword 相等做过期判断

### R-048：通话预接听阶段的本地 `_pending_signals` 没有任何上限，ICE/offer 可以在本地无限排队

状态：closed（2026-04-14）

修复记录：

- `AiortcVoiceEngine.MAX_PENDING_SIGNALS` 已限制 pre-accept signaling queue
- `_emit_or_queue_signal()` 超限时淘汰最旧 pending signal，不再无限 append
- 来电 invite 阶段已移除 hidden prewarm，预接听信令队列不会再被多设备 invite 放大

现状：

- `_emit_or_queue_signal()` 在 `_signaling_ready` 之前会把 signaling 直接塞进 `_pending_signals`
- 当前没有容量限制、没有去重策略，也没有过期淘汰

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 预热阶段如果持续产生本地 ICE 或重复 signaling，本地队列会无限增长
- 这会把“接听前预热”变成又一条无界缓存链

建议：

- pending local signaling 也要有正式的上限和去重策略
- 不要让 pre-accept 队列成为无界列表

### R-049：消息侧 fallback session 一旦落进缓存，就缺少正式的 authoritative upgrade contract

状态：closed（2026-04-14）

修复记录：

- fallback session 已显式区分 `authoritative_snapshot = False`
- `ensure_remote_session()`、`ensure_direct_session()`、消息侧 `_ensure_session_exists()` 都会在远端 payload 可用时把 fallback session 升级成 authoritative session

现状：

- 消息侧 `_ensure_session_exists()` / `_build_fallback_session()` 可以先写入临时 session
- 后续 `ensure_remote_session()` / `ensure_direct_session()` 都会优先命中缓存并短路
- `_remember_session()` 也会在 race 下直接丢弃后到达的 authoritative session 对象

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- fallback session 不是临时占位，而是可能长期升级失败的第二真相
- 这会把会话属性、direct counterpart identity、security state、call capability 一起拖进缓存漂移

建议：

- 明确建模 fallback session 和 authoritative session 的升级关系
- 任何显式 open / direct-open / search-open 都应有机会把 fallback session canonicalize

### R-050：startup history warmup 没有 per-session fault isolation，一条坏 session 会拖垮整批预热

状态：closed（2026-04-14）

修复记录：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_warm_history_pages()` 已按 session 隔离失败
- startup warmup 现在绑定 authoritative session snapshot 批次；`_prime_history_page()` 在本地/远端预热前都会重查 session 是否仍存在，旧 prefetch task 不会再给已移除会话回填历史缓存

现状：

- `_warm_history_pages()` 的 worker 没有本地 `try/except`
- 任何单个 session 在 `_prime_history_page()` 里的异常都会向外冒泡到整轮 `gather()`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- startup prefetch 的稳定性取决于“这一批里是否每一个 session 都正常”
- 一条坏会话会让其它本来可以成功预热的会话全部失去 warmup

建议：

- startup warmup 需要 per-session best-effort 语义
- 错误隔离应下沉到 worker，而不是让整批任务 fail-fast

### F-370：self-sent direct fallback session 在缺失 `participant_ids` 时只会把当前用户写进成员列表，后续根本无法按对端用户重新发现同一私聊

状态：closed（2026-04-14）

修复记录：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 direct fallback 现在会优先吸收消息 payload 里的 `counterpart_*` authoritative metadata
- self-sent direct fallback 不再退化成“participant_ids 里只有自己”，后续 direct reopen、E2EE 发送和通话入口都能继续解析对端

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_build_fallback_session()` 在 direct 且消息里缺失 `participant_ids` 时，会退化成 `[current_user_id, message.sender_id]`
- 如果这条消息本来就是当前用户自己发出的，`message.sender_id == current_user_id`，最终 `participant_ids` 里只剩当前用户自己
- 同文件 `find_direct_session(user_id)` 又只按 `user_id in session.participant_ids` 发现 direct session，不看 `counterpart_id`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 这类 fallback direct session 进了 `_sessions` 之后，后续 `find_direct_session(peer_id)` 根本找不到它
- 联系人发起聊天、搜索命中私聊、`ensure_direct_session()` 都可能再创建第二条 direct session 本地状态

建议：

- direct fallback session 不能在缺失对端身份时把成员列表退化成“只有我自己”
- `find_direct_session()` 至少要在 participant_ids 之外补一层 `counterpart_id` 发现逻辑

### F-371：self-sent direct fallback session 会稳定退化成泛化标题，直到 authoritative 会话快照到达前都无法显示真实对端名称

状态：已修复（2026-04-14）

现状：

- `_build_fallback_session()` 对 direct 会话的标题逻辑是：
  - 对端发来的消息时，用 `sender_name`
  - 自己发出的消息时，用 `counterpart_id or session_name or "Private Chat"`
- 而在 self-sent + `participant_ids` 缺失场景下，`counterpart_id` 本来就可能解析不到

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 会话列表、搜索结果和聊天顶部在 authoritative session 到达前都会显示泛化的 `Private Chat` 或裸 id
- 这条 direct 主链路对“自己先发出第一条消息”的首屏体验很差

建议：

- self-sent direct fallback 不应直接退化成泛化标题
- 至少要补一条基于本地联系人缓存或 authoritative fetch 的对端名称修正路径

### F-372：fallback session 直接把首条消息时间写成 `created_at/updated_at`，一旦没有 authoritative upgrade，会话生命周期和排序语义会被永久带偏

状态：已修复（2026-04-14）

现状：

- `_build_fallback_session()` 创建 `Session` 时把：
  - `created_at = message.timestamp`
  - `updated_at = message.timestamp`
  - `last_message_time = message.timestamp`
- 如果后续 `ensure_remote_session()` / `ensure_direct_session()` 因缓存短路没有 canonicalize，这份临时时间就会长期留在本地

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 会话排序、创建时间、更新时间都可能被首条消息时间错误代替
- fallback session 会继续伪装成 authoritative lifecycle snapshot

建议：

- fallback session 的 lifecycle 时间不能直接等同于消息时间
- 至少要显式标记为 provisional，或在第一次 authoritative fetch 后强制纠正

### F-373：broken direct fallback session 会把后续 E2EE 发送和直接通话一起卡死在“无法解析对端”

状态：已修复（2026-04-14）

现状：

- `MessageManager._resolve_direct_counterpart_id()` 优先从 `session.participant_ids` 里找对端，找不到才回退 `session.extra.counterpart_id`
- `CallManager._resolve_peer_user_id()` 也是同一模型：先扫 `participant_ids`，再看 `counterpart_id`
- 对于 `F-370` 那种 self-sent fallback direct session，`participant_ids` 可能只剩当前用户自己，`counterpart_id` 又为空

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- direct E2EE 文本发送会直接抛 `direct session counterpart could not be resolved for E2EE`
- direct 通话入口也会直接抛 `Unable to resolve the other participant`

建议：

- fallback direct session 的 peer identity 不能继续是“可空”的临时状态
- send/call 入口前至少要有一条 authoritative counterpart resolve 自愈路径

### F-374：本地群成员搜索会把成员备注丢掉，只要成员还有 `display_name/nickname`，按 remark 搜群就会直接 miss

状态：已修复（2026-04-14）

现状：

- [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `_group_member_previews()` 组装搜索文本时按：
  - `display_name`
  - `nickname`
  - `remark`
  - `username`
  - `user_id`
  取第一个非空值
- 这意味着成员一旦同时有 `display_name/nickname` 和 `remark`，remark 就完全不会进入 `member_search_text`

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 用户给联系人加了 remark 后，按备注名搜群成员仍可能搜不到对应群
- 群搜索和联系人搜索对“remark 优先”的正式语义继续分裂

建议：

- group member search text 不能只保留一个首选展示字段
- remark、display_name、nickname 至少都应进入本地索引

### F-375：本地群成员搜索完全忽略 `group_nickname`，按群内昵称搜群成员会直接 miss

状态：已修复（2026-04-14）

现状：

- 联系人/会话展示侧的成员命名通常会考虑 `group_nickname`
- 但 `_group_member_previews()` 里完全没有把 `group_nickname` 纳入本地群搜索索引

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)

影响：

- 群成员在群内有专属昵称时，本地群搜索仍按群外资料匹配
- 用户最自然的“按群内叫法搜这个群”路径会直接失败

建议：

- `group_nickname` 也应进入 `member_search_text` / `member_previews`
- 群内展示语义和群搜索语义要统一

### F-376：本地群成员搜索也会在成员有展示名时丢掉 `username/user_id`，按账号 id 搜群成员仍可能搜不到群

状态：已修复（2026-04-14）

现状：

- `_group_member_previews()` 只保存每个成员的一个首选名字
- 只要 `display_name/nickname/remark` 任一存在，后面的 `username/user_id` 就不会进入索引

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 即使用户知道对方账号名或 user id，本地群搜索仍可能命中不到该群
- 群搜索的“按成员账号查群”能力并不可靠

建议：

- `username/user_id` 不应因为更友好的展示名存在而被索引层丢掉
- 群成员索引应允许多字段并存，而不是单字段优先覆盖

### F-377：晚到的 `offer/answer/ice` 只要还能匹配 `active_call`，就会把用户已经关掉的通话窗口重新建出来并显示回来

状态：已修复（2026-04-14）

现状：

- `ChatInterface._on_call_signal()` 在 `_call_window` 不存在或 call_id 不匹配时，会取 `active_call`
- 只要 `active_call.call_id == payload.call_id`，就直接 `_ensure_call_window(active_call, start_media=False)`
- `_ensure_call_window()` 的默认参数是 `reveal=True`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 用户已经手动关掉的通话窗口，只要晚到一条 signaling，就可能重新弹回来
- 通话窗口的关闭语义不是 terminal close，而更像“暂时隐藏，等晚到信令再复活”

建议：

- `_on_call_signal()` 不应通过普通 reveal 路径重建用户已关闭的通话窗口
- 至少要区分“隐藏预热窗口”“当前活动窗口”“用户已明确关闭”的三种状态

### F-378：不同 `call_id` 的晚到 signaling 还会先把当前窗口关掉，再切到新的 call window，旧信令足以打断当前通话 UI

状态：已修复（2026-04-14）

现状：

- `_on_call_signal()` 只要认定 payload 属于 `active_call`，就会调用 `_ensure_call_window(active_call, ...)`
- `_ensure_call_window()` 发现当前 `_call_window.call_id != call.call_id` 时，会先 `_close_call_window()`
- 然后才创建新的 `CallWindow`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- 只要本地 `active_call` 已被晚到事件带偏，后续一条 signaling 就足以先关掉当前窗口
- 通话 UI 对 call_id 一致性的最后一道保护仍然缺失

建议：

- `_on_call_signal()` 和 `_ensure_call_window()` 之间要补 current-call generation/call_id guard
- 不能继续允许“先关旧窗口、再决定新窗口是否合法”的顺序

### F-379：`_close_call_window()` 会先把 `_call_window` 置空，再执行 `window.end_call()`；一旦 close path 抛错，窗口会变成无引用孤儿

状态：已修复（2026-04-14）

现状：

- `ChatInterface._close_call_window()` 的顺序是：
  - `window = self._call_window`
  - `self._call_window = None`
  - `window.end_call()`
- 但 `CallWindow.end_call()` 又会直接走引擎 close 和窗口 close 路径，本身没有异常兜底

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 只要 `end_call()` 在边界条件下抛错，主界面已经丢掉了对这个窗口的跟踪引用
- 之后窗口还活着，但 `_call_window` 已空，后续 close/signal/state 都无法再正式收口

建议：

- `_call_window` 不应早于 `end_call()` 成功完成就被清空
- 至少要把“正在关闭”和“已关闭”拆成两步状态

### F-380：通话窗口的 End 按钮只会发 hangup，不会本地关闭窗口或停止媒体；一旦 signaling 终态晚到，窗口会继续悬挂

状态：已修复（2026-04-14）

现状：

- `CallWindow.end_control.clicked` 只连接到 `_emit_hangup()`
- `_emit_hangup()` 只发 `hangup_requested`
- 真正关闭窗口的是后续 `ChatInterface._on_call_ended/_on_call_failed/...` 这些终态回调

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 用户点击 End 后，本地窗口和媒体不会立即进入“正在结束”或关闭状态
- 只要 hangup 发送慢、失败或终态 fanout 晚到，用户会看到一个已经点了结束却还挂着的通话窗口

建议：

- End 按钮要么进入本地“ending”态并禁用控件，要么直接走与手动关窗一致的本地收口路径
- 不能继续把“用户已结束通话”和“服务端终态已回来了”混成一个时刻

### F-381：通话窗口的 End 按钮没有任何 in-flight guard，重复点击会连续排队多次 `hangup_call()`

状态：已修复（2026-04-14）

现状：

- End 按钮点击后不会禁用自身
- `_on_call_window_hangup_requested()` 也只是每次都 `_schedule_ui_task(self._chat_controller.hangup_call(call_id), ...)`
- 中间没有“已在结束中”的去重状态

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 用户连续点 End 会排队多次 hangup 请求
- 这会继续放大当前通话链路里“单 call_id 多个重复控制消息”的问题面

建议：

- End/hangup 路径至少需要本地 in-flight guard
- 第一次结束动作发出后，就应把结束控件置成 disabled 或 loading

### F-382：收到来电后会先向对端发送 `call_ringing`，再尝试本地展示 toast 和预热窗口；本地 UI 失败时对端仍会被告知“正在响铃”

状态：已修复（2026-04-14）

现状：

- `ChatInterface._on_call_invite_received()` 里先异步调度 `send_call_ringing(call_id)`
- 然后才继续构造 `IncomingCallToast`、调用 `toast.show()`，以及调度 `_prepare_incoming_call_window()`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 只要本地 toast/window 创建失败，对端仍会先收到“callee 已进入 ringing”的反馈
- caller 看到的通话状态和 callee 实际 UI 可见性可能继续分裂

建议：

- `call_ringing` 至少应在本地来电 UI 成功 surface 后再发送
- 不要继续让“本地还没真正提示用户”和“已经向对端承诺正在响铃”重叠

### R-051：本地群成员搜索索引把 `地区:` 这种中文展示字样直接写进缓存文本，搜索语义和当前 UI 语言绑定在一起

状态：已修复（2026-04-14）

修复说明：

- `ContactController._group_member_previews()` 已改成原始 token 拼接，只保留 `display_name/remark/group_nickname/nickname/username/user_id/region` 去重结果。
- `member_search_text` 不再写入 `地区:` 这类本地化展示前缀。

现状：

- `_group_member_previews()` 在成员有 region 时，会拼出 `"{name}(地区: {region})"`
- 这份文本随后既进入 `member_previews`，也进入 `member_search_text`

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 本地群搜索索引直接绑死在当前中文展示文案上
- 搜索语义和 UI 语言耦合，后续本地化或字段文案调整会直接影响索引结果

建议：

- 本地搜索索引应只存规范化字段值，不要把展示型本地化标签直接混进索引文本

### R-052：由于 `地区:` 被硬编码进 `member_search_text`，像“地区”这类泛词会把大量本不应相关的群都一起命中

状态：已修复（2026-04-14）

修复说明：

- 群成员搜索索引已移除本地化标签字样，`member_search_text` 只保留成员自身字段 token。

现状：

- 任何带 region 的成员都会把 `地区:` 这段固定文案写进 group member search text
- group search 的 LIKE/FTS 都会把这段文本当成正式可检索内容

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 用户只要搜“地区”这类泛词，就可能命中大量仅仅因为成员带了 region 字段的群
- 本地群搜索结果会被无意义的结构性噪声污染

建议：

- 展示标签不能进入正式搜索索引
- region 搜索应只匹配字段值本身，而不是本地化前缀

### R-053：contacts/groups FTS 的自愈条件只有“行数不相等”，同样行数下的脏索引会永久保留下来

状态：已修复（2026-04-14）

修复说明：

- 本地 FTS 自愈已从“只比 row count”升级为 `row count + integrity-check`。
- contacts/groups/message 任一索引 integrity-check 失败都会触发正式 rebuild。

现状：

- `Database._rebuild_search_fts_if_needed()` 对 `contacts_cache/group_search_fts` 只比较：
  - base table row count
  - FTS table row count
- 只要两边行数相等，就不会触发 rebuild

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 纯内容漂移、触发器缺失、局部写坏这类“行数没变但内容错了”的索引问题不会自愈
- 本地搜索可能长期停留在脏 FTS 状态

建议：

- FTS 自愈不能只靠 row count
- 至少要增加 schema/version/hash 或显式 rebuild trigger

### R-054：message 搜索 FTS 会在每次数据库连接初始化时整表 `delete-all + reinsert`，冷启动成本会随着消息量线性增长

状态：已修复（2026-04-14）

修复说明：

- message FTS 现在和 contacts/groups 一样只在 `force`、row count 漂移或 integrity-check 失败时 rebuild。
- 连接初始化不再固定执行整表 `delete-all + reinsert`。

现状：

- `_ensure_search_fts_schema()` 在连接时会调用 `_rebuild_search_fts_if_needed()`
- 该函数对 `message_search_fts` 的逻辑不是“检查后再 rebuild”，而是每次都：
  - `INSERT INTO message_search_fts(message_search_fts) VALUES ('delete-all')`
  - 再把全部 `messages.content` 重新插回去

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 冷启动、重连建库、迁移后 reopen 都会随着本地消息量增长而付出整表重建成本
- 本地搜索索引初始化有明显的线性性能风险

建议：

- message FTS 也要像其它缓存表一样先判定是否需要 rebuild
- 不要继续把全量 message 索引重建挂在每次 connect path 上

### R-055：隐藏预热窗口和正式活动窗口共用同一个 `_call_window` 槽位，预热态与正式通话态没有隔离

状态：已修复（2026-04-14）

现状：

- `_prepare_incoming_call_window()` 会通过 `_ensure_call_window(call, reveal=False)` 创建隐藏预热窗口
- 但 `_ensure_call_window()` 不区分 `reveal=False` 还是正式 show，都会把它写进同一个 `self._call_window`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 后续 `_on_call_signal()`、`_on_call_accepted()`、`_close_call_window()` 都拿这一槽位当“当前正式通话窗口”
- 预热阶段和正式活动窗口的状态边界继续混在一起

建议：

- hidden prewarm window 和 visible active call window 应拆成不同状态或不同引用
- 不要继续用一个 `_call_window` 同时承载两种语义

### R-056：`_on_call_window_hangup_requested()` 不校验 `call_id` 是否仍是当前 active call，旧窗口也能继续向外发 hangup

状态：已修复（2026-04-14）

现状：

- `ChatInterface._on_call_window_hangup_requested()` 收到 `call_id` 后就直接：
  - `_schedule_ui_task(self._chat_controller.hangup_call(call_id), ...)`
- 这里不核对：
  - `self._call_window.call_id`
  - `self._chat_controller.get_active_call().call_id`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 只要旧窗口或孤儿窗口仍能发出 signal，就还能继续对旧 `call_id` 打 hangup
- 通话 UI 到控制面的最后一层 current-call guard 仍未建立

建议：

- hangup relay 前必须校验 `call_id` 仍属于当前 active call
- 旧窗口发出的控制信号应被直接丢弃

### R-057：`_on_call_window_signal_generated()` 同样没有 current-call guard，旧窗口还能继续向外发 `offer/answer/ice`

状态：已修复（2026-04-14）

现状：

- `ChatInterface._on_call_window_signal_generated()` 只做了 payload 类型和 `call_id` 非空校验
- 然后就直接把 `call_offer/call_answer/call_ice` 转发到 `ChatController`
- 不检查该 `call_id` 是否仍是当前窗口 / 当前 active call

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 旧窗口、孤儿窗口或 superseded window 的晚到媒体信令仍可继续发往服务端
- 这会把当前通话状态机外又多开一条“旧窗口直通 signaling”的旁路

建议：

- signal relay 也必须先校验 current active call
- 旧窗口产出的 `offer/answer/ice` 不应再进入正式 signaling 主链路

### F-383：`security_pending` 横幅只看当前已加载消息模型，未加载的待确认消息会被静默隐藏

状态：已修复（2026-04-14）

现状：

- `ChatPanel._pending_security_messages()` 只遍历 `self._message_model.get_messages()`
- `ChatPanel._refresh_security_pending_banner()` 也完全依赖这份当前已加载的消息列表决定是否显示横幅
- 但真正的待确认消息来源并不是“当前视图里是否加载到了这条消息”，而是该会话本地是否仍存在 `AWAITING_SECURITY_CONFIRMATION`

证据：

- [D:\AssistIM_V2\client\ui\widgets\chat_panel.py](D:\AssistIM_V2/client/ui/widgets/chat_panel.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 只要待确认消息不在当前 message model 里，比如：
  - 还没滚动到那一段历史
  - 当前页只加载了最近一屏消息
  - 本地 pending message 数量超过当前 chat panel 的可见缓存
- 横幅就会直接消失
- 用户明明仍有待确认发送的消息，却没有任何稳定入口去执行 `Verify and Send / Discard`

建议：

- `security_pending` 的可见性应来自 session 级 authoritative local state，而不是当前已加载消息视图
- ChatPanel 横幅应查询该 session 是否存在待确认消息，不能只看当前 message model
- 这条状态最好还能同步到会话级提示，而不是只绑定当前聊天面板

### F-384：`security_pending` 本地暂存消息会直接发 `MessageEvent.SENT`，事件语义早于真实发送

状态：已修复（2026-04-14）

修复说明：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 新增 `MessageEvent.SECURITY_PENDING`；命中本地安全确认时只发该事件，不再复用 `MessageEvent.SENT`。
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 已订阅 `SECURITY_PENDING` 并复用当前消息插入逻辑，UI 仍能显示待确认消息，但 transport 生命周期不再被提前标成 sent。
- 已更新 `test_message_manager_queues_security_pending_message_when_identity_review_required` 和 UI boundary 测试。

现状：

- `MessageManager.send_message()` 在命中 `security_pending` 时，只会把消息本地落库成 `AWAITING_SECURITY_CONFIRMATION`
- 此时既没有入 websocket send queue，也没有任何 transport attempt
- 但代码仍然立刻 `emit(MessageEvent.SENT, {"message": message})`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 当前 UI 和上层状态机会把“本地待确认消息”误当成“已经发送中的消息”
- `ChatInterface._on_message_sent()` 也会立刻把它追加到当前消息列表
- `MessageEvent.SENT` 已经不再代表“进入正式发送链路”，只代表“本地出现了一条自发消息”

建议：

- 为 `security_pending` 建独立事件或独立本地状态流，不要复用 `MessageEvent.SENT`
- `SENT` 应只在进入正式 transport 主链后再发

### F-385：同一条 `security_pending` 消息在释放发送时会再次发 `MessageEvent.SENT`，单条消息出现双重 sent 生命周期

状态：已修复（2026-04-14）

修复说明：

- 待确认阶段现在只发 `MessageEvent.SECURITY_PENDING`，释放发送阶段才发 `MessageEvent.SENT`。
- 同一条 pending message 不再经历两次 `SENT` 生命周期；`release_security_pending_messages()` 只负责把 DB 队列里的消息按 FIFO 重新送入正式发送链。
- 已补 `test_message_manager_security_pending_release_uses_database_fifo_queue` 覆盖释放顺序和事件语义。

现状：

- 第一轮：命中 `security_pending` 时会发一次 `MessageEvent.SENT`
- 第二轮：`release_security_pending_messages()` 调 `send_message(existing_message=...)` 时，又会把同一 `message_id` 设成 `SENDING` 并再次 `emit(MessageEvent.SENT, {"message": message})`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 同一条消息会经历两次 `SENT` 事件：
  - 一次是本地待确认
  - 一次才是真正释放到发送链路
- 上层如果把 `MessageEvent.SENT` 当成幂等生命周期事件，就会得到重复、混义的状态推进

建议：

- `security_pending -> release` 应拆成独立事件
- 同一 `message_id` 的 sent 生命周期不应被复用两次

### F-386：新消息加密准备失败时也会先发 `MessageEvent.SENT`，再发 `FAILED`

状态：已修复（2026-04-14）

现状：

- `send_message()` 在 `_prepare_outbound_encryption()` 抛错且 `existing_message is None` 时：
  - 先创建一个 `FAILED` 本地消息
  - 先 `emit(MessageEvent.SENT, {"message": failed_message})`
  - 再 `emit(MessageEvent.FAILED, ...)`
- 这条消息实际上从未进入 send queue

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 一条从未真正发送过的消息，会先被 UI/状态机当成 sent，再马上变 failed
- `ChatInterface._on_message_sent()` 还会先把它追加到消息列表
- 失败语义和发送语义被人为叠在同一条本地失败路径上

建议：

- 本地加密准备失败应直接走 `FAILED` 本地生命周期
- 不要再复用 `MessageEvent.SENT` 作为“本地消息出现了”的通用事件

### F-387：待确认消息释放失败后会被降级成通用 `FAILED`，原始安全待确认语义丢失

状态：已修复（2026-04-14）

现状：

- `release_security_pending_messages()` 会把待确认消息重新送进 `send_message(existing_message=...)`
- 如果这一步在 `_prepare_outbound_encryption()` 里再次失败，代码会直接：
  - `existing_message.status = FAILED`
  - 保存并发 `MessageEvent.FAILED`
- 不会恢复成 `AWAITING_SECURITY_CONFIRMATION`
- 也不会保留“仍需完成身份确认”的正式状态

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 一次释放尝试失败后，这条消息就从“安全待确认”退化成“普通发送失败”
- 用户再也看不出这条消息原本为何被拦截，也失去了原始 security-pending 语义

建议：

- `security_pending` 释放失败应区分：
  - 仍需安全确认
  - 安全确认完成但发送失败
- 不要把两种根因都压成通用 `FAILED`

### F-388：`history_events` 回放没有单事件隔离，一条坏事件会直接中断后续整批 replay

状态：已修复（2026-04-15）

现状：

- `_process_history_events()` 逐条遍历 `events`
- 每条都直接 `await self._handle_ws_message(event_payload)`
- 这里没有单条 `try/except`
- 只要某个 event handler 抛异常，后面的离线事件就不会再继续 replay

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 一条格式异常或状态异常的离线 mutation event，就能把后续整批 offline replay 打断
- 客户端拿到的是“前半批已应用、后半批完全未应用”的半回放状态

建议：

- `history_events` 必须按单事件隔离错误
- 至少要做到：坏事件单独记日志，后续事件继续 replay

### R-058：`history_messages` 会逐条串行解密后再落库，历史同步延迟直接绑定到加密消息数量

状态：已修复（2026-04-14）

现状：

- `_process_history_messages()` 对每条新消息都会先：
  - `_normalize_loaded_message(...)`
  - `await _decrypt_message_for_display(...)`
- 全部串行完成后才统一 `save_messages_batch(saved_messages)`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 一次历史同步里只要加密消息较多，`SYNC_COMPLETED` 就会被单条解密链路线性拖慢
- 同步完成时间直接绑定到本地 E2EE 解密耗时，而不是只绑定 I/O 和批量落库

建议：

- 历史同步和本地解密展示应适当解耦
- 至少不要让整批落库和 sync completion 完全阻塞在串行解密上

### F-389：服务端没有校验 direct 文本 envelope 的 `recipient_user_id` 是否就是当前私聊对端

状态：已修复（2026-04-14）

现状：

- `MessageService._validate_direct_text_envelope()` 只校验：
  - 必填字段存在
  - `recipient_prekey_type` 合法
  - `recipient_prekey_id` 为正整数
- 不校验 envelope 里的 `recipient_user_id` 是否等于当前 direct session 的真实对端

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 服务端会接受“发往本 session，但 envelope 声称目标用户是别人”的 direct 文本密文
- 会话 membership 和 envelope 目标用户之间没有正式绑定

建议：

- direct E2EE envelope 必须校验 `recipient_user_id == direct session counterpart`
- 不要只做字段存在性校验

### F-390：服务端没有校验 direct 附件 envelope 的 `recipient_user_id` 是否就是当前私聊对端

状态：已修复（2026-04-14）

现状：

- `MessageService._validate_direct_attachment_envelope()` 与 direct 文本同样只做字段存在性和枚举校验
- 不校验 `recipient_user_id` 是否对应当前私聊真实对端

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- direct 附件消息也能出现“消息属于 session A，但 envelope 目标用户是别的用户”的分裂态

建议：

- direct attachment envelope 也必须绑定到当前 session 的 authoritative counterpart

### F-391：服务端没有校验 group 文本 envelope 内部的 `session_id` 是否等于当前目标会话

状态：已修复（2026-04-14）

现状：

- `MessageService._validate_group_text_envelope()` 只要求 group text envelope 自身带一个非空 `session_id`
- 但不校验该 `session_id` 是否等于正在发送到的外层 `session_id`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 服务端会接受“外层消息发往 group A，但密文 envelope 自称属于 group B”的 payload
- 外层会话和密文内部 session 语义继续分裂

建议：

- group text envelope 的 `session_id` 必须和当前消息目标 session 严格一致

### F-392：服务端没有校验 group 附件 envelope 内部的 `session_id` 是否等于当前目标会话

状态：已修复（2026-04-14）

现状：

- `MessageService._validate_group_attachment_envelope()` 同样只要求 envelope 里存在非空 `session_id`
- 没有校验它是否等于当前外层 session

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- group 附件消息也能形成“消息属于 session A，但加密 envelope 自称属于 session B”的分裂态

建议：

- group attachment envelope 也必须和当前外层 session 严格绑定

### F-393：服务端没有校验 group 文本 fanout 里的接收方是否属于当前会话成员

状态：已修复（2026-04-14）

现状：

- `MessageService._require_group_fanout()` 只校验：
  - fanout 非空
  - 每项是 dict
  - 每项包含 `recipient_user_id/recipient_device_id/...`
  - `scheme == group-sender-key-fanout-v1`
- 但不校验 `recipient_user_id` 是否真的是当前 group session 的成员

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- fanout 列表和 authoritative group membership 没有正式绑定
- 服务端接受的只是“结构上像 fanout”，不是“语义上属于这个群的 fanout”

建议：

- group text fanout 至少要校验接收方用户集合属于当前群成员集

### F-394：服务端没有校验 group 附件 fanout 里的接收方是否属于当前会话成员

状态：已修复（2026-04-14）

现状：

- group attachment fanout 也走同一套 `_require_group_fanout()` 结构校验
- 不校验 fanout 里的 `recipient_user_id` 是否属于当前群成员

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- group 附件 envelope 也缺少“fanout 接收方集合 == 当前群成员集合”的 authoritative 绑定

建议：

- group attachment fanout 也应绑定当前群成员集，而不是只做形状校验

### F-395：服务端没有校验 group 文本 envelope 的 `member_version` 是否匹配当前群成员版本

状态：已修复（2026-04-14）

现状：

- 群成员版本在客户端 E2EE 流程里被正式建模成 `member_version`
- 但 `MessageService._validate_group_text_envelope()` 并没有校验它是否与当前群 authoritative 成员版本一致

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 服务端无法据此拒绝“基于旧成员快照生成”的 group text envelope
- 群成员变更后的 sender-key 轮换边界没有被服务端正式执行

建议：

- group text envelope 应和 authoritative `member_version` 对齐校验

### F-396：服务端没有校验 group 附件 envelope 的 `member_version` 是否匹配当前群成员版本

状态：已修复（2026-04-14）

现状：

- group attachment 路径同样携带 `member_version`
- 但服务端验证里没有把它和当前 authoritative 群成员版本比对

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 群成员变更后，旧成员快照生成的 group attachment 密文也不会被服务端拒绝

建议：

- group attachment envelope 也应执行 authoritative `member_version` 校验

### F-397：`send_message_to()` 会把 `security_pending` 和本地加密失败消息都直接推进成会话最新预览

状态：已修复（2026-04-14）

修复说明：

- [chat_controller.py](/D:/AssistIM_V2/client/ui/controllers/chat_controller.py) 现在只会把非 `AWAITING_SECURITY_CONFIRMATION`、非 `FAILED` 的新发送消息推进到 session preview。
- 本地安全待确认和加密准备失败不再污染会话最新预览；释放后进入正式 `SENDING` 才会按正常发送链更新。

现状：

- `ChatController.send_message_to()` 不区分消息是真正进入发送链路，还是只停在本地：
  - 先 `message = await self._msg_manager.send_message(...)`
  - 再无条件 `await self._session_manager.add_message_to_session(session_id, message=message)`
- 对 `security_pending` 和“加密准备失败即本地 FAILED”的消息，这一步都会直接刷新 session preview

证据：

- [D:\AssistIM_V2\client\ui\controllers\chat_controller.py](D:\AssistIM_V2/client/ui/controllers/chat_controller.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 会话列表会把“尚未发送 / 实际发送失败”的本地消息直接当成最新会话预览
- 这进一步放大了前面 `MessageEvent.SENT` 语义过宽的问题

建议：

- 会话预览更新也应区分：
  - 本地草稿/待确认
  - 真正进入发送链路
  - 发送失败

### F-398：`MessageEvent.RECOVERED` 当前没有生产订阅方，消息恢复完成后 UI 不会自动收口

状态：已修复（2026-04-14）

现状：

- `MessageManager.recover_session_messages()` 完成后会发 `MessageEvent.RECOVERED`
- 但当前生产代码里没有实际订阅方消费它：
  - `ChatInterface` 不订阅
  - `SessionManager` 不订阅
  - 只有测试里会断言它被发出

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 即使本地/远端消息恢复成功，当前打开的聊天页和会话预览也不会自动按这条恢复结果收口
- 结果更多依赖后续手工刷新、重新打开会话或别的旁路事件

建议：

- `RECOVERED` 不应是死事件
- 至少要让当前聊天页和会话预览能对恢复结果做正式刷新

### R-059：服务端目前把 `sender_device_id/sender_key_id` 基本当成客户端自报字段，没有和认证用户或设备谱系绑定

状态：已修复（2026-04-14）

现状：

- 当前服务端只验证这些字段“存在且格式像样”
- 但不会把：
  - `sender_device_id`
  - `sender_key_id`
- 和当前认证用户、已注册设备、当前 sender-key 世代做 authoritative 绑定校验

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 服务端当前接受的是“客户端声称自己用了哪个设备/哪个 sender key”
- 而不是“服务端确认这是当前用户当前允许使用的设备/密钥代际”

建议：

- 后续如果要把 E2EE envelope 收口成正式服务端边界，这组字段不能继续只做 opaque pass-through

### R-060：`MessageSendQueue.stop()` 会直接取消 worker，队列里尚未发送的消息不会被 drain，也不会被正式标记失败

状态：已修复（2026-04-14）

现状：

- `MessageSendQueue.stop()` 只是：
  - `_running = False`
  - `cancel()` worker task
- 没有：
  - drain queue
  - 把尚未处理的 queued message 回传给 `MessageManager`
  - 给这些消息打上明确失败或保留恢复状态

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- close / teardown 时，队列里尚未真正发送的消息会直接蒸发
- 对上层来说，它们既不是 ACK timeout，也不是 transport failure，只是“没了”

建议：

- send queue 停止前应有 drain / fail / persist 三选一的正式策略

### R-061：`_fetch_remote_messages()` 对每条远端消息都会额外做一次本地 `get_message()`，形成 N+1 本地查询

状态：已修复（2026-04-14）

现状：

- `_fetch_remote_messages()` 遍历远端 payload 时，每条都先：
  - `existing_message = await self._db.get_message(message_id)`
- 然后才做 normalize / decrypt / merge local cache

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 一页远端历史会变成：
  - 1 次 HTTP 拉取
  - N 次本地 `get_message()`
  - 再 1 次 batch save
- 对恢复、翻页、远端补拉这种高频路径来说，这是明显的本地 N+1 开销

建议：

- 这条链至少应改成批量存在性/缓存查询，而不是逐条本地查库

### R-062：`recover_session_messages()` 的远端翻页只用 `oldest_timestamp` 推进，秒级时间戳碰撞会提前截断恢复窗口

状态：已修复（2026-04-14）

现状：

- `recover_session_messages()` 远端翻页时，只用一页里最老消息的 `timestamp` 作为下一页 `before_timestamp`
- 同时又有：
  - `if next_before_timestamp is not None and oldest_timestamp >= next_before_timestamp: break`
- 只要两页边界上存在同秒消息，分页就可能被提前判成“没有再往前推进”

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 高频消息或批量导入场景下，时间戳碰撞并不罕见
- 远端恢复窗口可能被过早截断，导致更早的一部分消息根本不会进入恢复流程

建议：

- 远端恢复分页不要只靠秒级 timestamp
- 应引入更稳定的分页锚点，例如 `(timestamp, message_id)` 或服务端游标

### F-399：服务端没有校验 direct 文本 envelope 的 `recipient_device_id` 是否属于 envelope 声称的接收用户

状态：已修复（2026-04-14）

现状：

- `MessageService._validate_direct_text_envelope()` 只要求：
  - `recipient_user_id`
  - `recipient_device_id`
  - `recipient_prekey_type`
  - `recipient_prekey_id`
- 字段存在且格式合法即可
- 不会去校验这个 `recipient_device_id` 是否真的属于该 `recipient_user_id`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 服务端接受的是“看起来像一个目标设备”的 opaque 字段
- 不是“当前 direct 对端名下真实存在的设备”

建议：

- direct text envelope 必须把 `recipient_device_id` 和 `recipient_user_id` 绑定校验

### F-400：服务端没有校验 direct 附件 envelope 的 `recipient_device_id` 是否属于 envelope 声称的接收用户

状态：已修复（2026-04-14）

现状：

- `MessageService._validate_direct_attachment_envelope()` 同样只做字段存在性和枚举校验
- 不会把 `recipient_device_id` 和 `recipient_user_id` 做设备归属绑定

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- direct 附件密文也缺少“目标设备真实属于这个接收用户”的服务端验证

建议：

- direct attachment envelope 也应绑定接收用户与接收设备的真实关系

### F-401：服务端没有校验 group 文本 fanout 里的 `recipient_device_id` 是否属于该 fanout 项声明的 `recipient_user_id`

状态：已修复（2026-04-14）

现状：

- `_require_group_fanout()` 只校验 fanout item 的字段存在性
- 不会校验 item 里的 `recipient_device_id` 是否真的是 `recipient_user_id` 的设备

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- group text fanout 当前只是“结构上完整”，不是“设备归属上自洽”

建议：

- group fanout item 必须校验 `recipient_user_id -> recipient_device_id` 的真实设备归属

### F-402：服务端没有校验 group 附件 fanout 里的 `recipient_device_id` 是否属于该 fanout 项声明的 `recipient_user_id`

状态：已修复（2026-04-14）

现状：

- group attachment 路径复用同一套 `_require_group_fanout()`
- 同样不校验 `recipient_device_id` 与 `recipient_user_id` 的真实绑定关系

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- group attachment fanout 也只是“字段像样”，不是“语义正确”

建议：

- group attachment fanout 也应绑定接收用户和接收设备的真实关系

### F-403：服务端不会拒绝 group 文本 fanout 里的重复接收项

状态：已修复（2026-04-14）

现状：

- `_require_group_fanout()` 不检查 fanout item 是否重复
- 无论是重复的 `recipient_user_id` 还是重复的 `recipient_device_id`，都不会被拒绝

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 服务端允许同一 group text envelope 带着重复接收项进入正式消息主链
- fanout 去重语义没有被服务端收口

建议：

- group text fanout 至少应拒绝重复 recipient user/device

### F-404：服务端不会拒绝 group 附件 fanout 里的重复接收项

状态：已修复（2026-04-14）

现状：

- group attachment fanout 也走同一套结构校验
- 重复 recipient user/device 不会被服务端拒绝

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- group attachment fanout 同样缺少服务端去重边界

建议：

- group attachment fanout 也应拒绝重复 recipient user/device

### F-405：服务端不会拒绝只覆盖部分成员的 group 文本 fanout

状态：已修复（2026-04-14）

现状：

- 当前 group text fanout 只要求“非空”
- 不要求 fanout 覆盖当前群的全部应收成员/设备

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 只覆盖部分成员的 partial fanout 仍能被服务端当成合法群消息接收
- 群消息“应该发给谁”仍主要依赖客户端自觉

建议：

- 服务端应至少校验 fanout 覆盖当前群 authoritative 接收集合

### F-406：服务端不会拒绝只覆盖部分成员的 group 附件 fanout

状态：已修复（2026-04-14）

现状：

- group attachment fanout 同样只要求“非空且结构完整”
- 不要求覆盖当前群全部应收成员/设备

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- partial attachment fanout 也会被服务端正式接收

建议：

- group attachment fanout 也应校验覆盖范围

### F-407：服务端不会拒绝 group 文本 fanout 把发送者自己也列为接收方

状态：已修复（2026-04-14）

现状：

- `_require_group_fanout()` 不检查 fanout recipient 是否等于发送者本人
- 只要 item 结构完整就会通过

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- group text fanout 当前没有“接收方集合应排除发送者本端”的服务端约束

建议：

- 群 fanout 的服务端语义应显式定义是否允许自投递；如果不允许，应直接拒绝

### F-408：服务端不会拒绝 group 附件 fanout 把发送者自己也列为接收方

状态：已修复（2026-04-14）

现状：

- group attachment fanout 同样没有“发送者是否出现在 recipient 集合中”的服务端判断

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 群附件 fanout 也缺少是否允许 self-recipient 的正式边界

建议：

- group attachment fanout 也应把 self-recipient 语义显式收口

### F-409：服务端没有校验 group 文本 envelope 的 `sender_device_id` 是否属于当前认证发送者

状态：已修复（2026-04-14）

现状：

- 当前 group text envelope 验证并不会把 `sender_device_id` 和当前认证用户做设备归属绑定
- 只要字段存在即可

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 服务端当前接受的是“客户端自报自己用哪个设备发的”
- 不是“这是当前认证发送者名下真实存在的设备”

建议：

- `sender_device_id` 应绑定当前认证用户的设备谱系

### F-410：服务端没有校验 group 附件 envelope 的 `sender_device_id` 是否属于当前认证发送者

状态：已修复（2026-04-14）

现状：

- group attachment 路径同样不校验 `sender_device_id` 与当前发送者的真实设备关系

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- group attachment 也存在“客户端自报发送设备”的服务端信任缺口

建议：

- group attachment envelope 也要绑定当前发送者的设备谱系

### F-411：服务端没有校验 group 文本 envelope 的 `sender_key_id` 是否属于当前 `sender_device_id` 和当前会话

状态：已修复（2026-04-14）

现状：

- 当前 group text 验证会要求存在 `sender_key_id`
- 但不会校验这个 key id 是否：
  - 属于当前 `sender_device_id`
  - 属于当前会话
  - 对应当前允许的 sender-key 代际

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- `sender_key_id` 当前仍是 opaque 自报字段，不是服务端确认过的密钥谱系

建议：

- `sender_key_id` 应和 `sender_device_id + session_id` 一起绑定校验

### F-412：服务端没有校验 group 附件 envelope 的 `sender_key_id` 是否属于当前 `sender_device_id` 和当前会话

状态：已修复（2026-04-14）

现状：

- group attachment 路径也只要求 `sender_key_id` 存在
- 不校验它和当前设备/会话的真实关系

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- group attachment 的 sender-key 谱系也没有服务端 authoritative 边界

建议：

- group attachment envelope 也应把 `sender_key_id` 绑定到当前设备和当前会话

### F-413：`security_pending` 横幅动作来自 session summary，而不是实际待确认消息本身

状态：已修复（2026-04-14）

现状：

- `ChatPanel._refresh_security_pending_banner()` 会先取：
  - `pending_messages = self._pending_security_messages()`
  - `summary = self._current_session.security_summary()`
- 但最终横幅显示的 `action_id` 取的是 `summary["recommended_action"]`
- 不是 pending message 自己 `extra.security_pending.action_id`

证据：

- [D:\AssistIM_V2\client\ui\widgets\chat_panel.py](D:\AssistIM_V2/client/ui/widgets/chat_panel.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 如果同一 session 里待确认消息的原因/动作并不完全一致，横幅会把它们压成一个统一动作
- UI 展示的是 session 级推断，不是消息级真实待确认原因

建议：

- `security_pending` 横幅至少要和实际 pending message 的 action/reason 保持一致

### F-414：一次 session 级安全确认会直接释放该 session 下全部待确认消息，不区分每条消息原始 `action_id`

状态：已修复（2026-04-14）

现状：

- `ChatInterface._confirm_security_pending_messages(session_id, action_id)` 只执行一次 session 级 action
- 随后直接 `release_session_security_pending_messages(session_id)`
- `MessageManager.release_security_pending_messages()` 会把该 session 下所有 pending message 全部释放
- 不会逐条比对消息自身 `extra.security_pending.action_id`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 当前实现默认“一个 session 里所有待确认消息都共享同一个安全动作”
- 这条假设没有在消息层被正式建模

建议：

- 如果产品要求按 session 统一动作，就应正式建模这个前提
- 如果不是，就不能一次确认后直接释放全部 pending message

### F-415：`SearchManager._build_highlight_payload()` 返回的是截断 snippet，但 `highlight_ranges` 仍是原文坐标

状态：已修复（2026-04-14）

现状：

- `_build_highlight_payload()` 先基于完整内容求出 `ranges`
- 然后只截取首个命中附近的 `matched_text`
- 返回值却是 `(matched_text, ranges)`
- 没有把 ranges 重新映射到 snippet 坐标

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- `SearchResult / ContactSearchResult / GroupSearchResult` 里的 `highlight_ranges` 当前不是对 `matched_text` 有效的坐标
- 这是一份内部自相矛盾的数据 contract

建议：

- 要么对 snippet 重算 ranges
- 要么明确只返回 snippet，不返回失效坐标

### F-416：`SearchResultCard` 完全忽略 manager 提供的 `highlight_ranges`，搜索高亮 contract 在 manager 和 UI 间分裂

状态：已修复（2026-04-14）

现状：

- `SearchManager` 专门生成了：
  - `matched_text`
  - `highlight_ranges`
- 但 `SearchResultCard` 渲染时只调用 `_highlight_html(text, keyword)`
- 不消费 `highlight_ranges`

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)
- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- manager 和 UI 分别维护了一套高亮语义
- manager 里那套 `highlight_ranges` 当前是死数据

建议：

- 搜索高亮应统一只保留一套 contract
- 不要继续让 manager 和 UI 各算一份

### R-063：`search_all()` 的结果列表和 section total 来自独立查询，不是同一个本地快照

状态：已修复（2026-04-14）

现状：

- `SearchManager.search_all()` 会并发跑：
  - `search()`
  - `search_contacts()`
  - `search_groups()`
  - `count_search_message_sessions()`
  - `count_search_contacts()`
  - `count_search_groups()`
- 这些都不是同一个数据库快照里的单次查询

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- 在本地缓存同时被刷新/替换时，UI 可能拿到：
  - 一份时刻 A 的结果列表
  - 一份时刻 B 的 total count
- section total 和实际卡片列表不一定描述同一份数据快照

建议：

- 如果要把 total 和 list 当成一组 authoritative 搜索结果，就应提供 snapshot 语义

### F-417：`AddFriendDialog` 的用户搜索没有 generation guard，晚到旧结果仍可能覆盖当前结果

状态：已修复（2026-04-14）

现状：

- `_trigger_search()` 只会取消上一条 `_search_task`
- `_search_async(keyword)` 在 `await self._controller.search_users(keyword)` 之后
- 不会再检查：
  - 当前输入框是否还是这个关键词
  - 当前完成的 task 是否仍是最新一代搜索
- 然后就直接 `_render_search_results(filtered)`

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 只要旧搜索请求晚到且没有被真正底层取消，旧结果就还能覆盖当前搜索结果
- 这条对话框自己的搜索链并没有像 grouped search 那样做任何 latest-wins 防护

建议：

- `AddFriendDialog` 搜索也要补 request token / generation guard

### F-418：服务端没有校验 direct 文本 envelope 的 `recipient_prekey_id` 是否属于当前目标设备

状态：已修复（2026-04-14）

现状：

- direct text 验证目前只要求：
  - `recipient_prekey_id` 是正整数
  - `recipient_prekey_type` 是 `signed/one_time`
- 但不会去 authoritative device/prekey 存储层确认：
  - 这个 prekey id 是否真实存在
  - 是否属于当前 `recipient_device_id`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- direct 文本 envelope 里的目标 prekey 目前仍是“像个 id 就行”的客户端自报字段
- 服务端没有把它绑定到真实目标设备的 prekey 库

建议：

- direct text 入站时要把 `recipient_prekey_id` 绑定到 `recipient_device_id` 的 authoritative prekey 记录

### F-419：服务端没有校验 direct 附件 envelope 的 `recipient_prekey_id` 是否属于当前目标设备

状态：已修复（2026-04-14）

现状：

- direct attachment 路径对 `recipient_prekey_id` 的检查和文本路径一致
- 只校验字段形状，不校验它是否属于当前目标设备

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- 附件 envelope 也缺少“目标 prekey 属于当前设备”的 authoritative 边界

建议：

- direct attachment envelope 也要对 `recipient_prekey_id -> recipient_device_id` 做 authoritative 绑定

### F-420：服务端没有校验 direct 文本 envelope 的 `recipient_prekey_type` 是否匹配真实 prekey 类型

状态：已修复（2026-04-14）

现状：

- direct text 验证会要求 `recipient_prekey_type` 只能是 `signed` 或 `one_time`
- 但不会去确认当前 `recipient_prekey_id` 在真实设备记录里到底是哪一类 key

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- 客户端可以自报 `signed/one_time` 类型
- 服务端没有把 prekey 的“类别”收口成 authoritative 数据

建议：

- 校验 `recipient_prekey_type` 时应同时校验该 `recipient_prekey_id` 在真实设备库存里的 key class

### F-421：服务端没有校验 direct 附件 envelope 的 `recipient_prekey_type` 是否匹配真实 prekey 类型

状态：已修复（2026-04-14）

现状：

- direct attachment 路径同样只验证 `recipient_prekey_type` 枚举值
- 不验证该类型是否和真实 prekey 记录一致

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- direct 附件链路同样把 prekey 类型停留在客户端自报层

建议：

- direct attachment envelope 也要把 `recipient_prekey_type` 和真实 prekey 类型一起校验

### F-422：服务端没有校验 direct 文本 envelope 的 `sender_identity_key_public` 是否属于当前发送设备

状态：已修复（2026-04-14）

现状：

- direct text envelope 会要求存在 `sender_identity_key_public`
- 但不会校验这个 identity key 是否：
  - 属于 `sender_device_id`
  - 属于当前认证发送者

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- `sender_identity_key_public` 当前仍是客户端自报字段
- 服务端没有把它绑定到真实设备身份谱系

建议：

- direct text 入站时应把 `sender_identity_key_public` 绑定到当前发送设备的 authoritative identity key

### F-423：服务端没有校验 direct 附件 envelope 的 `sender_identity_key_public` 是否属于当前发送设备

状态：已修复（2026-04-14）

现状：

- direct attachment 也要求 `sender_identity_key_public` 存在
- 但不会校验这个公钥是否真的是当前发送设备的 identity key

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- 附件链路同样没有 authoritative sender identity 绑定

建议：

- direct attachment envelope 也要校验 `sender_identity_key_public` 和发送设备的真实绑定关系

### F-424：服务端没有把 direct 文本 envelope 的 `sender_device_id` 绑定到当前认证发送端

状态：已修复（2026-04-14）

现状：

- direct text 验证会要求存在 `sender_device_id`
- 但不会把它和当前认证上下文里的真实发送设备做 authoritative 比对

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- `sender_device_id` 目前仍是 envelope 自报字段
- direct 文本发送者设备身份没有被服务端真正收口

建议：

- direct text 入站时应把 `sender_device_id` 绑定到当前认证发送设备

### F-425：服务端没有把 direct 附件 envelope 的 `sender_device_id` 绑定到当前认证发送端

状态：已修复（2026-04-14）

现状：

- direct attachment 路径同样只要求有 `sender_device_id`
- 不校验它是否等于当前真实发送设备

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- direct 附件链路的发送设备身份也没有 authoritative 边界

建议：

- direct attachment envelope 也要把 `sender_device_id` 绑定到当前认证发送设备

### F-426：服务端没有校验 group 文本 fanout item 的 `sender_device_id` 是否与 top-level envelope 一致

状态：已修复（2026-04-14）

现状：

- group text envelope 会在 top-level 要求 `sender_device_id`
- fanout item 里也单独要求 `sender_device_id`
- 但服务端不会比对两者是否一致

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- group text fanout item 仍可携带和外层 envelope 不同的发送设备 id
- 当前协议里“谁发送了 fanout 包”的语义并没有真正收口

建议：

- group text fanout item 的 `sender_device_id` 应强制等于 top-level `sender_device_id`

### F-427：服务端没有校验 group 附件 fanout item 的 `sender_device_id` 是否与 top-level envelope 一致

状态：已修复（2026-04-14）

现状：

- group attachment 路径也同时要求：
  - top-level `sender_device_id`
  - fanout item `sender_device_id`
- 但不比较两者是否一致

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- group attachment fanout 同样允许外层和逐设备项出现两套发送设备标识

建议：

- group attachment fanout item 的 `sender_device_id` 也要强制和外层 envelope 保持一致

### F-428：服务端没有校验 group 文本 fanout item 的 `sender_key_id` 是否与 top-level envelope 一致

状态：已修复（2026-04-14）

现状：

- group text envelope 在 top-level 要求 `sender_key_id`
- fanout item 里也要求 `sender_key_id`
- 服务端只校验字段存在，不比对两者是否一致

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 同一条 group 文本 envelope 里可以并存两套 sender-key 标识
- 这会继续削弱 sender-key 谱系的 authoritative 约束

建议：

- group text fanout item 的 `sender_key_id` 应和 top-level `sender_key_id` 保持严格一致

### F-429：服务端没有校验 group 附件 fanout item 的 `sender_key_id` 是否与 top-level envelope 一致

状态：已修复（2026-04-14）

现状：

- group attachment envelope 也同时要求外层和 fanout item 提供 `sender_key_id`
- 但不会校验逐设备项是否和外层 sender-key 一致

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- group attachment 逐设备 fanout 也还允许出现两套 sender-key 标识

建议：

- group attachment fanout item 的 `sender_key_id` 也要强制和 top-level 保持一致

### F-430：`security_pending` 的释放/丢弃只会扫描会话最近 200 条本地消息

状态：已修复（2026-04-14）

修复说明：

- [database.py](/D:/AssistIM_V2/client/storage/database.py) 新增 `get_security_pending_messages(session_id)`，直接按 DB 中 `AWAITING_SECURITY_CONFIRMATION` 状态查询整个 session 的本地队列。
- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 release/discard 已改为使用该 DB authoritative 队列，不再依赖 `get_messages(limit=200)`。
- 队列按 `timestamp ASC, rowid ASC` 释放，已补 FIFO 回归测试。

现状：

- `MessageManager._collect_security_pending_messages(session_id, limit=200)` 只会：
  - `get_messages(session_id, limit=200)`
  - 再从这 200 条里过滤 `AWAITING_SECURITY_CONFIRMATION`
- `release_security_pending_messages()` 和 `discard_security_pending_messages()` 都依赖这条扫描结果

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 只要某个 session 里更早的待确认消息已经滑出最近 200 条窗口，它们就不会被 release/discard 命中
- 当前 `security_pending` 不是 session 全量状态，而只是“最近一页消息里的局部状态”

建议：

- `security_pending` 的释放/丢弃必须基于 session 级 authoritative 待确认集合，而不是固定页大小的消息扫描

### F-431：`AddFriendDialog` 搜索失败时不会清空旧结果列表

状态：已修复（2026-04-14）

现状：

- `_search_async(keyword)` 失败时只会：
  - 更新 summary 为 `Search failed.`
  - 弹 InfoBar
- 不会清空上一轮已经渲染出来的结果卡片

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户会同时看到“搜索失败”的提示和上一轮旧关键词的结果列表
- 失败态和旧结果态被混在一起，UI 没有 authoritative 收口

建议：

- 搜索失败时要么清空旧结果，要么明确把旧结果标成 stale，不能继续当当前搜索结果展示

### F-432：`AddFriendDialog` 输入空关键词时不会清空旧结果列表

状态：已修复（2026-04-14）

现状：

- `_trigger_search()` 在关键词为空时只会更新 summary 文案
- 不会清空上一轮搜索结果

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 对话框可以在“请输入关键词”的空查询状态下继续显示上一轮结果
- 当前 UI 没有把“无查询”收口成真正空结果状态

建议：

- 空关键词应显式清空结果列表和当前搜索状态

### F-433：通话 signaling 仍然依赖底层 direct 会话存在且仍是双人成员，通话中途会话漂移会把控制面打断

状态：已修复（2026-04-14）

现状：

- `CallService._require_participant_call()` 在处理 `reject/hangup/offer/answer/ice` 时
- 会继续调用 `_require_private_session(call.session_id, user_id)`
- 后者要求：
  - session 仍然存在
  - 用户仍然是成员
  - session 仍是 private 且非 AI
  - 成员数仍然恰好等于 2

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)

影响：

- 通话建立后，如果底层 direct session 被删除、成员关系漂移，后续 signaling 会直接 403/404/409
- registry 里的 active call 可能因此停在半残状态，busy/terminal 清理只能依赖旁路收口

建议：

- 通话控制面应主要绑定 call 自身的 authoritative state
- 不应在每条 signaling 命令上继续强依赖“底层私聊此刻仍完全未变化”

### F-434：`CallWindow` 在麦克风恢复可用时会覆盖用户原本的静音选择

状态：已修复（2026-04-14）

现状：

- `_on_microphone_available_changed(True)` 会强制：
  - 图标改为 `MICROPHONE`
  - 文案改为 `Mic on`
  - 按钮 `checked=False`
- 不会恢复用户在设备暂时不可用前的原始 mute 选择

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 设备 availability 变化会直接覆写用户本地静音偏好
- “设备可用性”与“用户是否想开麦”两层状态被混成了一层

建议：

- 设备恢复后应恢复先前用户 mute 偏好，而不是直接强制回到 `Mic on`

### F-435：`CallWindow` 在摄像头恢复可用时会覆盖用户原本的关摄像头选择

状态：已修复（2026-04-14）

现状：

- `_on_camera_available_changed(True)` 会强制：
  - 图标改为 `CAMERA`
  - 文案改为 `Camera on`
  - 按钮 `checked=True`
- 不会保留用户之前主动关摄像头的本地选择

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 设备 availability 恢复会直接把用户的 camera-off 偏好抹掉
- “设备能不能用”和“用户要不要开视频”被错误耦合

建议：

- 摄像头恢复后应恢复用户原始视频偏好，而不是自动切回 `Camera on`

### F-436：`security_pending` 的 session 级确认可能显示成功，但更早待确认消息会继续残留在会话里

状态：已修复（2026-04-14）

修复说明：

- session 级 release/discard 现在处理 DB 中该 session 的全部 `AWAITING_SECURITY_CONFIRMATION` 消息，不再受当前页或最近 200 条窗口限制。
- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 同时加了 session 级 in-progress guard，避免同一会话并发消费 pending 队列。

现状：

- 当前聊天页会按 session 级动作执行“确认/丢弃”
- 但底层只扫描最近 200 条消息
- 如果更早的待确认消息已经滑出窗口，本次 session 级动作不会覆盖到它们

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- UI 会给出一次 session 级确认已经完成的感觉
- 但该 session 下更早的 pending message 其实仍可能残留，session 级 contract 失真

建议：

- session 级安全确认必须对该 session 的全部 pending message 生效，或者改成显式“仅处理当前页消息”

### F-437：`GroupMemberManagementDialog` 初始加载失败后没有正式重试入口

状态：已修复（2026-04-14）

现状：

- 群成员管理窗口初始加载失败时只会显示错误态
- 当前对话框没有正式的页内 retry 动作
- 用户想恢复这次操作，只能关掉窗口重新打开

证据：

- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)

影响：

- 群成员管理页的错误恢复能力过弱
- 一次瞬时失败就会把整个弹窗打成一次性死状态

建议：

- 群成员管理窗口应提供正式 retry 路径，而不是要求用户整窗重开

### F-438：`recover_session_messages()` 的恢复计数只统计本地重解密消息，却把远端回拉消息一起塞进 `message_ids`

状态：已修复（2026-04-14）

现状：

- `recover_session_messages()` 返回结果里的：
  - `updated` 只等于 `len(updated_messages)`
  - `MessageEvent.RECOVERED.count` 也只等于 `len(updated_messages)`
- 但同一次结果里的 `message_ids` 会同时包含：
  - 本地缓存里真正被重新解密的消息
  - 远端分页回拉得到的消息 id

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)

影响：

- 同一个恢复结果里，“恢复了多少条”和“涉及哪些消息”不是同一个口径
- 上层如果按 `count` 理解本次恢复范围，会系统性低估远端回拉带来的实际变更

建议：

- 把“本地重解密数量”和“远端补拉数量”拆成正式字段
- 不要继续让 `count`、`updated`、`message_ids` 三套口径混在一起

### F-439：`recover_session_messages()` 只会扫描会话最近一页本地消息，旧的加密历史不会参与恢复

状态：已修复（2026-04-14）

现状：

- `recover_session_messages(session_id, limit=500, ...)` 本地恢复阶段只调用：
  - `get_messages(session_id, limit=effective_limit)`
- 默认只会扫描最近 `500` 条本地消息

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client\storage/database.py)

影响：

- 更早的本地加密历史即使在设备恢复后已经可解，也不会被这条恢复链覆盖
- 当前“会话恢复”实际上只是“最近一页缓存恢复”

建议：

- 会话级恢复应支持真正遍历该 session 的本地加密历史
- 或至少把“只恢复最近 N 条”明确建模成受限模式，而不是默认会话恢复语义

### F-440：`recover_session_messages()` 的远端恢复被默认 `remote_pages=3` 硬截断

状态：已修复（2026-04-14）

现状：

- 远端恢复阶段默认最多只会循环 `3` 页
- 每页大小又复用本地 `limit`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)

影响：

- 深历史会话在恢复时会被静默截断
- 当前“远端恢复”不是开放式补偿，而是固定窗口回拉

建议：

- 远端恢复要么支持显式继续翻页
- 要么把“恢复窗口已截断”变成正式结果字段，不要静默成功

### F-441：`recover_session_messages()` 的 `remote` 恢复统计会把整页远端消息都算进去，而不区分是否真的被恢复

状态：已修复（2026-04-14）

现状：

- 远端恢复阶段会对 `_fetch_remote_messages()` 回来的每条消息都执行 `_accumulate_recovery_stats()`
- 这一步不要求该消息：
  - 原本是不可解的
  - 本次真的发生了解密状态变化

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)

影响：

- `recovery_stats.remote` 实际更接近“远端回拉了什么类型的消息”
- 不是“本次真正恢复了哪些类型的消息”

建议：

- 远端恢复统计要区分：
  - fetched
  - changed
  - recovered
- 不要继续把“回拉量”伪装成“恢复量”

### F-442：`recover_session_messages()` 即使远端恢复阶段失败，也仍会照常发 `RECOVERED` 事件

状态：已修复（2026-04-14）

现状：

- 远端恢复阶段异常只会：
  - 记录 `remote_error`
  - 打 warning 日志
- 最后仍然无条件 `emit(MessageEvent.RECOVERED, ...)`
- 且顶层事件字段里没有单独暴露失败态，只是把 `remote_error` 藏进嵌套 `result`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)

影响：

- 上层更容易把“部分失败的恢复”误判成完整成功
- 当前恢复链没有正式的 partial-failure contract

建议：

- 为恢复流程补正式的部分成功/部分失败状态
- `RECOVERED` 不应继续默认代表整条恢复链已成功完成

### F-443：`_process_history_messages()` 缺少逐消息隔离，一条坏消息会打断整批同步

状态：已修复（2026-04-14）

现状：

- `_process_history_messages()` 会对每条新消息依次执行：
  - `_normalize_loaded_message(...)`
  - `_decrypt_message_for_display(...)`
- 这条循环没有逐消息 `try/except`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)

影响：

- 只要一条历史消息在 normalize/decrypt 路径抛异常，后续消息就都不会继续处理
- 同一次 `history_messages` 批次会被单条坏消息整体打穿

建议：

- `history_messages` 回放应做逐消息隔离
- 至少要允许坏消息被单条跳过，而不是让整批同步一起失败

### F-444：`_fetch_remote_messages()` 缺少逐消息隔离，一条坏远端消息会打断整页历史回拉

状态：已修复（2026-04-14）

现状：

- `_fetch_remote_messages()` 对每条远端 payload 依次执行：
  - `get_message(message_id)`
  - `_normalize_loaded_message(...)`
  - `_decrypt_message_for_display(...)`
- 整个页循环没有逐条异常隔离

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)

影响：

- 一条异常 payload 就会让整页远端历史回拉失败
- 本地 `get_messages()` 也会把这类页级失败整体吞成“远端回拉失败”

建议：

- 远端历史回拉至少要做到逐消息 skip + 逐页容错
- 不要继续让单条坏 payload 把整页 backfill 打断

### F-445：`_fetch_remote_messages()` 只有整页循环结束后才落库，尾部一条异常会让前面已成功处理的消息全部丢失

状态：已修复（2026-04-14）

现状：

- `_fetch_remote_messages()` 先把整页消息积到 `remote_messages`
- 只有整个循环成功结束后才：
  - `save_messages_batch(remote_messages)`
  - 调度媒体预取

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client\managers\message_manager.py)

影响：

- 即使同一页前半段消息已经成功 normalize/decrypt
- 只要尾部一条消息抛异常，这一页前面成功处理的结果也完全不会落库

建议：

- 至少要把页内成功结果做增量持久化或 chunk 落库
- 不要继续把“单条坏消息”放大成“整页成功结果全丢”

### F-446：服务端 group 文本 envelope 甚至不要求客户端显式提供 `member_version`

状态：已修复（2026-04-14）

现状：

- `_validate_group_text_envelope()` 只要求：
  - `session_id`
  - `sender_device_id`
  - `sender_key_id`
  - `content_ciphertext`
  - `nonce`
  - `fanout`
- 并没有把 `member_version` 列为必填字段

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2\server\app\services\message_service.py)

影响：

- 当前 group text 入站不只是“不会校验 member_version 是否正确”
- 而是连“客户端有没有显式提交 member_version”都不要求

建议：

- group text envelope 至少应把 `member_version` 升级为正式必填字段
- 再在此基础上执行 authoritative 成员版本校验

### F-447：服务端 group 附件 envelope 也不要求客户端显式提供 `member_version`

状态：已修复（2026-04-14）

现状：

- `_validate_group_attachment_envelope()` 的必填字段同样不包含 `member_version`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2\server\app\services\message_service.py)

影响：

- group attachment 路径也还停留在“member_version 可有可无”的状态
- 后续任何服务端 authoritative 成员版本约束都缺正式入口字段

建议：

- group attachment envelope 也要先把 `member_version` 收成正式必填字段
- 再谈和当前群成员版本的绑定校验

### F-448：`CallManager._merge_state()` 会把别的 `call_id` 的 payload 和当前通话残留字段拼成一条假状态

状态：已修复（2026-04-14）

现状：

- `_merge_state()` 先按 payload 新建 `ActiveCallState`
- 但只要 payload 缺字段，就会继续从当前 `_active_call` 补：
  - `initiator_id`
  - `recipient_id`
  - `media_type`
- 这一步并不要求 `payload.call_id == current_state.call_id`

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2\client/managers/call_manager.py)

影响：

- 晚到的另一通电话 payload 只要字段不全，就可能继承当前通话的参与者或媒体类型
- 本地单槽 call state 会被拼出不存在的混合通话状态

建议：

- `merge_state` 只能在相同 `call_id` 内做字段继承
- 跨 call 的 payload 必须独立校验，不要继续借当前 active call 补字段

### F-449：外呼 unanswered timeout 到点后只会尝试发送 `hangup(timeout)`，本地没有兜底进入 timeout 终态

状态：已修复（2026-04-14）

现状：

- `_run_unanswered_timeout()` 到点后只执行：
  - `await self.hangup_call(call_id, reason="timeout")`
- 不会在本地直接把 call state 收口成 timeout/ended

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2\client/managers/call_manager.py)

影响：

- 只要这次 hangup 发送失败，或者终态广播没回来
- 本地外呼就不会正式进入 timeout 终态

建议：

- unanswered timeout 应先有本地 authoritative 终态收口
- 再把 hangup(timeout) 当成对外同步动作，而不是反过来依赖它来完成本地收口

### F-450：群搜索命中 `member_search_text` 时会把真实命中的成员信息退化成泛化占位文案

状态：已修复（2026-04-14）

现状：

- `_highlight_group_match()` 在：
  - 群名没命中
  - `member_previews` 没命中
  - 但 `member_search_text` 命中时
- 会把 `matched_text` 固定写成：
  - `Group member match`

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2\client/managers/search_manager.py)

影响：

- 用户能搜到“某个群里某个成员命中了关键词”
- 但结果卡片不再显示到底是哪位成员命中的

建议：

- 群成员命中结果应返回真实命中的成员预览文本
- 不要在最后一层 render 前退化成泛化占位

### F-451：群成员搜索 fallback 的高亮元数据是按占位文案生成的，不是按真实命中文本生成的

状态：已修复（2026-04-14）

现状：

- `member_search_text` 命中 fallback 分支里
- 代码会对占位文案 `Group member match` 再跑一次 `_build_highlight_payload()`
- 这不是对真实命中文本生成高亮信息

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2\client/managers/search_manager.py)

影响：

- 群成员 fallback 命中时，UI 侧收到的 `matched_text/highlight_ranges` 进一步失真
- 这条结果即使显示出来，也很可能没有任何有意义的高亮

建议：

- 高亮元数据必须绑定真实命中文本生成
- 不要继续把 placeholder 当成高亮源文本

### F-452：全局搜索进入 loading 态时不会清空上一轮结果快照

状态：已修复（2026-04-14）

现状：

- `GlobalSearchResultsPanel.set_loading()` 只会：
  - 更新 `_keyword`
  - 显示“搜索中...”
  - `hide()` 掉 `scroll_area`
- 不会清空：
  - `_results`
  - 已渲染的结果布局
  - 当前展开 section 状态

证据：

- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2\client/ui/widgets/global_search_panel.py)

影响：

- loading 态底下仍保留着上一轮完整结果快照
- 当前面板并不是“空白等待新结果”，而是“隐藏着一份旧结果”

建议：

- loading 态要么清空上一轮结果
- 要么显式把旧结果标记为 stale，避免继续当当前查询快照保存

### F-453：全局搜索 overlay 关闭时不会重置内部结果状态，重开前一直保留旧关键词和旧结果

状态：已修复（2026-04-14）

现状：

- `GlobalSearchPopupOverlay.close_overlay()` 只会：
  - stop timer
  - hide overlay
  - emit closed
- 不会调用：
  - `results_panel.clear_results()`

证据：

- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2\client/ui/widgets/global_search_panel.py)

影响：

- overlay 实例在关闭后仍保留上一轮关键词和结果快照
- 当前 reopen correctness 依赖外部调用方每次都记得手工清状态

建议：

- overlay close 应有明确的 state reset contract
- 至少不要继续把“已关闭 overlay”保留成一份可直接复活的旧搜索快照

### F-454：聊天页确认 `security_pending` 后，即使实际释放了 0 条消息，也会弹成功提示

状态：已修复（2026-04-14）

修复说明：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 现在把 `released_count <= 0` 建成独立 no-op 分支，提示没有待确认队列，而不是继续弹发送成功。

现状：

- `_confirm_security_pending_messages()` 中：
  - 只要 `failed_count == 0`
  - 就直接弹 success InfoBar
- 即使 `released_count == 0` 也是如此

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client/ui/windows/chat_interface.py)

影响：

- 在 banner stale、最近 200 条窗口漏扫等场景下
- 用户可能会得到“queued messages are now sending”的成功提示，但实际上一条都没释放

建议：

- `released=0` 应单独建模成 no-op 或 stale-state 提示
- 不要继续和真正释放成功共用 success 分支

### F-455：聊天页丢弃 `security_pending` 时，如果底层实际删除了 0 条消息，会直接静默返回

状态：已修复（2026-04-14）

修复说明：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 现在会在 `removed_count <= 0` 时给出 no-op InfoBar，用户能区分“没有待处理项”和“已丢弃成功”。

现状：

- `_discard_security_pending_messages()` 中：
  - `removed_count <= 0` 时直接 `return`
- 不给用户任何反馈

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2\client/ui/windows/chat_interface.py)

影响：

- 用户已经点击“Discard”，但 UI 不会说明：
  - 没有命中待确认消息
  - 还是状态已经过期

建议：

- discard no-op 也应给出正式反馈
- 至少要告诉用户这是 stale-state 还是没有待处理项

### F-456：`AiortcVoiceEngine` 会把“有无输出设备”直接当成默认扬声器开关

状态：已修复（2026-04-14）

现状：

- 引擎初始化时直接：
  - `self._speaker_enabled = self._remote_audio_output.is_available()`
- 默认扬声器开关不是来自用户偏好，而是来自“当前有没有音频输出设备”

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2\client/call/aiortc_voice_engine.py)

影响：

- 每次新建通话引擎时，speaker enabled 初始值都会被设备可用性重新决定
- “用户想不想外放”和“系统此刻有没有输出设备”被建模成同一个状态

建议：

- speaker enabled 应作为独立用户偏好建模
- 设备 availability 只能决定是否可执行，不应决定默认开关值

### F-457：`CallWindow` 的扬声器按钮初始态也直接镜像“是否有输出设备”，而不是当前真实通话路由偏好

状态：已修复（2026-04-14）

现状：

- 构造函数里：
  - `speaker_control.checked = self._has_audio_output`
  - label 也是 `Speaker on / No speaker`

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2\client/ui/windows/call_window.py)

影响：

- UI 初始态会把“当前设备可用性”直接显示成“用户已经开启外放”
- 这和真正的音频路由偏好、后端引擎状态不是同一层语义

建议：

- 扬声器按钮初始态应绑定真实 speaker preference / route state
- 不要再用 `has_audio_output` 直接伪装成“Speaker on”

### F-458：`recover_session_messages()` 的本地恢复阶段没有逐消息隔离，一条坏消息会打断整批缓存恢复

状态：已修复（2026-04-14）

现状：

- `recover_session_messages()` 会先取最近一页本地消息
- 然后逐条 `await self._decrypt_message_for_display(candidate)`
- 这段循环没有单条 `try/except`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

影响：

- 只要最近一页里有一条异常消息解密抛错
- 整个本地恢复阶段就会被中断
- 前面本来已经可以恢复成功的消息也不会落库

建议：

- 本地恢复阶段要补逐消息隔离
- 单条失败只能记录 diagnostics，不能打断整批 cached recovery

### F-459：`get_messages()` 会把远端历史回拉失败静默降级成“只返回本地缓存”

状态：已修复（2026-04-14）

现状：

- `get_messages()` 触发 `_fetch_remote_messages()` 失败时
- 只会 `logger.warning(...)`
- 然后直接返回最开始读出来的本地 `messages`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

影响：

- 调用方拿不到“这页其实已经 stale / 远端回拉失败”的任何正式信号
- UI 会把旧缓存继续当成 fresh 历史页展示

建议：

- `get_messages()` 至少要把 stale/error 状态显式返回给上层
- 不要继续把“远端回拉失败”和“本地历史就是最新”混成同一个返回 contract

### R-064：`get_messages()` 首屏历史页即使本地已经满页，也仍然会固定再打一轮远端回拉

状态：已修复（2026-04-14）

现状：

- `should_fetch_remote = before_timestamp is None or len(messages) < limit`
- 这意味着首屏页 `before_timestamp is None` 时
- 不管本地缓存是不是已经有完整一页，都会再触发 `_fetch_remote_messages()`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

影响：

- 会话首屏打开会稳定多一次远端历史请求
- 本地已有完整缓存时，这轮请求主要只是验证“有没有更新”，但当前接口没有更轻量的 freshness contract

建议：

- 把“首屏要不要回拉远端”从固定策略改成显式 freshness 策略
- 不要再让 `before_timestamp is None` 直接等于“必须打远端”

### R-065：`get_messages()` 用“本地页是否满页”充当 freshness 判断，满页但 stale 的历史页永远不会再回拉

状态：已修复（2026-04-14）

现状：

- 对翻页场景，只有 `len(messages) < limit` 才会继续 `_fetch_remote_messages()`
- 也就是说只要本地这页恰好有 `limit` 条
- 当前实现就默认这页已经 fresh

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

影响：

- “缓存页已满”被错误当成“缓存页已新鲜”
- 历史页如果因为 earlier gap、局部删除、旧数据漂移而 stale，上层也不会再补远端

建议：

- 历史翻页不能只靠页长判断 freshness
- 需要单独的 cursor / watermark / authoritative window contract

### F-460：group E2EE 的 `member_version` 在缺失权威值时，会退化成本地成员列表哈希

状态：已修复（2026-04-14）

现状：

- `_resolve_group_member_version()` 先读 `session.extra.group_member_version`
- 如果没有，就对本地 `member_ids` 排序后做 `sha256`
- 再把前 16 位十六进制转成整数作为 `member_version`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

影响：

- `member_version` 本应是权威群成员版本
- 现在却会被本地缓存结构临时伪造出来

建议：

- `member_version` 必须来自服务端权威值
- 缺失时应显式失败或先补 authoritative session/group payload，不应本地伪造

### F-461：本地群成员缓存漂移会触发无权威依据的 sender-key 轮换

状态：已修复（2026-04-14）

现状：

- `prepare_group_session_fanout()` 会在 `current_local_sender_key.member_version != normalized_member_version` 时轮换 sender key
- 而 `normalized_member_version` 又可能来自 `F-460` 那套本地哈希

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)
- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 只要本地 members cache 变化、缺字段或顺序漂移
- 客户端就可能在没有真实群成员变更的情况下轮换 sender key

建议：

- sender-key rotation 必须绑定权威群成员版本
- 不要继续让本地 cache drift 直接驱动密钥轮换

### F-462：group E2EE 的接收方集合完全来自本地 session 缓存，不来自权威群成员关系

状态：已修复（2026-04-14）

现状：

- `_resolve_group_member_ids()` 只读：
  - `session.extra["members"]`
  - `session.participant_ids`
- 然后直接拿这份本地列表驱动 recipient bundle 拉取和 fanout

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

影响：

- 当前发送链本质上把“本地会话缓存里的成员列表”当成 authoritative group membership
- 只要本地缓存过时，E2EE 发送对象就会一起漂移

建议：

- 群聊 E2EE fanout 必须绑定权威群成员快照
- 不能继续只靠本地 session cache 推导接收方集合

### F-463：本地群成员缓存为空或残缺时，group 文本加密会直接硬失败

状态：已修复（2026-04-14）

现状：

- group 文本发送前会先：
  - `member_ids = _resolve_group_member_ids(...)`
- 如果结果为空，直接抛：
  - `group session members could not be resolved for E2EE`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

影响：

- 这类失败不一定代表真实群成员不存在
- 很多时候只是本地 session cache 没跟上

建议：

- 发送前要么先补权威群成员
- 要么把“本地成员缓存缺失”建模成可恢复状态，而不是直接把发送打成业务失败

### F-464：本地群成员缓存为空或残缺时，group 附件加密也会直接硬失败

状态：已修复（2026-04-14）

现状：

- `prepare_attachment_upload()` 的 group 路径
- 同样先走 `_resolve_group_member_ids(...)`
- 为空时直接抛：
  - `group session members could not be resolved for attachment encryption`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

影响：

- 群附件发送会和文本一样被本地 stale membership 直接卡死
- 这不是权威群状态失败，而是 cache failure

建议：

- group attachment E2EE 也要先收口 authoritative membership
- 不要继续让本地会话缓存直接决定“能不能发附件”

### F-465：本地群成员缓存不完整时，group 文本 fanout 会静默遗漏合法接收方

状态：已修复（2026-04-14）

现状：

- `_resolve_group_member_ids()` 先裁出本地 member_ids
- `_resolve_group_recipient_bundles()` 只对这批 member_ids 拉 bundle
- 之后 `encrypt_text_for_group_session()` 就按这批 bundle 生成 fanout

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)
- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 只要本地 members cache 漏了合法成员
- group 文本就可能在没有报错的情况下直接少发一部分人

建议：

- fanout 接收方集合必须来自权威群成员快照
- 至少要在发送前校验“本地成员集是否完整/最新”

### F-466：本地群成员缓存不完整时，group 附件 fanout 也会静默遗漏合法接收方

状态：已修复（2026-04-14）

现状：

- group 附件发送路径复用了同一套：
  - `_resolve_group_member_ids()`
  - `_resolve_group_recipient_bundles()`
  - `encrypt_attachment_for_group_session()`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)
- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 群附件和群文本一样会在本地静默少发合法接收方
- 只是问题更隐蔽，因为媒体链本身还有上传/预取噪音

建议：

- group attachment fanout 也要挂到 authoritative membership 上
- 不要继续沿用“本地 session cache -> recipient bundles -> fanout”这条旁路

### R-066：group E2EE 每次发送都会按成员串行拉 prekey bundle，群越大发送越慢

状态：已修复（2026-04-14）

现状：

- `_resolve_group_recipient_bundles()` 里对每个 member_id 都是：
  - `await fetch_prekey_bundle(member_id)`
- 没有批量接口，也没有并发控制或短期缓存

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

影响：

- 群聊 E2EE 发送会随成员数线性增加网络 RTT
- 文本和附件都会走这条串行链路

建议：

- 给 recipient bundle 拉取补批量接口或发送期短缓存
- 至少不要在群成员循环里串行 await 每个用户的 bundle 请求

### F-467：`apply_group_session_fanout()` 会信任解密后 payload 里的 `session_id`，而不是强绑定外层 envelope 的 `session_id`

状态：已修复（2026-04-14）

现状：

- `normalized_session_id = payload.get("session_id") or normalized.get("session_id")`
- 也就是说只要内层 payload 带了 `session_id`
- 它就会覆盖外层 fanout envelope 的 `session_id`

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 接收端安装 inbound sender key 时
- 并没有把“内层解密 payload”和“外层 fanout envelope”绑定成同一个会话

建议：

- 接收端必须强校验 inner payload `session_id == outer envelope session_id`
- 不一致时应拒绝安装 inbound sender key

### F-468：`apply_group_session_fanout()` 会信任内层 payload 的 `owner_device_id`，而不是强绑定外层 `sender_device_id`

状态：已修复（2026-04-14）

现状：

- `owner_device_id = payload.get("owner_device_id") or normalized.get("sender_device_id")`
- 内层 payload 只要带了 `owner_device_id`
- 就会覆盖外层 sender device

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 接收端安装 sender key 时
- 没有把“这个 key 属于哪台发送设备”正式绑定到外层 envelope

建议：

- inner payload `owner_device_id` 必须和 outer `sender_device_id` 严格一致
- 不应继续允许内层字段覆盖外层 transport 身份

### F-469：`apply_group_session_fanout()` 会信任内层 payload 的 `sender_key_id`，而不是强绑定外层 `sender_key_id`

状态：已修复（2026-04-14）

现状：

- 存储 inbound key 时使用：
  - `payload.get("sender_key_id") or normalized.get("sender_key_id")`
- 内层 `sender_key_id` 优先级更高

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 接收端没有正式校验
- “消息外层声明的 sender_key_id”和“实际安装到本地状态里的 sender_key_id”是不是同一个 key

建议：

- inbound fanout 安装时应强校验 inner / outer `sender_key_id` 一致
- 不一致时直接拒绝

### F-470：`apply_group_session_fanout()` 会信任内层 payload 的 `member_version`，而不是强绑定外层 `member_version`

状态：已修复（2026-04-14）

现状：

- 存储 inbound key 时使用：
  - `int(payload.get("member_version") or normalized.get("member_version") or 0)`
- 内层 `member_version` 优先级高于外层

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 接收端记录的 sender-key 成员版本
- 并没有和外层 fanout envelope 的版本值正式绑定

建议：

- inner / outer `member_version` 应强制一致
- 不一致时不能继续把这把 key 装进本地 group session state

### F-471：group fanout payload 缺失 `owner_user_id` 时，接收端会把 inbound sender key 错记到本地接收者自己名下

状态：已修复（2026-04-14）

现状：

- `owner_user_id` 的回退逻辑是：
  - `payload.get("owner_user_id") or normalized.get("recipient_user_id")`
- 而 outer `recipient_user_id` 对当前接收端来说正是本地用户自己

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 一旦 fanout payload 没带 `owner_user_id`
- 本地就会把“远端发来的 inbound sender key”错误归属到自己用户名下

建议：

- `owner_user_id` 不能再回退到 `recipient_user_id`
- 缺失时应直接拒绝安装 inbound sender key

### F-472：inbound sender key 只按 `owner_device_id` 存一份，新 fanout 会覆盖同设备旧 key

状态：已修复（2026-04-14）

现状：

- `apply_group_session_fanout()` 直接：
  - `inbound_sender_keys[owner_device_id] = {...}`
- 当前结构没有 retired inbound sender keys

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 同一远端设备只要轮换过 sender key
- 新 fanout 就会把旧 inbound key 直接覆盖掉
- 旧消息如果还依赖旧 key，本地运行态就只能靠别的旁路状态兜底

建议：

- inbound sender key 也要有按 `sender_key_id` 保留的历史记录
- 不要继续把整个远端设备只压成“当前一把 key”

### F-473：`reconcile_group_session_state()` 只有在 `member_user_ids` 非空时才会清掉已移除成员的 inbound sender key

状态：已修复（2026-04-14）

现状：

- `allowed_user_ids` 为空时
- reconcile 不会进入 `filtered_inbound_sender_keys` 那段 pruning 逻辑
- 即使 `member_version` 已经变了也一样

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2\client/managers/session_manager.py)

影响：

- 如果当前 session payload 只有版本号、没有完整 members 列表
- 已被移除成员的 inbound sender key 仍会继续残留在本地 group state

建议：

- reconcile 不能把“没有 member_user_ids”直接等同于“不要 prune”
- 需要明确的权威成员快照或更保守的失效策略

### F-474：group 附件 decryption diagnostics 在“只有 fanout、还没装 sender key”时会直接报 `READY`

状态：已修复（2026-04-14）

现状：

- `_describe_group_text_decryption_state()` 在这种场景下会返回：
  - `MISSING_GROUP_SENDER_KEY`
- 但 `_describe_group_attachment_decryption_state()` 只要看到了 matching fanout 且本地有对应 private key
- 就直接返回：
  - `READY`
  - `can_decrypt = True`

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 文本和附件对同一“sender key 还没安装”的状态给出相反 diagnostics
- 附件侧 UI 会被误导成“已经可解密”

建议：

- group attachment diagnostics 也应把“只有 fanout、sender key 尚未装入”建模成 `MISSING_GROUP_SENDER_KEY`
- 不要提前宣称 `READY`

### F-475：group 文本解密在只缺 sender key 时，会一边读消息一边改写持久化 group key 状态

状态：已修复（2026-04-14）

现状：

- `decrypt_group_text_content()` 在本地缺 sender key 时
- 会直接找 `matching_fanout`
- 然后调用 `apply_group_session_fanout(...)`

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 纯“读消息 / 渲染消息”路径带了持久化 side effect
- 只要打开一条消息，就可能把新的 inbound sender key 装进本地状态

建议：

- 解密读取路径和 key-install 路径应拆开
- 不要继续让 display path 隐式改写 group session state

### F-476：group 附件 metadata 解密也会在读取过程中隐式安装 fanout/sender key

状态：已修复（2026-04-14）

现状：

- `_decrypt_group_attachment_metadata()` 在 sender key 缺失时
- 同样会先选 `matching_fanout`
- 然后直接 `apply_group_session_fanout(...)`

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 读附件元数据也不再是纯读取
- 点击一条加密附件就可能永久改变本地 E2EE group state

建议：

- 附件 metadata 的解密路径也应去 side effect 化
- fanout 安装应改成显式、可观测、可回滚的状态迁移

### F-477：group 文本解密第一次找 sender key 时完全不带 `sender_key_id`

状态：已修复（2026-04-14）

现状：

- `decrypt_group_text_content()` 先调用：
  - `get_group_sender_key_record(session_id, owner_device_id=sender_device_id)`
- 没把当前消息 envelope 里的 `sender_key_id` 带进去

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 只要同一远端设备轮换过 sender key
- 当前消息第一次取 key 时就可能拿到“该设备当前某把 key”，而不是这条消息真正声明的那把 key

建议：

- group 文本解密取 key 时必须同时绑定 `owner_device_id + sender_key_id`
- 不能只按设备找“某把现有 key”

### F-478：group 文本解密在安装 fanout 之后的第二次取 key，仍然不带 `sender_key_id`

状态：已修复（2026-04-14）

现状：

- `apply_group_session_fanout()` 完成后
- `decrypt_group_text_content()` 再次调用：
  - `get_group_sender_key_record(session_id, owner_device_id=sender_device_id)`
- 第二次 lookup 仍然没有 `sender_key_id`

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 即使刚刚安装好了这条消息对应的 fanout
- 第二次取 key 仍可能因为同设备已有别的 key 而拿错

建议：

- 第二次 lookup 也必须严格带上 `sender_key_id`
- 不要继续把 “owner device 命中” 当成足够条件

### F-479：`apply_group_session_fanout()` 不要求解密后 payload 一定带 `sender_key`

状态：已修复（2026-04-14）

现状：

- `apply_group_session_fanout()` 只强校验：
  - `session_id`
  - `owner_device_id`
- 然后就会把：
  - `payload.get("sender_key")`
- 原样写进 `inbound_sender_keys`

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 接收端可以把一条没有真正 sender key 材料的 fanout 安装进本地状态
- 后续解密时才在更晚阶段爆出“group sender key is unavailable”

建议：

- 安装 inbound sender key 前必须把 `sender_key` 收成必填
- 不完整 fanout 不应进入本地 group state

### F-480：`apply_group_session_fanout()` 也不要求解密后 payload 一定带 `sender_key_id`

状态：已修复（2026-04-14）

现状：

- 当前安装逻辑会直接写：
  - `payload.get("sender_key_id") or normalized.get("sender_key_id") or ""`
- 这意味着空 `sender_key_id` 也能落进本地状态

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- inbound sender key 记录可能变成“有 device、有 key bytes、但没有正式 key id”
- 后续按 `sender_key_id` 定位时会进入不稳定 fallback

建议：

- `sender_key_id` 也应在安装前收成硬性必填
- 不要让缺 key id 的 inbound key 进入持久化状态

### F-481：旧 fanout 可以无条件覆盖同设备的新 inbound sender key

状态：已修复（2026-04-14）

现状：

- `apply_group_session_fanout()` 直接：
  - `inbound_sender_keys[owner_device_id] = {...}`
- 没有比较：
  - `member_version`
  - `issued_at`
  - `updated_at`
  - `installed_at`

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 晚到旧 fanout 也能把更新的 inbound sender key 覆盖回去
- 本地 group key state 不具备最基本的 monotonic install contract

建议：

- inbound key 安装必须比较版本/时间并拒绝回滚
- 不能继续用“最后一次写入”决定当前 sender key

### F-482：重复 fanout item 命中当前设备时，接收端采用“first match wins”

状态：已修复（2026-04-14）

现状：

- `_select_group_fanout_envelope()` 遍历 `fanout`
- 只要命中：
  - `scheme == group fanout`
  - `session_id == current`
  - `recipient_device_id == local`
- 就直接返回第一条

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 如果外层 envelope 里对同一接收设备带了多条 fanout item
- 接收端没有冲突检测，只会无条件吃第一条

建议：

- fanout 选择应拒绝 duplicate recipient item
- 不要继续用 first-match-wins 掩盖上游冲突

### F-483：history recovery sender-key fallback 会按导入顺序返回第一条匹配 key，没有任何 recency 排序

状态：已修复（2026-04-14）

现状：

- `_find_history_group_sender_key_record()` 会遍历：
  - `devices.values()`
- 然后遇到第一条匹配 `session_id / owner_device_id / sender_key_id` 的记录就返回

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- recovery state 里如果有多份同类 sender key
- 现在是谁先被导入、谁先排到 dict 里，就可能决定 live decrypt 拿哪一条

建议：

- history sender-key fallback 至少要按 `imported_at/exported_at/updated_at` 做明确排序
- 不要继续让 dict insertion order 充当恢复优先级

### F-484：group 文本解密会透明回退到 imported history recovery sender key，调用方拿不到 provenance 信号

状态：已修复（2026-04-14）

现状：

- `decrypt_group_text_content()` 走的 `get_group_sender_key_record(...)`
- 在 runtime state miss 时会继续回退：
  - `_find_history_group_sender_key_record(...)`
- 上层拿不到“这次其实是用 recovery material 解开的”正式标记

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- live group decrypt 和 imported recovery fallback 被混成同一条成功路径
- UI/diagnostics 无法区分“当前会话状态完整”还是“只是 recovery material 在兜底”

建议：

- recovery fallback 成功应显式返回 provenance
- 不要继续把 live sender-key state 和 imported recovery material 混成一层 contract

### F-485：导入 history recovery package 时，已有 `signed_prekey` 会按 `key_id` 被静默覆盖

状态：已修复（2026-04-14）

现状：

- `import_history_recovery_package()` 里：
  - `signed_prekeys[key_name] = {...}`
- 对同一个 `key_id`
- 没有任何新旧判断，直接覆盖

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 同一 source device 的旧 recovery 包
- 可以把更新的 signed prekey private material 覆盖回旧值

建议：

- import 时要对同 key_id 的旧记录做 recency / exported_at 判断
- 不能继续无条件覆盖

### F-486：导入 history recovery package 时，已有 `one_time_prekey` 也会按 `prekey_id` 被静默覆盖

状态：已修复（2026-04-14）

现状：

- `one_time_prekeys[key_name] = {...}`
- 对同一个 `prekey_id`
- 当前同样没有任何新旧判断

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- recovery import 会把已有 one-time prekey 私钥材料直接回写
- 导入顺序而不是版本信息决定最终状态

建议：

- one-time prekey import 也要有明确的 overwrite contract
- 至少要拒绝旧包覆盖新记录

### F-487：导入 history recovery package 时，已有 group sender key 会按 `session_id + key_id` 被静默覆盖

状态：已修复（2026-04-14）

现状：

- `sender_keys[key_id] = normalized_sender_key`
- 对同一 `session_id` 下同一 `key_id`
- 当前也没有比较 `updated_at/exported_at`

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 同一 source device 的旧 recovery 包
- 能把较新的 group sender key 记录覆盖掉

建议：

- group sender key import 也要有 recency guard
- 不要继续只靠 dict assignment 合并 recovery state

### F-488：同一 source device 的旧 recovery package 可以把更晚导入的恢复状态回滚掉

状态：已修复（2026-04-14）

现状：

- import 时会直接改写：
  - `device_record["imported_at"]`
  - `device_record["exported_at"]`
- 并把各类 key material 无条件 merge 回去

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- 对同一 source device，如果先导入新包、后导入旧包
- 当前 state 仍可能被旧包整体回滚

建议：

- recovery import 必须有“拒绝旧包覆盖新包”的正式规则
- 至少按 `exported_at` 建立 monotonic import contract

### F-489：`apply_group_session_fanout()` 会把 outer envelope 的 `sender_identity_key_public` 直接写进 inbound key 记录

状态：已修复（2026-04-14）

现状：

- 安装 inbound key 时直接存：
  - `sender_identity_key_public = normalized.get("sender_identity_key_public")`
- 本地没有再把它和最终安装的 `owner_device_id` 做绑定校验

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- inbound sender key record 里的 identity material
- 仍然只是 transport envelope 自报字段

建议：

- 安装 inbound key 时应把 identity material 和 owner device / owner user 一起正式绑定
- 不要继续把 envelope 自报值直接当本地权威记录

### F-490：本地消息搜索会把 recall notice 当成正常消息内容建立索引

状态：已修复（2026-04-14）

现状：

- `message_search_fts` 的触发器和重建逻辑只排除：
  - `is_encrypted = 1`
- 不排除：
  - `status = recalled`
- recalled 消息本地 content 又已经被改成了 recall notice 文案

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2\client/storage/database.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2\client/managers/message_manager.py)

影响：

- 用户可以搜到一堆“消息已撤回”这类系统 notice
- 但这并不是原始聊天内容，也不是用户真正想搜的业务文本

建议：

- message search 应把 recall notice 排除或单独建模
- 不要继续把撤回占位文案当成普通消息内容入索引

### F-491：`search_all()` 会通过内部调用 `search()` 去改写全局 `_current_results`

状态：已修复（2026-04-14）

现状：

- `search_all()` 并发里直接调用：
  - `self.search(...)`
- 而 `search()` 完成后会无条件：
  - `self._current_results = results`

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2\client/managers/search_manager.py)

影响：

- aggregate search 不只是返回 catalog
- 还会顺手覆盖 SearchManager 的 message-only result state

建议：

- `search_all()` 不应再复用会改写全局 message state 的 `search()`
- aggregate search 和 message-only search 需要拆开缓存槽位

### F-492：aggregate search 输入空关键词时，会把 SearchManager 的全局缓存一起清空

状态：已修复（2026-04-14）

现状：

- `search_all(keyword="")` 会直接：
  - `self._current_results = []`
  - `self._last_catalog_results = empty`

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2\client/managers/search_manager.py)

影响：

- 只要某个 aggregate-search consumer 把关键词清空
- 同一个 singleton 上别的搜索 consumer 的结果缓存也会被顺手清掉

建议：

- 空关键词处理也应限定在当前 search mode / 当前 consumer
- 不要继续清整个 singleton 的共享缓存

### R-067：`SearchManager` 现在是共享可变 singleton，aggregate search 和 message-only search 会互相踩状态

状态：已修复（2026-04-14）

修复说明：

- `SearchManager` 已拆成 `_message_results` 与 `_last_catalog_results` 两套状态。
- `search_all()` 改走不写 message-only 缓存的内部路径，aggregate search 不再覆盖 message-only consumer 的结果槽位。

现状：

- `SearchManager` 同时维护：
  - `_current_results`
  - `_last_catalog_results`
- 两类搜索都共享这一个 singleton

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2\client/managers/search_manager.py)

影响：

- 当前设计天然要求不同搜索入口串行使用
- 只要两个入口交错，就会出现“我的搜索把你的缓存洗掉”的状态踩踏

建议：

- 至少按 search mode 拆分 state
- 更稳妥的是把 search result state 从 singleton manager 拆到调用方上下文

### R-068：imported recovery sender-key fallback 没有正式 provenance / recency contract，live decrypt 结果带有隐藏来源

状态：已修复（2026-04-14）

现状：

- 当前 live decrypt path 会在 runtime state miss 时透明回退到 history recovery state
- 同时 history recovery state 本身又没有明确的“新旧包覆盖规则”和“来源优先级”

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2\client/services/e2ee_service.py)

影响：

- “这条消息为什么现在能解开”
- 可能既不是 live sender-key state，也不是明确用户感知过的 recovery restore，而只是某份 imported material 的隐式兜底

建议：

- recovery fallback 必须有正式 provenance / recency contract
- live decrypt、recovery decrypt、diagnostics 三条链不能继续混成一层成功语义

### F-493：AddFriendDialog 搜索失败时不会清掉旧结果，用户仍可点击上一轮 stale 用户项

状态：已修复（2026-04-14）

修复说明：

- Add Friend 搜索失败分支现在会先清空旧结果区，再更新错误提示。

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `AddFriendDialog._search_async()`
- 异常分支只会：
  - `summary_label.setText("Search failed.")`
  - 弹 `InfoBar.error`
- 不会清空 `result_layout`

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 新一轮搜索失败后
- 对话框里仍保留上一轮可点击结果
- 用户可以继续对已经和当前关键词无关的 stale 用户发好友请求

建议：

- 搜索失败时同步清空结果区
- 至少把旧结果置灰或锁住，避免 stale action 继续可点

### F-494：AddFriendDialog 输入空关键词时只改提示文案，不会清掉上一轮搜索结果

状态：已修复（2026-04-14）

修复说明：

- 空关键词分支现在会取消在途搜索并清空结果区，不再保留旧查询残留项。

现状：

- `AddFriendDialog._trigger_search()` 在 keyword 为空时只会：
  - `summary_label.setText("Please enter a search keyword.")`
  - 然后 `return`
- 不会清空当前结果列表

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户把关键词清空后
- 对话框里仍显示上一轮结果
- 当前 UI 已经处于“空查询”，但 action surface 仍然对应旧查询

建议：

- 空关键词分支也应清空结果区
- 不要继续保留与当前输入不一致的旧结果

### F-495：AddFriendDialog 发起新搜索时，上一轮结果会在“Searching users...”期间继续保持可点击

状态：已修复（2026-04-14）

修复说明：

- Add Friend 每次发起新搜索都会先清空旧结果区，loading 态不再保留可点击 stale 行。

现状：

- `AddFriendDialog._search_async()` 开始时只会：
  - `summary_label.setText("Searching users...")`
- 直到请求成功后才会 `_render_search_results(filtered)`
- 中间不会先清空或禁用旧结果

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户看到的是“正在搜新的关键词”
- 但实际上仍能点旧关键词留下的结果项
- 这会把 remote user search 的输入态和可执行 action 分裂开

建议：

- 新搜索开始时先清空或禁用旧结果区
- loading 态不要继续保留可执行的 stale 行

### F-496：AddFriendDialog 在空关键词触发搜索时不会取消已有 in-flight 搜索，晚到旧结果仍可能回填

状态：已修复（2026-04-14）

修复说明：

- Add Friend 已补 generation guard；空关键词和新关键词都会推进 generation 并取消旧 task，晚到旧结果不再允许回填。

现状：

- `AddFriendDialog._trigger_search()` 在 keyword 为空时直接返回
- 这条分支不会取消 `_search_task`
- 如果前一轮搜索仍在飞，晚到成功后仍会 `_render_search_results()`

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户已经把查询清空
- 但旧查询结果仍可能在稍后重新出现
- 对话框会回到“空关键词 + 非空结果”的自相矛盾状态

建议：

- 空关键词触发时也要取消 in-flight 搜索
- 渲染前补一层当前 keyword 一致性校验

### F-497：`security_pending` 释放发送会按“最新消息优先”重放，而不是按原始发送顺序 FIFO 释放

状态：已修复（2026-04-14）

现状：

- `MessageManager._collect_security_pending_messages()` 直接调用：
  - `db.get_messages(session_id, limit=...)`
- [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `get_messages()` 是：
  - `ORDER BY timestamp DESC`
- `release_security_pending_messages()` 又直接按返回顺序逐条 `send_message(...)`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 一批待确认消息释放后
- 新消息会先于旧消息发出
- 本地待确认队列没有保持用户原始输入顺序

建议：

- release 前至少按原始创建时间升序处理
- `security_pending` 应有正式 FIFO queue contract

### F-498：`security_pending` 丢弃也按“最新消息优先”删除，删除顺序和原始输入顺序相反

状态：已修复（2026-04-14）

现状：

- `discard_security_pending_messages()` 同样依赖 `_collect_security_pending_messages()`
- 而这份集合来自 `ORDER BY timestamp DESC`
- 删除和 `MessageEvent.DELETED` 发射都按这条倒序列表执行

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 用户看到的待确认消息如果是一串连续输入
- discard 时会从最新一条开始倒着删除
- 这和用户对“丢弃这一批未发送消息”的直觉顺序不一致

建议：

- discard 也应基于 FIFO 队列语义处理
- 至少把删除顺序和原始输入顺序统一

### F-499：busy 分支会在校验 `call_id` 之前返回 `call_busy`，空 `call_id` 的非法 invite 可被忙线结果掩盖

状态：已修复（2026-04-14）

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `invite()`
- 先检查 `initiator_call/recipient_call`
- 只有不 busy 时才继续校验：
  - `normalized_call_id`
  - `if not normalized_call_id: raise 422`

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)

影响：

- 当目标或发起方正忙线时
- 一个缺失 `call_id` 的非法 invite 不会返回 `422`
- 而是被直接折叠成 `call_busy`

建议：

- 基础字段校验应先于 busy 分支
- 不要让业务状态掩盖协议层非法输入

### F-500：客户端 `call_busy` UI 完全忽略 `busy_user_id`，会把“自己忙线”也提示成“对方忙线”

状态：已修复（2026-04-14）

现状：

- 服务端 busy payload 明确包含：
  - `busy_user_id`
- 且当 `initiator_call is not None` 时，这个字段会是发起者自己
- 但 [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_busy()` 固定提示：
  - `The other participant is already in another call.`

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 当服务端判定“本机自己已经在另一通电话里”时
- UI 仍会错误归因为“对方忙线”
- 用户得到的失败原因是错的

建议：

- busy 文案应基于 `busy_user_id` 区分“自己忙线”与“对方忙线”
- 不要继续硬编码成单一对方原因

### F-501：`call_busy` 里的 `active_call_id` 会在客户端模型层被直接丢掉

状态：已修复（2026-04-14）

现状：

- 服务端 busy payload 明确带：
  - `active_call_id`
- 但 `ActiveCallState.from_payload()` 没有这个字段
- `CallManager._handle_busy()` 只会走 `_merge_state()` 生成普通 `ActiveCallState`

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\models\call.py](D:\AssistIM_V2/client/models/call.py)
- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- 服务端其实已经告诉了客户端“真正占用中的那通电话 id”
- 但客户端事件、session call_state、UI 全都拿不到
- busy payload 的关键上下文在模型层就被截断了

建议：

- busy 事件不要继续复用普通 `ActiveCallState` 载体
- 至少把 `active_call_id` 纳入正式 call-busy contract

### F-502：来电窗口在接听前被用户手动关闭时，客户端会发 `hangup` 而不是 `reject`

状态：已修复（2026-04-14）

现状：

- [call_window.py](/D:/AssistIM_V2/client/ui/windows/call_window.py) 的 `closeEvent()`
- 只要不是程序化 close，就会 `_emit_hangup()`
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_window_hangup_requested()`
- 又会直接转成 `chat_controller.hangup_call(call_id)`

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 来电方如果在接听前直接关窗口
- 对外发出的不是 `call_reject`
- 而是普通 `call_hangup`

建议：

- 来电未接听阶段的窗口关闭应走 reject 语义
- 不要继续和“已接通后挂断”共用同一条 hangup path

### F-503：来电窗口接听前手动关闭后，外呼侧系统结果会被记成 `failed/ended`，而不是 `rejected`

状态：已修复（2026-04-14）

现状：

- 接听前手动关窗会走 `hangup`
- 外呼侧收到的是 `call_hangup`，不是 `call_reject`
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_call_end_outcome()`
- 对“未 answered 且 actor 不是 initiator”的 `call_hangup`
- 会回退成 `failed`

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 被叫只是“拒接/关掉来电窗口”
- 主叫侧聊天里却可能留下“通话失败”而不是“对方已拒绝”
- 终态语义被窗口交互路径带偏

建议：

- 先把 pre-answer close 正式收口为 reject
- 再让 call result message 只根据正式终态生成

### F-504：通话结果系统消息按 `(call_id, outcome)` 去重，同一通电话在晚到终态下仍可能写出多条不同 outcome 消息

状态：已修复（2026-04-14）

现状：

- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_call_result_messages_sent`
- 去重 key 是：
  - `(call.call_id, outcome)`
- 不是单纯 `call_id`

证据：

- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 同一通电话如果先被记成 `busy`
- 后面又因晚到终态被记成 `failed` / `cancelled`
- 聊天里仍可能插入多条相互矛盾的系统结果消息

建议：

- 通话结果消息应按 `call_id` 做单次 authoritative 终态收口
- 不要按 outcome 维度继续放行多次写入

### F-505：`CallManager._handle_error_message()` 只按外层 `msg_id` 路由失败，不看 payload 里的 `call_id`

状态：已修复（2026-04-14）

现状：

- `_handle_error_message()` 的判定条件是：
  - `message.msg_id == self._active_call.call_id`
- 并不会检查 `payload.call_id`

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- 当前错误路由完全耦合在“所有 call 命令都把 `msg_id` 复用成 `call_id`”这个隐含约束上
- 一旦服务端 error envelope 改动或补上真实请求级 `msg_id`
- 客户端就会开始静默漏掉 call failure

建议：

- call error routing 应显式绑定 `payload.call_id`
- 不要继续把 outer `msg_id` 当成 call identity

### F-506：服务端允许被叫在 `accepted` 之后继续发送 `call_reject`

状态：已修复（2026-04-14）

现状：

- `CallService.reject()` 只校验：
  - 调用者是 `recipient_id`
- 然后直接：
  - `registry.end(call.call_id)`
  - 返回 `call_reject`
- 没有检查当前状态是否仍处于 `invited/ringing`

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)

影响：

- 一通已经 accepted 的电话
- 仍可被晚到的 `call_reject` 覆盖成“拒绝”
- 服务器终态约束没有闭合

建议：

- reject 只能在 pre-answer 状态合法
- accepted 之后应只允许 hangup / media failure / timeout 这类终态

### F-507：通话中途如果底层 direct 会话漂移或不再是双人成员，连 `hangup` 都会被服务端拒绝，registry 忙线状态会残留

状态：已修复（2026-04-14）

现状：

- `CallService._require_participant_call()` 每次都要再调：
  - `_require_private_session(call.session_id, user_id)`
- `_require_private_session()` 又强制要求：
  - session 仍存在
  - 当前用户仍是成员
  - `type == private`
  - `len(member_ids) == 2`
- 这意味着 session 漂移后，`accept/reject/hangup/offer/answer/ice` 全都会直接报错

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)

影响：

- 通话中途如果 direct 会话被删除、成员关系漂移、或不再满足双人成员
- 用户连结束这通电话都做不到
- registry 中的 active call 也不会被清掉，双方还可能持续处于 busy

建议：

- call runtime 应和 invite 时的 participant snapshot 绑定
- session 漂移不能继续阻止 hangup / cleanup 终态

### F-508：麦克风恢复可用时，通话窗口会自动把用户原本的 mute 状态改回“Mic on”

状态：已修复（2026-04-14）

现状：

- [call_window.py](/D:/AssistIM_V2/client/ui/windows/call_window.py) 的 `_on_microphone_available_changed(True)`
- 会无条件：
  - `set_icon(MICROPHONE)`
  - `set_label("Mic on")`
  - `set_checked_quietly(False)`

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 如果用户原本主动静音
- 只要设备临时不可用后又恢复
- UI 就会把这份用户偏好覆盖掉

建议：

- microphone availability 恢复不应重置用户 mute preference
- 设备可用性和用户开关必须拆开建模

### R-069：AddFriendDialog 的用户搜索没有正式 keyword generation guard，latest-wins 依赖任务取消恰好生效

状态：已修复（2026-04-14）

现状：

- `AddFriendDialog._search_async(keyword)` 成功后直接：
  - `_render_search_results(filtered)`
- 没有像 sidebar grouped search 那样再校验：
  - 当前输入框文本是否仍等于该 `keyword`

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 当前 latest-wins 语义完全依赖 `_search_task.cancel()` 刚好成功
- 一旦底层 await 不及时响应取消或未来 search flow 变复杂
- 晚到旧结果就会直接覆盖当前查询

建议：

- 用户搜索也应补 generation / keyword guard
- 不要继续把正确性建立在“取消一定足够快”上

### R-070：`call_busy` 当前没有单一 canonical payload contract，attempted call 和 blocking call 被拆成两套 id

状态：closed（2026-04-14）

修复记录：

- busy payload 现在明确以本次 attempted call 为主体：`call_id/session_id/initiator_id/recipient_id/status=busy/media_type/created_at`
- blocking call 上下文保留为 `active_call_id/active_session_id/active_initiator_id/active_recipient_id/active_media_type`
- 客户端 busy 消费必须匹配本地当前 attempted call，不再把 blocking call 与本地 active call 混成一条状态

现状：

- busy payload 同时带：
  - `call_id` / `session_id`：失败的这次新 invite
  - `active_call_id`：真正占用中的电话
  - `busy_user_id`：真正忙线的人
- 但客户端主模型 `ActiveCallState` 只吸收：
  - `call_id/session_id/status`

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\models\call.py](D:\AssistIM_V2/client/models/call.py)
- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- busy 事件到底描述的是“失败的这次呼叫”还是“当前阻塞中的那次呼叫”
- 现在没有单一真相
- 上层 UI、session call_state、系统消息只能拿到半残上下文

建议：

- 为 `call_busy` 单独定义正式 payload/model
- 不要继续强塞进普通 active-call state

### R-071：通话窗口没有正式的“speaker availability”状态，输出设备热插拔不在状态机里

状态：closed（2026-04-14）

修复记录：

- `_play_remote_audio()` 不再在远端音频到达且当前无输出设备时直接退出
- 无输出设备时会保持消费循环并周期性重试，输出设备恢复后可继续创建 sink 并进入播放路径
- 远端音频状态会显式上报 `Remote audio received (no output device)`，不再把 speaker availability 缺失伪装成永久 connecting

现状：

- `CallWindow` 只在构造时快照：
  - `_has_audio_output = bool(QMediaDevices.audioOutputs())`
- `AiortcVoiceEngine` 只有：
  - `speaker_enabled_changed`
- 没有对应的 `speaker_available_changed`

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)
- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 如果通话开始时没有输出设备
- speaker 控件会保持 disabled
- 后面即使热插拔恢复输出设备，也没有正式链路把控件和播放状态带回可用态

建议：

- speaker availability 也应进入 runtime state machine
- 不要继续把“enabled”同时承担“有没有设备”的语义

### R-072：`security_pending` 当前不是正式待发送队列，而是“最近消息页 + 倒序扫描”的隐式实现

状态：已修复（2026-04-14）

现状：

- 现有 release / discard 都来自：
  - 最近 200 条消息扫描
  - `ORDER BY timestamp DESC`
- 本地没有单独的 authoritative pending queue

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- `security_pending` 的处理范围、顺序、剩余集合
- 都不是一份正式队列语义
- 当前实现更像“从最近一页消息里猜待确认消息”

建议：

- 把 `security_pending` 建成正式的本地待发送队列
- 范围和顺序不要再依赖消息页扫描

### F-509：AddFriendDialog 的搜索摘要会把不可操作结果也算进“找到 N 个用户”

状态：已修复（2026-04-14）

现状：

- [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 `AddFriendDialog._search_async()`
- 成功后直接用 `len(filtered)` 更新 summary
- 但 `filtered` 只排除了自己，没有排除“Already Friends”这类不可操作结果

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 搜索摘要会高报当前真正可操作的结果数量
- 用户看到“找到 N 个用户”，但实际可点的添加入口更少

建议：

- 搜索摘要应区分“总结果数”和“可添加结果数”
- 不要继续把 disabled row 一起算进主摘要

### F-510：AddFriendDialog 在请求提交途中关闭窗口，会丢失本地 follow-up，即使远端请求已成功

状态：已修复（2026-04-14）

现状：

- `AddFriendDialog._send_friend_request_async()` 只有在 await 返回后才会：
  - `friend_request_sent.emit(...)`
  - `self.close()`
- 但窗口 `finished/destroyed` 会取消 `_action_task`
- 一旦用户在请求 in-flight 时主动关窗，本地 follow-up 就会被取消

证据：

- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 如果后端其实已经接受了这次好友请求
- 当前设备的 requests / contacts 本地状态仍可能停在旧快照
- 本地正确性继续依赖别的 realtime 或手工 reload 补救

建议：

- “窗口关闭”不能直接等价于“业务取消”
- send_friend_request 的本地 follow-up 应和对话框生命周期解耦

### F-511：SessionPanel 的 grouped search 晚到结果在 teardown 后仍可能重建 flyout

状态：已修复（2026-04-14）

现状：

- [session_panel.py](/D:/AssistIM_V2/client/ui/widgets/session_panel.py) 的 `_run_global_search()`
- await 之后只检查：
  - `self.search_box.text().strip() == keyword`
- 没有像联系人页那样再检查 `_destroyed` / Qt object 有效性

证据：

- [D:\AssistIM_V2\client\ui\widgets\session_panel.py](D:\AssistIM_V2/client/ui/widgets/session_panel.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- panel teardown 时即使已经 cancel 了 task
- 晚到成功结果仍可能继续 `_show_search_flyout()`
- 会把旧 generation 的搜索 overlay 再次拉起来

建议：

- SessionPanel 的 grouped search 也要补 destroyed / validity guard
- 不要只靠任务取消维持 teardown 正确性

### F-512：本地消息聚合搜索每个会话只保留“第一条命中”，后续更好的命中只会涨计数不会更新卡片内容

状态：已修复（2026-04-14）

现状：

- [search_manager.py](/D:/AssistIM_V2/client/managers/search_manager.py) 的 `search()`
- 对同一 `session_id`：
  - 第一条命中会生成 `SearchResult`
  - 后续命中只做 `existing.match_count += 1`
- 不会比较“更新的时间 / 更好的 snippet / 更准确的命中位置”

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- 搜索卡片可能长期展示该会话里一条较旧、较差的命中片段
- 但旁边计数已经反映了更多命中，卡片语义和真实命中集合分裂

建议：

- grouped search 应定义“代表性命中”的正式选择规则
- 不能只按第一条命中静态锁定卡片内容

### F-513：联系人搜索在 LIKE fallback 模式下不搜索 `display_name`

状态：已修复（2026-04-14）

现状：

- [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `search_contacts()` / `count_search_contacts()`
- LIKE fallback 只查：
  - `nickname`
  - `remark`
  - `assistim_id`
  - `region`
- 没有把 `display_name` 纳入查询

证据：

- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 一旦 FTS 不可用或触发 LIKE fallback
- 仅靠 display_name 才能命中的联系人会直接搜不到
- 搜索能力依赖运行时 FTS 环境，不稳定

建议：

- LIKE fallback 和 FTS 应覆盖同一组正式字段
- `display_name` 不能继续只存在于缓存、不存在于 fallback 查询

### F-514：群搜索命中群名时，结果卡片会把真正命中的文本丢掉，只显示成员数

状态：已修复（2026-04-14）

现状：

- [global_search_panel.py](/D:/AssistIM_V2/client/ui/widgets/global_search_panel.py) 的 `_build_group_card()`
- 当 `matched_field != "member"` 时
- subtitle 固定渲染成“{count} 位成员”
- 不会显示 `result.matched_text`

证据：

- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)

影响：

- 用户明明是按群名搜到的结果
- 卡片却只显示成员数，看不到匹配片段
- group search 的“为什么命中”在 UI 上被隐藏了

建议：

- group card 也应保留正式 matched-text contract
- 不要在 name match 时把命中信息退化成成员数摘要

### F-515：CreateGroupDialog 的本地好友过滤不支持 `assistim_id`

状态：已修复（2026-04-14）

现状：

- [group_creation_dialogs.py](/D:/AssistIM_V2/client/ui/windows/group_creation_dialogs.py) 的 `CreateGroupDialog._rebuild_member_list()`
- 当前只按：
  - `display_name`
  - `username`
  - `signature`
- 过滤好友
- 同仓其他相似入口已经支持 `assistim_id`

证据：

- [D:\AssistIM_V2\client\ui\windows\group_creation_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_creation_dialogs.py)
- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)

影响：

- 联系人域不同入口的本地搜索字段 contract 继续分裂
- 用户按 AssistIM 号能在一个入口找到好友，在另一个入口却找不到

建议：

- 群创建相关入口应复用统一的联系人过滤字段集
- 不要再让各弹窗各自维护一套搜索字段

### F-516：群成员管理窗口刷新失败后会重新开放旧快照上的操作入口

状态：已修复（2026-04-14）

现状：

- [group_member_management_dialogs.py](/D:/AssistIM_V2/client/ui/windows/group_member_management_dialogs.py) 的 `_reload_group_async()`
- `fetch_group()` 失败后会：
  - `InfoBar.error(...)`
  - `_set_busy(False, "...load_failed...")`
  - `return`
- 但不会清空旧的 `_group_record` / `_members()` / 权限快照

证据：

- [D:\AssistIM_V2\client\ui\windows\group_member_management_dialogs.py](D:\AssistIM_V2/client/ui/windows/group_member_management_dialogs.py)

影响：

- 窗口会在“加载失败”后重新变成可操作
- 但用户操作的其实还是旧成员列表和旧权限快照
- 错误之后继续 mutation 的语义不可靠

建议：

- refresh failure 后应明确进入 stale / degraded state
- 至少要禁止继续在未确认快照上执行成员 mutation

### F-517：服务端正式发送入口允许空内容消息

状态：已修复（2026-04-14）

现状：

- [message.py](/D:/AssistIM_V2/server/app/schemas/message.py) 的 `MessageCreate.content` 默认就是空字符串
- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `send_message()` / `send_ws_message()`
- 只做 membership / extra normalization / encryption validation
- 没有对普通消息内容做 non-empty 校验

证据：

- [D:\AssistIM_V2\server\app\schemas\message.py](D:\AssistIM_V2/server/app/schemas/message.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 即使桌面端主输入框会拦截空文本
- 正式服务端边界仍然接受空内容消息
- HTTP / WS 协议 contract 继续弱于业务语义

建议：

- 服务端要收口“哪些消息类型允许空内容”
- 普通 text/system 入口不能只依赖前端拦截

### F-518：服务端正式编辑入口同样允许把消息改成空内容

状态：已修复（2026-04-14）

现状：

- [message.py](/D:/AssistIM_V2/server/app/schemas/message.py) 的 `MessageUpdate.content` 没有 non-empty 约束
- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `edit()`
- 也没有额外的空内容校验

证据：

- [D:\AssistIM_V2\server\app\schemas\message.py](D:\AssistIM_V2/server/app/schemas/message.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 正式编辑边界允许把一条已有消息改成空字符串
- 消息可见语义、预览语义、已编辑语义会进一步分裂

建议：

- edit 也要沿用和 send 相同的内容合法性约束
- 不要允许“空编辑”绕过正式消息语义

### F-519：group E2EE fanout 校验允许同一接收设备重复出现

状态：已修复（2026-04-14）

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `_require_group_fanout()`
- 当前只校验：
  - fanout 是非空 list
  - 每个 item 是 dict
  - 每个 item required fields / scheme 合法
- 不会校验 `(recipient_user_id, recipient_device_id)` 唯一性

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 同一个接收设备可以在 fanout 中出现多次
- 服务端不会拒绝重复或冲突 ciphertext
- 群 E2EE fanout 仍不是单一 authoritative 目标集合

建议：

- fanout item 至少要按 `(recipient_user_id, recipient_device_id)` 做唯一性约束
- 冲突重复项不能继续静默放行

### F-520：direct E2EE envelope 校验允许 self-target / loopback recipient

状态：已修复（2026-04-14）

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 direct text / attachment envelope 校验
- 只检查：
  - `recipient_user_id`
  - `recipient_device_id`
  - `sender_device_id`
  - `recipient_prekey_*`
  - ciphertext / nonce
- 没有禁止 `recipient_user_id == sender_id`
- 也没有禁止 `recipient_device_id == sender_device_id`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 直接会话里的 envelope 现在仍允许构造“发给自己/发回自己设备”的 loopback 目标
- 这说明 direct E2EE validator 还没真正表达“两端私聊”的正式业务约束

建议：

- direct envelope 至少要拒绝 self-recipient / same-device loopback
- 这类约束不能继续留给客户端自觉维护

### F-521：撤回加密文本时，客户端会直接丢掉本地加密态和原密文

状态：已修复（2026-04-14）

现状：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `recall_message()` / `_process_recall()`
- 在把消息改成本地 recall notice 之前会：
  - `_drop_encryption_state(message)`
- `_drop_encryption_state()` 直接 `pop("encryption")`
- 数据库存储内容随后也会变成 recall notice 文本

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 一条原本加密的文本消息一旦被撤回
- 本地就不再保留对应加密 envelope / ciphertext / local crypto context
- 这会让后续审计、恢复、问题排查都失去原始加密态

建议：

- recall notice 不应破坏原消息的加密存档语义
- UI 展示层和持久化密文层必须分开

### F-522：`recover_session_messages()` 只会重试最近 N 条本地消息

状态：已修复（2026-04-14）

现状：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的 `recover_session_messages()`
- 本地恢复起点是：
  - `db.get_messages(session_id, limit=effective_limit)`
- 默认 limit 是 500

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 更早的本地未解密消息不会进入这次恢复扫描
- 用户看到“恢复完成”，但老消息仍然保持未恢复状态
- 当前恢复边界继续依赖最近一页窗口，而不是 session 全量 contract

建议：

- recover contract 必须明确“范围是最近 N 条”还是“整会话”
- 当前默认行为至少要在 UI/结果里显式暴露范围限制

### F-523：`recover_session_messages()` 会把“恢复可读性”动作顺带变成附件预取下载

状态：已修复（2026-04-14）

现状：

- 同一个 `recover_session_messages()` 流程里
- 对每条本地恢复成功消息和远端拉回消息都会：
  - `_maybe_schedule_encrypted_media_prefetch(...)`

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 用户触发一次“恢复解密”
- 实际上还会顺带启动加密媒体后台下载
- 恢复语义和媒体预取语义被混在一起，副作用过重

建议：

- decrypt recovery 和 media prefetch 应拆成两条明确链路
- 不要在恢复动作里隐式启动附件下载

### F-524：`security_pending` 的 release / discard 没有 in-progress guard

状态：已修复（2026-04-14）

现状：

- [message_manager.py](/D:/AssistIM_V2/client/managers/message_manager.py) 的
  - `release_security_pending_messages()`
  - `discard_security_pending_messages()`
- 当前都没有 session 级互斥或 in-progress 标记
- 两次点击会并发扫描并处理同一批本地 held messages

证据：

- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 同一批待确认消息可能被重复 release 或重复 delete
- 结果数量、message_ids、UI 提示都可能失真
- `security_pending` 继续不是正式的单次消费动作

建议：

- release / discard 必须补 session 级互斥
- 同一会话同时只能存在一个 security-pending action

### F-525：复用已有 `call_id` 创建新通话时，旧参与者的 busy 映射会被错误指到新通话

状态：已修复（2026-04-14）

现状：

- [call_registry.py](/D:/AssistIM_V2/server/app/realtime/call_registry.py) 的 `create()`
- 会直接：
  - `self._calls[call_id] = active_call`
  - 覆盖新参与者的 `_call_id_by_user_id`
- 但不会清理旧参与者仍指向该 `call_id` 的 mapping

证据：

- [D:\AssistIM_V2\server\app\realtime\call_registry.py](D:\AssistIM_V2/server/app/realtime/call_registry.py)

影响：

- 一旦服务端接受了复用 `call_id` 的新 invite
- 旧用户的 `get_by_user_id()` 也可能被解析到这通新电话
- busy 判定会污染到无关用户

建议：

- registry 不能继续允许不清理旧映射的 call_id 覆盖
- 要么拒绝冲突 call_id，要么先完整 teardown 旧索引

### F-526：`CallManager._merge_state()` 会把上一通电话的字段继承到别的 `call_id`

状态：已修复（2026-04-14）

现状：

- [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 的 `_merge_state()`
- 只有 direction 继承做了 `current_state.call_id == payload.call_id` 判断
- 但后面的：
  - `initiator_id`
  - `recipient_id`
  - `media_type`
- 只要 payload 缺值，就会直接从 `current_state` 继承

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- 一条不同 `call_id` 的半残 payload
- 也可能和当前 active call 的旧字段拼成一条假通话状态
- 当前通话单槽状态机继续会被跨 call 污染

建议：

- 跨 `call_id` 的 payload 不能继续吃当前 active-call 残留字段
- state merge 必须严格按 call generation 隔离

### F-527：摄像头恢复可用时，通话窗口会自动把用户原本的 camera-off 选择改回打开

状态：已修复（2026-04-14）

现状：

- [call_window.py](/D:/AssistIM_V2/client/ui/windows/call_window.py) 的 `_on_camera_available_changed(True)`
- 会无条件：
  - `set_icon(CAMERA)`
  - `set_label("Camera on")`
  - `set_checked_quietly(True)`

证据：

- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 只要摄像头设备临时丢失后又恢复
- UI 就会把用户原本主动关闭摄像头的偏好覆盖掉
- camera availability 和 user preference 仍然混在一起

建议：

- 摄像头可用性恢复不应重置用户 camera-off 状态
- 设备状态和用户开关必须拆开建模

### F-528：`call_ringing` 只回给主叫，无法同步到被叫的其它在线设备

状态：已修复（2026-04-14）

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `ringing()`
- 当前返回：
  - `"call_ringing", [call.initiator_id], ...`
- 被叫自己的其它在线设备不会收到这条 authoritative ringing 事件

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)

影响：

- 被叫侧通话状态仍主要依赖本地 optimistic UI
- 同账号多设备下，只有发出 `ringing` 的那台设备知道自己已经进入 ringing
- call state 继续不是多设备一致的 authoritative 模型

建议：

- `call_ringing` 至少要广播到该通话参与者的所有在线设备
- 不要只让主叫拿到权威 ringing 状态

### F-529：服务端正式发送入口没有 `message_type` allowlist，客户端可直接构造 `system` 消息入库

状态：已修复（2026-04-12）

修复说明：

- `MessageService.send_message()` / `send_ws_message()` 已通过 `_normalize_client_message_type()` 限定客户端可发送类型为 `text/image/file/video/voice`
- HTTP 与 WS 入口均已覆盖拒绝 `system` 的回归测试

原状态：已确认

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `send_message()` / `send_ws_message()`
- 会直接把外部传入的 `message_type` 原样交给 repository create
- 当前没有任何“用户态只能发送 text/image/file/video/voice，不能发送 system”的服务端边界

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 现在“系统消息”不是服务端保留类型
- 任何走正式发送入口的客户端都可以伪造系统消息
- 通话结果、公告类文案这类本应权威生成的消息类型边界没有收口

建议：

- 服务端正式 send 边界必须建立 `message_type` allowlist
- `system` 只能由服务端内部能力生成，不能继续对普通发送入口开放

### F-530：服务端允许创建没有附件 payload 的 `image/file/video/voice` 消息

状态：已修复（2026-04-12）

修复说明：

- `MessageService._validate_attachment_payload()` 已为 `image/file/video/voice` 建立附件 payload gate
- 非加密附件消息必须在 `extra` / `media` 中提供 `url`、文件名、MIME/type 和正数 size
- 带 `attachment_encryption.enabled` 的加密附件继续由已有 envelope 校验负责必填密文字段
- 已补 HTTP 发送残缺附件 payload 的 422 回归，并调整非文本编辑测试使用完整合法附件 payload

原现状：

- `send_message()` / `send_ws_message()` 只会在 `extra` 里存在 `attachment_encryption` 时做附件 envelope 校验
- 但对非加密附件消息，本身并不要求 `url/name/size/file_type` 等附件字段
- 结果是空内容、无附件元数据的附件型消息也能通过正式入口入库

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

修复前影响：

- `message_type` 和真实消息形态继续脱节
- 客户端和服务端都会收到“类型是附件，但实际没有附件 payload”的半残消息
- 正式协议边界仍弱于业务语义

修复建议：

- 对 `image/file/video/voice` 建立正式 payload contract
- 非加密附件和加密附件都要有权威必填字段校验

### F-531：服务端允许编辑非文本消息，附件消息和系统消息都能走正式 edit 入口

状态：已修复（2026-04-12）

修复说明：

- `MessageService.edit()` 已调用 `_ensure_message_type_allows_edit()`
- `EDITABLE_MESSAGE_TYPES` 当前收口为 `{"text"}`，非文本消息编辑返回 422
- 已有 `test_message_mutations_reject_terminal_status_and_non_text_edits` 覆盖 image 消息不可编辑

原状态：已确认

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `edit()`
- 当前只校验“是不是发送者本人”和“是否超时”
- 不校验消息类型是否允许编辑

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- `image/file/video/voice/system` 这类非文本消息也能被改写 `content`
- 附件消息的 content / extra contract 会继续被破坏
- “编辑消息”目前并不等价于“编辑文本消息”

建议：

- 服务端 edit 入口应只接受正式允许编辑的消息类型
- 如果产品只支持文本编辑，就明确收口到 text

### F-532：服务端 edit 没有状态 gate，recalled/failed 等异常状态消息仍可继续编辑

状态：已修复（2026-04-12）

修复说明：

- `MessageService.edit()` 已调用 `_ensure_message_status_allows(message, "edit")`
- `MUTABLE_MESSAGE_STATUSES` 当前收口为 `sent/edited`
- 已有 `test_message_mutations_reject_terminal_status_and_non_text_edits` 覆盖 recalled 消息不可再编辑

原状态：已确认

现状：

- `edit()` 只校验 sender 和时间窗口
- 并没有校验消息当前状态
- 当前服务端不会拒绝对 recalled / failed 等状态消息继续发起 edit

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 正式消息生命周期没有收口
- 客户端本地规则和服务端权威规则继续分叉
- “已撤回后不可编辑”这类语义现在只停留在客户端侧

建议：

- edit 入口必须建立状态 allowlist
- recalled / failed / deleted / system 这类状态都应有显式拒绝

### F-533：服务端 recall 没有状态/类型 gate，已撤回或非普通消息仍可重复 recall

状态：已修复（2026-04-12）

修复说明：

- `MessageService.recall()` 已调用 `_ensure_message_status_allows(message, "recall")`，recalled 等终态会返回 409
- `MessageService.recall()` 已新增 `_ensure_message_type_allows_recall()`，只允许客户端用户态消息类型，`system` 等非用户态消息返回 422
- 已有 API 测试覆盖重复 recall，新增 `test_message_service_recall_rejects_non_user_message_types` 覆盖 `system` 类型 gate

原状态：已确认

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `recall()`
- 当前只校验 sender 和时间窗口
- 不校验消息当前状态，也不限制可撤回的消息类型

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- recall 正式边界仍然过宽
- 已撤回消息、失败消息甚至客户端伪造的系统消息都可能继续进入 recall 流程
- 服务端没有给消息生命周期建立正式终态

建议：

- recall 入口要建立类型和状态 gate
- 已撤回 / 非用户态消息应直接拒绝

### F-534：direct text envelope 的标量字段没有类型校验，字典/列表值会被 `str()` 误判为合法

状态：已修复（2026-04-12）

修复说明：

- _require_envelope_fields() 已改为要求必填字段必须是非空字符串，不再通过 str(value) 接受 dict/list 等结构值
- 已补 	est_message_service_rejects_structured_values_for_envelope_scalar_fields 覆盖 direct text 场景

原状态：已确认

现状：

- `_validate_direct_text_envelope()` 依赖 `_require_envelope_fields()`
- `_require_envelope_fields()` 用 `str(envelope.get(...)).strip()` 判断必填
- 结果是 `sender_device_id / sender_identity_key_public / recipient_user_id / recipient_device_id / content_ciphertext / nonce`
- 这些本应是标量字符串的字段，传入字典/列表也会被当成“非空合法值”

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- direct text envelope 现在仍停留在“字段看起来有值”层面
- 服务端不会拒绝结构错误的加密 payload
- 后续设备绑定和解密诊断都建立在脏数据之上

建议：

- envelope 必填字段必须做严格类型校验
- 对密钥、nonce、ciphertext、device/user id 都要收口到正式标量 contract

### F-535：direct attachment envelope 的标量字段同样没有类型校验

状态：已修复（2026-04-12）

修复说明：

- _require_envelope_fields() 已改为要求必填字段必须是非空字符串，不再通过 str(value) 接受 dict/list 等结构值
- 已补 	est_message_service_rejects_structured_values_for_envelope_scalar_fields 覆盖 direct attachment 场景

原状态：已确认

现状：

- `_validate_direct_attachment_envelope()` 也复用了 `_require_envelope_fields()`
- `sender_device_id / sender_identity_key_public / recipient_user_id / recipient_device_id / metadata_ciphertext / nonce`
- 当前都只做了“`str()` 后非空”判断

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- direct attachment envelope 仍可携带结构错误的元数据密文和设备字段
- 服务端不会在正式边界拒绝这类 malformed payload

建议：

- direct attachment envelope 也要建立严格的字段类型 contract

### F-536：group text envelope 的 top-level 标量字段没有类型校验

状态：已修复（2026-04-12）

修复说明：

- _require_envelope_fields() 已改为要求必填字段必须是非空字符串，不再通过 str(value) 接受 dict/list 等结构值
- 已补 	est_message_service_rejects_structured_values_for_envelope_scalar_fields 覆盖 group text 场景

原状态：已确认

现状：

- `_validate_group_text_envelope()` 要求的 `session_id / sender_device_id / sender_key_id / content_ciphertext / nonce`
- 当前仍然走 `_require_envelope_fields()` 的 `str()` 非空判断

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- group text top-level envelope 也能带着结构错误的 key/ciphertext 字段进入服务端
- group E2EE 的正式协议边界还是“像就行”

建议：

- group text top-level envelope 要补齐严格标量校验

### F-537：group attachment envelope 的 top-level 标量字段没有类型校验

状态：已修复（2026-04-12）

修复说明：

- _require_envelope_fields() 已改为要求必填字段必须是非空字符串，不再通过 str(value) 接受 dict/list 等结构值
- 已补 	est_message_service_rejects_structured_values_for_envelope_scalar_fields 覆盖 group attachment 场景

原状态：已确认

现状：

- `_validate_group_attachment_envelope()` 要求的 `session_id / sender_device_id / sender_key_id / metadata_ciphertext / nonce`
- 也仍然只做了 `str()` 非空校验

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- group attachment top-level envelope 也能携带结构错误的密文字段进入正式链路

建议：

- group attachment envelope 的 top-level 字段要和 direct envelope 一样做严格类型校验

### F-538：group fanout item 的标量字段没有类型校验，结构错误 payload 也会通过正式校验

状态：已修复（2026-04-12）

修复说明：

- _require_envelope_fields() 已改为要求必填字段必须是非空字符串，不再通过 str(value) 接受 dict/list 等结构值
- 已补 	est_message_service_rejects_structured_values_for_envelope_scalar_fields 覆盖 group fanout 场景

原状态：已确认

现状：

- `_require_group_fanout()` 对 fanout item 同样复用了 `_require_envelope_fields()`
- `recipient_user_id / recipient_device_id / sender_device_id / sender_key_id / ciphertext / nonce`
- 目前只做 `str()` 非空检查

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- fanout item 的结构错误会一路进入服务端和接收端
- group E2EE 现在不仅 authority 绑定不够，连基本字段类型都没有正式收口

建议：

- fanout item 的 recipient / sender / ciphertext / nonce 都需要严格类型校验

### F-539：实时入站消息会无条件取消本地隐藏，任何 live message 都能把会话重新放回列表

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_on_message_received()`
- 在 `_ensure_session_exists()` 之前就先 `await self._unhide_session(message.session_id)`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 只要该会话再收到一条 live message
- 用户之前做的“本机隐藏/删除会话”就会被立即打破
- tombstone 语义继续被实时入站旁路绕开

建议：

- live message 不应直接等价于“取消本地隐藏”
- 是否复活会话必须走统一 tombstone gate

### F-540：history sync 也会无条件取消本地隐藏，断线补偿会把已隐藏会话整批复活

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_on_history_synced()`
- 遍历每条 synced message 时都会 `await self._unhide_session(message.session_id)`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- reconnect / history sync 不再只是补消息
- 它会顺带取消用户本机的隐藏决定
- “删除/隐藏会话”在断线补偿场景下没有稳定语义

建议：

- history sync 不应直接改 tombstone
- 是否恢复可见性必须走统一会话可见性 contract

### F-541：`add_session()` 本身没有 hidden/tombstone gate，任何后台 fetch/build 都能把会话重新写回本地

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `add_session()`
- 当前只做 `self._sessions[session.session_id] = session` 和 `db.save_session(session)`
- 没有再次检查 `_should_hide_session()` 或本地 tombstone

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 只要某条后台路径拿到一个 session 对象
- 就可以绕开本地隐藏 contract，重新写回内存和数据库
- 当前 tombstone 仍然不是统一 add/remember path 的硬 gate

建议：

- visible/tombstone gate 要下沉到统一 add/remember path
- 不要继续依赖调用方自己记得判断

### F-542：`ensure_remote_session()` 命中已有缓存后会直接短路，fallback/stale session 没有 authoritative 升级路径

状态：已修复（2026-04-14）

现状：

- `ensure_remote_session()` 先读 `_sessions.get(session_id)`
- 一旦本地已经有这个 session，就直接返回，不再走 `fetch_session()`
- 这意味着消息侧先落下的 fallback / stale session，后续显式 ensure 也不会升级成 authoritative snapshot

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- fallback session 会长期保留缺失字段和错误默认值
- session list、E2EE 决策、call capability、counterpart profile 都可能继续围绕旧快照运行
- 当前“ensure loaded”并不真的保证 authoritative

建议：

- `ensure_remote_session()` 不能把“本地有缓存”直接等价成“已经 authoritative”
- 至少要为 fallback / stale session 建立升级路径

### F-543：消息搜索先按原始消息条数限流，再按会话聚合，导致 grouped search 系统性漏会话

状态：已修复（2026-04-14）

现状：

- [search_manager.py](/D:/AssistIM_V2/client/managers/search_manager.py) 的 `search()`
- 会先调用 `self._search_messages(..., limit=normalized_limit)` 拿到原始 message hit
- 然后再按 `session_id` 聚合成 grouped result

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- 如果前 N 条 raw hit 大多来自同一会话
- 其它也命中的会话会在聚合前就被截掉
- grouped search 结果并不是“前 N 个命中会话”，而是“前 N 条命中消息压缩后的残片”

建议：

- grouped search 要么先按 session 聚合再限流
- 要么单独建立 session-level 搜索查询

### F-544：搜索面板的“查看更多(count)”只会展开当前已加载子集，不会真正拉取剩余结果

状态：已修复（2026-04-14）

现状：

- [global_search_panel.py](/D:/AssistIM_V2/client/ui/widgets/global_search_panel.py) 的 `_add_section()`
- 当 `total_count > _section_item_limit` 时会显示“查看更多(count)”
- 但展开动作只是把 `items[:1]` 切成当前 `items`，并不会重新查询更多结果

证据：

- [D:\AssistIM_V2\client\ui\widgets\global_search_panel.py](D:\AssistIM_V2/client/ui/widgets/global_search_panel.py)
- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- UI 会向用户承诺“还有更多结果”
- 但当前 panel 实际只能展开当前那一页已经拿到的子集
- `total_count` 和“可展开得到的结果集”不是同一个 contract

建议：

- expand 动作要么触发正式增量查询
- 要么改成只表达“展开当前结果”，不要继续显示误导性的总数

### F-545：通话窗口不会展示“无麦克风/无摄像头/降级成接收-only”这类真实媒体退化原因

状态：已修复（2026-04-14）

现状：

- [aiortc_voice_engine.py](/D:/AssistIM_V2/client/call/aiortc_voice_engine.py) 会发出
  - `No microphone detected`
  - `Microphone unavailable, receive-only mode`
  - `No camera detected`
  - `Camera unavailable`
- 但 [call_window.py](/D:/AssistIM_V2/client/ui/windows/call_window.py) 的 `_on_engine_state_changed()`
- 并没有为这些状态建立正式 UI 分支

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)
- [D:\AssistIM_V2\client\ui\windows\call_window.py](D:\AssistIM_V2/client/ui/windows/call_window.py)

影响：

- 媒体已经退化成 receive-only 或设备不可用时
- 用户仍只会看到笼统的 `Connecting...` / `Waiting...`
- 通话媒体退化原因没有正式 surface

建议：

- 通话窗口要对关键媒体退化状态建立明确 UI 文案
- 不要继续把设备失败折叠成 generic connecting

### F-546：无效 offer/answer payload 会被客户端静默忽略，通话不会进入正式失败状态

状态：已修复（2026-04-14）

现状：

- [aiortc_voice_engine.py](/D:/AssistIM_V2/client/call/aiortc_voice_engine.py) 的 `_session_description_from_payload()`
- 在 `sdp.type` 或 `sdp.sdp` 缺失时只会返回 `None`
- `_receive_offer()` / `_preload_offer()` / `_receive_answer()` 随后直接 `return`
- 没有任何 `error_reported` 或正式 failed 事件

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- signaling payload 即使已经坏掉
- 通话窗口也只会停在等待/连接中
- 客户端缺少对 malformed SDP 的正式失败收口

建议：

- 无效 SDP payload 必须升级成正式失败信号
- 不要继续静默吞掉

### F-547：无效 ICE payload 也会被客户端静默丢弃，诊断链上没有正式错误面

状态：已修复（2026-04-14）

现状：

- `_receive_ice_candidate()` 里
- `sdpMLineIndex` 解析失败会直接 `return`
- `addIceCandidate()` 的 `ValueError` 也只写 debug log 后返回
- 没有向上层发出任何可见错误

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- ICE payload 错误不会进入正式通话状态机
- 用户和上层 UI 都无法区分“网络慢”和“candidate 已损坏”

建议：

- malformed ICE 也要进入正式 diagnostics / failed contract

### F-548：远端音频轨在“当前无输出设备”时会直接退出，之后再插入输出设备也不会恢复播放

状态：已修复（2026-04-14）

现状：

- [aiortc_voice_engine.py](/D:/AssistIM_V2/client/call/aiortc_voice_engine.py) 的 `_play_remote_audio()`
- 如果 remote track 到达时 `self._remote_audio_output.is_available()` 为假
- 会发一条 `Remote audio received (no output device)` 然后直接 `return`

证据：

- [D:\AssistIM_V2\client\call\aiortc_voice_engine.py](D:\AssistIM_V2/client/call/aiortc_voice_engine.py)

影响：

- 同一通话里只要远端音频轨第一次到达时本机没有输出设备
- 后面就算用户重新插上耳机/扬声器
- 这条 remote audio consumer 也不会再被拉起

建议：

- 无输出设备不应让远端音频消费任务永久退出
- 需要正式的设备恢复重绑/重启播放 contract

### F-549：HTTP 发消息 schema 自身仍把 `system` 暴露为客户端可提交的正式 `message_type`

状态：已修复（2026-04-12）

修复说明：

- `MessageCreate.message_type` schema pattern 已收紧为 `^(text|image|file|video|voice)$`
- `test_http_send_message_requires_msg_id_and_rejects_system_type` 已覆盖 HTTP schema 拒绝 `system`

原状态：已确认

现状：

- [message.py](/D:/AssistIM_V2/server/app/schemas/message.py) 的 `MessageCreate.message_type`
- 正则仍是 `^(text|image|file|video|voice|system)$`
- 也就是说 HTTP 正式 schema 仍把 `system` 当成客户端合法输入

证据：

- [D:\AssistIM_V2\server\app\schemas\message.py](D:\AssistIM_V2/server/app/schemas/message.py)

影响：

- 即使后端 service 层后续补了更严格 gate
- API schema 仍在向调用方暴露“客户端可创建 system message”的错误 contract
- 文档、客户端和服务端边界会继续漂移

建议：

- 把客户端正式可提交的 `message_type` allowlist 收紧
- `system` 只能保留给服务端内部生成链路

### F-550：HTTP 编辑消息 schema 没有 `extra=forbid`，未知编辑字段会被静默忽略

状态：已修复（2026-04-12）

修复说明：

- `MessageUpdate` 已配置 `ConfigDict(extra="forbid")`
- 相关 API 测试已覆盖编辑入口未知字段返回 422

原状态：已确认

现状：

- [message.py](/D:/AssistIM_V2/server/app/schemas/message.py) 里的 `MessageCreate` 明确用了 `ConfigDict(extra="forbid")`
- 但 `MessageUpdate` 没有对应约束
- 调用方额外带的未知字段会被 schema 静默吞掉

证据：

- [D:\AssistIM_V2\server\app\schemas\message.py](D:\AssistIM_V2/server/app/schemas/message.py)

影响：

- create / update 两条正式入口的 schema contract 不一致
- 调用方以为某些编辑字段被接受了，服务端却只是忽略
- 这会继续放大“请求成功但语义没生效”的灰区

建议：

- 统一 create / update schema 的 extra 策略
- 正式编辑入口不要继续静默吃掉未知字段

### F-551：建群正式 schema 允许空群名，服务端会直接持久化 unnamed group

状态：已修复（2026-04-14）

现状：

- [group.py](/D:/AssistIM_V2/server/app/schemas/group.py) 的 `GroupCreate.name` 默认就是空字符串
- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `create_group()`
- 会把 `str(name or \"\").strip()` 直接作为正式群名写进 `sessions/groups`

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 服务端正式建群边界允许产生空群名
- 当前客户端是否补默认名会变成非权威 UI 细节
- 群生命周期 contract 继续缺少最基本的 name 约束

建议：

- 建群正式边界要显式要求非空群名
- 默认名若保留，也应在服务端统一生成而不是允许空值入库

### F-552：群资料更新正式边界允许把群名清成空字符串

状态：已修复（2026-04-14）

现状：

- [group.py](/D:/AssistIM_V2/server/app/schemas/group.py) 的 `GroupProfileUpdate.name`
- 只限制了 `max_length`，没有 `min_length`
- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `update_group_profile()`
- 会把 `normalized_name or \"\"` 写回 `group.name` 和 `session.name`

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 群资料 PATCH 会把 shared group/session 正式名称打成空值
- 这不是前端显示问题，而是服务端正式领域约束缺失

建议：

- 共享群名更新要明确要求非空
- “清空群名”不应作为合法 shared profile mutation

### F-553：群资料 PATCH 即使没有产生任何共享变更，也会无条件广播 `group_profile_update`

状态：已修复（2026-04-14）

现状：

- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `PATCH /groups/{group_id}`
- 调完 `update_group_profile()` 后无条件执行 `_broadcast_group_profile_update(...)`
- 即使 `payload.name/payload.announcement` 都没变，或者请求体根本没有共享字段
- 仍会追加一次 shared profile event fanout

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- no-op PATCH 也会制造正式 shared event
- event_seq、realtime fanout 和真实 shared mutation 不再一一对应
- 客户端会被迫处理大量“语义上没有变化”的权威事件

建议：

- 共享群资料更新应先判定是否产生 effective shared diff
- 只有真正变更时才追加/广播 `group_profile_update`

### F-554：空的 `PATCH /groups/{group_id}/me` 也会创建空白 member profile 并 touch shared session

状态：已修复（2026-04-12）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `update_my_group_profile()`
- 无论 `note` / `my_group_nickname` 是否为空，都会调用 `groups.update_member_profile(..., commit=False)` 和 `sessions.touch_without_commit(...)`
- [group_repo.py](/D:/AssistIM_V2/server/app/repositories/group_repo.py) 的 `update_member_profile()`
- 在 member 记录不存在时会直接创建 `GroupMember(...)`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\repositories\group_repo.py](D:\AssistIM_V2/server/app/repositories/group_repo.py)

影响：

- 一个空 self-profile PATCH 也会产生持久化 side effect
- 当前用户的空白 member metadata 可能被凭空补出来
- shared session `updated_at` 也会被推进

建议：

- self-profile PATCH 先判定是否真的有 self-scoped diff
- 空 mutation 不应创建 metadata row，也不应 touch shared session

### F-555：仅修改 `note` 的 self-profile 也会推进 shared session `updated_at`，但不会给其它成员配套共享事件

状态：已修复（2026-04-12）

现状：

- `update_my_group_profile()` 无论改的是 `note` 还是 `my_group_nickname`
- 都会执行 `sessions.touch_without_commit(group.session_id)`
- 但 [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 里只有 `my_group_nickname is not None` 才广播 `_broadcast_group_profile_update(...)`
- note-only 变更只会发 self-scoped `group_self_profile_update`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- 其它成员后续看到的 session ordering 可能变化
- 但没有任何配套 shared realtime/event 解释这次 shared `updated_at` 变化
- shared 排序语义和 shared 事件语义继续脱节

建议：

- self-only note 不应推进 shared session 活动时间
- 或者必须同时定义清楚对应的 shared 生命周期事件

### F-556：`my_group_nickname` 变更会错误触发 shared `group_profile_update` 广播

状态：已修复（2026-04-12）

现状：

- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `PATCH /groups/{group_id}/me`
- 只要 `payload.my_group_nickname is not None`
- 就会额外广播 `_broadcast_group_profile_update(...)` 给所有成员
- 但 `my_group_nickname` 从接口命名到返回 payload 都是 self-scoped 字段

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- 一个本应只作用于当前用户的 group nickname 改动
- 会被错误提升成 shared group profile event
- 其它成员客户端会收到并处理一条不属于 shared domain 的权威更新

建议：

- `my_group_nickname` 只能走 self-scoped realtime / event contract
- 不要再额外扇出 shared `group_profile_update`

### F-557：shared group/session payload 会把每个成员的 `group_nickname` 一起发给所有成员

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `serialize_group()`
- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `serialize_session()`
- 在 shared `members[]` 里都会直接塞入每个成员的 `group_nickname`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 当前用户自己的 group nickname 本是 self-scoped 资料
- 现在会通过 shared group/session snapshot 泄漏给所有成员
- shared payload 和 self-scoped payload 的边界已经被打穿

建议：

- shared `members[]` 不应继续携带每个成员的私有 `group_nickname`
- self-scoped 字段必须只走 self-scoped payload

### F-558：`group_member_version` / `member_version` 只按成员 ID 计算，角色和 owner 变化不会推进版本

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 和 [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py)
- 都通过 `_group_member_version()` 计算版本
- 这个函数只对排序后的 `member_ids` 做哈希
- 不包含 role、owner、admin 权限或其它成员元数据

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- owner transfer / admin 变更 / role 变更时
- 表面上的 `group_member_version` 仍可能完全不变
- 客户端无法把“成员集合没变但权限拓扑变了”识别成一次正式版本推进

建议：

- 成员版本若要承载权限/角色同步语义
- 版本计算就不能只看 user id 集合

### F-559：给已在群里的成员再次执行 `add_member` 仍会返回成功并 bump 群头像版本

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `add_member()`
- 不会先判定目标用户是否已经在群里
- action 里无条件调用 `sessions.add_member()`、`groups.update_member_role()`、`avatars.bump_group_avatar_version()`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)

影响：

- 重复 add 不会报冲突，只会伪装成一次新的成功加人
- 群头像版本还会被无意义推进
- 客户端很难区分“真的新增成员”和“重复提交的 no-op”

建议：

- 重复 add_member 应返回明确冲突或 no-op 结果
- 不要再对 avatar/version 施加副作用

### F-560：移除不存在的成员也会走成功路径，并继续 bump 群头像版本

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `remove_member()`
- action 里不检查 `groups.remove_member()` / `sessions.remove_member()` 的返回值
- 即使目标成员根本不在群里，仍会继续 `bump_group_avatar_version()`
- 路由最终还是返回 `204`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\repositories\group_repo.py](D:\AssistIM_V2/server/app/repositories/group_repo.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)

影响：

- remove_member 的正式语义里混入了“静默 no-op 也算成功”
- 群头像版本与真实成员变更脱节
- 调用方无法区分“真的移除了人”和“目标本来就不在群里”

建议：

- remove_member 应显式处理 not-a-member 场景
- no-op 不应继续推进任何 group/session 副作用

### F-561：`GroupMemberAdd.role` 对外暴露成可配置字段，但服务端实际上只允许 `member`

状态：已修复（2026-04-14）

现状：

- [group.py](/D:/AssistIM_V2/server/app/schemas/group.py) 的 `GroupMemberAdd`
- 对外暴露了 `role`
- 但 [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `_normalize_new_member_role()`
- 明确把除 `member` 外的所有值都判成非法

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- API contract 暗示“加人时可同时设角色”
- 真实服务端却完全不支持
- 这会让客户端和调用方继续围绕一个不存在的能力写逻辑

建议：

- 要么从 schema 去掉 `role`
- 要么把 add-member 正式扩成支持角色设置的能力

### F-562：成员角色更新 schema 默认值是 `member`，空 PATCH 会把目标静默降成普通成员

状态：已修复（2026-04-14）

现状：

- [group.py](/D:/AssistIM_V2/server/app/schemas/group.py) 的 `GroupMemberRoleUpdate.role`
- 默认值就是 `member`
- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 PATCH 直接把 `payload.role` 传进 service

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- 空请求体或漏传 `role`
- 不会被判成非法，而会直接把目标更新成 `member`
- 这是一个非常危险的默认 side effect

建议：

- 角色更新请求应要求显式提供 `role`
- 空 PATCH 不应再退化成“默认降权”

### F-563：转让群主允许把 owner 转给自己，服务端会静默走一遍伪 no-op 成功路径

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `transfer_ownership()`
- 只校验 `new_owner_id` 是群成员
- 没有校验 `new_owner_id != current_user.id`
- action 里会先把自己改成 `member`，再改回 `owner`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- self-transfer 会被伪装成一次成功 ownership mutation
- 这会制造无意义的角色 churn 和客户端 follow-up
- 也继续模糊了“真正发生了 owner 变更”和“请求其实是 no-op”的边界

建议：

- 转让群主必须显式拒绝 self-transfer
- no-op ownership 请求不应再走正式成功路径

### F-564：群公告消息广播只按第一个收件人序列化一次，再把同一 payload 发给所有收件人

状态：已修复（2026-04-12）

修复说明：

- `_broadcast_group_announcement_message()` 已改为按每个 participant 的 viewer 视角分别调用 `MessageService.serialize_message()` 并单独 fanout
- 已补 `test_group_announcement_message_fanout_serializes_each_viewer` 覆盖每个 viewer 都拿到独立序列化 payload

原状态：已确认

现状：

- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `_broadcast_group_announcement_message()`
- 对收件人侧只调用一次 `service.serialize_message(message, recipient_ids[0])`
- 然后把同一个 payload 发给全部 `recipient_ids`

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- `serialize_message()` 里本来就带 viewer-specific 字段
- 比如 `is_self`、`is_read_by_me`、read metadata
- 现在这些字段会按“第一个收件人”的视角错误复用到其它所有收件人

建议：

- 面向多个 viewer 的消息广播不能继续共用单个 viewer 序列化结果
- 至少要按 viewer 视角重新序列化，或剥离 viewer-specific 字段

### F-565：服务端会话快照把加密文本的密文原样暴露成 `last_message` 预览

状态：已修复（2026-04-12）

修复说明：

- `SessionService._serialize_last_message_preview()` 已在 `text` 消息携带 `extra.encryption.enabled` 时返回 `[encrypted message]` formal 占位
- 已补 `test_session_service_encrypted_text_last_message_preview_uses_formal_placeholder` 覆盖密文不进入 session preview

原状态：已确认

现状：

- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `_serialize_last_message_preview()`
- 对所有非 recalled 消息都直接返回 `last_message.content`
- 没有区分这条内容是不是 E2EE 密文

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2/server/app/repositories/message_repo.py)

影响：

- 新登录、冷启动或远端刷新会话列表时
- 服务端 authoritative session snapshot 可能直接把密文当作最后一条预览下发
- 这和“E2EE 内容不应在服务端生成可读预览”的设计明显不一致

建议：

- 服务端 session snapshot 不应直接把加密文本内容当预览
- 应收口成占位文本或由客户端本地解密后再生成预览

### F-566：服务端会话快照也会把附件消息的原始 URL/内容当成 `last_message` 预览

状态：已修复（2026-04-12）

修复说明：

- `SessionService._serialize_last_message_preview()` 已对 `file/image/video/voice` 返回类型化 formal 占位，不再把 transport URL/content 当作会话预览
- 已补 `test_session_service_attachment_last_message_preview_uses_type_placeholder` 覆盖附件类型预览，并覆盖 recalled 优先级

原状态：已确认

现状：

- `_serialize_last_message_preview()` 只特判了 `recalled`
- 对 `image/file/video/voice` 等附件消息
- 也会直接返回 `last_message.content`
- 这通常就是上传 URL 或其它传输内容

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 会话列表 authoritative preview 会直接显示 URL/传输字段
- 这不是 UI 小问题，而是 session preview contract 本身没有对消息类型做语义化处理

建议：

- 服务端会话快照要为附件消息生成类型化 preview
- 不要继续把 transport content 直接当作会话预览

### F-567：好友请求正式 payload 同时接受 `receiver_id` 和 `user_id`，冲突时会静默偏向 `receiver_id`

状态：已修复（2026-04-12）

修复说明：

- `FriendRequestCreate` 已在 schema validator 中拒绝 `receiver_id` / `user_id` 冲突，并归一化出 canonical target
- 已有 group/friend schema API 回归覆盖对应 422/归一化行为

原状态：已确认

现状：

- [friend.py](/D:/AssistIM_V2/server/app/schemas/friend.py) 的 `FriendRequestCreate`
- 同时暴露了 `receiver_id` 和 `user_id`
- [friends.py](/D:/AssistIM_V2/server/app/api/v1/friends.py) 的 `send_request()`
- 直接用 `payload.receiver_id or payload.user_id`

证据：

- [D:\AssistIM_V2\server\app\schemas\friend.py](D:\AssistIM_V2/server/app/schemas/friend.py)
- [D:\AssistIM_V2\server\app\api\v1\friends.py](D:\AssistIM_V2/server/app/api/v1/friends.py)

影响：

- 如果调用方同时传了两个不同的目标
- 服务端不会报冲突，只会静默吃掉一个
- 这让好友请求正式 API 的 target contract 继续模糊

建议：

- 正式 payload 只保留一个 canonical target 字段
- 或显式拒绝 `receiver_id` / `user_id` 冲突请求

### F-568：删除好友即使本来就不存在关系，也会返回 `204` 并广播 `friendship_removed`

状态：已修复（2026-04-14）

现状：

- [friend_service.py](/D:/AssistIM_V2/server/app/services/friend_service.py) 的 `remove_friend()`
- 直接调用 repo 删除，不校验是否真的存在 friendship
- [friend_repo.py](/D:/AssistIM_V2/server/app/repositories/friend_repo.py) 的 `remove_friendship()`
- 即使一条记录都没删，也会直接 commit
- 路由仍会广播 `contact_refresh(reason=\"friendship_removed\")`

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)
- [D:\AssistIM_V2\server\app\repositories\friend_repo.py](D:\AssistIM_V2/server/app/repositories/friend_repo.py)
- [D:\AssistIM_V2\server\app\api\v1\friends.py](D:\AssistIM_V2/server/app/api/v1/friends.py)

影响：

- 删除好友的正式语义里混入了“静默 no-op 也算删除成功”
- 两端客户端还会收到一次权威 `friendship_removed` realtime
- 这会把“真的删好友”和“本来就不是好友”的状态完全混掉

建议：

- 删除好友应显式区分 not-friend 与删除成功
- 不要在 no-op 删除上继续广播正式 removal 事件

### F-569：建私聊正式 schema 只要求 `participant_ids` 至少 1 个，但服务端实际只支持“恰好一个其他参与者”

状态：已修复（2026-04-12）

修复说明：

- `CreateDirectSessionRequest.participant_ids` 已在 schema validator 中去重并要求归一化后恰好一个参与者
- 相关行为已由 direct session schema 测试或 typing API 测试覆盖

原状态：已确认

现状：

- [session.py](/D:/AssistIM_V2/server/app/schemas/session.py) 的 `CreateDirectSessionRequest.participant_ids`
- 只有 `min_length=1`
- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `_normalize_private_members()`
- 却要求最终只能留下“一个其他用户”

证据：

- [D:\AssistIM_V2\server\app\schemas\session.py](D:\AssistIM_V2/server/app/schemas/session.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- API schema 暗示私聊可带多个 participant
- 真实服务端却只支持 1:1
- 调用方只能等 service 层晚报错，正式 contract 不清晰

建议：

- 私聊创建 schema 应直接约束为“恰好一个其他参与者”

### F-570：建私聊请求 schema 没有 `extra=forbid`，未知字段会被静默忽略

状态：已修复（2026-04-12）

修复说明：

- `CreateDirectSessionRequest` 已配置 `ConfigDict(extra="forbid")`
- 相关行为已由 direct session schema 测试或 typing API 测试覆盖

原状态：已确认

现状：

- [session.py](/D:/AssistIM_V2/server/app/schemas/session.py) 的 `CreateDirectSessionRequest`
- 没有像部分其它 schema 那样显式 `extra="forbid"`

证据：

- [D:\AssistIM_V2\server\app\schemas\session.py](D:\AssistIM_V2/server/app/schemas/session.py)

影响：

- 调用方多传的字段不会被拒绝
- 只会被静默吞掉
- create-session 正式入口的 schema contract 继续模糊

建议：

- session create schema 应与其它正式入口统一 extra 策略

### F-571：HTTP typing 入口仍使用裸 `dict`，没有正式请求 schema

状态：已修复（2026-04-12；2026-04-14 被 R-005 重构移除 HTTP typing 入口）

修复说明：

- 2026-04-12 曾把 `POST /sessions/{session_id}/typing` 收口到 `SessionTypingRequest` 正式 schema
- 2026-04-14 按 `R-005` 继续重构，已删除 HTTP typing route 和 `SessionTypingRequest`
- typing 现在只保留聊天 WebSocket `typing` 正式入口，避免 HTTP/WS 双实现
- 相关行为已由 direct session schema 测试和 WS typing 边界测试覆盖

原状态：已确认

现状：

- [sessions.py](/D:/AssistIM_V2/server/app/api/v1/sessions.py) 的 `POST /sessions/{session_id}/typing`
- 直接把请求体声明成 `payload: dict`
- 没有任何专用 pydantic schema

证据：

- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2/server/app/api/v1/sessions.py)

影响：

- typing 正式入口没有清晰 payload contract
- 未知字段、错误类型、缺省值都只能在 route 里临时兜

建议：

- typing 应补正式 schema，而不是继续裸接 `dict`

### F-572：HTTP typing 会把任意非布尔 `typing` 值原样广播给其它成员

状态：已修复（2026-04-12；2026-04-14 被 R-005 重构移除 HTTP typing 入口）

修复说明：

- 2026-04-12 曾通过 `SessionTypingRequest.typing: StrictBool` 拒绝非布尔值
- 2026-04-14 按 `R-005` 继续重构，已删除 HTTP typing route 和 `SessionTypingRequest`
- typing 现在只保留聊天 WebSocket `typing` 正式入口；WS 入口继续要求 `typing` 为布尔值，否则返回 `422`
- 相关行为已由 direct session schema 测试和 WS typing 边界测试覆盖

原状态：已确认

现状：

- `typing_session()` 直接读取 `payload.get("typing", True)`
- 然后把这个值原样放进响应和 realtime payload
- 没有布尔归一化或类型校验

证据：

- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2/server/app/api/v1/sessions.py)

影响：

- 客户端完全可以发字符串、对象、数字作为 `typing`
- 服务端仍会把它当正式 typing 事件扇出
- typing control event 的 payload type 没有收口

建议：

- `typing` 应限制为正式布尔字段
- route 不要再把任意 JSON 值直接广播

### F-573：建群请求同时接受 `member_ids` 和 `members`，冲突时会静默偏向 `member_ids`

状态：已修复（2026-04-12）

修复说明：

- `GroupCreate` 已在 model validator 中拒绝 `member_ids` / `members` 冲突输入
- 已有 group/friend schema API 回归覆盖对应 422/归一化行为

原状态：已确认

现状：

- [group.py](/D:/AssistIM_V2/server/app/schemas/group.py) 的 `GroupCreate`
- 同时暴露了 `member_ids` 和 `members`
- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `create_group()`
- 直接用 `payload.member_ids or payload.members`

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- 两个字段同时出现且内容冲突时
- 服务端不会报错，只会静默吃掉其中一个
- 建群 target contract 继续模糊

建议：

- 建群正式 payload 只保留一个 canonical 成员字段
- 或显式拒绝冲突输入

### F-574：建群正式入口允许空成员列表，请求体为空时也能创建“只有自己”的群

状态：已修复（2026-04-14）

现状：

- `GroupCreate.member_ids` / `members` 都有默认空列表
- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `_normalize_group_members()`
- 会无条件把 `current_user.id` 放进成员集
- 所以空请求体最终仍会创建一个只有自己的群

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 服务端正式建群边界没有“至少还有一个其他成员”的约束
- 产品是否允许 self-only group 会变成调用方偶然行为

建议：

- 若产品不允许自建单人群，服务端应直接拒绝空成员集

### F-575：建群请求 schema 没有 `extra=forbid`，未知字段会被静默忽略

状态：已修复（2026-04-12）

修复说明：

- `GroupCreate` 已配置 `ConfigDict(extra="forbid")`
- 已有 group/friend schema API 回归覆盖对应 422/归一化行为

原状态：已确认

现状：

- [group.py](/D:/AssistIM_V2/server/app/schemas/group.py) 的 `GroupCreate`
- 没有显式 extra 限制

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)

影响：

- create-group 正式入口会静默吃掉未知字段
- API contract 继续模糊

建议：

- 建群 schema 应和其它正式入口统一 extra 策略

### F-576：加群成员请求 schema 没有 `extra=forbid`，未知字段会被静默忽略

状态：已修复（2026-04-12）

修复说明：

- `GroupMemberAdd` 已配置 `ConfigDict(extra="forbid")`
- 已有 group/friend schema API 回归覆盖对应 422/归一化行为

原状态：已确认

现状：

- [group.py](/D:/AssistIM_V2/server/app/schemas/group.py) 的 `GroupMemberAdd`
- 没有显式 extra 限制

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)

影响：

- add-member 正式入口继续接受“看似成功但字段无效”的请求

建议：

- 成员 mutation schema 应禁止未知字段

### F-577：成员角色更新请求 schema 没有 `extra=forbid`

状态：已修复（2026-04-12）

修复说明：

- `GroupMemberRoleUpdate` 已配置 `ConfigDict(extra="forbid")`
- 已有 group/friend schema API 回归覆盖对应 422/归一化行为

原状态：已确认

现状：

- [group.py](/D:/AssistIM_V2/server/app/schemas/group.py) 的 `GroupMemberRoleUpdate`
- 没有显式 extra 限制

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)

影响：

- role PATCH 仍会静默忽略未知字段
- 正式 mutation contract 不够严格

建议：

- 角色更新 schema 应禁止未知字段

### F-578：转让群主请求 schema 没有 `extra=forbid`

状态：已修复（2026-04-12）

修复说明：

- `GroupTransferOwner` 已配置 `ConfigDict(extra="forbid")`
- 已有 group/friend schema API 回归覆盖对应 422/归一化行为

原状态：已确认

现状：

- [group.py](/D:/AssistIM_V2/server/app/schemas/group.py) 的 `GroupTransferOwner`
- 没有显式 extra 限制

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)

影响：

- transfer-owner 正式入口仍会静默吞掉未知字段

建议：

- ownership mutation schema 应禁止未知字段

### F-579：共享群资料 PATCH schema 没有 `extra=forbid`

状态：已修复（2026-04-12）

修复说明：

- `GroupProfileUpdate` 已配置 `ConfigDict(extra="forbid")`
- 已有 group/friend schema API 回归覆盖对应 422/归一化行为

原状态：已确认

现状：

- [group.py](/D:/AssistIM_V2/server/app/schemas/group.py) 的 `GroupProfileUpdate`
- 没有显式 extra 限制

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)

影响：

- 共享 group profile PATCH 继续静默吞掉未知字段
- 与真实共享资料 contract 不一致

建议：

- shared profile schema 应禁止未知字段

### F-580：self-scoped 群资料 PATCH schema 也没有 `extra=forbid`

状态：已修复（2026-04-12）

修复说明：

- `GroupSelfProfileUpdate` 已配置 `ConfigDict(extra="forbid")`
- 已有 group/friend schema API 回归覆盖对应 422/归一化行为

原状态：已确认

现状：

- [group.py](/D:/AssistIM_V2/server/app/schemas/group.py) 的 `GroupSelfProfileUpdate`
- 同样没有显式 extra 限制

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)

影响：

- self-profile PATCH 继续静默接受未知字段
- self-scoped contract 不清晰

建议：

- self-profile schema 也应统一 extra 策略

### F-581：好友请求 schema 没有 `extra=forbid`，未知字段会被静默忽略

状态：已修复（2026-04-12）

修复说明：

- `FriendRequestCreate` 已配置 `ConfigDict(extra="forbid")`
- 已有 group/friend schema API 回归覆盖对应 422/归一化行为

原状态：已确认

现状：

- [friend.py](/D:/AssistIM_V2/server/app/schemas/friend.py) 的 `FriendRequestCreate`
- 没有显式 extra 限制

证据：

- [D:\AssistIM_V2\server\app\schemas\friend.py](D:\AssistIM_V2/server/app/schemas/friend.py)

影响：

- friend request 正式入口仍会静默吞掉未知字段
- payload contract 继续模糊

建议：

- 好友请求 schema 应禁止未知字段

### F-582：好友请求 schema 在入口层允许完全空 body，缺失 target 只会晚到 service 层报错

状态：已修复（2026-04-12）

修复说明：

- `FriendRequestCreate` 已在 schema validator 中要求 `receiver_id` 或 `user_id` 至少一项存在
- 已有 group/friend schema API 回归覆盖对应 422/归一化行为

原状态：已确认

现状：

- `FriendRequestCreate.receiver_id` / `user_id` 都是可空
- schema 层不要求至少提供一个 target
- 真正的 `receiver_id is required` 校验在 [friend_service.py](/D:/AssistIM_V2/server/app/services/friend_service.py) 里

证据：

- [D:\AssistIM_V2\server\app\schemas\friend.py](D:\AssistIM_V2/server/app/schemas/friend.py)
- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)

影响：

- 正式 API schema 不能在入口层表达“目标用户必填”
- 空 body 会走到 service 才失败

建议：

- 好友请求 target 应在 schema 层就被建模成必填

### F-583：本地搜索返回的 `highlight_ranges` 仍是原文坐标，但 `matched_text` 已经被裁成 snippet

状态：已修复（2026-04-14）

现状：

- [search_manager.py](/D:/AssistIM_V2/client/managers/search_manager.py) 的 `_build_highlight_payload()`
- 先在完整原文上算出 `ranges`
- 然后把 `matched_text` 裁成前后各 20 字符的 snippet，还会加 `...`
- 但返回的 `highlight_ranges` 没有按 snippet 重新偏移

证据：

- [D:\AssistIM_V2\client\managers\search_manager.py](D:\AssistIM_V2/client/managers/search_manager.py)

影响：

- 这套 metadata 即使以后被 UI 正式消费
- 也会指向 snippet 之外的坐标
- manager 提供的高亮 contract 本身就是失真的

建议：

- snippet 一旦裁剪，就必须重算相对范围
- 否则不要继续输出这套 ranges

### F-584：建私聊接口接受 `name`，但命中已有 direct session 时会静默忽略这个名称

状态：已修复（2026-04-14）

现状：

- [session.py](/D:/AssistIM_V2/server/app/schemas/session.py) 的 `CreateDirectSessionRequest` 暴露了 `name`
- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `create_private()`
- 如果 direct session 已存在，会直接返回 existing session
- 完全不处理新请求里提供的 `name`

证据：

- [D:\AssistIM_V2\server\app\schemas\session.py](D:\AssistIM_V2/server/app/schemas/session.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- API contract 暗示创建私聊时可带名字
- 但在“命中已有私聊”这条正式路径上，这个字段会被静默忽略
- 调用方无法区分“名字被接受”还是“只是返回了已有对象”

建议：

- 要么把 direct create 的 `name` 从正式 contract 去掉
- 要么在复用已有会话时返回明确的 no-op / ignored 语义

### F-585：好友请求的 `message` 在正式入口层没有任何长度约束

状态：已修复（2026-04-12）

修复说明：

- `FriendRequestCreate.message` 已添加 `max_length=500`，并补充超长 message 的 422 回归
- 已有 group/friend schema API 回归覆盖对应 422/归一化行为

原状态：已确认

现状：

- [friend.py](/D:/AssistIM_V2/server/app/schemas/friend.py) 的 `FriendRequestCreate.message`
- 没有 `max_length`
- [user.py](/D:/AssistIM_V2/server/app/models/user.py) 里的 `FriendRequest.message` 也是 `Text`

证据：

- [D:\AssistIM_V2\server\app\schemas\friend.py](D:\AssistIM_V2/server/app/schemas/friend.py)
- [D:\AssistIM_V2\server\app\models\user.py](D:\AssistIM_V2/server/app/models/user.py)

影响：

- 好友请求附言大小没有正式入口约束
- 联系人正式入口继续允许超大 payload 直接进入持久化链路

建议：

- friend request message 应在 schema 层收口长度上限

### F-586：`GET /friends/requests` 会在读路径里直接修改请求状态

状态：已修复（2026-04-14）

现状：

- [friend_service.py](/D:/AssistIM_V2/server/app/services/friend_service.py) 的 `list_requests()`
- 会对每条请求执行 `_expire_if_needed()`
- `_expire_if_needed()` 命中过期条件时会直接 `update_request_status(request, "expired")`

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)
- [D:\AssistIM_V2\server\app\repositories\friend_repo.py](D:\AssistIM_V2/server/app/repositories/friend_repo.py)

影响：

- 单纯的列表读取会变成持久化写操作
- 联系人域把“展示请求列表”和“推进请求状态”混成了一条链路

建议：

- request 过期应走明确的领域动作或后台收口
- 不应在 GET list 上顺手改库

### F-587：读路径里发生的好友请求过期不会产生任何 `contact_refresh`

状态：已修复（2026-04-14）

现状：

- `list_requests()` 里的 `_expire_if_needed()`
- 可能把 `pending` 请求直接改成 `expired`
- 但 [friends.py](/D:/AssistIM_V2/server/app/api/v1/friends.py) 只有 create/accept/reject/remove 的显式动作才会广播 `contact_refresh`

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)
- [D:\AssistIM_V2\server\app\api\v1\friends.py](D:\AssistIM_V2/server/app/api/v1/friends.py)

影响：

- 一台设备读请求列表时可把请求改成 `expired`
- 但其它在线设备和联系人页实时状态不会同步收口

建议：

- request expiry 如果继续保留为在线写动作
- 就必须进入正式 realtime / refresh contract

### F-588：自动接受好友请求不是 failure-atomic 的

状态：已修复（2026-04-14）

现状：

- [friend_service.py](/D:/AssistIM_V2/server/app/services/friend_service.py) 的 `create_request()`
- 命中对向 pending request 时，会先 `update_request_status(..., "accepted")`
- 然后再 `create_friendship_pair(...)`
- 两步都通过 repo 自己 `commit()`

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)
- [D:\AssistIM_V2\server\app\repositories\friend_repo.py](D:\AssistIM_V2/server/app/repositories/friend_repo.py)

影响：

- 如果 friendship 创建阶段失败
- request 状态可能已经变成 `accepted`
- 联系人关系却还没真正建立

建议：

- 自动接受应放进一个单事务领域动作
- 不要把 request 状态更新和 friendship 建立拆成两个 repo 级提交

### F-589：手动接受好友请求也不是 failure-atomic 的

状态：已修复（2026-04-14）

现状：

- [friend_service.py](/D:/AssistIM_V2/server/app/services/friend_service.py) 的 `accept_request()`
- 先 `update_request_status(request, "accepted")`
- 再 `create_friendship_pair(...)`
- 仍然是两次独立 `commit()`

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)
- [D:\AssistIM_V2\server\app\repositories\friend_repo.py](D:\AssistIM_V2/server/app/repositories/friend_repo.py)

影响：

- 手动 accept 同样可能留下“请求已接受、好友关系未建成”的半提交状态

建议：

- accept request 应与 friendship creation 共用一个事务边界

### R-077：联系人域请求状态仍依赖多个 repo 级 `commit()` 拼接，没有统一事务边界

状态：已修复（2026-04-14）

现状：

- `create_request()/accept_request()/reject_request()/list_requests()` 都会通过 repo 直接提交
- 过期、自接受、手动接受、关系建立分散在多条提交链上

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)
- [D:\AssistIM_V2\server\app\repositories\friend_repo.py](D:\AssistIM_V2/server/app/repositories/friend_repo.py)

影响：

- 联系人请求域缺少清晰的 authoritative mutation boundary
- 同一业务动作容易留下半状态并且难以配套 realtime 收口

建议：

- friend request 域应收敛到 service-level transaction，而不是 repo-level 自提交

### F-590：消息 mention 只校验文本片段，不校验 `member_id` 是否属于当前会话

状态：已修复（2026-04-12）

修复说明：

- `MessageService._normalize_message_extra()` 已在 text mention 正规化时加载当前 session member 集
- `_normalize_mentions()` 已拒绝 `member_id` 不属于当前会话的 member mention，返回 422
- 已补 `test_member_mentions_require_session_members_and_non_overlapping_spans` 覆盖伪造成员 mention

原状态：已确认

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `_normalize_mentions()`
- 对 `member` mention 只要求 `member_id` 非空
- 后续没有任何一步把它和当前 session member 集做 authoritative 校验

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 客户端可以在正式消息里伪造“提到了非会话成员”的 mention payload
- mention contract 仍然停留在“文本长得像”而不是“目标成员真实存在”

建议：

- member mention 应绑定当前会话成员集做正式校验

### F-591：消息 mention 没有收口成一套无重叠的 canonical span contract

状态：已修复（2026-04-12）

修复说明：

- `_normalize_mentions()` 已对归一化后的 mention span 按 `start/end` 排序，并拒绝重复或重叠区间，返回 422
- 已补 `test_member_mentions_require_session_members_and_non_overlapping_spans` 覆盖重复 span 冲突

原状态：已确认

现状：

- `_normalize_mentions()` 会收集所有看起来合法的 mention span
- 但不会拒绝重叠范围
- 也不会拒绝同一位置的重复或互相覆盖的 mention item

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- mention payload 仍可能包含互相冲突的 span 集
- 下游高亮、通知、@成员逻辑拿不到一份 authoritative mention 结果

建议：

- mention spans 应在服务端正规范化为无重叠、单一解释的集合

### F-592：消息创建 schema 没有任何内容长度上限

状态：已修复（2026-04-12）

修复说明：

- `MessageCreate.content` 已使用 `Field(min_length=1, max_length=MAX_MESSAGE_CONTENT_LENGTH)`，并保留非空白 validator
- 已有 HTTP 创建消息超长 content 的 422 回归覆盖

原状态：已确认

现状：

- [message.py](/D:/AssistIM_V2/server/app/schemas/message.py) 的 `MessageCreate.content`
- 是裸 `str`
- 没有 `max_length`

证据：

- [D:\AssistIM_V2\server\app\schemas\message.py](D:\AssistIM_V2/server/app/schemas/message.py)

影响：

- 正式消息发送入口没有 schema 级 payload 大小约束
- 超大文本只能一路走到更晚层才暴露问题

建议：

- message create 应补正式内容长度边界

### F-593：消息编辑 schema 同样没有内容长度上限

状态：已修复（2026-04-12）

修复说明：

- `MessageUpdate.content` 已使用 `Field(min_length=1, max_length=MAX_MESSAGE_CONTENT_LENGTH)`，并保留非空白 validator
- 已有 HTTP 编辑消息超长 content 的 422 回归覆盖

原状态：已确认

现状：

- [message.py](/D:/AssistIM_V2/server/app/schemas/message.py) 的 `MessageUpdate.content`
- 也是裸 `str`
- 没有 `max_length`

证据：

- [D:\AssistIM_V2\server\app\schemas\message.py](D:\AssistIM_V2/server/app/schemas/message.py)

影响：

- 正式 edit 入口也没有 schema 级内容大小约束
- create / edit 两条正式边界的 payload size contract 都没收口

建议：

- message update 也应补正式长度限制

### R-078：缺失消息同步查询按 session 数量线性膨胀 `OR` 条件

状态：已修复（2026-04-14）

现状：

- [message_repo.py](/D:/AssistIM_V2/server/app/repositories/message_repo.py) 的 `list_missing_messages_for_user()`
- 会先取出该用户全部 `session_id`
- 然后为每个 session 构造一个 `Message.session_id == ... AND session_seq > cursor` 的 `OR` 条件

证据：

- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2/server/app/repositories/message_repo.py)

影响：

- reconnect/sync 的消息补偿查询会随会话数线性放大 SQL 条件规模
- 会话多时，这条基础补偿查询会继续退化

建议：

- 缺失消息同步应改成 join/partition 友好的批量查询模型

### R-079：缺失事件同步查询同时为 shared/private 两套事件表构造线性膨胀条件

状态：已修复（2026-04-14）

现状：

- [message_repo.py](/D:/AssistIM_V2/server/app/repositories/message_repo.py) 的 `list_missing_events_for_user()`
- 对 shared `SessionEvent` 和 private `UserSessionEvent`
- 都会按每个 session 构造一组 `OR` 条件

证据：

- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2/server/app/repositories/message_repo.py)

影响：

- event 补偿查询会比消息补偿更快放大
- shared/private 双表同步成本都被会话数直接拖高

建议：

- event sync 也应改成按用户可见 session 的批量化查询路径

### F-594：`CallManager._handle_invite()` 会无条件覆盖当前 `_active_call`

状态：已修复（2026-04-14）

现状：

- [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 的 `_handle_invite()`
- 收到任意 `call_invite`
- 就直接 `self._active_call = ActiveCallState.from_payload(...)`
- 不检查当前是否已经有另一通进行中的 call

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- 晚到或并发的 invite 可以直接覆盖本地当前通话状态
- 单槽 `_active_call` 仍没有最基本的 invite-side guard

建议：

- invite 处理必须绑定 current call slot 和 call_id / state guard

### F-595：通话发送入口允许对任意 `call_id` 直接发 accept/reject/hangup/signal

状态：已修复（2026-04-14）

现状：

- `accept_call()/reject_call()/hangup_call()/send_offer()/send_answer()/send_ice_candidate()`
- 都只校验 `call_id` 非空
- 不校验它是否就是当前 `_active_call.call_id`

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)

影响：

- 本地旧窗口、旧任务或错误调用都能继续向外发任意 call control
- call control 入口没有 current-call authoritative guard

建议：

- outbound call actions 应严格绑定当前 active call 和允许阶段

### F-596：`CallRegistry.get_for_user()` 不校验映射到的 call 是否真的包含该用户

状态：已修复（2026-04-14）

现状：

- [call_registry.py](/D:/AssistIM_V2/server/app/realtime/call_registry.py) 的 `get_for_user()`
- 先通过 `_call_id_by_user_id[user_id]` 找 call_id
- 再从 `_calls[call_id]` 直接返回 call
- 但不会检查 `call.includes_user(user_id)`

证据：

- [D:\AssistIM_V2\server\app\realtime\call_registry.py](D:\AssistIM_V2/server/app/realtime/call_registry.py)

影响：

- 一旦 user->call 映射残留或 call_id 被覆盖
- `get_for_user()` 就可能把别人的当前通话错报成该用户的 active call

建议：

- `get_for_user()` 至少应校验 returned call 真实包含该用户

### F-597：`CallRegistry.create()` 没有 `call_id` 冲突保护，会直接覆盖现有 `_calls` 槽位

状态：已修复（2026-04-14）

现状：

- `create()` 直接执行 `self._calls[call_id] = active_call`
- 没有检查这个 `call_id` 是否已被别的 active call 占用

证据：

- [D:\AssistIM_V2\server\app\realtime\call_registry.py](D:\AssistIM_V2/server/app/realtime/call_registry.py)

影响：

- 复用同一个 `call_id` 时，旧 call 记录会被新 call 直接覆盖
- registry 的 call lookup 和 user busy lookup 会一起被污染

建议：

- registry create 应显式拒绝 active `call_id` 冲突

### F-598：发送好友请求的 preflight 会在“发送新请求”前顺手修改旧请求状态

状态：已修复（2026-04-14）

现状：

- [friend_service.py](/D:/AssistIM_V2/server/app/services/friend_service.py) 的 `create_request()`
- 会先 `_list_pair_requests(...)`
- `_list_pair_requests()` 又会对每条结果执行 `_expire_if_needed()`
- 于是一次“发送请求”会先把历史 pair request 里的 pending 直接改成 expired

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)
- [D:\AssistIM_V2\server\app\repositories\friend_repo.py](D:\AssistIM_V2/server/app/repositories/friend_repo.py)

影响：

- create request 入口混入了历史请求维护写操作
- 同一个动作同时承担“清理旧状态”和“创建新状态”，边界继续模糊

建议：

- 旧请求过期和新请求创建应拆成明确的领域边界

### F-599：群访问鉴权只看 `SessionMember`，不看 `GroupMember`

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `_ensure_group_member()`
- 只检查 `sessions.has_member(group.session_id, user_id)`
- 不检查 `groups.get_member(group.id, user_id)`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 只要 session/group 两张成员表发生漂移
- session 侧成员就仍可通过群鉴权并拿到 group payload

建议：

- 群访问应以 `GroupMember` 为准，或至少同时校验两侧一致性

### F-600：群序列化会为缺失 `GroupMember` 记录的 session 成员伪造默认角色

状态：已修复（2026-04-14）

现状：

- `serialize_group()` 里的 `members[]`
- 对 role 的回退逻辑是：
- 缺失 `GroupMember` 时，owner 用 `owner`，其他人一律回退成 `member`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- authoritative group payload 会把“群成员表缺失”的数据漂移静默伪装成合法成员
- drift 被掩盖后更难在上层及时暴露

建议：

- 群成员序列化不应静默编造 role
- 应显式暴露或修复 session/group membership drift

### F-601：群快照里的 `member_count` 也是按 `SessionMember` 算，不按 `GroupMember` 算

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `serialize_group()`
- `member_count = len(session_members)`
- 完全不参考 `group_members`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 只要 session/group 成员表出现漂移
- 群详情里的成员数量就会继续被 `SessionMember` 主导
- authoritative group snapshot 仍无法真实反映 group membership

建议：

- group snapshot 的人数与成员列表应收口到同一份群成员真相


### R-073：好友列表接口存在稳定的 N+1 用户查询

状态：已修复（2026-04-14）

修复说明：

- `FriendService.list_friends()` 已改成 `list_friends() + list_users_by_ids()` 的 bulk 路径，不再逐条 `get_by_id()`。

现状：

- [friend_service.py](/D:/AssistIM_V2/server/app/services/friend_service.py) 的 `list_friends()`
- 先 `list_friends(current_user.id)` 拿 friendship
- 然后对每条 friendship 再单独 `users.get_by_id(...)`

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)

影响：

- 好友数一大，列表接口会稳定退化成 N+1 查询
- 联系人主列表的基础加载性能没有收口

建议：

- 朋友列表应改成批量取 user profile，而不是逐条 `get_by_id`

### R-074：好友请求列表序列化存在稳定的 `2N` 用户查询

状态：已修复（2026-04-14）

修复说明：

- requests 列表序列化已改成一次批量拉取 sender/receiver user map，再逐条序列化。

现状：

- `list_requests()` 会遍历请求后逐条 `serialize_request()`
- `serialize_request()` 对每条请求都会单独查 `sender` 和 `receiver`

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)

影响：

- requests 列表会稳定退化成按请求数线性放大的用户查表
- 联系人域的基础加载性能继续依赖小数据量

建议：

- 请求列表也应批量拉取 sender/receiver profile

### R-075：群列表接口的序列化路径仍是明显的 N+1 成员/用户查询

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `list_groups()`
- 会对每个群都调用 `serialize_group()`
- `serialize_group()` 里又会继续 `sessions.list_members()`、`groups.list_members()`、`users.list_users_by_ids()`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 群列表越大，群成员与用户资料查询越呈现 N+1 放大
- 这条主列表接口还没进入成熟的批量加载形态

建议：

- 群列表应补 bulk member / bulk user / bulk avatar 路径

### R-076：会话列表在 group session 分支上仍保留 per-session 群资料查询

状态：closed（2026-04-14）

修复记录：

- [group_repo.py](/D:/AssistIM_V2/server/app/repositories/group_repo.py) 已补 `list_by_session_ids()` 和 `list_members_for_groups()`
- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `list_sessions()` 现在会先批量取 group/group-members，再把结果传给 `serialize_session(...)`

现状：

- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `list_sessions()`
- 虽然 session members 和 last messages 已经先做了 bulk 查询
- 但 `serialize_session()` 遇到 group session 仍会逐个 `groups.get_by_session_id()`、`groups.list_members()`、`avatars.ensure_group_avatar()`

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 会话列表的 group 分支仍带着明显的 per-session 扩散查询
- 群聊一多，session list 的序列化成本会继续放大

建议：

- 会话列表也应把 group 相关元数据批量化
- 不要在 serialize path 里继续逐会话回查 group state

### F-602：`/users/search` 会向任意已认证用户暴露完整私密资料字段

状态：已修复（2026-04-14）

修复说明：

- `/users/search` 已收口到 public summary，只返回 `id/username/nickname/display_name/avatar/avatar_kind/gender`。

现状：

- [users.py](/D:/AssistIM_V2/server/app/api/v1/users.py) 的 `GET /users/search`
- 直接返回 [user_service.py](/D:/AssistIM_V2/server/app/services/user_service.py) 的 `search_users()`
- 而 `search_users()` 会把命中用户全部走 `serialize_user()`
- `serialize_user()` 包含 `email/phone/birthday/region/signature/status`

证据：

- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2/server/app/api/v1/users.py)
- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)

影响：

- Add Friend / 用户搜索正式入口没有 public profile projection
- 任意已认证用户都能通过搜索拿到他人的私密资料字段

建议：

- 用户搜索应收口到 public user summary
- 不应复用 `serialize_user()` 这种完整 profile 输出

### F-603：`/users` 会向任意已认证用户暴露完整用户目录和私密资料

状态：已修复（2026-04-14）

修复说明：

- `/users` 已分页并统一返回 public summary contract，不再暴露 email/phone/birthday/region/signature/status。

现状：

- [users.py](/D:/AssistIM_V2/server/app/api/v1/users.py) 的 `GET /users`
- 直接返回 `UserService.list_users()`
- `list_users()` 同样复用 `serialize_user()`

证据：

- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2/server/app/api/v1/users.py)
- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)

影响：

- 任何已认证用户都能直接枚举完整用户目录
- 还会一起拿到 email/phone/birthday/region/signature 等私密字段

建议：

- `/users` 要么删掉用户侧正式入口
- 要么收口到分页后的 public summary contract

### F-604：`/users/{user_id}` 也会向普通用户返回完整私密 profile

状态：已修复（2026-04-14）

修复说明：

- `GET /users/{id}` 已收口到 public summary；完整 self profile 仍只保留在 `/auth/me`。

现状：

- [users.py](/D:/AssistIM_V2/server/app/api/v1/users.py) 的 `GET /users/{user_id}`
- 也直接返回 `UserService.get_user() -> serialize_user()`

证据：

- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2/server/app/api/v1/users.py)
- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)

影响：

- 任意用户详情查询都没有 public/private projection 边界
- 普通联系人展示、请求补名、搜索补全都在使用完整 profile 输出

建议：

- `GET /users/{id}` 也应区分 public summary 与 self profile

### F-605：`/users/search` 的空关键词会直接退化成全量用户枚举

状态：已修复（2026-04-14）

修复说明：

- `/users/search` 入口现在会拒绝空白关键词，空查询不再退化成目录枚举。

现状：

- `keyword` 在 [users.py](/D:/AssistIM_V2/server/app/api/v1/users.py) 里默认就是空字符串
- [user_repo.py](/D:/AssistIM_V2/server/app/repositories/user_repo.py) 的 `search_users()`
- 会把 keyword 直接拼成 `pattern = f"%{keyword}%"`
- 空字符串时就是 `%%`

证据：

- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2/server/app/api/v1/users.py)
- [D:\AssistIM_V2\server\app\repositories\user_repo.py](D:\AssistIM_V2/server/app/repositories/user_repo.py)

影响：

- `/users/search` 和 `/users` 的语义进一步重叠
- 搜索正式入口自己就能被拿来做目录枚举

建议：

- 空关键词应被入口层拒绝
- 或至少收口成 no-op / empty result

### F-606：用户搜索正式入口会按 `email/phone` 命中，而 UI 和文案只承诺 `username/nickname`

状态：已修复（2026-04-14）

修复说明：

- `UserRepository.search_users()` 已删除 `email/phone` 匹配，只保留 `username/nickname`。

现状：

- [user_repo.py](/D:/AssistIM_V2/server/app/repositories/user_repo.py) 的 `search_users()`
- 搜索条件包含 `email.ilike()` 和 `phone.ilike()`
- 但 [contact_interface.py](/D:/AssistIM_V2/client/ui/windows/contact_interface.py) 的 Add Friend 文案只写“Search username or nickname”

证据：

- [D:\AssistIM_V2\server\app\repositories\user_repo.py](D:\AssistIM_V2/server/app/repositories/user_repo.py)
- [D:\AssistIM_V2\client\ui\windows\contact_interface.py](D:\AssistIM_V2/client/ui/windows/contact_interface.py)

影响：

- 用户发现面比产品语义更宽
- 私密联系字段被悄悄纳入公共搜索入口

建议：

- user search 的正式匹配字段应与产品语义一致

### F-607：`PUT /users/me` 允许空 body，并且空更新也会广播 `user_profile_update`

状态：已修复（2026-04-14）

现状：

- [user.py](/D:/AssistIM_V2/server/app/schemas/user.py) 的 `UserUpdateRequest` 全部字段可选
- [users.py](/D:/AssistIM_V2/server/app/api/v1/users.py) 的 `update_me()`
- 空 payload 也会执行 `UserService.update_me(...)`
- 随后无条件调用 `_broadcast_profile_update_events(...)`

证据：

- [D:\AssistIM_V2\server\app\schemas\user.py](D:\AssistIM_V2/server/app/schemas/user.py)
- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2/server/app/api/v1/users.py)

影响：

- no-op profile PATCH 仍会产生活跃 realtime/event side effect
- user profile 正式 mutation boundary没有收口

建议：

- 空 PATCH 应在入口或 service 层被识别为 no-op
- 不应继续广播 profile update

### F-608：用户读取接口会在读路径里直接改写 avatar 状态

状态：已修复（2026-04-14）

现状：

- `list_users()/get_user()/search_users()` 都会在序列化前调用 `AvatarService.backfill_user_avatar_state()`
- `backfill_user_avatar_state()` 内部会直接 `users.update_avatar_state(...)`
- 也就是 GET/search 读取会顺手改库

证据：

- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)
- [D:\AssistIM_V2\server\app\repositories\user_repo.py](D:\AssistIM_V2/server/app/repositories/user_repo.py)

影响：

- 用户目录读取和用户状态迁移被混成一条链
- 普通读请求也会带持久化 side effect

建议：

- avatar compat/backfill 应从 read path 拆出去

### R-080：用户目录读取存在按返回行数放大的写放大风险

状态：已修复（2026-04-14）

修复说明：

- `serialize_public_user()` 已退出 `backfill_user_avatar_state()` 写路径，`/users` 与 `/users/search` 不再按返回行数放大写库。

现状：

- 每个命中的 user 都可能在 `backfill_user_avatar_state()` 里触发一次 `update_avatar_state()`
- `list_users()` 和 `search_users()` 返回多少行，就可能触发多少次写

证据：

- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- 本来只读的目录/搜索请求会被放大成批量写
- 数据量一大，用户目录读取的成本和行为都会变形

建议：

- compat 修复不应继续绑定在 user list/search read path 上

### F-609：不只是 user API，好友/会话/消息读路径也会在序列化时改写 avatar 状态

状态：已修复（2026-04-14）

现状：

- `FriendService.list_friends()/serialize_request()`
- `SessionService.serialize_session()`
- `MessageService.serialize_message()`
- 都会调用 `backfill_user_avatar_state()`

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- avatar compat 迁移不是局部问题，而是扩散到了多个正式读链路
- 任何好友/会话/消息读取都可能顺手改用户表

建议：

- avatar state 修复应退出各类 read/serialize path

### R-081：avatar 状态迁移没有单一 compat 边界，而是分散在多个运行时读路径

状态：已修复（2026-04-14）

修复说明：

- avatar compat 已从 user/friend/session/message 正式读路径移除，运行时只解析已有 avatar state，不再在读链路里隐式迁移。

现状：

- 仓库里已经有 [schema_compat.py](/D:/AssistIM_V2/server/app/core/schema_compat.py) 的 backfill 机制
- 但 `backfill_user_avatar_state()` 仍被散落调用在多条运行时服务读路径里

证据：

- [D:\AssistIM_V2\server\app\core\schema_compat.py](D:\AssistIM_V2/server/app/core/schema_compat.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- 兼容迁移和正式业务读取边界继续混在一起
- 迁移何时完成、是否可关闭，都没有单一收口点

建议：

- compat/backfill 应收口到 schema/data migration，不应长期散落在 read path

### F-610：`record_profile_update_events()` 对每个 session 都会单独回查成员列表

状态：已修复（2026-04-14）

现状：

- [user_service.py](/D:/AssistIM_V2/server/app/services/user_service.py) 的 `record_profile_update_events()`
- 先 `list_user_sessions(updated_user.id)`
- 然后在循环里对每个 session 再 `sessions.list_member_ids(session.id)`

证据：

- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)

影响：

- 一次 profile update 的 event 构造成本会随 session 数量线性放大
- user profile 正式 fanout 仍是明显的 N+1

建议：

- profile update event generation 应补 bulk member lookup

### R-082：用户资料更新事件会按 session 数量线性复制同一份 profile payload

状态：已修复（2026-04-14）

修复说明：

- `record_profile_update_events()` 已补 no-op 抑制和 bulk member lookup，profile update 不再在无变化时广播，也不再按 session 做 N+1 成员回查。

现状：

- `record_profile_update_events()` 会为用户参与的每个 session 都 append 一条 event
- 每条 event 里都重复携带同一份 `profile` payload

证据：

- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)

影响：

- profile update fanout 和离线事件存储都会按 session 数量成倍重复
- 用户参与会话越多，这条基础资料更新链越重

建议：

- 资料更新事件应重新审视 payload 重复和 fanout shape

### F-611：`/users` 正式入口没有分页或 size 限制

状态：已修复（2026-04-14）

现状：

- [users.py](/D:/AssistIM_V2/server/app/api/v1/users.py) 的 `GET /users`
- 直接调用 `list_users()`
- 没有 `page/size` 等任何分页参数

证据：

- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2/server/app/api/v1/users.py)
- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)

影响：

- 用户目录正式入口会随总用户数线性膨胀
- 读取成本和暴露面都没有边界

建议：

- `/users` 如保留，至少应分页且收口到 public summary

### F-612：联系人缓存会把完整好友 payload 原样塞进本地 `extra`

状态：已修复（2026-04-14）

修复说明：

- contacts cache 落盘已改成最小搜索摘要，只保留 `id/display_name/username/nickname/avatar/gender/status/profile_event_id`。

现状：

- [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `load_contacts()`
- `ContactRecord.extra = dict(item or {})`
- 后续 `_persist_contacts_cache()` 会把这份 `extra` 整体落入 [database.py](/D:/AssistIM_V2/client/storage/database.py) 的 `contacts_cache.extra`

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\storage\database.py](D:\AssistIM_V2/client/storage/database.py)

影响：

- 朋友列表返回的 email/phone/birthday 等完整字段会被一起落到本地联系人缓存
- contacts_cache 不再只是搜索摘要，而是变成完整资料镜像

建议：

- 本地 contacts cache 应只保存搜索/展示真正需要的最小字段

### F-613：好友请求补名会拉完整 `/users/{id}` profile，只为取一个显示名

状态：已修复（2026-04-14）

修复说明：

- requests 列表不再为补名调用 `/users/{id}`，客户端直接消费服务端返回的请求方/接收方 public summary。

现状：

- [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `_load_request_user_names()`
- 对缺名字的请求会逐个 `user_service.fetch_user(user_id)`
- 然后只取 `nickname/username` 作为显示名

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)
- [D:\AssistIM_V2\client\services\user_service.py](D:\AssistIM_V2/client/services/user_service.py)

影响：

- 为了请求列表补一个名字，客户端会拉完整用户资料
- 这条链同时放大了网络负载和资料暴露面

建议：

- 请求补名应改成 public summary / bulk summary 接口

### R-083：好友请求补名会对所有缺名用户做无上限并发 `fetch_user`

状态：已修复（2026-04-14）

修复说明：

- `_load_request_user_names()` 与对应并发 `fetch_user` fan-out 已删除。

现状：

- `_load_request_user_names()` 直接 `asyncio.gather(*(_fetch_name(user_id) ...))`
- 没有批量接口，也没有并发上限

证据：

- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)

影响：

- requests 一多，就会同时打出一批用户详情请求
- 联系人页的基础 reload 继续受无上限并发影响

建议：

- 请求补名应改为 bulk summary 或至少加并发上限

### F-614：普通资料编辑不会刷新依赖成员头像/昵称的 generated group avatar

状态：已修复（2026-04-14）

现状：

- generated group avatar 的构图来自 [avatar_service.py](/D:/AssistIM_V2/server/app/services/avatar_service.py) 的 `_group_member_avatar_payload()`
- 其中使用了成员的 `nickname/username/avatar/gender`
- 但 [user_service.py](/D:/AssistIM_V2/server/app/services/user_service.py) 的 `update_me()`
- 只更新用户并广播 `user_profile_update`
- 不会像 avatar upload/reset 那样调用 `_refresh_generated_group_avatars_for_user()`

证据：

- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)
- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)
- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2/server/app/api/v1/users.py)

影响：

- 成员昵称/性别等资料变化后，generated group avatar 会继续停留在旧构图
- user profile 和 group avatar 两条正式视图继续分裂

建议：

- 影响 generated group avatar 的用户资料变更应同步刷新 group avatar

### F-615：头像上传/重置虽然会刷新 generated group avatar，但不会广播 `group_profile_update`

状态：已修复（2026-04-14）

现状：

- [avatar_service.py](/D:/AssistIM_V2/server/app/services/avatar_service.py) 的 `upload_user_avatar()/reset_user_avatar()`
- 都会调用 `_refresh_generated_group_avatars_for_user()`
- 该方法会更新 group avatar 和 session avatar 并 `commit()`
- 但 [users.py](/D:/AssistIM_V2/server/app/api/v1/users.py) 在上传/重置头像后只广播 `user_profile_update`
- 不会给受影响的群补 `group_profile_update`

证据：

- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)
- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2/server/app/api/v1/users.py)

影响：

- 数据库里的 group/session avatar 已更新
- 但群侧 realtime 和离线事件模型并没有配套收口
- 其它成员客户端不会及时看到新的群头像

建议：

- 由用户头像变化触发的群头像刷新也应进入正式 group update 事件模型

### F-616：`backfill_user_avatar_state()` 会在读路径里把“缺文件的 custom avatar”重写成别的正式状态

状态：已修复（2026-04-15）

现状：

- `backfill_user_avatar_state()` 先看 `avatar_kind == custom and avatar_file_id`
- 如果文件查不到，就继续往下走默认头像推断 / custom URL / assign default 分支
- 也就是一次普通读取就可能把用户原本的 custom avatar 状态重写成 default 或别的 custom state

证据：

- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- read path 不只是“补字段”，而是在做破坏性状态纠偏
- 一次普通用户读取就可能永久改变用户头像语义

建议：

- 这类状态修复应显式迁移或后台修复，不应继续在 read path 自动改写

### R-084：头像上传/重置会同步重建该用户参与的所有 generated group avatar

状态：已修复（2026-04-14）

现状：

- `_refresh_generated_group_avatars_for_user()` 会遍历 `groups.list_user_groups(user_id)`
- 对每个 generated group 都 `bump_group_avatar_version()` + `ensure_group_avatar()`
- 最后统一 `commit()`

证据：

- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- 一个用户头像变更的成本会随其参与群数量线性放大
- profile mutation 正式路径里继续夹着重型 group-avatar rebuild

建议：

- generated group avatar 刷新应考虑异步化或增量化
- 至少要给 profile mutation 和 group-avatar rebuild 分清正式边界

### F-617：`GET /files` 会把内部存储细节原样暴露给客户端

状态：已修复（2026-04-12）

修复说明：

- `FileService.serialize_file()` 已移除公开 file payload 顶层和 `media` 内的 `storage_provider/storage_key/checksum_sha256` 字段
- 已更新 `test_file_upload_returns_normalized_media_metadata_and_list_roundtrips` 覆盖 `GET /files` 不再返回内部存储字段

原状态：已确认

现状：

- [files.py](/D:/AssistIM_V2/server/app/api/v1/files.py) 的 `GET /files`
- 直接返回 [file_service.py](/D:/AssistIM_V2/server/app/services/file_service.py) 的 `serialize_file()`
- payload 里同时包含：
  - `storage_provider`
  - `storage_key`
  - `checksum_sha256`
  - `user_id`
  - `file_url/url`

证据：

- [D:\AssistIM_V2\server\app\api\v1\files.py](D:\AssistIM_V2/server/app/api/v1/files.py)
- [D:\AssistIM_V2\server\app\services\file_service.py](D:\AssistIM_V2/server/app/services/file_service.py)

影响：

- 文件列表正式入口把内部存储实现、对象键和校验和一起暴露给前端
- `files` 不再只是“可展示的附件摘要”，而是变成了存储后端细节镜像

建议：

- `/files` 应收口成最小 public file summary，不应继续暴露 `storage_key/checksum/user_id`

### F-618：`POST /files/upload` 的正式响应同样暴露了内部存储细节

状态：已修复（2026-04-12）

修复说明：

- `FileService.serialize_file()` 已移除上传响应顶层和 `media` 内的 `storage_provider/storage_key/checksum_sha256` 字段
- 已更新 `test_file_upload_returns_normalized_media_metadata_and_list_roundtrips` 覆盖上传响应不再返回内部存储字段

原状态：已确认

现状：

- [files.py](/D:/AssistIM_V2/server/app/api/v1/files.py) 的 `POST /files/upload`
- 返回 [file_service.py](/D:/AssistIM_V2/server/app/services/file_service.py) 的 `serialize_file()`
- 上传成功后客户端会立刻拿到 `storage_provider/storage_key/checksum_sha256`

证据：

- [D:\AssistIM_V2\server\app\api\v1\files.py](D:\AssistIM_V2/server/app/api/v1/files.py)
- [D:\AssistIM_V2\server\app\services\file_service.py](D:\AssistIM_V2/server/app/services/file_service.py)

影响：

- 正式 upload contract 直接把后端存储实现泄露给上层
- 后续客户端会继续把这些字段当成权威元数据传播到聊天消息和本地缓存

建议：

- upload 响应应收口成最小的 public media descriptor，不应继续公开内部存储键

### F-619：本地媒体后端会把整个上传目录直接静态挂到公开 `/uploads`

状态：已修复（2026-04-12）

修复说明：

- create_app() 已移除 StaticFiles 对 upload_dir 的整目录公开挂载
- 本地媒体访问改为同一路径下的 FastAPI 受认证路由，普通上传对象必须能按 storage_key 在 files 表中找到
- 默认头像和群头像这类服务端生成资源仍走同一路径，但也需要通过认证路由访问
- 已更新 test_file_upload_returns_normalized_media_metadata_and_list_roundtrips 覆盖未认证下载返回 401、认证下载返回原始 bytes

### F-620：通用 `POST /files/upload` 没有文件类型 allowlist

状态：已修复（2026-04-12）

修复说明：

- LocalMediaStorage.store_upload() 已在落盘前校验扩展名与 MIME allowlist，拒绝不在正式附件范围内的上传
- 不允许的扩展名或 MIME 会返回 422 upload file type is not allowed，避免通用上传入口退化为任意文件托管
- 已新增 test_file_upload_rejects_disallowed_file_types 覆盖 .exe / application/x-msdownload 被拒绝

### F-621：通用文件上传会把客户端自报 MIME 和文件名当成正式元数据持久化

状态：已修复（2026-04-12）

修复说明：

- LocalMediaStorage.store_upload() 已不再把 UploadFile.content_type 当正式 MIME 持久化，content_type 改由服务端根据文件头和允许扩展名派生
- 文件扩展名与派生 MIME 必须匹配 allowlist，不匹配时返回 422 upload file type is not allowed
- 上传显示名已进入 _normalize_original_name() 规范化后再持久化，不再直接保存客户端原始 filename
- 已更新 test_file_upload_returns_normalized_media_metadata_and_list_roundtrips 覆盖客户端乱报 MIME 时仍返回服务端派生 text/plain

### F-622：`GET /files` 没有分页或数量边界

状态：已修复（2026-04-12）

修复说明：

- GET /files 已新增 limit 查询参数，范围为 1..200，默认 50
- FileService.list_files() / FileRepository.list_by_user() 已把 limit 下推到数据库查询
- 已更新 test_file_upload_returns_normalized_media_metadata_and_list_roundtrips 覆盖 limit=1 和非法 limit 422

原状态：已确认

现状：

- [files.py](/D:/AssistIM_V2/server/app/api/v1/files.py) 的 `GET /files`
- 直接调用 [file_repo.py](/D:/AssistIM_V2/server/app/repositories/file_repo.py) 的 `list_by_user()`
- 该查询会把该用户的全部上传记录一次性返回

证据：

- [D:\AssistIM_V2\server\app\api\v1\files.py](D:\AssistIM_V2/server/app/api/v1/files.py)
- [D:\AssistIM_V2\server\app\repositories\file_repo.py](D:\AssistIM_V2/server/app/repositories/file_repo.py)

影响：

- 文件列表正式入口会随历史上传数量线性膨胀
- 读取成本和暴露面都没有边界

建议：

- `/files` 如保留，应至少补分页、时间窗口或业务域过滤

### F-623：文件上传不是 failure-atomic，数据库失败会留下孤儿文件

状态：已修复（2026-04-12）

修复说明：

- MediaStorage 已补充 delete_object() 边界，LocalMediaStorage 可按 storage_key 删除已落盘对象
- FileService.save_upload_record() 已把上传落盘与数据库记录持久化收口为统一链路，DB create 失败时会清理刚写入的对象再抛出原异常
- AvatarService 自定义头像上传已改走 FileService.save_upload_record()，不再通过 FileRepository 绕过上传失败补偿
- 已新增 test_file_upload_removes_stored_object_when_database_insert_fails 覆盖数据库写入失败后不会留下孤儿文件

### F-624：附件上传的内部存储字段会继续沿聊天消息 payload 广播给会话成员

状态：已修复（2026-04-12）

修复说明：

- `MessageService._sanitize_transport_extra()` 已剥离附件 extra 顶层和 `media` 内的 `storage_provider/storage_key/checksum_sha256` 字段
- 客户端 `FileService.upload_file()` 与 `build_remote_attachment_extra()` 已不再把这些内部字段写入聊天附件 payload
- 已补 server/client 回归覆盖 history/sync 与客户端构造链路都不再传播内部存储字段

原状态：已确认

现状：

- 客户端 [file_service.py](/D:/AssistIM_V2/client/services/file_service.py) 会保留服务端返回的 `storage_provider/storage_key/checksum_sha256`
- [message.py](/D:/AssistIM_V2/client/models/message.py) 的 `build_remote_attachment_extra()` 会把这些字段继续放进 `media`
- 聊天附件发送时，这份 `media` 会被作为消息 `extra` 的一部分继续发给服务端和其它成员

证据：

- [D:\AssistIM_V2\client\services\file_service.py](D:\AssistIM_V2/client/services/file_service.py)
- [D:\AssistIM_V2\client\models\message.py](D:\AssistIM_V2/client/models/message.py)
- [D:\AssistIM_V2\client\managers\message_manager.py](D:\AssistIM_V2/client/managers/message_manager.py)

影响：

- 上传响应里的内部存储细节不会停留在 upload 边界，而会继续进入正式聊天协议
- message extra/media 不再只是展示摘要，而会携带后端存储实现细节

建议：

- 附件消息正式 payload 应只保留业务上真正需要的公共字段

### F-625：`GET /keys/prekey-bundle/{user_id}` 没有关系或授权边界，任意用户都能枚举目标设备 bundle

状态：已修复（2026-04-14）

现状：

- [keys.py](/D:/AssistIM_V2/server/app/api/v1/keys.py) 的 `get_prekey_bundle()`
- 只要求调用者已登录
- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `list_prekey_bundles()` 直接 `del current_user`
- 然后只校验目标用户存在，就会返回其全部 active device bundle

证据：

- [D:\AssistIM_V2\server\app\api\v1\keys.py](D:\AssistIM_V2/server/app/api/v1/keys.py)
- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)

影响：

- 预密钥 bundle 正式入口没有把“谁可以看谁的设备身份材料”收口成授权模型
- 任意已登录用户都可以探测任意目标用户的设备面

建议：

- prekey bundle 入口应至少绑定到正式可通信关系，或明确限制为同账号 / 同会话 / 同好友边界

### F-626：prekey bundle 正式响应会泄露目标设备活跃度和库存信息

状态：已修复（2026-04-14）

现状：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `serialize_prekey_bundle()`
- 会把：
  - `available_prekey_count`
  - `last_seen_at`
- 一起返回给调用方

证据：

- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\api\v1\keys.py](D:\AssistIM_V2/server/app/api/v1/keys.py)

影响：

- 目标设备的活跃时间和 prekey 库存被一起暴露
- 这已经超出了“拿到加密所需最小公钥材料”的范围

建议：

- prekey bundle 正式响应应缩到最小必需字段，不应继续公开活动时间和库存计数

### F-627：prekey bundle 正式响应还会泄露目标设备名

状态：已修复（2026-04-14）

现状：

- `serialize_prekey_bundle()` 同时返回 `device_name`
- 调用方可以直接看到目标用户设备的命名信息

证据：

- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\api\v1\keys.py](D:\AssistIM_V2/server/app/api/v1/keys.py)

影响：

- prekey bundle 入口额外泄露了终端命名信息
- 这会继续放大设备指纹和设备画像暴露面

建议：

- device name 不应出现在面向对端的正式 prekey bundle 里

### F-628：`POST /keys/prekeys/claim` 允许任意已登录用户消耗任意设备的 one-time prekey

状态：已修复（2026-04-14）

现状：

- [keys.py](/D:/AssistIM_V2/server/app/api/v1/keys.py) 的 `claim_prekeys()`
- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 里同样 `del current_user`
- 然后只要 `device_id` 存在且活跃，就会 `claim_one_time_prekey(device_id)`

证据：

- [D:\AssistIM_V2\server\app\api\v1\keys.py](D:\AssistIM_V2/server/app/api/v1/keys.py)
- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- one-time prekey 消耗边界没有和正式通信关系绑定
- 任意登录用户都可以消耗目标设备库存，制造后续加密失败或退化

建议：

- prekey claim 必须绑定到明确的正式发送场景，不能继续作为裸公共入口存在

### F-629：设备注册会把已存在的 `device_id` 重新绑定到当前账号

状态：已修复（2026-04-14）

现状：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `register_device()`
- 直接调用 [device_repo.py](/D:/AssistIM_V2/server/app/repositories/device_repo.py) 的 `upsert_device()`
- `upsert_device()` 如果发现同名 `device_id` 已存在
- 会直接把 `device.user_id` 改成当前用户

证据：

- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- `device_id` 现在不是稳定的“设备归属键”，而是可被重新抢占的逻辑主键
- 一个账号提交了别人已有的 `device_id`，就可能把那条设备记录整条改绑

建议：

- `device_id` 一旦注册成功，应变成不可跨账号重绑的正式标识

### F-630：one-time prekey claim 没有并发锁或数据库级占用保护

状态：已修复（2026-04-14）

现状：

- [device_repo.py](/D:/AssistIM_V2/server/app/repositories/device_repo.py) 的 `claim_one_time_prekey()`
- 先 `SELECT is_consumed = false LIMIT 1`
- 再在 Python 里把该行改成 `is_consumed = true`
- 整个过程没有 `FOR UPDATE`、版本检查或唯一 claim token

证据：

- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- 并发 claim 同一设备 prekey 时存在双重领取竞态
- one-time prekey 的“只消耗一次”正式语义没有被数据库边界真正保证

建议：

- prekey claim 应下沉到数据库级互斥或原子 update

### F-631：`list_prekey_bundles()` 对 `available_prekey_count` 是稳定的 N+1 查询

状态：已修复（2026-04-14）

现状：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `list_prekey_bundles()`
- 先查一批 active devices
- 然后对每个 device 单独 `count_available_prekeys(item.device_id)`

证据：

- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- 目标用户设备越多，bundle 列表查询成本越高
- prekey bundle 入口会被设备数线性放大

建议：

- available prekey count 应改成批量聚合，而不是 per-device 计数

### F-632：`list_my_devices()` 同样是稳定的 N+1 预密钥计数路径

状态：已修复（2026-04-14）

现状：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `list_my_devices()`
- 会对每个 device 单独调用 `count_available_prekeys(item.device_id)`

证据：

- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- “查看我的设备列表”这种基础诊断路径也会随设备数线性放大
- E2EE 设备正式视图仍然建立在 N+1 查询上

建议：

- 设备列表里的 prekey 库存应批量聚合，不应逐行回查

### F-633：设备 / 预密钥正式 schema 对大块 key material 没有上限

状态：已修复（2026-04-14）

修复说明：

- [device.py](/D:/AssistIM_V2/server/app/schemas/device.py) 已为 `identity_key_public`、`signing_key_public`、`signed_prekey.public_key`、`signed_prekey.signature`、`one_time_prekey.public_key` 增加明确 `max_length`。
- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 进一步要求这些字段是固定长度 base64 key/signature，而不是任意长字符串。

现状：

- [device.py](/D:/AssistIM_V2/server/app/schemas/device.py)
- `identity_key_public`
- `signing_key_public`
- `signed_prekey.public_key`
- `signed_prekey.signature`
- `one_time_prekey.public_key`
- 都只有 `min_length`
- 没有 `max_length`

证据：

- [D:\AssistIM_V2\server\app\schemas\device.py](D:\AssistIM_V2/server/app/schemas/device.py)

影响：

- 设备注册 / refresh 正式入口对 key material payload 大小没有明确边界
- 恶意或异常客户端可以提交极大的 base64 字符串，放大请求体和持久化成本

建议：

- 这些 key material 字段应建立明确的长度上限和编码约束

### F-634：刷新设备 keys 不会更新 `last_seen_at`

状态：已修复（2026-04-14）

现状：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `refresh_my_device_keys()`
- 会更新 signed prekey / one-time prekeys
- 但不会更新 [device_repo.py](/D:/AssistIM_V2/server/app/repositories/device_repo.py) 里的 `last_seen_at`
- `last_seen_at` 目前只会在 `upsert_device()` 时推进

证据：

- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- 设备活跃时间会和真实 key 刷新活动脱节
- 既然该字段又被正式对外暴露，当前语义就已经不可靠

建议：

- 如果 `last_seen_at` 要继续对外暴露，就需要统一其正式推进规则

### F-635：已消耗 prekey 的 id 永远不能复用

状态：已修复（2026-04-14）

现状：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `refresh_my_device_keys()`
- 会用 [device_repo.py](/D:/AssistIM_V2/server/app/repositories/device_repo.py) 的 `existing_prekey_ids()`
- 该查询不会过滤 `is_consumed`
- 所以只要某个 `prekey_id` 历史上出现过，就永远不能再次追加

证据：

- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- long-lived device 的 prekey id 空间会持续单向消耗
- 预密钥库存刷新 contract 没有定义“历史已消费 prekey 是否可复用 id”

建议：

- prekey id 的生命周期要么明确允许回收，要么明确采用足够稳定的单调分配策略并文档化

### F-636：history recovery 导入只按 `source_device_id` 建索引，不绑定发送者身份

状态：已修复（2026-04-14）

修复说明：

- history recovery payload 的 inner/outer 层都会携带并校验 `sender_identity_key_public`。
- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 将 `source_device_id` 与 `sender_identity_key_public` 一起持久化；同一 `source_device_id` 后续若出现不同 sender identity 会拒绝导入。
- 导入旧于当前 `exported_at` 的 package 也会被拒绝，避免旧包回滚同一 source device 的恢复状态。

现状：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `import_history_recovery_package()`
- 解包后用 `source_device_id` 作为 `history_recovery_state.devices[...]` 的主键
- `sender_identity_key_public` 只用于这次包解密
- 后续落盘的 [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) `_normalize_history_recovery_device_record()`
- 并不会把“这个 source device 对应的发送者身份公钥”建成固定绑定

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)

影响：

- 只要两个恢复包复用了同一个 `source_device_id`
- 后来的包就会继续合并/覆盖同一条 recovery 记录
- 本地恢复材料的正式主键不是“设备身份”，而只是一个客户端自报字符串

建议：

- history recovery state 应把 `source_device_id` 和经过验证的发送者身份材料一起绑定成正式主键

### F-637：`serialize_group()` 在普通读路径里会直接改写 `session.avatar`

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `serialize_group()`
- 读路径一进来就调用 [avatar_service.py](/D:/AssistIM_V2/server/app/services/avatar_service.py) 的 `ensure_group_avatar(group)`
- `ensure_group_avatar()` 又会调用 [session_repo.py](/D:/AssistIM_V2/server/app/repositories/session_repo.py) 的 `update_avatar(..., commit=False)`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)

影响：

- 普通 `GET /groups`、`GET /groups/{id}` 读取群资料时就会带出数据库写操作
- `serialize_group()` 不再是纯序列化，而是兼带状态修复和 session mirror 更新

建议：

- group 序列化应从 read path 剥离 `ensure_group_avatar()` 这类写操作

### F-638：`serialize_session()` 在 group session 读路径里也会直接改写 `session.avatar`

状态：已修复（2026-04-14）

现状：

- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `serialize_session()`
- 遇到 group session 时同样会调用 `avatars.ensure_group_avatar(group)`
- 于是 `GET /sessions`、`GET /sessions/{id}` 的普通读取也会落到 `session_repo.update_avatar(..., commit=False)`

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)

影响：

- session 列表和详情读取也会夹带 group-avatar mirror 写入
- session 域和 group-avatar 生成域在读路径上继续耦合

建议：

- session 序列化也应改成只读，不应再在读取时修正 avatar mirror

### F-639：`SessionRepository.update_avatar()` 不会推进 `session.updated_at`

状态：已修复（2026-04-14）

现状：

- [session_repo.py](/D:/AssistIM_V2/server/app/repositories/session_repo.py) 的 `update_avatar()`
- 只更新 `session.avatar`
- 不更新 `updated_at`
- 但这条路径又被 `ensure_group_avatar()` 在群相关读写链路里广泛调用

证据：

- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- session avatar 已变，但 session freshness 时间戳不变
- `updated_at` 作为会话最新性和列表排序信号的正式语义继续被打穿

建议：

- 如果 session avatar 继续镜像进 session，就必须一起定义 `updated_at` 的推进规则

### F-640：加人、踢人、退群都不会推进 `session.updated_at`

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `add_member()`
- `remove_member()`
- `leave_group()`
- 都会改 `SessionMember / GroupMember / group avatar`
- 但不会调用 `touch_without_commit()` 或其他 session freshness 更新

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)

影响：

- 群成员生命周期变化不会反映到 session freshness
- 会话列表排序、远端快照替换和“最近活跃会话”语义都会和真实群变更脱节

建议：

- 成员增删退群这类正式 group lifecycle mutation 应明确是否推进 `session.updated_at`

### F-641：角色变更和转让群主也不会推进 `session.updated_at`

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `update_member_role()`
- `transfer_ownership()`
- 只改 `GroupMember/Group.owner_id`
- 不触发 `touch_without_commit()`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)

影响：

- owner/admin 这种高价值治理变化也不会进入 session freshness
- 群治理状态和会话 authoritative snapshot 的最新性继续分裂

建议：

- 角色和所有权变化也应进入明确的 session freshness / lifecycle contract

### F-642：`GroupRepository.update_member_role()` 会在“更新角色”路径里自动补建缺失的 `GroupMember`

状态：已修复（2026-04-14）

现状：

- [group_repo.py](/D:/AssistIM_V2/server/app/repositories/group_repo.py) 的 `update_member_role()`
- 如果 `get_member()` 为空
- 会直接 `member = GroupMember(...)`
- 然后继续当成功路径写库

证据：

- [D:\AssistIM_V2\server\app\repositories\group_repo.py](D:\AssistIM_V2/server/app/repositories/group_repo.py)

影响：

- “更新角色”不再是纯更新操作，而会静默修复缺失行
- group/session drift 会被 repo 层直接吞掉，后续很难发现数据模型已经漂移

建议：

- role update 应只允许更新已存在成员；缺失成员应显式报错

### F-643：`GroupRepository.update_member_profile()` 会在“更新自己的群资料”路径里自动补建缺失的 `GroupMember`

状态：已修复（2026-04-14）

现状：

- [group_repo.py](/D:/AssistIM_V2/server/app/repositories/group_repo.py) 的 `update_member_profile()`
- `member is None` 时会直接构造新的 `GroupMember(group_id, user_id)`
- 然后再写 `group_nickname/note`

证据：

- [D:\AssistIM_V2\server\app\repositories\group_repo.py](D:\AssistIM_V2/server/app/repositories/group_repo.py)

影响：

- self-profile patch 不再是纯更新，而是会悄悄补建 group member 行
- 读写边界继续掩盖 group/session 双表漂移

建议：

- self-profile patch 也应只允许更新现有 `GroupMember`

### F-644：`remove_member()` 会把“GroupMember 已缺失”的漂移静默当成成功路径

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `remove_member()`
- action 里依次调用：
  - `groups.remove_member(...)`
  - `sessions.remove_member(...)`
- 两个 repo 方法的返回值都没有检查

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\repositories\group_repo.py](D:\AssistIM_V2/server/app/repositories/group_repo.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)

影响：

- 只要 `SessionMember` 还在，API 就可能返回 204/成功
- 但 `GroupMember` 缺失这种更底层的数据漂移会被整个隐藏掉

建议：

- 成员移除应显式校验 group/session 两侧成员关系是否一致

### F-645：`leave_group()` 也会把“GroupMember 已缺失”的漂移静默当成成功路径

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `leave_group()`
- 同样忽略了 `groups.remove_member()` 和 `sessions.remove_member()` 的返回值

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\repositories\group_repo.py](D:\AssistIM_V2/server/app/repositories/group_repo.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)

影响：

- “退群成功”可能只是把 `SessionMember` 删掉，而 `GroupMember` 早已漂移丢失
- 服务端会把这类 drift 继续伪装成正常 lifecycle 成功

建议：

- leave 也应显式校验 group/session 双表一致性，不应继续静默吞漂移

### F-646：`update_member_role()` 会借 repo 自动补建逻辑静默修复缺失 `GroupMember`

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `update_member_role()`
- 虽然前面调用了 `_ensure_group_member()`，但它只校验 `SessionMember`
- 真正写入时又落到会自动补建行的 `groups.update_member_role()`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\repositories\group_repo.py](D:\AssistIM_V2/server/app/repositories/group_repo.py)

影响：

- “角色更新”会把 session/group 双表漂移直接抹平
- 上层再也看不到 “session 有成员但 group_members 丢行” 这种结构性错误

建议：

- role update 应在 service 层要求 `GroupMember` 已存在，而不是继续靠 repo 自动补行

### F-647：`transfer_ownership()` 也会借 repo 自动补建逻辑静默修复缺失 `GroupMember`

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `transfer_ownership()`
- 同样只用 `_ensure_group_member()` 校验 `SessionMember`
- 然后依赖 `groups.update_member_role()` 给旧 owner / 新 owner 写角色
- 缺失的 `GroupMember` 行会被悄悄补出来

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\repositories\group_repo.py](D:\AssistIM_V2/server/app/repositories/group_repo.py)

影响：

- 所有权转移也会静默吞掉底层 membership drift
- owner 变更链路无法再作为 authoritative 校验点发现数据异常

建议：

- transfer ownership 应把 `GroupMember` 缺失当正式错误，而不是隐式自愈

### F-648：`record_group_profile_update_event()` 先提交 event，再单独走 websocket fanout

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `record_group_profile_update_event()`
- 在 helper 里就执行 `append_session_event(..., commit=False)` 后 `self.db.commit()`
- 路由层 [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 再拿这份结果去 `send_json_to_users()`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- event append 和 realtime fanout 不是 failure-atomic
- 一旦 websocket fanout 失败，离线补偿里已经有 event，但在线端本轮不会收到对应 realtime

建议：

- 这类 event append + fanout 应至少定义统一 outbox/retry contract

### F-649：`record_group_self_profile_update_event()` 也先提交 event，再单独走 websocket fanout

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `record_group_self_profile_update_event()`
- 同样在 helper 里 commit
- 路由层再把 payload 广播给当前用户其它连接

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- self-scoped profile event 和 realtime 也不是 failure-atomic
- 其它设备可能要等下次离线补偿才能看到这次正式变更

建议：

- private event append 与多端 fanout 也应收口成统一的可靠投递 contract

### F-650：群公告广播和 `group_profile_update` 广播不是一个原子步骤

状态：已修复（2026-04-14）

现状：

- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `update_group_profile()`
- 先在 `result.announcement_message_id` 存在时广播公告消息
- 再广播 `group_profile_update`
- 中间没有统一的“二者必须一起成功”边界

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 在线端可能先收到公告消息、但没收到群资料更新
- 或只看到群资料变化，却错过与之配套的公告系统消息

建议：

- 群公告 message 和 group profile mutation 应定义更清晰的打包/顺序/retry contract

### F-651：`call_invite` 忙线分支返回的是“本次尝试的 media_type”，不是当前占线通话的 media_type

状态：已修复（2026-04-14）

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `invite()`
- 忙线时直接返回：
  - `media_type: normalized_media_type`
- 这里用的是当前 invite 请求里想发起的类型
- 不是 `busy_call.media_type`

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)

影响：

- `call_busy` payload 里的 `media_type` 不是“阻塞中的那通电话类型”
- 客户端收到的 busy 结果会把“尝试发起的通话”与“当前占线通话”混成一条语义

建议：

- busy payload 应明确区分 attempted media 和 blocking call media，或只返回阻塞通话的 authoritative 信息

### F-652：`call_busy` payload shape 与其它 call 事件不一致，客户端无法恢复完整通话上下文

状态：已修复（2026-04-14）

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的忙线分支返回的 payload 只有：
  - `call_id`
  - `session_id`
  - `busy_user_id`
  - `active_call_id`
  - `media_type`
- 不包含其它 call 事件普遍带的：
  - `initiator_id`
  - `recipient_id`
  - `status`
  - `created_at`
  - `answered_at`
- 客户端 [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 的 `ActiveCallState.from_payload()`
- 又只会解析 canonical call 字段，`busy_user_id/active_call_id` 根本不会进入模型

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)
- [D:\AssistIM_V2\client\models\call.py](D:\AssistIM_V2/client/models/call.py)

影响：

- `call_busy` 目前没有单一 canonical payload contract
- 客户端既拿不到完整 call 上下文，也会把 `busy_user_id/active_call_id` 这类专用字段静默丢掉

建议：

- 为 `call_busy` 单独定义正式 model，或把它收口到统一 call payload shape

### R-085：普通 `GET /groups` / `GET /sessions` 可能同步触发 group avatar 生成和文件 I/O

状态：已修复（2026-04-14）

现状：

- `serialize_group()` / `serialize_session()` 的读路径都会调用 `ensure_group_avatar()`
- [avatar_service.py](/D:/AssistIM_V2/server/app/services/avatar_service.py) 的 `ensure_group_avatar()`
- 会进一步调用 [group_avatars.py](/D:/AssistIM_V2/server/app/media/group_avatars.py) 的生成逻辑

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- 普通列表/详情读取会被同步 CPU / 文件系统工作拖慢
- 读路径延迟会受 group avatar 生成状态影响

建议：

- group avatar 生成应从普通 read path 剥离

### R-086：读路径写库依赖外层后续是否 `commit()`，写入时机不再确定

状态：已修复（2026-04-14）

现状：

- `ensure_group_avatar(...)->update_avatar(..., commit=False)` 与 `backfill_user_avatar_state()` 这类兼容修复
- 都可能在普通序列化中触发 `flush`
- 但真正是否落盘、何时落盘，取决于外层请求后续还有没有别的 commit

证据：

- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 普通读取带出的写操作会和后续无关 mutation 一起 piggyback 提交
- 写入时序不再由单一正式边界控制

建议：

- read path 引出的 compat / mirror 更新应改成显式迁移或后台任务

### R-087：`session.updated_at` 现在已经不是群生命周期变化的 authoritative freshness 信号

状态：已修复（2026-04-14）

现状：

- 消息发送会通过 `last_message_seq` 推进 `updated_at`
- group profile/self-profile 某些路径会 `touch_without_commit()`
- 但成员增删、退群、角色变更、转让群主、avatar mirror 更新并不统一推进 `updated_at`

证据：

- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2/server/app/repositories/message_repo.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)

影响：

- session freshness 在不同 mutation 类型上口径已经分裂
- 会话列表排序、远端快照 replace 和本地 tombstone 比较都会受影响

建议：

- `updated_at` 必须重新定义为哪类 lifecycle mutation 的 authoritative freshness 标记

### R-088：群事件 append 和 realtime fanout 现在是 split-phase，没有 outbox / retry contract

状态：已修复（2026-04-14）

现状：

- group profile / self profile 事件都是先 append+commit
- 再由 route 层单独做 websocket fanout
- 中间没有 outbox、补投或重试边界

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- 在线和离线两套视图的收敛时机会继续分裂
- 在线端错过 fanout 时，只能等下一轮 reconnect/history 补偿

建议：

- group 事件 append 和 realtime 投递应考虑 outbox/retry 或至少定义明确的失败补偿 contract

### F-653：`serialize_session()` 会在普通会话读路径里回写成员用户的 avatar 状态

状态：已修复（2026-04-14）

修复说明：

- session 成员摘要不再调用 `backfill_user_avatar_state()`；读路径只用 `resolve_user_avatar_url()` 解析当前 avatar。

现状：

- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `serialize_session()`
- 在构造 `members[]` 时会对每个 user 调 `backfill_user_avatar_state()`
- 这不是单纯格式化，而是可能直接更新用户 avatar 字段并提交到数据库

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- 普通 `GET /sessions` / `GET /sessions/{id}` 会顺手改写用户资料
- 会话域读路径继续承担用户资料兼容修复 side effect

建议：

- 用户 avatar 兼容修复不要继续挂在会话序列化读路径里

### F-654：`_serialize_counterpart_profile()` 也会在 direct 会话读路径里回写对端用户 avatar 状态

状态：已修复（2026-04-14）

修复说明：

- direct counterpart 摘要已收口到 `resolve_user_avatar_url()` 只读路径，不再在会话读取中回写用户 avatar 状态。

现状：

- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `_serialize_counterpart_profile()`
- 在 direct 会话里会对 counterpart user 调 `backfill_user_avatar_state()`
- 即使本次请求只想拿会话摘要，也可能直接改写对端用户行

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- direct 会话详情/列表读取会继续夹带用户资料写操作
- 会话域与用户资料域边界继续污染

建议：

- counterpart 摘要序列化应只读，不应顺手做用户资料迁移

### F-655：`serialize_message()` 在普通消息读路径里也会回写 sender 的 avatar 状态

状态：已修复（2026-04-14）

修复说明：

- 消息 sender profile 序列化已去掉 `backfill_user_avatar_state()` 读路径写入，历史消息和 sync 返回不再顺手改用户表。

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `_serialize_sender_profile()`
- 会对 sender user 调 `backfill_user_avatar_state()`
- 也就是说，普通历史消息列表和 sync 返回都可能顺手更新用户表

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- 消息读路径继续承担用户资料 compat 修复
- 历史回拉和消息分页会带出额外数据库写入

建议：

- sender profile 规范化应从消息读取主链剥离

### F-656：`serialize_group()` 的成员头像口径和会话/消息/user 端点不一致

状态：已修复（2026-04-14）

修复说明：

- 用户、会话、消息和群成员头像现在统一通过 `resolve_user_avatar_url()` 输出，只读序列化不再混入兼容写操作。

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `serialize_group()`
- 在构造 `members[]` 时直接对原始 user 调 `resolve_user_avatar_url()`
- 并不会像 user/session/message 那样先 `backfill_user_avatar_state()`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- 同一个用户在群详情里的头像，可能落后于用户详情、会话摘要、消息 sender profile
- 群域和其它域对同一 avatar state 的序列化口径继续分裂

建议：

- 群成员头像的序列化口径要和用户/会话/消息统一

### F-657：生成 group avatar 的输入成员头像也没有先过 avatar state 规范化

状态：已修复（2026-04-14）

修复说明：

- generated group avatar 的成员输入同样走 `resolve_user_avatar_url()`，与其它端点共用当前 avatar state 的只读解析口径。

现状：

- [avatar_service.py](/D:/AssistIM_V2/server/app/services/avatar_service.py) 的 `_group_member_avatar_payload()`
- 同样直接对原始 user 调 `resolve_user_avatar_url()`
- 不会先 `backfill_user_avatar_state()`

证据：

- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- generated group avatar 可能基于过期/未规范化的成员头像状态生成
- group avatar 与用户/会话/消息侧看到的成员头像不再一致

建议：

- 生成 group avatar 前也应使用统一的用户 avatar 规范化视图

### F-658：消息返回里的 `session_avatar` 仍直接取原始 `session.avatar`

状态：已修复（2026-04-14）

修复说明：

- 消息 session metadata 的 group `session_avatar` 改用 `resolve_group_avatar_url()`，不再直接依赖可能陈旧的 `session.avatar`。

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `_load_session_metadata()`
- 直接把 `session.avatar` 填进 `session_avatar`
- 不会像 `serialize_session()` / `serialize_group()` 那样触发 `ensure_group_avatar()`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 同一个群会话，消息列表里看到的 `session_avatar` 可能落后于会话列表/群详情
- session avatar 的正式口径继续在不同 endpoint 之间分裂

建议：

- message session metadata 也应复用统一的会话头像 authoritative contract

### F-659：`list_messages()` 仍会暴露“已被 direct 可见性模型隐藏”的私聊历史

状态：closed（2026-04-14）

修复记录：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `list_messages()` 已统一走 `_ensure_visible_session_membership()`
- hidden private session 现在不会再通过消息分页接口继续暴露历史

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `list_messages()`
- 只做 `_ensure_membership()`
- 不会像 [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 那样对 direct 会话执行 `_is_visible_private_session()` 可见性 gate

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 一条 direct 会话即使已经从会话列表/会话详情里被隐藏
- 只要当前设备还保留 membership，就仍能通过消息接口继续读到历史

建议：

- 消息读取链也应复用同一套 direct 可见性模型

### F-660：`sync_missing_messages()` / `sync_missing_events()` 也没有 direct 可见性 gate

状态：closed（2026-04-14）

修复记录：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 missing-messages / missing-events 已统一经过 `_filter_visible_session_items()`
- reconnect/history 补偿现在不会再把 hidden private session 继续回放给当前用户

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的两条 missing-sync 入口
- 最终只按 `SessionMember` membership 枚举 session
- 不会过滤“member 不足 2 人、应对用户隐藏”的 direct 会话

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2/server/app/repositories/message_repo.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 会话可见性和 reconnect/history 补偿模型继续分裂
- 被隐藏的 direct 会话仍可能在 sync 阶段被继续回放事件和消息

建议：

- missing-messages / missing-events 也应收口到同一套 direct visibility contract

### F-661：`create_private()` 命中已有 direct_key 时，会用请求侧成员集覆盖返回的 `participant_ids`

状态：closed（2026-04-14）

修复记录：

- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 命中既有 direct session 后，返回 payload 已改为读取 authoritative `existing_member_ids`
- 对应单测已补，create-direct 返回值不再信任当前请求里的 participant 输入

现状：

- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `create_private()`
- 命中已有 direct 会话时直接：
  - `serialize_session(existing, participant_ids=members, ...)`
- 这里的 `members` 来自当前请求归一化结果
- 不是从已存在 session 的实际 `SessionMember` 重新读取

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 一旦已存在 direct 会话的 membership 已发生漂移
- create-direct 返回值仍会把请求侧的“两人集合”冒充成 authoritative `participant_ids`

建议：

- 命中既有会话后，返回 payload 不应再信任请求侧 participant 输入

### F-662：群详情里的 `member_version/group_member_version` 仍按 `SessionMember` 计算

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `serialize_group()`
- `member_version` 和 `group_member_version`
- 都是基于 `session_members` 的 `user_ids` 哈希
- 不是基于 `GroupMember`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\repositories\group_repo.py](D:\AssistIM_V2/server/app/repositories/group_repo.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)

影响：

- group/session membership drift 会被版本号继续静默掩盖
- 群详情里的“成员版本”并不真正代表群 authoritative 成员集

建议：

- 群版本字段应明确绑定到 `GroupMember` 的 authoritative 集合

### F-663：会话详情里的 `group_member_version` 也仍按 `SessionMember` 计算

状态：已修复（2026-04-14）

现状：

- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `serialize_session()`
- group 会话里的 `group_member_version`
- 直接拿 `member_ids` 做哈希
- 这里的 `member_ids` 来自 session membership，不是 group membership

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- session 详情里的 `group_member_version` 继续和群 authoritative 成员集脱节
- 会话域和群域对“群成员版本”没有单一真相

建议：

- 会话域里的群成员版本也应复用群 authoritative 版本来源

### F-664：群详情里的成员 `joined_at` 取自 `SessionMember`，不是 `GroupMember`

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `serialize_group()`
- `members[].joined_at` 直接取 `session_members`
- 不是 `group_members`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\models\group.py](D:\AssistIM_V2/server/app/models/group.py)
- [D:\AssistIM_V2\server\app\models\session.py](D:\AssistIM_V2/server/app/models/session.py)

影响：

- 群详情把 session membership 的加入时间冒充成 group membership 的 authoritative 加入时间
- 一旦 group/session membership 出现漂移，两条时间线会继续被混成一条

建议：

- 群成员视图里的加入时间应明确来自 `GroupMember.joined_at`

### F-665：`update_group_profile()` 已提交共享变更后，任一广播失败都会把 HTTP 请求变成 500

状态：已修复（2026-04-14）

现状：

- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `update_group_profile()`
- 先调用 service 完成持久化
- 再依次：
  - 广播公告消息
  - 广播 `group_profile_update`
- 中间任一步 websocket fanout 抛错，HTTP 路由就会异常返回

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 服务端已经提交了群资料修改
- 但调用方却会收到 500，形成“持久化已成功、HTTP 却报失败”的分裂契约

建议：

- 持久化成功后的 realtime fanout 不应继续决定这条 HTTP mutation 的成败

### F-666：`update_my_group_profile()` 也会在提交成功后因为 fanout 失败而报 500

状态：已修复（2026-04-14）

现状：

- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `update_my_group_profile()`
- 先持久化当前用户的群备注/群昵称
- 再广播 shared `group_profile_update` 与 self-scoped `group_self_profile_update`

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- self-profile mutation 已提交后，任一 fanout 失败都会把路由变成 500
- 客户端会把一次已成功 mutation 误判成失败

建议：

- group self-profile mutation 也应拆开“commit 成功”和“fanout 最佳努力”两层语义

### F-667：`edit_message()` 已提交消息编辑后，广播失败仍会把 HTTP 请求变成 500

状态：已修复（2026-04-12）

修复说明：

- `edit_message()` 已通过 `_broadcast_message_event()` 执行 best-effort realtime fanout，广播异常只记录日志，不再反向推翻已提交的 HTTP mutation
- 已由 `test_message_mutations_succeed_when_realtime_fanout_fails` 覆盖 edit fanout 失败仍返回 200

原状态：已确认

现状：

- [messages.py](/D:/AssistIM_V2/server/app/api/v1/messages.py) 的 `edit_message()`
- `service.edit()` 内部已经 commit
- 随后 route 再做 websocket 广播

证据：

- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2/server/app/api/v1/messages.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 消息内容已改成功
- 但在线广播失败时，HTTP 调用方仍会收到 500

建议：

- message edit 的 HTTP 成功语义不应被后续 fanout 反向推翻

### F-668：`recall_message()` 已提交撤回后，广播失败仍会把 HTTP 请求变成 500

状态：已修复（2026-04-12）

修复说明：

- `recall_message()` 已通过 `_broadcast_message_event()` 执行 best-effort realtime fanout，广播异常只记录日志，不再反向推翻已提交的 HTTP mutation
- 已由 `test_message_mutations_succeed_when_realtime_fanout_fails` 覆盖 recall fanout 失败仍返回 200

原状态：已确认

现状：

- [messages.py](/D:/AssistIM_V2/server/app/api/v1/messages.py) 的 `recall_message()`
- `service.recall()` 先提交状态与 session event
- route 层之后才 fanout

证据：

- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2/server/app/api/v1/messages.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 撤回已生效
- 但 HTTP 层可能仍把这次 mutation 报成失败

建议：

- recall 的 route-level contract 也应与 realtime fanout 解耦

### F-669：`delete_message()` 已提交删除后，广播失败仍会把 HTTP 请求变成 500

状态：已修复（2026-04-12）

修复说明：

- `delete_message()` 已通过 `_broadcast_message_event()` 执行 best-effort realtime fanout，广播异常只记录日志，不再反向推翻已提交的 HTTP mutation
- 已由 `test_message_mutations_succeed_when_realtime_fanout_fails` 覆盖 delete fanout 失败仍返回 204

原状态：已确认

现状：

- [messages.py](/D:/AssistIM_V2/server/app/api/v1/messages.py) 的 `delete_message()`
- `service.delete()` 先提交删除和事件
- route 层随后再 fanout

证据：

- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2/server/app/api/v1/messages.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 消息已经删掉
- 但 HTTP 删除接口仍可能返回 500，让客户端误以为删除失败

建议：

- delete route 也应区分“mutation 已提交”和“realtime 广播是否成功”

### F-670：`read_message_batch()` 已推进已读游标后，广播失败仍会把 HTTP 请求变成 500

状态：已修复（2026-04-12）

修复说明：

- `read_message_batch()` 已通过 `_broadcast_message_event()` 执行 best-effort realtime fanout，广播异常只记录日志，不再反向推翻已推进的 read cursor
- 已由 `test_message_mutations_succeed_when_realtime_fanout_fails` 覆盖 read fanout 失败仍返回 200

原状态：已确认

现状：

- [messages.py](/D:/AssistIM_V2/server/app/api/v1/messages.py) 的 `read_message_batch()`
- `service.batch_read()` 已经推进 read cursor 并 commit
- route 层随后才向其它成员广播 `read`

证据：

- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2/server/app/api/v1/messages.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 已读推进已在服务端生效
- 但广播失败时 HTTP 调用方会被误导成“这次 read 没成功”

建议：

- read HTTP 入口也应收口为“commit 成功”和“broadcast 最佳努力”两层语义

### F-671：`update_me()` 已提交用户资料后，profile event 广播失败仍会把 HTTP 请求变成 500

状态：已修复（2026-04-14）

现状：

- [users.py](/D:/AssistIM_V2/server/app/api/v1/users.py) 的 `update_me()`
- `UserService.update_me()` 内部已 commit 用户资料
- route 层再调 `_broadcast_profile_update_events()`

证据：

- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2/server/app/api/v1/users.py)
- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)

影响：

- 用户资料已经更新成功
- 但 profile realtime fanout 失败时，HTTP 路由仍会报 500

建议：

- profile mutation 的 HTTP 成功语义不应继续依赖 fanout 成败

### F-672：用户头像上传/重置也会在持久化成功后因为 profile fanout 失败而报 500

状态：已修复（2026-04-14）

现状：

- [users.py](/D:/AssistIM_V2/server/app/api/v1/users.py) 的 `upload_me_avatar()` / `reset_me_avatar()`
- 先完成 avatar state 持久化以及关联 generated group avatar 刷新
- 再广播 profile update 事件

证据：

- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2/server/app/api/v1/users.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)
- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)

影响：

- 头像 mutation 已经成功落库并触发群头像 side effect
- 但若 profile fanout 失败，HTTP 仍会错误返回 500

建议：

- avatar mutation 和 profile fanout 也应拆开正式 success contract

### F-673：`DELETE /auth/session` 已推进 `auth_session_version` 后，disconnect/fanout 失败仍会把 logout 报成 500

状态：已修复（2026-04-13）

修复说明：

- [auth.py](/D:/AssistIM_V2/server/app/api/v1/auth.py) 已把 logout 的 durable auth mutation 和后续 realtime/control fanout 拆开；`AuthService.logout()` 推进 `auth_session_version` 后，断连或 offline 广播失败只记录日志，不再把已生效 logout 改写成 HTTP 500
- 已新增 `test_logout_success_does_not_depend_on_realtime_disconnect` 覆盖 disconnect 失败时 logout 仍返回 `204`，旧 access token 也已经失效

### F-674：`POST /auth/login(force=true)` 会在踢旧连接前先旋转新 session 版本

状态：已修复（2026-04-13）

修复说明：

- `POST /auth/login(force=true)` 现在先执行旧 runtime disconnect，再旋转并提交新 session 版本；如果旧连接断开失败，路由会返回失败且不会推进新的 `auth_session_version`
- offline broadcast 仍是 disconnect 成功后的 best-effort fanout，不再决定 durable login mutation 是否已提交
- 已新增 `test_force_login_disconnects_existing_runtime_before_rotating_session` 覆盖断旧连接失败时旧 token 仍保持有效

### F-675：注册链路不是 failure-atomic，用户创建、默认头像赋值、session 旋转分三次提交

状态：已修复（2026-04-13）

修复说明：

- [auth_service.py](/D:/AssistIM_V2/server/app/services/auth_service.py) 的 `register()` 已收口成单事务边界：用户创建、默认头像赋值、`auth_session_version` 旋转全部使用 `commit=False`，最后统一 `commit()`，任一步异常都会 rollback
- [user_repo.py](/D:/AssistIM_V2/server/app/repositories/user_repo.py) 和 [avatar_service.py](/D:/AssistIM_V2/server/app/services/avatar_service.py) 已补可控提交参数，避免注册链中途提前提交半成品用户
- 已新增 `test_register_rolls_back_user_when_default_avatar_assignment_fails` 覆盖默认头像赋值失败时不会残留已创建账号

### F-676：认证三条请求 schema 仍没有 `extra=forbid`

状态：已修复（2026-04-13）

修复说明：

- [auth.py](/D:/AssistIM_V2/server/app/schemas/auth.py) 的 `RegisterRequest`、`LoginRequest`、`RefreshTokenRequest` 已统一补上 `ConfigDict(extra="forbid")`
- 已新增 `test_auth_request_models_reject_unknown_fields` 和 `test_auth_schema_contracts_are_strict_and_match_runtime_payloads`，覆盖 HTTP 路由和 schema 边界的 strict contract

### F-677：`LoginRequest` 没有最基本的长度/去空白约束

状态：已修复（2026-04-13）

修复说明：

- `LoginRequest.username` 现已补齐长度边界，并在 schema 入口先做 canonical strip
- `LoginRequest.password` 已补上和注册链一致的最小/最大长度约束
- 已新增 `test_auth_identity_inputs_are_canonicalized_and_validated` 覆盖空白用户名和过短密码拒绝

### F-678：`RefreshTokenRequest` 也没有长度或格式边界

状态：已修复（2026-04-13）

修复说明：

- `RefreshTokenRequest.refresh_token` 已补最小/最大长度边界，并在入口先 strip 再解 token
- 已新增 `test_auth_identity_inputs_are_canonicalized_and_validated` 覆盖带前后空白的 refresh token 仍可按 canonical 值工作

### F-679：认证响应的 `token_type` 与公开 schema 的默认值大小写不一致

状态：已修复（2026-04-13）

修复说明：

- 新增 [auth_contract.py](/D:/AssistIM_V2/server/app/core/auth_contract.py) 统一 auth contract 常量，`TokenPair.token_type` 与 `AuthService` 返回值都收口到 `Bearer`
- 已新增 `test_auth_schema_contracts_are_strict_and_match_runtime_payloads` 钉住 schema 默认值，避免再次和运行时 payload 漂移

### F-680：删除设备不会使该设备上的现有认证 runtime 失效

状态：已修复（2026-04-14）

现状：

- [devices.py](/D:/AssistIM_V2/server/app/api/v1/devices.py) 的 `delete_device()`
- 只删除 `UserDevice` 和预密钥材料
- 不会推进 `auth_session_version`
- 也不会断开该设备对应的现有 websocket/runtime
- 而 [security.py](/D:/AssistIM_V2/server/app/core/security.py) 的 access/refresh token 根本不携带 `device_id`

证据：

- [D:\AssistIM_V2\server\app\api\v1\devices.py](D:\AssistIM_V2/server/app/api/v1/devices.py)
- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)
- [D:\AssistIM_V2\server\app\core\security.py](D:\AssistIM_V2/server/app/core/security.py)

影响：

- 一个“已删除设备”上的现有登录态仍可能继续工作
- device registry 与真实 authenticated runtime 继续脱节

建议：

- 设备删除要么绑定 device-scoped auth，要么显式触发该设备 runtime 失效

### F-681：`register_device()` 每次都会 destructive replace 全部 one-time prekeys

状态：已修复（2026-04-14）

修复说明：

- `register_device()` 仍作为设备身份全量注册入口，但 device/prekey contract 已重新定义：首次/重注册必须提交完整 signed prekey 与 one-time prekey 库存，并通过签名校验。
- 增量补库存不再通过 register 旁路完成，而是由 `refresh_my_device_keys()` 追加新 prekey；重复 `prekey_id` 会显式拒绝，避免误把刷新建模成 destructive replace。

现状：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `register_device()`
- 每次注册都会调用 `replace_prekeys()`
- 这会先删光该 device 现有 prekeys，再插入新集合

证据：

- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- 设备重注册或重试会直接抹掉现有未消费 prekeys
- device register 和 key refresh 两条正式入口的语义明显分裂

建议：

- register_device 是否允许 destructive key reset，需要单独定义明确 contract

### F-682：服务端从未验证 signed prekey 签名是否真的匹配 `signing_key_public`

状态：已修复（2026-04-14）

修复说明：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的注册和 signed-prekey 刷新现在都会用 `signing_key_public` 验证 `signed_prekey.signature` 是否签在 `signed_prekey.public_key` 上。
- key material 同时要求 base64 解码后符合 Ed25519/X25519 固定长度。
- 已补 `test_device_registration_rejects_invalid_signed_prekey_signature`。

现状：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 里
- `register_device()` / `refresh_my_device_keys()`
- 只检查 `signed_prekey.key_id/public_key/signature` 非空
- 但从未验证 `signature` 是否真的由 `signing_key_public` 对该 prekey 签出

证据：

- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- 服务端当前接受的 signed prekey 只是“字段长得像”
- E2EE bootstrap 的核心信任前提没有被服务端 formalize

建议：

- signed prekey 注册/刷新至少要有正式的签名验证边界

### F-683：设备密钥材料 schema 只有 `min_length`，没有结构或上限约束

状态：已修复（2026-04-14）

现状：

- [device.py](/D:/AssistIM_V2/server/app/schemas/device.py) 的：
  - `identity_key_public`
  - `signing_key_public`
  - `signed_prekey.public_key`
  - `signed_prekey.signature`
  - `prekey.public_key`
- 基本都只有 `min_length=8`
- 没有 `max_length`，也没有结构/编码验证

证据：

- [D:\AssistIM_V2\server\app\schemas\device.py](D:\AssistIM_V2/server/app/schemas/device.py)

影响：

- device/key 正式入口会接受任意超长、任意格式的大块字符串
- E2EE formal boundary 仍停留在“看起来像字符串”

建议：

- key material schema 也应补长度与编码层面的正式约束

### F-684：发送好友请求后，`contact_refresh` fanout 失败仍会把 HTTP 请求报成 500

状态：已修复（2026-04-14）

现状：

- [friends.py](/D:/AssistIM_V2/server/app/api/v1/friends.py) 的 `send_request()`
- 先执行 `FriendService.create_request()`
- 再调用 `_broadcast_contact_refresh()`

证据：

- [D:\AssistIM_V2\server\app\api\v1\friends.py](D:\AssistIM_V2/server/app/api/v1/friends.py)
- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)

影响：

- 好友请求或 auto-accept 已经生效
- 但若 contact_refresh fanout 失败，HTTP 仍会误报失败

建议：

- 好友请求 mutation 的 HTTP 成功语义不应继续依赖 side-channel realtime fanout

### F-685：接受好友请求后，`contact_refresh` fanout 失败仍会把 HTTP 请求报成 500

状态：已修复（2026-04-14）

现状：

- [friends.py](/D:/AssistIM_V2/server/app/api/v1/friends.py) 的 `accept_request()`
- 先执行 `FriendService.accept_request()`
- 再调用 `_broadcast_contact_refresh()`

证据：

- [D:\AssistIM_V2\server\app\api\v1\friends.py](D:\AssistIM_V2/server/app/api/v1/friends.py)
- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)

影响：

- friendship 已创建成功
- 但 fanout 失败时，HTTP 仍会把已成功 mutation 报成失败

建议：

- accept_request 也应拆开 commit 与 fanout 的正式 contract

### F-686：拒绝好友请求后，`contact_refresh` fanout 失败仍会把 HTTP 请求报成 500

状态：已修复（2026-04-14）

现状：

- [friends.py](/D:/AssistIM_V2/server/app/api/v1/friends.py) 的 `reject_request()`
- 先执行 `FriendService.reject_request()`
- 再调用 `_broadcast_contact_refresh()`

证据：

- [D:\AssistIM_V2\server\app\api\v1\friends.py](D:\AssistIM_V2/server/app/api/v1/friends.py)
- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)

影响：

- request 状态已更新
- 但 route 仍可能因为 fanout 失败报 500

建议：

- reject_request 的 route-level success contract 也应与 realtime 解耦

### F-687：删除好友后，`contact_refresh` fanout 失败仍会把 HTTP 请求报成 500

状态：已修复（2026-04-14）

现状：

- [friends.py](/D:/AssistIM_V2/server/app/api/v1/friends.py) 的 `remove_friend()`
- 先执行 `FriendService.remove_friend()`
- 再广播 `friendship_removed`

证据：

- [D:\AssistIM_V2\server\app\api\v1\friends.py](D:\AssistIM_V2/server/app/api/v1/friends.py)
- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)

影响：

- friendship 已删除
- 但 route 仍会在 fanout 失败时把请求报成失败

建议：

- remove_friend 也应拆分 mutation success 与 side-channel realtime success

### R-089：`count_available_prekeys()` 通过全表加载再 `len()` 计数

状态：已修复（2026-04-14）

修复说明：

- [device_repo.py](/D:/AssistIM_V2/server/app/repositories/device_repo.py) 的 `count_available_prekeys()` 已改为数据库侧 `COUNT(*)`。
- 同文件新增 `count_available_prekeys_by_device_ids()`，供设备列表和 prekey bundle/claim 批量复用。

现状：

- [device_repo.py](/D:/AssistIM_V2/server/app/repositories/device_repo.py) 的 `count_available_prekeys()`
- 不是 `COUNT(*)`
- 而是先查出所有未消费 prekey 行，再 `len(list(...))`

证据：

- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- 设备一多、prekey 一多，单纯计数都会把整批行加载进内存
- device/prekey 链路有明显的无谓读放大

建议：

- 可用 prekey 数量应改成数据库侧聚合计数

### R-090：device list / prekey bundle / claim 链路都有 per-device N+1 计数与 signed-prekey 查询

状态：已修复（2026-04-14）

修复说明：

- [device_repo.py](/D:/AssistIM_V2/server/app/repositories/device_repo.py) 新增 `list_devices_by_ids()`、`get_active_signed_prekeys()`、`count_available_prekeys_by_device_ids()`。
- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `list_my_devices()`、`list_prekey_bundles()`、`claim_prekeys()` 已改为批量读取 signed-prekey 和 prekey count，不再逐 device 回查。

现状：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的：
  - `list_my_devices()`
  - `list_prekey_bundles()`
  - `claim_prekeys()`
- 都会对每个 device：
  - 单独查一次 `count_available_prekeys()`
  - 或再单独查一次 `get_active_signed_prekey()`

证据：

- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- 设备越多，这几条正式入口越会线性放大数据库查询数
- prekey bootstrap 与 device 管理都存在结构性 N+1

建议：

- 设备列表、bundle 列表、claim 返回应收口成批量聚合查询

### R-091：限流 key 只按 `client_host` 建，不区分账号或请求主体

状态：已修复（2026-04-13）

修复说明：

- [rate_limit.py](/D:/AssistIM_V2/server/app/core/rate_limit.py) 的限流 key 已从单纯 `key_prefix:client_host` 扩展为 `key_prefix:client_host:subject`
- `login/register` 会从请求体提取并 canonicalize `username`，`friend-request` 会提取目标用户主体，避免同一 NAT / 代理后的不同账号完全挤在同一个桶里
- 已新增 `test_rate_limiter_keys_login_attempts_by_canonical_subject`，并更新既有 rate limiter store 断言

### R-092：当前限流实现是进程内内存桶，多实例部署下没有全局一致性

状态：已修复（2026-04-13）

修复说明：

- [rate_limit.py](/D:/AssistIM_V2/server/app/core/rate_limit.py) 已新增 `DatabaseRateLimitStore`，固定窗口命中记录持久化到共享数据库表 `rate_limit_hits`
- [config.py](/D:/AssistIM_V2/server/app/core/config.py) 已新增 `RATE_LIMIT_STORE_BACKEND`，默认值为 `database`；`memory` 仍只作为显式单进程配置使用
- [main.py](/D:/AssistIM_V2/server/app/main.py) 会在应用创建时按 settings 配置全局 rate limiter store
- 已新增 [20260413_0012_rate_limit_hits.py](/D:/AssistIM_V2/server/alembic/versions/20260413_0012_rate_limit_hits.py) 建表迁移，并保留 store 侧 `CREATE TABLE IF NOT EXISTS` 兜底
- 已新增 `test_database_rate_limit_store_shares_counters_across_instances` 覆盖两个 store 实例共享同一数据库计数

### R-093：默认 CORS 组合是 `allow_origins='*' + allow_credentials=True`

状态：已修复（2026-04-13）

修复说明：

- [config.py](/D:/AssistIM_V2/server/app/core/config.py) 的默认 `CORS_ORIGINS` 已改成显式本地开发 origin，不再默认使用 `*`
- [main.py](/D:/AssistIM_V2/server/app/main.py) 会在配置包含 `*` 时自动关闭 `allow_credentials`，显式 origin 才启用 credentials
- 已新增 `test_create_app_disables_credentials_for_wildcard_cors` 覆盖 wildcard 与 explicit origin 两种配置

### R-094：group avatar 生成直接覆盖目标文件，没有临时文件或并发保护

状态：已修复（2026-04-14）

现状：

- [group_avatars.py](/D:/AssistIM_V2/server/app/media/group_avatars.py) 的 `build_group_avatar()`
- 直接 `image.save(target_path, format=\"PNG\")`
- 没有先写临时文件再原子替换
- 也没有文件锁或并发保护

证据：

- [D:\AssistIM_V2\server\app\media\group_avatars.py](D:\AssistIM_V2/server/app/media/group_avatars.py)

影响：

- 多个请求并发生成同一群头像时，读者可能看到半写入文件或互相覆盖结果
- group avatar 的读路径副作用继续缺少稳定并发 contract

建议：

- 生成头像应改成临时文件 + 原子替换，必要时再加并发保护

### F-708：`call_invite` 只会 fanout 给被叫，主叫自己的其它在线设备收不到权威外呼事件

状态：已修复（2026-04-14）

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `invite()`
- 成功时固定返回 `("call_invite", [recipient_id], payload)`
- [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 只会把这条事件发给 `target_user_ids`

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)

影响：

- 同账号多设备下，主叫侧只有发起呼叫的那台设备知道自己已经进入外呼
- 其它在线设备拿不到权威 `call_invite`，只能停留在“无通话”本地态

建议：

- `call_invite` 也应镜像到主叫侧其它在线设备，不能只通知被叫

### F-709：发起通话没有任何 sender-side ACK / canonical echo，主叫当前设备只能依赖本地 optimistic 状态

状态：已修复（2026-04-14）

现状：

- [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 对 `call_invite`
- 成功后只 `send_json_to_users(target_user_ids, ...)`
- 不会像 `chat_message` 那样给发起连接返回 ACK
- 也不会把 canonical `call_invite` 回送给当前连接

证据：

- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)

影响：

- 主叫当前设备在 `call_invite` 发出后拿不到“服务端已正式接收/建档”的权威确认
- 外呼建立仍然依赖本地 optimistic 状态，失败与成功边界继续模糊

建议：

- 通话发起也应有 sender-side canonical ACK / echo，不要继续只靠本地 optimistic 状态

### F-710：`call_invite` 是唯一把 `data.call_id` 视为可选、并回退到 outer `msg_id` 的正式通话命令

状态：已修复（2026-04-14）

现状：

- [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 处理 `call_invite` 时
- 用的是 `call_id=str(data.get("call_id") or msg_id)`
- 其它 `call_ringing/call_accept/call_reject/call_hangup/call_offer/call_answer/call_ice`
- 都统一要求 `data.call_id`

证据：

- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)

影响：

- 同一组正式通话命令在 `call_id` 的来源上继续分裂
- transport `msg_id` 和业务 `call_id` 仍被混在一起

建议：

- `call_invite` 也应显式要求 `data.call_id`，不要继续依赖 outer transport id 回填业务 id

### F-711：`call_invite` 会把缺失的 `media_type` 静默默认成 `voice`

状态：已修复（2026-04-14）

现状：

- [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 里处理 `call_invite`
- 直接传 `media_type=str(data.get("media_type") or "voice")`
- 也就是说 route 先给了默认值，service 再校验

证据：

- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)

影响：

- 发起通话时，“未明确声明媒体类型”和“明确发起语音通话”被折叠成同一条正式路径
- 通话正式入口继续依赖 route 层隐式默认，而不是显式 contract

建议：

- `media_type` 应作为 `call_invite` 的正式必填字段，而不是静默默认成 `voice`

### F-712：建私聊 schema 只约束列表长度，不约束每个 `participant_id` 的 strip / 非空 / 唯一性

状态：已修复（2026-04-14）

现状：

- [session.py](/D:/AssistIM_V2/server/app/schemas/session.py) 的 `CreateDirectSessionRequest.participant_ids`
- 只有 `min_length=1`
- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `_normalize_private_members()`
- 才会再逐项：
  - `strip()`
  - 去空值
  - 去掉自己
  - 去重

证据：

- [D:\AssistIM_V2\server\app\schemas\session.py](D:\AssistIM_V2/server/app/schemas/session.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- schema contract 和 service contract 继续分裂
- 调用方提交脏 participant 列表时，只会被 service 静默重写成另一组 canonical 成员

建议：

- direct create 的 participant 列表应在 schema/入口层就完成 strip、非空、唯一性约束

### F-713：建私聊的 `name` 没有长度上限，纯空白名称也会被当成正式会话名写入

状态：已修复（2026-04-14）

现状：

- [session.py](/D:/AssistIM_V2/server/app/schemas/session.py) 的 `CreateDirectSessionRequest.name`
- 没有 `max_length`
- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `create_private()`
- 直接用 `name or "Private Chat"`
- [session_repo.py](/D:/AssistIM_V2/server/app/repositories/session_repo.py) 的 `create()`
- 也不会再做 strip

证据：

- [D:\AssistIM_V2\server\app\schemas\session.py](D:\AssistIM_V2/server/app/schemas/session.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)

影响：

- 超长或纯空白 direct session 名称都还能进入正式存储
- 会话创建入口和群资料/用户资料入口的基本字符串约束继续不一致

建议：

- direct session `name` 应补长度上限与 strip/empty 归一化

### F-714：`GET /sessions` 没有分页或 size 边界

状态：已修复（2026-04-14）

现状：

- [sessions.py](/D:/AssistIM_V2/server/app/api/v1/sessions.py) 的 `list_sessions()`
- 没有 `page/size`
- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `list_sessions()`
- 会把当前用户全部会话一次性序列化返回

证据：

- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2/server/app/api/v1/sessions.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 会话越多，这条正式列表入口越容易退化成大 payload 和重序列化
- session list 仍停留在“全量快照一把返回”，没有正式窗口化边界

建议：

- session list 应补正式分页/窗口 contract

### F-715：`GET /groups` 同样没有分页或 size 边界

状态：已修复（2026-04-14）

现状：

- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `list_groups()`
- 没有 `page/size`
- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `list_groups()`
- 会把当前用户全部群一次性返回

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 群越多，这条正式列表入口越容易退化成大 payload + N+1 序列化
- 群列表 contract 仍然没有窗口化

建议：

- group list 也应补分页/size 边界

### F-716：`GET /sessions` 会为每个会话默认内联完整 `members[]`，没有轻量 summary contract

状态：已修复（2026-04-14）

现状：

- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `list_sessions()`
- 对每个 session 都固定 `serialize_session(..., include_members=True, ...)`
- 最终返回 payload 自带完整 `members[]`

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- session summary list 和 session detail 的 payload 边界继续模糊
- 左侧会话列表正式入口天然带着完整成员对象图，放大会更快

建议：

- `GET /sessions` 应先收口成轻量 summary；`members[]` 不应默认内联在列表里

### F-717：`GET /groups` 也会为每个群默认内联完整 `members[]`，列表和详情 contract 没有分层

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `list_groups()`
- 会对每个 group 调 `serialize_group(..., include_members=True, ...)`
- 列表 payload 自带完整 `members[]`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- group list 和 group detail 没有轻重分层
- 群成员多时，这条正式列表入口会天然膨胀

建议：

- `GET /groups` 也应先定义轻量 summary contract

### F-718：`/sessions/unread` 不复用 direct 可见性 gate，已被隐藏的异常私聊仍可能继续贡献 unread

状态：已修复（2026-04-14）

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `session_unread_counts()`
- 直接调用 `messages.unread_by_session_for_user(current_user.id)`
- [message_repo.py](/D:/AssistIM_V2/server/app/repositories/message_repo.py) 的 `unread_by_session_for_user()`
- 只按 `SessionMember` 和 `last_read_seq` 聚合
- 不像 [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `list_sessions()` 那样再过 `_is_visible_private_session()`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2/server/app/repositories/message_repo.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- direct 可见性模型继续没有真正下沉到 unread 统计链
- session list 已隐藏的异常私聊，仍可能在 unread snapshot 里留下 ghost unread

建议：

- unread 聚合也应复用同一套 direct 可见性 gate

### F-719：用户名唯一性仍是精确大小写匹配，`Alice` 和 `alice` 可并存为两个正式账号

状态：已修复（2026-04-13）

修复说明：

- [auth_contract.py](/D:/AssistIM_V2/server/app/core/auth_contract.py) 已把用户名 canonicalization 从 `NFKC + strip` 扩展为 `NFKC + strip + lower`，注册入口会把正式用户名写成小写 canonical identity
- [user_repo.py](/D:/AssistIM_V2/server/app/repositories/user_repo.py) 的 `get_by_username()` 已改为按 `lower(username)` 查找，大小写变体不会再绕过注册重复检查
- [models/user.py](/D:/AssistIM_V2/server/app/models/user.py) 已增加 `uq_users_username_lower` 表达式唯一索引，并新增 [20260413_0011_username_case_canonical.py](/D:/AssistIM_V2/server/alembic/versions/20260413_0011_username_case_canonical.py) / schema compatibility DDL 覆盖运行库升级
- 已新增 `test_username_identity_is_case_canonical_across_register_login_and_search` 覆盖 `Case.User` 注册为 `case.user`、大小写重复注册返回 409

### F-720：用户发现是 `ILIKE`，登录认证却是精确大小写匹配，发现链和认证链对 username 的语义分裂

状态：已修复（2026-04-13）

修复说明：

- 登录认证和注册重复检查现在都复用同一 lowercase canonical username 规则，发现链的大小写不敏感语义不再和认证链分裂
- 已新增 `test_username_identity_is_case_canonical_across_register_login_and_search` 覆盖 `CASE.USER` 可登录同一账号，并且 `/users/search?keyword=CASE.USER` 只返回 canonical `case.user`

### F-721：`GET /moments?user_id=...` 没有任何关系或可见性 gate，任意已登录用户都能查看指定用户动态

状态：已修复（2026-04-14）

现状：

- [moments.py](/D:/AssistIM_V2/server/app/api/v1/moments.py) 的 `list_moments()`
- 接受任意 `user_id`
- [moment_service.py](/D:/AssistIM_V2/server/app/services/moment_service.py) 的 `list_moments()`
- 直接 `self.moments.list_moments(user_id=user_id)`
- 没有任何 friendship / audience / visibility 检查

证据：

- [D:\AssistIM_V2\server\app\api\v1\moments.py](D:\AssistIM_V2/server/app/api/v1/moments.py)
- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)
- [D:\AssistIM_V2\server\app\repositories\moment_repo.py](D:\AssistIM_V2/server/app/repositories/moment_repo.py)

影响：

- 朋友圈用户时间线可见性完全没有正式边界
- 只要知道 user_id，任意登录用户都能拉取该用户 moments

建议：

- moments list 应先定义 audience / relationship contract，再决定 user feed 是否可见

### F-722：点赞 moment 只校验动态存在，不校验当前用户是否有查看/互动权限

状态：已修复（2026-04-14）

现状：

- [moment_service.py](/D:/AssistIM_V2/server/app/services/moment_service.py) 的 `like()`
- 只先 `_ensure_exists(moment_id)`
- 然后直接 `self.moments.like(moment_id, current_user.id)`

证据：

- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)
- [D:\AssistIM_V2\server\app\repositories\moment_repo.py](D:\AssistIM_V2/server/app/repositories/moment_repo.py)

影响：

- like 入口没有与可见性/audience 绑定
- 任意已登录用户只要知道 moment_id，就能正式点赞该动态

建议：

- 点赞前也应校验当前用户是否对该 moment 拥有查看/互动权限

### F-723：取消点赞同样只校验动态存在，不校验当前用户是否对该动态有互动权限

状态：已修复（2026-04-14）

现状：

- [moment_service.py](/D:/AssistIM_V2/server/app/services/moment_service.py) 的 `unlike()`
- 同样只 `_ensure_exists(moment_id)`
- 不校验当前用户与该动态之间的任何关系/可见性

证据：

- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)

影响：

- unlike 正式入口与 like 一样缺少 audience gate
- 朋友圈互动权限仍没有被建成正式 contract

建议：

- unlike 也应挂到同一套 moment visibility / interaction gate 上

### F-724：评论 moment 也只校验动态存在，不校验评论权限

状态：已修复（2026-04-14）

现状：

- [moment_service.py](/D:/AssistIM_V2/server/app/services/moment_service.py) 的 `comment()`
- 先 `_ensure_exists(moment_id)`
- 然后直接 `self.moments.comment(moment_id, current_user.id, content)`

证据：

- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)
- [D:\AssistIM_V2\server\app\repositories\moment_repo.py](D:\AssistIM_V2/server/app/repositories/moment_repo.py)

影响：

- 只要拿到 moment_id，任意登录用户都能正式评论
- moment interaction contract 继续没有 relationship / audience 边界

建议：

- 评论入口也应先校验是否允许当前用户对该 moment 互动

### F-725：`GET /moments` 在不带 `user_id` 时会直接返回全局 authenticated feed，没有正式 audience 模型

状态：已修复（2026-04-14）

现状：

- [moments.py](/D:/AssistIM_V2/server/app/api/v1/moments.py) 的 `list_moments()`
- `user_id` 默认 `None`
- [moment_repo.py](/D:/AssistIM_V2/server/app/repositories/moment_repo.py) 的 `list_moments()`
- 当 `user_id` 为空时就不加任何过滤，直接返回全表 moments

证据：

- [D:\AssistIM_V2\server\app\api\v1\moments.py](D:\AssistIM_V2/server/app/api/v1/moments.py)
- [D:\AssistIM_V2\server\app\repositories\moment_repo.py](D:\AssistIM_V2/server/app/repositories/moment_repo.py)

影响：

- 当前 authenticated 用户默认会拿到全局动态流，而不是基于关系、受众或产品规则裁剪后的 feed
- moment list 的正式 audience contract 仍然缺失

建议：

- 全局 feed 是否存在、对谁可见、按什么规则裁剪，必须先定义成正式 contract

### F-726：moments create / like / unlike / comment 四条正式互动入口都没有限流边界

状态：已修复（2026-04-14）

现状：

- [moments.py](/D:/AssistIM_V2/server/app/api/v1/moments.py) 的：
  - `POST /moments`
  - `POST /moments/{moment_id}/likes`
  - `DELETE /moments/{moment_id}/likes`
  - `POST /moments/{moment_id}/comments`
- 都没有像 auth / friend request 那样挂 `rate_limiter`

证据：

- [D:\AssistIM_V2\server\app\api\v1\moments.py](D:\AssistIM_V2/server/app/api/v1/moments.py)
- [D:\AssistIM_V2\server\app\core\rate_limit.py](D:\AssistIM_V2/server/app/core/rate_limit.py)

影响：

- moment 互动正式入口没有最基本的滥用保护
- 这条链路和 auth / friend 等其它正式入口的保护边界明显不一致

建议：

- moments create / interaction 也应补正式 rate-limit contract

### F-727：上传文件的 `original_name` 只做 `basename()`，没有控制字符或长度规范化

状态：已修复（2026-04-12）

修复说明：

- LocalMediaStorage._normalize_original_name() 已在 basename 之后过滤不可打印字符和路径/文件名危险字符
- 上传显示名最大长度已收口为 120 字符，截断时保留扩展名
- 已新增 test_file_upload_canonicalizes_name_and_derives_content_type 覆盖控制字符、路径分隔符、超长文件名和服务端派生 MIME

### F-688：`get_current_user()` 在 token 指向的用户已不存在时返回 `404 USER_NOT_FOUND`，不是统一的认证失效 `401`

状态：已修复（2026-04-13）

修复说明：

- [auth_dependency.py](/D:/AssistIM_V2/server/app/dependencies/auth_dependency.py) 现在会把“access token subject 已失效/用户不存在”统一收口成 `UNAUTHORIZED / 401`
- 已新增 `test_deleted_auth_subjects_return_unauthorized` 覆盖删除账号后旧 access token 的 `/auth/me` 路径

### F-689：refresh 链路在 refresh token 指向的用户已不存在时也返回 `404`，不是统一的 `401`

状态：已修复（2026-04-13）

修复说明：

- [auth_service.py](/D:/AssistIM_V2/server/app/services/auth_service.py) 的 `refresh()` 和 `refresh_access_token()` 已统一把失效 subject 收口成 `UNAUTHORIZED / 401`
- 已新增 `test_deleted_auth_subjects_return_unauthorized` 覆盖 HTTP refresh 和直接 service 调用两条链路

### F-690：认证用户名没有 strip/字符集约束，空白和控制字符都能进入正式身份

状态：已修复（2026-04-13）

修复说明：

- 新增 [auth_contract.py](/D:/AssistIM_V2/server/app/core/auth_contract.py) 收口认证用户名 contract；用户名现在会先做 `NFKC + strip`，再校验允许字符集为字母、数字、点、下划线和连字符
- `RegisterRequest` / `LoginRequest` 与 `AuthService` 已共同复用这套 canonicalization，注册写入和登录查找不再接受前后空白用户名
- 已新增 `test_auth_identity_inputs_are_canonicalized_and_validated` 覆盖 strip 后登录、非法空格用户名拒绝和规范化后的持久化结果

### F-691：注册昵称没有 strip 规则，纯空白昵称会被当成合法正式资料写入

状态：已修复（2026-04-13）

修复说明：

- 注册昵称现在会先 strip 再做长度校验，纯空白昵称会在 schema 边界直接被拒绝
- `AuthService.register()` 已复用同一 canonical nickname 规则，注册链和资料编辑链不再各走一套 normalization
- 已新增 `test_auth_identity_inputs_are_canonicalized_and_validated` 覆盖空白昵称拒绝
### F-692：`exclude_device_id` 是调用方可控的任意过滤器，调用方可以把目标用户设备静默从 bundle 列表里剔掉

状态：已修复（2026-04-14）

修复说明：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 现在只会在 `target_user_id == current_user.id` 时应用 `exclude_device_id`，并且要求该 device 是当前用户自己的 active device。
- 查询其它用户 bundle 时，调用方传入的 `exclude_device_id` 不再能过滤目标用户设备。

现状：

- [keys.py](/D:/AssistIM_V2/server/app/api/v1/keys.py) 的 `GET /keys/prekey-bundle/{user_id}`
- 直接接受 `exclude_device_id` query
- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `list_prekey_bundles()`
- 会原样把它传给 `list_active_devices_for_user(..., exclude_device_id=...)`
- 这条过滤没有绑定“当前请求发起方自己的 device_id”

证据：

- [D:\AssistIM_V2\server\app\api\v1\keys.py](D:\AssistIM_V2/server/app/api/v1/keys.py)
- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- 调用方可以通过手工传参，把目标用户的某台设备从返回 bundle 中静默隐藏
- direct 多设备加密 fanout 因此还能被调用方主动压缩成部分设备集

建议：

- `exclude_device_id` 如继续保留，应只允许过滤“当前请求方自己的当前设备”，不能继续做任意设备过滤器

### F-693：`list_prekey_bundles()` 会静默跳过缺 active signed prekey 的设备，返回 partial bundle 但不显式报错

状态：已修复（2026-04-14）

修复说明：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 已批量读取 active signed prekey；任一 active device 缺 signed prekey 会返回明确 `409`，不再静默跳过。

现状：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `list_prekey_bundles()`
- 遍历 active devices 时，只要 `get_active_signed_prekey()` 是 `None` 就 `continue`
- route 最终仍返回 `200 success`

证据：

- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)

影响：

- 目标账号某些设备的 E2EE bootstrap 已经坏掉时，调用方只会拿到一份看似成功但不完整的 bundle 列表
- 多设备加密因此会在正式入口上继续退化成“静默 partial fanout”

建议：

- bundle 返回应显式区分“完整成功”和“存在不可用设备”，不要继续把部分成功折叠成普通成功

### F-694：`claim_prekeys()` 会静默跳过不存在、inactive 或缺 active signed prekey 的设备

状态：已修复（2026-04-14）

修复说明：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `claim_prekeys()` 现在会先批量加载并校验所有目标 device。
- 目标不存在或 inactive 返回 `404`，缺 active signed prekey 返回 `409`，不再把部分失败折叠进成功列表。

现状：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `claim_prekeys()`
- 对每个 `device_id`：
  - device 不存在就 `continue`
  - inactive 就 `continue`
  - signed prekey 缺失也 `continue`
- 最终 route 仍返回普通 `success`

证据：

- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)

影响：

- 调用方拿到的是一份 silently filtered 结果，而不是每台设备的明确 claim 状态
- prekey claim 的正式入口没有 authoritative per-device success/failure contract

建议：

- claim 结果应显式返回每个目标 device 的状态，或在部分失败时给出正式错误

### F-695：`claim_prekeys()` 在 one-time prekey 已耗尽时仍返回 `200`，并把 `one_time_prekey=None` 混进成功结果

状态：已修复（2026-04-14）

修复说明：

- `claim_prekeys()` 现在要求每个目标 device 都实际 claim 到 one-time prekey；库存耗尽返回明确 `409`。
- 已补 `test_device_registration_and_prekey_claim_flow` 覆盖耗尽后不再返回 `one_time_prekey=None`。

现状：

- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 的 `claim_prekeys()`
- 只要 device 存在且 signed prekey 存在
- 即使 `claim_one_time_prekey()` 返回 `None`
- 也照样序列化 bundle 并加入成功结果

证据：

- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)
- [D:\AssistIM_V2\server\app\repositories\device_repo.py](D:\AssistIM_V2/server/app/repositories/device_repo.py)

影响：

- “成功 claim 到完整 bootstrap material”和“只拿到 signed prekey、one-time prekey 已耗尽”被混成同一类成功
- 调用方只能靠解析 payload 里的 `None` 自己猜状态

建议：

- one-time prekey 耗尽应有正式状态或错误语义，不应继续折叠进普通成功结果

### F-696：`PreKeyClaimRequest.device_ids` 允许空白和重复项，服务端再静默归一化/去重

状态：已修复（2026-04-14）

修复说明：

- [device.py](/D:/AssistIM_V2/server/app/schemas/device.py) 的 `PreKeyClaimRequest.device_ids` 已在 schema validator 中 strip、去空和去重。
- service 层保留同一 canonical 列表语义，正式 contract 不再把脏输入偷偷变成 partial result。

现状：

- [device.py](/D:/AssistIM_V2/server/app/schemas/device.py) 的 `PreKeyClaimRequest`
- 只约束 list 长度，不约束每个 `device_id` 的最小长度、strip 后非空或唯一性
- [device_service.py](/D:/AssistIM_V2/server/app/services/device_service.py) 里再逐项 `strip()`、去空值、去重

证据：

- [D:\AssistIM_V2\server\app\schemas\device.py](D:\AssistIM_V2/server/app/schemas/device.py)
- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)

影响：

- schema 口径和 service 口径继续分裂
- 客户端提交脏输入时，不会得到明确 validation error，而是被静默改写成另一组请求参数

建议：

- `device_ids` 的 item 级 strip、非空和唯一性应前移到 schema/入口层

### F-697：好友列表正式入口会把 email/phone/birthday/region/signature/status 一并暴露给所有好友

状态：已修复（2026-04-14）

修复说明：

- `GET /friends` 现已复用 public summary contract，不再暴露 email/phone/birthday/region/signature/status。

现状：

- [friend_service.py](/D:/AssistIM_V2/server/app/services/friend_service.py) 的 `list_friends()`
- 返回的不只是 `id/username/nickname/avatar`
- 还包括：
  - `email`
  - `phone`
  - `birthday`
  - `region`
  - `signature`
  - `gender`
  - `status`

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)

影响：

- 联系人正式入口已经等价于“好友可见完整 profile”
- 公开用户摘要、联系人摘要、完整私密资料三层边界继续没有正式收口

建议：

- 好友列表应先定义正式 summary contract，不要继续默认暴露完整 profile

### F-698：`GET /friends` 只是读列表，却会对每个好友执行 avatar backfill 写库

状态：已修复（2026-04-14）

现状：

- [friend_service.py](/D:/AssistIM_V2/server/app/services/friend_service.py) 的 `list_friends()`
- 会逐个 `get_by_id(friendship.friend_id)`
- 然后对每个好友调用 `avatars.backfill_user_avatar_state(friend)`

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- 好友列表读路径也会带持久化副作用
- 联系人域 read contract 继续和 avatar compat 写库逻辑耦合在一起

建议：

- `GET /friends` 不应继续通过读取去修数据库状态

### F-699：`GET /friends/requests` 也会在序列化 `from_user/to_user` 时触发 avatar backfill 写库

状态：已修复（2026-04-14）

现状：

- [friend_service.py](/D:/AssistIM_V2/server/app/services/friend_service.py) 的 `serialize_request()`
- 会分别 `get_by_id(sender_id)` 和 `get_by_id(receiver_id)`
- 然后对 sender / receiver 都执行 `avatars.backfill_user_avatar_state(...)`

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- 好友请求列表这条纯读取路径也会触发用户资料写回
- 联系人域“读路径写库”的问题已经不只出现在 `/users*`，好友请求链也被带进来了

建议：

- request 序列化应消费已收口的公开资料，不要在 GET 路径里继续做 avatar state 修补

### F-700：`GET /friends/requests` 没有分页或数量边界，会把全量历史 sent/received requests 一次性返回

状态：已修复（2026-04-14）

现状：

- [friends.py](/D:/AssistIM_V2/server/app/api/v1/friends.py) 的 `list_requests()`
- 没有 `page/size`
- [friend_repo.py](/D:/AssistIM_V2/server/app/repositories/friend_repo.py) 的 `list_requests_for_user()`
- 直接按时间倒序返回当前用户全部 sent/received requests

证据：

- [D:\AssistIM_V2\server\app\api\v1\friends.py](D:\AssistIM_V2/server/app/api/v1/friends.py)
- [D:\AssistIM_V2\server\app\repositories\friend_repo.py](D:\AssistIM_V2/server/app/repositories/friend_repo.py)

影响：

- 请求历史越长，这条正式入口越容易退化成大 payload + 大量序列化
- 联系人页 request 读取 contract 仍停留在“把全历史一把梭”而不是正式窗口化列表

建议：

- request 列表也应收口到正式分页 contract

### F-701：好友请求附言没有 strip 规则，纯空白 message 会被当成正式请求内容保存

状态：已修复（2026-04-14）

修复说明：

- friend request schema 已对 `message` 做 strip + empty-to-none 归一化。

现状：

- [friend.py](/D:/AssistIM_V2/server/app/schemas/friend.py) 的 `FriendRequestCreate.message`
- 没有 strip 或 empty-to-none 规则
- [friend_service.py](/D:/AssistIM_V2/server/app/services/friend_service.py) 的 `create_request()`
- 会把原始 `message` 直接传给 repo

证据：

- [D:\AssistIM_V2\server\app\schemas\friend.py](D:\AssistIM_V2/server/app/schemas/friend.py)
- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)

影响：

- `"   "` 这类纯空白附言会被保存成正式 request message
- request create 和其它较新的 profile/message 输入归一化规则继续分裂

建议：

- friend request message 应先 strip，再把空白值归一化成 `None`

### F-702：朋友圈发布内容没有 strip 规则，纯空白 moment 也会被当成合法内容创建

状态：已修复（2026-04-14）

修复说明：

- `MomentCreate.content` 已在 schema 入口 strip，并拒绝空白内容
- 已增加 `test_moment_create_schema_strips_content_and_rejects_invalid_payloads` 覆盖 strip 后落库和空白拒绝

原现状：

- [moment.py](/D:/AssistIM_V2/server/app/schemas/moment.py) 的 `MomentCreate.content`
- 只有 `min_length=1`
- [moment_service.py](/D:/AssistIM_V2/server/app/services/moment_service.py) 的 `create_moment()`
- 会直接把原始 `content` 写入 repo

证据：

- [D:\AssistIM_V2\server\app\schemas\moment.py](D:\AssistIM_V2/server/app/schemas/moment.py)
- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)
- [D:\AssistIM_V2\server\app\repositories\moment_repo.py](D:\AssistIM_V2/server/app/repositories/moment_repo.py)

影响：

- `"   "` 这种纯空白动态会被当成正式内容创建
- 朋友圈内容链路也没有和消息/资料输入复用同一套基本 normalization 规则

建议：

- moment content 应在入口层先 strip，再校验非空

### F-703：朋友圈评论内容同样没有 strip 规则，纯空白 comment 会被写进正式评论流

状态：已修复（2026-04-14）

修复说明：

- `MomentCommentCreate.content` 已在 schema 入口 strip，并拒绝空白内容
- 已增加 `test_moment_comment_schema_strips_content_and_rejects_invalid_payloads` 覆盖 strip 后落库和空白拒绝

原现状：

- [moment.py](/D:/AssistIM_V2/server/app/schemas/moment.py) 的 `MomentCommentCreate.content`
- 只有 `min_length=1`
- [moment_service.py](/D:/AssistIM_V2/server/app/services/moment_service.py) 的 `comment()`
- 会把原始 `content` 直接写进 repo

证据：

- [D:\AssistIM_V2\server\app\schemas\moment.py](D:\AssistIM_V2/server/app/schemas/moment.py)
- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)
- [D:\AssistIM_V2\server\app\repositories\moment_repo.py](D:\AssistIM_V2/server/app/repositories/moment_repo.py)

影响：

- 纯空白评论会被正式保存并计入 comment 流
- 朋友圈评论入口同样缺少最基本的 canonical content normalization

建议：

- comment content 也应统一做 strip + 非空校验

### F-704：`MomentCreate` 仍只有 `min_length`，没有 `max_length` 或 `extra=forbid`

状态：已修复（2026-04-14）

修复说明：

- `MomentCreate` 已补齐 `ConfigDict(extra="forbid")`
- 已为 moment content 增加 `MAX_MOMENT_CONTENT_LENGTH = 2_000` 上限
- 定向 API 测试已覆盖未知字段和超长内容返回 422

原现状：

- [moment.py](/D:/AssistIM_V2/server/app/schemas/moment.py) 的 `MomentCreate`
- 只声明了 `content: str = Field(min_length=1)`
- 没有长度上限，也没有 `model_config = ConfigDict(extra=\"forbid\")`

证据：

- [D:\AssistIM_V2\server\app\schemas\moment.py](D:\AssistIM_V2/server/app/schemas/moment.py)

影响：

- moment create 入口仍弱于仓库里较新的正式 schema 口径
- 大体积 payload 和未知字段会继续直接落到 service 层

建议：

- `MomentCreate` 也应补齐长度上限和 `extra=forbid`

### F-705：`MomentCommentCreate` 同样没有长度上限或 `extra=forbid`

状态：已修复（2026-04-14）

修复说明：

- `MomentCommentCreate` 已补齐 `ConfigDict(extra="forbid")`
- 已为 comment content 增加 `MAX_MOMENT_COMMENT_LENGTH = 1_000` 上限
- 定向 API 测试已覆盖未知字段和超长内容返回 422

原现状：

- [moment.py](/D:/AssistIM_V2/server/app/schemas/moment.py) 的 `MomentCommentCreate`
- 也只有 `content: str = Field(min_length=1)`

证据：

- [D:\AssistIM_V2\server\app\schemas\moment.py](D:\AssistIM_V2/server/app/schemas/moment.py)

影响：

- comment 正式入口仍缺少最基本的 schema 收口
- 朋友圈 create/comment 两条正式入口的输入 contract 一起偏松

建议：

- `MomentCommentCreate` 也应补齐上限与 `extra=forbid`

### F-706：`GET /moments` 没有分页或数量边界，而且会把每条动态的 comments/likes 一次性全部内联返回

状态：已修复（2026-04-14）

修复说明：

- `GET /moments` 已改为分页 envelope：`{total, page, size, items}`
- 列表页只返回 comment preview、`comment_count`、`comments_truncated`、`like_count` 和 `is_liked`
- 已新增 `GET /moments/{moment_id}` detail 入口承载完整 comments
- 客户端 `DiscoveryService` 已直接按分页 envelope 读取，不再兼容旧 list payload
- 已增加 `test_moment_list_returns_paged_summary_without_liker_roster` 和 `test_discovery_service_fetch_moments_requires_paged_envelope` 覆盖新 contract

原现状：

- [moments.py](/D:/AssistIM_V2/server/app/api/v1/moments.py) 的 `list_moments()`
- 没有 `page/size`
- [moment_service.py](/D:/AssistIM_V2/server/app/services/moment_service.py) 的 `list_moments()`
- 会先取整批 moments
- 再整批拉：
  - `comments_map`
  - `like_user_ids_map`
  - `users_map`
- 最终每条动态都内联完整 comments 和 liker ids

证据：

- [D:\AssistIM_V2\server\app\api\v1\moments.py](D:\AssistIM_V2/server/app/api/v1/moments.py)
- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)
- [D:\AssistIM_V2\server\app\repositories\moment_repo.py](D:\AssistIM_V2/server/app/repositories/moment_repo.py)

影响：

- feed 越大，这条正式入口越会退化成全量聚合和大 payload
- 朋友圈列表 contract 仍停留在“整页全展开对象图”，没有正式窗口化边界

建议：

- moments feed 应先定义正式分页 contract，再区分 summary 与 detail payload

### F-707：moment 列表会把每条动态的完整 `liked_user_ids` 原样返回给任意查看者

状态：已修复（2026-04-14）

修复说明：

- moment summary/detail payload 已移除 `liked_user_ids`
- 点赞状态只通过 `like_count` 和当前查看者相关的 `is_liked` 返回
- 客户端 discovery controller 已移除对旧 `liked_user_ids` / `likes` 字段的回退读取
- 已增加 API 测试断言列表和详情均不返回 `liked_user_ids`

原现状：

- [moment_service.py](/D:/AssistIM_V2/server/app/services/moment_service.py) 的 `serialize_moment()`
- 无论查看者是谁
- 都会把 `liked_user_ids` 整个列表写进返回 payload

证据：

- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)

影响：

- `like_count`、`is_liked` 和“完整 liker roster”被混进同一个正式 summary payload
- 点赞名单可见性没有被建模成单独的隐私/权限边界

建议：

- feed summary 应只返回 `like_count` 和当前查看者相关状态，完整 liker roster 不应默认随列表全量下发

### F-728：服务端公开输出 schema 大量游离于真实 route payload 之外，FastAPI 没有任何 `response_model` 在做正式约束

状态：已修复（2026-04-14）

现状：

- [server/app/api/v1](D:\AssistIM_V2/server/app/api/v1) 下当前正式 route
- 基本都只返回裸 `dict` + [success_response()](D:\AssistIM_V2/server/app/utils/response.py)
- 全仓没有一条 API route 使用 `response_model=...`
- 结果是现有 `*Out` schema 只剩“旁注文档”作用，真实公开 payload 不受任何运行时约束

证据：

- [D:\AssistIM_V2\server\app\api\v1](D:\AssistIM_V2/server/app/api/v1)
- [D:\AssistIM_V2\server\app\utils\response.py](D:\AssistIM_V2/server/app/utils/response.py)

影响：

- formal API contract 只能靠 service 返回的动态 dict 维持
- output schema 漂移时，FastAPI 不会给任何告警或自动收口

建议：

- 关键正式入口至少补 `response_model`
- 不再让 `*Out` schema 和真实 route payload 各走各的

### F-729：`success_response(data=None)` 会把“无 payload”静默改写成空对象 `{}`，把 no-content 和 empty-object 合并成同一种正式返回

状态：已修复（2026-04-14）

现状：

- [response.py](D:\AssistIM_V2/server/app/utils/response.py) 的 `success_response()`
- 现在固定返回：
  - `data if data is not None else {}`
- 所以像 moments `like/unlike` 这类“无返回体成功”和“真的返回空对象成功”
- 对客户端看起来是同一种 contract

证据：

- [D:\AssistIM_V2\server\app\utils\response.py](D:\AssistIM_V2/server/app/utils/response.py)
- [D:\AssistIM_V2\server\app\api\v1\moments.py](D:\AssistIM_V2/server/app/api/v1/moments.py)

影响：

- formal response contract 无法表达“无 payload”
- mutation route 的状态回显语义继续模糊

建议：

- 明确区分 `null`、`{}` 和 `204`
- 不要再用统一 helper 抹平这三种语义

### F-730：认证公开 schema `TokenPair` 已经落后于真实 auth 响应 payload

状态：已修复（2026-04-14）

现状：

- [auth.py](D:\AssistIM_V2\server/app/schemas/auth.py) 的 `TokenPair`
- 只有：
  - `access_token`
  - `refresh_token`
  - `token_type`
- 但 [auth_service.py](D:\AssistIM_V2\server/app/services/auth_service.py) 的真实 auth payload 还会返回：
  - `expires_in`
  - `refresh_expires_in`
  - `user`

证据：

- [D:\AssistIM_V2\server\app\schemas\auth.py](D:\AssistIM_V2/server/app/schemas/auth.py)
- [D:\AssistIM_V2\server\app\services\auth_service.py](D:\AssistIM_V2/server/app/services/auth_service.py)

影响：

- 公开 auth schema 已不能代表真实 route contract
- 认证 payload 的正式边界继续漂移

建议：

- 要么把 schema 扩成真实 contract
- 要么给 auth route 补单独 response model，而不是继续靠动态 dict

### F-731：`UserOut` 已经落后于真实 `/users/*` 返回值，正式 user contract 漂移

状态：已修复（2026-04-14）

现状：

- [user.py](D:\AssistIM_V2\server/app/schemas/user.py) 的 `UserOut`
- 不包含：
  - `created_at`
  - `updated_at`
- 但 [user_service.py](D:\AssistIM_V2\server/app/services/user_service.py) 的 `serialize_user()`
- 真实会把这两个字段一起公开返回

证据：

- [D:\AssistIM_V2\server\app\schemas\user.py](D:\AssistIM_V2/server/app/schemas/user.py)
- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)

影响：

- user formal schema 和真实 payload 已经分叉
- 客户端若按 schema 实现，会继续低估真实字段集

建议：

- 收口 `UserOut` 和 `serialize_user()` 的字段面

### F-732：`FriendOut` 已经不能代表 `/friends` 的真实返回 payload

状态：已修复（2026-04-14）

现状：

- [friend.py](D:\AssistIM_V2\server/app/schemas/friend.py) 的 `FriendOut`
- 只包含：
  - `id`
  - `username`
  - `nickname`
  - `avatar`
- 但 [friend_service.py](D:\AssistIM_V2\server/app/services/friend_service.py) 的 `list_friends()`
- 真实还会返回：
  - `avatar_kind`
  - `email`
  - `phone`
  - `birthday`
  - `region`
  - `signature`
  - `gender`
  - `status`

证据：

- [D:\AssistIM_V2\server\app\schemas\friend.py](D:\AssistIM_V2/server/app/schemas/friend.py)
- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)

影响：

- friends formal schema 已经失真
- 联系人公开 contract 继续只靠 service dict 维持

建议：

- 明确 `/friends` 是 summary 还是 full profile
- 然后让 schema 和 route payload 对齐

### F-733：`FriendRequestOut` 已经不能代表 `/friends/requests` 的真实返回 payload

状态：已修复（2026-04-14）

现状：

- [friend.py](D:\AssistIM_V2\server/app/schemas/friend.py) 的 `FriendRequestOut`
- 只建模了：
  - `request_id`
  - `sender_id`
  - `receiver_id`
  - `status`
  - `message`
  - `created_at`
- 但 [friend_service.py](D:\AssistIM_V2\server/app/services/friend_service.py) 的 `serialize_request()`
- 真实还会返回嵌套：
  - `from_user`
  - `to_user`

证据：

- [D:\AssistIM_V2\server\app\schemas\friend.py](D:\AssistIM_V2/server/app/schemas/friend.py)
- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)

影响：

- 好友请求 formal schema 和真实 payload 分裂
- 请求详情链继续只能靠动态字典约定

建议：

- 明确 request summary / detail contract
- 把 `from_user` / `to_user` 正式建模进去

### F-734：`SessionOut` 已经不能代表 `/sessions` 的真实返回 payload

状态：已修复（2026-04-14）

现状：

- [session.py](D:\AssistIM_V2\server/app/schemas/session.py) 的 `SessionOut`
- 已经落后于 [session_service.py](D:\AssistIM_V2\server/app/services/session_service.py) 的 `serialize_session()`
- 真实 payload 还会返回：
  - `group_id`
  - `owner_id`
  - `group_announcement`
  - `announcement_message_id`
  - `announcement_author_id`
  - `announcement_published_at`
  - `group_note`
  - `my_group_nickname`

证据：

- [D:\AssistIM_V2\server\app\schemas\session.py](D:\AssistIM_V2/server/app/schemas/session.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 会话 formal schema 已经无法覆盖真实 group/direct 混合 payload
- 会话列表和详情 contract 继续依赖隐式约定

建议：

- 把 session public contract 分成最小 summary 和 detail
- 不要继续让 schema 落后于实际返回值

### F-735：`SessionMemberOut` 已经不能代表真实会话成员 payload

状态：已修复（2026-04-14）

现状：

- [session.py](D:\AssistIM_V2\server/app/schemas/session.py) 的 `SessionMemberOut`
- 只包含：
  - `id`
  - `nickname`
  - `username`
  - `avatar`
  - `gender`
  - `joined_at`
- 但 [session_service.py](D:\AssistIM_V2\server/app/services/session_service.py) 真实还会返回：
  - `group_nickname`
  - `role`

证据：

- [D:\AssistIM_V2\server\app\schemas\session.py](D:\AssistIM_V2/server/app/schemas/session.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- session members formal contract 和真实群成员 contract 已经脱节
- 群成员 role / 群内昵称继续靠隐式字段存在

建议：

- 成员 payload 也应拆出 shared member contract，而不是继续靠 service 自由拼装

### F-736：`GroupOut` 已经不能代表 `/groups` 的真实返回 payload

状态：已修复（2026-04-14）

现状：

- [group.py](D:\AssistIM_V2\server/app/schemas/group.py) 的 `GroupOut`
- 不包含真实 route payload 里的：
  - `member_count`
  - `created_at`
  - `group_note`
  - `my_group_nickname`
  - `members`
- 但 [group_service.py](D:\AssistIM_V2\server/app/services/group_service.py) 的 `serialize_group()`
- 真实都会返回这些字段

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 群 formal schema 已经明显落后
- group summary / detail / self-scoped 字段仍没有正式分层

建议：

- 先定义 group summary / detail / self-profile 三套 contract
- 再让 schema 和 route payload 对齐

### F-737：`MomentOut` 已经不能代表 `/moments` 的真实返回 payload

状态：已修复（2026-04-14）

现状：

- [moment.py](D:\AssistIM_V2\server/app/schemas/moment.py) 的 `MomentOut`
- 只有：
  - `id`
  - `user_id`
  - `content`
- 但 [moment_service.py](D:\AssistIM_V2\server/app/services/moment_service.py) 的 `serialize_moment()`
- 真实还会返回：
  - `created_at`
  - `username`
  - `nickname`
  - `avatar`
  - `author`
  - `comments`
  - `like_count`
  - `comment_count`
  - `liked_user_ids`
  - `is_liked`

证据：

- [D:\AssistIM_V2\server\app\schemas\moment.py](D:\AssistIM_V2/server/app/schemas/moment.py)
- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)

影响：

- moments formal schema 已经失去描述能力
- feed contract 继续完全依赖 service 动态字典

建议：

- 先区分 moment summary / detail / interaction payload
- 再把 schema 拉回真实 contract

### F-738：`MomentCommentOut` 已经不能代表 comment 正式返回 payload

状态：已修复（2026-04-14）

现状：

- [moment.py](D:\AssistIM_V2\server/app/schemas/moment.py) 的 `MomentCommentOut`
- 只有：
  - `id`
  - `moment_id`
  - `user_id`
  - `content`
- 但 [moment_service.py](D:\AssistIM_V2\server/app/services/moment_service.py) 的 `serialize_comment()`
- 真实还会返回：
  - `created_at`
  - `username`
  - `nickname`
  - `avatar`

证据：

- [D:\AssistIM_V2\server\app\schemas\moment.py](D:\AssistIM_V2/server/app/schemas/moment.py)
- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)

影响：

- comment formal schema 已经与真实返回值分叉
- 评论链没有单一 authoritative output contract

建议：

- comment response 也应正式建模，不要继续让 schema 形同虚设

### F-739：`GET /calls/ice-servers` 没有任何对应的公开输出 schema，ICE payload contract 只存在于 service 动态字典里

状态：已修复（2026-04-14）

现状：

- [calls.py](D:\AssistIM_V2\server/app/api/v1/calls.py) 的 `get_ice_servers()`
- 直接返回 [call_service.py](D:\AssistIM_V2\server/app/services/call_service.py) 里的动态 payload
- 当前没有任何 `CallIceServersOut` 一类 schema 在描述：
  - `ice_servers`
  - `generated_at`
  - `credential_mode`
  - `ttl_seconds`
  - `expires_at`

证据：

- [D:\AssistIM_V2\server\app\api\v1\calls.py](D:\AssistIM_V2/server/app/api/v1/calls.py)
- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)

影响：

- 通话前置 REST contract 完全靠 service dict 维持
- ICE/TURN payload 以后继续扩字段时没有正式边界

建议：

- 给 `/calls/ice-servers` 补独立 output schema

### F-740：文件公开响应没有单一 canonical 字段集，而是同时暴露 `url/file_url`、`mime_type/file_type`、`original_name/file_name/name`

状态：已修复（2026-04-12）

修复说明：

- FileService.serialize_file() 已把公开字段收口为 id/url/mime_type/original_name/size_bytes/created_at
- upload-result 与 list-result 不再返回 file_url/file_type/file_name/name 等 alias
- 客户端 FileService.upload_file() 和 build_remote_attachment_extra() 已改为只读取 canonical 上传字段
- 已更新 server/client 文件上传与附件 extra 回归用例

### F-741：文件公开响应把同一份传输元数据同时放在顶层和嵌套 `media` 里，contract 继续重复

状态：已修复（2026-04-12）

修复说明：

- FileService.serialize_file() 已移除公开响应里的 media 嵌套镜像
- 文件公开响应只保留顶层 canonical summary 字段，聊天附件 extra 的 media 仅由客户端发送消息时重新构造
- 已更新 test_file_upload_returns_normalized_media_metadata_and_list_roundtrips 覆盖 upload/list payload 不再包含 media

### F-742：`FileOut` 把 alias 泛滥和 internal/public 混合字段直接固化进公开 schema

状态：已修复（2026-04-12）

修复说明：

- FileOut 已收口为 id/url/mime_type/original_name/size_bytes/created_at
- storage_provider/storage_key/user_id/media 和 alias 字段已从公开 schema 移除

### F-743：点赞已点赞动态时仍返回统一成功，moments like 缺少显式 no-op 语义

状态：已修复（2026-04-12）

修复说明：

- MomentRepository.like() 已返回 changed bool，重复点赞返回 False
- MomentService.like() / POST /moments/{id}/likes 已回显 {liked: true, changed: bool}
- 已新增 test_moment_like_and_unlike_echo_state_changes 覆盖首次点赞和重复点赞

### F-744：取消点赞未点赞动态时仍返回统一成功，moments unlike 缺少显式 no-op 语义

状态：已修复（2026-04-12）

修复说明：

- MomentRepository.unlike() 已返回 changed bool，重复取消点赞返回 False
- MomentService.unlike() / DELETE /moments/{id}/likes 已回显 {liked: false, changed: bool}
- 已新增 test_moment_like_and_unlike_echo_state_changes 覆盖首次取消点赞和重复取消点赞

### F-745：moment 正式返回把作者资料同时放在顶层和嵌套 `author` 里，author contract 重复

状态：已修复（2026-04-12）

修复说明：

- MomentService.serialize_moment() 已移除顶层 username/nickname/avatar
- moment 作者信息只保留 author 子结构
- 已新增 test_moment_and_comment_author_payloads_are_canonical 覆盖 create/list moment payload

### F-746：comment payload 的作者 shape 和 moment payload 的作者 shape 不一致

状态：已修复（2026-04-12）

修复说明：

- MomentService.serialize_comment() 已移除顶层 username/nickname/avatar
- comment 作者信息已对齐为 author 子结构
- MomentOut / MomentCommentOut 已补充共享的 MomentAuthorOut
- 已新增 test_moment_and_comment_author_payloads_are_canonical 覆盖 comment route 与 list 中嵌套 comments

### F-747：`GET /files` 和 `POST /files/upload` 没有 summary/detail 分层，两个正式入口都直接返回同一份 internal-heavy 文件详情 payload

状态：已修复（2026-04-12）

修复说明：

- FileService.list_files() 已改用 serialize_file_summary()，列表返回 id/url/mime_type/original_name/size_bytes
- POST /files/upload 已改用 serialize_upload_result()，上传结果在 summary 基础上额外返回 created_at
- FileSummaryOut / FileOut 已拆成 summary 与 upload-result 两套 schema
- 已更新 test_file_upload_returns_normalized_media_metadata_and_list_roundtrips 覆盖 list summary 不再与 upload result 完全同形

### F-748：建私聊命中已有会话时仍返回普通成功，正式入口没有 `created/reused` 语义

状态：已修复（2026-04-12）

修复说明：

- SessionService.create_private() 已在新建成功时回显 created=true/reused=false
- 命中已有 direct_key 或并发唯一键冲突回退到已有会话时，回显 created=false/reused=true
- 已新增 test_create_direct_session_echoes_created_or_reused 覆盖首次创建和复用旧私聊

### F-749：发好友请求命中已有 outgoing pending 时仍返回普通成功，联系人正式入口缺少显式 no-op 语义

状态：已修复（2026-04-12）

修复说明：

- FriendService.create_request() 已在新请求时回显 action=request_created、created=true、changed=true
- 命中已有 outgoing pending 时回显 action=request_reused、created=false、changed=false
- 已新增 test_friend_request_create_echoes_reused_and_auto_accept_actions 覆盖重复发送好友请求 no-op 语义

### F-750：发好友请求命中 incoming pending 时会自动接受，但公开返回仍是 request payload，正式动作语义混合

状态：已修复（2026-04-12）

修复说明：

- FriendService.create_request() 命中 incoming pending 自动接受时已回显 action=friendship_created、changed=true
- 自动接受响应已附带 friendship={is_friend, friend_id}，显式表达实际建立好友关系的结果
- friends route 的 contact_refresh reason 已优先按 action=friendship_created 判定
- 已新增 test_friend_request_create_echoes_reused_and_auto_accept_actions 覆盖 incoming pending 自动接受

### F-751：群 mutation 路由家族没有统一返回 contract，同一资源会返回四种不同成功 shape

状态：已修复（2026-04-14）

修复说明：

- 群 mutation 已统一返回 `{group, mutation}` contract，`mutation.action` 明确表达 `created/profile_updated/member_added/member_removed/member_role_updated/left/deleted/ownership_transferred`
- `delete_group/remove_member/leave_group` 不再返回 `204` 或裸 `status`，删除/离群类动作以 `group: null` 或更新后的 group snapshot 搭配 mutation meta 表达 committed 结果
- `update_group_profile()` 的公告 side-effect 元数据已纳入 `mutation.announcement`，不再作为另一套 top-level shape
- 桌面端 contact controller 已改为只解析新的 group mutation result，移除删除后再回查的旧跟随逻辑
- 已补 `test_group_remove_member_returns_canonical_mutation_result`，并更新 group/chat/client 边界测试覆盖新 contract

现状：

- [groups.py](D:\AssistIM_V2\server/app/api/v1/groups.py)
- 现在同一组群 mutation 路由会返回：
  - 纯 `group` 对象：`create_group/get_group/update_group_profile/transfer_group`
  - `{"status","group"}`：`add_member/update_member_role`
  - `{"status":"left"}`：`leave_group`
  - `204 No Content`：`delete_group/remove_member`

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- group formal mutation contract 已经碎成多套 shape
- 客户端要按具体路由分别写解析和 follow-up

建议：

- 群 mutation 至少统一成“canonical group snapshot + optional mutation meta”
- 不要继续混用四种返回风格

### F-752：`update_my_group_profile()` 是 self-scoped mutation，却返回完整共享群快照

状态：已修复（2026-04-12）

现状：

- [group_service.py](D:\AssistIM_V2\server/app/services/group_service.py) 的 `update_my_group_profile()`
- 实际修改的是：
  - `note`
  - `my_group_nickname`
- 但最终返回的是 `serialize_group(group, include_members=True, current_user_id=...)`
- route 层 [groups.py](D:\AssistIM_V2\server/app/api/v1/groups.py) 直接把这整份共享群快照公开返回

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- self-scoped mutation 和 shared group snapshot 继续混在同一返回 contract 里
- 调用方拿不到一个干净的 self-profile result

建议：

- `/groups/{id}/me` 应返回 self-scoped canonical payload
- 不要继续复用完整 shared group detail

### F-753：`update_group_profile()` 会丢掉 service 侧已有的 announcement side-effect 元数据，只返回 group snapshot

状态：已修复（2026-04-12）

现状：

- [group_service.py](D:\AssistIM_V2\server/app/services/group_service.py) 的 `update_group_profile()`
- service 已经生成：
  - `group`
  - `announcement_message_id`
  - `participant_ids`
- 但 route 层 [groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- 最终只 `return success_response(result.group)`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- mutation 已经产生的正式 side effect 元数据在公开响应里被静默吞掉
- route 返回值和真实领域动作结果继续分裂

建议：

- 要么只保留纯共享资料 PATCH 语义
- 要么把 announcement side effect 明确纳入正式返回

### F-754：消息 route 家族没有统一 mutation contract，`send/list` 返回 `MessageOut`，`edit/recall` 返回事件 delta，`delete` 返回 `204`

状态：部分修复（2026-04-12）

现状：

- [messages.py](D:\AssistIM_V2\server/app/api/v1/messages.py)
- `list_messages()` / `send_message()`
- 返回的是 canonical `serialize_message(...)`
- `edit_message()` / `recall_message()`
- 返回的是 event-style delta payload
- `delete_message()` 已改为返回 committed `message_delete` event payload
- `send/list` 的 canonical `MessageOut` 与 `edit/recall` 的 event delta 主 contract 仍未统一

证据：

- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2/server/app/api/v1/messages.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 同一消息资源家族没有单一 mutation output contract
- 客户端必须按每条 route 单独分支解析

建议：

- 统一消息 mutation 的正式响应风格
- 至少明确“canonical message snapshot”和“event delta”哪个是主 contract

### F-755：`read_message_batch()` 的成功 payload 会随 `advanced` 分支分裂成两种 shape

状态：已修复（2026-04-12）

现状：

- [message_service.py](D:\AssistIM_V2\server/app/services/message_service.py) 的 `batch_read()`
- 如果 read cursor 真正前进
- 会补：
  - `event_seq`
  - `advanced`
  - 以及广播相关字段
- 如果没有前进
- 返回的只是另一种较小 shape

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2/server/app/repositories/message_repo.py)

影响：

- 同一正式 read endpoint 的成功返回不是单一 shape
- 调用方需要额外依赖 `advanced` 才知道如何解释 payload

建议：

- 已读批处理应返回稳定的 canonical result
- 不要再让 `advanced` 改变整体 shape

### F-756：`read_message_batch()` 即使没有推进任何游标，也会返回统一 `success=true`，缺少显式 no-op 语义

状态：已修复（2026-04-12）

现状：

- [message_service.py](D:\AssistIM_V2\server/app/services/message_service.py) 的 `batch_read()`
- [message_repo.py](D:\AssistIM_V2\server/app/repositories/message_repo.py) 的 `_advance_read_cursor()`
- 当 `target_seq <= current_seq`
- 只会返回 `advanced=False`
- route 层仍统一回 `success_response(data)`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2/server/app/repositories/message_repo.py)

影响：

- “真正推进已读游标”和“纯 no-op 重复提交”共享同一种成功语义
- 客户端拿不到正式 state-changed / no-op 区分

建议：

- read mutation 应显式回显 `advanced/noop`

### F-757：`MessageReadBatch` 请求 schema 没有 `extra=forbid`

状态：已修复（2026-04-12）

现状：

- [message.py](D:\AssistIM_V2\server/app/schemas/message.py) 的 `MessageReadBatch`
- 只是裸 `BaseModel`
- 没有 `ConfigDict(extra="forbid")`

证据：

- [D:\AssistIM_V2\server\app\schemas\message.py](D:\AssistIM_V2/server/app/schemas/message.py)

影响：

- 已读正式入口仍会静默吞掉未知字段
- read contract 严格度落后于较新的 schema

建议：

- `MessageReadBatch` 也应统一到 `extra=forbid`

### F-758：`MessageReadBatch` 的 `session_id/message_id` 没有长度或去空白约束，关键标识仍靠 service 层兜底

状态：已修复（2026-04-12）

现状：

- [message.py](D:\AssistIM_V2\server/app/schemas/message.py) 的 `MessageReadBatch`
- `session_id` 和 `message_id` 都是裸 `str`
- 没有：
  - `min_length`
  - `max_length`
  - `strip`

证据：

- [D:\AssistIM_V2\server\app\schemas\message.py](D:\AssistIM_V2/server/app/schemas/message.py)

影响：

- 已读正式入口仍接受空白或异常长标识
- 关键 id 合法性继续后移到 service/repo 才暴露

建议：

- 把 id 规范化前移到 schema

### F-759：建群成员列表的 item 级 strip / 去空 / 去重仍藏在 service 里，正式 schema 没有收口

状态：已修复（2026-04-12）

现状：

- [group.py](D:\AssistIM_V2\server/app/schemas/group.py) 的 `GroupCreate`
- `member_ids` / `members` 都只是 `list[str]`
- [group_service.py](D:\AssistIM_V2\server/app/services/group_service.py) 的 `_normalize_group_members()`
- 再逐项：
  - `strip()`
  - 去空值
  - 去重
  - 去掉当前用户重复项

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 群成员列表的 canonicalization 仍是隐式 service 逻辑
- schema 无法表达真正的正式成员输入 contract

建议：

- 成员列表的 item 级规则应前移到 schema/入口层

### F-760：建私聊 `participant_ids` 的 item 级 strip / 去空 / 去重仍藏在 service 里，正式 schema 没有收口

状态：已修复（2026-04-12）

修复说明：

- `CreateDirectSessionRequest.participant_ids` 已改为 `SessionIdentifier` item 类型，在 schema 层执行 strip、非空和长度上限约束
- schema validator 已对 participant 列表去重，并要求归一化后恰好一个参与者
- 已有 `test_create_direct_session_requires_exactly_one_normalized_participant` 覆盖空白、超长、非字符串、未知字段、去空白和去重场景

原现状：

- [session.py](D:\AssistIM_V2\server/app/schemas/session.py) 的 `CreateDirectSessionRequest`
- `participant_ids` 只是 `list[str]`
- [session_service.py](D:\AssistIM_V2\server/app/services/session_service.py) 的 `_normalize_private_members()`
- 再逐项：
  - `strip()`
  - 去空值
  - 去重
  - 去掉当前用户自己

证据：

- [D:\AssistIM_V2\server\app\schemas\session.py](D:\AssistIM_V2/server/app/schemas/session.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

修复前影响：

- direct create 的正式成员输入 contract 继续依赖隐式 service 清洗
- schema 不能表达真正的 participant canonicalization

修复建议：

- `participant_ids` 的 item 级规则应前移到 schema/入口层

### F-761：`GroupMemberAdd.user_id` 没有最基本的长度或去空白约束

状态：已修复（2026-04-12）

修复说明：

- `GroupMemberAdd.user_id` 已改为 `GroupIdentifier`，在 schema 层执行 strip、非空和长度上限约束
- 已有 `test_group_member_and_profile_schemas_reject_extra_fields` 覆盖空白、超长、非字符串和未知字段场景

原现状：

- [group.py](D:\AssistIM_V2\server/app/schemas/group.py) 的 `GroupMemberAdd.user_id`
- 只是裸 `str`
- 没有长度边界，也没有 strip 归一化

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)

修复前影响：

- add-member 正式入口仍接受空白/异常长目标 id
- 关键标识合法性继续后移到 service 层

修复建议：

- `user_id` 应补基础长度和归一化约束

### F-762：`GroupTransferOwner.new_owner_id` 也没有最基本的长度或去空白约束

状态：已修复（2026-04-12）

修复说明：

- `GroupTransferOwner.new_owner_id` 已改为 `GroupIdentifier`，在 schema 层执行 strip、非空和长度上限约束
- 已有 `test_group_member_and_profile_schemas_reject_extra_fields` 覆盖空白与超长 transfer-owner 目标

原现状：

- [group.py](D:\AssistIM_V2\server/app/schemas/group.py) 的 `GroupTransferOwner.new_owner_id`
- 同样只是裸 `str`

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)

修复前影响：

- transfer-owner 正式入口仍接受空白/异常长 id
- 群主转移目标的 canonicalization 没有在 schema 层收口

修复建议：

- `new_owner_id` 也应补基础长度和归一化约束

### F-763：`GroupMemberRoleUpdate.role` 没有 schema 级枚举约束，角色合法性仍靠 service 私下收口

状态：已修复（2026-04-12）

修复说明：

- `GroupMemberRoleUpdate.role` 已改为 `GroupMemberRole = Literal["member", "admin"]`
- schema 层会先对字符串角色做 strip/lower，再交给 Literal 枚举校验
- 已有 `test_group_role_update_requires_owner_and_disallows_owner_role_change` 覆盖非法角色、非字符串和缺失角色

原现状：

- [group.py](D:\AssistIM_V2\server/app/schemas/group.py) 的 `GroupMemberRoleUpdate.role`
- 只是普通 `str`
- 没有 enum / pattern
- 当前合法角色集合仍由 [group_service.py](D:\AssistIM_V2\server/app/services/group_service.py) 的内部规范化逻辑决定

证据：

- [D:\AssistIM_V2\server\app\schemas\group.py](D:\AssistIM_V2/server/app/schemas/group.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

修复前影响：

- 角色 mutation 的正式 contract 不能从 schema 直接看出
- route 入口和 service 内部规则继续分裂

修复建议：

- 角色集合应在 schema 层显式建模

### F-764：`DeviceKeysRefreshRequest` 不能表达“`signed_prekey` 或 `prekeys` 至少一项存在”的正式约束

状态：已修复（2026-04-12）

修复说明：

- `DeviceKeysRefreshRequest` 已通过 schema validator 明确要求 `signed_prekey` 或 `prekeys` 至少一项存在
- 已补充回归测试覆盖空请求、空 `prekeys`、仅刷新 `signed_prekey`、仅追加 `prekeys`

原现状：

- [device.py](D:\AssistIM_V2\server/app/schemas/device.py) 的 `DeviceKeysRefreshRequest`
- 允许：
  - `signed_prekey=None`
  - `prekeys=[]`
- 真正的“至少要有一项”检查
- 仍在 [device_service.py](D:\AssistIM_V2\server/app/services/device_service.py) 的 `refresh_my_device_keys()` 里手工抛错

证据：

- [D:\AssistIM_V2\server\app\schemas\device.py](D:\AssistIM_V2/server/app/schemas/device.py)
- [D:\AssistIM_V2\server\app\services\device_service.py](D:\AssistIM_V2/server/app/services/device_service.py)

修复前影响：

- refresh-device-keys 的正式请求 contract 无法从 schema 直接读出
- schema 和 service 继续分担同一个基本必填约束

修复建议：

- 用 schema validator 显式建模 “至少一项存在”

### F-765：用户 route 家族没有统一的 collection/detail contract，`/users/search`、`/users`、`/users/{id}`、`/auth/me` 现在是四种不同组织方式

状态：已修复（2026-04-14）

修复说明：

- `/users` 已改为与 `/users/search` 同类的 `{total,page,size,items}` collection envelope
- `/users` 和 `/users/{id}` 使用 canonical public user summary，不再泄漏 `email/phone/created_at` 等 self detail 字段
- `/auth/me` 明确保留 self detail contract，返回建立在 public summary 之上的当前用户详情
- 已补 `test_user_routes_use_collection_and_public_detail_contracts` 覆盖 collection、public detail 和 self detail 三者边界

现状：

- [users.py](D:\AssistIM_V2\server/app/api/v1/users.py) 的：
  - `/users/search` 返回 `{total,page,size,items}`
  - `/users` 返回数组
  - `/users/{id}` 返回单对象
- [auth.py](D:\AssistIM_V2\server/app/api/v1/auth.py) 的 `/auth/me`
- 又复用同一份 full user payload

证据：

- [D:\AssistIM_V2\server\app\api\v1\users.py](D:\AssistIM_V2/server/app/api/v1/users.py)
- [D:\AssistIM_V2\server\app\api\v1\auth.py](D:\AssistIM_V2/server/app/api/v1/auth.py)
- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)

影响：

- 用户正式 API 没有统一的 collection/detail 层级
- “目录搜索”“目录列表”“公开详情”“当前用户详情”继续共享或错用同一 full profile

建议：

- 给 user domain 拆出 search summary、public detail、self detail 三套正式 contract

### F-766：好友 route 家族没有统一的 relationship contract，列表、检查、请求 mutation、删除现在是四种不同返回风格

状态：已确认

现状：

- [friends.py](D:\AssistIM_V2\server/app/api/v1/friends.py)
- 现在同一组好友 route 会返回：
  - `/friends`：好友 full profile 数组
  - `/friends/check/{id}`：`{"is_friend": bool}`
  - request create/accept/reject：request payload
  - `DELETE /friends/{id}`：`204`

证据：

- [D:\AssistIM_V2\server\app\api\v1\friends.py](D:\AssistIM_V2/server/app/api/v1/friends.py)
- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)

影响：

- relationship formal contract 仍按 route 各自长出来
- 客户端无法围绕统一的“好友关系状态”建模

建议：

- 先定义 friendship summary / request detail / mutation result 三套正式 contract

### F-767：HTTP typing 的响应只回 `typing` 布尔值，不回 canonical event payload，和它实际广播出去的 realtime shape 分裂

状态：已修复（2026-04-12；2026-04-14 被 R-005 重构移除 HTTP typing 入口）

修复说明：

- 2026-04-12 曾把 `typing_session()` 的 HTTP ack 对齐到与 realtime fanout 同源的 canonical `typing_event`
- 2026-04-14 按 `R-005` 继续重构，已删除 HTTP typing route；typing 不再有 HTTP ack
- typing 现在只保留聊天 WebSocket `typing` 正式入口，并由 realtime protocol 文档记录其 canonical payload

原现状：

- [sessions.py](D:\AssistIM_V2\server/app/api/v1/sessions.py) 的 `typing_session()`
- 实际广播给成员的是：
  - `session_id`
  - `user_id`
  - `typing`
- 但 HTTP 响应只返回：
  - `{"typing": payload.get("typing", True)}`

证据：

- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2/server/app/api/v1/sessions.py)

修复前影响：

- 同一个 typing 正式动作在 HTTP ack 和 realtime event 上有两套 shape
- 调用方拿不到 canonical `session_id/user_id` echo

修复建议：

- typing HTTP ack 至少和 realtime payload 对齐到同一份 canonical shape

### F-768：`call_ringing` 没有 sender-side canonical echo，发起 ringing 的被叫当前设备只能依赖本地 optimistic 状态

状态：已修复（2026-04-14）

现状：

- [call_service.py](D:\AssistIM_V2\server/app/services/call_service.py) 的 `ringing()`
- 固定返回：
  - `("call_ringing", [call.initiator_id], payload)`
- [chat_ws.py](D:\AssistIM_V2\server/app/websocket/chat_ws.py)
- 只会把这条 canonical event fanout 给 `target_user_ids`
- 也就是说发起 `call_ringing` 的被叫当前设备拿不到任何服务端 echo

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)

影响：

- 被叫当前设备对“已正式进入 ringing”只能依赖本地 optimistic 状态
- 通话状态机继续缺 sender-side canonical ack

建议：

- `call_ringing` 也应回送 sender-side canonical echo

### F-769：`call_offer/call_answer/call_ice` 只发给对端，不镜像到发送方自己的其它在线设备

状态：已修复（2026-04-14）

现状：

- [call_service.py](D:\AssistIM_V2\server/app/services/call_service.py) 的：
  - `relay_offer()`
  - `relay_answer()`
  - `relay_ice()`
- 都只返回：
  - `[self._peer_id(call, user_id)]`
- [chat_ws.py](D:\AssistIM_V2\server/app/websocket/chat_ws.py)
- 又会原样只 fanout 给这组 target user ids

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)

影响：

- 同账号多设备下，发送 signaling 的那一侧只有当前设备和对端设备知道最新 offer/answer/ice
- 发送方其它在线设备会长期停留在旧 signaling 状态

建议：

- signaling 事件也应镜像到发送方其它在线设备，不能只转发给 peer

### F-770：`GET /sessions` 和 `GET /sessions/{id}` 现在复用同一份 full-detail payload，没有 summary/detail 分层

状态：已确认

现状：

- [sessions.py](D:\AssistIM_V2\server/app/api/v1/sessions.py) 的：
  - `list_sessions()`
  - `get_session()`
- 最终都走 [session_service.py](D:\AssistIM_V2\server/app/services/session_service.py) 的 `serialize_session(..., include_members=True)`

证据：

- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2/server/app/api/v1/sessions.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 会话 collection 和 detail 没有轻重分层
- 列表接口继续返回完整 detail 级对象图

建议：

- 会话域应拆出 summary payload 和 detail payload

### F-771：session payload 同时返回 `id` 和 `session_id`，两个字段实际是同一个值

状态：已确认

现状：

- [session_service.py](D:\AssistIM_V2\server/app/services/session_service.py) 的 `serialize_session()`
- 当前同时写：
  - `id: session.id`
  - `session_id: session.id`

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- session formal payload 没有单一 canonical id 字段
- 客户端会继续在 `id/session_id` 两套别名上分裂实现

建议：

- 会话 payload 只保留一套 canonical 标识字段

### F-772：会话列表 payload 仍直接带 self-scoped `group_note/my_group_nickname`，collection response 继续混入 viewer-specific detail

状态：已确认

现状：

- [session_service.py](D:\AssistIM_V2\server/app/services/session_service.py) 的 `list_sessions()`
- 会直接返回 `serialize_session(... include_members=True ...)`
- 而 `serialize_session()` 又会把：
  - `group_note`
  - `my_group_nickname`
- 直接写进 payload

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- collection payload 继续混入当前查看者私有字段
- 会话 summary 不能再被当作稳定 shared snapshot 复用

建议：

- self-scoped group profile 应从 session collection payload 拆出去

### F-773：`GET /groups` 和 `GET /groups/{id}` 现在同样复用一份 full-detail payload，没有 summary/detail 分层

状态：已确认

现状：

- [groups.py](D:\AssistIM_V2\server/app/api/v1/groups.py) 的：
  - `list_groups()`
  - `get_group()`
- 最终都走 [group_service.py](D:\AssistIM_V2\server/app/services/group_service.py) 的 `serialize_group(... include_members=True ...)`

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- group collection 和 detail 继续没有层次
- 列表接口会长期返回 detail 级对象图

建议：

- 群域也应拆出 summary payload 和 detail payload

### F-774：group payload 同时返回 `member_version` 和 `group_member_version`，两者当前其实是同一个值

状态：已确认

现状：

- [group_service.py](D:\AssistIM_V2\server/app/services/group_service.py) 的 `serialize_group()`
- 当前同时写：
  - `member_version`
  - `group_member_version`
- 且两者都直接来自同一次 `_group_member_version(user_ids)` 计算

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- group formal payload 再次出现双字段同义别名
- 调用方无法判断哪一个才是 canonical 版本字段

建议：

- 统一群成员版本字段，只保留一套 canonical 名称

### F-775：group 成员 payload 同时返回 `user_id` 和 `id`，两个字段实际指向同一个用户

状态：已确认

现状：

- [group_service.py](D:\AssistIM_V2\server/app/services/group_service.py) 的 `serialize_group()`
- `members[]` 当前同时写：
  - `user_id`
  - `id`
- 二者都来自同一个用户 id

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- group member formal payload 继续没有单一 canonical id 字段
- 客户端成员模型会继续在 `id/user_id` 两套字段间分裂

建议：

- 群成员 payload 只保留一套 canonical 用户标识

### F-776：群列表 payload 也直接带 self-scoped `group_note/my_group_nickname`，collection response 混入 viewer-specific detail

状态：已确认

现状：

- [group_service.py](D:\AssistIM_V2\server/app/services/group_service.py) 的 `list_groups()`
- 直接返回 `serialize_group(... include_members=True, current_user_id=...)`
- `serialize_group()` 又会把：
  - `group_note`
  - `my_group_nickname`
- 放进列表 payload

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- group collection payload 继续夹带当前查看者私有字段
- 群 summary 不能再被视为稳定 shared snapshot

建议：

- self-scoped 群资料应和 shared group summary 正式分层

### F-777：message payload 同时返回 `created_at` 和 `timestamp`，两个字段当前是同一个值

状态：已修复（2026-04-12）

修复说明：

- `MessageService.serialize_message()` 已移除 message payload 顶层 `timestamp`，只保留 `created_at` / `updated_at`
- `MessageOut` schema 已同步移除 `timestamp`
- 客户端 websocket 入站消息在无 `timestamp` 时会用 message `created_at` 初始化本地 `ChatMessage.timestamp`
- 已补 API/schema/client 入站回归断言，避免正式 message payload 再次暴露同义时间字段

原现状：

- [message_service.py](D:\AssistIM_V2\server/app/services/message_service.py) 的 `serialize_message()`
- 当前同时写：
  - `created_at = isoformat_utc(message.created_at)`
  - `timestamp = isoformat_utc(message.created_at)`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

修复前影响：

- message formal payload 再次出现双字段同义别名
- 客户端会继续在 `created_at/timestamp` 两套时间字段间分裂

修复建议：

- 消息时间字段应只保留一套 canonical 名称

### F-778：message payload 会把 `session_seq/read_count/read_target_count/read_by_user_ids/is_read_by_me` 同时放在顶层和 `extra` 里

状态：已修复（2026-04-12）

修复说明：

- `MessageService._message_extra()` 已停止把 `read_metadata` merge 进 `extra`
- `session_seq/read_count/read_target_count/read_by_user_ids/is_read_by_me` 只保留在 message payload 顶层 canonical 字段
- 已在 `test_group_read_receipts_are_tracked_per_member` 中断言 read metadata 不再出现在 `extra` 内

原现状：

- [message_service.py](D:\AssistIM_V2\server/app/services/message_service.py) 的 `serialize_message()`
- 顶层已经返回：
  - `session_seq`
  - `read_count`
  - `read_target_count`
  - `read_by_user_ids`
  - `is_read_by_me`
- 但 `_message_extra()` 又会把同一批 `read_metadata` 再 merge 进 `extra`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

修复前影响：

- message output contract 出现结构性重复
- 同一语义要维护顶层和 `extra` 两份表示

修复建议：

- read metadata 应只保留一层正式表示

### F-779：`extra` 已经不再是消息持久化 extra，而是“持久化 extra + 当前查看者 read metadata”的混合体

状态：已修复（2026-04-12）

修复说明：

- `extra` 已恢复为服务端持久化 message extra 的 sanitized 输出
- 当前 viewer 相关 read metadata 不再混入 `extra`，只通过 message 顶层 canonical 字段表达

原现状：

- [message_service.py](D:\AssistIM_V2\server/app/services/message_service.py) 的 `_message_extra()`
- 先读取持久化 `extra`
- 再把当前 viewer 相关的 `read_metadata` merge 进去

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

修复前影响：

- 同一条消息对不同查看者返回的 `extra` 不再一致
- `extra` 失去“authoritative stored extra”语义

修复建议：

- persisted extra 和 derived viewer metadata 应正式分层

### F-780：`GET /sessions/{id}/messages` 在单会话分页里仍为每条消息重复塞入同一份 session metadata

状态：已确认

现状：

- [message_service.py](D:\AssistIM_V2\server/app/services/message_service.py) 的 `serialize_message()`
- 对每条消息都会重复返回：
  - `session_type`
  - `session_name`
  - `session_avatar`
  - `participant_ids`
  - `is_ai_session`
- 但 [messages.py](D:\AssistIM_V2\server/app/api/v1/messages.py) 的 `list_messages()`
- 本来就是单个 `session_id` 下的分页

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2/server/app/api/v1/messages.py)

影响：

- 单会话历史页 payload 被结构性放大
- 同一页内的静态 session metadata 会被每条消息重复传输

建议：

- 单会话消息列表应把 session metadata 抽到页级，避免逐条重复

### F-781：group 成员 payload 和 session 成员 payload 仍不是同一套正式 contract

状态：已确认

现状：

- [group_service.py](D:\AssistIM_V2\server/app/services/group_service.py) 的 `serialize_group().members[]`
- 返回：
  - `user_id`
  - `id`
  - `username`
  - `nickname`
  - `group_nickname`
  - `avatar`
  - `gender`
  - `region`
  - `role`
  - `joined_at`
- [session_service.py](D:\AssistIM_V2\server/app/services/session_service.py) 的 `serialize_session().members[]`
- 返回的又是另一套字段面

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- “群成员”在 group detail 和 session detail 上没有单一 canonical 结构
- 客户端必须按来源写两套成员解析逻辑

建议：

- 群成员正式 payload 应抽成一套共享 contract

### F-782：direct session payload 同时返回 `counterpart_*` 摘要和完整 `members[]`，同一对端信息有两套表示

状态：已确认

现状：

- [session_service.py](D:\AssistIM_V2\server/app/services/session_service.py) 的 `serialize_session()`
- direct session 当前会同时返回：
  - `counterpart_id/counterpart_name/counterpart_username/counterpart_avatar/counterpart_gender`
  - 以及完整 `members[]`

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- direct session formal payload 对同一对端信息保留了两套表示
- 调用方要么维护两套逻辑，要么承担字段漂移风险

建议：

- direct summary 和成员详情应正式分层

### F-783：`serialize_session()` 会把 `unread_count` 固定写成 `0`，formal session payload 继续夹带 dummy 字段

状态：已修复（2026-04-12）

修复说明：

- `SessionService.list_sessions()` / `get_session()` 已把 `unread_count` 接到 `MessageRepository.unread_by_session_for_user()` 的权威计数
- 已补充 `test_session_service.py` 覆盖 session payload 不再返回恒为 0 的 dummy unread

原现状：

- [session_service.py](D:\AssistIM_V2\server/app/services/session_service.py) 的 `serialize_session()`
- 无论是：
  - `GET /sessions`
  - `GET /sessions/{id}`
- 当前都直接返回：
  - `unread_count: 0`
- 但服务端真正的未读 authoritative 入口在：
  - [sessions.py](D:\AssistIM_V2\server/app/api/v1/sessions.py) 的 `GET /sessions/unread`
  - [message_repo.py](D:\AssistIM_V2\server/app/repositories/message_repo.py) 的 `unread_by_session_for_user()`

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2\server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2\server/app/api/v1/sessions.py)
- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2\server/app/repositories/message_repo.py)

修复前影响：

- formal session payload 继续暴露一个看起来 authoritative、实际上恒为 0 的 dummy 字段
- 调用方会被迫同时面对“session 自带 unread_count”和“单独 unread summary”两套真相

修复建议：

- 要么把 unread 从 session snapshot 中移除
- 要么在同一条 formal session route 上返回真实 unread，而不是继续塞 placeholder

### F-784：`serialize_session()` 里的 `session_crypto_state` 目前始终是空对象 `{}`，formal session payload 继续暴露 placeholder 状态

状态：已修复（2026-04-12）

修复说明：

- 服务端 `serialize_session()` 和 `SessionOut` 已移除空壳 `session_crypto_state`
- session crypto state 继续由客户端 authenticated runtime 本地注解，不再伪装成服务端权威字段

原现状：

- [session_service.py](D:\AssistIM_V2\server/app/services/session_service.py) 的 `serialize_session()`
- 当前始终写：
  - `session_crypto_state: {}`
- 没有任何服务端权威计算，也没有和真实 session E2EE 状态绑定

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2\server/app/services/session_service.py)

修复前影响：

- formal session payload 再次出现“字段存在但没有 authoritative 语义”的 placeholder
- 客户端很容易把它误当成正式安全状态，而实际上它只是一块空壳

修复建议：

- 没有权威服务端安全态之前，应移除该字段或显式标为未实现

### F-785：`serialize_message()` 里的 `is_ai` 当前恒为 `False`，message formal payload 继续夹带 dummy 字段

状态：已修复（2026-04-12）

修复说明：

- 服务端 `serialize_message()` 和 `MessageOut` 已移除恒为 `False` 的 `is_ai` 字段
- AI 会话身份继续由已有 `is_ai_session` 表达，避免 message payload 暴露假权威字段

原现状：

- [message_service.py](D:\AssistIM_V2\server/app/services/message_service.py) 的 `serialize_message()`
- 当前始终写：
  - `is_ai: False`
- 没有任何按消息来源、sender profile 或 AI session 真正计算的逻辑

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2\server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\schemas\message.py](D:\AssistIM_V2/server/app/schemas/message.py)

修复前影响：

- 消息 formal payload 继续暴露一个看起来 authoritative、实际上永远为假值的字段
- 客户端如果据此判断 AI 消息，只会得到持续错误的 contract

修复建议：

- `is_ai` 要么正式实现
- 要么从公开 message payload 中移除

### F-786：被撤回的最后一条消息在会话预览里会被序列化成空字符串，`recalled` 和“没有预览”被混成一类

状态：已修复（2026-04-12）

修复说明：

- `SessionService._serialize_last_message_preview()` 已为 recalled last-message 返回稳定 formal 占位 `[message recalled]`
- 已补充 `test_session_service.py` 覆盖 recalled session preview 不再退化为空字符串

原现状：

- [session_service.py](D:\AssistIM_V2\server/app/services/session_service.py) 的 `_serialize_last_message_preview()`
- 当前对 `recalled` 最后一条消息直接返回：
  - `""`

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2\server/app/services/session_service.py)

修复前影响：

- 会话列表无法区分“最后一条消息被撤回”与“根本没有可展示预览”
- 上层只能额外拼读 `last_message_status` 之类旁路字段补语义

修复建议：

- 会话预览应给 recalled last-message 单独的 formal placeholder，而不是直接清成空字符串

### F-787：被撤回消息的 `content` 也会被序列化成空字符串，`recalled` 和“空文本消息”没有单一 formal 区分

状态：已修复（2026-04-12）

修复说明：

- `MessageService._serialize_message_content()` 已为 recalled message 返回稳定 formal 占位 `[message recalled]`
- 已补充 `test_message_service.py` 覆盖 recalled message content 不再退化为空字符串

原现状：

- [message_service.py](D:\AssistIM_V2\server/app/services/message_service.py) 的 `_serialize_message_content()`
- 当前对 recalled message 直接返回：
  - `""`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2\server/app/services/message_service.py)

修复前影响：

- message payload 本身无法只靠 `content` 区分“被撤回”与“原本就是空字符串”
- formal contract 继续要求调用方同时拼 `status` 和内容解释语义

修复建议：

- recalled message 应有明确的内容占位或独立字段语义，不要继续把 `content` 直接清空

### F-788：会话历史分页用 `created_at` 当 cursor，但正式排序用的是 `session_seq`，消息翻页 contract 继续是两套真相

状态：已修复（2026-04-12）

修复说明：

- 服务端 `GET /sessions/{session_id}/messages` 已从 `before` 时间戳 cursor 收口为 `before_seq` 序号 cursor
- `MessageRepository.list_session_messages()` 已按 `Message.session_seq < before_seq` 翻页，并继续按 `session_seq DESC, created_at DESC` 取页后反转成正序返回
- 客户端远端历史回拉、窗口历史页缓存 key、恢复补偿 `recover_session_messages()` 都已传递/推进 `before_seq`
- 已补 `test_list_messages_uses_session_seq_cursor`、`test_chat_service_fetch_messages_uses_session_seq_cursor` 和 manager/controller 边界回归

原现状：

- [message_repo.py](D:\AssistIM_V2\server/app/repositories/message_repo.py) 的 `list_session_messages()`
- `before` 条件是：
  - `Message.created_at < before`
- 但正式排序却是：
  - `ORDER BY session_seq DESC, created_at DESC`

证据：

- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2/server/app/repositories/message_repo.py)
- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2/server/app/api/v1/messages.py)

修复前影响：

- history paging cursor 继续不是按 canonical `session_seq` 翻页
- 一旦出现时间戳碰撞、时钟漂移或补写消息，翻页就可能跳过或重复消息

修复建议：

- 单会话历史分页应统一到 `session_seq` 或另一套单一有序 cursor

### F-789：缺失消息补偿的服务端排序继续优先 `created_at`，而不是按每个会话的 `session_seq` authoritative 顺序输出

状态：已修复（2026-04-12）

修复说明：

- `list_missing_messages_for_user()` 已改为按 `session_id, session_seq, created_at, id` 输出
- 缺失消息补偿不再让 `created_at` 排在同一会话的 authoritative `session_seq` 之前

原现状：

- [message_repo.py](D:\AssistIM_V2\server/app/repositories/message_repo.py) 的 `list_missing_messages_for_user()`
- 当前排序是：
  - `Message.created_at ASC`
  - `Message.session_id ASC`
  - `Message.session_seq ASC`

证据：

- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2/server/app/repositories/message_repo.py)

修复前影响：

- reconnect/history 补偿继续把 `created_at` 和 `session_seq` 混成两套 ordering truth
- 某个会话内只要 `created_at` 和 `session_seq` 不严格同向，就可能打乱 authoritative replay 顺序

修复建议：

- 缺失消息补偿应按 canonical session order 输出，不要再让 `created_at` 排在 `session_seq` 之前

### F-790：`call_offer/call_answer/call_ice` 当前是“按 user fanout”，会把点对点 signaling 扩散到对端全部在线设备

状态：closed（2026-04-14）

修复记录：

- signaling 仍按参与者 user 做 authoritative mirror，但客户端已补 current-call 和 accepted-stage guard；非当前 call、非 accepted call、自己发出的 sender echo 都不会进入媒体窗口
- 被动镜像设备在 accepted 后会清掉本地 invite/toast 状态，不再保留可消费 SDP/ICE 的 active call
- 后续如要把网络 fanout 本身收窄到设备连接，需要引入正式 device/connection routing registry；本轮关闭的是“非当前设备消费 signaling 并拉起媒体”的产品缺陷

现状：

- [call_service.py](D:\AssistIM_V2\server/app/services/call_service.py) 的：
  - `relay_offer()`
  - `relay_answer()`
  - `relay_ice()`
- 都只返回：
  - `[self._peer_id(call, user_id)]`
- [chat_ws.py](D:\AssistIM_V2\server/app/websocket/chat_ws.py) 再把这组 user id 直接喂给：
  - `send_json_to_users(...)`

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)

影响：

- offer / answer / ice 这种本应设备级点对点协商的 signaling 会被同时发到对端所有在线设备
- 多设备场景下，未参与当前媒体协商的其它设备也会收到同一份 SDP / ICE

建议：

- signaling 应补 device-scoped routing contract，而不是继续只按 user fanout

### F-791：`call_offer/call_answer/call_ice` 没有 sender 当前设备的 canonical echo，发送方当前连接只能依赖本地 optimistic 状态

状态：closed（2026-04-14）

修复记录：

- `CallService.relay_offer()` / `relay_answer()` / `relay_ice()` 现在返回通话参与双方作为 authoritative fanout 目标，发送方也能收到服务端 canonical echo
- 客户端收到自己 `actor_id` 的 echo 会用于确认边界但不会回灌媒体窗口，避免 sender echo 造成本地重复处理
- 服务端下行 envelope 已使用独立 `msg_id`，sender echo 和 peer fanout 都不再复用 `call_id` 作为 transport id

现状：

- [call_service.py](D:\AssistIM_V2\server/app/services/call_service.py) 的 signaling relay 只返回 peer user
- [chat_ws.py](D:\AssistIM_V2\server/app/websocket/chat_ws.py) 成功后也只：
  - `send_json_to_users(target_user_ids, ...)`
- 当前连接拿不到任何 sender-side canonical echo

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)

影响：

- 发送方当前设备无法确认服务端已正式接受并转发这条 signaling 命令
- 当前通话状态机会继续依赖 optimistic 本地推进，而不是 authoritative echo

建议：

- signaling 发送方当前连接也应拿到 canonical echo / ack

### F-792：通话 signaling payload 同时保留 `actor_id`、`from_user_id`、`to_user_id`，actor/recipient formal contract 继续重复

状态：closed（2026-04-14）

修复记录：

- `_signal_payload()` 已移除 `from_user_id` / `to_user_id`
- signaling payload 统一复用 `_call_payload(..., actor_id=...)`，actor 只有 `actor_id` 一套 canonical 表示
- 已在 `test_call_service_requires_accept_before_signaling_and_validates_payload` 中断言旧重复字段不再出现

现状：

- [call_service.py](D:\AssistIM_V2\server/app/services/call_service.py) 的 `_signal_payload()`
- 先复用 `_call_payload(call, actor_id=...)`
- 再额外塞入：
  - `from_user_id`
  - `to_user_id`

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)

影响：

- signaling formal payload 对“谁发出的、发给谁”的语义继续保留两套表示
- 后续字段扩展或客户端解析会继续在 `actor_id` 和 `from/to_user_id` 两套 actor contract 上分裂

建议：

- signaling payload 应收口成一套 canonical actor/recipient 字段

### F-793：同一个 `avatar` 字段在 REST / realtime / chat payload 上仍然没有单一语义，有的返回原始存储值，有的返回解析后的 URL

状态：已修复（2026-04-14）

修复说明：

- `UserService.serialize_public_user()` 已成为公开用户摘要的 canonical 入口，`avatar` 统一返回最终公开 URL
- REST users、auth user detail、friend/friend request、moments author/comment author、message sender profile 和 realtime `user_profile_update.profile` 已统一使用这套 public user summary
- 已增加/更新 profile、friend request、moment 和 message sender profile 相关回归测试

原现状：

- [user_service.py](D:\AssistIM_V2\server/app/services/user_service.py) 的 `serialize_user()`
- [friend_service.py](D:\AssistIM_V2\server/app/services/friend_service.py) 的：
  - `list_friends()`
  - `_serialize_request_party()`
- [moment_service.py](D:\AssistIM_V2\server/app/services/moment_service.py) 的：
  - `serialize_moment()`
  - `serialize_comment()`
- 当前都直接返回原始 `user.avatar`
- 但 [message_service.py](D:\AssistIM_V2\server/app/services/message_service.py) 的 `_serialize_sender_profile()`
- 以及 [session_service.py](D:\AssistIM_V2\server/app/services/session_service.py)、[group_service.py](D:\AssistIM_V2\server/app/services/group_service.py) 的成员/对端序列化
- 又会返回 `resolve_user_avatar_url(...)`

证据：

- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)
- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)
- [D:\AssistIM_V2\server\app\services\moment_service.py](D:\AssistIM_V2/server/app/services/moment_service.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 同名 `avatar` 字段在不同正式入口上继续代表两种完全不同的值
- 客户端必须按来源猜“这是 raw avatar state 还是最终 URL”

建议：

- `avatar` 应收口成一套 canonical public meaning，不要继续在不同入口返回不同语义

### F-794：好友请求 payload 继续同时返回 `sender_id/receiver_id` 和嵌套 `from_user/to_user`，relationship identity 在一条响应里重复两次

状态：已修复（2026-04-14）

修复说明：

- friend request payload 已收口为 `sender` / `receiver` 两个 canonical public user summary
- 顶层 `sender_id` / `receiver_id` 与旧 `from_user` / `to_user` 已移除
- 桌面端 `ContactController.load_requests()` 已直接按新 contract 读取，不保留旧字段回退
- 已增加服务端断言确认旧镜像字段不再返回，并更新客户端 request normalization 测试

原现状：

- [friend_service.py](D:\AssistIM_V2\server/app/services/friend_service.py) 的 `serialize_request()`
- 当前同时返回：
  - 顶层 `sender_id`
  - 顶层 `receiver_id`
  - 嵌套 `from_user`
  - 嵌套 `to_user`

证据：

- [D:\AssistIM_V2\server\app\services\friend_service.py](D:\AssistIM_V2/server/app/services/friend_service.py)

影响：

- friend request formal payload 继续没有单一 participant contract
- 同一请求参与者身份既可以从顶层拿，也可以从嵌套对象拿，后续字段扩展会继续双份维护

建议：

- request participant contract 应明确区分“标识字段”和“用户摘要字段”，不要继续双层镜像

### F-795：REST user payload 和 realtime `user_profile_update` payload 仍不是同一套 canonical user summary contract

状态：已修复（2026-04-14）

修复说明：

- 已定义 canonical public user summary：`id/username/nickname/display_name/avatar/avatar_kind/gender/region/signature/status`
- REST collection/search、friend request、moments、message sender profile 与 realtime `user_profile_update.profile` 已统一使用该 summary
- `/auth/me` / user detail 仍可在 summary 基础上扩展私有/detail 字段，但不再另起一套 profile event shape

原现状：

- [user_service.py](D:\AssistIM_V2\server/app/services/user_service.py) 的 `serialize_user()`
- REST 公开用户 payload 会返回：
  - `email`
  - `phone`
  - `birthday`
  - `region`
  - `created_at`
  - `updated_at`
  - 等完整资料
- 但 realtime [user_profile_update](D:\AssistIM_V2\server/app/services/user_service.py) 用的是 `serialize_profile_event_user()`
- 其字段面又是另一套：
  - `display_name`
  - `avatar_kind`
  - `signature`
  - `status`
  - 不含 REST 那批字段

证据：

- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)

影响：

- “同一个 user summary” 在 REST 和 realtime 上继续不是一套 formal contract
- 客户端需要分别维护 profile detail 和 profile event 两套解析模型

建议：

- 先定义一套 canonical public user summary，再让 REST 和 realtime 在其上分层

### F-796：`user_profile_update` 仍被建模成“每个 session 一条事件”，而不是 user-scoped authoritative 资料变更事件

状态：已修复（2026-04-14）

修复说明：

- `user_profile_update` realtime fanout 已改为 user-scoped payload：`{profile_event_id, user_id, profile}`
- 同一次资料变更只按受影响用户集合广播一次，不再按 session 逐条 fanout
- session history 中仍保留补偿镜像事件，但 event data 保持 user-scoped；客户端收到无 `session_id` 的 profile update 会按 user_id 更新所有本地缓存
- 已更新 realtime live 和 history replay 测试，确认 payload 不再携带 `session_id`

原现状：

- [user_service.py](D:\AssistIM_V2\server/app/services/user_service.py) 的 `record_profile_update_events()`
- 当前会遍历该用户参与的每一个 session
- 然后为每个 session 单独 append 一条：
  - `user_profile_update`

证据：

- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)

影响：

- 同一次 user profile 变更不会形成一条 user-scoped authoritative event
- 用户参与 session 越多，同一次资料修改就会被拆成越多条 session-scoped 事件

建议：

- 用户资料变更应先有一条 user-scoped authoritative event，再决定哪些 session / 页面消费它

### F-797：`user_profile_update` payload 仍夹带 `session_avatar`，同一次用户资料变更会因为 session 不同而得到不同 payload

状态：已修复（2026-04-14）

修复说明：

- `user_profile_update` realtime 与 history event payload 已移除 `session_avatar`
- 客户端 profile update 处理链不再读取或转发 `session_avatar`
- session/group 视图相关 avatar 仍保留在对应 session/message/group payload 中，不再混入 user profile event

原现状：

- [user_service.py](D:\AssistIM_V2\server/app/services/user_service.py) 的 `record_profile_update_events()`
- 每个 event payload 当前除了 `profile` 外，还会写：
  - `session_avatar`

证据：

- [D:\AssistIM_V2\server\app\services\user_service.py](D:\AssistIM_V2/server/app/services/user_service.py)

影响：

- `user_profile_update` 不再是单一的 user profile contract
- 同一用户资料变更在不同 session 上会变成不同 payload，进一步放大 REST/realtime 的 contract 分裂

建议：

- `user_profile_update` 应只携带用户资料自身；session 相关视图应走 session/group 的正式事件

### F-798：shared `group_profile_update` payload 继续夹带 self-scoped `group_note/my_group_nickname`，只是因为 `current_user_id=None` 才退化成空字符串

状态：已修复（2026-04-14）

修复说明：

- `record_group_profile_update_event()` 在构造 shared event payload 后会移除 `group_note/my_group_nickname`，self-scoped 字段只保留在 `group_self_profile_update`。

现状：

- [group_service.py](D:\AssistIM_V2\server/app/services/group_service.py) 的 `record_group_profile_update_event()`
- 会调用：
  - `serialize_group(group, include_members=True, current_user_id=None)`
- 但 `serialize_group()` 无论当前是不是 shared payload
- 都会生成：
  - `group_note`
  - `my_group_nickname`
- 只是 `current_user_id=None` 时，这两个字段退化成空字符串

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- shared group-profile event 继续把 self-scoped 字段带进 formal payload
- 当前只是“值恰好为空”，并不是边界真的收口了

建议：

- shared group profile payload 应彻底移除 self-scoped 字段，而不是继续返回空占位

### F-799：`group_profile_update` shared payload 每次都会内联完整 `members[]`，哪怕只是改群名或群公告

状态：部分修复（2026-04-14）

修复说明：

- shared event 已统一承载群 lifecycle authoritative snapshot，并清除了 self-scoped 字段；本轮没有拆轻量 profile-delta，仍保留完整 members snapshot 作为正式补偿载体。

现状：

- [group_service.py](D:\AssistIM_V2\server/app/services/group_service.py) 的 `record_group_profile_update_event()`
- 每次都调用：
  - `serialize_group(... include_members=True ...)`
- 因此哪怕只是：
  - 改群名
  - 改公告
- shared realtime/event payload 也会带完整成员 roster

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- group profile event payload 被结构性放大
- shared profile update 和 group membership snapshot 继续被混成同一条 contract

建议：

- group profile update 应拆成轻量 shared profile delta，不要每次都内联完整成员列表

### R-095：通话 signaling 仍然没有 device-scoped routing model，控制面 fanout 继续停留在“按 user 广播”

状态：closed（2026-04-14）

修复记录：

- realtime hub 已补单用户单连接投递边界，`call_invite` 被叫侧不再按 user 全连接广播，而是投递到一个 primary connection
- call state/control payload 已带 `actor_connection_id/ringing_connection_id/accepted_connection_id/active_connection_id`，正式表达 active realtime connection
- accepted/signaling/terminal 在客户端必须匹配本地 current call 和 media endpoint guard；即使 participant mirror 仍用于状态同步，也不会被动拉起媒体或旧窗口 signaling

现状：

- [call_service.py](D:\AssistIM_V2\server/app/services/call_service.py) 的 signaling relay
- 目标当前都只是 user id
- [chat_ws.py](D:\AssistIM_V2\server/app/websocket/chat_ws.py) 再统一用：
  - `send_json_to_users(...)`
- 整条通话控制面里没有任何“当前活跃设备 / 目标设备连接”概念

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)

影响：

- 1:1 WebRTC signaling 仍缺最小的设备级路由边界
- 后续多设备镜像、sender echo、active callee selection 都会继续建立在不稳定 user fanout 之上

建议：

- 通话控制面至少应补“目标设备 / 当前活跃设备”的正式路由 contract

### R-096：formal payload 里仍保留多块 dummy placeholder 字段，表面上看像 authoritative 状态，实际上没有真实语义

状态：已修复（2026-04-14）

现状：

- 当前公开 payload 里至少还有：
  - session `unread_count`
  - session `session_crypto_state`
  - message `is_ai`
- 这些字段都已经出现在正式返回里
- 但没有任何对应的 authoritative 计算逻辑

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)

影响：

- 调用方会被鼓励依赖这些字段
- 一旦客户端真的按它们建模，就会把 placeholder 当正式状态消费

建议：

- 公开 payload 不应再暴露没有 authoritative 语义的占位字段

### R-097：消息历史和 reconnect 补偿仍混用 `created_at` 与 `session_seq` 两套排序真相，后续很难得到单一的 paging/sync contract

状态：已修复（2026-04-14）

现状：

- 单会话历史分页用：
  - `created_at < before`
- 但列表排序又用：
  - `session_seq`
- reconnect 缺失消息补偿也把：
  - `created_at`
  - `session_seq`
- 混在同一排序链里

证据：

- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2/server/app/repositories/message_repo.py)

影响：

- paging、sync、lost-ack recovery 很难围绕同一套 authoritative order 收口
- 后续即使继续补单点，也会反复踩到 cursor 和排序真相不一致的问题

建议：

- 先统一消息正式顺序真相，再去定义 paging 和 reconnect contract

### F-800：`refresh_remote_sessions()` 遇到单条坏 session payload 会直接把该会话从 authoritative 快照里静默丢掉，本地随后会把它当成“已消失”

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `refresh_remote_sessions()`
- 会逐条调用 `_build_session_from_payload(...)`
- 而 `_build_session_from_payload()` 只要遇到：
  - 缺失或非法 `session_type`
  - `Session.from_dict(...)` 失败
- 就会直接 `return None`
- `refresh_remote_sessions()` 不会保留这条坏记录，也不会把这次 refresh 标成 partial failure
- 随后的 `_replace_sessions(remote_sessions)` 会把本地现有快照整体替换掉

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 单条坏 session payload 会被本地直接当成“服务端 authoritative 快照里已经没有这条会话”
- 现有会话会在一次 refresh 里被静默移出本地列表
- refresh contract 继续把“坏条目”与“会话正式消失”混成一类

建议：

- `refresh_remote_sessions()` 应显式区分：
  - authoritative 删除
  - 单条 payload 解析失败
  - 整轮 refresh 失败
- 至少不要因为一条坏记录就把本地现有会话当作 authoritative 消失处理

### F-801：会话全量刷新会先逐条做一次 `decorate/crypto/call` 注解，随后在 `_replace_sessions()` 里整批再做一遍，存在确定性的重复工作

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_build_session_from_payload()`
- 每生成一条 session 都会：
  - `_decorate_session_members([session], current_user)`
  - `_annotate_session_crypto_state([session])`
  - `_normalize_session_display(session, current_user)`
- 但 `refresh_remote_sessions()` 把这批 session 收集起来后
- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_replace_sessions()`
- 又会对整批 session 再做一次：
  - `_decorate_session_members(sessions, current_user)`
  - `_annotate_session_crypto_state(sessions)`
  - `_normalize_session_display(...)`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 一次全量 refresh 会重复跑联系人 remark 覆盖、E2EE 状态计算、call 能力注解和 direct display normalize
- 会话越多，这条主链路的 CPU / I/O / 本地状态写放大会越明显
- 当前 refresh contract 里已经存在的 E2EE / visibility / warmup 问题，也会被这类重复工作继续放大

建议：

- 把 `_build_session_from_payload()` 收口成纯 payload normalize
- batch refresh 场景只在 `_replace_sessions()` 里统一做一次 decorate / annotate / display normalize

### F-802：`call_accept` 会 fanout 给双方全部在线设备，而客户端收到 accepted 后会无条件 `start_media`，多设备场景下会把其它设备也拉进媒体建立

状态：closed（2026-04-14）

修复记录：

- `CallManager.accept_call()` 会记录本机正在 accept 的 `call_id`，`call_accept` 入站时生成 `is_local_media_endpoint`
- `ChatInterface._on_call_accepted()` 只有在本机是发起端或本机执行了 accept 时才 `start_media()` / 播放 connected UX
- 同账号其它被动设备收到 accepted 只关闭本地 toast/window 并停止响铃，不再拉起媒体
- 已补 `test_call_manager_marks_passive_accepted_mirror_without_starting_media`

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `accept()`
- 当前返回：
  - `("call_accept", call.participant_ids(), payload)`
- 也就是 accepted 状态会 fanout 给主叫和被叫两个 user 的全部在线连接
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_accepted()`
- 收到 accepted 后会无条件：
  - `_ensure_call_window(call, start_media=True)`
- 这里没有任何“是不是当前接受通话的那台设备”的 device guard

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 被叫在一台设备上点接听后，本账号其它在线设备也会把 accepted 当成本地正式起媒体信号
- 主叫的其它在线设备同样可能被动拉起窗口和媒体初始化
- `call_accept` 现在仍是 user-scoped 状态广播，但客户端却把它消费成了 device-scoped 媒体启动命令

建议：

- `call_accept` 至少要补 accepter device / active media device 的正式 contract
- 客户端只有在“当前设备就是正式媒体设备”时，才能把 accepted 升级成 `start_media`

### F-803：`update_group_profile()` 返回给 HTTP 调用方的 group snapshot，和随后 realtime/history 里追加的 `group_profile_update` payload 不是同一份快照

状态：部分修复（2026-04-14）

修复说明：

- `update_group_profile()` 的 HTTP response 已改成 shared canonical 视角，和 `group_profile_update` event 不再 actor-view 分裂；事件仍在 route helper 中重新读取一次快照，未做同对象复用。

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `update_group_profile()`
- mutation 完成后先返回：
  - `result.group = serialize_group(..., current_user_id=current_user.id)`
- 但 [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 route 随后又单独调用：
  - `_broadcast_group_profile_update(...)`
- 而 `_broadcast_group_profile_update()` 内部会重新执行：
  - `record_group_profile_update_event(group_id, ...)`
  - `serialize_group(group, include_members=True, current_user_id=None)`
- 也就是说 realtime/history event payload 不是复用 mutation 时那份已确定的快照，而是“事后按当前库状态再序列化一遍”

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- 同一次群资料修改，HTTP 返回值和后续 `group_profile_update` 事件不保证描述的是同一份状态快照
- 一旦两次 mutation 紧邻发生，晚一步生成的 event payload 就可能夹带后续变化
- shared group profile 的 formal contract 继续缺少“这条事件到底对应哪次 mutation”的单一真相

建议：

- `update_group_profile()` 应把 mutation 后的 canonical payload 一次性定格
- HTTP response、history event 和 realtime fanout 都应复用同一份 snapshot，而不是各自事后重建

### F-804：`update_my_group_profile()` 的 self-profile realtime/history payload 也是事后重建的，不保证和本次 self-scoped mutation 返回值描述同一状态

状态：部分修复（2026-04-14）

修复说明：

- self-profile response 已收口为 self-only payload，空/no-op 不再写 event；event 仍由 route helper 在提交后重建，未完全复用同一 payload 对象。

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `update_my_group_profile()`
- 当前先提交 mutation，然后返回：
  - `serialize_group(group, include_members=True, current_user_id=current_user.id)`
- route 层随后再调用：
  - `_broadcast_group_self_profile_update(db, current_user, group_id)`
- 后者内部会重新执行：
  - `record_group_self_profile_update_event(current_user, group_id)`
  - `build_group_self_profile_payload(current_user, group_id)`
- 这条 self-scoped event payload 不是复用 mutation 时的确定结果，而是“提交后再读一次当前状态”

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- 同一次 self-profile 修改，HTTP 返回值与 `group_self_profile_update` 事件不保证描述同一份状态
- 紧邻的第二次 self-profile mutation 可能被第一条晚生成的 event 一起带进 payload
- self-scoped mutation 继续没有单一的 canonical output contract

建议：

- self-profile mutation 也应先定格一份 canonical self payload
- route response、offline event 和 realtime fanout 应复用这份 payload，而不是提交后再次读取当前状态

### F-805：通话终态事件会 fanout 给参与者全部在线设备，而 `_schedule_call_result_message()` 没有 device guard；同一主叫账号多设备可能各自发送一条系统结果消息

状态：closed（2026-04-14）

修复记录：

- `CallManager` 现在只有本地当前 call 会消费 busy/terminal/error，非当前 call 的终态 fanout 不会 materialize 本地 outgoing state
- 被动 accepted mirror 会在 accepted 时清掉 `_active_call`，后续 terminal 不再满足 current-call guard
- `_schedule_call_result_message()` 已改为按 `call_id` 单一终态去重，并保留 TTL/容量淘汰，不再按 `(call_id, outcome)` 写出多条矛盾结果
- 主叫结果消息仍由当前发起端设备写入；其它没有本地 current call 的镜像设备不会进入结果消息链

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的：
  - `reject()`
  - `hangup()`
  - 以及 accepted 后的其它终态
- 都会把事件 fanout 给参与者 user 级目标，而不是单一 active device
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的：
  - `_on_call_rejected()`
  - `_on_call_ended()`
  - `_on_call_busy()`
  - `_on_call_failed()`
- 都会调用 `_schedule_call_result_message(call, outcome=...)`
- 而 `_schedule_call_result_message()` 只校验：
  - `call.direction == "outgoing"`
  - `call.initiator_id == current_user_id`
- 没有任何“当前设备是否是正式通话设备/正式结果写入设备”的 guard
- `_call_result_messages_sent` 也只是当前进程内去重，不会跨设备去重

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 同一主叫账号如果有多台在线设备
- 一条 participant-scoped 终态 fanout 会让多台设备都满足“我是 outgoing initiator”的条件
- 这些设备可能各自往会话里发送一条本地 system result message
- 最终同一通电话会在聊天记录里出现重复结果消息

建议：

- call result message 必须绑定到单一 canonical writer 设备
- 至少在正式 call state 里补 active media device / result-writer device contract

### F-806：`PATCH /groups/{group_id}` 是 shared mutation，但 HTTP 返回仍直接复用 viewer-scoped `serialize_group(..., current_user_id=current_user.id)`；调用方拿到的是 actor 视角而不是 shared canonical payload

状态：已修复（2026-04-14）

修复说明：

- shared group profile mutation 现在返回 `current_user_id=None` 的 canonical shared group payload，不再把 actor 的 `group_note/my_group_nickname` 混入正式 response。

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `update_group_profile()`
- 当前返回：
  - `serialize_group(group, include_members=True, current_user_id=current_user.id)`
- 这份 payload 会带 actor 视角的：
  - `group_note`
  - `my_group_nickname`
  - 以及 viewer-scoped members 展示字段
- 但同一次 shared mutation 随后追加到 event/history 的 payload
- 又是：
  - `serialize_group(group, include_members=True, current_user_id=None)`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- 同一次 shared group profile mutation
- HTTP response 给 actor 的是 viewer-scoped detail
- realtime/history 给其它客户端的是 shared payload
- route response 和 shared event 不只是“时序不同”，连视角也不是同一个正式 contract

建议：

- shared mutation 应先定义一份 shared canonical payload
- actor 需要的 viewer-scoped detail 应作为额外 detail query 或明确的 actor-only response 层返回

### F-807：通话终态 fanout 到参与者全部在线设备后，聊天页会在被动镜像设备上同样播放结束音并弹 InfoBar，没有 current-device guard

状态：closed（2026-04-14）

修复记录：

- `CallManager._handle_terminal_event()` / `_handle_busy()` / `_handle_error_message()` 都要求 payload 匹配本地当前 call
- 被动镜像设备不会因为 participant-scoped terminal event 创建或清空本地 call，也不会触发 `ChatInterface` 的终态音效和 InfoBar
- 旧窗口的 hangup / offer / answer / ice 也增加 source-window 与 call_id 双重 guard，旧窗口不能继续向外发控制消息

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的：
  - `reject()`
  - `hangup()`
  - `busy()`
  - 以及其它终态
- 都是按 participant user fanout，而不是单一 active device
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的：
  - `_on_call_rejected()`
  - `_on_call_ended()`
  - `_on_call_busy()`
  - `_on_call_failed()`
- 收到后都会直接：
  - `_play_call_terminal_sound()`
  - 弹 `InfoBar`
- 这里没有任何“当前设备是否就是实际通话设备”的 guard

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 一台设备上的真实通话结束后
- 同账号其它在线设备即使只是被动镜像，也会同步播放结束音和弹终态提示
- 多设备下本地 UI 会把 participant-scoped 终态误消费成 current-device authoritative 终态

建议：

- participant-scoped terminal event 和 current-device UI side effect 必须拆开
- passive mirror device 至多更新镜像状态，不应直接播放本地终态提示音或弹主要提示

### F-808：会话全量刷新里的重复 crypto annotate 不是纯 CPU 重复，而是会把本地 E2EE 查询放大成 N+1

状态：closed（2026-04-14）

修复记录：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 batch refresh 路径已把 `_build_session_from_payload()` 与 `_replace_sessions()` 的重复 runtime normalize/crypto annotate/call annotate 拆开
- `_build_session_from_payload(..., normalize_runtime=False)` 在全量 refresh 中只负责构造基础对象，整批 annotate 改为后置一次性执行

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_build_session_from_payload()`
- 每生成一条 session 都会立即调用：
  - `_annotate_session_crypto_state([session])`
- 而 `_annotate_session_crypto_state()` 内部会进一步执行：
  - `get_local_device_summary()`
  - direct 会话的 `get_peer_identity_summary(counterpart_id)`
  - group 会话的 `reconcile_group_session_state(...)`
- 但 `refresh_remote_sessions()` 收集完整批次后
- `_replace_sessions()` 又会对整批 session 再调用一次 `_annotate_session_crypto_state(sessions)`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 一次全量会话 refresh 会把本应按批处理的一次 E2EE 状态注解放大成：
  - 每条 session 一次本地设备摘要读取
  - 每条 direct 一次 peer identity 查询
  - 每条 group 一次 sender-key reconcile
- 然后整批再重复一遍
- 会话越多，启动 warmup 和手动 refresh 的本地 E2EE 开销越明显

建议：

- `_build_session_from_payload()` 不应在 batch refresh 路径里立刻做 crypto annotate
- 把 E2EE / call state 注解收口成 batch-only 一次性阶段

### F-809：`delete_session()` 没有复用 `_is_visible_private_session()`；同一条异常直聊会在 `GET` 上表现为 404，但在 `DELETE` 上仍允许继续 mutation

状态：closed（2026-04-14）

修复记录：

- [sessions.py](/D:/AssistIM_V2/server/app/api/v1/sessions.py) 已移除 `DELETE /api/v1/sessions/{session_id}`
- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 也同步移除了 `delete_session()` 硬删除入口，delete mutation 不再绕开 private visibility contract

现状：

- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的：
  - `list_sessions()`
  - `get_session()`
- 都会对 direct session 复用：
  - `_is_visible_private_session(session, member_ids)`
- 但同文件的 `delete_session()`
- 只校验：
  - session 存在
  - 当前用户是成员
  - 不是 group session
- 不会再检查 `_is_visible_private_session(...)`

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 同一条 private session
- 在 list/get 语义里已经被 visibility 模型视为“不可见 / 不存在”
- 但在 delete mutation 上又仍然是可操作资源
- formal visibility contract 在读写入口之间继续分裂

建议：

- private session 的 visibility gate 应在 list/get/delete/create-existing 这些正式入口上统一复用
- 不要再让“读路径 404，但 mutation 还能操作”继续并存

### F-810：`create_private()` 命中已有直聊时也没有复用 `_is_visible_private_session()`；异常 private session 仍可被“建私聊”入口重新取回

状态：closed（2026-04-14）

修复记录：

- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `create_private(existing)` 已复用 `_is_visible_private_session(...)`
- 异常 hidden private session 现在不会再被 create-direct 入口重新返回

现状：

- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `create_private()`
- 命中已有 direct session 后会直接：
  - `return serialize_session(existing, include_members=True, participant_ids=members, current_user_id=current_user.id)`
- 这里不会像 `list_sessions()/get_session()` 那样校验：
  - `_is_visible_private_session(existing, member_ids)`

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 同一条异常 private session 可能已经不会出现在列表里，也不能通过 `GET /sessions/{id}` 取到
- 但用户再次“发起私聊”时，服务端仍会把它当作既有会话重新返回
- 会话 visibility contract 在 create/reuse 路径上继续被打穿

建议：

- `create_private(existing)` 路径也应复用统一的 private-session visibility gate
- 如果既有会话已不满足正式可见性模型，应先收口异常状态，而不是直接复用返回

### F-811：建群、加人、踢人、退群这些群生命周期 mutation 仍把 `ensure_group_avatar()` 直接塞进事务动作里，DB mutation 和文件系统 side effect 没有统一原子边界

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的：
  - `create_group()`
  - `add_member()`
  - `remove_member()`
  - `leave_group()`
- 都会在 `self._run_transaction(action)` 的 `action()` 内部执行：
  - `bump_group_avatar_version(...)`
  - `ensure_group_avatar(group)`
- 而 `ensure_group_avatar()` 不只是改 DB 内存对象
- 还会触发 group avatar 文件生成和 `session.avatar` mirror 更新

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- 一次群成员生命周期 mutation 会同时跨：
  - `SessionMember / GroupMember / ChatSession`
  - group avatar 文件
- 数据库事务失败和文件系统 side effect 失败没有共同原子边界
- 事务持有期间还会夹带额外文件 I/O，继续放大群 mutation 的时延和失败面

建议：

- 群生命周期 mutation 不要再在主事务里直接做 `ensure_group_avatar()`
- avatar 重建应拆成明确的后置 side effect 或异步补偿步骤

### F-812：会话全量刷新里的重复 members decorate 也会把本地联系人 cache 查询放大成按 session 的 N+1

状态：已修复（2026-04-14）

现状：

- [session_manager.py](/D:/AssistIM_V2/client/managers/session_manager.py) 的 `_build_session_from_payload()`
- 每生成一条 session 就会调用：
  - `_decorate_session_members([session], current_user)`
- 而 `_decorate_session_members()` 内部又会：
  - `_load_contact_cache_map(user_ids)`
- 这意味着 batch refresh 场景会先按“每条 session 一次”去查本地 contacts cache
- 随后的 `_replace_sessions()` 又会对整批 session 再调用一次 `_decorate_session_members(sessions, current_user)`

证据：

- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 一次全量 refresh 会把本应批量完成的联系人 remark/昵称覆盖
- 放大成按 session 的重复 cache lookup
- 会话越多，warmup 和手动 refresh 的本地 contacts lookup 冗余越明显

建议：

- batch refresh 路径里不要在单条 `_build_session_from_payload()` 上就做 members decorate
- 统一在 `_replace_sessions()` 里按整批 session 一次性完成联系人 overlay

### F-813：`call_accept` 的 participant-scoped fanout 还会让被动镜像设备一并播放 connected 音效和 accepted 提示，没有 current-device guard

状态：closed（2026-04-14）

修复记录：

- accepted 入站事件现在携带客户端侧 `is_local_media_endpoint` 判定
- `ChatInterface._on_call_accepted()` 对 passive mirror 只关闭 toast/window 与响铃，不再 `start_media()`、播放 connected 音效或弹 accepted InfoBar
- 已补 `test_call_manager_marks_passive_accepted_mirror_without_starting_media`

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `accept()`
- 会把 accepted event fanout 给 `call.participant_ids()` 对应的全部在线设备
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_accepted()`
- 收到后会无条件：
  - `_ensure_call_window(call, start_media=True)`
  - `_play_call_sound(AppSound.CALL_CONNECTED)`
  - 弹 `InfoBar.success(...)`
- 这里没有任何“当前设备是不是实际接听设备”的 guard

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 被叫在一台设备上接听后
- 同账号其它在线设备即使只是镜像，也会播放 connected 声音并弹 accepted 提示
- participant-scoped accepted event 被错误消费成 current-device authoritative UX 事件

建议：

- accepted 的 participant mirror 和 current-device accepted UX 必须拆开
- passive mirror device 不应直接播放 connected 音效或弹主提示

### F-814：HTTP typing 仍然只看 membership，不复用 private-session visibility gate；已被 visibility 模型隐藏的异常直聊仍可继续广播 typing

状态：已修复（2026-04-14）

现状：

- [sessions.py](/D:/AssistIM_V2/server/app/api/v1/sessions.py) 的 `typing_session()`
- 只调用 [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `get_session_member_ids(session_id, current_user.id)`
- `get_session_member_ids()` 只检查：
  - `current_user.id in member_ids`
- 不会像 [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `get_session()` / `list_sessions()` 那样再过：
  - `_is_visible_private_session(...)`

证据：

- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2/server/app/api/v1/sessions.py)
- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 一条已经被 direct visibility 模型判成“不可见/404”的异常私聊
- 仍可继续通过 HTTP typing 入口给两端成员广播 typing realtime
- 会话可见性 contract 在 session/read 路径和 typing 路径之间继续分裂

建议：

- typing 正式入口也应复用 private-session visibility gate
- 不要再让“不可见会话”继续产生 ghost typing

### F-815：`call_ringing/call_accept/call_reject/call_hangup/call_busy` 入站 payload 即使 `call_id` 为空，也能污染甚至清掉当前 `_active_call`

状态：closed（2026-04-14）

修复记录：

- `CallManager._handle_ws_message()` 对所有非 error call event 先要求非空 `data.call_id`
- `_handle_state_event()` / `_handle_terminal_event()` / `_handle_busy()` 在 merge 前必须通过 `_matches_current_call(payload)`
- 空 `call_id`、其它 `call_id`、无本地 active call 的 state/terminal/busy payload 都会被丢弃，不能再污染或清掉当前 `_active_call`
- 已补 `test_call_manager_ignores_empty_or_stale_call_payloads`

现状：

- [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 的：
  - `_handle_state_event()`
  - `_handle_terminal_event()`
  - `_handle_busy()`
- 都直接把 payload 交给 `_merge_state()`
- 而 `_merge_state()` 又会调用：
  - `ActiveCallState.from_payload(payload, ...)`
- [call.py](/D:/AssistIM_V2/client/models/call.py) 的 `ActiveCallState.from_payload()`
- 对缺失 `call_id` 只会生成：
  - `call_id=""`
- `_handle_terminal_event()` / `_handle_busy()` 后续还会无条件：
  - `self._active_call = None`

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)
- [D:\AssistIM_V2\client\models\call.py](D:\AssistIM_V2/client/models/call.py)

影响：

- 一条 malformed 的 state / terminal / busy payload
- 即使没有合法 `call_id`
- 也可能先把当前 active call merge 成一条 `call_id=""` 的假状态
- 终态分支还会进一步把当前通话直接清掉
- 通话链缺少最基础的入站身份校验，异常包能直接破坏本地状态机

建议：

- 非 invite 的 call state/terminal/busy 事件必须要求非空 `call_id`
- 在进入 `_merge_state()` 前就丢弃空 `call_id` payload
- 终态清理也必须绑定到已验证的当前 call generation

### F-816：`call_invite` 入站同样不校验 `call_id/session_id`；空标识 payload 也能直接建出本地 ghost active call

状态：closed（2026-04-14）

修复记录：

- `_handle_invite()` 已统一走 `_has_required_identity(..., require_session=True)`
- 空 `call_id` 或空 `session_id` 的 invite 不再进入 `_active_call`
- sender-side canonical echo 只有本机已有同一 current call 时才会被接受；其它本账号被动设备不会因为 outgoing invite echo 建出 ghost outgoing call
- 已补 `test_call_manager_ignores_empty_or_stale_call_payloads`

现状：

- [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 的 `_handle_invite()`
- 直接：
  - `self._active_call = ActiveCallState.from_payload(payload, ...)`
- 这里不会检查：
  - `payload.call_id` 是否非空
  - `payload.session_id` 是否非空
- [call.py](/D:/AssistIM_V2/client/models/call.py) 的 `from_payload()`
- 对缺失字段会直接生成空字符串状态对象

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)
- [D:\AssistIM_V2\client\models\call.py](D:\AssistIM_V2/client/models/call.py)

影响：

- 一条 malformed `call_invite` payload
- 就能把客户端单槽 `_active_call` 污染成：
  - `call_id=""`
  - `session_id=""`
- 后续 timeout、UI window 路由、signal correlation 都会围绕一条 ghost call 继续运行
- invite 入口本身没有 formal identity gate

建议：

- `call_invite` 入站也应要求非空 `call_id/session_id`
- malformed invite 不应再进入 `_active_call` 单一真相
- invite、state、terminal 三类入站都应统一走同一套 payload identity 校验

### F-817：消息正式发送入口也没有复用 private-session visibility gate；异常直聊仍可继续发送并广播新消息

状态：已修复（2026-04-14）

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的：
  - `send_message()`
  - `send_ws_message()`
- 都只做：
  - `_ensure_membership(...)`
- 不会像 [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `get_session()` / `list_sessions()` 那样再过：
  - `_is_visible_private_session(...)`
- [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 的 `chat_message` 路径
- 也只是：
  - `get_session_member_ids(...)`
  - `send_ws_message(...)`
  - 然后按 member_ids 广播 `chat_message`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 一条已经被 direct visibility 模型判成“不可见/404”的异常私聊
- 仍可继续通过 HTTP / WS 正式发送入口创建新消息
- 还会继续给成员 fanout realtime `chat_message`
- direct visibility contract 在“能否看见会话”和“能否继续对会话发消息”之间继续分裂

建议：

- 消息正式发送入口也应复用统一的 private-session visibility gate
- 不要再让不可见直聊继续产出 ghost message / realtime fanout

### F-818：`read_message_batch()` 和 WS `read_ack/read` 也没有复用 private-session visibility gate；异常直聊仍可继续推进 read cursor 并广播已读

状态：已修复（2026-04-14）

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `batch_read()`
- 只做：
  - `_ensure_membership(current_user.id, session_id)`
- [messages.py](/D:/AssistIM_V2/server/app/api/v1/messages.py) 的 `read_message_batch()`
- 成功后继续：
  - `get_session_member_ids(...)`
  - 广播 `read`
- [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 的 `read_ack/read` 路径
- 也是同一套：
  - `batch_read(...)`
  - `get_session_member_ids(...)`
  - 广播 `read`
- 这条链全程都没有复用：
  - `_is_visible_private_session(...)`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2/server/app/api/v1/messages.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 已被 direct visibility 模型隐藏的异常直聊
- 仍可继续推进已读游标、追加 read event、广播 realtime 已读
- “不可见会话”不仅还能发 typing，还能继续改变对端 read state

建议：

- read mutation 链也应复用 private-session visibility gate
- 不要再让异常直聊继续产生 ghost read / read broadcast

### F-819：`edit/recall/delete` 也没有复用 private-session visibility gate；异常直聊仍可继续广播消息 mutation event

状态：已修复（2026-04-14）

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的：
  - `edit()`
  - `recall()`
  - `delete()`
- 都不会复用：
  - `_is_visible_private_session(...)`
- `edit/recall` 只校验：
  - message 存在
  - sender 是否是当前用户
  - 时间窗口是否合法
- `delete()` 也只校验 message 存在和 sender
- [messages.py](/D:/AssistIM_V2/server/app/api/v1/messages.py) 和 [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py)
- 后续还都会：
  - `get_session_member_ids(...)`
  - fanout `message_edit/message_recall/message_delete`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2/server/app/api/v1/messages.py)
- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 已被 direct visibility 模型隐藏的异常直聊
- 仍可继续编辑、撤回、删除旧消息
- 还会继续给成员广播 message mutation realtime
- 会话 visibility contract 在消息 mutation 链上仍然没有真正收口

建议：

- edit / recall / delete 这条 mutation 链也应复用统一的 private-session visibility gate
- 不要再让不可见直聊继续产生 ghost message mutation

### F-820：`call_ringing` fanout 到主叫全部在线设备后，主叫被动镜像设备也会凭一条 ringing payload 直接 materialize 本地 outgoing call 并弹 ringing UI

状态：closed（2026-04-14）

修复记录：

- sender-side `call_invite` echo 只投递给发起通话的当前连接；主叫其它连接不会仅凭后续 ringing materialize outgoing call
- `CallManager._handle_state_event()` 必须匹配本地当前 call，passive device 没有同一 current call 时会丢弃 `call_ringing`
- 重复 `call_ringing` 现在按当前状态幂等丢弃，不再重复弹窗或重放 ringing UX

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `ringing()`
- 会把事件发给：
  - `[call.initiator_id]`
- 也就是主叫账号的全部在线设备
- 而 [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 的 `_handle_state_event()`
- 不要求本地先存在同一 `call_id` 的 invite / active call
- 会直接 `_merge_state(payload, status="ringing")`
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_ringing()`
- 随后又会无条件：
  - `_ensure_call_window(call)`
  - `window.set_status_text("Ringing...")`
  - 弹 `InfoBar.info(...)`

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 主叫在 A 设备发起外呼后
- 同账号 B 设备即使从未收到 sender-side invite echo
- 也会在收到 `call_ringing` 时凭单条 payload 直接生成一通 outgoing active call
- 并弹出 ringing 窗口与提示
- 通话多设备镜像仍然把 participant-level event 错当成 current-device authoritative UX 事件

建议：

- `call_ringing` 的 participant mirror 和 current-device outbound UX 应拆开
- 被动镜像设备不应仅凭一条 ringing payload 就 materialize/展示本地 ringing call

### F-821：群公告消息广播使用的是 mutation 前缓存的 `participant_ids`，而后续 `group_profile_update` event 又会重新取成员集；同一次群资料修改可能 fanout 到两套不同 roster

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `update_group_profile()`
- 在事务动作开始前先取一次：
  - `participant_ids = self.sessions.list_member_ids(group.session_id)`
- 然后把这份 roster 塞进 `GroupProfileUpdateResult`
- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `update_group_profile()`
- 后续用这份缓存的 `result.participant_ids` 去广播群公告消息
- 但 `_broadcast_group_profile_update()` 里又会重新调用：
  - `record_group_profile_update_event(...)`
  - 并在里面重新读取当前成员集

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- 同一次群资料 mutation
- 公告消息 fanout 和 `group_profile_update` event fanout 并不保证打到同一批成员
- 并发成员变更下：
  - 已被移除成员可能仍收到群公告消息
  - 新加入成员可能收到 profile update 却漏掉对应公告消息
- 同一事务结果在两条 realtime 链路上继续没有统一的 canonical recipient roster

建议：

- 群公告消息和 `group_profile_update` 至少应共享同一份定格 recipient roster
- 不要继续让 route 一条用缓存 roster、一条再临时重读当前成员集

### F-822：`/messages/unread` 总未读统计也没有复用 direct visibility gate；异常直聊仍会继续贡献全局未读 badge

状态：已修复（2026-04-14）

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `unread_summary()`
- 直接返回：
  - `self.messages.unread_total_for_user(current_user.id)`
- [message_repo.py](/D:/AssistIM_V2/server/app/repositories/message_repo.py) 的 `unread_total_for_user()`
- 只按：
  - `SessionMember`
  - `last_read_seq`
  - `Message.sender_id != user_id`
  计算总数
- 这条链不会像 [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 那样再过：
  - `_is_visible_private_session(...)`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\repositories\message_repo.py](D:\AssistIM_V2/server/app/repositories/message_repo.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 即使一条异常私聊已经被 direct visibility 模型从会话列表里隐藏
- 它的未读消息仍会继续计入 `/messages/unread` 的全局总数
- 顶部 badge total 和会话可见性仍然不是同一份 authoritative truth

建议：

- 总未读统计也应复用同一套 private-session visibility gate
- 不要再让隐藏会话继续贡献 ghost unread total

### F-823：`delete_group()` 只删 group/session 记录，不清任何 group avatar 资产；删群后会留下 orphan 文件

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `delete_group()`
- 事务里只做：
  - `self.groups.delete_group(group, commit=False)`
  - `self.sessions.delete_session(group.session_id, commit=False)`
- 不会调用任何：
  - file delete
  - avatar cleanup
- 但 [avatar_service.py](/D:/AssistIM_V2/server/app/services/avatar_service.py) 表明 group avatar 目前可能来自两类资产：
  - `avatar_kind == "custom"` 时绑定 `avatar_file_id`
  - `avatar_kind == "generated"` 时 `build_group_avatar(...)` 会在文件系统生成 PNG

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)
- [D:\AssistIM_V2\server\app\repositories\group_repo.py](D:\AssistIM_V2/server/app/repositories/group_repo.py)

影响：

- 删群后：
  - custom group avatar 对应的 `StoredFile` 记录/文件可能继续残留
  - generated group avatar PNG 也可能继续残留在磁盘
- group 生命周期和媒体资产生命周期没有统一收口
- 长期运行下会留下 orphan 文件和隐私残留

建议：

- `delete_group()` 应明确收口 group avatar 资产清理 contract
- 至少区分 custom file 与 generated avatar 两条资源释放路径

### F-824：`call_busy` 只 fanout 给主叫账号，但主叫其它在线设备也会凭单条 busy payload 直接走 busy 终态 UI 和本地结果消息

状态：closed（2026-04-14）

修复记录：

- `_handle_busy()` 现在必须命中本地当前 call；没有发起本次 invite 的同账号其它设备会丢弃 busy payload
- busy 不再能凭空 `_merge_state()` materialize outgoing call，也不会触发 passive device 的终态音效、InfoBar 或结果系统消息
- `_schedule_call_result_message()` 同时改为按 `call_id` 单一终态去重，避免晚到终态写出多条矛盾结果

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `invite()` 在 busy 分支返回：
  - `("call_busy", [initiator_id], payload)`
- 也就是主叫账号的全部在线设备都会收到 busy event
- [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 的 `_handle_busy()`
- 不要求本地先存在同一 `call_id` 的 active call
- 会直接 `_merge_state(payload, status="busy")`
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_busy()`
- 随后又会无条件：
  - `_schedule_call_result_message(call, outcome="busy")`
  - 弹 busy `InfoBar`
  - 播放终态音效

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 主叫在 A 设备发起外呼失败为 busy 时
- 同账号 B 设备即使从未参与这次外呼
- 也会凭单条 busy payload 直接走 busy 终态 UX
- 甚至还可能各自补一条本地“忙线”结果系统消息
- busy participant mirror 仍被错误消费成 current-device authoritative 终态

建议：

- `call_busy` 的 mirror 和 current-device outbound failure UX 应拆开
- 被动镜像设备不应仅凭单条 busy payload 就弹终态提示或写本地结果消息

### F-825：`create_group/add_member/leave_group` 会在同一请求里重复执行 `ensure_group_avatar()`；事务里先跑一次，返回序列化时又立刻再跑一次

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的：
  - `create_group()`
  - `add_member()`
  - `leave_group()`
- 都会在事务动作里直接调用：
  - `self.avatars.ensure_group_avatar(group)`
- 但这些路径返回前又都会继续：
  - `self.serialize_group(group, include_members=True, current_user_id=...)`
- 而 `serialize_group()` 开头又会再次：
  - `self.avatars.ensure_group_avatar(group)`

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)

影响：

- 同一次群 lifecycle mutation
- 会同步重复做两次：
  - generated avatar 文件生成
  - `session.avatar` mirror 更新
- 事务持有时间和返回时延都会被无意义放大
- 也让前面已经确认的“DB mutation + file side effect 混在一起”问题进一步恶化

建议：

- mutation path 和 response serialization 之间不要再重复执行 `ensure_group_avatar()`
- 至少保证同一请求里 group avatar 生成/mirror 只发生一次

### F-826：generated group avatar 每次 bump 都会写出新版本文件，但没有任何旧版本清理；成员变更和头像变更会稳定留下历史 PNG

状态：已修复（2026-04-14）

现状：

- [avatar_service.py](/D:/AssistIM_V2/server/app/services/avatar_service.py) 的 `bump_group_avatar_version()`
- 每次都会把：
  - `avatar_version += 1`
- [group_avatars.py](/D:/AssistIM_V2/server/app/media/group_avatars.py) 的 `group_avatar_storage_key()`
- 直接把版本编码进文件名：
  - `group_avatars/{group_id}_v{version}.png`
- `build_group_avatar()` 只会写当前版本目标文件
- 代码里没有任何：
  - 删除旧版本 PNG
  - 清理过期 generated avatar
  - 合并旧版本文件

证据：

- [D:\AssistIM_V2\server\app\services\avatar_service.py](D:\AssistIM_V2/server/app/services/avatar_service.py)
- [D:\AssistIM_V2\server\app\media\group_avatars.py](D:\AssistIM_V2/server/app/media/group_avatars.py)

影响：

- 群成员变更、资料头像变更、显式 bump 都会不断留下旧版本 generated group avatar 文件
- 长期运行下磁盘只增不减
- generated avatar 生命周期和 group lifecycle / avatar_version lifecycle 没有统一清理 contract

建议：

- generated group avatar 需要正式的旧版本回收策略
- 至少在 bump 或删群时清理过期版本文件

### F-827：同一条来电 `call_invite` 会 fanout 到被叫账号全部在线设备，而每台设备都会立即自动发送一次 `call_ringing`；主叫会收到重复 ringing fanout

状态：closed（2026-04-14）

修复记录：

- realtime hub 增加 `send_json_to_one_user_connection()`，`chat_ws.py` 对 `call_invite` 只投递给被叫账号的一个 primary connection
- `CallService.ringing()` 对已 ringing 的 call 走幂等 no-op fanout，不再重复通知 caller
- caller 侧 `CallManager` 对重复 ringing 做状态幂等，双层避免重复 ringing UX

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `invite()`
- 当前返回：
  - `("call_invite", [recipient_id], payload)`
- 这会把同一条 invite 发给被叫账号的全部在线连接
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_invite_received()`
- 每台收到 invite 的设备都会立即调度：
  - `self._chat_controller.send_call_ringing(call.call_id)`
- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `ringing()`
- 只校验：
  - `user_id == call.recipient_id`
- 并不会区分“到底是哪一台被叫设备正式进入响铃”

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 被叫账号如果同时在线多台设备
- 一次来电会被每台设备各自回一条 `call_ringing`
- 主叫侧会收到重复 ringing fanout
- 通话状态机仍缺“哪台被叫设备正式 claim 了 ringing”这一层 canonical contract

建议：

- `call_invite -> call_ringing` 之间应补 callee-device claim / ringing-owner contract
- 不要继续让每台收到 invite 的设备都自动回一条 `call_ringing`

### F-828：同一条来电会在被叫账号每台在线设备上都强制刷新 ICE 并预热隐藏通话窗口；一次 invite 会被放大成 N 路预热任务

状态：closed（2026-04-14）

修复记录：

- `call_invite` 现在只投递给一个 callee primary connection，不再让被叫所有在线连接都进入来电处理
- `ChatInterface._on_call_invite_received()` 已移除 invite 阶段的 `_prepare_incoming_call_window()` 调度
- ICE refresh 和媒体窗口创建推迟到 accepted 后，来电提示阶段不再强制刷新 ICE 或预热隐藏窗口

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `invite()`
- 会把 invite 发给被叫账号全部在线设备
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_invite_received()`
- 每台设备收到后都会调度：
  - `_prepare_incoming_call_window(active_call)`
- 而 `_prepare_incoming_call_window()` 会先：
  - `await self._chat_controller.refresh_call_ice_servers(force_refresh=True)`
- 然后：
  - `_ensure_call_window(call, reveal=False)`
  - `window.prepare_media(is_caller=False)`

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 一次来电在被叫账号多设备场景下
- 会被放大成多路 `refresh_call_ice_servers(force_refresh=True)`
- 以及多路隐藏窗口 / 媒体预热任务
- 这不只是单设备“提前预热”的问题，而是缺少 callee-device arbitration 后的确定性放大

建议：

- 来电预热必须绑定单一 callee media device / ringing owner
- 其它被动镜像设备最多保留轻量镜像状态，不应继续强制刷新 ICE 或预热媒体窗口

### F-829：群公告消息会先于 `group_profile_update` 发出，但客户端公告 banner/version state 只会在 session 侧 profile payload 到达后更新；两条链路顺序分裂

状态：已修复（2026-04-14）

现状：

- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `update_group_profile()`
- 当前顺序是：
  1. `_broadcast_group_announcement_message(...)`
  2. `_broadcast_group_profile_update(...)`
- [chat_panel.py](/D:/AssistIM_V2/client/ui/widgets/chat_panel.py) 和 [message.py](/D:/AssistIM_V2/client/models/message.py)
- 公告 banner 的可见性依赖：
  - `session.group_announcement_needs_view()`
  - `session.group_announcement_message_id()`
- 这些字段都来自 session extra / group profile payload
- 单独收到一条公告 `chat_message` 并不会更新 session 侧公告版本状态

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\client\ui\widgets\chat_panel.py](D:\AssistIM_V2/client/ui/widgets/chat_panel.py)
- [D:\AssistIM_V2\client\models\message.py](D:\AssistIM_V2/client/models/message.py)
- [D:\AssistIM_V2\client\managers\session_manager.py](D:\AssistIM_V2/client/managers/session_manager.py)

影响：

- 客户端可能先收到新的群公告消息
- 但群公告 banner / viewed-version 状态要等后面的 `group_profile_update` 才能更新
- 如果第二条链路晚到或失败，公告内容和 session 侧公告版本会继续分裂

建议：

- 群公告消息和 session 侧公告版本应共享同一份 canonical output / ordering contract
- 不要继续让“公告消息已到达”和“公告 banner/version 已更新”走两条松散排序的链路

### F-830：主叫侧 `call_ringing` UI 不是幂等消费；被叫多设备重复回 `call_ringing` 时，caller 会反复重放 ringing UX

状态：closed（2026-04-14）

修复记录：

- `CallManager._handle_state_event()` 在当前状态已经是 `ringing` 时直接丢弃重复 `call_ringing`
- `ChatInterface._on_call_ringing()` 不再激活 signaling；pre-accept 阶段不会因为重复 ringing 冲出 queued offer/ICE
- 服务端 `CallService.ringing()` 对已 ringing 的重复请求不再向 caller fanout

现状：

- 前面的 `F-827` 已确认：
  - 多台被叫设备会各自自动发送 `call_ringing`
- [call_manager.py](/D:/AssistIM_V2/client/managers/call_manager.py) 的 `_handle_state_event()`
- 每收到一条 `call_ringing` 都会继续：
  - `_merge_state(payload, status="ringing")`
  - `emit(CallEvent.RINGING, ...)`
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_ringing()`
- 没有任何去重 / 幂等 guard
- 每次都会：
  - `_ensure_call_window(call)`
  - `window.set_status_text("Ringing...")`
  - `window.activate_signaling()`
  - 弹 `InfoBar.info(...)`

证据：

- [D:\AssistIM_V2\client\managers\call_manager.py](D:\AssistIM_V2/client/managers/call_manager.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 被叫账号只要有多台设备在线
- caller 侧就可能连续吃到多条重复 ringing event
- 同一通电话的 caller UX 会重复重放 ringing 文案、状态切换和 signaling 激活动作

建议：

- caller 侧对 `call_ringing` 至少要补按 `call_id` 的幂等消费
- `call_ringing` 也不应继续被多台被叫设备重复生成

### F-831：来电没有任何 callee primary-device claim；被叫账号所有在线设备都会同时 surface 完整来电 UI 和响铃

状态：closed（2026-04-14）

修复记录：

- `RealtimeHub` 新增单用户单连接投递入口，`call_invite` 的被叫侧投递改为一个 deterministic primary connection
- 同一来电不再广播给被叫账号全部在线设备，因此不会在所有设备同时弹 toast、响铃和进入来电媒体准备
- 其它同账号连接仍可通过后续参与者级终态/资料同步感知结果，但不会 surface 完整来电 UI

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `invite()`
- 只按被叫 user fanout：
  - `("call_invite", [recipient_id], payload)`
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_on_call_invite_received()`
- 每台收到 invite 的设备都会：
  - 构造 `IncomingCallToast`
  - `toast.show()`
  - `_start_call_ring_sound(AppSound.CALL_INCOMING_RING)`
  - 调度 `_prepare_incoming_call_window(...)`
- 当前没有任何：
  - primary device
  - call claim
  - passive mirror only
 这类 callee-side device contract

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- 被叫账号只要多设备在线
- 同一通来电就会在所有设备上同时弹来电 toast、同时响铃、同时预热通话窗口
- 后续重复 `call_ringing`、重复 prewarm、重复 accept/reject race 都是在这条“没有 callee primary-device claim”的根上继续放大

建议：

- 来电 contract 需要明确：
  - 哪台设备是 primary interactive callee device
  - 哪些设备只是 passive mirror
- passive mirror 设备不应继续 surface 完整来电 UI、响铃和媒体预热

### F-832：同账号被叫其它在线设备仍可再次 `accept` 同一通电话；服务端只按 user 校验，不按 accepter device claim 收口

状态：closed（2026-04-14）

修复记录：

- `CallService.accept()` 只允许 `invited/ringing` 状态进入 accepted；call 一旦 accepted，重复 accept 会返回 `SESSION_CONFLICT`
- `InMemoryCallRegistry.mark_accepted()` 不再重复刷新 `answered_at`
- 被叫侧 invite 只投递给一个 primary connection，其它连接不会获得可 accept 的本地 incoming current call
- 已补 `test_call_service_rejects_duplicate_accept_and_post_accept_reject`

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `accept()`
- 只校验：
  - `user_id == call.recipient_id`
- 然后直接：
  - `self.registry.mark_accepted(call.call_id)`
  - `return "call_accept", call.participant_ids(), payload`
- [call_registry.py](/D:/AssistIM_V2/server/app/realtime/call_registry.py) 的 `mark_accepted()`
- 也不看当前是否已经 accepted
- 会再次重写：
  - `status = "accepted"`
  - `answered_at = utcnow()`
- 这意味着被叫账号只要多设备在线
- 一台设备 accept 之后，另一台同账号设备仍可再次发 `call_accept`

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\server\app\realtime\call_registry.py](D:\AssistIM_V2/server/app/realtime/call_registry.py)

影响：

- 被叫侧没有单一 accepter device / media device claim
- 同一通电话可以被同账号多台设备重复 accept
- 这会继续触发重复 accepted fanout、重写 `answered_at`，并把前面已确认的多设备媒体启动问题进一步放大

建议：

- `call_accept` 必须绑定单一 accepter device contract
- 一旦已有 accepted owner，其它同账号设备的重复 accept 应明确拒绝或退化成被动镜像同步

### F-833：`DELETE /groups/{group_id}/members/{user_id}` 只返回 `204`，没有 canonical group snapshot；客户端只能在 mutation 成功后额外 `fetch_group()`

状态：已修复（2026-04-14）

现状：

- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `remove_member()`
- 当前只做：
  - `GroupService(db).remove_member(...)`
  - `return Response(status_code=204)`
- [contact_service.py](/D:/AssistIM_V2/client/services/contact_service.py) 的 `remove_group_member()`
- 也只是发出这条 `DELETE`
- [contact_controller.py](/D:/AssistIM_V2/client/ui/controllers/contact_controller.py) 的 `remove_group_member()`
- mutation 成功后只能再额外：
  - `return await self.fetch_group(group_id)`

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\client\services\contact_service.py](D:\AssistIM_V2/client/services/contact_service.py)
- [D:\AssistIM_V2\client\ui\controllers\contact_controller.py](D:\AssistIM_V2/client/ui/controllers/contact_controller.py)

影响：

- remove-member 的正式返回值本身不足以形成 authoritative follow-up
- 客户端只能靠“mutation 已提交 + 再查一次 group”拼出最新快照
- 一旦第二次 `fetch_group()` 失败，就会把已成功 mutation 误报成失败，并继续放大前面已经确认的 route split-phase 问题

建议：

- remove-member 应直接返回 mutation 后的 canonical group snapshot，或同步进入正式 realtime/history event 模型
- 不要继续把 actor 端 authoritative 收口外包给第二次 `fetch_group()`

### F-834：`POST /groups/{group_id}/leave` 只返回 `{\"status\":\"left\"}`，没有 authoritative tombstone / removal payload；客户端只能靠本地删 session 和手工刷新联系人收口

状态：已修复（2026-04-14）

现状：

- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `leave_group()`
- 当前只返回：
  - `{"status": "left"}`
- [contact_service.py](/D:/AssistIM_V2/client/services/contact_service.py) 的 `leave_group()`
- 也只把这份状态字典向上传
- [chat_interface.py](/D:/AssistIM_V2/client/ui/windows/chat_interface.py) 的 `_leave_group_async()`
- 服务端成功后只能本地手工：
  - `session_controller.remove_session(session_id)`
  - `emit(ContactEvent.SYNC_REQUIRED, {"reason":"group_membership_changed"})`

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\client\services\contact_service.py](D:\AssistIM_V2/client/services/contact_service.py)
- [D:\AssistIM_V2\client\ui\windows\chat_interface.py](D:\AssistIM_V2/client/ui/windows/chat_interface.py)

影响：

- leave-group 的正式输出没有携带：
  - 哪个 session/group 被 authoritative 移除
  - 当前用户后的 canonical 会话可见性状态
- actor 端当前只能靠本地 session 删除和联系人页手工 refresh hack 收口
- 这也解释了为什么 leave-group 到现在仍没有进入统一的 realtime/history lifecycle 模型

建议：

- leave-group 应明确返回 authoritative removal payload，或直接进入正式的 session/group membership event 模型
- 不要继续让客户端自己拼“删本地 session + 刷联系人”的补丁闭环

### F-835：通话正式入口也没有复用 private-session visibility gate；已被 visibility 模型隐藏的异常直聊仍可继续发起/接受/挂断/信令

状态：closed（2026-04-14）

修复记录：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `_require_private_session()` 已复用 private-session visibility gate
- hidden private session 现在会在 invite/accept/reject/hangup/offer/answer/ice 全链路统一返回 `404`

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `_require_private_session()`
- 当前只校验：
  - session 存在
  - `sessions.has_member(session_id, user_id)`
  - `session.type == "private"` 且非 AI
  - `len(member_ids) == 2`
- 它不会像 [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `list_sessions()/get_session()` 那样再过：
  - `_is_visible_private_session(session, member_ids)`
- 后续：
  - `invite()`
  - `_require_participant_call() -> accept()/reject()/hangup()/relay_offer()/relay_answer()/relay_ice()`
  都建立在这条 gate 上

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 异常直聊即使已经被 session visibility 模型从列表/详情里隐藏
- 只要 membership 还在且成员数看起来是 2
- 仍能继续发起 `call_invite`，也能继续 `accept/reject/hangup/offer/answer/ice`
- private-session visibility contract 现在不只是消息链漏口，连通话链也仍能产出 ghost call lifecycle

建议：

- `CallService` 也应复用统一的 private-session visibility gate
- 不要再让“对 session service 不可见”的异常直聊继续进入正式通话状态机

### F-836：`DELETE /groups/{group_id}` 只返回 `204`，没有 authoritative group/session tombstone payload；actor 端和其它端都拿不到正式删除结果

状态：已修复（2026-04-14）

现状：

- [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 的 `delete_group()`
- 当前只做：
  - `GroupService(db).delete_group(current_user, group_id)`
  - `return Response(status_code=204)`
- 这条 route 不返回：
  - 被删除的 `group_id/session_id`
  - canonical removal snapshot
  - 任何 deletion event payload
- 同时前面已经确认：
  - `delete_group()` 也没有正式 realtime/history lifecycle event

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- actor 端请求成功后，只知道“HTTP 204 成功”，拿不到 authoritative 删除结果
- 其它在线成员和其它设备也同样没有正式 deletion payload 可消费
- 这让 group delete 继续停留在“服务端已做 destructive mutation，但协议层没有 canonical output”的状态

建议：

- delete-group 应明确返回 authoritative removal payload，或进入正式 group/session deletion event 模型
- 不要继续让 `204` 承担整个群删除生命周期的全部 formal output

### F-837：服务端公开了 `DELETE /groups/{group_id}`，但桌面端根本没有对应的 service/controller/UI 边界；这个 destructive route 处于未接入主产品的游离状态

状态：已修复（2026-04-14）

现状：

- 服务端 [groups.py](/D:/AssistIM_V2/server/app/api/v1/groups.py) 明确公开：
  - `DELETE /groups/{group_id}`
- 但客户端全仓检索不到任何：
  - `delete_group(...)` service
  - controller boundary
  - UI entry / flow
- [contact_service.py](/D:/AssistIM_V2/client/services/contact_service.py) 当前只接了：
  - `get/update_group_profile`
  - `leave_group`
  - `add/remove member`
  - `update role`
  - `transfer ownership`
- 根本没有 delete-group 客户端边界

证据：

- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\client\services\contact_service.py](D:\AssistIM_V2/client/services/contact_service.py)

影响：

- 服务端保留了一条 destructive group lifecycle route
- 但桌面端正式产品路径根本不消费它
- 这让 group delete 继续停留在“协议上存在、主产品上游离”的状态，也会放大前面已经确认的：
  - `204` 无 tombstone payload
  - 无正式 realtime/history deletion event

建议：

- 要么把 delete-group 正式接入 service/controller/UI 边界
- 要么明确把这条 route 收敛成非主产品能力，不要继续维持半接入状态

### F-838：`add_member/update_member_role/transfer_ownership` 也是 shared mutation，但返回值仍直接复用 actor 视角的 `serialize_group(..., current_user_id=current_user.id)`

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的：
  - `add_member()`
  - `update_member_role()`
  - `transfer_ownership()`
- mutation 成功后分别返回：
  - `{"status":"added","group": serialize_group(..., current_user_id=current_user.id)}`
  - `{"status":"role_updated","group": serialize_group(..., current_user_id=current_user.id)}`
  - `serialize_group(..., current_user_id=current_user.id)`
- 也就是说，这三条 shared group lifecycle mutation 的 HTTP 返回，仍然都是 actor 视角的 viewer-scoped payload
- 返回值会继续夹带 actor 自己的：
  - `group_note`
  - `my_group_nickname`
  - 以及 viewer-scoped members 展示字段
- 但这三条 mutation 本质上修改的又都是 shared state：
  - 成员关系
  - 成员角色
  - 群 owner

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)

影响：

- 当前不只是 `PATCH /groups/{group_id}` 会把 shared mutation 和 actor-view payload 混在一起
- `add_member/update_member_role/transfer_ownership` 这三条 shared mutation 也在继续复用同样的 viewer-scoped返回
- 这会让 shared group lifecycle 的正式输出继续分裂：
  - actor 端拿到的是带 self-scoped 字段的 viewer payload
  - 其它端如果未来补 realtime/history event，又应消费 shared payload
- route response、shared state 和后续 event contract 很难真正收口成单一真相

建议：

- shared group mutation 应统一返回 shared canonical group payload
- actor 需要的 `group_note/my_group_nickname` 等 viewer-only detail，应走独立 self/detail contract

### F-839：服务端下行的 `call_*` 事件也统一把 outer `msg_id` 固定成 `call_id`，整场通话的多条 control/signaling event 共用同一个 transport id

状态：closed（2026-04-14）

修复记录：

- `chat_ws.py` 下行 call fanout 已改为 `msg_id=str(uuid.uuid4())`
- `call_id` 只保留在 payload 中作为业务级通话实例 id，outer envelope id 不再被整场通话复用
- 这同时覆盖 invite/ringing/accept/reject/hangup/offer/answer/ice 的服务端下行事件

现状：

- [chat_ws.py](/D:/AssistIM_V2/server/app/websocket/chat_ws.py) 在处理：
  - `call_invite`
  - `call_ringing`
  - `call_accept`
  - `call_reject`
  - `call_hangup`
  - `call_offer`
  - `call_answer`
  - `call_ice`
- 统一在 fanout 时执行：
  - `ws_message(outbound_type, payload, msg_id=payload.get("call_id", ""))`
- 也就是说，服务端发给客户端的整场通话事件外层 envelope，都会复用同一个 `msg_id=call_id`
- 这不是“同一命令重试复用同一 transport id”，而是：
  - 不同阶段状态事件
  - 不同 signaling 命令
  - 多条 `call_ice`
  全部共享同一个 outer transport id

证据：

- [D:\AssistIM_V2\server\app\websocket\chat_ws.py](D:\AssistIM_V2/server/app/websocket/chat_ws.py)

影响：

- 现在不只是客户端出站层把 `call_id` 复用成 `msg_id`
- 连服务端下行的 call event envelope 也在继续复用同一个 transport id
- 这会让：
  - transport 日志
  - 事件级排障
  - 客户端侧“到底是 invite / ringing / accept / 哪一条 ice” 的 envelope 级关联
  全都停留在半收口状态
- 尤其在多设备镜像和重复 ringing/ICE 的场景下，outer `msg_id` 已经失去“标识这一次下行事件”的能力

建议：

- `call_id` 应继续保留在 payload 里作为业务级通话实例 id
- 下行 `msg_id` 应单独标识这一次具体 event/signaling fanout，不要继续整场通话共用一个 transport id

### F-840：`POST /sessions/direct` 的 `name` 不只是“命中已有时会忽略”，而是新建直聊时会被当成 shared `session.name` 正式落库

状态：已修复（2026-04-14）

现状：

- [session.py](/D:/AssistIM_V2/server/app/schemas/session.py) 的 `CreateDirectSessionRequest`
- 当前正式暴露了可选：
  - `name`
- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `create_private()`
- 在真正创建新直聊时会直接：
  - `self.sessions.create(name or "Private Chat", "private", ...)`
- 也就是说，这个 `name` 不是纯客户端展示 hint，而会变成直聊共享 session 的正式持久化名称

证据：

- [D:\AssistIM_V2\server\app\schemas\session.py](D:\AssistIM_V2/server/app/schemas/session.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 直聊本应主要由 counterpart identity 派生展示名
- 但当前正式 contract 仍允许任意调用方在创建时写入一个 shared `session.name`
- 于是同一类 direct session 继续同时存在两套语义：
  - 一套是基于 counterpart 的 direct display
  - 一套是可由创建请求写入的 shared session name
- 这会让：
  - server session snapshot
  - client direct display
  - 后续复用已有会话时的 `name` ignored 语义
  继续分裂成不一致的 contract

建议：

- 如果 direct session 的正式语义是“名称由 counterpart 派生”，就应从 create-direct contract 移除 `name`
- 如果确实要支持 direct shared naming，则要把它定义成正式 shared field，并统一复用到 get/list/reuse 路径

### F-841：通话 private-session gate 只校验 `len(member_ids) == 2`，不校验“两位不同成员”；和 session visibility 的 distinct-member 口径继续分裂

状态：closed（2026-04-14）

修复记录：

- `CallService._require_private_session()` 已把 member ids 先 strip、去空、去重
- call gate 复用 `SessionService._is_visible_private_session(session, distinct_member_ids)`，再要求 distinct member 数量为 2
- 重复成员或 hidden private session 会在 invite/accept/reject/hangup/signaling 全链路统一拒绝
- 已补 `test_call_service_rejects_hidden_private_session_before_entering_call_state_machine` 和 `test_call_service_rejects_private_session_with_more_than_two_members`

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `_require_private_session()`
- 当前只要求：
  - session 存在
  - 当前用户仍是成员
  - `session.type == "private"` 且非 AI
  - `len(member_ids) == 2`
- 但 [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `_is_visible_private_session()`
- 对 private session 的正式可见性口径已经是：
  - `len(set(member_ids)) >= 2`
- 也就是说，通话链判断的是“有两条 member row”，不是“有两个不同成员”

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 一旦 private session 出现重复成员或 membership drift
- 通话 formal gate 和 session visibility gate 会继续给出不同结论
- session service 可能已经把这条直聊判成异常/不可见
- call service 却仍可能因为“member row 数量看起来是 2”而继续放行到 call lifecycle
- 这会让 private direct 的异常状态在消息链、会话链、通话链之间继续分裂

建议：

- call private-session gate 应统一到“两位不同成员”的 authoritative 口径
- 不要继续只按 `len(member_ids)` 判断 1:1 call 是否合法

### F-842：`GET /groups/{group_id}` 的 detail payload 也直接夹带 `group_note/my_group_nickname`，shared group detail 仍不是纯共享视图

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `get_group()`
- 直接返回：
  - `serialize_group(group, include_members=True, current_user_id=current_user.id)`
- 而 `serialize_group()` 在当前用户上下文下会继续写入：
  - `group_note`
  - `my_group_nickname`
- 这两个字段本质上都是当前查看者自己的 self-scoped member metadata
- 也就是说，不只是 `GET /groups` collection 在混 viewer-specific detail
- 连 `GET /groups/{group_id}` 这条 detail route 也不是一份纯 shared group snapshot

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- 当前群详情 formal payload 继续把：
  - shared group state
  - 当前用户自己的 self-scoped group metadata
  混在一份对象里
- 这会让：
  - detail query
  - shared realtime payload
  - self-profile payload
  三条 contract 继续没有清晰分层
- 调用方也无法把 `GET /groups/{id}` 当成真正可缓存、可共享比较的 canonical group detail

建议：

- `GET /groups/{group_id}` 应先定义 shared canonical detail payload
- `group_note/my_group_nickname` 这类 self-scoped detail 应拆到独立 self payload 或独立字段层

### F-843：`GET /sessions/{session_id}` 的 detail payload 也直接夹带 `group_note/my_group_nickname`，session detail 同样不是纯共享视图

状态：已修复（2026-04-14）

现状：

- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `get_session()`
- 最终直接返回：
  - `serialize_session(..., include_members=True, current_user_id=current_user.id)`
- 而 `serialize_session()` 在 group session 分支里，会按当前查看者继续写入：
  - `group_note`
  - `my_group_nickname`
- 也就是说，不只是 `GET /sessions` collection 会混入 viewer-specific detail
- 连 `GET /sessions/{session_id}` 这条 detail route 也不是纯 shared session snapshot

证据：

- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2/server/app/api/v1/sessions.py)

影响：

- 当前 session detail formal payload 继续把：
  - shared session/group state
  - 当前用户自己的 self-scoped group metadata
  混在一份对象里
- 这让：
  - `GET /sessions/{id}`
  - `GET /groups/{id}`
  - group self-profile payload
  之间的边界继续不清晰
- 调用方也无法把 session detail 当成真正可共享比较的 canonical snapshot

建议：

- `GET /sessions/{session_id}` 应先定义 shared canonical session detail
- `group_note/my_group_nickname` 这类 self-scoped detail 应拆到独立 self/detail contract

### F-844：通话 state/control payload 只有 `actor_id=user_id`，没有任何 `actor_device_id/active_device_id`；多设备下根本无法表达“哪台设备在正式执行这次动作”

状态：closed（2026-04-14）

修复记录：

- WS gateway 在 call state/control/signaling 下行 payload 中补入 `actor_connection_id`
- `call_ringing` 额外携带 `ringing_connection_id`，`call_accept` 额外携带 `accepted_connection_id/active_connection_id`，signaling 携带 `active_connection_id`
- 客户端 `ActiveCallState` 已建模这些 connection-scoped 字段；当前正式表达的是 active realtime connection，不再只剩 user-scoped `actor_id`
- 后续若把 connection claim 升级为持久设备 claim，可在这套字段语义上替换来源，不再阻塞本轮 current-device guard

现状：

- [call_service.py](/D:/AssistIM_V2/server/app/services/call_service.py) 的 `_call_payload()`
- 当前在：
  - `call_ringing`
  - `call_accept`
  - `call_reject`
  - `call_hangup`
  - 以及 `call_offer/call_answer/call_ice`
- 里最多只会附带：
  - `actor_id`
- 且这个 `actor_id` 只是用户 id，不是设备 id
- [client/models/call.py](/D:/AssistIM_V2/client/models/call.py) 的 `ActiveCallState`
- 也只建模了：
  - `actor_id`
- 没有任何：
  - `actor_device_id`
  - `ringing_device_id`
  - `accepted_device_id`
  - `active_media_device_id`
  之类的 device-scoped 字段

证据：

- [D:\AssistIM_V2\server\app\services\call_service.py](D:\AssistIM_V2/server/app/services/call_service.py)
- [D:\AssistIM_V2\client\models\call.py](D:\AssistIM_V2/client/models/call.py)

影响：

- 现在通话 formal payload 在多设备场景下只能表达：
  - “哪个用户触发了动作”
- 但完全不能表达：
  - “哪台设备正在响铃”
  - “哪台设备正式接听了”
  - “哪台设备是当前媒体设备”
- 这会让前面已经确认的一整串问题继续无解：
  - 重复 ringing
  - 重复 accept
  - passive mirror 设备误起媒体
  - 终态系统消息多设备重复写入
- 本质上不是客户端 guard 不够，而是 payload contract 自身缺了 device-scoped actor 层

建议：

- 通话 state/control payload 必须补 device-scoped actor contract
- 至少为 ringing / accept / active media / terminal writer 明确设备级字段，不要继续只靠 `actor_id=user_id`

### F-845：shared group/session payload 的 `members[]` 继续直接内联成员 `gender/region` 等资料切片，但这条链没有独立的 member-summary contract

状态：已确认

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `serialize_group()`
- 在 shared `members[]` 里直接写入：
  - `username`
  - `nickname`
  - `avatar`
  - `gender`
  - `region`
  - `role`
  - `joined_at`
- [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `serialize_session()`
- 在 session `members[]` 里也直接写入：
  - `username`
  - `nickname`
  - `avatar`
  - `gender`
  - `role`
  - `joined_at`
- 这些 `members[]` 又会被：
  - `GET /groups`
  - `GET /groups/{group_id}`
  - `GET /sessions`
  - `GET /sessions/{session_id}`
  - 以及多条 group shared mutation 的正式返回
  直接复用
- 但当前仓库里并没有一份独立、稳定的“shared member summary”正式 contract

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)
- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2/server/app/api/v1/sessions.py)

影响：

- 当前 shared group/session payload 实际上继续在承担“成员资料分发”的职责
- 但这条职责既没有正式 summary 边界，也没有和：
  - `/users` public summary
  - 好友列表 summary
  - direct counterpart summary
  对齐
- 结果是成员资料暴露面和字段集继续漂移：
  - group payload 带 `region`
  - session payload 不带 `region`
  - 两边都带 `gender`
  - 而 self/detail/shared 三层也不是同一套 member contract

建议：

- 为 shared session/group payload 单独定义 canonical member-summary contract
- 不要继续在 `members[]` 里随手扩张成员 profile 切片
- `gender/region` 这类资料字段是否应进入 shared payload，需要明确收口到正式边界

### F-846：`create_group()` 作为 shared create mutation，也直接返回 actor 视角的 `serialize_group(..., current_user_id=current_user.id)`

状态：已修复（2026-04-14）

现状：

- [group_service.py](/D:/AssistIM_V2/server/app/services/group_service.py) 的 `create_group()`
- 在真正创建完成后直接返回：
  - `serialize_group(group, include_members=True, current_user_id=current_user.id)`
- 这意味着建群这条 shared create mutation
- 从第一份正式输出开始，就已经混入了当前 actor 自己的 viewer-specific detail：
  - `group_note`
  - `my_group_nickname`
- 同时后续如果补 shared realtime/history lifecycle event
- 它们又应以 `current_user_id=None` 的 shared 视角对外传播

证据：

- [D:\AssistIM_V2\server\app\services\group_service.py](D:\AssistIM_V2/server/app/services/group_service.py)
- [D:\AssistIM_V2\server\app\api\v1\groups.py](D:\AssistIM_V2/server/app/api/v1/groups.py)

影响：

- 当前不只是：
  - `PATCH /groups/{id}`
  - `add_member/update_member_role/transfer_ownership`
  这些 shared mutation 会返回 actor-view payload
- 连最早的 shared create mutation `create_group()` 也从一开始就在混：
  - shared canonical group snapshot
  - actor-only self-scoped detail
- 这让 group lifecycle formal output 从 create 阶段起就没有统一的 shared contract

建议：

- `create_group()` 也应先定义 shared canonical group payload
- actor 端需要的 self-scoped detail 应拆到独立 self/detail contract，不要继续让 create 路由直接复用 viewer-scoped `serialize_group(...)`

### F-847：direct 消息 formal payload 仍直接下发 `session_name/session_avatar`，和 counterpart summary 并存成两套 direct 会话身份

状态：已确认

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的 `serialize_message()`
- 会无条件把 `_load_session_metadata()` 里的：
  - `session_name`
  - `session_avatar`
  - `participant_ids`
  直接写进消息 payload
- 但同一个 direct 会话在别的正式 payload 里又已经在走另一套语义：
  - `counterpart_id`
  - `counterpart_name`
  - `counterpart_username`
  - `counterpart_avatar`
- 尤其在前面已确认的：
  - `F-840`：direct create 可把请求里的 `name` 落成 shared `session.name`
  - `F-782`：direct session payload 同时带 `counterpart_*` 和完整 `members[]`
  这些问题存在时
- direct 消息 formal payload 就继续把 shared session identity 和 counterpart identity 混在一起往下游发

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 同一条 direct 消息现在可能同时携带两套“这是谁”的会话级身份：
  - 一套来自 `session_name/session_avatar`
  - 一套来自 direct/counterpart 语义
- 这会让消息 formal payload 继续无法作为单一的 canonical direct display contract
- 当前一旦 shared `session.name/avatar` 和 counterpart summary 漂移，下游调用方就没有明确规则判断哪一套才是正式真相

建议：

- direct 消息 payload 应收口成单一 direct display contract
- 如果 direct 会话正式语义是 counterpart-driven，就不要继续在消息 formal payload 里无条件内联 shared `session_name/session_avatar`

### F-848：session-bound 消息/已读 HTTP 路由对“不存在的 session”和“无 membership”没有统一错误语义，缺失 session 会直接退成 `403`

状态：已修复（2026-04-14）

现状：

- [message_service.py](/D:/AssistIM_V2/server/app/services/message_service.py) 的：
  - `list_messages()`
  - `send_message()`
  - `batch_read()`
- 都会先走：
  - `_ensure_membership(user_id, session_id)`
- 而 `_ensure_membership()` 只检查：
  - `self.sessions.has_member(session_id, user_id)`
  不先区分 session 是否存在
- 结果是 session 根本不存在时，这几条 HTTP 正式入口也会直接抛：
  - `403 not a session member`
- 但同一仓库里的其它正式入口又不是这套语义：
  - `SessionService.get_session()` 先 `get_by_id()`，缺失时回 `404 session not found`
  - `send_ws_message()` 也先 `get_by_id()`，缺失时回 `404 session not found`

证据：

- [D:\AssistIM_V2\server\app\services\message_service.py](D:\AssistIM_V2/server/app/services/message_service.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\api\v1\messages.py](D:\AssistIM_V2/server/app/api/v1/messages.py)

影响：

- 同样是 session-bound 的正式入口：
  - 有的缺 session 回 `404`
  - 有的缺 session 却回 `403`
- 调用方无法把：
  - “资源不存在”
  - “资源存在但我无权访问”
  当成稳定的 formal contract 区分
- 这也让 HTTP 和 WS 的同类 send/read 语义继续分叉

建议：

- session-bound message/read 路由应先收口到统一的 session existence + permission contract
- 不要继续让“缺失 session”在这条路上退化成 `403 not a session member`

### F-849：`DELETE /sessions/{session_id}` 只返回 `204`，没有任何 authoritative session tombstone/removal payload

状态：已修复（2026-04-14）

现状：

- [sessions.py](/D:/AssistIM_V2/server/app/api/v1/sessions.py) 的 `delete_session()`
- 当前只执行：
  - `SessionService(db).delete_session(current_user, session_id)`
  - `return Response(status_code=204)`
- 而 [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `delete_session()`
- 实际做的是 destructive 删除：
  - 校验 membership
  - 非 group 才允许
  - 直接调用 `SessionRepository.delete_session(session_id)`
- 也就是说协议层当前给 actor 端的 formal output 只有：
  - “HTTP 204 成功”
- 没有任何：
  - canonical removal snapshot
  - tombstone payload
  - final visibility/removal state

证据：

- [D:\AssistIM_V2\server\app\api\v1\sessions.py](D:\AssistIM_V2/server/app/api/v1/sessions.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)
- [D:\AssistIM_V2\server\app\repositories\session_repo.py](D:\AssistIM_V2/server/app/repositories/session_repo.py)

影响：

- 这条 route 不只是语义上和客户端“本地隐藏”冲突
- 它在 formal output 层也仍然停留在：
  - 服务端已做 destructive mutation
  - 但协议没有 canonical 删除结果
- actor 端请求成功后只知道“204 成功”，拿不到 authoritative removal/tombstone state
- 这也让 session delete 继续没有办法和：
  - realtime lifecycle event
  - offline compensation
  - 本地 tombstone 语义
  正式对齐

建议：

- 不要继续让 `204` 承担整个 session 删除生命周期的全部 formal output
- `delete_session()` 至少要返回 canonical removal/tombstone payload，或者明确并入正式 lifecycle event 模型

### F-850：`import_history_recovery_package()` 的返回把“本次导入结果”和“导入后全局 diagnostics”直接混成一份对象，scope 不是同一批状态

状态：已修复（2026-04-14）

修复说明：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `import_history_recovery_package()` 现在只返回本次 import delta：source device/user 与 imported counts。
- 全局 diagnostics 继续由 `get_history_recovery_diagnostics()` 单独提供，不再 merge 到 import result。

现状：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `import_history_recovery_package()`
- 在导入完成后先构造本次 import 结果：
  - `source_device_id`
  - `source_user_id`
  - `imported_signed_prekeys`
  - `imported_one_time_prekeys`
  - `imported_group_sessions`
  - `imported_group_sender_keys`
- 随后又直接：
  - `diagnostics = await self.get_history_recovery_diagnostics()`
  - `return { ..., **diagnostics }`
- 而这份 diagnostics 描述的是“导入后的全局 recovery state”，包括：
  - `source_device_count`
  - `primary_source_device_id`
  - `primary_source_user_id`
  - `last_imported_at`
  - `source_devices`
- 它和“这一次导入了什么”并不是同一 scope

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)

影响：

- 调用方当前拿到的是一份混合对象：
  - 一部分字段描述本次 import delta
  - 另一部分字段描述导入后的全局聚合状态
- 这会让 import result 没有单一 canonical 语义：
  - `source_user_id/source_device_id` 既像“本次导入来源”
  - 又和 `primary_source_*`、`source_devices[]` 这种全局视图并列出现
- 如果后续同一设备上已经积累了多份 recovery source，调用方很容易把：
  - 本次 import 结果
  - 当前全局 primary source
  混成一个对象理解

建议：

- `import_history_recovery_package()` 应拆成两层返回：
  - 本次 import canonical result
  - 可选的全局 diagnostics/snapshot
- 不要继续把 delta result 和 global diagnostics 直接 merge 成一份对象

### F-851：`export_history_recovery_package()` 里的 `source_user_id` 仍是调用方可传/可空的自报字段，不绑定本地真实身份

状态：已修复（2026-04-14）

修复说明：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 现在拒绝空 `source_user_id`，并要求 `source_user_id == target_user_id`，service 层不再生产跨账号/缺来源的 recovery package。
- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 从当前认证态传入 source user，并禁止 UI/controller 层覆盖为其它账号。

现状：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `export_history_recovery_package(...)`
- 当前签名是：
  - `target_user_id`
  - `target_device_id`
  - `source_user_id: str = ""`
- 后续无论 inner payload 还是 outer package
- 都直接写入：
  - `str(source_user_id or "").strip()`
- 也就是说，这个 history recovery package 的来源账号字段
- 不是从本地 bundle、当前认证态或其它本地权威身份材料里推导出来
- 而是一个调用方可控、甚至可为空的自报字段

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)

影响：

- 这会让 history recovery package 的 source identity contract 继续不稳：
  - 调用方可以传空 `source_user_id`
  - 也可以传和本地真实账号不一致的值
- 而 import 链又会把：
  - `payload.source_user_id`
  继续写入本地 recovery state / diagnostics
- 所以前面已经确认的 source identity 混乱，不只发生在 import 校验不足
- export 入口自身也还在生产可伪造、可缺省的 source identity

建议：

- `source_user_id` 不应继续作为 export service 的自由输入
- history recovery package 的 source identity 应直接绑定当前本地权威身份材料，不要继续接受调用方自报

### F-852：`AuthController.export_history_recovery_package()` 的返回同样把“本次导出结果”和全局 `history_recovery_diagnostics` 混成一份对象

状态：已修复（2026-04-14）

修复说明：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 export wrapper 只返回 `target_user_id`、`target_device_id` 和本次 `package`。
- 全局 history recovery diagnostics 保持为独立查询，不再混入 export action result。

现状：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `export_history_recovery_package()`
- 当前返回：
  - `target_user_id`
  - `target_device_id`
  - `package`
  - `history_recovery_diagnostics`
- 其中：
  - `package` 描述的是本次 export 结果
  - `history_recovery_diagnostics` 描述的是当前设备上的全局 recovery state
- 这两部分同样不是同一个 scope

证据：

- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)
- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)

影响：

- export route 当前和 import route 一样，都把：
  - 单次动作结果
  - 全局 diagnostics snapshot
  直接混在同一份返回对象里
- 调用方很难把：
  - “这次导出了什么”
  - “当前 recovery 全局状态是什么”
  分成稳定的 formal contract 来消费
- 这也让 recovery 这条链的 route/result 语义继续不统一：
  - service 层和 controller 层各自拼一份混合对象

建议：

- `export_history_recovery_package()` 也应拆成：
  - 单次 export canonical result
  - 可选的全局 diagnostics/snapshot
- 不要继续把 action result 和 global diagnostics 直接合并返回

### F-853：history recovery import 结果里同一份全局 diagnostics 被重复返回成两种 shape

状态：已修复（2026-04-14）

修复说明：

- [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 import wrapper 现在直接返回 E2EE service 的 import delta。
- 由于 service 不再平铺全局 diagnostics，controller 也不再追加嵌套 `history_recovery_diagnostics`，同一份全局状态不会以两种 shape 重复返回。

现状：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `import_history_recovery_package()`
- 已经把全局 diagnostics 直接平铺 merge 到返回对象里：
  - `source_device_count`
  - `primary_source_device_id`
  - `primary_source_user_id`
  - `last_imported_at`
  - `source_devices`
- 但 [auth_controller.py](/D:/AssistIM_V2/client/ui/controllers/auth_controller.py) 的 `import_history_recovery_package()`
- 在拿到这份结果后，又继续追加：
  - `history_recovery_diagnostics = await self.get_history_recovery_diagnostics()`
- 结果是同一份“导入后的全局 recovery state”
- 现在会同时以：
  - 顶层平铺字段
  - 嵌套 `history_recovery_diagnostics`
  两种 shape 一起返回

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)
- [D:\AssistIM_V2\client\ui\controllers\auth_controller.py](D:\AssistIM_V2/client/ui/controllers/auth_controller.py)

影响：

- import 结果当前不只是“delta 和 diagnostics 混在一起”
- 还把同一份全局 diagnostics 继续重复编码成两套 shape
- 调用方既可能读：
  - 顶层 `primary_source_* / source_device_count`
  也可能读：
  - `history_recovery_diagnostics.primary_source_* / source_device_count`
- 这让 recovery import route 的 formal output 更难收口，也更容易出现新旧调用方各读一套字段

建议：

- import route 应只保留一种 diagnostics 表示方式
- 不要继续同时返回：
  - 顶层平铺 diagnostics
  - 嵌套 `history_recovery_diagnostics`

### F-854：`SessionOut / SessionMemberOut` 已经明显落后于当前 session payload，session family 的 formal output schema 继续漂移

状态：已确认

现状：

- [session.py](/D:/AssistIM_V2/server/app/schemas/session.py) 里的：
  - `SessionOut`
  - `SessionMemberOut`
- 仍停留在较早的 session payload 形态
- 但 [session_service.py](/D:/AssistIM_V2/server/app/services/session_service.py) 的 `serialize_session()`
- 当前实际已经稳定返回更多字段：
  - session 级：
    - `group_id`
    - `owner_id`
    - `group_announcement`
    - `announcement_message_id`
    - `announcement_author_id`
    - `announcement_published_at`
    - `group_note`
    - `my_group_nickname`
  - member 级：
    - `group_nickname`
    - `role`
- 也就是说，session family 这组正式输出 schema
- 现在已经不是“少几个可选字段”这么简单
- 而是 session detail / collection / member summary 的实际 payload 和公开 `*Out` schema 已经形成稳定漂移

证据：

- [D:\AssistIM_V2\server\app\schemas\session.py](D:\AssistIM_V2/server/app/schemas/session.py)
- [D:\AssistIM_V2\server\app\services\session_service.py](D:\AssistIM_V2/server/app/services/session_service.py)

影响：

- 这会让 session family 继续维持“route 无 `response_model`，schema 只是文档碎片”的状态
- 调用方如果参考：
  - `SessionOut`
  - `SessionMemberOut`
  来理解正式输出
- 就会直接误解当前 session payload 的真实 contract
- 这也让前面已经确认的 shared/self-scoped session detail 问题更难收口：
  - 因为连当前实际输出了哪些字段
  - 都没有在 formal schema 层被明确建模

建议：

- 要么给 session family 正式补齐 `response_model`
- 要么至少让：
  - `SessionOut`
  - `SessionMemberOut`
  和当前 `serialize_session()` 的真实输出保持一致
- 不要继续让 session schema 停留在过期形态

### F-855：`history_recovery_diagnostics.primary_source_*` 只是按时间戳排序挑出的第一项，不是正式主来源 contract

状态：已修复（2026-04-15）

现状：

- [e2ee_service.py](/D:/AssistIM_V2/client/services/e2ee_service.py) 的 `get_history_recovery_diagnostics()`
- 会先构造 `source_devices[]`
- 然后仅按：
  - `imported_at`
  - `exported_at`
  - `source_device_id`
  做逆序排序
- 最后直接把 `source_devices[0]` 当成：
  - `primary_source_device_id`
  - `primary_source_user_id`
  - `last_imported_at`
- 也就是说，当前 diagnostics 里的“primary source”
- 并不是：
  - 当前设备最近一次实际恢复所绑定的正式来源
  - 经过额外验证的 source identity
  - 或显式持久化的 primary source 选择
- 而只是按排序规则选出的“第一条 source device 记录”

证据：

- [D:\AssistIM_V2\client\services\e2ee_service.py](D:\AssistIM_V2/client/services/e2ee_service.py)

影响：

- 这会让 `history_recovery_diagnostics` 的 UI-facing summary 语义继续漂移：
  - 同一份 recovery state 里只要再导入一个旧设备包
  - 或出现同时间窗口的多 source device
  - `primary_source_*` 就可能切到另一条记录
- 结合前面已经确认的：
  - history recovery 允许跨账号导入/导出
  - import/export result 还在混全局 diagnostics
- 当前 `primary_source_*` 更像“排序后的第一项”
- 而不是稳定、可解释的 formal diagnostics contract

建议：

- `history_recovery_diagnostics` 应单独定义 primary source 的正式语义
- 如果只是“最近导入来源”，就明确持久化这条关系
- 不要继续把：
  - `source_devices` 排序结果第一项
  直接当成 `primary_source_*`


## 4. 本轮 review 建议优先处理顺序

1. 先把 `encryption_mode` 收敛成服务端权威属性，补齐服务端入站校验
2. 尽快收口“删除会话”的正式语义，避免用户侧入口和服务端全局硬删除 API 并存
3. 再收口发送、编辑、撤回、删除、已读、typing 与通话 signaling 的正式入口和幂等模型，消除 HTTP / WS 分叉与半实现状态
