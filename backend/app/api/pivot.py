from fastapi import APIRouter, HTTPException, Query
from ..models.schema import (
    AggregateRequest,
    GroupByRequest,
    DataResponse,
    DrillDownRequest,
)
from ..services.aggregation_service import AggregationService

router = APIRouter(prefix="/api/pivot", tags=["数据透视"])


@router.post("/aggregate", response_model=DataResponse)
async def aggregate(request: AggregateRequest):
    """执行数据透视聚合"""
    try:
        service = AggregationService()
        result = service.aggregate(request)
        return DataResponse(success=True, data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/groupby", response_model=DataResponse)
async def group_by(request: GroupByRequest):
    """执行分组聚合"""
    try:
        service = AggregationService()
        result = service.group_by(request)
        return DataResponse(success=True, data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fields", response_model=DataResponse)
async def get_fields():
    """获取分类字段列表（固定字段 + 动态信号字段）"""
    try:
        service = AggregationService()
        result = service.get_fields()
        return DataResponse(success=True, data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data", response_model=DataResponse)
async def get_data(limit: int = 100):
    """获取原始扁平化数据"""
    try:
        service = AggregationService()
        result = service.get_data(limit=limit)
        return DataResponse(success=True, data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---- 下钻 API ----

@router.get("/persons", response_model=DataResponse)
async def get_persons():
    """获取人员列表"""
    try:
        service = AggregationService()
        result = service.get_persons()
        return DataResponse(success=True, data={"persons": result})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drill/tasks", response_model=DataResponse)
async def get_tasks(person: str = Query(description="人员名称")):
    """根据人员获取任务列表"""
    try:
        service = AggregationService()
        result = service.get_tasks_by_person(person)
        return DataResponse(success=True, data={"tasks": result})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drill/rules", response_model=DataResponse)
async def get_rules(task_id: int = Query(description="任务ID")):
    """根据任务获取规则列表"""
    try:
        service = AggregationService()
        result = service.get_rules_by_task(task_id)
        return DataResponse(success=True, data={"rules": result})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drill/alarms", response_model=DataResponse)
async def get_alarms(rule_id: int = Query(description="规则ID")):
    """根据规则获取报警记录"""
    try:
        service = AggregationService()
        result = service.get_alarms_by_rule(rule_id)
        return DataResponse(success=True, data={"alarms": result})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drill/signals", response_model=DataResponse)
async def get_signals(alarm_id: int = Query(description="报警结果ID")):
    """根据报警获取信号值列表"""
    try:
        service = AggregationService()
        result = service.get_signals_by_alarm(alarm_id)
        return DataResponse(success=True, data={"signals": result})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/drill/signal-timeline", response_model=DataResponse)
async def get_signal_timeline(request: dict):
    """获取信号时间序列（波形图数据）"""
    try:
        service = AggregationService()
        result = service.get_signal_timeline(
            signal_name=request["signal_name"],
            alarm_result_ids=request["alarm_result_ids"],
        )
        return DataResponse(success=True, data={"timeline": result})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
