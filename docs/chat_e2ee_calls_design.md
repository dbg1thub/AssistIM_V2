# 聊天端到端加密与 1:1 通话设计草案

## 1. 目标

本文档给出 AssistIM 下一阶段能力的推荐落地顺序与边界约束：

- 私聊文本消息端到端加密
- 私聊附件端到端加密
- 1:1 语音通话
- 1:1 视频通话

本文档是增量设计草案，目标是让后续实现与现有分层、实时链路和状态模型兼容，而不是引入第二套架构。

## 2. 当前现状

当前项目已经具备以下安全能力：

- 服务端密码哈希
- JWT access token / refresh token
- token `session_version` 失效机制
- 客户端本地 token 通过 Windows DPAPI 加密保存
- 可切换 `http/https`、`ws/wss`

当前项目尚不具备以下能力：

- 聊天内容端到端加密
- 服务端消息静态加密
- 附件端到端加密
- 通话 signaling
- WebRTC 媒体链路
- STUN / TURN 配置分发
- 通话状态机与通话 UI

## 3. 范围与非目标

### 3.1 本阶段范围

本阶段只设计并建议优先实现：

- `private` 会话的 E2EE
- `private` 会话的 1:1 语音 / 视频通话
- 私聊附件加密上传
- 基础设备管理与密钥交换

### 3.2 本阶段非目标

以下能力明确延后：

- 群聊 E2EE
- 群语音 / 群视频
- 多端设备同时在线的复杂密钥恢复
- E2EE 下的服务端全文搜索
- E2EE 下的 AI 会话统一加密

原因：

- 群聊 E2EE 与 sender key / member change / 设备同步绑定太深
- 群通话需要 SFU / MCU 设计，复杂度远高于 1:1
- AI 会话需要服务端或外部 provider 看到明文，和默认 E2EE 目标冲突

## 4. 推荐实现顺序

推荐按以下顺序推进：

1. 先补齐生产传输安全基线
2. 再落 1:1 通话 signaling + WebRTC
3. 再落 1:1 文本 E2EE
4. 最后落附件 E2EE

原因：

- 通话的媒体加密由 WebRTC 的 DTLS-SRTP 直接提供，收益高、链路清晰
- 文本 E2EE 会影响消息模型、本地缓存、搜索和多端同步，改动面更大
- 附件 E2EE 需要在文本 E2EE 稳定后统一附件 envelope

## 5. 设计原则

- 不自定义音视频传输协议，媒体层直接使用 WebRTC
- 不自定义密码学原语，优先使用成熟方案与库
- 业务命令继续遵守 `UI -> Controller -> Manager -> Service -> Network`
- WebSocket 仍只做实时命令、事件和 signaling，不承载音视频媒体流
- E2EE 只改变消息载荷与密钥管理，不破坏 `msg_id`、`session_seq`、`event_seq`
- 服务端在 E2EE 私聊中可以路由密文，但不应依赖明文执行业务

## 6. 传输与部署基线

上线前必须满足：

- 生产环境 HTTP 统一使用 `https`
- 生产环境 WebSocket 统一使用 `wss`
- 通话必须提供 STUN，建议同时提供 TURN
- TURN 凭证通过后端短期签发，不在客户端写死长期密钥

约束：

- 开发环境可保留 `http/ws`
- 生产环境不允许继续把 `use_ssl=false` 当作默认部署方式

## 7. 1:1 通话设计

### 7.1 总体链路

1:1 通话拆成两层：

- signaling：走现有 AssistIM WebSocket
- media：走 WebRTC P2P

服务端职责：

- 校验双方是否有该私聊会话权限
- 转发通话 signaling
- 提供 STUN / TURN 配置
- 维护短生命周期通话状态

客户端职责：

- 采集麦克风 / 摄像头
- 创建和维护 WebRTC peer connection
- 本地渲染通话 UI
- 处理来电、接听、拒绝、挂断、设备切换

### 7.2 signaling 事件

建议新增以下 WebSocket `type`：

- `call_invite`
- `call_ringing`
- `call_accept`
- `call_reject`
- `call_hangup`
- `call_offer`
- `call_answer`
- `call_ice`

统一外层仍沿用当前协议：

```json
{
  "type": "call_invite",
  "seq": 0,
  "msg_id": "uuid",
  "timestamp": 0,
  "data": {}
}
```

其中 `data` 至少包含：

- `call_id`
- `session_id`
- `initiator_user_id`
- `target_user_id`
- `media_type`，值为 `voice` 或 `video`

`call_offer` / `call_answer` 附带：

- `sdp`

`call_ice` 附带：

- `candidate`
- `sdp_mid`
- `sdp_mline_index`

### 7.3 通话状态机

客户端 `CallManager` 维护单通话状态机：

- `idle`
- `outgoing`
- `incoming`
- `ringing`
- `connecting`
- `connected`
- `ending`
- `ended`

约束：

- 一个用户同一时刻只允许一个活跃 1:1 通话
- 新来电进入时，如果本地已有活跃通话，服务端直接返回 busy/reject
- 通话状态变化只由 `CallManager` 统一向 UI 广播

### 7.4 客户端新增模块

建议新增：

- `client/services/call_service.py`
- `client/managers/call_manager.py`
- `client/models/call.py`
- `client/ui/windows/call_window.py`

边界要求：

- UI 不直接操作 WebRTC 底层对象
- WebRTC transport 由 `CallManager` 或其下层适配器持有
- 通话 signaling 发送通过 `ConnectionManager`

### 7.5 服务端新增模块

建议新增：

- `server/app/services/call_service.py`
- `server/app/schemas/call.py`
- `server/app/realtime/call_registry.py`

说明：

- 1:1 通话 MVP 不要求先落数据库持久化
- 活跃通话状态允许放在可替换的基础设施边界里
- 历史通话记录如果需要，后续单独补 `call_logs`

## 8. 聊天 E2EE 设计

### 8.1 范围

只对 `private` 会话启用：

- 文本消息
- 图片 / 文件 / 视频附件消息

以下不启用：

- AI 会话
- 群聊
- 朋友圈

### 8.2 密码学建议

推荐采用成熟组合：

- 身份密钥交换：`X25519`
- 消息内容加密：`AES-256-GCM`
- 每条消息独立 nonce
- 设备公钥签名：`Ed25519` 或使用成熟协议库自带实现

正式实现建议优先接近 Signal 的设备模型，而不是自定义协议。

### 8.3 设备模型

服务端新增设备注册与 prekey 分发能力。

建议新增表：

- `user_devices`
- `user_prekeys`

`user_devices` 至少包含：

- `device_id`
- `user_id`
- `identity_key_public`
- `signing_key_public`
- `device_name`
- `created_at`
- `last_seen_at`

`user_prekeys` 至少包含：

- `id`
- `device_id`
- `prekey_id`
- `prekey_public`
- `signed_prekey_public`
- `signed_prekey_signature`
- `is_consumed`

### 8.4 会话与消息 envelope

E2EE 不改变会话层 `msg_id` / `session_seq` / `event_seq` 规则，只改变消息载荷语义。

建议把消息分成两层：

- 路由层元数据：服务端可见
- 密文层载荷：只有客户端可解

建议消息 payload 结构如下：

```json
{
  "message_type": "text",
  "content": "BASE64_CIPHERTEXT",
  "extra": {
    "encryption": {
      "scheme": "x25519-aesgcm-v1",
      "sender_device_id": "dev_a",
      "recipient_device_id": "dev_b",
      "session_key_id": "sk_123",
      "nonce": "BASE64_NONCE",
      "aad": "BASE64_AAD",
      "ciphertext_version": 1
    }
  }
}
```

说明：

- `content` 在 E2EE 私聊里不再是明文
- 服务端只负责持久化和转发密文
- 消息预览、搜索、AI 总结不再能依赖服务端明文

### 8.5 本地缓存策略

客户端本地缓存建议保持两层：

- 持久化层保存服务端原样密文
- 解密后内容只保留在内存，或使用单独受保护的本地密钥二次加密缓存

MVP 推荐：

- SQLite 先保存密文
- 当前会话已解密消息只放内存
- 本地搜索对 E2EE 私聊先禁用

不建议第一版就把解密明文继续原样写回 SQLite，否则端到端加密价值会被本地明文缓存削弱。

### 8.6 编辑 / 撤回 / 删除

这些能力继续走当前事件流：

- `message_edit`
- `message_recall`
- `message_delete`

但规则要调整：

- `message_edit` 的新内容应为新的密文载荷
- `message_recall` / `message_delete` 不依赖服务端读懂明文
- 已读仍按 `last_read_seq` 推进，与密文无冲突

### 8.7 多端与离线同步

MVP 建议先约束为：

- 一个用户一个主设备优先
- 支持离线同步密文
- 暂不承诺多设备间自动补发旧会话密钥

如果后续要支持多设备并行，需要补：

- 新设备建链
- 设备间 session key fanout
- 历史消息密钥恢复或重新封装

## 9. 附件 E2EE

附件不应直接上传明文。

推荐流程：

1. 客户端生成随机文件密钥 `file_key`
2. 使用 `AES-GCM` 在本地加密附件
3. 上传密文文件
4. 消息 `extra` 中发送附件元数据与被接收端公钥包装过的 `file_key`

建议附件 envelope：

- `storage_provider`
- `storage_key`
- `encrypted_size_bytes`
- `mime_type`
- `original_name`
- `checksum_sha256`
- `file_key_wrap`
- `file_nonce`
- `thumbnail_policy`

约束：

- 服务端 `files` 表保存的是密文文件元数据
- 服务端不保存 `local_path`
- 缩略图如果需要服务端生成，会破坏 E2EE；MVP 建议客户端本地生成

## 10. AI 会话策略

AI 会话默认不启用 E2EE。

原因：

- AI provider 需要看到明文
- 服务端可能需要做 prompt 编排、流式转发和审计

建议：

- 普通私聊：可启用 E2EE
- AI 会话：明确标记为 `encryption_mode=server_visible`

不要把这两类会话混成同一个默认策略。

## 11. 对现有代码的影响

### 11.1 客户端

预计影响模块：

- `ConnectionManager`：新增 call signaling 转发
- `MessageManager`：发送前加密、接收后解密
- `ChatService` / `SessionService`：新增设备、公钥、prekey 拉取接口
- `Database`：密文缓存、本地密钥状态
- `ChatInterface` / `ContactInterface`：从占位按钮接入通话流程

### 11.2 服务端

预计影响模块：

- `websocket/chat_ws.py`：新增 call signaling 入口
- `services/message_service.py`：兼容密文消息 envelope
- `services/auth_service.py`：后续可扩展设备注册时的认证
- 新增 `call_service.py`
- 新增设备密钥相关 repository / schema / API

## 12. 推荐分阶段交付

### Phase 1

- 生产环境强制 `https/wss`
- 新增 STUN / TURN 配置接口
- 客户端通话入口从占位改为真实 `CallManager`

### Phase 2

- 打通 `call_invite` 到 `call_hangup`
- 落地 1:1 语音通话
- 补通话状态 UI 和基础错误处理

### Phase 3

- 在语音通话稳定后扩展到 1:1 视频通话
- 支持摄像头开关、麦克风开关、设备切换

### Phase 4

- 落地私聊文本 E2EE
- 新增设备、公钥、prekey API
- 客户端发送前加密、接收后解密

### Phase 5

- 落地附件 E2EE
- 禁用 E2EE 私聊的本地全文搜索
- 补密钥轮换、设备失效、重装迁移策略

## 13. 推荐技术选型

### 13.1 信令与传输

- HTTP API：`HTTPS`
- 实时信令：`WSS`
- TLS 版本目标：优先 `TLS 1.3`

说明：

- 通话信令和普通聊天实时事件继续复用当前 WebSocket
- 登录、联系人、设备公钥、TURN 凭证仍通过 HTTP API

### 13.2 消息 E2EE

- 推荐协议方向：`Double Ratchet`
- 推荐实现策略：优先使用成熟协议库，不手写棘轮算法
- 对称加密：`AES-256-GCM`
- 身份 / 会话交换：`X25519`

说明：

- `Double Ratchet` 只推荐先用于 `1:1 private` 会话
- 群聊不建议在本阶段复用同一套 1:1 棘轮设计

### 13.3 媒体链路

- 媒体传输：`WebRTC`
- 媒体加密：`DTLS-SRTP`
- 穿透：`STUN`
- 中继：`TURN`

说明：

- 媒体不走 WebSocket
- TURN 服务建议使用短时凭证，不给客户端下发长期静态密码

### 13.4 本地存储保护

- 当前本地缓存：`SQLite`
- 推荐后续演进：`SQLite + SQLCipher`
- 数据库密钥保护：优先复用系统安全存储，例如 Windows DPAPI

说明：

- `SQLCipher` 保护的是落盘数据库，不替代端到端加密
- 即便后续接入 `SQLCipher`，也不建议把 E2EE 明文长期写回本地库

## 14. 字段与协议改动清单

### 14.1 WebSocket 新增事件

建议新增以下 `type`：

- `call_invite`
- `call_ringing`
- `call_accept`
- `call_reject`
- `call_hangup`
- `call_offer`
- `call_answer`
- `call_ice`
- `call_busy`

建议统一错误事件复用现有 `error`，不再为通话新增第二套错误包格式。

### 14.2 WebSocket `data` 字段建议

`call_invite`：

- `call_id`
- `session_id`
- `initiator_user_id`
- `target_user_id`
- `media_type`
- `created_at`

`call_accept` / `call_reject` / `call_hangup` / `call_busy`：

- `call_id`
- `session_id`
- `actor_user_id`
- `reason`

`call_offer` / `call_answer`：

- `call_id`
- `session_id`
- `actor_user_id`
- `sdp`

`call_ice`：

- `call_id`
- `session_id`
- `actor_user_id`
- `candidate`
- `sdp_mid`
- `sdp_mline_index`

### 14.3 HTTP API 新增建议

建议新增：

- `POST /api/v1/devices/register`
- `GET /api/v1/devices`
- `DELETE /api/v1/devices/{device_id}`
- `GET /api/v1/keys/prekey-bundle/{user_id}`
- `POST /api/v1/keys/prekeys/claim`
- `GET /api/v1/calls/ice-servers`

说明：

- `devices/register` 用于桌面端首次生成并注册设备公钥
- `prekey-bundle` 用于建立 1:1 E2EE 会话
- `ice-servers` 返回 STUN / TURN 列表与短时凭证

### 14.4 消息 schema 改动建议

当前消息 schema 仍是：

- `content: str`
- `message_type: str`
- `extra: dict`

为了兼容现有链路，MVP 建议不改外层字段名，只在 `extra` 中新增：

- `encryption`
- `ciphertext_preview`
- `attachment_encryption`
- `client_flags`

`extra.encryption` 至少包含：

- `enabled`
- `scheme`
- `sender_device_id`
- `recipient_device_id`
- `nonce`
- `aad`
- `ciphertext_version`

`extra.attachment_encryption` 至少包含：

- `file_key_wrap`
- `file_nonce`
- `encrypted_size_bytes`

`extra.client_flags` 可用于客户端本地语义：

- `searchable`
- `decrypted_in_memory`

约束：

- 服务端不得依赖 `ciphertext_preview` 做权限判断
- `ciphertext_preview` 仅用于占位 UI 或本地回退，不应被视为权威明文

### 14.5 Session extra 改动建议

建议在 session 额外字段里加入：

- `encryption_mode`
- `call_capabilities`
- `call_state`

其中：

- `encryption_mode`：`plain` / `e2ee_private` / `server_visible_ai`
- `call_capabilities`：例如 `{"voice": true, "video": true}`
- `call_state`：仅客户端运行时可维护，不要求服务端持久化

## 15. 数据库改动清单

### 15.1 服务端新增表

建议新增：

- `user_devices`
- `user_prekeys`
- `user_signed_prekeys`

可选新增：

- `call_logs`
- `call_participants`

### 15.2 服务端 `messages` 表

MVP 建议保持当前结构不变：

- `content`
- `extra_json`

但语义变为：

- `content`：在 E2EE 私聊中存密文 base64
- `extra_json`：存加密 envelope 与附件元数据

这样可以避免第一版就做高风险迁移。

### 15.3 客户端本地库

建议新增 app state / 表字段：

- `device_id`
- `identity_key_encrypted`
- `signing_key_encrypted`
- `db_encryption_mode`

建议新增会话密钥缓存表：

- `session_crypto_state`

建议新增字段：

- `messages.is_encrypted`
- `messages.encryption_scheme`

说明：

- 如果第一版不改消息表结构，也可以先把这些状态塞入 `extra`
- 从长期维护看，后续拆成明确列更稳

### 15.4 SQLCipher 接入注意项

- 当前客户端使用 `aiosqlite`
- 当前本地消息搜索依赖 `FTS5`
- 接入 `SQLCipher` 时要验证：
  - Python 驱动兼容性
  - Windows 打包
  - FTS 能否保留
  - 现有数据库迁移策略

建议：

- 不要把 `SQLCipher` 作为 Phase 1 前置条件
- 在 E2EE 私聊稳定后再推进本地库加密

## 16. 实施路线图

### Step A. 传输安全收口

- 客户端配置增加生产模式强制 `https/wss`
- 服务端部署文档明确 TLS 终止位置
- 验证 WebSocket 在 `wss` 下连接、重连、refresh 都正常

完成标准：

- 生产部署不再允许纯 `http/ws`

### Step B. 通话骨架

- 新增 `CallManager`
- 新增 `CallService`
- 新增通话 WS payload model
- 聊天页和联系人页按钮接入真实 manager，而不是 placeholder

完成标准：

- 能发起来电、接听、拒绝、挂断
- 通话状态能在双端同步

### Step C. 语音通话

- 接入 WebRTC 音频轨
- 打通 STUN / TURN
- 处理麦克风权限、占线、断线和重连结束

完成标准：

- 两端在典型 NAT 环境下能稳定通话

### Step D. 视频通话

- 接入摄像头轨道
- 补本地预览、远端视频渲染
- 支持静音、关摄像头、切换设备

完成标准：

- 语音和视频状态切换不破坏现有通话状态机

### Step E. 设备密钥基础设施

- 客户端生成设备身份密钥
- 服务端存储设备公钥与 prekey
- 登录后设备注册与轮换生效

完成标准：

- 新设备能获取对端 prekey bundle

### Step F. 私聊文本 E2EE

- `MessageManager` 发送前加密
- 接收消息后按设备状态解密
- UI 对 E2EE 会话调整预览、失败态和不可搜索提示

完成标准：

- 服务端与数据库中看不到私聊明文正文
- 双端可以正常收发、编辑、撤回、已读

### Step G. 附件 E2EE

- 客户端先加密文件再上传
- 消息附件元数据携带加密 envelope
- 本地预览和下载后解密打通

完成标准：

- 服务端只持久化密文文件和密文元数据

### Step H. 本地数据库加固

- 验证 `SQLCipher` 技术可行性
- 设计从现有 SQLite 到加密库的迁移
- 使用 DPAPI 保护 DB key

完成标准：

- 直接复制本地 `.db` 文件无法明文读取

## 17. 风险与取舍

### 17.1 E2EE 与搜索

- 当前本地搜索依赖明文 FTS
- E2EE 私聊如果只存密文，本地全文搜索需要降级或重做

建议：

- MVP 先禁用 E2EE 私聊搜索

### 17.2 E2EE 与 AI

- AI provider 需要明文

建议：

- AI 会话明确保持 `server_visible`

### 17.3 E2EE 与多端

- 多端同步会显著放大密钥分发复杂度

建议：

- MVP 先做单主设备优先

### 17.4 WebRTC 与桌面打包

- Python WebRTC 依赖、摄像头兼容、Windows 打包可能成为工程风险

建议：

- 先做最小 1:1 语音验证，再扩视频

## 18. 明确不建议的做法

- 不要在 WebSocket 上直接传输音视频帧
- 不要自定义一套非标准对称加密协议
- 不要把 E2EE 明文继续长期写回本地 SQLite
- 不要第一版同时做群聊 E2EE 和群通话
- 不要让 AI 会话默认继承普通私聊的 E2EE 策略
- 不要为了兼容旧接口，把明文和密文长期双写成两套真相

## 19. 下一步

建议下一步先落文档与协议细化，而不是直接写 UI。

优先顺序：

1. 为通话 signaling 补 ADR 与协议字段
2. 为 E2EE 设备模型补后端 schema 设计
3. 先实现 `CallManager + call_service + WS signaling`
4. 语音通话跑通后，再开始私聊文本 E2EE
