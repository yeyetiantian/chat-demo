"""
Chat Demo 全链路追踪服务

通过 monkey-patch 拦截 Chat Demo agent 内部的 LLM 调用与工具调用，
完整记录从「用户输入 → system prompt → ReAct 循环 (LLM ↔ 工具) → 最终结果」的全过程，
写入 JSON 文件供前端可视化展示。

捕获点:
  1. BaseChatModel._generate_with_cache — 所有 LLM 调用必经之路
     (v2/v1 streaming + 非 streaming 三条路径汇聚点)
  2. BaseTool.invoke — 所有工具调用 (name + args + output)

隔离: 用 contextvars.ContextVar 绑定「当前请求」的 TraceCollector，
      多请求并发互不干扰；未绑定 trace 时 patch 函数直接透传，零开销。

输出: backend/logs/traces/<trace_id>.json  (单条完整 trace)
      backend/logs/traces/index.jsonl       (索引, 每行一条摘要)
"""
import contextvars
import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from ..utils.logger import get_logger

logger = get_logger("trace.service")

# ============================================================
# 存储路径
# ============================================================
LOGS_DIR = Path(__file__).parent.parent.parent / "logs" / "traces"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
INDEX_FILE = LOGS_DIR / "index.jsonl"

# 当前请求绑定的 TraceCollector；未绑定为 None（patch 透传）
_current_trace: contextvars.ContextVar["TraceCollector | None"] = contextvars.ContextVar(
    "chatdemo_trace", default=None
)

# 文件写入锁（多线程并发写索引/文件）
_write_lock = threading.Lock()


# ============================================================
# TraceCollector — 单次请求的链路收集器
# ============================================================
class TraceCollector:
    """收集一次 chat 请求的完整链路事件。"""

    # 事件 type 取值
    T_USER_INPUT = "user_input"
    T_PHASE = "phase"
    T_LLM_CALL = "llm_call"
    T_TOOL_CALL = "tool_call"
    T_FINAL = "final"
    T_ERROR = "error"

    def __init__(self, query: str, session_id: str | None, endpoint: str):
        self.trace_id = f"tr_{uuid.uuid4().hex[:8]}"
        self.query = query
        self.session_id = session_id or ""
        self.endpoint = endpoint  # "query" | "stream"
        self.events: list[dict] = []
        self._seq = 0
        self._phase = "ask"        # ask | plot | followup
        self._llm_iter_in_phase = 0
        self.start_iso = datetime.now().isoformat(timespec="milliseconds")
        self._t0 = time.perf_counter()
        self.status = "running"
        self.summary: dict = {}

    # ---- 阶段切换 ----
    def set_phase(self, phase: str):
        """切换当前阶段（ask/plot/followup），重置阶段内 LLM 轮次计数。"""
        if phase == self._phase:
            return
        self._phase = phase
        self._llm_iter_in_phase = 0
        self.add(self.T_PHASE, {"phase": phase})

    def next_llm_iteration(self) -> int:
        """阶段内 LLM 调用轮次 +1，返回当前轮次号（体现 ReAct 循环）。"""
        self._llm_iter_in_phase += 1
        return self._llm_iter_in_phase

    # ---- 事件追加 ----
    def add(self, type_: str, data: dict, **extra) -> dict:
        self._seq += 1
        evt = {
            "seq": self._seq,
            "type": type_,
            "phase": self._phase,
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "elapsed_ms": round((time.perf_counter() - self._t0) * 1000, 1),
            "data": data,
        }
        evt.update(extra)
        self.events.append(evt)
        return evt

    # ---- 结束并落盘 ----
    def finish(self, status: str, summary: dict | None = None, error: str | None = None):
        self.status = status
        self.summary = summary or {}
        if error:
            self.summary["error"] = error
        # 汇总统计
        llm_calls = [e for e in self.events if e["type"] == self.T_LLM_CALL]
        tool_calls = [e for e in self.events if e["type"] == self.T_TOOL_CALL]
        self.summary.setdefault("llm_calls", len(llm_calls))
        self.summary.setdefault("tool_calls", len(tool_calls))
        self.summary.setdefault("iterations", max((e["data"].get("iteration", 0) for e in llm_calls), default=0))
        total_tokens = sum(
            (e["data"].get("usage") or {}).get("total_tokens", 0)
            for e in llm_calls
            if e["data"].get("usage")
        )
        self.summary.setdefault("total_tokens", total_tokens)
        self.summary["duration_ms"] = round((time.perf_counter() - self._t0) * 1000, 1)
        self.summary["end_iso"] = datetime.now().isoformat(timespec="milliseconds")
        if error:
            self.add(self.T_ERROR, {"error": error})
        self._write_to_disk()

    def _write_to_disk(self):
        payload = self.to_dict()
        path = LOGS_DIR / f"{self.trace_id}.json"
        try:
            with _write_lock:
                path.write_text(
                    json.dumps(payload, ensure_ascii=False, default=str, indent=2),
                    encoding="utf-8",
                )
                # 追加索引
                index_entry = {
                    "trace_id": self.trace_id,
                    "query": self.query[:200],
                    "endpoint": self.endpoint,
                    "session_id": self.session_id,
                    "start_iso": self.start_iso,
                    "duration_ms": self.summary.get("duration_ms"),
                    "status": self.status,
                    "llm_calls": self.summary.get("llm_calls", 0),
                    "tool_calls": self.summary.get("tool_calls", 0),
                    "iterations": self.summary.get("iterations", 0),
                    "total_tokens": self.summary.get("total_tokens", 0),
                }
                with open(INDEX_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(index_entry, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.error("写入 trace 文件失败: %s", e)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "query": self.query,
            "session_id": self.session_id,
            "endpoint": self.endpoint,
            "start_iso": self.start_iso,
            "end_iso": self.summary.get("end_iso"),
            "duration_ms": self.summary.get("duration_ms"),
            "status": self.status,
            "summary": self.summary,
            "events": self.events,
        }


# ============================================================
# 公共 API — 给 chat.py 使用
# ============================================================
def start_trace(query: str, session_id: str | None, endpoint: str) -> TraceCollector:
    """创建并绑定一个 trace 到当前上下文。调用方需在 finally 中调用 end_trace。"""
    trace = TraceCollector(query=query, session_id=session_id, endpoint=endpoint)
    trace.add(TraceCollector.T_USER_INPUT, {"query": query, "session_id": session_id or ""})
    _current_trace.set(trace)
    logger.info("🔍 trace 开始 | id=%s | query=%s", trace.trace_id, query[:80])
    return trace


def end_trace(trace: TraceCollector, status: str = "success", summary: dict | None = None, error: str | None = None):
    """结束 trace 并落盘，解除上下文绑定。"""
    try:
        trace.add(TraceCollector.T_FINAL, summary or {})
        trace.finish(status, summary=summary, error=error)
        logger.info(
            "✅ trace 结束 | id=%s | status=%s | llm=%d tool=%d | %.0fms",
            trace.trace_id, status,
            trace.summary.get("llm_calls", 0), trace.summary.get("tool_calls", 0),
            trace.summary.get("duration_ms", 0),
        )
    finally:
        _current_trace.set(None)


# ============================================================
# 序列化工具 — 把 langchain 对象转为 JSON 友好的 dict
# ============================================================
def _safe_jsonable(obj: Any, max_len: int | None = None) -> Any:
    """递归转为 JSON 可序列化对象；超长字符串截断。"""
    if obj is None or isinstance(obj, (bool, int, float)):
        if isinstance(obj, float) and (obj != obj):  # NaN
            return None
        return obj
    if isinstance(obj, str):
        return obj if max_len is None or len(obj) <= max_len else obj[:max_len] + f"\n... [截断, 共 {len(obj)} 字符]"
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if v != v else v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.ndarray,)):
        return _safe_jsonable(obj.tolist(), max_len)
    if isinstance(obj, (list, tuple)):
        return [_safe_jsonable(x, max_len) for x in obj]
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            try:
                result[str(k)] = _safe_jsonable(v, max_len)
            except Exception:
                result[str(k)] = f"<serialize_error: {type(v).__name__}>"
        return result
    # 其它对象 → 字符串
    try:
        s = str(obj)
    except Exception:
        s = f"<unserializable {type(obj).__name__}>"
    return s if max_len is None or len(s) <= max_len else s[:max_len] + f"\n... [截断, 共 {len(s)} 字符]"


def _serialize_message(m: Any) -> dict:
    """把 langchain BaseMessage 序列化为 {role, content, tool_calls?, ...}。"""
    role = getattr(m, "type", None) or getattr(m, "role", None) or type(m).__name__
    content = getattr(m, "content", "")
    d: dict = {
        "role": role,
        "content": _safe_jsonable(content, max_len=20000),
    }
    # tool_calls (AIMessage)
    tool_calls = getattr(m, "tool_calls", None)
    if tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.get("id"),
                "name": tc.get("name"),
                "args": _safe_jsonable(tc.get("args", {}), max_len=5000),
            }
            for tc in tool_calls
        ]
    # 工具名 / tool_call_id (ToolMessage)
    name = getattr(m, "name", None)
    if name:
        d["name"] = name
    tool_call_id = getattr(m, "tool_call_id", None)
    if tool_call_id:
        d["tool_call_id"] = tool_call_id
    # 额外元数据
    usage = getattr(m, "usage_metadata", None)
    if usage:
        d["usage_metadata"] = _safe_jsonable(usage)
    return d


def _serialize_ai_message(aim: Any) -> dict:
    """提取 AIMessage 的关键字段（content + tool_calls + finish_reason + usage）。"""
    out: dict = {
        "content": _safe_jsonable(getattr(aim, "content", ""), max_len=20000),
    }
    tool_calls = getattr(aim, "tool_calls", None)
    if tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.get("id"),
                "name": tc.get("name"),
                "args": _safe_jsonable(tc.get("args", {}), max_len=5000),
            }
            for tc in tool_calls
        ]
    response_metadata = getattr(aim, "response_metadata", None) or {}
    if response_metadata:
        out["finish_reason"] = response_metadata.get("finish_reason")
        out["model"] = response_metadata.get("model_name") or response_metadata.get("model")
    usage = getattr(aim, "usage_metadata", None)
    if usage:
        out["usage"] = _safe_jsonable(usage)
    return out


# ============================================================
# Monkey-patch 安装（幂等）
# ============================================================
_installed = False


def install_tracing() -> None:
    """安装 LLM / 工具拦截 patch。进程内幂等，仅安装一次。

    拦截层级:
      1. BaseChatModel._generate_with_cache — 所有 LLM 调用的必经之路
         (v2 streaming / v1 streaming / 非 streaming 三条路径都在此汇聚)
      2. BaseTool.invoke — 所有工具调用
    """
    global _installed
    if _installed:
        return

    _patch_generate_with_cache()
    _patch_base_tool()
    _installed = True
    logger.info("🔧 trace patch 已安装 (BaseChatModel._generate_with_cache + BaseTool.invoke)")


# ---- LLM 拦截 ----

def _normalize_content_to_string(messages: list) -> list:
    """将 list 类型的 message content 还原为纯字符串。

    langchain-core 1.4+ 的 BaseMessage.content_blocks 机制可能在某些路径下
    将 string content 转为 [{"type": "text", "text": "..."}] 格式。
    DeepSeek 等兼容 API 不接受 content blocks 数组，需要还原为纯字符串。
    """
    try:
        normalized = list(messages)
        for i, m in enumerate(normalized):
            content = getattr(m, "content", None)
            if content is None or not isinstance(content, list):
                continue
            # 提取所有 text block 合并为字符串
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            if parts:
                normalized[i] = m.model_copy(update={"content": "".join(parts)})
        return normalized
    except Exception:
        return messages  # 防御性回退，任何异常都不应阻断 LLM 调用


def _patch_generate_with_cache():
    """拦截 BaseChatModel._generate_with_cache —— LLM 调用必经之路。

    为什么不用 ChatOpenAI._generate？
    LangGraph 运行时会附加 v2 streaming callback handler (_V2StreamingCallbackHandler)，
    导致 _should_use_protocol_streaming() 返回 True，LLM 调用走 v2 事件流路径，
    _generate() 根本不会被调用。而 _generate_with_cache 是上游汇聚点，
    无论走 v2 stream / v1 stream / 非 stream 哪条分支，都必经此方法。
    """
    try:
        from langchain_core.language_models.chat_models import BaseChatModel
    except ImportError:
        logger.warning("langchain_core 未安装，跳过 LLM patch")
        return

    orig = BaseChatModel._generate_with_cache

    def patched(self, messages, stop=None, run_manager=None, **kwargs):
        # Fix: DeepSeek 等兼容 API 不接受 content blocks 数组格式
        # (langchain-core 1.4+ 会将 string content 转为 [{"type":"text","text":"..."}])
        # 这里将所有 list 类型的 system/user message content 还原为纯字符串
        messages = _normalize_content_to_string(messages)

        trace = _current_trace.get()
        if trace is None:
            return orig(self, messages, stop=stop, run_manager=run_manager, **kwargs)

        iteration = trace.next_llm_iteration()
        t0 = time.perf_counter()
        input_msgs = [_serialize_message(m) for m in messages]
        model_name = (
            getattr(self, "model_name", None)
            or getattr(self, "model", None)
            or type(self).__name__
        )

        try:
            result = orig(self, messages, stop=stop, run_manager=run_manager, **kwargs)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            trace.add(
                trace.T_LLM_CALL,
                {
                    "model": str(model_name),
                    "iteration": iteration,
                    "duration_ms": round(elapsed, 1),
                    "input_messages": input_msgs,
                    "output": {"error": str(e)},
                },
                error=True,
            )
            raise

        elapsed = (time.perf_counter() - t0) * 1000
        output: dict = {}
        usage: dict | None = None

        try:
            if result.generations and result.generations[0]:
                # ChatResult.generations 在不同代码路径中格式不一致:
                #   v2 streaming: [ChatGeneration(message=...)]      — 扁平 list
                #   v1 streaming: [[ChatGeneration(...)]]            — 嵌套 list
                #   非 streaming: [[ChatGeneration(...)]]            — 嵌套 list
                first = result.generations[0]
                if isinstance(first, (list, tuple)):
                    gen = first[0]      # 嵌套结构
                else:
                    gen = first         # v2 streaming 扁平结构
                aim = gen.message
                output = _serialize_ai_message(aim)

                # 提取 usage (来自 AIMessage 的 usage_metadata)
                usage_meta = getattr(aim, "usage_metadata", None) or {}
                if usage_meta:
                    usage = {
                        "prompt_tokens": usage_meta.get("input_tokens", 0),
                        "completion_tokens": usage_meta.get("output_tokens", 0),
                        "total_tokens": usage_meta.get("total_tokens", 0),
                    }
                    # 缓存命中信息
                    cache_read = usage_meta.get("input_token_details", {}).get("cache_read", 0)
                    if cache_read:
                        usage["cache_read_tokens"] = cache_read

                # 从 generation_info 补充
                gen_info = getattr(gen, "generation_info", None) or {}
                if gen_info and not usage:
                    tu = gen_info.get("token_usage") if isinstance(gen_info, dict) else None
                    if tu:
                        usage = _safe_jsonable(tu)

        except Exception as e:
            output["__serialize_error__"] = str(e)

        # 构建最终 output
        final_output = dict(output)
        if usage:
            final_output["usage"] = usage

        trace.add(
            trace.T_LLM_CALL,
            {
                "model": str(model_name),
                "iteration": iteration,
                "duration_ms": round(elapsed, 1),
                "input_messages": input_msgs,
                "output": final_output,
                "usage": usage,
            },
        )
        return result

    BaseChatModel._generate_with_cache = patched
    BaseChatModel._orig_generate_with_cache = orig  # type: ignore[attr-defined]
    logger.info("  ✅ BaseChatModel._generate_with_cache patched")


# ---- 工具拦截 ----

def _patch_base_tool():
    """拦截 BaseTool.invoke — 记录工具名、参数、输出、耗时。

    注意：Chat Demo 的工具调用参数中可能包含 graph_state（完整的对话历史），
    这会导致 trace 文件暴增。这里对超大的 args 做智能摘要处理。
    """
    try:
        from langchain_core.tools import BaseTool
    except ImportError:
        logger.warning("langchain_core.tools 未安装，跳过工具 patch")
        return

    orig = BaseTool.invoke

    def patched(self, input, config=None, **kwargs):
        trace = _current_trace.get()
        if trace is None:
            return orig(self, input, config=config, **kwargs)

        t0 = time.perf_counter()
        tool_name = getattr(self, "name", None) or type(self).__name__
        tool_desc = (getattr(self, "description", "") or "")[:300]

        # 智能序列化：超大输入做摘要（防御性包裹，序列化异常不阻断工具调用）
        try:
            safe_args = _serialize_tool_args(input, tool_name)
        except Exception:
            safe_args = {"_serialize_error": f"<{type(input).__name__}>"}

        try:
            result = orig(self, input, config=config, **kwargs)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            trace.add(
                trace.T_TOOL_CALL,
                {
                    "name": tool_name,
                    "description": tool_desc,
                    "args": safe_args,
                    "output": None,
                    "duration_ms": round(elapsed, 1),
                    "error": str(e),
                },
                error=True,
            )
            raise

        elapsed = (time.perf_counter() - t0) * 1000
        trace.add(
            trace.T_TOOL_CALL,
            {
                "name": tool_name,
                "description": tool_desc,
                "args": safe_args,
                "output": _serialize_tool_output(result, tool_name),
                "duration_ms": round(elapsed, 1),
            },
        )
        return result

    BaseTool.invoke = patched
    BaseTool._orig_invoke = orig  # type: ignore[attr-defined]
    logger.info("  ✅ BaseTool.invoke patched")


# ---- 智能序列化：工具参数 ----

def _serialize_tool_args(input: Any, tool_name: str) -> dict:
    """智能序列化工具参数，避免 graph_state 等巨量数据撑爆 trace 文件。

    对 Chat Demo 的 run_sql_query / submit_result 等核心工具做专门优化。
    """
    args = _safe_jsonable(input, max_len=80000)

    if not isinstance(args, dict):
        return {"raw_input": str(args)[:500]}

    # 所有工具都可能收到 graph_state — 将其替换为摘要
    if "graph_state" in args:
        gs = args["graph_state"]
        if isinstance(gs, dict):
            messages = gs.get("messages", [])
            if isinstance(messages, list):
                args["graph_state"] = {
                    "_summary": f"graph_state 包含 {len(messages)} 条历史消息（此处省略以节省空间）",
                    "message_count": len(messages),
                    "last_message_preview": str(messages[-1])[:200] if messages else "(空)",
                }
            else:
                args["graph_state"] = {"_summary": str(gs)[:200]}
        elif isinstance(gs, str) and len(gs) > 500:
            args["graph_state"] = gs[:200] + f"... [截断, 共 {len(gs)} 字符]"

    # run_sql_query / submit_result: 保留 SQL 和关键字段，截断 artifact
    if tool_name in ("run_sql_query", "submit_result"):
        if "sql" in args:
            # 保留完整 SQL
            pass
        if "artifact" in args:
            art = args["artifact"]
            if isinstance(art, dict):
                # 保留 df 摘要
                df_info = art.get("df")
                if df_info is not None:
                    art["df"] = _summarize_df(df_info)
                # 截断 csv/markdown
                for k in ("csv", "markdown"):
                    if k in art and isinstance(art[k], str) and len(art[k]) > 1000:
                        art[k] = art[k][:500] + f"\n... [截断, 共 {len(art[k])} 字符]"
                args["artifact"] = art
            elif isinstance(art, str) and len(art) > 1000:
                args["artifact"] = art[:500] + f"... [截断, 共 {len(art)} 字符]"

    return args


def _serialize_tool_output(result: Any, tool_name: str) -> Any:
    """智能序列化工具输出，对大型结果做摘要。"""
    out = _safe_jsonable(result, max_len=80000)

    if tool_name in ("run_sql_query",) and isinstance(out, str):
        # SQL 查询结果 — 截断
        if len(out) > 2000:
            lines = out.split("\n")
            header = lines[0] if lines else ""
            row_count = len(lines) - 1
            return {
                "summary": f"查询返回 {row_count} 行数据",
                "header": header,
                "first_rows": "\n".join(lines[1:11]) if len(lines) > 1 else "",
                "truncated": len(out) > 2000,
            }
    return out


def _summarize_df(df_info: Any) -> Any:
    """将 DataFrame 信息压缩为摘要"""
    if df_info is None:
        return None
    if isinstance(df_info, str):
        # 可能是 str(DataFrame) 的字符串表示
        lines = df_info.strip().split("\n")
        return {
            "shape": f"{len(lines)-1} 行 (含表头)",
            "columns": lines[0] if lines else "",
            "first_rows": "\n".join(lines[1:6]) if len(lines) > 1 else "",
            "_truncated": len(df_info) > 800,
        }
    if hasattr(df_info, "shape"):
        return {
            "shape": list(getattr(df_info, "shape", [])),
            "columns": list(getattr(df_info, "columns", []))[:20],
        }
    return str(df_info)[:500]


# ============================================================
# 索引/文件读取 — 给 trace API 使用
# ============================================================
def list_traces(limit: int = 100) -> list[dict]:
    """读取索引，返回按时间倒序的 trace 摘要列表。"""
    if not INDEX_FILE.exists():
        return []
    entries: list[dict] = []
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error("读取 trace 索引失败: %s", e)
    # 按 start_iso 倒序
    entries.sort(key=lambda x: x.get("start_iso", ""), reverse=True)
    return entries[:limit]


def get_trace(trace_id: str) -> dict | None:
    """读取单个 trace 完整数据。"""
    path = LOGS_DIR / f"{trace_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("读取 trace %s 失败: %s", trace_id, e)
        return None


def delete_trace(trace_id: str) -> bool:
    """删除单个 trace 文件，并从索引中移除。"""
    path = LOGS_DIR / f"{trace_id}.json"
    deleted = path.exists()
    with _write_lock:
        if deleted:
            path.unlink(missing_ok=True)
        # 重写索引（剔除该 id）
        if INDEX_FILE.exists():
            kept: list[str] = []
            for line in INDEX_FILE.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                    if entry.get("trace_id") != trace_id:
                        kept.append(line)
                except json.JSONDecodeError:
                    kept.append(line)
            INDEX_FILE.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return deleted
