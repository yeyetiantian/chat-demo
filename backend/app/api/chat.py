"""
AI 对话 API — Chat Demo 全链路驱动

管线:
  用户输入 → agent.thread().ask() → (DataFrame + text)
  → thread.plot() → Plotly/Vega-Lite 图表
  → 返回 { answer, chart_spec, data, html }

多轮对话: thread 对象内部维护上下文，后续追问自动继承历史。

全链路追踪: 通过 trace_service.install_tracing() 拦截 LangChain 的
  ChatOpenAI._generate 与 BaseTool.invoke，完整记录每次 LLM 调用
  (完整 prompt messages + 原始响应) 与工具调用 (SQL 执行等) 的过程。
"""
import sys
import os
import json
import time
import asyncio
import queue
import io
import uuid
import pandas as pd
from typing import Dict
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from ..models.schema import ChatQueryRequest, ChatQueryResponse, ChartType
from ..utils.logger import get_logger
from ..services.trace_service import install_tracing, start_trace, end_trace

# ---------------------------------------------------------------------------
# Snowflake mock — Chat Demo 导入 snowflake.connector 但我们只用 DuckDB
# ---------------------------------------------------------------------------
if "snowflake" not in sys.modules:
    _snowflake = type(sys)("snowflake")
    _snowflake_connector = type(sys)("snowflake.connector")
    _snowflake_network = type(sys)("snowflake.connector.network")
    _snowflake_network.SNOWFLAKE_HOST_SUFFIX = ".snowflakecomputing.com"
    sys.modules["snowflake"] = _snowflake
    sys.modules["snowflake.connector"] = _snowflake_connector
    sys.modules["snowflake.connector.network"] = _snowflake_network

router = APIRouter(prefix="/api/chat", tags=["AI对话"])
logger = get_logger("api.chat")

# 模块加载时安装 trace monkey-patch（幂等，仅安装一次）
install_tracing()

# ---------------------------------------------------------------------------
# 流式 Writer — 捕获 Chat Demo 内部实时日志，推送给 SSE
# ---------------------------------------------------------------------------
class _StreamingWriter(io.StringIO):
    """线程安全的 writer，Chat Demo 内部 write() 调用被捕获到队列中"""

    def __init__(self):
        super().__init__()
        self._queue: queue.Queue = queue.Queue()

    def write(self, s: str) -> int:
        ret = super().write(s)
        text = s.strip()
        if text and len(text) > 2:  # 忽略过短的无意义输出
            self._queue.put(text)
        return ret

    def get_events(self, timeout: float = 0.3) -> list:
        """非阻塞获取积压事件"""
        events = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    def get_one(self, timeout: float = 0.5) -> str | None:
        """阻塞获取单条事件"""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None


# ---------------------------------------------------------------------------
# 模块级单例 — Chat Demo agent + 多轮对话线程池
# ---------------------------------------------------------------------------
_agent = None          # bao.agent 实例
_conn = None           # DuckDB 连接
_threads: Dict[str, dict] = {}  # session_id → {"thread": ..., "writer": ...}


def _get_duckdb_connection():
    """获取只读 DuckDB 连接（Chat Demo agent 需要 DuckDBPyConnection）"""
    global _conn
    if _conn is None:
        import duckdb
        from ..config import DUCKDB_PATH
        _conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        logger.info("🔌 DuckDB 只读连接已建立 | %s", DUCKDB_PATH)
    return _conn


_NO_KEY_MSG = (
    "未配置 AI API Key。请在可执行文件同目录、或当前工作目录下创建 .env 文件，内容示例：\n"
    "  DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
    "  DEEPSEEK_BASE_URL=https://api.deepseek.com/v1\n"
    "  （或设置 OPENAI_API_KEY 环境变量）\n"
    "  获取 Key: https://platform.deepseek.com/api_keys"
)


def _get_agent():
    """延迟初始化 Chat Demo agent 单例"""
    global _agent
    if _agent is None:
        import databao.agent as bao
        from ..config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

        if not DEEPSEEK_API_KEY and not os.getenv("OPENAI_API_KEY"):
            msg = f"未配置任何 API Key，AI 对话功能不可用\n{_NO_KEY_MSG}"
            logger.error(msg)
            raise RuntimeError(msg)

        # LLM 配置 — 使用 DeepSeek (OpenAI 兼容协议)
        model_name = "deepseek-chat" if DEEPSEEK_API_KEY else "gpt-4o-mini"
        llm_kwargs = {
            "name": model_name,
            "temperature": 0.1,
        }
        # DeepSeek 需要指定 api_base_url + 关闭 Responses API
        if DEEPSEEK_API_KEY:
            llm_kwargs["api_base_url"] = DEEPSEEK_BASE_URL
            llm_kwargs["use_responses_api"] = False  # DeepSeek 只支持 /chat/completions
        try:
            llm_config = bao.LLMConfig(**llm_kwargs)
        except Exception as e:
            msg = f"LLMConfig 初始化失败（API Key 缺失或不合法）: {e}\n{_NO_KEY_MSG}"
            logger.error(msg)
            raise RuntimeError(msg) from e
        logger.info("🤖 Chat Demo LLMConfig | model=%s | base_url=%s",
                    model_name, DEEPSEEK_BASE_URL if DEEPSEEK_API_KEY else "(default)")

        # 数据域 — 绑定 DuckDB
        domain = bao.domain()
        domain.add_db(_get_duckdb_connection())
        logger.info("📊 Chat Demo domain | DuckDB 已绑定")

        # 创建 agent（提高递归限制避免 LangGraph 超限）
        from databao.agent.configs.agent import AgentConfig
        agent_config = AgentConfig(recursion_limit=200)
        try:
            _agent = bao.agent(domain, name="datapivot", llm_config=llm_config, agent_config=agent_config)
        except Exception as e:
            if "credentials" in str(e).lower() or "api_key" in str(e).lower():
                msg = f"Chat Demo agent 初始化失败: {e}\n{_NO_KEY_MSG}"
                logger.error(msg)
                raise RuntimeError(msg) from e
            raise
        logger.info("✅ Chat Demo agent 初始化完成 | recursion_limit=200")

    return _agent


def _get_or_create_thread(session_id: str | None) -> tuple:
    """获取或创建对话线程（多轮记忆），返回 (session_id, thread, writer)"""
    sid = session_id or str(uuid.uuid4())[:8]
    if sid not in _threads:
        agent = _get_agent()
        writer = _StreamingWriter()
        thread = agent.thread(writer=writer)
        _threads[sid] = {"thread": thread, "writer": writer}
        logger.info("🧵 新对话线程 | session=%s", sid)
    entry = _threads[sid]
    return sid, entry["thread"], entry["writer"]


# ---------------------------------------------------------------------------
# 图表类型推断
# ---------------------------------------------------------------------------
def _infer_chart_type(df: pd.DataFrame, question: str) -> str:
    """根据数据特征和问题推断图表类型"""
    q = question.lower()
    # 用户意图
    if any(k in q for k in ["趋势", "时间", "变化", "走势"]):
        return "line"
    if any(k in q for k in ["占比", "比例", "百分比", "分布"]):
        return "pie" if len(df) <= 10 else "bar"
    if any(k in q for k in ["散点", "相关"]):
        return "scatter"
    # 数据驱动
    time_cols = [c for c in df.columns if any(t in str(c).lower() for t in ["时间", "time"])]
    num_cols = [c for c in df.columns if df[c].dtype in ('float64', 'int64')]
    if time_cols and num_cols:
        return "line"
    if len(df) <= 6 and len(num_cols) == 1 and len(df.columns) == 2:
        return "pie"
    return "bar"


def _sanitize_value(v):
    """递归转换 numpy 类型为 Python 原生类型"""
    import numpy as np
    if isinstance(v, (np.ndarray,)):
        return [_sanitize_value(x) for x in v.tolist()]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, dict):
        return {k: _sanitize_value(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize_value(x) for x in v]
    if pd.isna(v):
        return None
    return v


def _dataframe_to_response(df: pd.DataFrame) -> dict:
    """将 DataFrame 转为前端可用格式"""
    # 日期列转为字符串 (JSON 不支持 Timestamp)
    for col in df.columns:
        if df[col].dtype == 'datetime64[ns]' or 'timestamp' in str(df[col].dtype):
            df = df.copy()
            df[col] = df[col].astype(str)
    # 递归清理所有 numpy 类型，确保 JSON 可序列化
    rows = [_sanitize_value(row) for row in df.to_dict(orient="records")]
    return {
        "columns": list(df.columns),
        "rows": rows,
    }


def _sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """清洗 DataFrame：将嵌套的 list/ndarray 列展开为多行，确保 plot 可用"""
    import numpy as np

    # 检查是否有包含数组的列
    array_cols = []
    for col in df.columns:
        if df[col].dtype == 'object' and len(df) > 0:
            sample = df[col].iloc[0]
            if isinstance(sample, (list, np.ndarray)):
                array_cols.append(col)

    if not array_cols:
        return df

    # 如果有数组列，尝试 explode
    try:
        # 先将 ndarray 转为 list
        for col in array_cols:
            df = df.copy()
            df[col] = df[col].apply(lambda x: x.tolist() if isinstance(x, np.ndarray) else x)
        # explode 第一个数组列
        return df.explode(array_cols[0], ignore_index=True)
    except Exception:
        pass
    return df


# ---------------------------------------------------------------------------
# POST /api/chat/query
# ---------------------------------------------------------------------------
@router.post("/query", response_model=ChatQueryResponse)
async def chat_query(request: ChatQueryRequest):
    """
    自然语言查询 → Chat Demo agent → 图表

    Chat Demo agent 管线:
    1. thread.ask(question) → 理解问题、探索 schema、生成 SQL、执行查询
    2. thread.plot(description) → 智能选择图表类型、生成 Vega-Lite spec
    3. 返回 { answer, chart_spec, data }
    """
    query = request.query
    context = request.context or {}
    session_id = context.get("session_id")

    logger.info("💬 查询 [session=%s]: %s", session_id or "new", query[:100])
    t_total = time.perf_counter()

    # ---- 全链路追踪 ----
    trace = start_trace(query=query, session_id=session_id, endpoint="query")

    try:
        # ---- Step 1: 获取对话线程 (多轮记忆) ----
        session_id, thread = _get_or_create_thread(session_id)

        # ---- Step 2: Chat Demo agent 执行查询 ----
        trace.set_phase("ask")
        t_ask = time.perf_counter()
        thread.ask(query)
        ask_ms = (time.perf_counter() - t_ask) * 1000

        # 获取文本回答与 DataFrame
        answer = thread.text()
        df = thread.df()
        logger.info("🤖 agent.ask (%.0fms) | answer=%s | df=%s",
                    ask_ms, answer[:80] if answer else "(无)", df.shape if df is not None else None)

        if df is None or df.empty:
            end_trace(trace, "success", summary={
                "answer": answer or "",
                "has_data": False,
                "duration_ask_ms": round(ask_ms, 1),
            })
            return ChatQueryResponse(
                success=True,
                message=answer or "未能从数据库查询到相关数据，请尝试换个问法。",
            )

        # ---- Step 3: 图表生成 ----
        chart_type_str = _infer_chart_type(df, query)
        chart_type = ChartType(chart_type_str)
        chart_spec = None

        try:
            trace.set_phase("plot")
            chart_desc = f"{chart_type_str} chart"
            if "时间" in query or "趋势" in query:
                chart_desc = "line chart showing trend over time"
            elif "占比" in query or "比例" in query:
                chart_desc = "pie chart showing proportions"
            elif "比较" in query or "统计" in query or "数量" in query:
                chart_desc = "bar chart"

            t_plot = time.perf_counter()
            plot = thread.plot(chart_desc)
            chart_spec = plot.code  # Vega-Lite spec
            logger.info("🎨 agent.plot (%.0fms) | vega=%s",
                        (time.perf_counter() - t_plot) * 1000,
                        "yes" if chart_spec else "no")
        except Exception as plot_err:
            logger.warning("⚠️  plot 失败（降级返回纯数据）: %s", plot_err)

        # ---- Step 4: 组装响应 ----
        data_payload = _dataframe_to_response(df)
        total_ms = (time.perf_counter() - t_total) * 1000
        logger.info("✅ 完成 (%.0fms) | chart=%s rows=%d cols=%s | session=%s",
                    total_ms, chart_type_str, len(df), list(df.columns), session_id)

        end_trace(trace, "success", summary={
            "answer": (answer or "")[:500],
            "has_data": True,
            "data_shape": [len(df), len(df.columns)],
            "chart_type": chart_type_str,
            "has_chart_spec": chart_spec is not None,
            "duration_ask_ms": round(ask_ms, 1),
            "duration_total_ms": round(total_ms, 1),
        })

        return ChatQueryResponse(
            success=True,
            chart_type=chart_type,
            config={
                "dimensions": [c for c in df.columns if df[c].dtype == 'object'],
                "measures": [c for c in df.columns if df[c].dtype in ('float64', 'int64')],
                "aggregation": "auto",
                "session_id": session_id,
            },
            sql="-- 由 Chat Demo agent 自动生成",
            message=answer,
            data={
                "type": chart_type_str,
                "data": data_payload["rows"],
                "columns": data_payload["columns"],
                "dimensions": [],
                "measures": [],
                "chart_spec": chart_spec,
            },
            grounding="GROUNDED",
        )

    except Exception as e:
        total_ms = (time.perf_counter() - t_total) * 1000
        logger.error("❌ 失败 (%.0fms): %s", total_ms, str(e))
        end_trace(trace, "error", error=str(e), summary={
            "duration_total_ms": round(total_ms, 1),
        })
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/chat/threads — 查看活跃会话
# ---------------------------------------------------------------------------
@router.get("/threads")
async def list_threads():
    return {
        "success": True,
        "active_sessions": len(_threads),
        "sessions": list(_threads.keys()),
    }


@router.get("/patterns")
async def get_query_patterns():
    return {
        "success": True,
        "patterns": [
            "按车型统计报警数量",
            "按规则类型查看平均持续时间",
            "按人员统计任务数量分布",
            "查看各时间段的报警趋势",
            "统计各车型的报警占比",
            "查看过去一周每天的报警数量",
        ],
    }


# ---------------------------------------------------------------------------
# POST /api/chat/stream — SSE 流式对话（前端实时看到思考过程）
# ---------------------------------------------------------------------------
def _sse_event(event: str, data: str | dict) -> str:
    """构建 SSE 事件字符串"""
    if isinstance(data, dict):
        data = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {data}\n\n"


def _fix_timedelta_columns(df: pd.DataFrame) -> pd.DataFrame:
    """将 timedelta64 列转为秒数（数值），否则 Altair/Vega-Lite 无法渲染"""
    import numpy as np
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == 'timedelta64[ns]' or 'timedelta' in str(df[col].dtype):
            df[col] = df[col].dt.total_seconds()
            logger.info("🔧 timedelta列转换 | %s → 秒数(float64)", col)
    return df


def _generate_followup_questions(thread, df: pd.DataFrame, query: str, answer: str) -> list:
    """基于当前对话上下文，生成 3 个后续追问建议"""
    try:
        cols = ", ".join(df.columns[:6])
        thread.ask(
            f"用户刚才问了：「{query}」。你的回答摘要：{answer[:300]}。"
            f"当前数据表包含字段：{cols}。"
            f"请生成3个用户可能感兴趣的相关数据统计问题，要求简洁、可直接输入查询。"
            f"只输出3行，每行以' - '开头，不要其他内容。"
        )
        text = thread.text()
        questions = []
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("-"):
                q = stripped.lstrip("- ").strip()
                if q and len(q) < 60:
                    questions.append(q)
        return questions[:3] if len(questions) >= 2 else []
    except Exception as e:
        logger.warning("⚠️ 生成追问失败: %s", e)
        return []


def _do_agent_pipeline(query: str, session_id: str | None) -> dict:
    """在后台线程中执行 Chat Demo agent 全链路，返回结果 dict"""
    # ---- 全链路追踪 (SSE 模式) ----
    trace = start_trace(query=query, session_id=session_id, endpoint="stream")

    try:
        session_id, thread, _writer = _get_or_create_thread(session_id)

        # Step 1: ask
        trace.set_phase("ask")
        thread.ask(query)
        answer = thread.text()
        df = thread.df()

        if df is None or df.empty:
            end_trace(trace, "success", summary={
                "answer": answer or "",
                "has_data": False,
            })
            return {
                "success": True,
                "message": answer or "未能从数据库查询到相关数据。",
                "session_id": session_id,
            }

        # Step 1.5: 修复 timedelta 列（Altair 不支持）
        df = _fix_timedelta_columns(df)

        # Step 2: chart type
        chart_type_str = _infer_chart_type(df, query)
        chart_spec = None
        meta_steps = []

        # Step 3: plot
        try:
            trace.set_phase("plot")
            chart_desc = f"{chart_type_str} chart"
            if "时间" in query or "趋势" in query:
                chart_desc = "line chart showing trend over time"
            elif "占比" in query or "比例" in query:
                chart_desc = "pie chart showing proportions"

            plot = thread.plot(chart_desc)
            chart_spec = plot.code
        except Exception as plot_err:
            logger.warning("⚠️  plot 失败: %s", plot_err)

        # Step 3.5: 生成后续追问建议
        trace.set_phase("followup")
        followup_questions = _generate_followup_questions(thread, df, query, answer)

        # Step 4: build response
        data_payload = _dataframe_to_response(df)

        end_trace(trace, "success", summary={
            "answer": (answer or "")[:500],
            "has_data": True,
            "data_shape": [len(df), len(df.columns)],
            "chart_type": chart_type_str,
            "has_chart_spec": chart_spec is not None,
        })

        return {
            "success": True,
            "chart_type": chart_type_str,
            "config": {
                "dimensions": [c for c in df.columns if df[c].dtype == 'object'],
                "measures": [c for c in df.columns if df[c].dtype in ('float64', 'int64')],
                "aggregation": "auto",
                "session_id": session_id,
            },
            "sql": "-- 由 Chat Demo agent 自动生成",
            "message": answer,
            "data": {
                "type": chart_type_str,
                "data": data_payload["rows"],
                "columns": data_payload["columns"],
                "dimensions": [],
                "measures": [],
                "chart_spec": chart_spec,
            },
            "grounding": "GROUNDED",
            "thinking_steps": meta_steps,
            "followup_questions": followup_questions,
        }

    except Exception as e:
        logger.error("❌ _do_agent_pipeline 失败: %s", e)
        end_trace(trace, "error", error=str(e))
        raise


@router.post("/stream")
async def chat_stream(request: ChatQueryRequest):
    """
    SSE 流式对话 — 实时推送思考过程

    事件类型:
      - status:  阶段状态消息
      - thinking: 思考步骤
      - result:  最终结果 (完整 ChatQueryResponse)
      - error:   错误信息
      - done:    流结束
    """
    query = request.query
    context = request.context or {}
    session_id = context.get("session_id")

    logger.info("💬 SSE查询 [session=%s]: %s", session_id or "new", query[:100])

    def _classify_chunk(chunk: str) -> str:
        """分类 writer 输出块: text | tool_call | tool_output | sql | df | header | footer"""
        stripped = chunk.strip()
        if stripped.startswith("[tool_call:") or stripped.startswith("[tool_call_output:"):
            return "tool"
        if stripped.startswith("[df:"):
            return "df"
        if stripped.startswith("======== <THINKING> ========"):
            return "header"
        if stripped.startswith("======== </THINKING> ========"):
            return "footer"
        if stripped.startswith("```"):
            return "sql"
        return "text"

    def _should_flush(buf_type: str, new_type: str, buf: list) -> bool:
        """判断是否应刷新缓冲区"""
        if not buf:
            return False
        # 不同类型立即刷新
        if new_type != buf_type:
            return True
        # 同类型：tool/df/sql 每条独立发送；text 累积到换行或句号
        if buf_type in ("tool", "df", "sql", "header", "footer"):
            return True
        # text: 累积到方便阅读的长度或遇到句号
        combined = "".join(buf)
        if len(combined) > 80 or combined.rstrip().endswith((".", "。", ":", "：", "\n")):
            return True
        return False

    async def event_generator():
        t_start = time.perf_counter()

        try:
            # 预先初始化 thread+writer，确保 writer 可在主线程轮询
            sid, _thread, writer = _get_or_create_thread(session_id)

            # 发送初始状态 — 每次请求都从这里开始
            yield _sse_event("status", {"phase": "start", "message": "🔍 正在分析您的查询..."})

            # 在 executor 中执行阻塞的 agent 管线
            loop = asyncio.get_event_loop()
            future = loop.run_in_executor(None, _do_agent_pipeline, query, session_id)

            # 轮询 writer，智能分组
            buf_type = "text"
            buf: list = []
            last_yield_time = time.perf_counter()
            last_status_time = time.perf_counter()  # 定期状态推送计时器

            def flush_buffer():
                nonlocal buf_type, buf
                if not buf:
                    return None
                combined = "".join(buf).strip()
                buf = []
                if not combined:
                    return None
                if buf_type in ("tool", "df"):
                    return _sse_event("tool", {"message": combined})
                if buf_type == "sql":
                    return _sse_event("sql", {"message": combined})
                if buf_type in ("header", "footer"):
                    return None  # 忽略横线装饰
                return _sse_event("thinking", {"message": combined})

            # 阶段状态消息序列
            phase_messages = [
                (8, "📡 正在探索数据库结构..."),
                (18, "🤔 正在分析您的查询意图..."),
                (30, "⚙️  正在生成并执行 SQL 查询..."),
                (50, "📊 正在生成图表..."),
            ]
            phase_index = 0

            while not future.done():
                events = writer.get_events(timeout=0.3)
                now = time.perf_counter()

                if events:
                    for evt in events:
                        if len(evt) > 600:
                            continue  # 跳过过长的输出
                        ct = _classify_chunk(evt)
                        if _should_flush(buf_type, ct, buf):
                            ev = flush_buffer()
                            if ev:
                                yield ev
                            buf_type = ct
                        buf_type = ct
                        # 清理装饰性字符
                        clean = evt.replace("<THINKING>", "").replace("</THINKING>", "").replace("========", "").strip()
                        if clean:
                            buf.append(clean if ct == "text" else evt)
                    last_yield_time = now
                    last_status_time = now  # 有内容产出时重置状态计时器
                else:
                    # 定时刷新 text 缓冲区，让用户看到增量内容
                    if buf_type == "text" and buf and now - last_yield_time > 1.5:
                        ev = flush_buffer()
                        if ev:
                            yield ev
                        buf_type = "text"
                        last_yield_time = now

                    # 阶段状态推送 — 按耗时推进进度提示
                    elapsed = now - t_start
                    while phase_index < len(phase_messages) and elapsed >= phase_messages[phase_index][0]:
                        yield _sse_event("status", {"phase": "thinking", "message": phase_messages[phase_index][1]})
                        phase_index += 1

                    # 超过 3s 无输出时发心跳状态
                    if now - last_status_time > 3:
                        elapsed = now - t_start
                        yield _sse_event("status", {"phase": "thinking", "message": f"⏳ 处理中...({elapsed:.0f}s)"})
                        last_status_time = now

                await asyncio.sleep(0.3)

            # 刷新残留 buffer
            ev = flush_buffer()
            if ev:
                yield ev

            # 获取结果
            result = future.result()
            elapsed_ms = (time.perf_counter() - t_start) * 1000

            # 发送最终结果
            result["elapsed_ms"] = round(elapsed_ms)
            yield _sse_event("result", result)
            yield _sse_event("done", {"message": f"✅ 完成 ({elapsed_ms/1000:.1f}s)"})

            logger.info("✅ SSE完成 (%.0fms) | session=%s", elapsed_ms, session_id or "new")

        except Exception as e:
            logger.exception("❌ SSE失败")
            yield _sse_event("error", {"message": str(e)})
            yield _sse_event("done", {"message": "❌ 处理失败"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )
