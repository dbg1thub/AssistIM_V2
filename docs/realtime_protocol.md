# 实时协议说明

## 1. 文档定位

本文档只定义聊天 WebSocket 的正式协议 contract，包括：

- 统一外层结构
- 当前稳定事件类型
- 通话 signaling payload
- 私聊 E2EE envelope
- 错误包与协议变更规则

架构边界、一致性模型和 E2EE / 通话设计取舍分别以以下文档为准：

1. [design_decisions.md](./design_decisions.md)
2. [architecture.md](./architecture.md)
3. [backend_architecture.md](./backend_architecture.md)
4. 本文档

## 2. 统一外层结构

所有聊天 WebSocket 消息统一使用：

```json
{
  "type": "message_type",
  "seq": 0,
  "msg_id": "uuid-or-empty",
  "timestamp": 0,
  "data": {}
}
```

字段约束：

- `type`：消息类型
- `seq`：服务端顺序字段；状态事件可表达 `event_seq`，普通聊天消息不以外层 `seq` 作为会话内顺序
- `msg_id`：客户端命令幂等键；对会改变状态的命令必须存在
- `timestamp`：发送时间；不作为正式补偿依据
- `data`：业务负载

## 3. 当前稳定事件类型

### 3.1 连接与保活

事件：

- 客户端发送：`auth`
- 服务端返回：`auth_ack`、`error`、`force_logout`

桌面端保活使用 WebSocket transport ping frame，不使用应用层 `ping` / `heartbeat` / `pong` JSON 包。

`auth`：

```json
{
  "type": "auth",
  "msg_id": "ws-auth-1",
  "data": {
    "token": "ACCESS_TOKEN"
  }
}
```

`auth_ack`：

```json
{
  "type": "auth_ack",
  "data": {
    "success": true,
    "user_id": "user_x"
  }
}
```

`force_logout.data.reason` 当前枚举：

- `session_replaced`
- `logout`

客户端收到 `force_logout` 后必须进入 auth-loss teardown / re-auth 流程，不进入 `history_events` 补偿模型。

### 3.2 轻量实时状态

当前稳定广播事件：

- `typing`
- `contact_refresh`
- `user_profile_update`
- `group_profile_update`
- `group_self_profile_update`

约束：

- `contact_refresh` 是联系人域刷新提示，不写入 `history_events`
- `user_profile_update` 使用 `profile_event_id` 做实时幂等标识
- `group_profile_update` 与 `group_self_profile_update` 属于 `event_seq` / `history_events` 语义

### 3.3 消息同步

事件：

- 客户端发送：`sync_messages`
- 服务端返回：`history_messages`、`history_events`

`sync_messages`：

```json
{
  "type": "sync_messages",
  "msg_id": "sync-1",
  "data": {
    "session_cursors": {
      "session_id": 12
    },
    "event_cursors": {
      "session_id": 5
    }
  }
}
```

约束：

- `history_messages` 只补新消息
- `history_events` 只补状态事件
- `session_cursors` 与 `event_cursors` 不可混用

### 3.4 聊天消息与状态事件

聊天消息相关事件：

- 客户端发送：`chat_message`
- 服务端返回 / 广播：`message_ack`、`chat_message`、`message_delivered`

`chat_message.data`：

```json
{
  "session_id": "session_x",
  "content": "hello",
  "message_type": "text",
  "extra": {}
}
```

状态事件：

- 客户端发送：`message_recall`、`message_edit`、`message_delete`
- 服务端广播：`read`、`message_recall`、`message_edit`、`message_delete`

约束：

- `msg_id` 作为逻辑消息 ID；重发必须复用同一个 `msg_id`
- `message_ack` 只表示服务端已提交消息并返回权威消息对象
- 发送失败统一返回同 `msg_id` 的 `error`
- `read` 的持久化正式入口是 HTTP `/messages/read/batch`；聊天 WebSocket 不接受 `read_ack/read` 命令
- 广播进入 `event_seq` 模型的事件时，外层 `seq` 与 `data.event_seq` 保持一致

## 4. 稳定消息对象

聊天消息与 ACK 中返回的权威对象至少包含以下稳定核心字段：

- `message_id`
- `session_id`
- `sender_id`
- `content`
- `message_type`
- `status`
- `created_at`
- `updated_at`
- `session_type`
- `session_name`
- `session_avatar`
- `participant_ids`
- `is_ai_session`
- `session_seq`
- `read_count`
- `read_target_count`
- `read_by_user_ids`
- `is_read_by_me`
- `extra`

约束：

- 会话内排序使用 `session_seq`
- `content` 在普通会话中是明文，在 E2EE 私聊中允许变为密文
- `extra` 是扩展字段容器，不替代外层协议职责

## 5. 1:1 通话 signaling

新增 `type`：

- `call_invite`
- `call_ringing`
- `call_accept`
- `call_reject`
- `call_hangup`
- `call_offer`
- `call_answer`
- `call_ice`
- `call_busy`

共同字段：

- `call_id`
- `session_id`
- `initiator_id`
- `recipient_id`

事件附加字段：

- `call_invite`
  - `media_type`
  - `created_at`
  - 客户端发送时可附带 `target_user_id`
- `call_ringing` / `call_accept` / `call_reject` / `call_hangup` / `call_busy`
  - `actor_id`
  - `reason`（仅需要时返回）
- `call_offer` / `call_answer`
  - `actor_id`
  - `sdp`
- `call_ice`
  - `actor_id`
  - `candidate`
  - `sdp_mid`
  - `sdp_mline_index`

`call_invite.data`：

```json
{
  "call_id": "call_x",
  "session_id": "session_x",
  "initiator_id": "user_a",
  "recipient_id": "user_b",
  "media_type": "voice",
  "created_at": "2026-04-05T12:00:00Z"
}
```

约束：

- 通话 signaling 不进入 `session_seq` / `event_seq` 补偿模型
- `session_id` 必须是 `private` 会话
- 错误继续复用统一 `error` 结构

## 6. 私聊 E2EE 消息 envelope

适用范围：

- 仅 `private` 会话

外层兼容规则：

- E2EE 不修改外层 WebSocket 结构
- `msg_id`、`session_seq`、`event_seq` 规则保持不变
- 只改变 `content`、`extra.encryption`、`extra.attachment_encryption`

文本消息：

```json
{
  "session_id": "session_x",
  "content": "BASE64_CIPHERTEXT",
  "message_type": "text",
  "extra": {
    "encryption": {
      "enabled": true,
      "scheme": "double-ratchet-v1",
      "sender_device_id": "dev_a",
      "recipient_device_id": "dev_b",
      "nonce": "BASE64_NONCE",
      "aad": "BASE64_AAD",
      "ciphertext_version": 1
    }
  }
}
```

附件消息新增：

- `extra.attachment_encryption.scheme`
- `extra.attachment_encryption.file_key_wrap`
- `extra.attachment_encryption.file_nonce`
- `extra.attachment_encryption.encrypted_size_bytes`

约束：

- 服务端不依赖解密正文执行业务规则
- 服务端保存密文文件和密文附件元数据
- 服务端不保存 `local_path`
- 若缩略图依赖明文，MVP 阶段应由客户端本地生成

## 7. 错误包

实时错误统一复用：

```json
{
  "type": "error",
  "msg_id": "original-msg-id",
  "data": {
    "message": "human-readable message",
    "code": 40101
  }
}
```

约束：

- `error` 不强制断开连接
- 失败命令优先回原始 `msg_id`
- 通话与 E2EE 相关实时错误不另起第二套错误包格式

## 8. 协议变更规则

新增字段或事件时，必须同步更新：

- [architecture.md](./architecture.md)
- [backend_architecture.md](./backend_architecture.md)
- [design_decisions.md](./design_decisions.md)
- 对应测试

不允许通过“临时兼容字段”长期双写两套真相。
