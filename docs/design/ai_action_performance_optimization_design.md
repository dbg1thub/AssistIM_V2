# AI Action Workflow 性能优化设计

## 1. 背景

AI Action Workflow 已经具备 Planner、Normalizer、ResourceManager、Optimizer、Executor、PlanStore 等基础模块。当前性能瓶颈主要来自三类成本：

- Planner 本地模型调用耗时高，尤其是简单读取类问题也要等待完整规划。
- memory.search 和 memory.summarize 可能处理过多上下文，导致 IO、token 和总结延迟上升。
- 重复的联系人解析、检索和总结没有形成稳定复用。

本设计只讨论性能优化，不改变安全边界和用户确认语义。

## 2. 设计原则

1. 不降低准确性和安全性。
2. 不写本地语义兜底代码。
3. 不用规则层替代 Planner 理解自然语言。
4. 所有模型输出都必须经过 Normalizer、ResourceManager、PermissionPolicy。
5. 写操作必须确认，读取操作不得要求确认。
6. Optimizer 只能做语义等价变换。
7. 低置信、不完整、冲突或非法 plan 必须 fail closed。

这里的 fail closed 指：

- 不构造替代业务 plan。
- 不自动猜用户意图。
- 不展示错误确认。
- 必要时回到普通聊天路径，或要求用户补充明确参数。

## 3. 非目标

本阶段不做以下事情：

- 不做基于正则或关键词的本地自然语言解析。
- 不做“用户问历史时本地直接抽联系人并构造 memory plan”的兜底。
- 不让 Fast Path 处理任何写操作。
- 不让 Router 生成可执行业务 plan。
- 不为了性能跳过确认、权限、资源限制或 plan 校验。

## 4. 当前基线流程

```text
User Input
-> Planner
-> Normalizer
-> ResourceManager
-> Optimizer
-> PlanStore
-> Executor
-> UI / Streamed Chat
```

当前流程的主要问题：

- Optimizer 在 ResourceManager 之后运行，纯去重优化无法帮助资源检查通过。
- Planner 是简单读取类任务的主要延迟来源。
- memory.search 默认可能拉取较多结果，summarize 也缺少分层和 early stop。
- contact.resolve、memory.search、memory.summarize 缺少版本化缓存。

## 5. 目标流程

建议调整为：

```text
User Input
-> Planner
-> Normalizer
-> Safe Optimizer
-> ResourceManager
-> PlanStore
-> Executor
-> UI / Streamed Chat
```

说明：

- Safe Optimizer 放在 ResourceManager 前，只允许做语义等价压缩。
- ResourceManager 仍然是执行前硬限制。
- Executor 继续逐步持久化状态，保证暂停、恢复和失败可解释。

## 6. 优化分层

### 6.1 Phase 1: 观测和 Planner 成本控制

先补齐分段性能指标：

```text
planner_ms
normalizer_ms
optimizer_ms
resource_check_ms
executor_ms
contact_resolve_ms
memory_search_ms
memory_summarize_ms
plan_total_ms
```

同时记录：

- planner 输入字符数。
- planner 输出字符数。
- step 数。
- memory search 结果数量。
- summarize 输入字符数。
- cache hit/miss。

Planner 成本控制：

- 精简 Planner prompt。
- 缩短输出 schema 中非必要字段。
- 降低简单 plan 的 max_tokens。
- 明确读取类任务不需要 user.confirm。

### 6.2 Phase 2: Safe Optimizer

Optimizer 只处理结构性、语义等价优化：

- 合并相同参数的 `contact.resolve`。
- 合并相同参数的 `memory.search`。
- 清理不可达 step。
- 规范化重复 depends。
- 修复重复 step id。

不允许 Optimizer 做：

- 根据用户文本补联系人。
- 根据关键词推断 action。
- 把非法 confirm plan 改写成读取 plan。
- 删除写操作确认。
- 改变 final 输出来源语义。

### 6.3 Phase 3: Summary-first Memory Search

读取历史时优先检索 summary，再按需要升级到 message 级检索。

```text
summary search
-> enough?
   -> yes: return summary refs
   -> no: message search
-> merge refs
```

`enough` 的判断必须只依赖检索结果质量，不依赖本地解析用户自然语言：

- 命中数量。
- 命中总字符数。
- 结果覆盖的 session/date 数。
- 结果是否为空。
- 检索层返回的 score。

message search 只在 summary 不足时触发。

### 6.4 Phase 4: Memory Summarize 分层

总结采用 Top-K + chunk + final 的分层策略：

```text
ranked refs
-> summarize top-k
-> sufficient?
   -> yes: return
   -> no: summarize chunks
-> summarize partial summaries
```

Early stop 只能基于中间结果和资源预算：

- 已覆盖足够多不同 session/date。
- 已达到 token/字符预算。
- partial summary 已包含主要 evidence。
- 后续 chunk 分数低于阈值。

### 6.5 Phase 5: 版本化缓存

缓存分三层：

| 层级 | 内容 | Key 必须包含 |
| --- | --- | --- |
| L1 | contact.resolve | query、联系人索引版本 |
| L2 | memory.search | participants、time_scope、keywords、index_version、search_version |
| L3 | memory.summarize | source ids/checksum、question、prompt_version、model_id |

缓存原则：

- 没有 version 禁止命中。
- summarize 缓存不能只按联系人和时间命中。
- 写操作不使用结果缓存跳过确认。
- cache hit 也必须写入 plan step result，方便 UI 和审计。

### 6.6 Phase 6: 可选 Lightweight Router

Router 是最后阶段，不是第一阶段。

Router 只允许做分类：

```json
{
  "route": "chat | action_candidate | unknown",
  "confidence": 0.0,
  "reason": "short diagnostic text"
}
```

Router 不允许：

- 生成 executable plan。
- 抽取联系人并构造 memory plan。
- 处理写操作。
- 输出 user.confirm。
- 替代 Normalizer 或 ResourceManager。

只有在满足以下条件时才可以考虑启用：

- 有 golden corpus。
- Router 结果和完整 Planner 对比通过。
- 低置信度直接走完整 Planner。
- feature flag 默认关闭或灰度开启。

## 7. 安全不变量

任何优化都必须满足：

- `message.send` 必须依赖 `user.confirm`。
- `user.confirm` 必须服务于明确写操作。
- 没有写操作依赖的 `user.confirm` 是非法 plan。
- 读取类 plan 不能进入 `waiting_confirmation`。
- 缺少目标或内容的发送确认必须进入 clarification，不得生成“目标对象”确认。
- Optimizer 输出必须再次通过 ResourceManager。
- Executor 必须在每个 step 后持久化状态。

## 8. 推荐落地顺序

1. 增加性能指标和日志。
2. 调整流程顺序，让 Safe Optimizer 在 ResourceManager 前运行。
3. 扩展 Safe Optimizer 的确定性优化。
4. 实现 Summary-first memory search。
5. 实现分层 summarize。
6. 实现版本化缓存。
7. 在测试集充分后评估 Router。

## 9. 测试要求

每个阶段都需要对应测试：

- Planner prompt 不把读取类任务引导到确认。
- 非法 `user.confirm` plan 被拒绝。
- Optimizer 不改变 final source。
- Optimizer 不删除写操作确认。
- ResourceManager 仍能拒绝过多 step、过多联系人、多个写操作。
- Summary-first 在 summary 足够时不触发 message search。
- Summary-first 在 summary 不足时触发 message search。
- 缓存 version 变化后必须 miss。
- UI 不重复展示 pending response_text。

## 10. 结论

性能优化应从确定性、可测量、不会改变语义的部分开始：

```text
观测
-> Planner 成本控制
-> Safe Optimizer
-> Summary-first
-> 分层 Summarize
-> 版本化缓存
-> 可选 Router
```

Router 和 Fast Path 不应作为第一阶段。当前更稳的收益来源是减少 Planner 输出成本、减少重复 step、减少 memory search 和 summarize 的无效工作。
