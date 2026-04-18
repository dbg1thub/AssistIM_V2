# AI 功能详细设计文档

## 1. 文档目标

本文档定义 AssistIM 当前阶段 AI 功能的落地方案，范围包括本地模型接入、输入辅助、私聊推荐回复、AI 会话、隐私边界、数据模型、错误处理和测试要求。

本文档以当前 Python / PySide6 / FastAPI 项目为准，不再使用前端工程目录示例作为设计基线。已有架构约束参考：

- [architecture.md](../architecture/architecture.md)
- [design_decisions.md](../architecture/design_decisions.md)
- [ai_rules.md](../engineering/ai_rules.md)

## 2. 当前项目基线

当前项目已经具备 AI 功能的部分基础，不应另起一套平行架构。

客户端基础：

- 客户端分层为 `UI -> Controller -> Manager -> Service -> Network / Storage`。
- UI 基于 PySide6 / QFluentWidgets，业务状态应由 Manager 维护。
- Manager 通过公开 Storage API 读写数据库，不直接在 UI 中写 SQL。
- 实时消息、会话同步、本地缓存和 EventBus 已经存在。

已有 AI 相关代码：

- `client/services/ai_service.py` 已有 `AIService`、`AIProvider`、`OpenAIProvider`、`OllamaProvider`、`HTTPProvider`。
- `AIProviderType.LOCAL` 已存在枚举，但本地 GGUF Provider 尚未落地。
- `client/models/message.py` 已有 `Session.is_ai_session`、`AISession`、`encryption_mode="server_visible_ai"` 等 AI 会话字段。
- `client/managers/session_manager.py` 已有 AI session 创建和 session 展示相关逻辑。
- `client/ui/widgets/message_input.py` 已有 AI 按钮入口，但功能链路仍需补齐。
- 服务端已支持 AI session 相关字段，AI 会话不需要重新设计一套完全独立协议。

设计结论：

- 首期应扩展现有 `AIService` / `AIProvider`，而不是新建另一套 Provider 系统。
- 首期应复用现有 `Session` / `ChatMessage`，而不是引入独立 `ai_sessions` / `ai_messages` 主表。
- AI 会话类型以当前代码的 `session_type="ai"`、`is_ai_session=True` 为准，不引入新的自定义 session type。
- `server_visible_ai` 是 AI 会话的数据可见性标识，不代表普通私聊或 E2EE 会话可以被 AI 自动读取。

## 3. 设计原则

AI 功能必须遵守以下边界：

- UI 只负责展示和触发用户动作，不直接持有 Provider、模型进程或 Prompt 逻辑。
- Controller 只做输入归一化和动作分发，不维护业务真相。
- Manager 维护任务状态、会话状态、候选建议状态和失败恢复。
- Service 提供稳定 AI 能力接口，Provider 封装不同模型后端。
- Provider / Runtime 不直接推 UI，所有状态变化通过 Manager 汇总后通知 UI。
- 流式输出必须批量合并或节流刷新，不能每个 token 触发一次重绘。
- 外部 AI Provider 不得复用 AssistIM 的业务 Bearer Token，不得触发业务 token refresh。
- E2EE 私聊明文只有在用户明确授权且策略允许时才能进入 AI 上下文。
- 日志不得输出完整 Prompt、聊天明文、密钥、附件明文路径或 Provider Token。
- 异常处理必须给出明确错误码和状态收敛，不允许用宽泛 `try/except` 静默吞错。

## 4. 首期范围

首期目标不是做完整 Agent，也不是一次性接入多模型路由，而是先把本地 AI 基础链路做稳。

MVP 范围：

- 接入本地 GGUF Provider。
- 支持手动 AI 输入辅助，例如改写、润色、翻译、总结选中文本。
- 支持私聊推荐回复，结果只作为候选草稿，不自动发送。
- 支持基础 AI 会话，复用现有会话和消息模型。
- 支持生成取消、失败提示、运行时状态展示和最小可观测日志。

暂不纳入 MVP：

- AI 自动读取所有聊天内容。
- AI 自动替用户发送消息。
- 群聊自动 AI 参与。
- 复杂 Agent / Action System。
- RAG、本地知识库、多模态推理、多模型自动路由。
- 多模型尺寸路由策略。

## 5. 推荐落地顺序

推荐按以下顺序拆分开发，避免先做 UI 壳后发现模型链路不可用。

1. 扩展 `client/services/ai_service.py`，补齐 `LocalGGUFProvider` 的接口和假实现测试。
2. 新增本地 GGUF runtime 适配层，封装模型加载、生成、取消和健康检查。
3. 新增 `AITaskManager`，统一管理 AI 任务状态、取消、失败和节流输出。
4. 打通手动输入辅助，先从选中文本改写或推荐回复开始。
5. 打通私聊推荐回复 UI，候选只插入输入框，不写入消息流。
6. 打通 AI 会话，复用现有 session/message 存储和展示能力。
7. 增加崩溃恢复、日志指标和回归测试。

## 6. 模块设计

推荐模块关系：

```text
UI
  -> AIController
      -> AITaskManager
      -> AIAssistManager
      -> AIConversationManager
          -> AIService
              -> AIProvider
                  -> LocalGGUFProvider
                      -> LocalGGUFRuntime
```

### 6.1 AIController

建议新增 `client/ui/controllers/ai_controller.py`。

职责：

- 接收 UI 触发的 AI 动作。
- 校验空输入、当前会话、选中文本、用户确认状态。
- 调用对应 Manager。
- 将错误码转换为 UI 可展示文案 key。

不负责：

- 拼 Prompt。
- 持有模型进程。
- 维护流式 token。
- 直接写数据库。

### 6.2 AITaskManager

建议新增 `client/managers/ai_task_manager.py`。

职责：

- 管理 `queued`、`running`、`cancelling`、`done`、`failed`、`cancelled` 状态。
- 控制本地模型并发，首期默认并发数为 1。
- 聚合流式输出，按时间或字符数节流通知 UI。
- 处理用户取消、runtime 崩溃、超时和可恢复失败。
- 输出 `[ai-diag]` 日志，日志只包含任务元信息。

### 6.3 AIAssistManager

建议新增 `client/managers/ai_assist_manager.py`。

职责：

- 管理私聊推荐回复、输入框改写、选中文本总结等轻量 AI 辅助状态。
- 决定推荐回复是否可触发。
- 保存候选建议的内存态和失效条件。
- 将候选插入输入框，而不是直接发送消息。

### 6.4 AIConversationManager

建议新增或扩展当前会话管理逻辑，专门处理 AI 会话。

职责：

- 创建 `session_type="ai"`、`is_ai_session=True` 的会话。
- 为用户输入和 AI 回复创建统一 `ChatMessage`。
- 将流式 AI 回复写入同一条占位消息的 `extra["ai"]` 状态。
- 应用重启时收敛未完成 AI 消息。

### 6.5 AIService

应扩展现有 `client/services/ai_service.py`，而不是新建同名能力。

推荐接口形态：

```python
class AIService:
    async def generate_once(self, request: AIRequest) -> AIResult: ...
    async def stream_chat(self, request: AIRequest) -> AsyncIterator[AIStreamEvent]: ...
    async def suggest_replies(self, request: AIReplySuggestionRequest) -> AIReplySuggestionResult: ...
    async def cancel(self, task_id: str) -> None: ...
    async def get_model_info(self) -> AIModelInfo: ...
```

`AIRequest` 需要包含隐私路由约束：

```json
{
  "task_id": "uuid",
  "task_type": "reply_suggestion",
  "session_id": "uuid",
  "must_be_local": true,
  "privacy_scope": "e2ee_plaintext",
  "max_output_chars": 2000
}
```

约束：

- `must_be_local=True` 时只能使用本地 Provider。
- 如果本地模型不可用，任务必须失败，不能自动降级到远端 Provider。
- E2EE 会话触发的推荐回复、总结和改写默认必须设置 `must_be_local=True`。
- `max_output_chars` 是 Manager 层硬上限，不能只依赖模型参数。

### 6.6 LocalGGUFProvider

`LocalGGUFProvider` 是本地模型 Provider，负责把统一 AI 请求转换为本地 runtime 调用。

职责：

- 检查模型文件存在性和配置。
- 构造 runtime 参数。
- 接收 runtime 的流式输出。
- 将 runtime 错误转换为统一 AI 错误码。

不负责：

- UI 展示。
- 会话写库。
- 推荐回复触发策略。

### 6.7 LocalGGUFRuntime

Runtime 层封装具体推理方式。实现可以是 llama.cpp subprocess、Ollama 本地服务、llamafile 或后续其他 GGUF 引擎，但上层不应感知细节。

职责：

- 模型加载和释放。
- 单次生成和流式生成。
- 中断当前生成。
- 健康检查。
- runtime 崩溃检测。

## 7. 本地 GGUF 运行时

当前项目出现了 `qwen3.5-omni-2B-Q4_K_M.gguf` 模型文件，首期可将其作为默认候选模型，但必须通过配置加载，不应在代码中硬编码绝对路径。

配置建议：

```json
{
  "provider": "local_gguf",
  "model_path": "client/resources/models/qwen3.5-omni-2B-Q4_K_M.gguf",
  "context_size": 4096,
  "max_output_tokens": 512,
  "temperature": 0.4,
  "concurrency": 1,
  "gpu_layers": "auto",
  "vram_budget_mb": null,
  "idle_unload_seconds": 300
}
```

运行时状态：

- `unloaded`
- `loading`
- `ready`
- `busy`
- `cancelling`
- `error`
- `releasing`

首期约束：

- 默认单并发，避免桌面端资源争抢。
- 模型加载不能阻塞 UI 线程。
- 首 token 延迟、总耗时、取消耗时需要记录。
- runtime 崩溃后，所有运行中任务必须收敛为失败态。
- 取消必须尽量中断底层生成，而不是只隐藏 UI。

### 7.1 资源保护

本地模型运行必须把资源保护作为 Provider / Runtime 的基础能力。

显存与内存策略：

- Runtime 启动前检查模型文件大小、可用内存和可选 GPU 信息。
- 如果 GPU 初始化失败或显存预算不足，允许回退到 CPU 推理，但必须在任务状态中标记 `cpu_fallback=True`。
- CPU 回退可能明显变慢，UI 需要显示“本地模型低速运行”一类状态，避免用户误以为卡死。
- 如果用户配置为禁止 CPU 回退，则直接返回 `AI_RESOURCE_EXHAUSTED`。

KV Cache 策略：

- 推荐回复、改写、翻译等短任务结束后立即释放上下文缓存。
- AI 会话可复用短期上下文，但必须设置最大上下文长度和空闲过期时间。
- 当高优先级任务需要资源时，低优先级短任务缓存应优先释放。

模型卸载策略：

- 默认空闲 5 分钟后卸载模型。
- 正在生成、正在取消、正在上传诊断状态时不能卸载。
- 卸载前需要确认没有运行中的 AI task。
- 卸载后保留模型配置和健康状态，下次任务重新加载。

输出保护：

- Provider 层使用 `max_output_tokens` 限制生成。
- Manager 层再增加硬性字符数上限，防止模型重复输出导致 UI 卡死。
- 触发硬截断时，任务状态标记为 `AI_OUTPUT_TRUNCATED`，UI 显示“输出已截断”。

### 7.2 模型分发与版本

模型文件不应默认打进主程序二进制。推荐作为独立资源包或首次使用时下载。

模型清单建议：

```json
{
  "model_id": "qwen3.5-omni-2b-q4",
  "version": "1.0.0",
  "file_name": "qwen3.5-omni-2B-Q4_K_M.gguf",
  "size_bytes": 0,
  "sha256": "...",
  "runtime": "local_gguf",
  "default": true
}
```

分发要求：

- 下载必须支持断点续传或失败后重新校验。
- 下载完成后必须校验 `sha256`，校验失败不能加载。
- 模型清单需要可信来源，后续如果远程下发必须考虑签名校验。
- 允许多个模型版本并存，但同一时间只能有一个 active model。
- 远程配置只能选择 `client/resources/models/` 下已安装且校验通过的模型，不能下发任意本地路径。
- 正在运行 AI 任务时不能热切换模型，只能在任务结束后切换。

打包策略：

- Nuitka 或其他桌面打包工具只负责主程序。
- GGUF 模型作为外挂资源包或首次启动后的独立下载内容。
- 如果提供离线安装包，模型资源包也应独立校验，避免主程序更新和模型更新强绑定。

## 8. 数据模型与存储

### 8.1 会话模型

AI 会话复用现有 `Session`。

推荐字段：

```json
{
  "session_type": "ai",
  "is_ai_session": true,
  "encryption_mode": "server_visible_ai",
  "extra": {
    "ai": {
      "provider": "local_gguf",
      "model": "qwen3.5-omni-2B-Q4_K_M",
      "version": 1
    }
  }
}
```

注意：

- `server_visible_ai` 只用于 AI 会话，不应改变普通私聊的 E2EE 策略。
- 如果未来做纯本地 AI 会话，需要新增明确的 `local_only_ai` 标识和同步规则。
- 不建议同时维护一套 `ai_sessions` 主表，除非产品明确要求 AI 会话完全脱离 IM 同步。

### 8.2 消息模型

AI 消息复用现有 `ChatMessage`。

推荐扩展：

```json
{
  "is_ai": true,
  "extra": {
    "ai": {
      "task_id": "uuid",
      "provider": "local_gguf",
      "model": "qwen3.5-omni-2B-Q4_K_M",
      "status": "streaming",
      "finish_reason": null,
      "partial": false
    }
  }
}
```

状态策略：

- 现有 `MessageStatus` 不应在没有迁移和测试的情况下随意扩展。
- `streaming`、`cancelled`、`partial` 等 AI 运行时状态首期放在 `message.extra["ai"]["status"]`。
- 如果后续要把这些状态升为正式 `MessageStatus`，需要数据库迁移、旧数据兼容和 UI 回归测试。

### 8.3 推荐回复模型

私聊推荐回复不是正式消息，不写入消息流。

推荐结构：

```json
{
  "session_id": "uuid",
  "anchor_message_id": "uuid",
  "status": "ready",
  "items": [
    {"id": "1", "text": "收到，我先看一下。"},
    {"id": "2", "text": "可以，你方便再补充一点细节吗？"},
    {"id": "3", "text": "好的，我晚点确认后回复你。"}
  ]
}
```

存储策略：

- 首期只保存在内存中，应用重启即消失。
- 不写入持久化数据库，避免无价值磁盘 IO 和隐私残留。
- 只在后续产品明确要求跨页面保留时，才考虑短期本地缓存。
- 不参与 unread、session preview、消息同步和搜索索引。

### 8.4 AI 生成元数据

AI 生成内容需要保留最小可追溯元数据，但不能记录完整 Prompt 明文。

推荐字段：

```json
{
  "extra": {
    "ai": {
      "task_id": "uuid",
      "provider": "local_gguf",
      "model": "qwen3.5-omni-2B-Q4_K_M",
      "model_version": "1.0.0",
      "prompt_hash": "sha256",
      "generation_hash": "sha256",
      "seed": null,
      "status": "done"
    }
  }
}
```

字段含义：

- `prompt_hash` 只用于诊断和溯源，不可反推出原文。
- `generation_hash` 基于输出文本、模型标识、模型版本和可选 seed 生成。
- 如果 runtime 不支持确定性 seed，`seed` 可以为空。

### 8.5 本地存储安全

AI 会话和普通消息一样属于用户数据。

存储要求：

- 如果本地数据库加密开启，AI 会话和 AI 消息必须同样进入加密数据库。
- 如果本地数据库加密关闭，AI 数据不得假装具备额外安全性，UI 或设置中应保持一致表述。
- AI 任务临时文件、下载中的模型包、runtime cache 不应长期留在系统临时目录。
- 推荐回复候选不持久化，重启后丢弃。

### 8.6 崩溃恢复

应用启动时需要收敛未完成 AI 状态：

- `running` / `cancelling` 任务转为 `failed_recoverable`。
- AI 占位消息如果有部分内容，标记为 `partial`。
- AI 占位消息如果没有内容，标记为 `failed` 或删除占位，具体取决于产品选择。
- 推荐回复生成中状态转为 `idle`，旧候选按 anchor 是否仍有效决定保留或清理。

## 9. 私聊推荐回复

### 9.1 启用范围

首期只支持：

- 1:1 私聊。
- 文本消息。
- 当前用户手动触发，或当前会话活跃时被动触发。
- 用户点击候选后插入输入框。

首期不支持：

- 群聊自动建议。
- 附件、语音、视频内容自动转文本后建议。
- 自动发送。
- 未授权读取 E2EE 明文并调用远端 AI。

### 9.2 触发条件

推荐回复可触发的条件：

- 当前 session 是 direct/private。
- 最新有效消息来自对方。
- 消息类型是文本。
- 用户没有正在输入大量草稿，或产品允许覆盖候选。
- 同一 anchor message 没有重复生成。
- 当前没有同会话 AI 任务在运行。
- 隐私策略允许当前 Provider 读取上下文。

### 9.3 上下文策略

推荐回复只需要短上下文。

推荐输入：

- 对方最近一条文本消息。
- 最近 4 到 8 条相关文本消息。
- 当前用户最近 1 到 3 条回复，用于语气参考。
- 当前语言和简短风格偏好。

禁止输入：

- 完整历史聊天记录。
- 密钥、token、内部调试日志。
- 未经用户授权的 E2EE 明文远端上传。

### 9.4 Prompt 策略

推荐回复 Prompt 应短、稳定、易解析。

示例：

```text
你是聊天输入辅助助手。根据最近对话，为当前用户生成 4 条中文回复建议。
风格要求：前 2 条积极推进，后 2 条保守婉拒，整体保持礼貌、克制。
每条建议单独一行，只输出建议文本。

最近对话：
{messages}
```

2B 模型首期不应强依赖严格 JSON 输出。建议优先使用“每行一条”的格式，然后做简单清洗和数量限制。

### 9.5 UI 交互

推荐回复展示在输入框附近。

行为：

- 点击候选后插入输入框。
- 插入后用户可以继续编辑。
- 用户发送消息后候选失效。
- 对方又发送新消息后旧候选失效。
- 用户切换会话后候选可隐藏，回到会话时根据 anchor 是否仍有效决定恢复。

## 10. AI 输入辅助

输入辅助通过现有 AI 按钮进入。

首期动作：

- 改写选中文本。
- 润色草稿。
- 缩短草稿。
- 翻译草稿。
- 根据当前私聊生成候选回复。

处理原则：

- AI 结果默认进入草稿或候选区。
- 不自动发送。
- 替换选中文本前应保留撤销路径。
- 空草稿、超长草稿、无选中文本要给出明确提示。

## 11. AI 会话

AI 会话是二阶段或 MVP 后半段能力，前提是本地 Provider 和任务管理已稳定。

实现原则：

- 使用 `session_type="ai"` 和 `is_ai_session=True`。
- 用户消息和 AI 回复复用 `ChatMessage`。
- AI 回复采用一条占位消息持续更新。
- 会话 preview 使用最后一条用户或 AI 正式内容。
- AI 会话不应影响普通 direct/group session 的 unread、删除、重建和 E2EE 行为。

如果产品决定做纯本地 AI 会话：

- 必须明确 `local_only_ai`。
- 不进入服务端 session/event/message 同步。
- 不与 `server_visible_ai` 混用。
- 需要单独说明多端不可见和数据备份限制。

## 12. 隐私与安全

E2EE 边界：

- E2EE 私聊明文默认不能发送给远端 AI。
- 本地 GGUF Provider 可在用户启用 AI 辅助后读取本地已解密内容。
- 如果要把 E2EE 内容发给远端 Provider，必须有显式确认和清晰文案。
- E2EE 会话发起 AI 请求时，`AIRequest.must_be_local` 默认必须为 `true`。
- 当 `must_be_local=true` 且本地模型不可用时，任务应返回 `AI_LOCAL_REQUIRED_UNAVAILABLE`，不能自动路由到远端 Provider。

普通聊天边界：

- 普通非 E2EE 会话仍应遵守最小上下文原则。
- 推荐回复不应默认读取完整历史。
- 会话总结必须由用户主动触发。

外部 Provider 边界：

- 不得携带 AssistIM 业务 Bearer Token。
- 不得复用业务 HTTPClient 的自动刷新 token 行为。
- Provider Token 单独配置、单独存储、单独脱敏日志。

日志边界：

- 记录 task_id、session_id、provider、model、耗时、错误码。
- 不记录完整 Prompt。
- 不记录完整消息明文。
- 不记录附件明文内容。
- 不记录密钥和 Provider Token。

输入与输出安全：

- Prompt 构造前可以做本地轻量规则检查，例如超长文本、明显密钥格式、内部日志片段。
- 规则检查不应变成静默篡改用户消息；如果需要移除内容，应明确标记为已脱敏或直接拒绝该 AI 任务。
- System Prompt 需要明确 AI 只能完成当前请求，不得创建递归任务、不得要求执行本地命令、不得声称已经发送消息或操作系统。
- 对模型输出做最终长度截断和基础清洗，避免重复循环输出拖垮 UI。
- 对推荐回复类输出，解析失败或内容不合格时只显示“暂无建议”，不把原始异常输出展示给用户。

## 13. 错误处理

统一错误码建议：

- `AI_MODEL_NOT_FOUND`
- `AI_MODEL_LOAD_FAILED`
- `AI_MODEL_UNAVAILABLE`
- `AI_RUNTIME_BUSY`
- `AI_CONTEXT_TOO_LONG`
- `AI_STREAM_INTERRUPTED`
- `AI_USER_CANCELLED`
- `AI_TIMEOUT`
- `AI_PROVIDER_UNAVAILABLE`
- `AI_OUTPUT_INVALID`
- `AI_PRIVACY_DENIED`
- `AI_LOCAL_REQUIRED_UNAVAILABLE`
- `AI_RESOURCE_EXHAUSTED`
- `AI_OUTPUT_TRUNCATED`
- `AI_MODEL_DOWNLOAD_FAILED`
- `AI_MODEL_CHECKSUM_FAILED`

错误处理原则：

- 用户取消不是错误日志，应该记录为正常取消事件。
- 输入超长不可自动重试，应提示用户缩短上下文。
- 模型文件缺失不可自动重试，应提示配置模型路径。
- runtime 崩溃可以提供重新生成入口，但不能无限重试。
- 推荐回复解析失败可以降级为“暂无建议”，但日志必须有错误码。
- `must_be_local=True` 且本地 Provider 不可用时，只能失败提示，不能静默切远端。
- 输出被 Manager 硬截断时应保留已生成内容，并标记为截断状态。
- 模型包下载或校验失败不能加载，也不能修改 active model。
- 不允许为了隐藏错误而包一层宽泛 `except Exception` 后继续返回成功态。

## 14. 可观测性

日志统一使用 `[ai-diag]` 前缀。

推荐字段：

- `task_id`
- `session_id`
- `task_type`
- `provider`
- `model`
- `state`
- `duration_ms`
- `ttft_ms`
- `chunk_count`
- `cancelled`
- `error_code`
- `cpu_fallback`
- `must_be_local`
- `model_version`

示例：

```text
[ai-diag] task_finished task_id=... session_id=... task_type=reply_suggestion provider=local_gguf model=qwen3.5-omni-2B-Q4_K_M duration_ms=1420 ttft_ms=310 error_code=None
```

禁止字段：

- 完整 Prompt。
- 完整消息内容。
- Provider Token。
- 模型下载签名密钥。
- 本地附件明文内容。

## 15. 测试要求

单元测试：

- `AIService` Provider 选择和错误转换。
- `LocalGGUFProvider` 使用 fake runtime 的成功、失败、取消。
- `LocalGGUFProvider` CPU fallback、资源不足和空闲卸载。
- `PromptBuilder` 上下文裁剪和隐私过滤。
- `AIAssistManager` 推荐触发、去重、失效。
- `AITaskManager` 状态机、取消、runtime 崩溃收敛。
- `AITaskManager` Manager 层输出硬截断。
- `AIConversationManager` 占位消息、partial 状态、重启恢复。
- 模型清单解析、sha256 校验和 active model 选择。

集成测试：

- 私聊收到对方文本后生成推荐回复。
- 点击推荐回复只插入输入框，不自动发送。
- 用户发送消息后推荐候选失效。
- E2EE 会话在未授权远端 Provider 时返回 `AI_PRIVACY_DENIED`。
- E2EE 会话设置 `must_be_local=True` 后不会路由到远端 Provider。
- 本地 Provider 读取 E2EE 明文时不产生远端网络请求。
- 外部 Provider 请求不携带业务 Bearer Token。
- 模型下载校验失败时不能加载模型。
- AI 会话流式输出不会高频刷新 UI。
- 普通聊天发送、接收、删除、预览不受 AI 模块影响。

回归测试：

- direct/group session 的 preview 不被 AI 候选覆盖。
- session 删除和重建语义不受 AI 会话影响。
- E2EE badge、搜索 badge、媒体消息展示不受 AI 变更影响。
- 应用重启后未完成 AI 任务能正确收敛。
- 推荐回复候选重启后不会从数据库恢复。

## 16. 路线图

Phase 1：本地 AI 基础能力

- `LocalGGUFProvider`
- `LocalGGUFRuntime`
- `AITaskManager`
- 模型清单、校验和本地路径配置。
- CPU fallback、空闲卸载和输出硬截断。
- 手动输入辅助
- 手动私聊推荐回复
- 基础日志和错误码

Phase 2：推荐回复产品化

- 活跃私聊自动推荐。
- 候选刷新和风格切换。
- E2EE 本地 AI 策略开关。
- 推荐回复质量评估和失败降级。

Phase 3：AI 会话

- `session_type="ai"` 会话创建。
- 流式 AI 回复。
- 停止生成和重新生成。
- 重启恢复和 preview 策略。

Phase 4：远端 Provider 和多模型

- OpenAI-compatible Provider 完整策略。
- Provider Token 独立配置。
- 远端上下文授权确认。
- 多模型路由和质量模式。

Future：Agent / Action System

- 只作为未来扩展，不进入当前 MVP。
- AI 只能生成动作意图。
- 动作必须经过系统校验和用户确认。
- 高风险动作不能自动执行。

## 17. 验收标准

MVP 验收条件：

- 本地模型配置错误时有明确提示。
- AI 任务可以开始、完成、取消和失败收敛。
- 本地模型资源不足时能明确失败或回退 CPU，不能卡死 UI。
- 模型文件校验失败时不能加载。
- 私聊推荐回复不会自动发送。
- 推荐回复候选不写入持久化数据库。
- AI 结果不会污染 session preview、unread 和消息同步。
- E2EE 明文不会被未经授权发送到远端 AI。
- E2EE 触发的 AI 请求在本地模型不可用时不会自动切到远端。
- 日志足够定位问题，但不泄漏用户明文。
- 相关单元测试和关键集成测试通过。
