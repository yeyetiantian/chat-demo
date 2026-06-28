from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum


class ChartType(str, Enum):
    BAR = "bar"
    PIE = "pie"
    LINE = "line"
    WAVEFORM = "waveform"
    RADAR = "radar"
    SCATTER = "scatter"


class AggregationType(str, Enum):
    SUM = "sum"
    AVG = "avg"
    COUNT = "count"
    MIN = "min"
    MAX = "max"


# ---- 请求模型 ----

class AggregateRequest(BaseModel):
    rows: List[str] = Field(default=[], description="行维度字段")
    columns: List[str] = Field(default=[], description="列维度字段")
    values: List[str] = Field(default=[], description="值字段")
    aggregations: List[AggregationType] = Field(
        default=[AggregationType.SUM], description="聚合方式"
    )
    filters: Dict[str, List[Any]] = Field(default={}, description="过滤条件")


class GroupByRequest(BaseModel):
    group_by: List[str] = Field(description="分组字段")
    values: List[str] = Field(description="聚合值字段")
    aggregations: List[AggregationType] = Field(default=[AggregationType.COUNT])


class ChartDataRequest(BaseModel):
    dimensions: List[str] = Field(description="维度字段")
    measures: List[str] = Field(description="度量字段")
    chart_type: Optional[ChartType] = Field(None, description="图表类型")


class ChartRecommendRequest(BaseModel):
    dimensions: List[str] = Field(description="维度字段")
    measures: List[str] = Field(description="度量字段")


class ChatQueryRequest(BaseModel):
    query: str = Field(description="自然语言查询")
    context: Optional[Dict[str, Any]] = Field(default={}, description="上下文信息")


class ChartRenderRequest(BaseModel):
    """服务端图表渲染请求 (Chat Demo plotting)"""
    chart_type: ChartType = Field(description="图表类型")
    x_column: str = Field(description="X 轴字段")
    y_columns: List[str] = Field(description="Y 轴字段")
    title: str = Field(default="", description="图表标题")
    # 可选：直接传数据，或传查询参数
    data: Optional[List[Dict[str, Any]]] = Field(None, description="直接传入的数据")
    dimensions: Optional[List[str]] = Field(None, description="维度字段(查询用)")
    measures: Optional[List[str]] = Field(None, description="度量字段(查询用)")


# ---- 响应模型 ----

class DataResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class ChartRecommendResponse(BaseModel):
    success: bool
    recommended: ChartType
    alternatives: List[ChartType]
    reason: str


class ChatQueryResponse(BaseModel):
    success: bool
    chart_type: Optional[ChartType] = None
    config: Optional[Dict[str, Any]] = None
    sql: Optional[str] = None
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    grounding: Optional[str] = Field(None, description="Chat Demo guardrails 校验结果 (GROUNDED/UNGROUNDED)")


class ChartRenderResponse(BaseModel):
    success: bool
    html: Optional[str] = None
    png_base64: Optional[str] = None
    message: Optional[str] = None


class FieldInfo(BaseModel):
    name: str
    field_type: str  # "fixed" or "dynamic"
    data_type: str  # "string", "number", "datetime"


# ---- 下钻查询模型 ----

class DrillDownRequest(BaseModel):
    person: Optional[str] = Field(None, description="人员名称")
    task_id: Optional[int] = Field(None, description="任务ID")
    rule_id: Optional[int] = Field(None, description="规则ID")
    alarm_id: Optional[int] = Field(None, description="报警结果ID")


class SignalTimelineRequest(BaseModel):
    signal_name: str = Field(description="信号名称")
    alarm_result_ids: List[int] = Field(description="报警结果ID列表")
