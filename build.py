#!/usr/bin/env python3
"""
DataPivot 打包脚本
将前后端打包成单个可执行文件
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
BUILD_DIR = PROJECT_ROOT / "dist"
VENV_DIR = BACKEND_DIR / "venv"

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
EXEC_SUFFIX = ".exe" if IS_WIN else ""
EXECUTABLE = BUILD_DIR / f"DataPivot{EXEC_SUFFIX}"
SEP = ";" if IS_WIN else ":"

# 虚拟环境中的 python/pip 路径（跨平台）
_VENV_PYTHON = VENV_DIR / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")
_VENV_PIP = VENV_DIR / ("Scripts" if IS_WIN else "bin") / ("pip.exe" if IS_WIN else "pip")


def _print_step(step: str, total: int, current: int):
    bar = "█" * int(40 * current / total) + "░" * (40 - int(40 * current / total))
    print(f"\r[{bar}] {step} {current}/{total}", end="", flush=True)


def run(cmd, cwd=None):
    """运行命令（强制子进程以 UTF-8 交互，避免 Windows CP1252 解码崩溃）"""
    print(f"  执行: {' '.join(cmd)}")
    sub_env = os.environ.copy()
    sub_env["PYTHONUTF8"] = "1"
    sub_env["PYTHONIOENCODING"] = "utf-8:surrogateescape"
    # Windows：CHCP 是 cmd.exe 命令，不是环境变量，这里不设
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env=sub_env,
        )
    except Exception as e:
        print(f"  ❌ 子进程启动失败: {e}")
        return False
    if result.returncode != 0:
        tail_out = (result.stdout or "").strip()
        tail_err = (result.stderr or "").strip()
        output = tail_err or tail_out or "(无输出，exit={result.returncode})"
        if len(output) > 4000:
            output = output[:2000] + "\n...[中间省略]...\n" + output[-2000:]
        print(f"  ❌ 失败 (exit={result.returncode}):\n{output}")
        return False
    return True


# ============================================================
# 步骤 0: 准备虚拟环境
# ============================================================
def ensure_venv():
    """确保虚拟环境存在 & 安装好依赖"""
    print("\n[0/5] 准备虚拟环境...")

    if not _VENV_PYTHON.exists():
        print(f"  ⚠️  虚拟环境不存在，正在创建...")
        if IS_WIN:
            if not run([sys.executable, "-m", "venv", str(VENV_DIR)]):
                return False
        else:
            if not run([sys.executable, "-m", "venv", str(VENV_DIR)]):
                return False
        print("  ✅ 虚拟环境已创建")
    else:
        print(f"  ✅ 虚拟环境已存在: {_VENV_PYTHON}")

    # 升级 pip
    run([str(_VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip", "--quiet"])

    # 安装后端依赖（包含 PyInstaller）
    req_file = BACKEND_DIR / "requirements.txt"
    if req_file.exists():
        print("  安装后端依赖...")
        run([str(_VENV_PYTHON), "-m", "pip", "install", "-r", str(req_file), "--quiet"])
    else:
        print("  ⚠️  requirements.txt 不存在，跳过依赖安装")

    # 确保 PyInstaller 已安装
    print("  安装 PyInstaller...")
    run([str(_VENV_PYTHON), "-m", "pip", "install", "pyinstaller", "--quiet"])

    # 安装 databao-agent（Chat Demo 底层依赖，必须预先安装好才能被 PyInstaller 收集）
    print("  安装 databao-agent...")
    run([str(_VENV_PYTHON), "-m", "pip", "install", "databao-agent", "--only-binary", "cryptography", "--quiet"])

    print("  ✅ 虚拟环境就绪")
    return True


# ============================================================
# 步骤 1: 打包前端
# ============================================================
def build_frontend():
    """打包前端"""
    print("\n[1/5] 打包前端...")
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


# ============================================================
# 步骤 2: 创建主程序
# ============================================================
def create_server_main():
    """创建主程序（FastAPI + 静态文件托管）"""
    print("\n[2/5] 创建主程序...")

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
    # 诊断（不暴露 key 内容）
    try:
        from app.config import DEEPSEEK_API_KEY as _k1
        import os as _os
        _k2 = _os.getenv("OPENAI_API_KEY", "")
        _status = "✅ 已配置 (DEEPSEEK_API_KEY)" if _k1 else (
            "✅ 已配置 (OPENAI_API_KEY)" if _k2 else "\\u26a0\\ufe0f  未配置（AI 对话功能不可用）"
        )
        print(f"   AI API Key: {_status}")
        if not (_k1 or _k2):
            print("   \\u2192 请在可执行文件同目录创建 .env 文件，例如：")
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
    print("\\n\\u2705 DataPivot \\u5df2\\u542f\\u52a8: http://localhost:8080")
    print(f"   \\u8d44\\u6e90\\u76ee\\u5f55: {BASE_DIR}")
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


# ============================================================
# 步骤 3: 打包后端
# ============================================================
def build_executable():
    """打包后端"""
    print("\n[3/5] 打包后端...")

    cmd = [
        str(_VENV_PYTHON), "-m", "PyInstaller",
        "--onefile",
        "--console",
        "--name", "DataPivot",
        "--add-data", f"frontend/dist{SEP}frontend/dist",
        # vcloud_duck.db 不内置到 exe，放同目录让用户可替换
        # hidden imports: databao 精确导入（只导入当前用到的模块，避免收集到有问题的子包）
        "--hidden-import", "databao",
        "--hidden-import", "databao.agent",
        "--hidden-import", "databao.agent.api",
        "--hidden-import", "databao.agent.configs",
        "--hidden-import", "databao.agent.configs.agent",
        "--hidden-import", "databao.agent.configs.llm",
        "--hidden-import", "databao.agent.core",
        "--hidden-import", "databao.agent.core.agent",
        "--hidden-import", "databao.agent.core.domain",
        "--hidden-import", "databao.agent.core.executor",
        "--hidden-import", "databao.agent.core.thread",
        "--hidden-import", "databao.agent.core.visualizer",
        "--hidden-import", "databao.agent.duckdb",
        "--hidden-import", "databao.agent.duckdb.react_tools",
        "--hidden-import", "databao.agent.duckdb.schema_inspection",
        "--hidden-import", "databao.agent.executors",
        "--hidden-import", "databao.agent.executors.react_duckdb",
        "--hidden-import", "databao.agent.executors.prompt",
        "--hidden-import", "databao.agent.executors.llm",
        "--hidden-import", "databao.agent.domains",
        "--hidden-import", "databao.agent.databases",
        "--hidden-import", "databao.agent.databases.database_adapter",
        "--hidden-import", "databao.agent.databases.database_connection",
        "--hidden-import", "databao.agent.databases.databases",
        "--hidden-import", "databao.agent.databases.duckdb_adapter",
        "--hidden-import", "databao.agent.visualizers",
        "--hidden-import", "databao.agent.visualizers.vega_chat",
        "--hidden-import", "databao.subagents",
        "--hidden-import", "databao.subagents.shared",
        "--hidden-import", "databao.subagents.shared.introspection",
        "--hidden-import", "databao.subagents.shared.introspection.introspectors",
        "--hidden-import", "databao.subagents.shared.introspection.introspectors.duckdb",
        "--hidden-import", "databao.subagents.shared.introspection.introspectors.duckdb.duckdb_introspector",
        "--hidden-import", "databao.subagents.shared.introspection.introspectors.duckdb.connection_config",
        "--hidden-import", "databao.subagents.shared.introspection.introspectors.databases_types",
        "--hidden-import", "databao.subagents.shared.plotting",
        "--hidden-import", "databao.subagents.shared.llm_utils",
        "--hidden-import", "databao.subagents.shared.logging",
        # 收集 databao 的非代码数据文件（prompts、模板等）
        "--collect-all", "databao",
        # langchain + AI 框架依赖
        "--hidden-import", "langchain_openai",
        "--hidden-import", "langchain_community",
        "--hidden-import", "langchain_core",
        "--hidden-import", "langchain_core.language_models",
        "--hidden-import", "langchain_core.language_models.chat_models",
        "--hidden-import", "langchain_core.tools",
        "--hidden-import", "langgraph",
        # 标准库：防止 PyInstaller tree-shaking 误删
        "--hidden-import", "os",
        "--hidden-import", "re",
        "--hidden-import", "uuid",
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        "--noupx",
        "--distpath", str(BUILD_DIR / "backend_dist"),
        f"backend/app/server_main.py"
    ]

    # 内嵌 .env（仅在 CI 中存在，由 workflow 从 Secrets 写入，不会进 git）
    # 用户拿到 exe 后可在同目录放自己的 .env 覆盖内置值
    env_file = BACKEND_DIR / "app" / ".env"
    if env_file.exists():
        cmd.extend(["--add-data", f"{env_file}{SEP}app/.env"])
        print("  📄 已内嵌 .env（API Key 来自 CI Secrets）")

    if not run(cmd, cwd=PROJECT_ROOT):
        return False
    print("  ✅ 后端打包成功")
    return True


# ============================================================
# 步骤 4: 复制可执行文件
# ============================================================
def copy_executable():
    """从 PyInstaller 输出目录复制可执行文件到 dist/"""
    print("\n[4/5] 复制可执行文件...")

    # PyInstaller 在 Windows 上输出为 DataPivot.exe，Unix 上为 DataPivot
    # 先统一无后缀名搜索，再按平台特定后缀名
    candidates = [
        BUILD_DIR / "backend_dist" / f"DataPivot{EXEC_SUFFIX}",  # 平台标准后缀
        BUILD_DIR / "backend_dist" / "DataPivot",                # 无后缀
    ]

    src = None
    for c in candidates:
        if c.exists():
            src = c
            break

    if src is None:
        print(f"  ⚠️  未找到可执行文件，请检查 {BUILD_DIR / 'backend_dist'}")
        return False

    shutil.copy2(src, EXECUTABLE)
    # Linux/macOS 确保可执行权限
    if not IS_WIN:
        EXECUTABLE.chmod(0o755)
    print(f"  ✅ 可执行文件: {EXECUTABLE} ({(EXECUTABLE.stat().st_size / 1024 / 1024):.0f} MB)")

    # 复制默认数据库到 dist/（不打包进 exe，放同目录让用户可替换）
    db_src = PROJECT_ROOT / "vcloud_duck.db"
    if db_src.exists():
        db_dst = BUILD_DIR / "vcloud_duck.db"
        shutil.copy2(db_src, db_dst)
        print(f"  ✅ 默认数据库: {db_dst} ({(db_dst.stat().st_size / 1024 / 1024):.0f} MB)")
    else:
        print(f"  ⚠️  未找到默认数据库 {db_src}，启动后需用户自备")
    return True


# ============================================================
# 步骤 5: 创建启动脚本 & 文档
# ============================================================
def create_launchers():
    """创建各平台启动脚本"""
    print("\n[5/5] 创建启动脚本...")

    # Windows
    if IS_WIN:
        bat = BUILD_DIR / "启动 DataPivot.bat"
        bat.write_text("""@echo off
chcp 65001 >nul
echo ========================================
echo   DataPivot \\u542f\\u52a8\\u4e2d...
echo ========================================
echo.
start "" "DataPivot.exe"
timeout /t 3 /nobreak >nul
start http://localhost:8080
echo.
echo ========================================
echo   \\u670d\\u52a1\\u5df2\\u542f\\u52a8
echo   \\u5173\\u95ed\\u6b64\\u7a97\\u53e3\\u5c06\\u7ec8\\u6b62\\u7a0b\\u5e8f
echo ========================================
pause
""", encoding='utf-8')
        print(f"  ✅ Windows 启动脚本: {bat}")

    # macOS
    if IS_MAC:
        cmd = BUILD_DIR / "启动 DataPivot.command"
        cmd.write_text("""#!/bin/bash
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
        cmd.chmod(0o755)
        print(f"  ✅ macOS 启动脚本: {cmd}")

    # Linux
    if IS_LINUX:
        sh = BUILD_DIR / "启动 DataPivot.sh"
        sh.write_text("""#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo "  DataPivot 启动中..."
echo "========================================"
echo ""
echo "[1/2] 启动后端服务..."
"./DataPivot" &
sleep 3
echo "[2/2] 打开浏览器..."
xdg-open http://localhost:8080
echo ""
echo "========================================"
echo "  服务已启动"
echo "  关闭 terminal 窗口将终止程序"
echo "========================================"
""", encoding='utf-8')
        sh.chmod(0o755)
        print(f"  ✅ Linux 启动脚本: {sh}")

    # README
    readme = BUILD_DIR / "README.txt"
    if not readme.exists():
        readme.write_text(f"""DataPivot 打包文件

使用说明:
1. 启动程序：双击对应平台的启动脚本
   - Windows: 双击 "启动 DataPivot.bat"
   - macOS: 双击 "启动 DataPivot.command"（首次可能需要 chmod +x）
   - Linux: 运行 "启动 DataPivot.sh"
2. 也可直接运行 DataPivot{EXEC_SUFFIX}
3. 程序会自动打开浏览器访问 http://localhost:8080
4. 关闭控制台窗口将终止程序

API 文档: http://localhost:8080/docs
""", encoding='utf-8')
        print(f"  ✅ 文档说明: {readme}")

    return True


def cleanup():
    """清理 PyInstaller 临时文件"""
    print("\n清理临时文件...")
    temp_dir = BUILD_DIR / "backend_dist"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
        print(f"  ✅ 已清理: {temp_dir}")

    # PyInstaller 在项目根目录生成 .spec 文件，清理
    spec_file = BACKEND_DIR / "server_main.spec"
    if spec_file.exists():
        spec_file.unlink()
        print(f"  ✅ 已清理: {spec_file}")

    # __pycache__
    build_dir = BACKEND_DIR / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print(f"  ✅ 已清理: {build_dir}")


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("DataPivot 打包脚本")
    print("=" * 60)
    print(f"  平台: {sys.platform}")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  输出: {EXECUTABLE}")

    steps = [
        ("准备虚拟环境", ensure_venv),
        ("打包前端", build_frontend),
        ("创建主程序", create_server_main),
        ("打包后端", build_executable),
        ("复制可执行文件", copy_executable),
        ("创建启动脚本 & 文档", create_launchers),
    ]

    total = len(steps)
    for i, (name, func) in enumerate(steps, 1):
        print(f"\n[{i}/{total}] {name}")
        if not func():
            print(f"\n❌ 打包失败: {name}")
            sys.exit(1)

    cleanup()

    print("\n" + "=" * 60)
    print("✅ 打包完成！")
    print("=" * 60)
    print(f"\n  🎯 可执行文件: {EXECUTABLE}")
    print(f"  📦 大小: {(EXECUTABLE.stat().st_size / 1024 / 1024):.0f} MB")
    print()


if __name__ == "__main__":
    main()
