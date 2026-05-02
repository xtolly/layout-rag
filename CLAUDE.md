# CLAUDE.md -- Layout RAG 项目指南

## 项目概述

基于历史电气柜布局模板检索与约束求解的元件布局推荐系统。输入新的柜体/面板元件清单，通过 Neo4j 向量检索召回相似历史布局模板，将模板坐标迁移到当前项目，再使用 OR-Tools CP-SAT 约束求解生成最终无重叠的二维布局。前端使用 Vue 3 提供可视化配置与微调能力。

## 技术栈

- **后端：** Python 3.11, FastAPI, Uvicorn
- **约束求解器：** OR-Tools CP-SAT（面板级 + 柜体级布局）
- **图数据库：** Neo4j 6.x（向量索引用于相似性搜索，图拓扑用于布局数据）
- **AI Agent：** LangChain + LangGraph（ReAct 模式，通义千问 3.5 Plus via DashScope）
- **前端：** Vue 3（CDN，无构建步骤），Tailwind CSS（CDN），marked.js + DOMPurify
- **包管理：** uv（可回退 pip），setuptools 构建后端

## 项目结构

```
src/layout_rag/           # 主 Python 包
  app.py                  # FastAPI 入口，领域实例化，路由挂载
  config.py               # 路径常量、SelectionConfig、特征 schema 构建、数据加载工具
  api/
    endpoints.py          # 核心布局 API：/api/schema, /recommend, /apply, /submit, /cabinet-layout
    agent_endpoints.py    # AI Agent API：/api/agent/chat/stream, /chat, /status
  core/
    feature_extractor.py  # 从布局 JSON 提取特征向量（6 组特征）
    vector_store.py       # Neo4j 特征编码器（归一化参数、加权向量编码）
    layout_optimizer.py   # 面板级：模板匹配 + CP-SAT 约束求解
    cabinet_layout_optimizer.py  # 柜体级：面板排列 CP-SAT 求解
    neo4j_client.py       # Neo4j 连接、向量搜索、布局数据检索
  services/
    layout_service.py     # 业务编排：推荐 -> 应用工作流
  domain/
    base.py               # 抽象 BusinessDomain 基类
    distribution_box.py   # 配电箱领域（domain_key: distribution_box）
    new_distribution_box.py  # 新配电箱领域（domain_key: new_distribution_box）-- 当前活跃
    lowvoltage_cabinet.py # 低压开关柜领域（domain_key: lowvoltage_cabinet）
  agent/
    configurator_agent.py # LangGraph ReAct Agent，11 个工具用于柜体 CRUD

static/                   # 前端静态资源（FastAPI StaticFiles 托管）
  configurator.html/js    # 主配置器 SPA（柜体/面板/元件 CRUD + AI 对话）
  layout_workbench.html/js/css  # 布局工作台 SPA（上传 -> 推荐 -> 应用 -> 微调）
  configurator_options.json  # 共享下拉选项（90+ 元件类型、柜体类型等）
  part.color              # ~90 种元件类型的 HSL 颜色映射
  vue.global.prod.js      # Vue 3（打包 CDN）
  tailwind.js             # Tailwind CSS（打包 CDN）

templates/<domain_key>/   # 历史布局 JSON 文件（按面板）
vecdb/<domain_key>/       # 向量库归一化参数（vector_store.json）
projects/<domain_key>/    # 原始项目数据（按柜体的 JSON，用于 Neo4j 导入）
tools/                    # ETL 脚本（Neo4j 构建、模板生成、数据迁移）
tests/                    # pytest 测试
docs/                     # 设计文档
```

## 常用命令

```bash
# 安装依赖
uv sync --dev

# 启动开发服务器（端口 8000，热重载）
uv run uvicorn --app-dir src layout_rag.app:app --host 0.0.0.0 --port 8000 --reload

# 运行测试
uv run pytest tests/

# 构建 Neo4j 图数据库（低压开关柜）
uv run python tools/build_neo4j.py

# 构建 Neo4j 图数据库（新配电箱）
uv run python tools/new_neo4j.py
```

## 架构设计

### 领域驱动设计

所有业务逻辑通过 `BusinessDomain` 抽象基类解耦。活跃领域在 `app.py` 中实例化（当前为 `NewDistributionBoxDomain`）。每个领域定义：
- `domain_key` -- 目录路径的唯一标识
- `feature_schema_def` -- 静态特征定义（类型、权重、显示名称）
- `layout_constraints` -- 求解器参数（precision_scale, margin, element_gap, y_penalty, time_limit）
- `default_panel_size`、`large_part_area_threshold`

添加新领域：在 `domain/` 中实现 `BusinessDomain`，在 `app.py` 中实例化。

### 数据流（推荐 -> 应用）

1. **特征提取：** `FeatureExtractor` 从布局 JSON 提取 6 组特征（几何、统计、类型计数、结构、分类、大元件比例）
2. **向量编码：** `VectorStore` 归一化特征（连续特征用 min-max，计数特征用 log1p-max），应用 sqrt(weight) 以兼容欧氏距离
3. **Neo4j 搜索：** 两阶段 -- 编码向量，查询 HNSW 索引获取 top-K ID + 分数，批量检索完整布局数据
4. **差异计算：** `LayoutService` 计算匹配/多余/缺失元件，以及按特征逐项比较的状态阈值（绿/黄/橙/红）
5. **模板应用：** `LayoutOptimizer` 运行四阶段级联：
   - 主模板精确匹配（权重=1000）：同 part_type，最接近尺寸
   - 备选模板补位（权重=120）：借用其他推荐模板坐标
   - 游标续排（权重=10）：沿同类型锚点继续排布
   - CP-SAT 求解：最小化加权 L1 距离，强制不重叠 + 边距约束

### AI Agent（LangGraph ReAct）

- 自定义 `_ChatOpenAIReasoning` 子类从千问/DeepSeek 风格响应中提取 `reasoning_content`
- 11 个工具用于柜体/面板/元件的 CRUD：`add_cabinets`、`add_panels`、`add_parts`、`edit_cabinet/panel/part`、`delete_cabinet/panel/part`、`get_current_selection`、`get_schema_summary`
- 工具输入使用 Pydantic 模型，枚举类型从 `configurator_options.json` 动态生成
- SSE 流式传输 via `POST /api/agent/chat/stream`，事件类型：`token`、`action`、`thinking`、`done`、`error`
- 状态：`messages`（对话）+ `current_schema`（完整柜体配置）

### 前端架构

两个 Vue 3 SPA 通过 `postMessage` 通信（iframe 组合）：
- **配置器**（`/`）：柜体/面板/元件 CRUD、AI 对话、图片上传、可调列宽
- **布局工作台**（`/layout`）：上传 JSON -> 查看推荐 -> 选择模板 -> 可视化布局编辑

无构建系统 -- 原始 HTML/JS/CSS 静态托管。Vue 3 Composition API，单体 `setup()` 函数。通过 `/api/ui-metadata` 实现 Schema 驱动的 UI。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/schema` | 特征 schema 定义 |
| GET | `/api/part-color-map` | 元件类型颜色映射 |
| GET | `/api/ui-metadata` | 动态 UI 字段定义（来自活跃领域） |
| POST | `/api/recommend` | 提交项目布局，获取 top-K 模板推荐 |
| POST | `/api/apply` | 应用模板到项目，执行 CP-SAT 求解 |
| POST | `/api/submit` | 提交人工微调后的最终布局 |
| POST | `/api/cabinet-layout` | 柜体级面板排列 CP-SAT 求解 |
| POST | `/api/agent/chat/stream` | SSE 流式 AI 对话（token 级） |
| POST | `/api/agent/chat` | 非流式 AI 对话（降级方案） |
| GET | `/api/agent/status` | Agent 就绪状态检查 |

## Neo4j 图模型

**new_distribution_box 领域：**
- 节点：`BoxInstance`、`BoxTemplate`、`PanelInstance`、`PanelTemplate`、`PanelCategory`、`ComponentInstance`、`ComponentTemplate`、`ComponentCategory`、`Rail`
- 关系：`INSTANCE_OF`、`CONTAINS`、`BELONGS_TO`
- 向量索引：`panel_vector_index`，基于 `PanelInstance.FeatureVector`（欧氏距离 HNSW）

**lowvoltage_cabinet 领域：**
- 节点：`CabinetTemplate/Variant/Instance`、`PanelTemplate/Variant/Instance`、`PartTemplate/Instance`
- 关系：`HAS_VARIANT`、`HAS_INSTANCE`、`CONTAINS_PANEL`、`CONTAINS_PART`、`ADJACENT_TO`、`SAME_ROW`、`SAME_COLUMN` 等

## 数据格式

布局 JSON（存储于 `templates/<domain_key>/`）：
```json
{
  "name": "项目名称",
  "uuid": "uuid",
  "schema": {
    "panel_size": [宽度, 高度],
    "parts": [
      {"part_id": "id", "part_type": "类型", "part_size": [宽, 高]}
    ]
  },
  "arrange": {
    "part_id": {"position": [x, y], "rotation": 0}
  }
}
```

柜体级 schema（由配置器管理）：
```
cabinets[] -> cabinet_id, cabinet_name, cabinet_width, cabinet_height, order, arrange{}, panels[]
  -> panels[] -> panel_id, panel_type, panel_width, panel_height, order, arrange{}, parts[]
    -> parts[] -> part_id, part_type, part_width, part_height, order
```

## 环境变量（.env）

- `DASHSCOPE_API_KEY` -- 阿里云 DashScope API 密钥
- `DASHSCOPE_API_BASE` -- API 端点（dashscope.aliyuncs.com/compatible-mode/v1）
- `DASHSCOPE_MODEL` -- 模型名称（qwen3.5-plus）
- `AGENT_TIMEOUT` -- Agent 超时时间（秒，默认 600）

## 开发注意事项

- Neo4j 必须在本地 `neo4j://127.0.0.1:7687` 运行，需有 `distributionbox` 和 `lowvoltagecabinet` 两个数据库
- 修改任何领域的 `feature_schema_def` ,必须重建 Neo4j 数据和 vecdb
- `VectorStore` 不再本地存储向量 -- 仅保存归一化参数。实际向量搜索委托给 Neo4j 的 HNSW 索引
- 前端无构建步骤，直接编辑 HTML/JS/CSS 并刷新即可
- CORS 完全开放（允许所有来源）-- 无身份认证
- 活跃领域在 `app.py` 中硬编码（`NewDistributionBoxDomain()`）
