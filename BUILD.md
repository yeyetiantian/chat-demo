# DataPivot 打包说明

## 概述

本方案将 DataPivot 前后端打包成一个独立的 `.exe` 可执行文件，用户无需安装任何依赖即可直接运行。

## 打包流程

### 1. 准备工作

确保已安装以下环境：
- Python 3.8+
- Node.js 16+
- Git

### 2. 创建虚拟环境并安装依赖

```bash
# 进入后端目录
cd backend

# 创建虚拟环境
./venv/bin/python -m venv venv

# 激活虚拟环境
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows

# 安装后端依赖
pip install -r requirements.txt
```

### 3. 打包前端

```bash
# 在项目根目录
cd ..

# 打包前端
python build.py
```

打包脚本会自动执行以下步骤：
1. **打包前端**: 运行 `npm run build` 生成静态文件
2. **创建主程序**: 生成 `server_main.py`（集成 FastAPI + 静态文件托管）
3. **打包后端**: 使用 PyInstaller 打包成 `.exe`
4. **最终整理**: 复制可执行文件、创建启动脚本、生成 README

### 4. 运行打包后的程序

打包完成后，会在 `dist/` 目录生成以下文件：

```
dist/
├── DataPivot.exe          # 主程序可执行文件
├── 启动 DataPivot.bat     # 启动脚本
└── README.txt             # 使用说明
```

**运行方式**：
1. 双击 `启动 DataPivot.bat`
2. 程序会自动启动后端服务
3. 1.5 秒后自动打开浏览器访问 http://localhost:8080
4. 关闭控制台窗口将终止整个程序

## 技术方案

### 1. 前端打包

使用 Vite 打包生成静态文件：
```bash
npm run build
```

输出目录：`frontend/dist/`

### 2. 后端打包

使用 PyInstaller 将 FastAPI 应用打包成单文件可执行程序：

**关键配置**：
- `--onefile`: 打包成单个 `.exe` 文件
- `--console`: 保留控制台窗口（不隐藏）
- `--add-data`: 添加静态文件和数据库到打包文件
  - `index.html;.` - 前端入口
  - `frontend/dist;frontend/dist` - 前端静态资源
  - `vcloud_duck.db;.` - 数据库文件
- `--exclude-module`: 排除不需要的模块（tkinter, matplotlib, numpy）
- `--noupx`: 不压缩，加快启动速度

### 3. 静态文件托管

在 `server_main.py` 中实现 SPA 路由中间件：

```python
class SPAStaticMiddleware(BaseHTTPMiddleware):
    """SPA 路由中间件：非 API 请求返回 index.html"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # API 路径直接转发
        if path.startswith("/api/"):
            return await call_next(request)

        # 静态资源直接返回
        if path.startswith("/static/"):
            static_file = Path(path[8:])
            if static_file.exists():
                return FileResponse(static_file)

        # 其他路径返回 index.html（支持 SPA 路由）
        return FileResponse(Path("index.html"))
```

### 4. 自动打开浏览器

在 `startup` 事件中启动浏览器：

```python
@app.on_event("startup")
async def startup():
    def open_browser():
        import time
        time.sleep(1.5)
        webbrowser.open("http://localhost:8080")

    threading.Thread(target=open_browser, daemon=True).start()
```

## 打包后的目录结构

```
dist/
├── DataPivot.exe          # 可执行文件（约 50-100MB）
├── 启动 DataPivot.bat     # Windows 启动脚本
├── README.txt             # 使用说明
└── (临时文件)             # PyInstaller 生成
```

## 使用说明

### Windows 用户

1. **首次运行**：
   - 双击 `启动 DataPivot.bat`
   - 程序会自动启动并打开浏览器
   - 在浏览器中访问 http://localhost:8080

2. **正常使用**：
   - 所有功能正常工作（AI 对话、拖拽透视、Chat Demo 联动）
   - API 文档：http://localhost:8080/docs

3. **关闭程序**：
   - 直接关闭控制台窗口即可
   - 或在浏览器中关闭所有标签页

### Linux/Mac 用户

如果需要在 Linux/Mac 上运行，可以修改 `build.py` 中的启动脚本部分，创建 `.sh` 脚本。

## 注意事项

### 1. 数据库文件

确保 `vcloud_duck.db` 文件与可执行文件在同一目录，或确保打包时已正确添加。

### 2. 端口占用

程序默认使用端口 8080，如果被占用会启动失败。可以修改 `server_main.py` 中的端口号：

```python
uvicorn.run(app, host="127.0.0.1", port=8080)
```

### 3. 打包时间

首次打包可能需要 5-10 分钟（取决于机器性能）。

### 4. 文件大小

- 前端静态文件：约 2-5 MB
- 后端依赖：约 50-100 MB
- 总计：约 50-100 MB

### 5. 路由支持

打包后的程序完全支持 SPA 路由，所有前端路由（`/chat`、`/pivot`、`/dashboard`）都能正常工作。

## 故障排除

### 问题 1: 程序启动后立即退出

**原因**：依赖未安装或数据库文件缺失

**解决**：
1. 确保已安装所有依赖：`pip install -r requirements.txt`
2. 确保数据库文件 `vcloud_duck.db` 存在

### 问题 2: 浏览器未自动打开

**原因**：防火墙阻止或浏览器未安装

**解决**：
1. 手动在浏览器中访问 http://localhost:8080
2. 检查防火墙设置

### 问题 3: 静态文件无法加载

**原因**：PyInstaller 打包时未正确添加静态文件

**解决**：
1. 检查 `build.py` 中的 `--add-data` 参数
2. 确保 `frontend/dist/` 目录存在且包含所有文件

### 问题 4: API 请求失败

**原因**：CORS 配置或路由未正确导入

**解决**：
1. 检查 `server_main.py` 中的路由导入
2. 确保所有 API 模块都已正确配置

## 测试打包后的程序

使用测试脚本验证打包结果：

```bash
python test_build.py
```

测试脚本会：
1. 启动打包后的程序
2. 测试 API 响应
3. 测试静态文件加载
4. 正常停止程序

## 重新打包

如果需要重新打包：

```bash
# 1. 清理旧的打包文件
rm -rf dist/

# 2. 运行打包脚本
python build.py
```

## 高级配置

### 修改程序图标

在 `build.py` 中添加 `--icon` 参数：

```bash
pyinstaller_cmd = [
    ...
    "--icon=icon.ico",  # 指定图标文件路径
    ...
]
```

### 修改启动延迟

修改 `server_main.py` 中的延迟时间：

```python
def open_browser():
    import time
    time.sleep(2.0)  # 修改延迟时间（秒）
    webbrowser.open("http://localhost:8080")
```

### 添加更多依赖

在 `build.py` 中添加更多 `--add-data` 参数：

```bash
pyinstaller_cmd = [
    ...
    "--add-data", "config.json;.",  # 添加配置文件
    "--add-data", "assets/images;assets/images",  # 添加资源文件
    ...
]
```

## 许可证

本打包方案遵循 DataPivot 项目的开源许可证。

## 联系方式

如有问题，请提交 Issue 或联系开发团队。
