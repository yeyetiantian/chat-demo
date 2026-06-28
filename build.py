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

_pyi_cache_default = Path.home() / ".cache" / "pyinstaller"
_pyi_cache_candidates = [
    Path(os.getenv("PYINSTALLER_CONFIG_DIR", "")) if os.getenv("PYINSTALLER_CONFIG_DIR") else None,
    Path(__file__).parent / ".pyinstaller_cache",
    Path("/tmp") / "pyinstaller_cache",
    _pyi_cache_default,
]
_pyi_cache_candidates = [c for c in _pyi_cache_candidates if c is not None]
for _c in _pyi_cache_candidates:
    try:
        _c.mkdir(parents=True, exist_ok=True)
        if os.access(str(_c), os.W_OK):
            os.environ["PYINSTALLER_CONFIG_DIR"] = str(_c)
            break
    except OSError:
        continue

PROJECT_ROOT = Path(__file__).parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
BUILD_DIR = PROJECT_ROOT / "dist"
VENV_DIR = BACKEND_DIR / "venv"

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
EXEC_SUFFIX = ".exe" if IS_WIN else ""
EXECUTABLE = BUILD_DIR / f"DataPivot{EXEC_SUFFIX}"
SEP = os.pathsep


def run(cmd, cwd=None, shell=False):
    """运行命令"""
    print(f"  执行: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=shell)
    if result.returncode != 0:
        print(f"  ❌ 失败: {result.stderr or result.stdout}")
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
    # 诊断（不暴露 key 内容）
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


def _stage_build_files():
    """把需要的资源复制到 BACKEND_DIR 以便 PyInstaller 打包时通过相对路径引用"""
    db_src = PROJECT_ROOT / "vcloud_duck.db"
    db_dst = BACKEND_DIR / "vcloud_duck.db"
    if db_src.exists() and not db_dst.exists():
        shutil.copy2(db_src, db_dst)
        print(f"  📦 复制数据库 -> {db_dst}")

    index_src = FRONTEND_DIR / "dist" / "index.html"
    index_dst = BACKEND_DIR / "index.html"
    if index_src.exists():
        shutil.copy2(index_src, index_dst)
        print(f"  📦 复制 index.html -> {index_dst}")

    fe_src = FRONTEND_DIR / "dist"
    fe_dst = BACKEND_DIR / "frontend" / "dist"
    if fe_src.exists():
        if fe_dst.exists():
            shutil.rmtree(fe_dst)
        shutil.copytree(fe_src, fe_dst)
        print(f"  📦 复制前端产物 -> {fe_dst}")

    # 打包内置 .env（含 API Key），优先级最低（dist 同目录 .env / 系统 env 仍可覆盖）
    env_candidates = [
        BACKEND_DIR / "app" / ".env",
        PROJECT_ROOT / ".env",
        BACKEND_DIR / ".env",
    ]
    env_dst = BACKEND_DIR / ".env"
    for env_src in env_candidates:
        if env_src.exists() and env_src.resolve() != env_dst.resolve():
            shutil.copy2(env_src, env_dst)
            print(f"  📦 内置 API Key (.env) -> {env_dst} (来自 {env_src.name})")
            break


def _clean_staged_files():
    for rel in ["vcloud_duck.db", "index.html", ".env", "frontend/dist", "frontend"]:
        p = BACKEND_DIR / rel
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass
        elif p.is_dir() and rel in ("frontend/dist", "frontend"):
            if rel == "frontend/dist" and p.exists():
                shutil.rmtree(p)
                parent = p.parent
                try:
                    parent.rmdir()
                except OSError:
                    pass
            elif rel == "frontend":
                pass


def build_executable():
    """打包后端"""
    print("\n[3/4] 打包后端...")

    _stage_build_files()

    venv_python = VENV_DIR / "bin" / "python"
    if not venv_python.exists():
        venv_python = VENV_DIR / "Scripts" / "python.exe"
    if not venv_python.exists():
        print(f"  ❌ 虚拟环境 Python 不存在: {venv_python}")
        return False

    work_dir = BUILD_DIR / "pyi_work"
    build_out = BUILD_DIR / "backend_dist"
    for d in (work_dir, build_out):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(venv_python), "-m", "PyInstaller",
        "--onefile", "--console",
        "--name", "DataPivot",
        "--clean",
        "--workpath", str(work_dir),
        "--distpath", str(build_out),
        "--collect-all", "databao",
        "--collect-all", "edaplot",
        f"--add-data", f"{BACKEND_DIR / 'index.html'}{SEP}.",
        f"--add-data", f"{BACKEND_DIR / 'frontend'}{SEP}frontend",
        f"--add-data", f"{BACKEND_DIR / 'vcloud_duck.db'}{SEP}.",
        f"--add-data", f"{BACKEND_DIR / '.env'}{SEP}.",
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        "--noupx",
        "app/server_main.py",
    ]

    ok = run(cmd, cwd=BACKEND_DIR)
    try:
        _clean_staged_files()
    except Exception as e:
        print(f"  ⚠️  清理临时文件失败: {e}")

    if not ok:
        return False

    built = build_out / f"DataPivot{EXEC_SUFFIX}"
    if not built.exists():
        for cand in build_out.rglob(f"DataPivot{EXEC_SUFFIX}"):
            built = cand
            break
    if not built.exists():
        print(f"  ❌ 打包产物未找到: {built}")
        return False

    print(f"  ✅ 后端打包成功: {built}")
    return True


def finalize():
    """最终整理"""
    print("\n[4/4] 最终整理...")

    temp_dir = BUILD_DIR / "backend_dist"
    built_src = temp_dir / f"DataPivot{EXEC_SUFFIX}"
    if not built_src.exists():
        for cand in temp_dir.rglob(f"DataPivot{EXEC_SUFFIX}"):
            built_src = cand
            break

    if not built_src.exists():
        print(f"  ❌ 找不到打包产物: {built_src}")
        return False

    EXECUTABLE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built_src, EXECUTABLE)
    if IS_MAC or not IS_WIN:
        try:
            os.chmod(EXECUTABLE, 0o755)
        except OSError:
            pass
    print(f"  ✅ 可执行文件: {EXECUTABLE}")

    if temp_dir.exists():
        try:
            shutil.rmtree(temp_dir)
            print(f"  🧹 清理临时目录: {temp_dir}")
        except OSError as e:
            print(f"  ⚠️  清理临时目录失败: {e}")

    work_dir = BUILD_DIR / "pyi_work"
    if work_dir.exists():
        try:
            shutil.rmtree(work_dir)
        except OSError:
            pass

    for spec_path in (BUILD_DIR / "DataPivot.spec", BACKEND_DIR / "DataPivot.spec"):
        if spec_path.exists():
            try:
                spec_path.unlink()
            except OSError:
                pass

    launcher_bat = BUILD_DIR / "启动 DataPivot.bat"
    launcher_bat.write_text("""@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
echo ========================================
echo   DataPivot 启动中...
echo ========================================
echo.

REM 加载同目录下的 .env 文件（若存在，覆盖默认内置 Key）
if exist ".env" (
    echo [i] 加载配置文件: "%~dp0.env"
    for /f "usebackq eol=# tokens=1,* delims==" %%K in (".env") do (
        set "_KEY=%%K"
        setlocal EnableDelayedExpansion
        if not "!_KEY!"=="" (
            endlocal
            set "%%K=%%L" 2>nul
        ) else (
            endlocal
        )
    )
    echo.
) else (
    echo [i] 未找到 .env，使用内置 API Key
    echo.
)

echo [i] 程序将在服务就绪后自动打开浏览器...
echo [i] 关闭本窗口将终止 DataPivot 服务
echo.

REM 前台运行（可执行文件始终在脚本同目录）
if exist "%~dp0DataPivot.exe" (
    "%~dp0DataPivot.exe"
) else (
    echo [错误] 同目录下未找到 DataPivot.exe
    pause
    exit /b 1
)
pause
""", encoding='utf-8')
    print(f"  ✅ 启动脚本 (Windows): {launcher_bat}")

    launcher_sh = BUILD_DIR / "启动 DataPivot.sh"
    launcher_sh.write_text(r"""#!/bin/bash
# DataPivot 启动脚本 (macOS / Linux)
# 无关键失败就退出 (不使用 set -e)

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR" || { echo "[错误] 无法进入脚本目录: $SCRIPT_DIR"; exit 1; }

echo "========================================"
echo "  DataPivot 启动中..."
echo "========================================"
echo

EXE="$SCRIPT_DIR/DataPivot"
if [ -f "$SCRIPT_DIR/DataPivot.exe" ]; then
    EXE="$SCRIPT_DIR/DataPivot.exe"
fi
if [ ! -f "$EXE" ]; then
    echo "[错误] 找不到可执行文件: $EXE"
    echo "请确认该脚本与 DataPivot (或 DataPivot.exe) 在同一目录。"
    read -r _unused
    exit 1
fi
chmod +x "$EXE" 2>/dev/null

if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "[i] 加载配置文件: $SCRIPT_DIR/.env (将覆盖内置 API Key)"
    while IFS= read -r line || [ -n "$line" ]; do
        line="$(printf '%s' "$line" | sed -e 's/#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        [ -z "$line" ] && continue
        case "$line" in
            *=*) : ;;
            *) continue ;;
        esac
        key=${line%%=*}
        val=${line#*=}
        # 去掉 key 首尾空格，并校验是合法 shell 变量名（字母数字下划线，非数字开头）
        key=$(printf '%s' "$key" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
        case "$key" in
            '' | [0-9]*) continue ;;
            *[!A-Za-z0-9_]*) continue ;;
        esac
        # 去掉 val 首尾空白、双引号、单引号（sed 单引号模式，无语法歧义）
        val=$(printf '%s' "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
        val=$(printf '%s' "$val" | sed -e 's/^"//' -e 's/"$//')
        val=$(printf '%s' "$val" | sed -e "s/^'//" -e "s/'\$//")
        export "$key=$val"
    done < "$SCRIPT_DIR/.env"
    echo
else
    echo "[i] 未找到 .env，使用内置 API Key"
    echo
fi

echo "[i] 程序将在服务就绪后自动打开浏览器..."
echo "[i] 按 Ctrl+C 或关闭本窗口将终止 DataPivot 服务"
echo

exec "$EXE"
""", encoding='utf-8')
    try:
        os.chmod(launcher_sh, 0o755)
    except OSError:
        pass
    print(f"  ✅ 启动脚本 (macOS/Linux): {launcher_sh}")

    readme = BUILD_DIR / "README.txt"
    readme.write_text(f"""DataPivot 打包文件

使用说明:
1. AI API Key 已内置到可执行文件，开箱即用，无需额外配置。
   【可选覆盖】若需要替换为自己的 Key，可在本目录 (与 DataPivot{EXEC_SUFFIX} 同级)
   创建 .env 文件：
     DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
     DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
   也可使用 OPENAI_API_KEY 兼容变量。

2. 双击启动脚本：
     - Windows:  启动 DataPivot.bat
     - macOS/Linux: 启动 DataPivot.sh
   或直接运行可执行文件 DataPivot{EXEC_SUFFIX}

3. 程序启动后会自动探测端口就绪，然后打开浏览器访问 http://localhost:8080
   首次启动 (PyInstaller onefile 解压) 可能需要 10~30 秒，请耐心等待。

4. 关闭控制台窗口将终止程序。

API 文档: http://localhost:8080/docs
""", encoding='utf-8')
    print(f"  ✅ 文档说明: README.txt")
    return True


def ensure_venv() -> bool:
    """若 backend/venv 不存在，自动创建并安装依赖（requirements + pyinstaller）。"""
    venv_py = VENV_DIR / "bin" / "python"
    if not venv_py.exists():
        venv_py = VENV_DIR / "Scripts" / "python.exe"

    if venv_py.exists():
        return True

    print("\n[0/4] 准备后端虚拟环境...")
    host_python = sys.executable
    if not host_python:
        print("  ❌ 无法确定宿主机 Python 解释器路径")
        return False

    print(f"  创建 venv: {VENV_DIR}")
    if not run([host_python, "-m", "venv", str(VENV_DIR)]):
        print(f"  ❌ 创建 venv 失败")
        return False

    venv_py = VENV_DIR / "bin" / "python"
    if not venv_py.exists():
        venv_py = VENV_DIR / "Scripts" / "python.exe"
    if not venv_py.exists():
        print("  ❌ venv 解释器仍不存在: " + str(venv_py))
        return False

    req_txt = BACKEND_DIR / "requirements.txt"
    if req_txt.exists():
        print("  安装 requirements.txt ...")
        if not run([str(venv_py), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"]):
            print("  ⚠️  升级 pip 失败，继续")
        if not run([str(venv_py), "-m", "pip", "install", "-r", str(req_txt)]):
            print("  ❌ 安装依赖失败")
            return False
    else:
        print(f"  ⚠️  未找到 requirements.txt: {req_txt}")

    print("  安装 PyInstaller ...")
    if not run([str(venv_py), "-m", "pip", "install", "pyinstaller>=6.0"]):
        print("  ❌ 安装 PyInstaller 失败")
        return False

    print("  ✅ 虚拟环境初始化完成")
    return True


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("DataPivot 打包脚本")
    print(f"平台: {sys.platform} | Python: {platform.python_version()}")
    print("=" * 60)

    if not ensure_venv():
        sys.exit(1)

    venv_py = VENV_DIR / "bin" / "python"
    if not venv_py.exists():
        venv_py = VENV_DIR / "Scripts" / "python.exe"
    if not venv_py.exists():
        print("\n❌ 虚拟环境不存在，请先在 backend 目录创建 venv")
        sys.exit(1)

    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    if not build_frontend():
        sys.exit(1)
    if not create_server_main():
        sys.exit(1)
    if not build_executable():
        sys.exit(1)
    if not finalize():
        sys.exit(1)

    print("\n" + "=" * 60)
    print("✅ 打包完成！")
    print(f"   输出目录: {BUILD_DIR}")
    print(f"   可执行文件: {EXECUTABLE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
