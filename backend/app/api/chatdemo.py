from fastapi import APIRouter, HTTPException, Query
from ..services.chatdemo_service import ChatDemoService

router = APIRouter(prefix="/api/chatdemo", tags=["Chat Demo"])


@router.get("/introspect")
async def introspect_database():
    """获取完整数据库内省摘要"""
    try:
        service = ChatDemoService()
        summary = service.get_database_summary()
        return {"success": True, **summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/table/columns")
async def get_table_columns(table_name: str = Query(default="v_alarm_data")):
    """获取表/视图的列信息"""
    try:
        service = ChatDemoService()
        columns = service.get_table_columns(table_name)
        return {"success": True, "table_name": table_name, "columns": columns}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/table/stats")
async def get_table_stats(table_name: str = Query(default="v_alarm_data")):
    """获取表的数据统计信息"""
    try:
        service = ChatDemoService()
        stats = service.get_table_stats(table_name)
        if stats:
            return {"success": True, "table_name": table_name, **stats}
        return {"success": False, "message": f"未找到表 {table_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/column/distinct")
async def get_column_distinct_values(
    table_name: str = Query(default="v_alarm_data"),
    column_name: str = Query(default="规则类型"),
    limit: int = 50,
):
    """获取字段的去重值"""
    try:
        service = ChatDemoService()
        values = service.get_column_distinct_values(table_name, column_name, limit)
        return {
            "success": True,
            "table_name": table_name,
            "column_name": column_name,
            "values": values,
            "count": len(values),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
