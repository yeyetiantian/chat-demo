#!/bin/bash
# ==========================================================
# DataPivot 迁移打包脚本
# 在本机（有网络）运行，生成一个离线压缩包
# 拷贝到目标电脑解压即可直接开发
# ==========================================================
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_NAME="DataPivot-Offline-Dev"

echo "========================================"
echo " DataPivot 离线开发包准备"
echo "========================================"
echo "本机: $(python3 --version) | $(node --version)"
echo "目标: Python 3.10 | Node 18"
echo ""

# 清空上次的离线包
rm -rf "$PROJECT_ROOT/pip_offline"
mkdir -p "$PROJECT_ROOT/pip_offline"

# ---------- 第 1 步: 下载 Python 依赖 ----------
echo "[1/4] 下载 Python 依赖（兼容 Python 3.10）..."

cd "$PROJECT_ROOT/backend"

# 先确保 venv 里的 pip 是最新的
"$PROJECT_ROOT/backend/venv/bin/pip" install --upgrade pip --quiet

# 下载项目依赖（兼容 3.10）
"$PROJECT_ROOT/backend/venv/bin/pip" download \
  -r requirements.txt \
  -d "$PROJECT_ROOT/pip_offline" \
  --python-version 3.10 \
  --only-binary cryptography 2>&1 | tail -5

# 下载 databao-agent
"$PROJECT_ROOT/backend/venv/bin/pip" download \
  databao-agent \
  -d "$PROJECT_ROOT/pip_offline" \
  --python-version 3.10 \
  --only-binary cryptography 2>&1 | tail -3

# 下载 PyInstaller（可选，如果要打包）
"$PROJECT_ROOT/backend/venv/bin/pip" download \
  pyinstaller \
  -d "$PROJECT_ROOT/pip_offline" 2>&1 | tail -3

COUNT=$(ls "$PROJECT_ROOT/pip_offline"/*.whl 2>/dev/null | wc -l)
echo "  ✅ 已下载 $COUNT 个 wheel 包"

# ---------- 第 2 步: 创建目标环境安装脚本 ----------
echo "[2/4] 生成目标电脑安装脚本..."

cat > "$PROJECT_ROOT/setup_target.sh" << 'SETUPEOF'
#!/bin/bash
# ==========================================================
# DataPivot 目标环境安装脚本（在目标电脑上运行一次即可）
# ==========================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo " DataPivot 开发环境安装"
echo " 本机: $(python3 --version)"
echo "========================================"
echo ""

# 1. 创建 venv
echo "[1/4] 创建虚拟环境..."
if [ -d "backend/venv" ]; then
  echo "  ⚠️  venv 已存在，跳过"
else
  python3 -m venv backend/venv
  echo "  ✅ venv 已创建"
fi

# 2. 离线安装 Python 依赖
echo "[2/4] 安装 Python 依赖..."
cd backend
./venv/bin/pip install --no-index --find-links ../pip_offline -r requirements.txt 2>&1 | tail -3
./venv/bin/pip install --no-index --find-links ../pip_offline databao-agent --only-binary cryptography 2>&1 | tail -3
echo "  ✅ Python 依赖已安装"

# 验证
./venv/bin/python -c "
import duckdb, fastapi, uvicorn, databao
print(f'  ✅ duckdb: {duckdb.__version__}')
print(f'  ✅ fastapi: {fastapi.__version__}')
print(f'  ✅ databao: 已加载')
"
cd ..

# 3. 安装前端依赖
echo "[3/4] 安装前端依赖..."
cd frontend
if [ -d "node_modules" ]; then
  echo "  ⚠️  node_modules 已存在，跳过"
else
  npm ci 2>&1 | tail -3
  echo "  ✅ 前端依赖已安装"
fi
cd ..

# 4. 创建快捷启动脚本
echo "[4/4] 创建启动脚本..."
cat > start_backend.sh << 'STARTEOF'
#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo "  DataPivot 后端启动 (port 8080)"
echo "========================================"
cd backend && ./venv/bin/python run.py
STARTEOF
chmod +x start_backend.sh

cat > start_frontend.sh << 'STARTEOF'
#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo "  DataPivot 前端启动 (port 3000)"
echo "========================================"
cd frontend && npm run dev
STARTEOF
chmod +x start_frontend.sh

echo ""
echo "========================================"
echo " ✅ 安装完成！"
echo "========================================"
echo ""
echo "启动方式（需要两个终端）:"
echo ""
echo "  # 终端 1: 启动后端"
echo "  ./start_backend.sh"
echo ""
echo "  # 终端 2: 启动前端"
echo "  ./start_frontend.sh"
echo ""
echo "  浏览器访问: http://localhost:3000"
echo "========================================"
SETUPEOF

chmod +x "$PROJECT_ROOT/setup_target.sh"

# ---------- 第 3 步: 创建 Windows 版安装脚本 ----------
echo "[3/4] 生成 Windows 安装脚本..."

cat > "$PROJECT_ROOT/setup_target.bat" << 'BATEOF'
@echo off
chcp 65001 >nul
echo ========================================
echo  DataPivot 开发环境安装
echo ========================================
echo.

REM 1. 创建 venv
echo [1/4] 创建虚拟环境...
if exist backend\venv (
  echo   venv 已存在，跳过
) else (
  python -m venv backend\venv
  echo   ✅ venv 已创建
)

REM 2. 安装 Python 依赖
echo [2/4] 安装 Python 依赖...
cd backend
.\venv\Scripts\pip install --no-index --find-links ..\pip_offline -r requirements.txt
.\venv\Scripts\pip install --no-index --find-links ..\pip_offline databao-agent --only-binary cryptography
echo   ✅ Python 依赖已安装
cd ..

REM 3. 安装前端依赖
echo [3/4] 安装前端依赖...
cd frontend
if exist node_modules (
  echo   node_modules 已存在，跳过
) else (
  npm ci
  echo   ✅ 前端依赖已安装
)
cd ..

echo.
echo ========================================
echo  ✅ 安装完成
echo ========================================
echo.
echo 启动方式（需要两个终端）:
echo.
echo  终端 1: cd backend ^&^& .\venv\Scripts\python run.py
echo  终端 2: cd frontend ^&^& npm run dev
echo.
echo  浏览器访问: http://localhost:3000
echo.
pause
BATEOF

# ---------- 第 4 步: 打包 ----------
echo "[4/4] 打包离线压缩包..."

cd "$PROJECT_ROOT"
tar -czf "../${OUTPUT_NAME}.tar.gz" \
  --exclude=node_modules \
  --exclude=__pycache__ \
  --exclude=.git \
  --exclude="*.pyc" \
  --exclude=.DS_Store \
  --exclude="dist" \
  --exclude="backend/logs/traces" \
  --exclude="backend/logs/charts" \
  --exclude="backend/logs/threads" \
  --exclude="backend/venv" \
  --exclude="frontend/dist" \
  --exclude="*.tar.gz" \
  .

echo ""
echo "========================================"
echo " ✅ 打包完成！"
echo "========================================"
echo ""
echo "输出文件: ../${OUTPUT_NAME}.tar.gz"
echo "大小: $(du -h "../${OUTPUT_NAME}.tar.gz" | cut -f1)"
echo ""
echo "迁移步骤:"
echo "  1. 将 ${OUTPUT_NAME}.tar.gz 拷到目标电脑"
echo "  2. 解压: tar -xzf ${OUTPUT_NAME}.tar.gz"
echo "  3. 运行安装: ./setup_target.sh (Mac/Linux)"
echo "     或双击 setup_target.bat (Windows)"
echo "  4. 启动开发:"
echo "     终端1: ./start_backend.sh"
echo "     终端2: ./start_frontend.sh"
echo "========================================"
