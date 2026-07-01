"""
图表配置 API — 存储/读取/管理 AI 生成或手动配置的图表
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any

from ..services.chart_config_service import (
    list_charts,
    get_chart,
    save_chart,
    update_chart,
    delete_chart,
    duplicate_chart,
)
from ..utils.logger import get_logger

router = APIRouter(prefix="/api/charts", tags=["图表配置"])
logger = get_logger("api.chart_config")


class ChartSaveRequest(BaseModel):
    chart_id: str | None = None
    name: str = "未命名图表"
    description: str = ""
    chart_type: str = "bar"
    source: str = "manual"
    source_query: str = ""
    chart_spec: dict | None = None
    data_config: dict = {}
    data: list[dict] = []
    columns: list[str] = []


class ChartFromAIRequest(BaseModel):
    query: str
    chart_type: str
    chart_spec: dict | None = None
    data: list[dict] = []
    columns: list[str] = []
    rowFields: list[str] = []
    columnFields: list[str] = []
    valueFields: list[str] = []
    aggregations: list[str] = ["count"]


@router.get("")
async def api_list_charts():
    """获取所有已保存的图表摘要列表"""
    try:
        charts = list_charts()
        return {"success": True, "charts": charts}
    except Exception as e:
        logger.error("获取图表列表失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{chart_id}")
async def api_get_chart(chart_id: str):
    """获取单个图表完整配置"""
    try:
        chart = get_chart(chart_id)
        if chart is None:
            raise HTTPException(status_code=404, detail=f"图表 {chart_id} 不存在")
        return {"success": True, "chart": chart}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取图表 %s 失败: %s", chart_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def api_save_chart(request: ChartSaveRequest):
    """新建或覆盖保存图表配置"""
    try:
        chart = save_chart(request.model_dump(exclude_none=True))
        return {"success": True, "chart": chart}
    except Exception as e:
        logger.error("保存图表失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/from-ai")
async def api_save_from_ai(request: ChartFromAIRequest):
    """从 AI 对话结果创建图表配置"""
    try:
        config = {
            "name": request.query[:30] + ("..." if len(request.query) > 30 else ""),
            "description": f"AI 生成: {request.query}",
            "chart_type": request.chart_type,
            "source": "ai",
            "source_query": request.query,
            "chart_spec": request.chart_spec,
            "data_config": {
                "rowFields": list(request.rowFields),
                "columnFields": list(request.columnFields),
                "valueFields": list(request.valueFields),
                "aggregations": list(request.aggregations) or ["count"],
                "filters": {},
            },
            "data": request.data,
            "columns": request.columns,
        }
        chart = save_chart(config)
        return {"success": True, "chart": chart}
    except Exception as e:
        logger.error("保存 AI 图表失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{chart_id}")
async def api_update_chart(chart_id: str, request: ChartSaveRequest):
    """更新已有图表"""
    try:
        chart = update_chart(chart_id, request.model_dump(exclude_none=True))
        if chart is None:
            raise HTTPException(status_code=404, detail=f"图表 {chart_id} 不存在")
        return {"success": True, "chart": chart}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("更新图表 %s 失败: %s", chart_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{chart_id}/duplicate")
async def api_duplicate_chart(chart_id: str):
    """复制图表"""
    try:
        chart = duplicate_chart(chart_id)
        if chart is None:
            raise HTTPException(status_code=404, detail=f"图表 {chart_id} 不存在")
        return {"success": True, "chart": chart}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("复制图表 %s 失败: %s", chart_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{chart_id}")
async def api_delete_chart(chart_id: str):
    """删除图表"""
    try:
        ok = delete_chart(chart_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"图表 {chart_id} 不存在")
        return {"success": True, "message": f"图表 {chart_id} 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("删除图表 %s 失败: %s", chart_id, e)
        raise HTTPException(status_code=500, detail=str(e))
