# 多图表方案分析

## 当前工作流（单图表）

```
用户输入 "按车型统计报警数量"
  │
  ├─ 后端 SSE event_generator
  │   ├─ status → "正在分析..."
  │   ├─ thinking → 中间步骤
  │   ├─ result → { data, chart_spec, config, followup_questions }
  │   │                              ↑ 只是一串文本问题，未执行
  │   └─ done → 完成
  │
  └─ 前端 chatStore (sendMessage)
      ├─ 收到 result 事件
      ├─ push 一条 assistant 消息（含图表 + 追问文本）
      └─ 展示为：1 个图表 + 6 个可点击文本芯片
```

**关键观察：** `followup_questions` 现在是**文本**，前端只展示为可点击按钮。用户点一个 → 发一条新消息 → 走完整 SSE 流。

## 多图表方案的约束

### 约束 1：后端 `_do_agent_pipeline` 一次只处理一条 query
```
def _do_agent_pipeline(query, session_id):
    thread.ask(query)       ← 1 次 AI 调用
    thread.plot(desc)        ← 1 个图表
    return { chart_spec, data, followup_questions }
```
每次调用生成 1 个 query → 1 个 SQL → 1 个 DataFrame → 1 个 chart。

不能一次返回多个图表，除非：
- 修改 agent 内部行为（复杂，不同 LLM 表现不同）
- 或者调用多次 `_do_agent_pipeline`（简单，但串行执行）

### 约束 2：SSE 连接是一次性的
```
event_generator():
    future = loop.run_in_executor(None, _do_agent_pipeline, query, session_id)
    ...轮询等待...
    result = future.result()
    yield _sse_event("result", result)    ← 只 yield 一次 result
    yield _sse_event("done", ...)
```
一条 SSE 连接只能处理一个 result。要返回多个结果需要：
- 在 `_do_agent_pipeline` 内部多次 yield（但它在独立线程里跑，不能 yield）
- 或者前端对每个追问开新的 SSE 连接

### 约束 3：前端 SSE handler 只处理单条 result
```javascript
case 'result': {
    messages.value.push({         ← 只 push 一条消息
        content: answer,
        _chartData: res.data,
        _followups: res.followup_questions,  ← 文本芯片
    })
}
```
一次 SSE 流 → 一条结果 → 一个 chart。

---

## 3 个可选方案详细对比

### 方案 A：前端逐个追问

```
用户输入 "多维度分析"
  ↓ SSE #1
AI 处理第一条 → 返回 result1 + 6 条追问（文本）
  ↓
前端自动执行追问（不用用户逐个点击）:
  追问1 → SSE #2 → result1 → 图表1
  追问2 → SSE #3 → result2 → 图表2
  追问3 → SSE #4 → result3 → 图表3
  ...
  ↓
全部完成后显示 3×2 网格
```

| 维度 | 评估 |
|------|------|
| 改动量 | 后端 prompt 10 行 + 前端 ChatPage 约 80 行 |
| 风险 | 低。不改 agent、不改 API、不改 store |
| 耗时 | 6 个图表 × 3-8s = **18-48s**（串行） |
| 用户体验 | 图表逐个出现，用户等待时间长 |
| 兼容性 | 兼容所有 LLM |

**优点：** 改动最小，风险最低
**缺点：** 慢，每个追问都要完整的 AI 管线

---

### 方案 B：后端并发执行

```
用户输入 "多维度分析"
  ↓
后端收到后在 event_generator 中并发执行多个追问:
  ┌─ _do_agent_pipeline(追问1) → result1 ─┐
  ├─ _do_agent_pipeline(追问2) → result2 ─┤
  ├─ _do_agent_pipeline(追问3) → result3 ─┤ → yield 多个 result 事件
  └─ _do_agent_pipeline(追问4) → result4 ─┘
  ↓
前端收到多个 result → 逐个 push 到消息列表
```

| 维度 | 评估 |
|------|------|
| 改动量 | 后端 event_generator + 前端 SSE handler |
| 风险 | 中。需要改 SSE 协议，多个 result 事件 |
| 耗时 | 并发执行，**≈ 3-8s**（最快的一个） |
| 用户体验 | 结果一起出现，快 |
| 兼容性 | 需要前端 SSE 支持多个 result |

**优点：** 速度快，用户体验好
**缺点：** 多线程并行执行，toknen 消耗大，需要改 SSE 协议（当前只 yield 一次 result）

---

### 方案 C：AI 单次返回多 SQL

```
用户输入 "多维度分析"
  ↓
修改 agent prompt，让 AI 一次生成 6 条 SQL:
  SELECT ... → SQL1
  SELECT ... → SQL2
  ...
  ↓
工具依次执行 6 条 SQL → 6 个 DataFrame
  ↓
返回 6 个 chart
```

| 维度 | 评估 |
|------|------|
| 改动量 | 需要改 agent 底层逻辑 |
| 风险 | 高。不同 LLM 对多工具调用的支持不同 |
| 耗时 | **≈ 10-20s**（一次 AI 调用 + 6 次 SQL） |
| 用户体验 | 结果一次性返回 |
| 兼容性 | 私有 LLM（Qwen）可能不支持并行 tool_call |

**优点：** 一次 AI 调用，token 利用率高
**缺点：** 需要深入改 agent 逻辑，私有 LLM 兼容性未知，开发周期长

---

## 推荐

### 近期（当前）：方案 A

改动最小，1-2 小时可完成。痛点：慢，但可用。

### 中期（Phase 1）：方案 A + 优化

在后端缓存追问的查询结果。当用户要求多维度分析时，`_do_agent_pipeline` 内部先生成所有追问 → 用同一个 thread 对象连续 `ask()` → 收集多个 DataFrame → 一次性返回。这样从 6 次独立 SSE 降为 1 次 SSE + 6 个 result 事件。

### 长期（Phase 2）：方案 B/C

在 agent 层面支持多工具并行调用，需要深入改造 lighthouse executor。

---

## 我建议先做方案 A

改动清单：

| 改什么 | 怎么改 | 行数 |
|--------|--------|------|
| `chat.py` prompt | 多维度关键词时生成 6 个问题 | ~10 |
| `ChatPage.vue` | 收到 followup≥3 时自动逐个执行追问 | ~60 |
| `ChatPage.vue` | 添加多图表网格展示 | ~50 |
| `ChatPage.vue` | "全部保存"按钮 | ~20 |
| 无其他改动 | — | 共 **~140 行** |

要开始实现吗？
