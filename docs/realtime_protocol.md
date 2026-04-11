# 实时协议说明

## 1. 适用范围

本文档描述 AssistIM 当前聊天 WebSocket 协议，以及下一阶段要补充的：

- 1:1 通话 signaling
- 私聊 E2EE 消息 envelope

如果协议字段与其他文档冲突，优先级如下：

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
- `seq`：事件顺序号；普通聊天消息不以外层 `seq` 作为会话内顺序
- `msg_id`：客户端命令幂等键；对会改变状态的命令必须存在
- `timestamp`：发送时间；不作为正式补偿依据
- `data`：业务负载

## 3. 当前已存在的事件

### 3.1 连接与保活

客户端发送：

- `auth`
- `ping`
- `heartbeat`

服务端返回：

- `auth_ack`
- `pong`
- `error`

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

### 3.2 在线状态

服务端广播：

- `online`
- `offline`
- `presence`
- `typing`

### 3.3 消息同步

客户端发送：

- `sync_messages`

服务端返回：

- `history_messages`
- `history_events`

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

### 3.4 聊天消息

客户端发送：

- `chat_message`

服务端返回 / 广播：

- `message_ack`
- `chat_message`
- `message_delivered`

当前 `chat_message.data` 结构：

```json
{
  "session_id": "session_x",
  "content": "hello",
  "message_type": "text",
  "extra": {}
}
```

约束：

- `msg_id` 作为逻辑消息 ID
- 重发必须复用同一个 `msg_id`
- 服务端 ACK 中返回权威消息对象

`message_ack.data`：

```json
{
  "msg_id": "client-msg-id",
  "success": true,
  "message": {}
}
```

### 3.5 状态事件

客户端发送：

- `read_ack` / `read`
- `message_recall`
- `message_edit`
- `message_delete`

服务端广播：

- `read`
- `message_recall`
- `message_edit`
- `message_delete`

约束：

- 这些事件属于 `event_seq` 语义
- 服务端广播时外层 `seq` 与 `data.event_seq` 保持一致

## 4. 权威消息对象

当前聊天消息与 ACK 中的权威对象至少包含：

- `message_id`
- `session_id`
- `sender_id`
- `content`
- `message_type`
- `status`
- `timestamp`
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
- `extra` 作为扩展字段容器，但不能替代正式的外层协议职责

## 5. 新增通话 signaling

### 5.1 事件列表

新增以下 `type`：

- `call_invite`
- `call_ringing`
- `call_accept`
- `call_reject`
- `call_hangup`
- `call_offer`
- `call_answer`
- `call_ice`
- `call_busy`

### 5.2 共同字段

服务端下发的通话相关 `data` 统一至少包含：

- `call_id`
- `session_id`
- `initiator_id`
- `recipient_id`

其中：

- `call_id`：一次通话的稳定 ID
- `session_id`：必须是 `private` 会话
- 客户端发起 `call_invite` 时仍可附带 `target_user_id` 作为目标用户提示

### 5.3 邀请与状态类事件

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

`call_ringing` / `call_accept` / `call_reject` / `call_hangup` / `call_busy.data`：

```json
{
  "call_id": "call_x",
  "session_id": "session_x",
  "initiator_id": "user_a",
  "recipient_id": "user_b",
  "actor_id": "user_b",
  "reason": "busy"
}
```

说明：

- `reason` 仅在需要时返回，例如 `busy`、`declined`、`cancelled`
- 这些事件不进入 `session_seq` / `event_seq` 补偿模型

### 5.4 SDP 类事件

`call_offer.data`：

```json
{
  "call_id": "call_x",
  "session_id": "session_x",
  "initiator_id": "user_a",
  "recipient_id": "user_b",
  "actor_id": "user_a",
  "sdp": "v=0..."
}
```

`call_answer.data`：

```json
{
  "call_id": "call_x",
  "session_id": "session_x",
  "initiator_id": "user_a",
  "recipient_id": "user_b",
  "actor_id": "user_b",
  "sdp": "v=0..."
}
```

### 5.5 ICE 类事件

`call_ice.data`：

```json
{
  "call_id": "call_x",
  "session_id": "session_x",
  "initiator_id": "user_a",
  "recipient_id": "user_b",
  "actor_id": "user_a",
  "candidate": "candidate:...",
  "sdp_mid": "0",
  "sdp_mline_index": 0
}
```

## 6. 私聊 E2EE 消息 envelope

### 6.1 外层兼容原则

E2EE 私聊不修改外层 WebSocket 结构，也不修改：

- `msg_id`
- `session_seq`
- `event_seq`

MVP 只改变：

- `content`
- `extra.encryption`
- `extra.attachment_encryption`

### 6.2 文本消息

E2EE 私聊中的 `chat_message.data` 仍为：

```json
{
  "session_id": "session_x",
  "content": "BASE64_CIPHERTEXT",
  "message_type": "text",
  "extra": {
    "encryption": {}
  }
}
```

`extra.encryption`：

```json
{
  "enabled": true,
  "scheme": "double-ratchet-v1",
  "sender_device_id": "dev_a",
  "recipient_device_id": "dev_b",
  "nonce": "BASE64_NONCE",
  "aad": "BASE64_AAD",
  "ciphertext_version": 1
}
```

约束：

- `content` 为密文 base64
- 服务端不依赖解密正文执行业务规则
- 服务端不基于密文内容做预览、搜索或 AI 总结

### 6.3 附件消息

附件消息继续使用当前：

- `message_type`
- `content`
- `extra.media`

但 E2EE 私聊中新增：

- `extra.attachment_encryption`

`extra.attachment_encryption`：

```json
{
  "scheme": "aes-gcm-file-v1",
  "file_key_wrap": "BASE64_WRAPPED_KEY",
  "file_nonce": "BASE64_NONCE",
  "encrypted_size_bytes": 123456
}
```

约束：

- 服务端保存密文文件和密文附件元数据
- 服务端不保存 `local_path`
- 如果缩略图依赖明文，MVP 阶段应由客户端本地生成

## 7. 错误返回

实时协议中的错误统一复用：

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
- 通话 signaling 错误继续复用同一 `error` 结构

## 8. 命名与兼容规则

- 新增字段优先放到 `data` 或 `extra` 的清晰命名空间中
- 不通过“临时兼容字段”长期双写两套真相
- 如果字段进入正式协议，必须同步更新：
  - [architecture.md](./architecture.md)
  - [backend_architecture.md](./backend_architecture.md)
  - [design_decisions.md](./design_decisions.md)
  - 测试用例

## 9. 下一步

后续实现时，建议优先保证以下顺序：

1. 先补 `call_*` payload model 与 WS handler
2. 再补 `ice-servers` HTTP 接口
3. 然后实现 `CallManager`
4. 最后再引入 E2EE 的设备、公钥与 prekey API
