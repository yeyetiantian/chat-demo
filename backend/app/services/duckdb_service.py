import time
import duckdb
from typing import Dict, Any, List, Optional
from ..config import DUCKDB_PATH
from ..utils.logger import get_logger

logger = get_logger("duckdb.service")


# 基础查询片段：将 6 张表 JOIN 为扁平化宽表
_ALARM_DATA_FROM = """
FROM TM_RMU_PS_TASK t
JOIN TM_RMU_PS_TASK_VEHICLETYPE vt ON t.TASK_ID = vt.TASK_ID
JOIN TM_RMU_PS_TASK_VEHICLE tv ON t.TASK_ID = tv.TASK_ID
JOIN TM_RMU_PS_TASK_RULE tr ON t.TASK_ID = tr.TASK_ID
LEFT JOIN TL_RMU_PS_TASK_RULE_RESULT rr ON tr.TASK_RULE_ID = rr.TASK_RULE_ID
"""

_ALARM_DATA_SELECT = f"""
SELECT
    t.CREATE_BY                          AS "人员",
    vt.VEHICLETYPE_NAME                  AS "车型",
    tv.VIN                               AS "车辆",
    t.TASK_NAME                          AS "任务",
    tr.RULE_NAME                         AS "规则名称",
    CASE tr.RULE_TYPE
        WHEN 0 THEN '统计'
        WHEN 1 THEN '报警'
        WHEN 2 THEN '事件'
        ELSE '未知'
    END                                  AS "规则类型",
    rr.TIME                              AS "报警时间",
    rr.TRIGGER_TIME                      AS "触发时间",
    TRY_CAST(COALESCE(rr.VALUE, '0') AS DOUBLE) AS "持续时间",
    rr.TASK_RULE_RESULT_ID               AS "报警结果ID",
    tr.TASK_RULE_ID                      AS "规则ID",
    t.TASK_ID                            AS "任务ID",
    tv.TASK_VEHICLE_ID                   AS "车辆关联ID",
    vt.TASK_VEHICLETYPE_ID               AS "车型关联ID"
{_ALARM_DATA_FROM}
"""

# 信号值查询片段
_SIGNAL_FROM = """
FROM TL_RMU_PS_TASK_RULE_RESULT_SIGNAL s
JOIN TL_RMU_PS_TASK_RULE_RESULT rr ON s.TASK_RULE_RESULT_ID = rr.TASK_RULE_RESULT_ID
"""

# 固定字段元数据（与 v_alarm_data SELECT 中的字段对应）
_FIXED_FIELDS_META = [
    {"column_name": "人员", "column_type": "VARCHAR"},
    {"column_name": "车型", "column_type": "VARCHAR"},
    {"column_name": "车辆", "column_type": "VARCHAR"},
    {"column_name": "任务", "column_type": "VARCHAR"},
    {"column_name": "规则名称", "column_type": "VARCHAR"},
    {"column_name": "规则类型", "column_type": "VARCHAR"},
    {"column_name": "报警时间", "column_type": "TIMESTAMP"},
    {"column_name": "触发时间", "column_type": "TIMESTAMP"},
    {"column_name": "持续时间", "column_type": "DOUBLE"},
]


class DuckDBService:
    """DuckDB 服务 — 单例，连接 vcloud_duck.db (只读)，使用 CTE 查询扁平化宽表"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        t0 = time.perf_counter()
        self.conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        self._signal_names = None  # 缓存信号名称列表
        logger.info("🔌 DuckDB 连接已建立 | path=%s | read_only=True (%.0fms)", DUCKDB_PATH, (time.perf_counter() - t0) * 1000)

    def _wrap_query(self, select_clause: str, where: str = "1=1",
                    group_by: str = "", order_by: str = "", limit: int = 0) -> str:
        """构建完整 CTE 查询：WITH v AS (JOIN) SELECT ... FROM v WHERE ... GROUP BY ..."""
        sql = f"WITH v AS ({_ALARM_DATA_SELECT}) SELECT {select_clause} FROM v WHERE {where}"
        if group_by:
            sql += f" GROUP BY {group_by}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit > 0:
            sql += f" LIMIT {limit}"
        return sql

    # ---- 基础查询 ----

    def execute_query(self, sql: str) -> List[Dict[str, Any]]:
        """执行 SQL 查询，返回字典列表"""
        result = self.conn.execute(sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def get_table_info(self, table_name: str = "v_alarm_data") -> List[Dict[str, str]]:
        """获取表/视图结构信息"""
        # 对于虚拟的 v_alarm_data，返回固定字段元数据
        if table_name == "v_alarm_data":
            return list(_FIXED_FIELDS_META)

        # 对于真实表，使用 DESCRIBE
        info = self.conn.execute(f"DESCRIBE {table_name}").fetchall()
        return [{"column_name": col[0], "column_type": col[1]} for col in info]

    # ---- 聚合查询 ----

    def _is_signal_field(self, field_name: str) -> bool:
        """检查字段是否为信号名称（动态字段，需要从信号表查询）"""
        signal_names = self.get_signal_names()
        return field_name in signal_names

    # ---- 字段类型感知：聚合兼容性选择 ----

    def _get_field_type(self, field_name: str) -> str:
        """返回字段的 DuckDB 类型字符串（大写）。未知类型返回 ''。"""
        clean = field_name.strip().strip('"')
        for meta in _FIXED_FIELDS_META:
            if meta["column_name"] == clean:
                return meta["column_type"].upper()
        if self._is_signal_field(clean):
            # 信号值在 SQL 中做了 TRY_CAST(VALUE AS DOUBLE)
            return "DOUBLE"
        # 动态类型未知，返回空串
        return ""

    def _is_numeric_type(self, t: str) -> bool:
        return any(k in t for k in ("DECIMAL", "DOUBLE", "FLOAT", "INT", "HUGEINT", "SMALLINT", "BIGINT", "UBIGINT", "UTINYINT", "USMALLINT", "UINTEGER", "NUMERIC"))

    def _is_temporal_type(self, t: str) -> bool:
        return any(k in t for k in ("TIMESTAMP", "DATE", "TIME", "INTERVAL"))

    def _is_bool_type(self, t: str) -> bool:
        return "BOOL" in t

    def _is_string_type(self, t: str) -> bool:
        return any(k in t for k in ("VARCHAR", "STRING", "TEXT", "CHAR", "CLOB", "JSON", "UUID", "ENUM"))

    def _make_compatible_agg(self, agg: str, field_name: str) -> str:
        """
        根据字段类型选择与该类型兼容的聚合函数：
        - SUM/AVG 仅对数值 & BOOL 安全（BOOL 被 DuckDB cast 为 0/1）
        - TIMESTAMP / VARCHAR / 未知类型 → SUM/AVG 自动降级为 COUNT
        - MIN / MAX / COUNT 对所有类型都安全，原样返回
        返回的 agg 永远是大写。
        """
        a = agg.upper()
        t = self._get_field_type(field_name)
        if a in ("MIN", "MAX", "COUNT"):
            return a
        if a == "AVG":
            if not t or self._is_numeric_type(t):
                return a
            if self._is_bool_type(t):
                return a
            # 时间 / 字符串 / 未知 → 退化为 COUNT
            logger.warning("AVG 与字段类型不兼容，自动改为 COUNT: field=%s type=%s", field_name, t or "UNKNOWN")
            return "COUNT"
        if a == "SUM":
            if not t or self._is_numeric_type(t):
                return a
            if self._is_bool_type(t):
                return a
            # 时间 / 字符串 / 未知 → 退化为 COUNT
            logger.warning("SUM 与字段类型不兼容，自动改为 COUNT: field=%s type=%s", field_name, t or "UNKNOWN")
            return "COUNT"
        # 其它自定义聚合：仅当类型未知时保守返回 COUNT
        if not t or self._is_temporal_type(t) or self._is_string_type(t):
            logger.warning("聚合 %s 与字段类型不兼容，自动改为 COUNT: field=%s type=%s", agg, field_name, t or "UNKNOWN")
            return "COUNT"
        return a

    def _build_value_expr(self, val: str, agg: str) -> str:
        """为聚合构建值表达式 — 普通列直接引用，信号列用标量子查询。
        注意：会根据字段类型对 agg 做兼容性修正（SUM(TIMESTAMP) → COUNT(TIMESTAMP) 等）。"""
        effective_agg = self._make_compatible_agg(agg, val)
        clean = val.replace('"', '')
        alias = f'"{clean}_{effective_agg.lower()}"'
        if self._is_signal_field(val):
            # 信号值存储在 TL_RMU_PS_TASK_RULE_RESULT_SIGNAL 表中（行级键值对）
            # 使用标量子查询获取对应报警结果的信号值
            return (
                f'{effective_agg}((SELECT TRY_CAST(s.VALUE AS DOUBLE) '
                f'FROM TL_RMU_PS_TASK_RULE_RESULT_SIGNAL s '
                f'WHERE s.TASK_RULE_RESULT_ID = v."报警结果ID" '
                f"AND s.SIGNAL_NAME = '{val}')) AS {alias}"
            )
        else:
            return f'{effective_agg}("{val}") AS {alias}'

    def _retry_with_count_fallback(self, build_sql_fn, values: List[str], original_agg: str) -> List[Dict[str, Any]]:
        """
        兜底重试：先尝试原聚合构建 SQL 并执行；
        若抛出 BinderException（如 SUM(TIMESTAMP) 这类函数签名不匹配），
        则把每个 value 都退化为 COUNT 再重新执行。
        """
        try:
            sql = build_sql_fn(original_agg)
            return self.execute_query(sql)
        except Exception as e:
            msg = str(e)
            # 仅在明确是聚合函数签名不匹配时才降级重试，其它错误（如字段不存在）直接抛出
            is_binder_error = (
                isinstance(e, getattr(duckdb, "BinderException", Exception))
                or "Binder Error" in msg
                or "No function matches" in msg
                or "could not be bound" in msg
            )
            if not is_binder_error or original_agg.upper() == "COUNT":
                raise
            logger.warning(
                "聚合 %s 抛出 BinderError，对全部字段降级为 COUNT 重试。错误: %s",
                original_agg, msg.splitlines()[0] if msg else str(e),
            )
            sql = build_sql_fn("COUNT")
            return self.execute_query(sql)

    def aggregate(
        self,
        rows: List[str],
        columns: List[str],
        values: List[str],
        aggregations: List[str],
        filters: Optional[Dict[str, List[Any]]] = None,
    ) -> Dict[str, Any]:
        """透视聚合 (GROUP BY)"""
        dims = rows + columns
        agg = aggregations[0].upper() if aggregations else "COUNT"

        where_parts = ["1=1"]
        if filters:
            for field, filter_vals in filters.items():
                if filter_vals:
                    vals_str = ", ".join(
                        f"'{v}'" if isinstance(v, str) else str(v) for v in filter_vals
                    )
                    where_parts.append(f'"{field}" IN ({vals_str})')
        where_clause = " AND ".join(where_parts)
        group_clause = ", ".join(f'"{d}"' for d in dims) if dims else ""

        def _build_sql(a: str) -> str:
            select_parts = [f'"{d}"' for d in dims]
            for val in values:
                select_parts.append(self._build_value_expr(val, a))
            select_clause = ", ".join(select_parts)
            order = group_clause if group_clause else select_parts[0] if select_parts else "1"
            return self._wrap_query(
                select_clause=select_clause,
                where=where_clause,
                group_by=group_clause,
                order_by=order,
            )

        result = self._retry_with_count_fallback(_build_sql, values, agg)
        return {"columns": list(result[0].keys()) if result else [], "rows": result}

    def group_by(
        self, group_by: List[str], values: List[str], aggregations: List[str]
    ) -> Dict[str, Any]:
        """分组聚合"""
        agg = aggregations[0].upper() if aggregations else "COUNT"
        group_clause = ", ".join(f'"{d}"' for d in group_by)

        def _build_sql(a: str) -> str:
            select_parts = [f'"{d}"' for d in group_by]
            for val in values:
                select_parts.append(self._build_value_expr(val, a))
            select_clause = ", ".join(select_parts)
            return self._wrap_query(
                select_clause=select_clause,
                group_by=group_clause,
                order_by=group_clause,
            )

        result = self._retry_with_count_fallback(_build_sql, values, agg)
        return {"columns": list(result[0].keys()) if result else [], "rows": result}

    def get_all_data(self, limit: int = 1000) -> Dict[str, Any]:
        """获取扁平化宽表数据"""
        sql = self._wrap_query(select_clause="*", limit=limit)
        result = self.execute_query(sql)
        return {"columns": list(result[0].keys()) if result else [], "rows": result}

    # ---- 下钻查询 ----

    def get_persons(self) -> List[Dict]:
        sql = self._wrap_query(
            select_clause='"人员", COUNT(DISTINCT "任务ID") AS 任务数',
            where='"人员" IS NOT NULL AND "人员" != \'null\'',
            group_by='"人员"',
            order_by="任务数 DESC",
        )
        return self.execute_query(sql)

    def get_tasks_by_person(self, person: str) -> List[Dict]:
        safe = person.replace("'", "''")
        sql = self._wrap_query(
            select_clause='"任务ID", "任务", "车型", COUNT(DISTINCT "车辆") AS 车辆数, COUNT(DISTINCT "规则ID") AS 规则数',
            where=f'"人员" = \'{safe}\'',
            group_by='"任务ID", "任务", "车型"',
            order_by="规则数 DESC",
        )
        return self.execute_query(sql)

    def get_rules_by_task(self, task_id: int) -> List[Dict]:
        sql = self._wrap_query(
            select_clause='"规则ID", "规则名称", "规则类型", COUNT(DISTINCT "报警结果ID") AS 报警次数',
            where=f'"任务ID" = {task_id}',
            group_by='"规则ID", "规则名称", "规则类型"',
            order_by="报警次数 DESC",
        )
        return self.execute_query(sql)

    def get_alarms_by_rule(self, rule_id: int) -> List[Dict]:
        sql = self._wrap_query(
            select_clause='"报警结果ID", "报警时间", "触发时间", "持续时间", "车辆"',
            where=f'"规则ID" = {rule_id}',
            order_by='"报警时间" DESC',
        )
        return self.execute_query(sql)

    # ---- 信号查询 ----

    def get_signal_names(self) -> List[str]:
        """获取所有信号名称（带缓存）"""
        if self._signal_names is None:
            rows = self.conn.execute(
                "SELECT DISTINCT SIGNAL_NAME FROM TL_RMU_PS_TASK_RULE_RESULT_SIGNAL WHERE SIGNAL_NAME IS NOT NULL ORDER BY SIGNAL_NAME"
            ).fetchall()
            self._signal_names = [r[0] for r in rows]
        return self._signal_names

    def get_signals_by_alarm(self, alarm_result_id: int) -> List[Dict]:
        sql = f"""
            SELECT s.SIGNAL_NAME AS "信号名称",
                   TRY_CAST(s.VALUE AS DOUBLE) AS "信号值",
                   rr.TIME AS "报警时间"
            {_SIGNAL_FROM}
            WHERE s.TASK_RULE_RESULT_ID = {alarm_result_id}
              AND s.VALUE IS NOT NULL AND s.VALUE != '' AND s.VALUE != 'NULL'
              AND TRY_CAST(s.VALUE AS DOUBLE) IS NOT NULL
            ORDER BY s.SIGNAL_NAME
        """
        return self.execute_query(sql)

    def get_signal_timeline(
        self, signal_name: str, alarm_result_ids: List[int]
    ) -> List[Dict]:
        """获取信号时间序列数据（用于波形图）"""
        if not alarm_result_ids:
            return []
        ids_str = ", ".join(str(i) for i in alarm_result_ids)
        safe = signal_name.replace("'", "''")
        sql = f"""
            SELECT s.TASK_RULE_RESULT_ID AS "报警结果ID",
                   rr.TIME AS "报警时间",
                   TRY_CAST(s.VALUE AS DOUBLE) AS "信号值"
            {_SIGNAL_FROM}
            WHERE s.SIGNAL_NAME = '{safe}'
              AND s.TASK_RULE_RESULT_ID IN ({ids_str})
              AND TRY_CAST(s.VALUE AS DOUBLE) IS NOT NULL
            ORDER BY rr.TIME
        """
        return self.execute_query(sql)

    # ---- 字段列表 ----

    def get_field_list(self) -> Dict[str, List[Dict]]:
        """获取分类字段列表（固定字段 + 动态信号字段）"""
        # 固定字段来自 _FIXED_FIELDS_META，但排除内部 ID 列
        fixed_fields = [
            f for f in _FIXED_FIELDS_META
            if f["column_name"] not in ("报警结果ID", "规则ID", "任务ID", "车辆关联ID", "车型关联ID")
        ]
        signal_names = self.get_signal_names()
        dynamic_fields = [{"column_name": s, "column_type": "DOUBLE"} for s in signal_names]
        return {"fixed": fixed_fields, "dynamic": dynamic_fields}


_db_instance = None


def get_duckdb_service() -> DuckDBService:
    """获取 DuckDBService 单例"""
    global _db_instance
    if _db_instance is None:
        _db_instance = DuckDBService()
    return _db_instance
