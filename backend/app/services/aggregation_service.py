from typing import Dict, Any, List
from ..models.schema import AggregateRequest, GroupByRequest
from .duckdb_service import get_duckdb_service


class AggregationService:
    """聚合服务 — 委托给 DuckDBService"""

    def __init__(self):
        self.db = get_duckdb_service()

    def aggregate(self, request: AggregateRequest) -> Dict[str, Any]:
        agg_types = [agg.value for agg in request.aggregations]
        result = self.db.aggregate(
            rows=request.rows,
            columns=request.columns,
            values=request.values,
            aggregations=agg_types,
            filters=request.filters,
        )
        return {
            "columns": result["columns"],
            "rows": result["rows"],
            "total": len(result["rows"]),
        }

    def group_by(self, request: GroupByRequest) -> Dict[str, Any]:
        agg_types = [agg.value for agg in request.aggregations]
        result = self.db.group_by(
            group_by=request.group_by,
            values=request.values,
            aggregations=agg_types,
        )
        return {
            "columns": result["columns"],
            "rows": result["rows"],
            "total": len(result["rows"]),
        }

    def get_fields(self) -> Dict[str, List[Dict]]:
        """获取分类字段列表"""
        return self.db.get_field_list()

    def get_data(self, limit: int = 100) -> Dict[str, Any]:
        result = self.db.get_all_data(limit=limit)
        return {
            "columns": result["columns"],
            "rows": result["rows"],
            "total": len(result["rows"]),
        }

    # ---- 下钻查询 ----

    def get_persons(self) -> List[Dict]:
        return self.db.get_persons()

    def get_tasks_by_person(self, person: str) -> List[Dict]:
        return self.db.get_tasks_by_person(person)

    def get_rules_by_task(self, task_id: int) -> List[Dict]:
        return self.db.get_rules_by_task(task_id)

    def get_alarms_by_rule(self, rule_id: int) -> List[Dict]:
        return self.db.get_alarms_by_rule(rule_id)

    def get_signals_by_alarm(self, alarm_id: int) -> List[Dict]:
        return self.db.get_signals_by_alarm(alarm_id)

    def get_signal_timeline(
        self, signal_name: str, alarm_result_ids: List[int]
    ) -> List[Dict]:
        return self.db.get_signal_timeline(signal_name, alarm_result_ids)
