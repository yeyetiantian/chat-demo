import time
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from .api import pivot_router, chart_router, chat_router, chatdemo_router, trace_router, chart_config_router
from .utils.logger import setup_logging, get_logger

# 初始化日志（如果 run.py 没调用则这里兜底）
setup_logging()

logger = get_logger("api")

app = FastAPI(
    title="DataPivot API",
    description="数据透视分析系统 API — 支持拖拽透视、AI 对话查询、Chat Demo 联动",
    version="2.0.0",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    status = response.status_code
    method = request.method
    path = request.url.path
    # 用不同颜色标记状态码
    if status < 300:
        logger.info("➡️  %s %s → %d (%.0fms)", method, path, status, elapsed_ms)
    elif status < 400:
        logger.warning("⚠️  %s %s → %d (%.0fms)", method, path, status, elapsed_ms)
    else:
        logger.error("❌ %s %s → %d (%.0fms)", method, path, status, elapsed_ms)
    return response


# 注册路由
app.include_router(pivot_router)
app.include_router(chart_router)
app.include_router(chat_router)
app.include_router(chatdemo_router)
app.include_router(trace_router)
app.include_router(chart_config_router)


@app.get("/")
async def root():
    return {
        "message": "DataPivot API v2.0",
        "docs": "/docs",
        "endpoints": {
            "pivot": "/api/pivot/*",
            "chart": "/api/chart/*",
            "chat": "/api/chat/*",
            "chatdemo": "/api/chatdemo/*",
        },
    }
