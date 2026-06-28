from typing import Dict, Any, List
from ..models.schema import ChartType, ChartRecommendRequest, GroupByRequest, AggregationType
from .aggregation_service import AggregationService
from .chatdemo_service import ChatDemoService

# 图表推荐规则
CHART_RECOMMENDATIONS = [
    {
        "conditions": {"dimension_count": 1, "measure_count": 1, "is_time_series": False},
        "recommended": ChartType.BAR,
        "alternatives": [ChartType.PIE],
        "reason": "单维度单度量，适合类别比较",
    },
    {
        "conditions": {"dimension_count": 1, "measure_count": 2, "is_time_series": False},
        "recommended": ChartType.BAR,
        "alternatives": [ChartType.RADAR],
        "reason": "单维度多度量，适合分组比较",
    },
    {
        "conditions": {"dimension_count": 1, "measure_count": 1, "is_time_series": True},
        "recommended": ChartType.LINE,
        "alternatives": [ChartType.BAR],
        "reason": "时间序列数据，适合趋势展示",
    },
    {
        "conditions": {"dimension_count": 2, "measure_count": 1, "is_time_series": False},
        "recommended": ChartType.BAR,
        "alternatives": [ChartType.LINE],
        "reason": "双维度数据，适合堆叠或分组展示",
    },
    {
        "conditions": {"dimension_count": 2, "measure_count": 2, "is_time_series": False},
        "recommended": ChartType.SCATTER,
        "alternatives": [ChartType.LINE],
        "reason": "双维度双度量，适合相关性分析",
    },
    {
        "conditions": {"dimension_count": 3, "measure_count": 1, "is_time_series": False},
        "recommended": ChartType.RADAR,
        "alternatives": [ChartType.SCATTER],
        "reason": "多维度数据，适合多维分析",
    },
    {
        "conditions": {"is_signal_data": True, "dimension_count": 1, "measure_count": 1},
        "recommended": ChartType.WAVEFORM,
        "alternatives": [ChartType.LINE],
        "reason": "信号类数据，适合波形展示",
    },
]

SIGNAL_FIELDS_PATTERNS = [
    "UDat", "Prplsn", "IBS", "Eng", "Bat", "Sys", "Veh",
    "Temp", "Volt", "Spd", "Pwr", "Pres", "Sts", "Cmd",
    "Req", "Pstn", "Flw", "Ht", "Clm", "Rng", "Pmp",
]


class ChartService:
    """图表服务 — 数据查询 + 图表推荐 + Chat Demo 渲染"""

    def __init__(self):
        self.agg_service = AggregationService()
        self.chatdemo_service = ChatDemoService()

    # ---- 图表推荐 ----

    def _is_time_field(self, field_name: str) -> bool:
        return any(kw in field_name for kw in ["时间", "time", "date", "datetime"])

    def _is_signal_field(self, field_name: str) -> bool:
        return any(p in field_name for p in SIGNAL_FIELDS_PATTERNS)

    def _analyze_fields(
        self, dimensions: List[str], measures: List[str]
    ) -> Dict[str, Any]:
        return {
            "dimension_count": len(dimensions),
            "measure_count": len(measures),
            "is_time_series": any(self._is_time_field(d) for d in dimensions),
            "is_signal_data": any(self._is_signal_field(m) for m in measures),
        }

    def recommend_chart(self, request: ChartRecommendRequest) -> Dict[str, Any]:
        analysis = self._analyze_fields(request.dimensions, request.measures)
        best_match = None
        best_score = 0

        for rec in CHART_RECOMMENDATIONS:
            cond = rec["conditions"]
            score = 0
            if cond.get("dimension_count") == analysis["dimension_count"]:
                score += 3
            if cond.get("measure_count") == analysis["measure_count"]:
                score += 3
            if cond.get("is_time_series") == analysis["is_time_series"]:
                score += 2
            if cond.get("is_signal_data") == analysis.get("is_signal_data", False):
                score += 2
            if score > best_score:
                best_score = score
                best_match = rec

        if best_match:
            return {
                "recommended": best_match["recommended"],
                "alternatives": best_match["alternatives"],
                "reason": best_match["reason"],
            }
        return {
            "recommended": ChartType.BAR,
            "alternatives": [ChartType.LINE, ChartType.PIE],
            "reason": "默认推荐柱状图",
        }

    # ---- 图表数据 ----

    def _prepare_chart_data(
        self, dimensions: List[str], measures: List[str]
    ) -> Dict[str, Any]:
        if not dimensions:
            dimensions = [measures[0]] if measures else ["规则类型"]
        if not measures:
            measures = ["持续时间"]

        request = GroupByRequest(
            group_by=dimensions,
            values=measures,
            aggregations=[AggregationType.SUM],
        )
        return self.agg_service.group_by(request)

    def get_chart_data(
        self, chart_type: ChartType, dimensions: List[str], measures: List[str]
    ) -> Dict[str, Any]:
        data = self._prepare_chart_data(dimensions, measures)
        return {
            "type": chart_type.value,
            "data": data["rows"],
            "columns": data["columns"],
            "dimensions": dimensions,
            "measures": measures,
        }

    # ---- Chat Demo Plotly 渲染 ----

    def render_chart(
        self,
        chart_type: ChartType,
        x_column: str,
        y_columns: List[str],
        title: str = "",
        dimensions: List[str] = None,
        measures: List[str] = None,
        data: List[Dict] = None,
    ) -> Dict[str, Any]:
        """使用 Chat Demo plotting 进行服务端图表渲染"""
        if data is None:
            if dimensions and measures:
                chart_data = self.get_chart_data(chart_type, dimensions, measures)
                data = chart_data.get("data", [])
            else:
                return {"error": "请提供 data 或 dimensions+measures"}

        result = self.chatdemo_service.render_chart(
            data, chart_type.value, x_column, y_columns, title
        )
        return result

    def render_chart_html(
        self,
        chart_type: ChartType,
        x_column: str,
        y_columns: List[str],
        title: str = "",
        dimensions: List[str] = None,
        measures: List[str] = None,
        data: List[Dict] = None,
    ) -> str:
        """渲染图表为 HTML"""
        if data is None:
            if dimensions and measures:
                chart_data = self.get_chart_data(chart_type, dimensions, measures)
                data = chart_data.get("data", [])
            else:
                return '<div style="padding:20px;color:#999">暂无数据</div>'

        return self.chatdemo_service.render_chart_html(
            data, chart_type.value, x_column, y_columns, title
        )
