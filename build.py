#!/usr/bin/env python3
"""
DataPivot 打包脚本
将前后端打包成单个可执行文件
"""

import os
import sys
import shutil
import subprocess
import platform
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
BUILD_DIR = PROJECT_ROOT / "dist"
VENV_DIR = BACKEND_DIR / "venv"

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
EXEC_SUFFIX = ".exe" if IS_WIN else ""
EXECUTABLE = BUILD_DIR / f"DataPivot{EXEC_SUFFIX}"

SEP = ";" if IS_WIN else ":"


def run(cmd, cwd=None):
    """运行命令"""
    print(f"  执行: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or "").strip() or (result.stdout or "").strip()
        if len(tail) > 2000:
            tail = tail[:1000] + "\n...[中间省略]...\n" + tail[-1000:]
        print(f"  ❌ 失败:\n{tail}")
        return False
    return True


def build_frontend():
    """打包前端"""
    print("\n[1/4] 打包前端...")
    npm = shutil.which("npm")
    if not npm:
        print("  ❌ 未找到 npm，请先安装 Node.js")
        return False
    if not run([npm, "run", "build"], cwd=FRONTEND_DIR):
        return False
    dist = FRONTEND_DIR / "dist"
    if not (dist / "index.html").exists():
        print(f"  ❌ 前端构建失败，未找到 {dist / 'index.html'}")
        return False
    print("  ✅ 前端打包成功")
    return True


def create_server_main():
    """创建主程序（FastAPI + 静态文件托管）"""
    print("\n[2/4] 创建主程序...")

    main_py = BACKEND_DIR / "app" / "server_main.py"
    server_code = '''"""
DataPivot 主程序 - 集成 FastAPI + 静态文件托管
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

app = FastAPI(title="DataPivot", version="2.0.0")

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
    try:
        from app.config import DEEPSEEK_API_KEY as _k1
        import os as _os
        _k2 = _os.getenv("OPENAI_API_KEY", "")
        _status = "✅ 已配置 (DEEPSEEK_API_KEY)" if _k1 else (
            "✅ 已配置 (OPENAI_API_KEY)" if _k2 else "⚠️  未配置（AI 对话功能不可用）"
        )
        print(f"   AI API Key: {_status}")
        if not (_k1 or _k2):
            print("   → 请在可执行文件同目录创建 .env 文件，例如：")
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
    print("\\n✅ DataPivot 已启动: http://localhost:8080")
    print(f"   资源目录: {BASE_DIR}")
    print(f"   index.html: {INDEX_PATH}")
    print("   浏览器将在服务就绪后自动打开（最长等待60秒）。")


from app.api import pivot_router, chart_router, chat_router, chatdemo_router, trace_router  # noqa: E402
app.include_router(pivot_router)
app.include_router(chart_router)
app.include_router(chat_router)
app.include_router(chatdemo_router)
app.include_router(trace_router)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
'''

    main_py.write_text(server_code, encoding='utf-8')
    print(f"  ✅ 主程序已创建: {main_py}")
    return True


def build_executable():
    """打包后端"""
    print("\n[3/4] 打包后端...")

    venv_python = VENV_DIR / "bin" / "python"

    # 打包后 index.html 和 frontend/dist 会被解压到 _MEIPASS 临时目录
    # server_main.py 中的 _base_dir() 会正确处理路径
    cmd = [
        str(venv_python), "-m", "PyInstaller",
        "--onefile",
        "--console",
        f"--add-data{SEP}index.html{SEP}.",
        f"--add-data{SEP}frontend/dist{SEP}frontend/dist",
        f"--add-data{SEP}vcloud_duck.db{SEP}.",
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
        "--noupx",
        "-D", str(BUILD_DIR / "backend_dist"),
        "app/server_main.py"
    ]

    if not run(cmd, cwd=BACKEND_DIR):
        return False
    print("  ✅ 后端打包成功")
    return True


def finalize():
    """最终整理"""
    print("\n[4/4] 最终整理...")

    # 清理临时文件
    temp_dir = BUILD_DIR / "backend_dist"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    # 复制可执行文件到 dist 根目录
    src_exe = BUILD_DIR / "backend_dist" / f"DataPivot{EXEC_SUFFIX}"
    if src_exe.exists():
        shutil.copy2(src_exe, EXECUTABLE)
        print(f"  ✅ 可执行文件: {EXECUTABLE}")
    else:
        # PyInstaller 输出可能在 dist/backend_dist/DataPivot/ 也可能是其它路径
        alt = BUILD_DIR / "backend_dist" / "DataPivot"
        if alt.exists():
            shutil.copy2(alt, EXECUTABLE)
            print(f"  ✅ 可执行文件: {EXECUTABLE}")
        else:
            print(f"  ⚠️ 未找到可执行文件，请检查 {BUILD_DIR / 'backend_dist'}")

    # 创建启动脚本
    if IS_WIN:
        _create_win_launcher()
    else:
        _create_mac_launcher()

    # 创建 README
    readme_path = BUILD_DIR / "README.txt"
    if not readme_path.exists():
        readme_path.write_text(f"""DataPivot 打包文件

使用说明:
1. 双击 "DataPivot" (或 启动 DataPivot.bat) 启动程序
2. 程序会自动打开浏览器访问 http://localhost:8080
3. 关闭控制台窗口将终止程序

API 文档: http://localhost:8080/docs
""", encoding='utf-8')
        print(f"  ✅ 文档说明: {readme_path}")

    return True


def _create_win_launcher():
    """Windows 启动脚本"""
    launcher = BUILD_DIR / "启动 DataPivot.bat"
    launcher.write_text("""@echo off
chcp 65001 >nul
echo ========================================
echo   DataPivot 启动中...
echo ========================================
echo.
start "" "DataPivot.exe"
timeout /t 3 /nobreak >nul
start http://localhost:8080
echo.
echo ========================================
echo   服务已启动
echo   关闭此窗口将终止程序
echo ========================================
pause
""", encoding='utf-8')
    print(f"  ✅ Windows 启动脚本: {launcher}")


def _create_mac_launcher():
    """macOS 启动脚本"""
    launcher = BUILD_DIR / "启动 DataPivot.command"
    launcher.write_text("""#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo "  DataPivot 启动中..."
echo "========================================"
echo ""
echo "[1/2] 启动后端服务..."
"./DataPivot" &
sleep 3
echo "[2/2] 打开浏览器..."
open http://localhost:8080
echo ""
echo "========================================"
echo "  服务已启动"
echo "  关闭 terminal 窗口将终止程序"
echo "========================================"
""", encoding='utf-8')
    os.chmod(launcher, 0o755)
    print(f"  ✅ macOS 启动脚本: {launcher}")


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("DataPivot 打包脚本")
    print("=" * 60)
    print(f"  平台: {sys.platform}")
    print(f"  输出: {EXECUTABLE}")

    # 检查虚拟环境
    if not (VENV_DIR / "bin" / "python").exists():
        print(f"\n❌ 虚拟环境不存在: {VENV_DIR / 'bin' / 'python'}")
        print("   请先创建: cd backend && python3 -m venv venv")
        sys.exit(1)

    # 执行打包步骤
    steps = [
        ("打包前端", build_frontend),
        ("创建主程序", create_server_main),
        ("打包后端", build_executable),
        ("最终整理", finalize),
    ]

    for name, func in steps:
        print(f"\n--- {name} ---")
        if not func():
            print(f"\n❌ 打包失败: {name}")
            sys.exit(1)

    print("\n" + "=" * 60)
    print("✅ 打包完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
