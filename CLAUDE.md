# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

DataPivot v2.0 — 数据透视分析系统。基于真实 `vcloud_duck.db` 数据库（6 表关联），支持拖拽式数据透视、AI 对话式查询、Chat Demo 联动仪表盘，生成 6 种图表类型。

## 启动命令

**重要：后端所有操作必须在虚拟环境 `backend/venv/` 中执行**，包括安装依赖、运行代码、执行脚本等。

```bash
# 后端 (port 8080, hot-reload) — 在 venv 中运行
cd backend && ./venv/bin/python run.py

# 前端 (port 3000, /api 代理到 localhost:8080)
cd frontend && npm run dev

# 前端构建
cd frontend && npm run build

# 打包成单文件可执行程序
python build.py

# 测试打包后的程序
python test_build.py
```

## 技术栈

- **后端**: FastAPI + DuckDB (连接 `vcloud_duck.db` 只读) + DeepSeek API + Chat Demo 0.6.2 (内省 + Plotly 渲染)
- **前端**: Vue 3 + Vue Router 4 (hash 模式) + Pinia + Vega-Lite (vega-embed) + Axios
- **打包**: PyInstaller (单文件 .exe)
- 数据源：`vcloud_duck.db` (6 张真实业务表，只读模式)

## 数据库 Schema

`vcloud_duck.db` 包含 6 张表，关系如下：

```
TM_RMU_PS_TASK (714行) — 任务，CREATE_BY = 人员
├── TM_RMU_PS_TASK_VEHICLETYPE (714行) — 1:1 车型
├── TM_RMU_PS_TASK_VEHICLE (13,163行) — 1:N 车辆
└── TM_RMU_PS_TASK_RULE (3,109行) — 1:N 规则 (RULE_TYPE: 0=统计/1=报警/2=事件)
    └── TL_RMU_PS_TASK_RULE_RESULT (301行) — 1:1 报警结果
        └── TL_RMU_PS_TASK_RULE_RESULT_SIGNAL (23,127行) — 1:N 信号值 (243种信号)
```

后端在查询时使用 CTE（WITH 子句）将这些表 JOIN 为扁平化宽表，字段名映射为中文：人员、车型、车辆、任务、规则名称、规则类型、报警时间、持续时间等。

## 后端架构 (`backend/app/`)

```
api/
  pivot.py    → 数据透视聚合 + 下钻 (人员→任务→规则→报警→信号)
  chart.py    → 图表数据 + 推荐 + Chat Demo Plotly 渲染
  chat.py     → AI 对话 (DeepSeek API + SSE 流式/非流式)
  chatdemo.py → Chat Demo 内省 API (schema 浏览, 列信息, 数据画像)
  trace.py    → 链路追踪 (LLM 调用 + 工具调用日志)
services/
  duckdb_service.py       → DuckDB 单例 (只读), CTE 查询, 聚合/下钻/信号
  aggregation_service.py  → 聚合委托层
  chart_service.py        → 图表推荐 + 数据准备 + chatdemo Plotly 渲染
  chatdemo_service.py     → Chat Demo 集成 (DuckDB 内省 + Plotly)
  trace_service.py        → 全链路追踪 (monkey-patch LLM + Tool 调用)
models/schema.py → Pydantic 模型 (ChartType/AggregationType 枚举, 请求/响应)
config.py        → 配置加载 (.env 多级查找) + 数据库路径解析
utils/logger.py  → 统一日志 (含 LLM 调用专用日志器 + 耗时装饰器)
```

### 后端关键点

- **DuckDBService** 是模块级单例，整个进程共享一个只读连接。不使用 VIEW（因只读限制），改用 `WITH v AS (JOIN...)` CTE 查询。聚合查询包含类型感知机制：`SUM(时间列)` 自动降级为 `COUNT`。信号字段（243 种）通过标量子查询从 `TL_RMU_PS_TASK_RULE_RESULT_SIGNAL` 表实时提取数值。
- **config.py** 会按优先级从多个位置加载 `.env` 文件：`$DATAPIVOT_ENV` → `sys.executable` 同目录 → `Path.cwd()` → `_MEIPASS` (PyInstaller) → `backend/app/.env` → `backend/.env` → 项目根 `.env`。`DEEPSEEK_API_KEY` 自动同步到 `OPENAI_API_KEY` 环境变量（DeepSeek 兼容 OpenAI SDK）。
- **Chat API** (`chat.py`) 同时提供非流式 (`POST /api/chat/query`) 和 SSE 流式 (`POST /api/chat/stream`)。使用 Chat Demo 的 `agent.thread()` 实现多轮对话（session_id 键值对）。流式模式通过 `_StreamingWriter` 线程安全捕获中间输出，经 SSE 实时推送给前端。**LLM 调用本身依赖 LangChain 生态，跨系统和 patch 会影响其稳定性，修改 trace_service.py 或 chat.py 时务必谨慎测试完整链路**。
- **Trace 服务** (`trace_service.py`) 通过 monkey-patch `BaseChatModel._generate_with_cache` 和 `BaseTool.invoke` 实现全链路追踪。使用 `contextvars.ContextVar` 隔离多请求并发，输出 JSON 文件到 `backend/logs/traces/`。
- **路由注册** 在 `api/__init__.py` 中导出 5 个 router 对象，由 `main.py` 统一 `app.include_router()`。

## 前端架构 (`frontend/src/`)

```
router/index.ts          → Vue Router (hash 模式: createWebHashHistory)，5 条路由
pages/
  ChatPage.vue           → /chat — AI 对话式报表（SSE 流式交互，多轮对话 + Vega-Lite 图表）
  PivotPage.vue          → /pivot — 拖拽透视（字段面板+透视区+图表/表格双视图）
  DashboardPage.vue      → /dashboard — Chat Demo 联动（Schema内省+列画像+下钻+AI洞察+波形图）
  TracePage.vue          → /trace — 链路追踪（LLM 调用链可视化）
components/
  charts/ChartRenderer.vue → 通用图表组件（根据 chartType prop 动态构建 Vega-Lite spec）
  pivot/PivotTable.vue     → 数据透视表组件
stores/
  pivot.ts               → Pinia store（字段管理，聚合查询，图表加载，图表推荐）
  chat.ts                → Pinia store（SSE 流式消息状态，多轮对话 session，思考过程）
api/index.ts             → Axios 封装（含透视/图表/对话/下钻/Chat Demo/Trace 所有 API + SSE 原生 fetch）
App.vue                  → App shell：顶部导航栏 + <router-view>
```

### 前端关键点

- **4 个页面**通过顶部导航栏切换：💬 AI 对话 / 📊 拖拽透视 / 🖥️ Chat Demo 联动 / 🔍 链路追踪，首页 `/` 重定向到 `/chat`。
- **路由使用 hash 模式** (`createWebHashHistory`)，路径为 `/#/chat`、`/#/pivot` 等。这意味着后端不需要为 SPA 路由做 fallback 配置——但在 PyInstaller 打包场景中，`server_main.py` 仍需将所有非 API 请求返回 index.html。
- **SSE 流式对话** (`api/index.ts` 中的 `chatStream` 函数) 使用原生 `fetch` + `ReadableStream`，手动解析 SSE 事件流。事件类型：`status`、`thinking`、`tool`、`sql`、`result`、`done`、`error`。
- **`ChartRenderer.vue`** 根据 `chartType` prop 动态构建 Vega-Lite spec（支持 bar/pie/line/waveform/radar/scatter），优先使用后端生成的 `chartSpec`（Vega-Lite JSON spec），回退到前端本地构建 spec。
- **API 超时** 设置为 2 分钟（`1000 * 120`），因为 Chat Demo agent 推理需要较长时间。

## API 端点一览

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/pivot/aggregate` | POST | 透视聚合查询 |
| `/api/pivot/groupby` | POST | 分组聚合查询 |
| `/api/pivot/fields` | GET | 字段列表（固定+动态信号） |
| `/api/pivot/data` | GET | 原始扁平化数据 |
| `/api/pivot/persons` | GET | 人员列表（下钻用） |
| `/api/pivot/drill/tasks` | GET | 按人员查任务 |
| `/api/pivot/drill/rules` | GET | 按任务查规则 |
| `/api/pivot/drill/alarms` | GET | 按规则查报警 |
| `/api/pivot/drill/signals` | GET | 按报警查信号 |
| `/api/pivot/drill/signal-timeline` | POST | 信号时间序列 |
| `/api/chart/recommend` | POST | 图表类型推荐 |
| `/api/chart/data` | POST | 图表数据 |
| `/api/chart/{type}` | POST | 指定类型图表快捷端点 |
| `/api/chart/render` | POST | Chat Demo Plotly 渲染 |
| `/api/chat/query` | POST | AI 对话查询 |
| `/api/chat/stream` | POST | SSE 流式对话 |
| `/api/chat/threads` | GET | 活跃会话列表 |
| `/api/chat/patterns` | GET | 示例查询列表 |
| `/api/trace/list` | GET | 链路追踪列表 |
| `/api/trace/stats` | GET | 追踪统计 |
| `/api/trace/{id}` | GET/DELETE | 追踪详情/删除 |
| `/api/chatdemo/introspect` | GET | Chat Demo 数据库内省 |
| `/api/chatdemo/table/columns` | GET | 表列详情 |
| `/api/chatdemo/table/stats` | GET | 表数据画像 |
| `/api/chatdemo/column/distinct` | GET | 列去重值 |

## 打包相关

- `build.py` — 完整打包脚本（前端构建 → 创建 server_main.py → PyInstaller 打包 → 最终整理），生成 `dist/DataPivot.exe`
- `test_build.py` — 打包后程序功能测试脚本
- `BUILD.md` — 打包文档
- `server_main.py` — PyInstaller 打包用的单独入口（嵌入 SPAStaticMiddleware 处理静态文件），不在常规开发中使用
- PyInstaller 参数：`--onefile --console --add-data "index.html;." --add-data "frontend/dist;frontend/dist" --add-data "vcloud_duck.db;."`

## 注意事项

- DuckDB 连接为只读模式 (`read_only=True`)，不要尝试写入数据库
- `vcloud_duck.db` 是 6 表关联的业务数据库（714 / 13,163 / 3,109 / 301 / 23,127 行），只读不可修改
- 修改 `trace_service.py` 的 monkey-patch 逻辑或 `chat.py` 的 agent 管线时务必谨慎——LLM 调用依赖复杂的 LangChain + Chat Demo 内部状态，建议修改后完整测试非流式、流式和链路追踪三条路径
- 前后端 API 通过 `frontend/vite.config.ts` 的 proxy 配置在开发模式下联调（端口 3000 → 8080）
