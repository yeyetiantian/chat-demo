import time
import duckdb
import pandas as pd
from typing import Dict, Any, List, Optional

from databao.subagents.shared.introspection.introspectors.duckdb.duckdb_introspector import (
    DuckDBIntrospector,
)
from databao.subagents.shared.introspection.introspectors.duckdb.connection_config import (
    DuckDBConnectionConfig,
)
from databao.subagents.shared.introspection.introspectors.databases_types import (
    DatabaseIntrospectionResult,
    FullyQualifiedTableName,
)
from databao.subagents.shared.plotting import build_fig_and_html, render_png
from ..config import DUCKDB_PATH
from ..utils.logger import get_logger

logger = get_logger("chatdemo.service")


class ChatDemoService:
    """Chat Demo 集成服务 — 数据库内省 + Plotly 图表渲染"""

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
        self._introspector = None
        logger.info("ChatDemoService 初始化完成 (DuckDB: %s)", DUCKDB_PATH)

    def get_introspector(self) -> DuckDBIntrospector:
        if not self._introspector:
            t0 = time.perf_counter()
            config = DuckDBConnectionConfig(database_path=DUCKDB_PATH, read_only=True)
            self._introspector = DuckDBIntrospector(config)
            logger.info(
                "🔌 DuckDBIntrospector 创建完成 (%.0fms)", (time.perf_counter() - t0) * 1000
            )
        return self._introspector

    # ---- 数据库内省 ----

    def introspect_database(
        self, include_samples: bool = False
    ) -> DatabaseIntrospectionResult:
        t0 = time.perf_counter()
        result = self.get_introspector().introspect_database(
            include_samples=include_samples
        )
        elapsed = (time.perf_counter() - t0) * 1000
        # 统计对象数量
        tables = sum(len(s.tables) for cat in result.catalogs for s in cat.schemas)
        logger.info("📊 数据库内省完成 (%.0fms) | 发现 %d 个对象", elapsed, tables)
        return result

    def get_database_summary(self) -> Dict[str, Any]:
        t0 = time.perf_counter()
        result = self.introspect_database()
        summary = {"tables": [], "views": [], "total_tables": 0, "total_columns": 0}

        for catalog in result.catalogs:
            for schema in catalog.schemas:
                for table in schema.tables:
                    kind = table.kind.value if table.kind else "table"
                    info = {
                        "name": table.name,
                        "kind": kind,
                        "column_count": len(table.columns),
                        "columns": [
                            {
                                "name": col.name,
                                "data_type": col.type,
                                "is_nullable": col.nullable,
                                "description": col.description or "",
                            }
                            for col in table.columns
                        ],
                    }
                    if kind == "view":
                        summary["views"].append(info)
                    else:
                        summary["tables"].append(info)
                    summary["total_tables"] += 1
                    summary["total_columns"] += len(table.columns)

        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            "📋 Schema 摘要完成 (%.0fms) | %d 表, %d 视图, %d 列",
            elapsed,
            len(summary["tables"]),
            len(summary["views"]),
            summary["total_columns"],
        )
        return summary

    def get_table_columns(self, table_name: str) -> List[Dict[str, Any]]:
        t0 = time.perf_counter()
        result = self.introspect_database()
        for catalog in result.catalogs:
            for schema in catalog.schemas:
                for table in schema.tables:
                    if table.name == table_name:
                        columns = [
                            {
                                "column_name": col.name,
                                "data_type": col.type,
                                "is_nullable": col.nullable,
                                "description": col.description or "",
                            }
                            for col in table.columns
                        ]
                        logger.info(
                            "📋 表 %s 列信息 (%.0fms) | %d 列",
                            table_name,
                            (time.perf_counter() - t0) * 1000,
                            len(columns),
                        )
                        return columns
        logger.warning("⚠️  未找到表 %s 的列信息", table_name)
        return []

    def get_table_stats(self, table_name: str) -> Optional[Dict[str, Any]]:
        t0 = time.perf_counter()
        result = self.introspect_database()
        for catalog in result.catalogs:
            for schema in catalog.schemas:
                for table in schema.tables:
                    if table.name == table_name:
                        fqn = FullyQualifiedTableName(
                            catalog_name=catalog.name,
                            schema_name=schema.name,
                            table_name=table.name,
                        )
                        introspector = self.get_introspector()
                        stats = introspector.data_profile_tables([fqn])
                        if fqn in stats:
                            ts = stats[fqn]
                            column_stats = {}
                            for col_name, cs in ts.columns.items():
                                column_stats[col_name] = {
                                    "null_count": cs.null_count,
                                    "non_null_count": cs.non_null_count,
                                    "distinct_count": cs.distinct_count,
                                    "cardinality_kind": (
                                        cs.cardinality_kind.value
                                        if cs.cardinality_kind
                                        else None
                                    ),
                                    "min_value": cs.min_value,
                                    "max_value": cs.max_value,
                                }
                            elapsed = (time.perf_counter() - t0) * 1000
                            logger.info(
                                "📊 表 %s 数据画像完成 (%.0fms) | %d 行, %d 列",
                                table_name, elapsed, ts.stats.row_count, len(column_stats),
                            )
                            return {"row_count": ts.stats.row_count, "columns": column_stats}
        logger.warning("⚠️  未找到表 %s 的统计信息", table_name)
        return None

    def get_column_distinct_values(
        self, table_name: str, column_name: str, limit: int = 100
    ) -> List[Any]:
        t0 = time.perf_counter()
        conn = duckdb.connect(DUCKDB_PATH, read_only=True)
        try:
            sql = (
                f'SELECT DISTINCT "{column_name}" FROM {table_name} '
                f'WHERE "{column_name}" IS NOT NULL LIMIT {limit}'
            )
            result = conn.execute(sql).fetchall()
            values = [row[0] for row in result]
            logger.info(
                "🔍 DISTINCT %s.%s (%.0fms) | %d 个值",
                table_name, column_name, (time.perf_counter() - t0) * 1000, len(values),
            )
            return values
        finally:
            conn.close()

    # ---- Plotly 图表渲染 ----

    def render_chart(
        self,
        data: List[Dict],
        chart_type: str,
        x_column: str,
        y_columns: List[str],
        title: str = "",
    ) -> Dict[str, Any]:
        """使用 Chat Demo plotting 渲染图表"""
        t0 = time.perf_counter()
        df = pd.DataFrame(data)
        if df.empty:
            return {"error": "数据为空"}

        for col in y_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.info(
            "🎨 Plotly 渲染开始 | type=%s x=%s y=%s title=%s | %d 行",
            chart_type, x_column, y_columns, title or "(无)", len(df),
        )

        fig, html_str = build_fig_and_html(df, chart_type, x_column, y_columns, title)
        png_b64 = render_png(fig)

        elapsed = (time.perf_counter() - t0) * 1000
        png_size = len(png_b64) if png_b64 else 0
        logger.info(
            "✅ Plotly 渲染完成 (%.0fms) | html=%d chars | png=%d bytes",
            elapsed, len(html_str), png_size,
        )

        return {"html": html_str, "png_base64": png_b64}

    def render_chart_html(
        self,
        data: List[Dict],
        chart_type: str,
        x_column: str,
        y_columns: List[str],
        title: str = "",
    ) -> str:
        t0 = time.perf_counter()
        df = pd.DataFrame(data)
        if df.empty:
            return '<div style="padding:20px;color:#999">暂无数据</div>'
        for col in y_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        _, html_str = build_fig_and_html(df, chart_type, x_column, y_columns, title)
        logger.info(
            "🎨 Plotly HTML 渲染完成 (%.0fms) | %d chars",
            (time.perf_counter() - t0) * 1000, len(html_str),
        )
        return html_str
