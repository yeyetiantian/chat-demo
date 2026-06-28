from fastapi import APIRouter, HTTPException
from ..models.schema import (
    ChartDataRequest,
    ChartRecommendRequest,
    ChartRecommendResponse,
    ChartRenderRequest,
    ChartRenderResponse,
    DataResponse,
)
from ..services.chart_service import ChartService

router = APIRouter(prefix="/api/chart", tags=["图表"])


@router.post("/recommend", response_model=ChartRecommendResponse)
async def recommend_chart(request: ChartRecommendRequest):
    """推荐图表类型"""
    try:
        service = ChartService()
        result = service.recommend_chart(request)
        return ChartRecommendResponse(success=True, **result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/data", response_model=DataResponse)
async def get_chart_data(request: ChartDataRequest):
    """获取指定类型图表数据"""
    try:
        service = ChartService()
        if not request.chart_type:
            raise ValueError("图表类型不能为空")
        if not request.dimensions:
            raise ValueError("维度字段不能为空")
        result = service.get_chart_data(
            request.chart_type, request.dimensions, request.measures
        )
        return DataResponse(success=True, data=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---- 单个图表类型的快捷端点 ----

_CHART_TYPES = ["bar", "pie", "line", "waveform", "radar", "scatter"]


def _make_chart_handler(chart_type: str):
    async def handler(request: ChartDataRequest):
        try:
            from ..models.schema import ChartType
            service = ChartService()
            result = service.get_chart_data(
                ChartType(chart_type), request.dimensions, request.measures
            )
            return DataResponse(success=True, data=result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    return handler


for ct in _CHART_TYPES:
    router.add_api_route(
        f"/{ct}",
        _make_chart_handler(ct),
        methods=["POST"],
        response_model=DataResponse,
        name=f"get_{ct}_chart",
    )


# ---- Chat Demo Plotly 服务端渲染 ----

@router.post("/render", response_model=ChartRenderResponse)
async def render_chart(request: ChartRenderRequest):
    """使用 Chat Demo plotting 服务端渲染图表，返回 HTML + PNG base64"""
    try:
        service = ChartService()
        result = service.render_chart(
            chart_type=request.chart_type,
            x_column=request.x_column,
            y_columns=request.y_columns,
            title=request.title,
            dimensions=request.dimensions,
            measures=request.measures,
            data=request.data,
        )
        if "error" in result:
            return ChartRenderResponse(success=False, message=result["error"])
        return ChartRenderResponse(
            success=True,
            html=result.get("html"),
            png_base64=result.get("png_base64"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
