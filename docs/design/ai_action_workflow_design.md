# AI 助手动作编排设计方案

## 1. 文档目标

本文档定义 AssistIM AI 助手中“通过自然语言执行应用能力”的通用架构设计。

设计目标不是继续为每个功能新增一个大 action，而是把用户意图拆解为可组合、可恢复、可审计的原子动作，并由统一执行器完成调度、追问、确认和状态持久化。

本文档覆盖范围：

- AI 助手中的自然语言动作规划
- 多 action 组合执行
- 原子 action 注册与执行
- 聊天记录查询、总结、消息草稿、发送确认等通用能力
- 联系人解析、聊天记忆检索、模型总结、用户确认的统一流程
- 失败恢复、重启恢复、权限和安全边界

本文档不描述某一个单点功能的临时实现，也不引入 `V2`、`legacy`、`fallback` 等双轨命名。后续代码应直接重构当前 action workflow，使新架构成为正式实现。

## 2. 当前问题

当前 action workflow 更接近“单 action + 填槽”：

```text
用户输入
  -> Planner 输出一个 action
  -> 本地校验 slots
  -> 执行 memory_query / send_message / add_friend / post_moment
```

这种设计已经暴露出以下问题。

### 2.1 大 action 限制模型真实意图

例如 `memory_query` 被设计为一个大 action 后，它既承担：

- 联系人解析
- 时间范围解析
- 聊天记录检索
- 摘要生成
- 追问策略
- 结果组织

这会导致 action 自身的结构反过来限制模型理解。例如用户说“我和 test1 聊过什么”，真实意图是查询全部历史，但如果 `memory_query` 强制要求 `time_range`，系统就会错误追问时间。

### 2.2 多对象和多步骤表达难以表示

用户可能说：

```text
我和 test1 和 test3 聊过什么？
```

真实意图通常是查询与多个对象相关的聊天内容，而不是在 `test1` 和 `test3` 中二选一。

用户也可能说：

```text
帮我总结昨天和 test1 聊的内容，然后发给 test3
```

这不是一个单 action，而是多个动作的组合：

```text
解析 test1
查询昨天与 test1 的聊天
总结查询结果
解析 test3
生成消息草稿
请求用户确认
发送消息
```

单 action 填槽无法自然表达这类组合任务。

### 2.3 本地硬编码语义判断不可扩展

任何形如：

```text
聊了什么 | 聊过什么 | 聊啥 | 谈过什么 | 说过什么
```

的本地硬编码判断都会存在覆盖不全的问题。

本地代码不应负责理解自然语言语义。语义理解应由模型完成，本地代码只负责：

- 校验结构化 plan
- 执行已注册原子 action
- 做联系人、权限、风险、状态等确定性判断
- 在信息不足或高风险时暂停并请求用户补充或确认

## 3. 设计原则

### 3.1 模型负责理解，系统负责执行

模型负责：

- 判断用户是否要执行应用动作
- 将用户目标拆成原子 action steps
- 决定 steps 之间的依赖
- 给出结构化参数
- 基于 pending plan 理解用户补充、确认、取消

系统负责：

- 校验 plan 是否符合 schema
- 校验 action 是否已注册且允许执行
- 解析 step 引用
- 执行原子 action
- 保存 step output
- 处理用户确认、追问和取消
- 记录日志、错误和审计信息

### 3.2 Action 必须原子化

每个 action 只做一件事。

错误示例：

```text
memory_query = 解析联系人 + 查记录 + 总结 + 追问
```

正确示例：

```text
contact.resolve
memory.search
memory.summarize
user.confirm
message.send
```

### 3.3 多对象不是歧义

用户同时提到多个联系人时，默认应表示多对象查询或多对象操作，不能直接转成“你要查哪一个”。

只有当某一个用户给出的名称在本地联系人中对应多个候选时，才进入联系人歧义确认。

### 3.4 无时间范围不等于缺信息

聊天记录查询中，没有时间范围时应允许 `all_history`。

例如：

```text
我和 test1 聊过什么？
```

应被理解为查询全部历史，而不是追问哪一天。

### 3.5 高风险 action 必须确认

任何会产生外部副作用的动作必须确认，例如：

- 发送消息
- 添加好友
- 发布朋友圈
- 删除数据
- 修改资料

低风险读取动作无需确认，例如：

- 解析联系人
- 查询聊天摘要
- 总结查询结果

### 3.6 Plan 可恢复

动作执行可能跨越多轮对话。系统必须保存完整 plan、当前 step、已完成 step 输出、等待用户输入的 payload。

程序重启、窗口关闭、模型任务取消后，应能恢复或给出明确失败状态。

## 4. 总体架构

目标架构：

```text
AI Assistant UI
  -> AIActionWorkflow
      -> AIActionPlanner
      -> AIPlanNormalizer
      -> AIPlanOptimizer
      -> AIResourceManager
      -> AIActionPlanStore
      -> AIActionExecutor
          -> AtomicActionRegistry
              -> contact.resolve
              -> memory.search
              -> memory.summarize
              -> message.draft
              -> user.confirm
              -> message.send
      -> AIPermissionPolicy
      -> AIActionCache
      -> AIResponder
```

处理流程：

```text
用户输入
  -> 查询当前线程是否存在 pending plan
  -> 无 pending plan: planner 生成新 plan
  -> 有 pending plan: planner 生成 resume decision 或修正后的 plan
  -> validator 校验 plan
  -> 校验失败时进入内部自纠错重试
  -> normalizer 做确定性补全和规范化
  -> optimizer 做安全的组合优化
  -> resource manager 评估预算
  -> executor 按依赖执行 step
  -> executor 发布细粒度状态事件
  -> action 输出写入 step_outputs
  -> 遇到 clarification / confirmation 暂停
  -> 用户补充后 resume
  -> 完成后 responder 输出最终回复
```

## 5. Plan 数据结构

Plan 是模型输出的结构化执行计划。

```json
{
  "goal": "总结我和 test1 的聊天内容",
  "risk": "low",
  "steps": [
    {
      "id": "resolve_contacts",
      "action": "contact.resolve",
      "depends_on": [],
      "args": {
        "queries": ["test1"],
        "allow_multiple": true
      }
    },
    {
      "id": "search_memory",
      "action": "memory.search",
      "depends_on": ["resolve_contacts"],
      "args": {
        "participants": "$resolve_contacts.contacts",
        "participant_match": "any",
        "time_scope": {
          "type": "all_history"
        },
        "keywords": [],
        "question": "我和 test1 聊过什么"
      }
    },
    {
      "id": "summarize_memory",
      "action": "memory.summarize",
      "depends_on": ["search_memory"],
      "args": {
        "source": "$search_memory.results",
        "question": "我和 test1 聊过什么"
      }
    }
  ],
  "final": {
    "type": "answer",
    "source": "$summarize_memory.text"
  }
}
```

### 5.1 字段说明

`goal`

- 用户真实目标的简短描述。
- 用于日志、调试和待确认展示。

`risk`

- plan 整体风险等级。
- 可选值：`low`、`medium`、`high`。
- 由 planner 初步判断，最终以 action registry 和 policy 判断为准。

`steps`

- 原子动作列表。
- 每个 step 必须有唯一 `id`。
- `action` 必须存在于 registry。
- `depends_on` 表示依赖的 step id。

`args`

- 当前 step 的输入参数。
- 可包含对上游 step output 的引用。

`final`

- 描述 plan 完成后如何生成最终回复。
- 可以直接引用某个 step 输出，也可以要求 responder 基于多个输出组织自然语言。

### 5.2 Step 引用语法

第一阶段只支持简单路径引用：

```text
$resolve_contacts.contacts
$search_memory.results
$summarize_memory.text
```

不支持表达式、过滤器、函数调用和复杂索引计算。

如确实需要列表取值，可支持有限索引：

```text
$resolve_target.contacts[0]
```

引用解析失败时，executor 应标记 plan failed 或进入 clarification，而不是让 action 收到未解析字符串继续执行。

### 5.3 大型 Payload 引用

Step output 不应无条件把大块文本写入 `step_outputs_json`。

当 action 输出可能超过阈值时，应写入本地临时结果集，并在 step output 中只保存引用。

示例：

```json
{
  "result_ref": {
    "type": "memory_search_result",
    "id": "temp_result_12345",
    "result_count": 150,
    "estimated_chars": 42000,
    "expires_at": 1776700000
  }
}
```

后续 step 使用：

```json
{
  "source": "$search_memory.result_ref"
}
```

Executor 在执行 `memory.summarize` 时，根据 `result_ref` 从本地数据库读取分页结果，而不是把完整结果通过 JSON 树传递。

适用对象：

- 聊天搜索结果
- 原始消息片段
- 图片 OCR / 视觉描述长文本
- 文件解析结果
- 模型中间草稿

默认阈值建议：

```text
单个 step output JSON 不超过 64 KB
传给模型的单次 source 不超过配置的 max_context_chars
临时结果集默认 24 小时过期
```

超过阈值时必须使用引用传值。

### 5.4 Plan 生命周期版本化

Plan 不是单次生成后永不变化的静态结构。

实际运行中可能出现：

- Planner 首次输出后被 validator 要求自纠错。
- Normalizer 自动补全 step id、依赖、确认步骤。
- Optimizer 替换或合并部分 step。
- 用户中途修改需求。
- Executor 发现运行时条件变化，需要插入或改写 step。

因此，存储层必须记录 plan 演进历史，而不是只保存最终 `plan_json`。

建议结构：

```json
{
  "current_version": 3,
  "versions": [
    {
      "version": 1,
      "plan": {},
      "reason": "initial",
      "created_at": 1776700000
    },
    {
      "version": 2,
      "plan": {},
      "reason": "planner_retry_fix_invalid_action",
      "created_at": 1776700001
    },
    {
      "version": 3,
      "plan": {},
      "reason": "user_revision",
      "created_at": 1776700100
    }
  ]
}
```

数据库字段建议：

```text
plan_version
parent_plan_id
plan_history_json
```

版本化要求：

- 每次 plan 结构变化都必须产生新版本。
- `step_outputs_json` 必须记录对应的 `plan_version`。
- resume 时必须校验 pending plan 的 `current_version`，避免使用旧 plan。
- 内部自纠错、normalizer、optimizer、用户修改都必须写入 `reason`。
- 日志中记录 `plan_id`、`plan_version`、`reason`，便于调试。

版本化目标：

- 追踪 plan 为什么变成当前结构。
- 对比 planner 输出和系统改写。
- 支持失败后回溯。
- 为后续回滚或 replay 提供依据。

## 6. Plan 状态存储

建议新增正式表：

```text
ai_action_plans
```

字段：

```text
id
thread_id
state
goal
plan_json
plan_version
parent_plan_id
plan_history_json
step_outputs_json
waiting_payload_json
current_step_id
error_text
created_at
updated_at
completed_at
```

`step_outputs_json` 只保存小型结构化输出和大型 payload 引用，不保存大量聊天明文。

大型临时结果建议单独存储：

```text
ai_action_temp_results
```

字段：

```text
id
plan_id
step_id
result_type
payload_json
payload_meta_json
created_at
expires_at
```

如 payload 包含聊天明文或摘要正文，应遵守本地加密策略。

### 6.1 State 枚举

```text
running
waiting_clarification
waiting_confirmation
done
failed
cancelled
```

### 6.2 waiting_payload

当 plan 暂停时，`waiting_payload_json` 保存恢复所需信息。

联系人歧义示例：

```json
{
  "type": "contact_ambiguity",
  "step_id": "resolve_contacts",
  "query": "小王",
  "candidates": [
    {
      "contact_id": "user-1",
      "display_name": "小王",
      "username": "test1"
    },
    {
      "contact_id": "user-2",
      "display_name": "小王",
      "username": "test2"
    }
  ]
}
```

发送确认示例：

```json
{
  "type": "confirmation",
  "step_id": "send_message",
  "risk": "high",
  "preview": {
    "target": "test3",
    "content": "昨天我们主要聊了..."
  }
}
```

## 7. Atomic Action Registry

Registry 描述系统具备哪些原子动作。

示例：

```python
AtomicActionSpec(
    name="memory.search",
    kind="read",
    risk_level="low",
    requires_confirmation=False,
    enabled=True,
    input_schema={...},
    output_schema={...},
    max_input_bytes=32768,
    max_output_json_bytes=65536,
    timeout_ms=15000,
    max_retries=1,
    max_targets=None,
    allow_batch=False,
    require_resolved_target=False,
    allow_all_history=True,
    allow_cross_session=True,
    allow_side_effect=False,
    allow_raw_content_return=False,
    max_content_chars=None,
    idempotency_required=False,
    supports_compensation=False,
    compensate_action=None,
)
```

Registry 只描述能力，不负责业务意图判断。

不应在 registry 中写：

```text
memory.search 必须有 time_range
```

应由 action 输入 schema 和 policy 判断实际是否可执行。对于聊天记录查询，`all_history` 是合法时间范围。

### 7.1 声明式执行边界

每个 action 都必须声明自己的执行边界。

这些限制不是业务语义理解规则，而是平台级护栏。它们用于防止资源爆炸、越权读取、误操作、重复执行和格式错误。

建议字段：

```python
class AtomicActionSpec(BaseModel):
    name: str
    kind: Literal["read", "write"]
    risk_level: Literal["low", "medium", "high"]
    requires_confirmation: bool = False
    enabled: bool = True

    max_input_bytes: int = 32768
    max_output_json_bytes: int = 65536
    timeout_ms: int = 15000
    max_retries: int = 0

    max_targets: int | None = None
    allow_batch: bool = False
    require_resolved_target: bool = False
    allow_all_history: bool = True
    allow_cross_session: bool = False
    allow_side_effect: bool = False
    allow_raw_content_return: bool = False
    max_content_chars: int | None = None
    idempotency_required: bool = False

    supports_compensation: bool = False
    compensate_action: str | None = None
```

执行边界必须由 registry、executor 和 policy 统一处理，不能散落在各个 action 的业务代码里。

不允许把自然语言语义特判写成 action 限制。

错误示例：

```text
memory.search 没有 time_range 就拒绝执行
用户提到两个联系人就必须追问选一个
```

正确示例：

```text
memory.search 允许 all_history，但 all_history 必须走摘要优先、结果上限和分块总结
message.send 首期只允许单目标、必须唯一解析、必须确认、必须预览
```

### 7.2 通用护栏

所有 action 默认继承以下通用限制：

- 输入大小上限。
- 输出 JSON 大小上限。
- 执行超时。
- 最大重试次数。
- 输入 schema 校验。
- 输出 schema 校验。
- 权限作用域校验。
- 是否允许副作用。
- 是否需要幂等键。
- 是否允许保存大型 payload。

通用护栏由 executor 在 action 执行前后统一检查：

```text
resolve refs
  -> check max_input_bytes
  -> validate input model
  -> check permission scope
  -> execute action with timeout
  -> validate output model
  -> enforce max_output_json_bytes or result_ref
  -> persist output
```

### 7.3 按 Action 类型分级限制

读类 action 重点限制资源和隐私。

默认策略：

```text
kind=read
risk_level=low 或 medium
allow_side_effect=false
requires_confirmation=false
idempotency_required=false
```

读类 action 典型限制：

- 一次最多解析多少个 query。
- 一次最多查多少联系人或群。
- 是否允许跨会话。
- 是否允许 all_history。
- all_history 是否必须摘要优先。
- 原文片段最多返回多少条、多少字。
- 单次 summarize 最多消耗多少上下文。
- 临时结果引用多久过期。

写类 action 重点限制误操作和重复执行。

默认策略：

```text
kind=write
risk_level=high
allow_side_effect=true
requires_confirmation=true
idempotency_required=true
```

写类 action 典型限制：

- 单次最多影响多少对象。
- 是否允许批量。
- 是否允许自动连续执行。
- 是否必须唯一解析目标对象。
- 是否必须展示 preview。
- 是否允许引用模型生成的长文本直接外发。
- 内容最大长度。
- resume 后是否必须重新确认。

### 7.4 高风险 Action 硬限制

高风险副作用 action 需要比“要求确认”更严格的硬门槛。

`message.send` 首期建议：

```python
AtomicActionSpec(
    name="message.send",
    kind="write",
    risk_level="high",
    requires_confirmation=True,
    enabled=False,
    max_targets=1,
    allow_batch=False,
    require_resolved_target=True,
    require_preview=True,
    max_content_chars=500,
    allow_auto_resume_after_confirm=False,
    idempotency_required=True,
)
```

规则：

- 目标必须是唯一解析实体。
- 首期只允许单目标。
- 不允许用户一句话触发批量发送。
- 发送内容必须展示 preview。
- 内容过长时必须先生成草稿并让用户确认。
- 用户确认只对当前 preview 生效。
- 如果 plan、目标或内容在确认后发生变化，必须重新确认。
- 当前真实发送未接入时，仍应执行完整确认流程后返回 disabled 状态。

未来 `friend.add`、`moment.publish`、删除类 action 也必须声明类似硬限制。

### 7.5 强类型输入输出

每个原子 action 必须定义严格的输入和输出模型。

Python 实现建议使用 Pydantic：

```python
class MemorySearchInput(BaseModel):
    participants: list[ResolvedContact] = Field(default_factory=list)
    participant_match: Literal["any", "all", "direct_only", "group_only"] = "any"
    time_scope: TimeScope
    keywords: list[str] = Field(default_factory=list)
    question: str = ""


class MemorySearchOutput(BaseModel):
    result_ref: TempResultRef | None = None
    results: list[MemoryItem] = Field(default_factory=list)
    result_count: int = 0
    truncated: bool = False
```

Executor 在解析 `$step.output` 引用并注入参数后，必须立即执行：

```python
validated_input = spec.input_model.model_validate(resolved_args)
```

Action 执行返回后，也必须执行：

```python
validated_output = spec.output_model.model_validate(raw_output)
```

类型错误应在 action 逻辑执行前被拦截，不允许把未校验参数传入数据库、网络或模型调用。

## 8. 首批原子 Action

### 8.1 contact.resolve

职责：把用户表达的联系人、群名、用户名、备注名解析成稳定本地实体。

输入：

```json
{
  "queries": ["test1", "test3"],
  "allow_multiple": true
}
```

输出：

```json
{
  "contacts": [
    {
      "raw": "test1",
      "contact_id": "user-1",
      "username": "test1",
      "nickname": "test1",
      "remark": "",
      "display_name": "test1",
      "aliases": ["test1", "user-1"]
    }
  ],
  "groups": [],
  "ambiguous": [],
  "unresolved": []
}
```

行为规则：

- 每个 query 独立解析。
- 多个 query 不构成歧义。
- 单个 query 对应多个联系人时，进入 `waiting_clarification`。
- query 找不到联系人时，进入 `waiting_clarification` 或允许后续按关键词查询，取决于 plan 和 policy。

### 8.2 memory.search

职责：根据结构化条件查询本地聊天摘要、聊天记忆索引或原始消息索引。

输入：

```json
{
  "participants": "$resolve_contacts.contacts",
  "participant_match": "any",
  "time_scope": {
    "type": "all_history"
  },
  "keywords": [],
  "question": "我和 test1 聊过什么"
}
```

`participant_match`：

```text
any
all
direct_only
group_only
```

含义：

- `any`：查询任一参与人相关记录，并合并结果。
- `all`：查询同一会话或同一记录中同时包含全部参与人的内容。
- `direct_only`：只查私聊。
- `group_only`：只查群聊。

`time_scope`：

```json
{ "type": "all_history" }
```

```json
{
  "type": "range",
  "start": "2026-04-20T00:00:00",
  "end": "2026-04-21T00:00:00",
  "label": "昨天"
}
```

```json
{
  "type": "recent",
  "days": 7,
  "label": "最近一周"
}
```

输出：

```json
{
  "result_ref": {
    "type": "memory_search_result",
    "id": "temp_result_12345",
    "result_count": 150
  },
  "preview": [
    {
      "source_type": "summary",
      "source_id": "summary:...",
      "title": "...",
      "text_preview": "..."
    }
  ],
  "result_count": 1,
  "truncated": false
}
```

查询策略：

1. 优先查本地摘要和聊天记忆索引。
2. 摘要不足时，可以查更细粒度消息索引。
3. 默认不直接输出原始聊天记录。
4. 用户明确要求原文时，才允许返回有限引用片段。
5. `all_history` 查询需要结果上限和摘要优先策略，防止一次性塞入过大上下文。

上下文和 payload 限制：

- `memory.search` 必须支持分页。
- 单次检索结果必须有 `max_items`、`max_chars` 或 `max_tokens` 上限。
- 超过上限时，输出 `result_ref` 和少量 `preview`，不把完整结果写入 `step_outputs_json`。
- `memory.summarize` 通过 `result_ref` 分批读取本地结果，必要时执行分块总结。
- 对 `all_history` 查询，默认走“摘要优先 + 分块汇总 + 最终归纳”的策略。

### 8.3 memory.summarize

职责：将 `memory.search` 的结果总结成用户可读回答。

输入：

```json
{
  "source": "$search_memory.result_ref",
  "question": "我和 test1 聊过什么",
  "style": "旁观者总结"
}
```

输出：

```json
{
  "text": "你和 test1 主要聊过三类内容：..."
}
```

行为规则：

- 输出应是总结，不是搜索结果列表。
- 不得编造未出现在 source 中的信息。
- source 为空时，应输出未找到相关记录的自然语言说明。
- source 超过模型上下文限制时，必须分块总结，再对分块总结做最终归纳。

分块策略：

```text
memory.search result_ref
  -> chunk 1 summarize
  -> chunk 2 summarize
  -> chunk N summarize
  -> final summarize
```

每个 chunk 的输入必须受 `max_context_chars` 或 `max_context_tokens` 限制。

### 8.4 message.draft

职责：生成消息草稿，不产生外部副作用。

输入：

```json
{
  "target": "$resolve_target.contacts[0]",
  "content": "$summarize_memory.text",
  "instruction": "发给对方"
}
```

输出：

```json
{
  "target": {
    "contact_id": "user-3",
    "display_name": "test3"
  },
  "content": "昨天我们主要聊了..."
}
```

### 8.5 user.confirm

职责：暂停 plan，等待用户确认高风险操作。

输入：

```json
{
  "risk": "high",
  "prompt": "确认要发送这条消息吗？",
  "preview": "$draft_message"
}
```

输出：

```json
{
  "approved": true
}
```

`user.confirm` 不应通过本地词表判断用户回复。用户补充输入应交给 planner，结合 pending plan 输出 resume decision。

### 8.6 message.send

职责：发送消息。

当前阶段可以保留 disabled executor，不进行真实发送。

输入：

```json
{
  "target": "$draft_message.target",
  "content": "$draft_message.content"
}
```

行为规则：

- 必须依赖 `user.confirm`。
- 如果没有确认输出，executor 必须拒绝执行。
- 当前未接入真实发送时，返回 disabled 状态。

### 8.7 后续动作

可在同一机制下扩展：

```text
friend.search
friend.add
moment.draft
moment.publish
profile.lookup
file.search
image.describe
```

新增 action 只需要注册 schema、risk、executor 和必要测试，不应新增业务大 workflow。

## 9. Planner 设计

Planner 输入：

- 用户当前输入
- 当前本地时间
- 可用 atomic action 列表
- 每个 action 的能力说明、输入输出概要和风险
- 当前 pending plan 和 waiting payload

Planner 输出：

- 新 plan
- 或 pending plan 的 resume decision
- 或普通聊天标记

Planner 不应独自承担全部确定性策略。系统应采用 hybrid planning：

```text
LLM Planner
  -> 输出 high-level structured plan
System Normalizer
  -> 做确定性补全、规范化、策略插入
System Optimizer
  -> 做安全的执行优化
Validator
  -> 校验最终可执行 plan
```

### 9.1 新 Plan 输出规则

Planner 必须遵守：

- 只输出 JSON。
- 不直接回答用户问题。
- 不编造联系人、聊天记录或执行结果。
- 复杂请求必须拆成多个原子 action。
- 多联系人使用数组表达。
- 没有时间范围但语义是“聊过什么、以前、所有聊天”时，使用 `all_history`。
- 高风险副作用必须加入 `user.confirm`。
- 不能要求系统执行未注册 action。

### 9.2 System Normalizer

Normalizer 是确定性改写层，用于降低对模型完美输出的依赖。

Normalizer 可以做：

- 补全缺失 step id。
- 规范化 action 名称大小写。
- 补全 `depends_on`。
- 将高风险 action 前自动插入 `user.confirm`。
- 将联系人字符串参数改写为显式 `contact.resolve` 依赖。
- 将无时间的聊天记忆查询规范化为 `time_scope.type = all_history`。
- 为每个 step 注入默认 retry policy 和 budget。

Normalizer 不应做：

- 猜测用户没表达的业务目标。
- 编造联系人、时间范围或聊天内容。
- 绕过用户确认。
- 把高风险 action 降级成低风险。

Normalizer 产生的任何结构变化都必须写入 plan history：

```json
{
  "version": 2,
  "reason": "normalizer_insert_user_confirm",
  "plan": {}
}
```

### 9.3 Planner 自纠错

模型输出可能出现以下问题：

- JSON 结构不合法。
- action 未注册。
- step id 重复。
- `depends_on` 引用不存在。
- `$step.output` 引用不存在。
- action args 不符合输入模型。
- 高风险 action 缺少 `user.confirm`。

Validator 不应第一次失败就直接把错误暴露给用户。

推荐内部自纠错流程：

```text
planner 输出 plan
  -> validator 校验失败
  -> 构造 validation error prompt
  -> planner 静默重试
  -> 最多重试 1-2 次
  -> 仍失败则进入 waiting_clarification 或 failed
```

自纠错 prompt 只包含结构化错误，不包含完整聊天明文。

示例：

```text
Validation failed:
- step "search_memory" action "memory.lookup" is not registered.
- step "summarize" references "$search.results", but no step id "search" exists.

Please return a corrected JSON plan using only registered actions.
```

重试限制：

- 默认最多 2 次。
- 不允许无限重试。
- 每次重试必须记录 `planner_retry_count` 和错误码。
- 若错误来自用户信息不足，应转入 clarification，而不是继续要求模型猜。

### 9.4 Resume Decision

当存在 pending plan 时，Planner 不重新生成完整 plan，优先输出 resume decision。

联系人选择：

```json
{
  "type": "clarification_answer",
  "target_step": "resolve_contacts",
  "payload": {
    "selected_contact_ids": ["user-2"]
  }
}
```

确认：

```json
{
  "type": "confirmation",
  "approved": true
}
```

取消：

```json
{
  "type": "cancel"
}
```

修改请求：

```json
{
  "type": "revise_plan",
  "instruction": "不要发给 test3，只总结给我看"
}
```

第一阶段可以只实现：

- `clarification_answer`
- `confirmation`
- `cancel`

`revise_plan` 可以后续扩展。

## 10. Executor 设计

Executor 不理解自然语言，只执行结构化 plan。

伪代码：

```python
async def run_plan(plan_state):
    while True:
        step = next_runnable_step(plan_state.plan, plan_state.step_outputs)
        if step is None:
            return build_final_response(plan_state)

        args = resolve_step_refs(step.args, plan_state.step_outputs)
        args = validate_action_input(step.action, args)
        result = await atomic_registry.execute(step.action, args, plan_state)
        output = validate_action_output(step.action, result.output)

        if result.status in ("waiting_clarification", "waiting_confirmation"):
            await store.pause(plan_state, step.id, result.waiting_payload)
            return result.user_message

        if result.status == "failed":
            await store.fail(plan_state, step.id, result.error)
            return result.user_message

        plan_state.step_outputs[step.id] = persist_or_reference_large_output(output)
        await store.save_outputs(plan_state)
```

### 10.1 Step 调度

第一阶段：

- 支持按 `steps` 顺序执行。
- 执行前校验 `depends_on` 是否已完成。
- 不做并发。

后续可扩展：

- DAG 拓扑排序。
- 无依赖 step 并行执行。
- 可重试 step。

### 10.2 输出持久化

每完成一个 step，立即写入 `step_outputs_json`。

这样在以下场景中可以恢复：

- 用户关闭 AI 助手页。
- 程序退出。
- 模型生成被取消。
- 需要用户确认后跨轮继续。

### 10.3 幂等性

低风险读取动作可以重试。

高风险副作用动作必须有幂等键，例如：

```text
plan_id + step_id
```

避免恢复或重试时重复发送消息。

当前真实发送未接入时，仍应按这个规则设计。

### 10.4 执行事件

Executor 应在状态变化时向 UI 发布细粒度事件。

事件类型：

```text
plan_started
step_started
step_progress
step_completed
step_waiting_clarification
step_waiting_confirmation
step_failed
plan_completed
plan_cancelled
```

事件示例：

```json
{
  "type": "step_started",
  "plan_id": "plan_1",
  "step_id": "resolve_contacts",
  "action": "contact.resolve",
  "display_text": "正在解析联系人..."
}
```

```json
{
  "type": "step_completed",
  "plan_id": "plan_1",
  "step_id": "search_memory",
  "action": "memory.search",
  "display_text": "已检索到 150 条记录，正在生成总结...",
  "meta": {
    "result_count": 150
  }
}
```

事件发布方式：

- 桌面客户端内部优先通过 Qt signal / EventBus。
- 如果后续需要跨进程或服务端执行，可复用 WebSocket 或 SSE 风格事件。

事件日志不得包含完整聊天明文。

### 10.5 上下文窗口控制

任何调用模型的 action 都必须显式声明上下文预算。

建议配置：

```text
planner.max_prompt_chars
memory_summarize.max_context_chars
memory_summarize.max_chunk_chars
memory_summarize.max_output_tokens
responder.max_context_chars
```

Executor 在调用模型前负责裁剪、分块或引用读取，不允许把完整 `step_outputs_json` 直接塞进 prompt。

默认优先级：

1. 用户当前问题
2. 当前 step 必要参数
3. 命中的高相关摘要
4. 低相关摘要
5. 原始消息片段

上下文不足时应降级为分块总结，而不是静默截断关键输入。

### 10.6 全局资源预算

Context budget 只控制单次模型调用，不足以控制整个 plan 的资源消耗。

需要新增 `AIResourceManager` 或 `BudgetController`，在 plan 执行前和 step 执行中做全局预算控制。

Plan 级预算：

```text
max_steps_per_plan
max_total_model_calls
max_total_input_tokens
max_total_output_tokens
max_total_runtime_seconds
max_contacts_per_plan
max_temp_result_bytes
max_memory_results
```

Step 级预算：

```text
max_retries
max_input_tokens
max_output_tokens
max_result_items
max_result_chars
timeout_seconds
```

预算行为：

- Planner 输出 plan 后，先做预算预估。
- 预算明显超限时进入 clarification，让用户缩小范围。
- 执行过程中每个 step 消耗都写入 plan state。
- 超过硬限制时停止后续 step，并给出可恢复说明。
- 读取类 action 可以降级为更粗粒度摘要。
- 高风险写 action 不允许因预算不足而跳过确认。

示例：

```text
用户：总结我过去一年和所有人的聊天，然后分别发给他们
```

系统应在执行前评估：

- 联系人数量是否超限
- 搜索结果是否超限
- 预计模型调用次数是否超限
- 是否包含批量高风险发送

如果超限，应先询问用户缩小范围，而不是直接生成巨大 plan。

### 10.7 Step 重试与降级

Step 失败不应只有 `done / waiting / failed` 三种最终状态。

每个 step 应支持 retry policy：

```json
{
  "retry_policy": {
    "max_retries": 2,
    "strategy": "exponential_backoff",
    "retry_on": ["timeout", "transient_model_error"]
  }
}
```

系统默认策略：

- 只读数据库查询：可短重试。
- 本地模型总结：可重试，失败后可降级为更短上下文或更粗摘要。
- 临时结果过期：可回到上游 search step 重建 result_ref。
- 高风险副作用：默认不可自动重试，除非有幂等键且 action 明确声明可重试。

Fallback 示例：

```json
{
  "fallback": {
    "action": "memory.search_light",
    "reason": "memory.search timeout"
  }
}
```

首期可以不开放 planner 自定义 fallback，但系统应预留 step fallback 字段，并先实现内置降级：

- `memory.search` 结果过大 -> `summary_only`
- `memory.summarize` context 超限 -> chunk summarize
- 模型生成失败 -> 缩短输入后重试一次

### 10.8 Plan Optimizer

Planner 输出的是语义计划，不一定是最佳执行计划。

需要引入 `AIPlanOptimizer` 做安全的组合级优化。

Optimizer 可以做：

- 合并连续相同 action。
- 删除不可达 step。
- 将明显重复的 `contact.resolve` 合并。
- 将 `memory.search + memory.summarize` 替换为更高效策略。
- 对 `all_history` 查询优先选择摘要索引，而不是原始消息。
- 对多联系人查询按联系人分组后合并总结。

示例：

```text
memory.search(all_history) -> memory.summarize
```

如果已有可用聚合摘要，可优化为：

```text
memory.quick_summary
```

Optimizer 约束：

- 不改变用户目标。
- 不降低安全等级。
- 不移除高风险确认。
- 不引入未注册 action。
- 每次优化必须写入 plan history，reason 以 `optimizer_` 开头。

### 10.9 跨 Step 语义缓存

`step_outputs` 只解决同一个 plan 内的数据传递，不解决跨 plan 或跨 step 的重复计算。

建议新增语义缓存：

```text
AIActionCache
```

缓存对象：

- 联系人解析结果
- 聊天记忆查询 result_ref
- 分块总结结果
- 最终聚合摘要
- 草稿生成结果

缓存 key 示例：

```text
contact.resolve:test1
memory.search:user-1:all_history:any
memory.summary:user-1:all_history:v1
memory.chunk_summary:temp_result_12345:chunk_3
```

缓存要求：

- cache key 必须包含数据版本或摘要索引版本。
- 会话摘要更新后，相关缓存失效。
- 联系人备注或昵称变化后，联系人解析缓存失效。
- 缓存不得跨越用户隐私授权边界。
- 缓存命中仍要记录日志指标。

### 10.10 Plan 长度与批处理

复杂任务可能生成非常长的 plan。

例如：

```text
给 10 个人分别发不同总结
```

如果展开为每人一套：

```text
resolve -> search -> summarize -> draft -> confirm -> send
```

Plan 会迅速膨胀。

首期限制：

```text
max_steps_per_plan <= 20
max_contacts_per_plan <= 5
max_write_actions_per_plan <= 1
```

超过限制时应进入 clarification，请用户缩小范围或分批执行。

后续可扩展：

```text
batch step
loop step
map-reduce step
```

但首期不实现循环 DSL，避免 executor 复杂度过高。

## 11. Policy 设计

Policy 负责判断能否执行，不负责理解自然语言。

### 11.1 直接执行

以下低风险动作可直接执行：

- `contact.resolve`
- `memory.search`
- `memory.summarize`
- `message.draft`

### 11.2 需要追问

以下情况进入 `waiting_clarification`：

- 联系人名称对应多个候选。
- 必要结构化参数无法解析。
- Plan 引用了不存在的 step output。
- 用户请求完全没有查询对象、查询主题或可执行目标。
- 查询范围过大且会明显影响性能，需要用户确认范围。

注意：无时间范围不应默认追问，`all_history` 是合法范围。

### 11.3 需要确认

以下动作必须确认：

- `message.send`
- `friend.add`
- `moment.publish`
- 删除或修改本地数据
- 任何跨出本地只读边界的操作

确认策略必须结合 action spec：

- `requires_confirmation=true` 的 action 必须确认。
- `max_targets` 超出限制时不得执行。
- `allow_batch=false` 时不得批量执行。
- `require_resolved_target=true` 时目标必须是唯一实体。
- `max_content_chars` 超出限制时必须改为草稿或要求用户缩短。
- `idempotency_required=true` 时必须具备幂等键。
- preview 内容、目标或 plan version 变化后，旧确认失效。

### 11.4 禁止执行

以下情况必须拒绝：

- Action 未注册。
- Action 被配置禁用。
- Plan 请求读取无权限会话。
- Plan 请求绕过 E2EE 授权边界。
- Plan 要求输出完整敏感聊天原文但用户没有明确请求。
- Action 输入或输出超过 spec 声明的硬限制。
- 高风险 action 缺少幂等键。
- 高风险 action 目标不是唯一解析实体。
- 高风险 action 试图批量执行但 `allow_batch=false`。

### 11.5 细粒度权限作用域

AI action 不应只有“允许 / 拒绝”的粗粒度权限。

建议定义 scope policy：

```json
{
  "allowed_contacts": ["user-1", "user-2"],
  "allowed_groups": ["group-1"],
  "excluded_contacts": [],
  "excluded_groups": [],
  "sensitive_tags": ["private", "work", "blocked"],
  "allow_e2ee_plaintext": false,
  "allow_raw_message_quote": false
}
```

权限判断点：

- Planner 生成 plan 后做初步 scope 校验。
- `contact.resolve` 输出实体后做实体级校验。
- `memory.search` 执行前做会话和消息范围校验。
- `memory.summarize` 读取 result_ref 前再次校验。
- 高风险写 action 执行前做目标对象校验。

典型策略：

- 黑名单联系人永远不进入 AI 查询结果。
- E2EE 私聊默认不进入 AI 上下文，除非用户明确授权。
- 工作标签、隐私标签可配置为需二次确认。
- 群聊查询需要遵守群成员和本地缓存可见性。

权限拒绝必须给出稳定错误码 `PERMISSION_DENIED`，但不暴露敏感对象细节。

## 12. 聊天记录查询设计

聊天记录查询不再是一个大 action，而是组合：

```text
contact.resolve
memory.search
memory.summarize
```

### 12.1 单联系人全部历史

用户：

```text
我和 test1 聊过什么？
```

Plan：

```text
contact.resolve(["test1"])
memory.search(time_scope=all_history, participants=$contacts, participant_match=any)
memory.summarize(...)
```

不追问时间。

### 12.2 多联系人全部历史

用户：

```text
我和 test1 和 test3 聊过什么？
```

Plan：

```text
contact.resolve(["test1", "test3"])
memory.search(time_scope=all_history, participants=$contacts, participant_match=any)
memory.summarize(...)
```

不追问“查哪一个”。

### 12.3 多联系人同一会话

用户：

```text
我、test1 和 test3 在群里聊过什么？
```

Planner 可以选择：

```text
participant_match=all
group_only
```

### 12.4 指定时间

用户：

```text
昨天我和 test1 聊了什么？
```

Plan 使用：

```json
{
  "type": "range",
  "start": "2026-04-20T00:00:00",
  "end": "2026-04-21T00:00:00",
  "label": "昨天"
}
```

### 12.5 查询结果不足

如果 `memory.search` 未找到结果：

- `memory.summarize` 输出未找到说明。
- 不应编造。
- 可提示用户换时间范围、联系人或关键词。

## 13. AI 助手 UI 集成

AI 助手页只负责展示状态，不直接执行 action。

UI 需要支持：

- plan 正在执行
- 等待用户补充
- 等待用户确认
- 已取消
- 失败
- 完成

消息展示建议：

- 用户输入立即插入消息流。
- 如果 plan 执行中，立即插入 AI 占位消息。
- 若进入 confirmation，AI 消息展示确认内容和预览。
- 若进入 clarification，AI 消息展示候选列表或追问。
- 用户确认或选择后，继续更新同一 plan 的后续 AI 回复。

### 13.1 细粒度状态展示

长任务不能只展示一个静态“AI 正在思考”。

UI 应根据 executor 事件展示可折叠的执行状态，例如：

```text
正在解析联系人...
已找到 test1
正在检索聊天记录...
已检索到 150 条记录
正在分块总结...
正在生成最终回复...
```

建议展示方式：

- AI 消息气泡上方或内部显示一个可折叠的“执行过程”区域。
- 默认只展示当前 step 的短状态。
- 用户展开后可查看 step 列表、耗时、结果数量和是否截断。
- 不展示聊天明文、完整 prompt 或敏感 payload。

### 13.2 可解释性展示

UI 除了显示“正在做什么”，还应能显示“为什么这么做”。

不需要展示模型完整推理链，只展示结构化解释摘要。

Step 可包含：

```json
{
  "id": "resolve_contacts",
  "action": "contact.resolve",
  "display_text": "正在解析联系人...",
  "explanation": "用户提到 test1，需要先解析为本地联系人。"
}
```

可解释性规则：

- explanation 由 planner 或 normalizer 给出。
- 系统可以覆盖或补充确定性解释。
- 不展示完整 Chain-of-Thought。
- 不展示完整 prompt。
- 不展示聊天明文。

UI 展示建议：

- 默认隐藏解释，只显示简短状态。
- 用户展开执行过程时显示 explanation。
- 高风险确认必须显示为什么需要确认。

### 13.3 Streaming 与最终回复

`memory.summarize` 和 `responder` 可流式输出。

推荐行为：

- plan 运行开始时立即插入 AI 占位消息。
- step 事件更新占位消息的状态区域。
- 最终自然语言回答流式写入正文区域。
- 如果用户滚动离开底部，不强制滚动到底部，只显示“回到底部”按钮。

### 13.4 取消

用户点击停止或取消时：

- 当前可取消模型任务应取消。
- plan state 写入 `cancelled`。
- 已完成的低风险 step output 可以保留用于审计和调试。
- 未确认的高风险 step 不执行。

## 14. 隐私和安全边界

### 14.1 本地优先

聊天记录、联系人、摘要和 E2EE 明文只允许进入本地模型上下文，除非用户明确授权外部 Provider。

### 14.2 日志约束

日志允许记录：

- plan id
- step id
- action name
- state
- result_count
- duration_ms
- error_code

日志不得记录：

- 完整聊天明文
- 完整 Prompt
- 联系人敏感字段全集
- 消息发送内容全文
- 附件明文路径
- 密钥或 token

### 14.3 高风险确认

所有外部副作用必须确认。

确认消息必须包含：

- 操作类型
- 目标对象
- 内容预览
- 风险提示

## 15. 错误处理

统一错误类型：

```text
PLAN_PARSE_FAILED
PLAN_SCHEMA_INVALID
PLAN_VALIDATION_RETRY_EXHAUSTED
ACTION_NOT_FOUND
ACTION_DISABLED
ARG_REFERENCE_INVALID
ARG_SCHEMA_INVALID
OUTPUT_SCHEMA_INVALID
CONTACT_AMBIGUOUS
CONTACT_NOT_FOUND
MEMORY_NOT_FOUND
PAYLOAD_TOO_LARGE
TEMP_RESULT_EXPIRED
CONTEXT_BUDGET_EXCEEDED
MODEL_GENERATION_FAILED
USER_CANCELLED
CONFIRMATION_REQUIRED
PERMISSION_DENIED
```

错误处理原则：

- 可补充的错误进入 clarification。
- 高风险未确认进入 confirmation。
- 不可恢复错误进入 failed。
- 用户取消进入 cancelled。
- failed / cancelled 必须写入 plan state。
- schema、引用和上下文预算错误应先进入内部自纠错重试。
- 自纠错耗尽后，能让用户补充的进入 clarification，不能恢复的进入 failed。

## 16. 补偿动作与事务边界

首期不实现跨 action 事务补偿，但 action registry 需要预留补偿字段。

未来可能出现的场景：

```text
向多个联系人发送不同消息
批量修改联系人备注
批量发布或删除内容
```

如果执行到一半用户取消或后续 step 失败，需要考虑补偿动作。

设计预留：

```python
AtomicActionSpec(
    name="message.send",
    risk_level="high",
    supports_compensation=True,
    compensate_action="message.recall",
)
```

首期规则：

- 不把多个高风险副作用合并成不可控批处理。
- 高风险 step 执行前必须逐项或批量明确确认。
- 一旦高风险 step 已执行，不承诺自动撤销。
- 文档和 UI 必须明确“取消只取消尚未执行的后续步骤”。

## 17. 测试要求

### 17.1 Planner 测试

使用 fake planner 覆盖：

- 单联系人全部历史查询
- 多联系人全部历史查询
- 指定时间查询
- 查询后发送消息
- 用户确认
- 用户取消
- 用户选择重名联系人
- planner 输出非法 action 后自纠错
- planner 输出非法 step 引用后自纠错

### 17.2 Executor 测试

覆盖：

- step 顺序执行
- depends_on 校验
- step output 引用解析
- 引用不存在时失败
- step output 持久化
- 中途暂停后 resume
- resume 不重跑已完成 step
- 输入模型校验失败
- 输出模型校验失败
- 大 payload 自动写入临时结果并以引用保存
- 临时结果过期后的错误处理
- 执行事件顺序

### 17.3 Atomic Action 测试

覆盖：

- `contact.resolve` 单命中、多命中、无命中
- `memory.search` all_history、range、recent
- `memory.search` participant_match any / all
- `memory.search` 分页、截断、result_ref
- `memory.summarize` 空结果和非空结果
- `memory.summarize` 分块总结和最终归纳
- `message.send` 未确认拒绝
- disabled action 返回稳定状态
- 通用护栏拦截超大输入和超大输出
- action 超时后进入稳定错误状态
- read action 超过资源限制时降级或 clarification
- write action 超过 `max_targets` 时拒绝
- `allow_batch=false` 时拒绝批量副作用
- `max_content_chars` 超限时不允许直接发送
- preview 变化后旧确认失效
- `idempotency_required=true` 时缺少幂等键拒绝执行

### 17.4 UI 测试

覆盖：

- 用户消息立即显示
- AI 占位立即显示
- 等待确认展示
- 等待补充展示
- 完成后替换或更新 AI 消息
- 取消后状态收敛
- step_started / step_completed 状态展示
- 搜索结果数量展示
- 长任务期间 UI 不假死

### 17.5 上下文预算测试

覆盖：

- 搜索命中几千条记录时不写爆 `step_outputs_json`
- `memory.summarize` 输入超过预算时自动分块
- 分块总结结果可继续最终归纳
- 日志不输出完整 payload

### 17.6 Replay Test

除单元测试和 fake planner 测试外，需要增加真实输入回放测试。

Replay Test 输入：

- 脱敏后的真实用户输入。
- 当前本地时间。
- 模拟联系人索引。
- 模拟聊天摘要索引。
- 期望 plan shape。

示例：

```json
{
  "input": "我和 test1 和 test3 聊过什么？",
  "now": "2026-04-21T10:00:00",
  "expected": {
    "actions": ["contact.resolve", "memory.search", "memory.summarize"],
    "time_scope": "all_history",
    "participant_match": "any",
    "requires_clarification": false
  }
}
```

Replay Test 目标：

- 捕获 planner prompt 调整导致的 plan 漂移。
- 捕获模型升级或量化模型差异。
- 验证常见真实表达不会退化成错误追问。
- 验证多 action 组合的稳定性。

回放结果应记录：

```text
input_id
model
planner_prompt_version
plan_version
actions
validation_result
diff_from_expected
```

Replay 测试数据必须脱敏，不得保存真实聊天明文。

## 18. 推荐落地顺序

1. 定义 plan、step、action result 数据结构。
2. 定义每个 atomic action 的 Pydantic input / output model。
3. 新增 `ai_action_plans` 和临时结果存储。
4. 实现 plan lifecycle versioning。
5. 重写 planner prompt 和 JSON schema，让模型输出 `steps`。
6. 实现 validator 和内部自纠错重试。
7. 实现 normalizer 和基础 optimizer。
8. 实现 resource manager 和预算校验。
9. 实现 atomic action registry。
10. 实现 executor、引用解析和强类型校验。
11. 实现大型 output 引用传值。
12. 实现执行事件并接入 AI 助手 UI。
13. 实现 `contact.resolve`。
14. 实现 `memory.search`。
15. 实现 `memory.summarize`。
16. 实现语义缓存。
17. 实现 `message.draft`、`user.confirm`、disabled `message.send`。
18. 删除旧单 action 填槽逻辑。
19. 补齐单测、回放测试和日志。

## 19. 建议文件拆分

建议不要继续把所有逻辑塞进 `ai_action_workflow.py`。

推荐结构：

```text
client/managers/ai_action_workflow.py
client/managers/ai_action_planner.py
client/managers/ai_action_normalizer.py
client/managers/ai_action_optimizer.py
client/managers/ai_action_executor.py
client/managers/ai_action_registry.py
client/managers/ai_action_resource_manager.py
client/managers/ai_action_permission_policy.py
client/managers/ai_action_types.py
client/managers/ai_action_events.py
client/managers/ai_action_cache.py
client/storage/ai_action_plan_store.py
client/storage/ai_action_temp_result_store.py
client/tests/test_ai_action_workflow.py
client/tests/test_ai_action_executor.py
client/tests/test_ai_action_registry.py
client/tests/test_ai_action_replay.py
```

职责：

- `ai_action_workflow.py`：入口编排，连接 UI、planner、executor、store。
- `ai_action_planner.py`：模型请求、prompt、JSON 解析。
- `ai_action_normalizer.py`：确定性 plan 补全、规范化和安全策略插入。
- `ai_action_optimizer.py`：组合级执行优化。
- `ai_action_executor.py`：step 调度、引用解析、状态推进。
- `ai_action_registry.py`：原子 action 注册和实现。
- `ai_action_resource_manager.py`：plan 和 step 的资源预算控制。
- `ai_action_permission_policy.py`：联系人、群组、E2EE、敏感标签等权限作用域判断。
- `ai_action_types.py`：数据结构和枚举。
- `ai_action_events.py`：executor 到 UI 的状态事件定义。
- `ai_action_cache.py`：跨 step 和跨 plan 的语义缓存。
- `ai_action_plan_store.py`：plan 状态持久化。
- `ai_action_temp_result_store.py`：大型 payload 临时结果引用存储。

## 20. 非目标

本设计不要求首期实现：

- 完整并发 DAG 执行。
- 任意表达式语言。
- 真正发送消息。
- 真正添加好友。
- 真正发布朋友圈。
- 自动补偿已执行的副作用 action。
- 外部 Provider 读取 E2EE 明文。
- 把搜索到的聊天记录全文直接输出给用户。
- 为旧 action workflow 维护长期兼容分支。

## 21. 验收标准

重构完成后，以下用户输入应符合预期：

```text
我和 test1 聊过什么？
```

- 查询全部历史。
- 不追问时间。
- 输出总结。

```text
我和 test1 和 test3 聊过什么？
```

- 解析两个联系人。
- 多联系人查询。
- 不追问“查哪一个”。

```text
昨天我和 test1 聊了什么？
```

- 使用昨天的时间范围。
- 输出总结。

```text
帮我总结昨天和 test1 聊的内容，然后发给 test3
```

- 查询、总结、生成草稿。
- 发送前请求确认。
- 未确认前不发送。

```text
小王有多个联系人
```

- 只对“小王”这个具体歧义项追问。
- 用户选择后继续原 plan。
- 已完成 step 不重跑。

额外工程验收：

- 大型搜索结果不直接写入 `step_outputs_json`。
- 每个 action input / output 都经过强类型校验。
- Planner 非法输出会经过有限自纠错。
- UI 能展示 step 级别状态。
- 模型上下文超过预算时走分块总结。
- Plan 每次结构变化都产生可追踪版本。
- Normalizer 能确定性插入必要确认和依赖。
- Resource manager 能阻止超大 plan 直接执行。
- Step 失败支持有限重试或明确降级。
- Optimizer 改写 plan 时不改变用户目标和安全等级。
- Semantic cache 能避免重复分块总结。
- 每个 action 都声明平台级执行边界。
- Executor 能统一执行通用护栏。
- 高风险 action 具备单目标、preview、幂等和重新确认限制。
- UI 能展示结构化 explanation，但不展示完整推理链。
- Permission policy 能按联系人、群组、E2EE、敏感标签拒绝越权查询。
- 超过 step 或联系人上限时进入 clarification。
- Replay Test 能覆盖真实输入表达的 plan shape 稳定性。

## 22. 总结

AssistIM AI 助手的动作系统应从“业务大 action”重构为“原子 action plan”。

新的核心边界是：

- 模型理解用户意图并生成结构化 plan。
- 系统校验、执行、暂停、恢复和审计。
- 原子 action 只做一件事。
- 组合能力来自 plan，而不是新增更大的 action。

这能让后续新增能力时只扩展 action registry，而不是不断堆叠复杂的业务 workflow。
