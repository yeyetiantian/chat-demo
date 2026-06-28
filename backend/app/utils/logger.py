"""
统一日志模块

使用方式:
    from app.utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("something happened")

日志格式: [时间] [LEVEL] [模块名] 消息
LLM 调用用 LLMCallLogger 专门记录输入/输出/耗时/token。
"""
import logging
import time
import os
import sys
from functools import wraps
from typing import Callable


def setup_logging(level: str = None) -> None:
    """初始化全局日志配置"""
    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO").upper()
    fmt = (
        "%(asctime)s.%(msecs)03d | %(levelname)-5s | %(name)-28s | %(message)s"
    )
    datefmt = "%H:%M:%S"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    logging.basicConfig(level=getattr(logging, level, logging.INFO), handlers=[handler], force=True)

    # 抑制过于冗长的第三方日志
    for noisy in ("httpx", "httpcore", "urllib3", "openai._base_client", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取带模块名的 logger"""
    return logging.getLogger(name)


# ---- LLM 调用专用日志器 ----

class LLMCallLogger:
    """记录 LLM API 调用的完整信息"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._seq = 0

    @staticmethod
    def _truncate(text: str, max_len: int = 1200) -> str:
        if len(text) <= max_len:
            return text
        return text[:max_len] + f"\n... [截断, 共 {len(text)} 字符]"

    def log_call(
        self,
        provider: str,
        model: str,
        messages: list,
        response_content: str,
        duration_ms: float,
        usage: dict = None,
        success: bool = True,
        error: str = None,
    ):
        """记录一次 LLM 调用"""
        self._seq += 1
        status = "✅" if success else "❌"
        self.logger.info(
            "=" * 70
        )
        self.logger.info(
            "🤖 LLM 调用 #%d | %s %s | 模型=%s | 耗时=%.0fms | %s",
            self._seq, provider, status, model, duration_ms,
            f"tokens: in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')} total={usage.get('total_tokens')}" if usage else ""
        )

        # 打印输入消息
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            self.logger.info(
                "  📥 [%s]\n%s",
                role,
                self._truncate(content)
            )

        # 打印输出
        if success:
            self.logger.info(
                "  📤 [response]\n%s",
                self._truncate(response_content)
            )
        else:
            self.logger.error("  ❌ [error] %s", error)

        self.logger.info(
            "=" * 70
        )


# 全局 LLM 日志器实例（与 chat.py 共享）
_llm_logger: LLMCallLogger = None


def get_llm_logger() -> LLMCallLogger:
    global _llm_logger
    if _llm_logger is None:
        _llm_logger = LLMCallLogger(get_logger("llm.deepseek"))
    return _llm_logger


# ---- 耗时装饰器 ----

def log_duration(logger: logging.Logger = None, label: str = ""):
    """记录函数调用耗时的装饰器"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            lg = logger or get_logger(func.__module__)
            desc = label or func.__name__
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                lg.info("⏱️  %s 完成，耗时 %.0fms", desc, elapsed)
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                lg.error("❌ %s 失败 (%.0fms): %s", desc, elapsed, str(e))
                raise
        return wrapper
    return decorator
