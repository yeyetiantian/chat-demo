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
