"""
Trace 日志 API — 查询和管理 Chat Demo agent 全链路追踪日志

端点:
  GET  /api/trace/list       — 列出所有 trace 摘要
  GET  /api/trace/{id}       — 获取单个 trace 完整详情
  DELETE /api/trace/{id}     — 删除 trace
  GET  /api/trace/stats      — trace 统计信息
"""
from fastapi import APIRouter, HTTPException, Query

from ..services.trace_service import list_traces, get_trace, delete_trace
from ..utils.logger import get_logger

router = APIRouter(prefix="/api/trace", tags=["链路追踪"])
logger = get_logger("api.trace")


@router.get("/list")
async def trace_list(limit: int = Query(default=50, le=200)):
    """获取 trace 列表（按时间倒序，仅含摘要信息）"""
    try:
        traces = list_traces(limit=limit)
        return {
            "success": True,
            "total": len(traces),
            "traces": traces,
        }
    except Exception as e:
        logger.error("获取 trace 列表失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def trace_stats():
    """获取 trace 统计信息"""
    try:
        from ..services.trace_service import LOGS_DIR
        import os
        files = [f for f in os.listdir(LOGS_DIR) if f.endswith(".json")] if LOGS_DIR.exists() else []
        total_size = sum(os.path.getsize(LOGS_DIR / f) for f in files) if files else 0

        # 简单统计
        total_llm = 0
        total_tool = 0
        total_duration = 0.0
        for fname in files[:50]:
            try:
                import json
                with open(LOGS_DIR / fname, "r") as f:
                    d = json.load(f)
                for evt in d.get("events", []):
                    if evt.get("type") == "llm_call":
                        total_llm += 1
                    elif evt.get("type") == "tool_call":
                        total_tool += 1
                total_duration += d.get("duration_ms", 0)
            except Exception:
                pass

        return {
            "success": True,
            "total_traces": len(files),
            "total_size_kb": round(total_size / 1024, 1),
            "total_llm_calls": total_llm,
            "total_tool_calls": total_tool,
            "avg_duration_ms": round(total_duration / len(files), 0) if files else 0,
        }
    except Exception as e:
        logger.error("获取 trace 统计失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{trace_id}")
async def trace_detail(trace_id: str):
    """获取单个 trace 的完整详情（含所有事件、LLM 调用、工具调用）"""
    try:
        trace = get_trace(trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail=f"Trace {trace_id} 不存在")
        return {"success": True, "trace": trace}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取 trace %s 失败: %s", trace_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{trace_id}")
async def trace_delete(trace_id: str):
    """删除指定 trace"""
    try:
        deleted = delete_trace(trace_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Trace {trace_id} 不存在")
        logger.info("🗑️ Trace 已删除 | %s", trace_id)
        return {"success": True, "message": f"Trace {trace_id} 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("删除 trace %s 失败: %s", trace_id, e)
        raise HTTPException(status_code=500, detail=str(e))
