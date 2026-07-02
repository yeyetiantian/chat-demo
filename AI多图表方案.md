# 多图表方案分析

## 方案 E：Agent 多轮内循环

### 核心思路

不改 executor、不改 SSE 协议、不改前端。只在 `_do_agent_pipeline` 内部加一个循环：

```
_do_agent_pipeline("多维度分析报警数据")
  │
  ├── 第 1 轮: thread.ask("多维度分析报警数据")
  │   └── AI 返回结果 + 追问建议
  │
  ├── 第 2 轮: thread.ask("按车型统计报警数量")
  │   └── AI 返回 DataFrame + chart
  │
  ├── 第 3 轮: thread.ask("按规则类型查看分布")
  │   └── AI 返回 DataFrame + chart
  │
  ├── ...（取追问列表的前 N 个，逐个 ask）
  │
  └── 返回: { multi_chart: true, charts: [chart1, chart2, ...] }
```

### 为什么可行

`thread.ask()` 本来就是多轮对话——每次 ask 都继承上下文。第一轮问完后，后面的每个 ask 直接用现成的 agent 和 schema 上下文，**不需要重新初始化**。所以每一轮的耗时 ≈ 仅 LLM 推理时间（3-5 秒），比重新开一个 SSE 连接快得多。

### 改动位置

**`chat.py` `_do_agent_pipeline`：**

```python
def _do_agent_pipeline(query, session_id):
    session_id, thread, _writer = _get_or_create_thread(session_id)
    
    # 首次查询
    trace.set_phase("ask")
    thread.ask(query)
    answer = thread.text()
    df = thread.df()
    
    if df is None or df.empty:
        return { "message": answer or "未能查询到数据" }
    
    # 生成图表
    chart_type = _infer_chart_type(df, query)
    chart_spec = thread.plot(f"{chart_type} chart")
    
    # 生成追问建议 + 字段映射
    fi = _generate_followup_questions(thread, df, query, answer)
    
    # ★ 多维度模式：自动执行追问，收集多个图表
    charts_data = [{
        "chart_type": chart_type,
        "chart_spec": chart_spec,
        "data": _dataframe_to_response(df),
        "config": { "rowFields": fi["rowFields"], ... },
    }]
    
    is_multi = any(kw in query.lower() for kw in ["多维度", "多角度", "全面", "多个", "各方面"])
    if is_multi and len(fi["questions"]) >= 2:
        for fq in fi["questions"][:5]:  # 最多额外 5 个
            thread.ask(fq)
            sub_df = thread.df()
            if sub_df is not None and not sub_df.empty:
                sub_type = _infer_chart_type(sub_df, fq)
                sub_spec = thread.plot(f"{sub_type} chart")
                charts_data.append({
                    "chart_type": sub_type,
                    "chart_spec": sub_spec,
                    "data": _dataframe_to_response(sub_df),
                    "query": fq,
                })
    
    return {
        "multi_chart": True,
        "charts": charts_data,
        "total": len(charts_data),
    }
```

### SSE event_generator 改动

```python
# 不再是 yield 一次 result，而是逐个 yield
result = await future
if result.get("multi_chart"):
    for i, chart in enumerate(result["charts"]):
        yield _sse_event("status", {
            "phase": "multi",
            "message": f"📊 正在生成第 {i+1}/{result['total']} 个图表...",
            "current": i+1, "total": result["total"],
        })
        yield _sse_event("result", chart)
    # 最后发送汇总
    yield _sse_event("result", { "multi_summary": True, "total": result["total"] })
else:
    yield _sse_event("result", result)
```

### 改动清单

| 文件 | 改动 | 行数 |
|------|------|------|
| `chat.py` `_do_agent_pipeline` | 首次查询后循环执行追问 | ~25 |
| `chat.py` `event_generator` | 支持 yield 多个 result | ~15 |
| `chat.ts` SSE handler | 展示多图表消息 | ~20 |
| `ChatPage.vue` | 多图表网格展示 + 全部保存 | ~80 |
| **总计** | | **~140 行** |

### 优点

- **真正的"一次性输出"**：一条 SSE 连接、一次 `_do_agent_pipeline` 调用
- **快**：后面的追问复用已有 agent 上下文，不用重新初始化
- **安全**：后端控制循环，不依赖前端多次请求
- **不改 executor**：不改 databao 内部的 agent 逻辑
- **不改 API 端点**：不新增接口
- **兼容所有 LLM**：只用了 `thread.ask()`，支持 tool calling 和纯文本都能跑
