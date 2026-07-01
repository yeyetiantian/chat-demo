"""
图表配置存储服务 — 类似 trace 的 JSON 文件管理
"""

import json
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from ..utils.logger import get_logger

logger = get_logger("chart.service")

CHARTS_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "charts"
CHARTS_DIR.mkdir(parents=True, exist_ok=True)
INDEX_FILE = CHARTS_DIR / "index.json"

_write_lock = threading.Lock()

# 默认索引
_DEFAULT_INDEX = {"order": [], "charts": {}}


def _load_index() -> dict:
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("图表索引文件损坏，重建: %s", e)
    return {"order": [], "charts": {}}


def _save_index(index: dict) -> None:
    INDEX_FILE.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _chart_path(chart_id: str) -> Path:
    return CHARTS_DIR / f"{chart_id}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    return f"ch_{uuid.uuid4().hex[:8]}"


# ---- 公开接口 ----


def list_charts() -> list[dict]:
    """返回所有图表的摘要列表（按 order 排序）"""
    index = _load_index()
    result = []
    for cid in index.get("order", []):
        info = index.get("charts", {}).get(cid)
        if info:
            info["chart_id"] = cid
            result.append(info)
    return result


def get_chart(chart_id: str) -> dict | None:
    """获取单个图表的完整配置"""
    path = _chart_path(chart_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("读取图表 %s 失败: %s", chart_id, e)
        return None


def save_chart(config: dict) -> dict:
    """
    保存图表配置。如果 config 中有 chart_id 则覆盖，否则新建。
    返回完整的 chart 配置（含 chart_id、created_at、updated_at）。
    """
    chart_id = config.pop("chart_id", None) or _new_id()
    now = _now()

    with _write_lock:
        index = _load_index()

        is_new = chart_id not in index.get("charts", {})

        chart = {
            "chart_id": chart_id,
            "name": config.get("name", "未命名图表"),
            "description": config.get("description", ""),
            "chart_type": config.get("chart_type", "bar"),
            "source": config.get("source", "manual"),
            "source_query": config.get("source_query", ""),
            "chart_spec": config.get("chart_spec"),
            "data_config": config.get("data_config", {}),
            "data": config.get("data", []),
            "columns": config.get("columns", []),
            "created_at": config.get("created_at", now) if not is_new else now,
            "updated_at": now,
        }

        # 写完整文件
        _chart_path(chart_id).write_text(
            json.dumps(chart, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        # 更新索引
        if chart_id not in index.setdefault("charts", {}):
            index.setdefault("order", []).append(chart_id)
        index["charts"][chart_id] = {
            "name": chart["name"],
            "chart_type": chart["chart_type"],
            "source": chart["source"],
            "source_query": chart.get("source_query", ""),
            "created_at": chart["created_at"],
            "updated_at": now,
        }
        _save_index(index)

        logger.info("📊 图表 %s: %s", "更新" if not is_new else "新建", chart_id)
        return chart


def update_chart(chart_id: str, config: dict) -> dict | None:
    """更新已有图表配置"""
    existing = get_chart(chart_id)
    if existing is None:
        return None
    merged = {**existing, **config}
    return save_chart(merged)


def delete_chart(chart_id: str) -> bool:
    """删除图表"""
    with _write_lock:
        index = _load_index()
        if chart_id not in index.get("charts", {}):
            return False
        del index["charts"][chart_id]
        if chart_id in index.get("order", []):
            index["order"].remove(chart_id)
        _save_index(index)

        path = _chart_path(chart_id)
        if path.exists():
            path.unlink()
        logger.info("🗑️ 图表已删除: %s", chart_id)
        return True


def duplicate_chart(chart_id: str) -> dict | None:
    """复制图表"""
    existing = get_chart(chart_id)
    if existing is None:
        return None
    copy = {k: v for k, v in existing.items() if k not in ("chart_id", "created_at", "updated_at")}
    copy["name"] = copy.get("name", "") + " (副本)"
    return save_chart(copy)
