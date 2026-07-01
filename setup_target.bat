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
