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
import httpx
import requests
import pandas as pd
from typing import Dict
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from ..models.schema import ChatQueryRequest, ChatQueryResponse, ChartType
from ..utils.logger import get_logger
from ..services.trace_service import install_tracing, start_trace, end_trace
from ..services.chat_history_service import append_message, get_thread, list_sessions, delete_thread

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
# 私有 LLM 适配（OAuth2 token + 自定义 access_token 请求头）
# ---------------------------------------------------------------------------
_PRIVATE_LLM_TOKEN = None
_PRIVATE_LLM_TOKEN_EXPIRES = 0.0


def _refresh_private_llm_token() -> str:
    """获取/刷新私有 LLM 的 OAuth2 token"""
    global _PRIVATE_LLM_TOKEN, _PRIVATE_LLM_TOKEN_EXPIRES
    import time as _time
    from ..config import PRIVATE_LLM_TOKEN_URL, PRIVATE_LLM_CLIENT_ID, PRIVATE_LLM_CLIENT_SECRET

    if _time.time() < _PRIVATE_LLM_TOKEN_EXPIRES and _PRIVATE_LLM_TOKEN:
        return _PRIVATE_LLM_TOKEN

    # 获取新 token
    resp = requests.post(
        PRIVATE_LLM_TOKEN_URL,
        data={
            "scope": "ALL",
            "grant_type": "client_credentials",
            "client_id": PRIVATE_LLM_CLIENT_ID,
            "client_secret": PRIVATE_LLM_CLIENT_SECRET,
        },
        headers={"content-type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _PRIVATE_LLM_TOKEN = data.get("access_token")
    expires_in = data.get("expires_in", 3600)
    _PRIVATE_LLM_TOKEN_EXPIRES = _time.time() + expires_in - 60  # 提前 60 秒刷新
    logger.info("🔑 私有 LLM token 已刷新，有效期 %ds", expires_in)
    return _PRIVATE_LLM_TOKEN


def _patch_chatopenai_for_private_llm():
    """通过 monkey-patch ChatOpenAI 注入自定义 http_client，支持 access_token 请求头"""
    from ..config import PRIVATE_LLM_CLIENT_ID, LLM_PROVIDER, AI_STRICT_MODE
    if LLM_PROVIDER != "private":
        return

    import httpx
    from langchain_openai import ChatOpenAI

    # 1. patch __init__: 注入自定义 http_client（access_token 认证）
    original_init = ChatOpenAI.__init__

    def _patched_init(self, *args, **kwargs):
        custom_client = httpx.Client(
            auth=_PrivateLLMAuth(),
            headers={
                "apiTag": "V1",
                "clientRequestId": "01",
                "client_id": PRIVATE_LLM_CLIENT_ID,
            },
            timeout=httpx.Timeout(120.0, connect=15.0),
        )
        kwargs["http_client"] = custom_client
        return original_init(self, *args, **kwargs)

    ChatOpenAI.__init__ = _patched_init

class _PrivateLLMAuth(httpx.Auth):
    """httpx Auth handler：在每次请求前自动注入 access_token，并清理请求体中的不兼容参数"""

    def auth_flow(self, request: httpx.Request):
        token = _refresh_private_llm_token()
        request.headers["access_token"] = token

        # 私有 LLM 需要 tool_choice 存在但值为 "required"（而非 "auto"）
        if request.method == "POST" and request.url.path.endswith("/chat/completions"):
            try:
                body = json.loads(request.content)
                # 某些 API 要求同时传 tool_call_parser
                if "tool_choice" in body and "tool_call_parser" not in body:
                    from langchain_core.output_parsers.openai_tools import JsonOutputToolsParser
                    body["tool_call_parser"] = JsonOutputToolsParser()
                request.content = json.dumps(body).encode("utf-8")
                request.headers["Content-Length"] = str(len(request.content))
            except Exception:
                pass

        yield request


# 模块加载时执行 patch
_patch_chatopenai_for_private_llm()

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

        from ..config import (
            LLM_PROVIDER,
            DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL,
            PRIVATE_LLM_MODEL, PRIVATE_LLM_API_URL,
        )

        # 判断使用哪个 LLM
        use_private = LLM_PROVIDER == "private"
        use_deepseek = LLM_PROVIDER == "deepseek" and bool(DEEPSEEK_API_KEY)
        use_openai = LLM_PROVIDER == "openai" and bool(os.getenv("OPENAI_API_KEY"))

        if not use_private and not use_deepseek and not use_openai:
            if DEEPSEEK_API_KEY:
                use_deepseek = True
            elif os.getenv("OPENAI_API_KEY"):
                use_openai = True

        if not use_private and not use_deepseek and not use_openai:
            msg = f"未配置任何 API Key，AI 对话功能不可用\n{_NO_KEY_MSG}"
            logger.error(msg)
            raise RuntimeError(msg)

        # LLM 配置
        if use_private:
            model_name = PRIVATE_LLM_MODEL
            llm_kwargs = {
                "name": model_name,
                "temperature": 0.1,
                "api_base_url": PRIVATE_LLM_API_URL,
                "use_responses_api": False,
            }
            logger.info("🤖 使用私有 LLM | model=%s | base_url=%s", model_name, PRIVATE_LLM_API_URL)
        elif use_deepseek:
            model_name = "deepseek-chat"
            llm_kwargs = {"name": model_name, "temperature": 0.1, "api_base_url": DEEPSEEK_BASE_URL, "use_responses_api": False}
            logger.info("🤖 使用 DeepSeek | model=%s | base_url=%s", model_name, DEEPSEEK_BASE_URL)
        else:
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            llm_kwargs = {"name": model_name, "temperature": 0.1}
            logger.info("🤖 使用 OpenAI | model=%s", model_name)

        try:
            llm_config = bao.LLMConfig(**llm_kwargs)
        except Exception as e:
            msg = f"LLMConfig 初始化失败（API Key 缺失或不合法）: {e}\n{_NO_KEY_MSG}"
            logger.error(msg)
            raise RuntimeError(msg) from e

        # 数据域 — 绑定 DuckDB
        domain = bao.domain()
        domain.add_db(_get_duckdb_connection())
        logger.info("📊 Chat Demo domain | DuckDB 已绑定")

        # 创建 agent（提高递归限制避免 LangGraph 超限）
        from ..config import AI_RECURSION_LIMIT
        from databao.agent.configs.agent import AgentConfig
        agent_config = AgentConfig(recursion_limit=AI_RECURSION_LIMIT)
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
                "rowFields": [c for c in df.columns if df[c].dtype == 'object'],
                "columnFields": [],
                "valueFields": [c for c in df.columns if df[c].dtype in ('float64', 'int64')],
                "aggregations": ["count"],
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


def _generate_followup_questions(thread, df: pd.DataFrame, query: str, answer: str) -> dict:
    """基于当前对话上下文，生成追问建议 + 字段映射"""
    result = {"questions": [], "rowFields": [], "columnFields": [], "valueFields": [], "aggregations": []}
    try:
        cols_list = list(df.columns[:8])
        type_hints = []
        for c in cols_list:
            dtype = str(df[c].dtype)
            label = "文本" if "object" in dtype else ("数值" if "int" in dtype or "float" in dtype else dtype)
            type_hints.append(f"{c}({label})")
        types_str = "; ".join(type_hints)

        # 检测是否是多维度/多图表分析请求
        is_multi = any(kw in query.lower() for kw in ["多维度", "多角度", "多图表", "全面", "多个", "各方面", "多种分析"])

        if is_multi:
            prompt = (
                f"用户要求「{query}」，需要多维度分析。当前数据字段及类型：{types_str}。"
                f"\n\n请完成：\n"
                f"1. 生成 6 个不同维度的分析问题，覆盖不同的图表类型（柱状图、饼图、折线图等），"
                f"每个问题只关注一个分析维度，用'dim'前缀标记。\n"
                f"输出格式：\n"
                f" - dim 问题1\n"
                f" - dim 问题2\n"
                f" ...\n"
                f"2. 最后输出字段映射 JSON（用第一个分析问题的字段即可）。\n"
                f"```json\n"
                f"{{\"rowFields\":[],\"columnFields\":[],\"valueFields\":[],\"aggregations\":[]}}\n"
                f"```\n"
            )
        else:
            prompt = (
                f"用户刚才问了：「{query}」。你的回答摘要：{answer[:200]}。"
                f"当前数据字段及类型：{types_str}。"
                f"\n\n请完成：\n"
                f"1. 生成 3 个用户可能感兴趣的相关追问，每行以' - '开头。\n"
                f"2. 在最后输出一个 JSON 对象，包含字段映射信息。\n"
                f"\nJSON 格式：\n"
                f"```json\n"
                f"{{\n"
                f'  "rowFields": ["文本维度字段1", "文本维度字段2"],\n'
                f'  "columnFields": ["文本维度字段3", "文本维度字段4"],\n'
                f'  "valueFields": ["数据库中的数值字段名"],\n'
                f'  "aggregations": ["count"]\n'
                f"}}\n"
                f"```\n"
                f"要求：\n"
                f"- rowFields 是文本分类字段（行维度），如车型、规则名称等\n"
                f"- columnFields 是文本分类字段（列维度），如车型、规则名称等\n"
                f"- valueFields 是数据库中的原始数值字段名，不是计算出来的别名\n"
                f"- 如果「报警数量」是 COUNT 某个字段的结果，valueFields 填那个原始字段名\n"
                f"- aggregations 只能是 count、sum、avg、min、max 中的一个\n"
            )
        thread.ask(prompt)
        text = thread.text()

        # 解析追问
        questions = []
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("-"):
                q = stripped.lstrip("- ").strip()
                # 多维度模式：去掉 dim 前缀
                if q.startswith("dim ") or q.startswith("dim "):
                    q = q[4:].strip()
                if q and len(q) < 80:
                    questions.append(q)
        result["questions"] = questions[:6] if len(questions) >= 2 else []

        # 解析 JSON 字段映射
        import re as _re
        import json as _json
        json_match = _re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if json_match:
            try:
                parsed = _json.loads(json_match.group(1))
                result["rowFields"] = parsed.get("rowFields", [])
                result["columnFields"] = parsed.get("columnFields", [])
                result["valueFields"] = parsed.get("valueFields", [])
                result["aggregations"] = parsed.get("aggregations", ["count"])
            except Exception:
                pass

        # 兜底：用 DataFrame 类型推断
        if not result["valueFields"]:
            result["rowFields"] = [c for c in df.columns if df[c].dtype == 'object']
            result["columnFields"] = []
            result["valueFields"] = [c for c in df.columns if df[c].dtype in ('float64', 'int64')]
            result["aggregations"] = ["count"] * len(result["valueFields"])

        return result
    except Exception as e:
        logger.warning("⚠️ 生成追问/字段映射失败: %s", e)
        result["rowFields"] = [c for c in df.columns if df[c].dtype == 'object']
        result["valueFields"] = [c for c in df.columns if df[c].dtype in ('float64', 'int64')]
        result["aggregations"] = ["count"] * len(result["valueFields"])
        return result


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

        # Step 3.5: 生成后续追问建议 + 字段映射
        trace.set_phase("followup")
        fi = _generate_followup_questions(thread, df, query, answer)  # returns dict
        followup_questions = fi["questions"]
        ai_rowFields = fi["rowFields"] or [c for c in df.columns if df[c].dtype == 'object']
        ai_columnFields = fi["columnFields"] or []
        ai_valueFields = fi["valueFields"] or [c for c in df.columns if df[c].dtype in ('float64', 'int64')]
        ai_aggregations = fi["aggregations"] or ["count"]

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
                "rowFields": ai_rowFields,
                "columnFields": ai_columnFields,
                "valueFields": ai_valueFields,
                "aggregations": ai_aggregations,
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

            # 保存用户消息
            append_message(sid, {"role": "user", "content": query, "timestamp": time.time()})

            # 发送初始状态 — 每次请求都从这里开始，带上 sessionId 方便前端持久化
            yield _sse_event("status", {"phase": "start", "message": "🔍 正在分析您的查询...", "session_id": sid})

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

            # 保存助手消息（含图表数据和 spec，用于刷新后恢复）
            msg_data = result.get("data", {})
            append_message(sid, {
                "role": "assistant",
                "content": result.get("message", ""),
                "chartType": result.get("chart_type"),
                "config": result.get("config"),
                "_chartType": result.get("chart_type"),
                "_chartSpec": msg_data.get("chart_spec"),
                "_columns": msg_data.get("columns", []),
                "_data": msg_data.get("data", []),
                "_followups": result.get("followup_questions", []),
                "timestamp": time.time(),
            })

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


# ---------------------------------------------------------------------------
# 聊天历史 API
# ---------------------------------------------------------------------------
@router.get("/sessions")
async def api_list_sessions():
    """获取所有历史会话列表"""
    try:
        sessions = list_sessions()
        return {"success": True, "sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{session_id}")
async def api_get_history(session_id: str):
    """获取某个会话的完整消息历史"""
    try:
        thread = get_thread(session_id)
        if thread is None:
            return {"success": True, "messages": [], "session_id": session_id}
        return {"success": True, "messages": thread.get("messages", []), "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/history/{session_id}")
async def api_delete_history(session_id: str):
    """删除会话历史"""
    try:
        ok = delete_thread(session_id)
        return {"success": ok, "message": "已删除" if ok else "会话不存在"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
