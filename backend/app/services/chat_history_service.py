"""
聊天历史存储服务 — 按 session 存储对话消息到 JSON 文件
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from ..utils.logger import get_logger

logger = get_logger("chat.history")

THREADS_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "threads"
THREADS_DIR.mkdir(parents=True, exist_ok=True)

_write_lock = threading.Lock()


def _thread_path(session_id: str) -> Path:
    return THREADS_DIR / f"{session_id}.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def list_sessions() -> list[dict]:
    """列出所有历史会话摘要"""
    sessions = []
    for f in sorted(THREADS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sessions.append({
                "session_id": data.get("session_id", f.stem),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "message_count": len(data.get("messages", [])),
                "preview": (data["messages"][0]["content"][:50] if data.get("messages") else ""),
            })
        except Exception:
            continue
    return sessions


def get_thread(session_id: str) -> dict | None:
    """获取某个会话的完整消息历史"""
    path = _thread_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("读取会话 %s 失败: %s", session_id, e)
        return None


def append_message(session_id: str, message: dict) -> dict:
    """追加一条消息到会话。如果会话不存在则新建。"""
    with _write_lock:
        path = _thread_path(session_id)
        now = _now()

        if path.exists():
            try:
                thread = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                thread = {"session_id": session_id, "created_at": now, "messages": []}
        else:
            thread = {"session_id": session_id, "created_at": now, "messages": []}

        thread.setdefault("messages", []).append(message)
        thread["updated_at"] = now

        path.write_text(
            json.dumps(thread, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.debug("💬 消息已保存 | session=%s | role=%s", session_id, message.get("role"))
        return thread


def delete_thread(session_id: str) -> bool:
    """删除会话"""
    path = _thread_path(session_id)
    if not path.exists():
        return False
    path.unlink()
    logger.info("🗑️ 会话已删除: %s", session_id)
    return True
