"""
ChatDemo 主程序 - 集成 FastAPI + 静态文件托管
"""

import os
import sys
import webbrowser
import threading
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
INDEX_PATH = BASE_DIR / "index.html"
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
if FRONTEND_DIST.exists():
    ALT_INDEX = FRONTEND_DIST / "index.html"
    if ALT_INDEX.exists() and not INDEX_PATH.exists():
        INDEX_PATH = ALT_INDEX

app = FastAPI(title="ChatDemo", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SPAStaticMiddleware(BaseHTTPMiddleware):
    """SPA 路由中间件：非 API 请求返回 index.html"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path.startswith("/api/"):
            return await call_next(request)

        if path.startswith("/assets/"):
            candidate = FRONTEND_DIST / path.lstrip("/")
            if candidate.exists():
                return FileResponse(candidate)
            base_candidate = BASE_DIR / path.lstrip("/")
            if base_candidate.exists():
                return FileResponse(base_candidate)
            return HTMLResponse("<h1>404</h1>", status_code=404)

        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            for root in (BASE_DIR, FRONTEND_DIST):
                f = root / rel
                if f.exists():
                    return FileResponse(f)
            return HTMLResponse("<h1>404</h1>", status_code=404)

        if path != "/" and "." in Path(path).name:
            for root in (FRONTEND_DIST, BASE_DIR):
                f = root / path.lstrip("/")
                if f.exists():
                    return FileResponse(f)

        if INDEX_PATH.exists():
            return FileResponse(INDEX_PATH)
        return HTMLResponse("<h1>404</h1>", status_code=404)


app.add_middleware(SPAStaticMiddleware)


@app.on_event("startup")
async def startup():
    """启动时打印诊断 + 延迟打开浏览器"""
    # 诊断（不暴露 key 内容）
    try:
        from app.config import DEEPSEEK_API_KEY as _k1
        import os as _os
        _k2 = _os.getenv("OPENAI_API_KEY", "")
        _status = "✅ 已配置 (DEEPSEEK_API_KEY)" if _k1 else (
            "✅ 已配置 (OPENAI_API_KEY)" if _k2 else "\u26a0\ufe0f  未配置（AI 对话功能不可用）"
        )
        print(f"   AI API Key: {_status}")
        if not (_k1 or _k2):
            print("   \u2192 请在可执行文件同目录创建 .env 文件，例如：")
            print("     DEEPSEEK_API_KEY=sk-xxx")
            print("     DEEPSEEK_BASE_URL=https://api.deepseek.com/v1")
        from app.config import DUCKDB_PATH as _dp
        print(f"   数据库: {_dp}")
    except Exception:
        pass

    def open_browser():
        import time as _t
        import urllib.request as _ur
        import socket as _sk
        url = "http://localhost:8080/"
        deadline = _t.time() + 60
        while _t.time() < deadline:
            try:
                _ = _ur.urlopen(url, timeout=2)
                break
            except (_sk.timeout, OSError, Exception):
                _t.sleep(0.8)
                continue
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=open_browser, daemon=True).start()
    print("\n\u2705 ChatDemo \u5df2\u542f\u52a8: http://localhost:8080")
    print(f"   \u8d44\u6e90\u76ee\u5f55: {BASE_DIR}")
    print(f"   index.html: {INDEX_PATH}")
    print("   浏览器将在服务就绪后自动打开（最长等待60秒）。")


from app.api import pivot_router, chart_router, chat_router, chatdemo_router, trace_router, chart_config_router  # noqa: E402
app.include_router(pivot_router)
app.include_router(chart_router)
app.include_router(chat_router)
app.include_router(chatdemo_router)
app.include_router(trace_router)
app.include_router(chart_config_router)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
