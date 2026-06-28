# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

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
```

## 技术栈

- **后端**: FastAPI + DuckDB (连接 `vcloud_duck.db` 只读) + DeepSeek API + Chat Demo 0.6.2 (内省 + Plotly 渲染)
- **前端**: Vue 3 + Vue Router 4 + Pinia + Vega-Lite (vega-embed) + Axios
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
  chat.py     → AI 对话 (DeepSeek API + 本地关键词回退)
  chatdemo.py  → Chat Demo 内省 API (schema 浏览, 列信息, 数据画像)
services/
  duckdb_service.py       → DuckDB 单例 (只读), CTE 查询, 聚合/下钻/信号
  aggregation_service.py  → 聚合委托层
  chart_service.py        → 图表推荐 + 数据准备 + chatdemo Plotly 渲染
  chatdemo_service.py      → Chat Demo 集成 (DuckDB 内省 + Plotly)
models/schema.py → Pydantic 模型 (ChartType/AggregationType 枚举, 请求/响应)
config.py        → DeepSeek API key (仅从环境变量 DEEPSEEK_API_KEY 读取)
```

关键点：
- `DuckDBService` 是模块级单例，整个进程共享一个只读连接
- 不使用 VIEW（因只读限制），改用 `WITH v AS (JOIN...)` CTE
- `config.py` 不再硬编码 API key — 从 `DEEPSEEK_API_KEY` 环境变量获取
- Chat Demo 的 `DatabaseColumn.type` 和 `DatabaseColumn.nullable` 属性名为 `type`/`nullable`（不是 `data_type`/`is_nullable`）

## 前端架构 (`frontend/src/`)

```
router/index.ts          → Vue Router，3 条路由
pages/
  ChatPage.vue           → /chat — AI 对话式报表（独立页面，对话+图表）
  PivotPage.vue          → /pivot — 拖拽透视（字段面板+透视区+图表/表格视图）
  DashboardPage.vue      → /dashboard — Chat Demo 联动（Schema内省+下钻+AI洞察）
components/
  charts/ChartRenderer.vue → 通用图表组件（根据 chartType prop 渲染6种图表）
  pivot/PivotTable.vue     → 数据透视表组件
stores/pivot.ts          → Pinia store（字段管理，图表加载，推荐）
api/index.ts             → Axios 封装（含透视/图表/对话/下钻/Chat Demo 所有 API）
App.vue                  → App shell：顶部导航 + <router-view>
```

关键点：
- 3 个页面通过顶部导航栏切换：💬 AI 对话 / 📊 拖拽透视 / 🖥️ Chat Demo 联动
- `ChartRenderer.vue` 替代了之前 6 个重复的图表组件，根据 `chartType` prop 动态构建 Vega-Lite spec
- DashboardPage 展示了 Chat Demo 的核心能力：数据库 schema 浏览、数据画像、下钻查询、AI 洞察
- 后端 `/api/pivot/drill/*` 端点支持人员→任务→规则→报警的分层下钻
