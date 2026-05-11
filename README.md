# Layout-RAG 工业电气柜布局智能推荐与生成系统

Layout-RAG 是一个专为工业电气柜设计的智能排版系统。它结合了**基于图数据库的大语言模型智能体（LangGraph Agent）**与**约束规划求解器（CP-SAT）**，能够通过解析自然语言或解析导入的系统图数据，自动推荐元器件 BOM 清单，并从历史沉淀的工程图纸中召回最相似的排版方案，最终自动生成无重叠、符合电气物理约束的二维布局坐标。

## 核心能力

* **多路智能 BOM 推荐**：基于 Neo4j 图数据库，结合环境向量（箱体尺寸/外部约束）、BOM 向量（内部物料构成）以及图谱共现网络进行多路召回，通过置信度融合与互补过滤，智能补全缺失的电气元件。
* **AI 智能体配置 (Agentic Configurator)**：内置基于 LangGraph 的 ReAct 智能体，支持流式对话。工程师可以用自然语言下达指令（如“帮我加一个宽600的面板，里面放3个微型断路器”），智能体会自动调用内部 CRUD 工具完成柜体数据结构的搭建。
* **图向量混合检索 (Graph-Vector RAG)**：提取面板的几何维度、元件统计、类型计数及强业务逻辑特征，利用 Neo4j 的 HNSW 向量索引进行“宽进”召回，再配合 Gower 距离算法进行高精度“严出”排序。
* **约束求解排版 (Constraint-Based Layout)**：利用 OR-Tools 的 CP-SAT 求解器，将选定历史模板的元件坐标映射到当前项目，严格保证面板边距限制与元件无重叠约束，自动进行空间压缩与排版优化。
* **桌面端/Web 端双模态**：提供开箱即用的 Vue 3 可视化工作台（支持拖拽微调排版），同时可通过构建工具一键打包为无头启动的 Electron 桌面客户端，便于工业软件集成。

## 系统架构与目录结构

项目采用领域驱动设计（DDD），将核心算法与具体业务领域（如配电箱、低压开关柜）解耦。

```text
layout-rag/
├── src/layout_rag/      # 后端核心包 (FastAPI)
│  ├── api/         # 接口路由 (RESTful Endpoints, Agent SSE Stream)
│  ├── core/         # 核心算法 (特征提取, 向量转换, CP-SAT求解器, Neo4j图客户端)
│  ├── domain/        # 领域业务规则 (如 NewDistributionBox 新配电箱特征定义)
│  ├── services/       # 业务编排层 (布局推荐与应用流程串联)
│  └── agent/        # LangGraph 智能体逻辑 (图计算节点, 结构化工具调用)
├── static/          # 前端静态资源 (Vue 3, Tailwind, 工作台界面)
├── templates/        # 沉淀的历史优良布局 JSON 模板库
├── tools/          # 运维与数据管道脚本 (知识图谱重建, 向量刷新, PLM导入)
├── tests/          # 自动化测试用例
└── build_electron.bat    # 桌面端自动打包构建脚本
```

## 快速开始

### 1. 环境准备

* **Python 3.11+**：项目使用 `uv` 进行快速依赖管理。
* **Neo4j 6.x**：需要在本地运行图数据库，默认连接 `neo4j://127.0.0.1:7687`（需预先建立相应业务数据库，例如 `distributionbox`）。
* **大模型 API (可选)**：如果需要使用 AI 智能体功能，请在根目录创建 `.env` 文件并配置 `DASHSCOPE_API_KEY`。

### 2. 安装与初始化

```bash
# 1. 安装项目依赖
uv sync --dev

# 2. 初始化知识图谱与向量索引
# 读取原始项目数据，抽取拓扑关系并建立 Neo4j HNSW 索引
uv run python tools/new_neo4j.py

# 3. 启动本地服务
uv run uvicorn --app-dir src layout_rag.app:app --host 0.0.0.0 --port 8000 --reload
```

启动后，访问 `http://localhost:8000/` 即可进入可视化布局配置与工作台。

## 业务领域切换

系统通过 `BusinessDomain` 基类实现抽象。目前活跃领域为 `NewDistributionBoxDomain` (新配电箱)。如果需要接入如“低压开关柜”等新业务，只需在 `src/layout_rag/domain` 中新建领域类，定义其特征提取逻辑与业务约束，并在 `app.py` 中实例化挂载即可。

## API 集成参考

对于外部工业软件对接，核心流程通常只需调用三个接口：

1. `POST /api/recommend`：传入当前元件清单，获取 Top-K 推荐模板及分数。
2. `POST /api/apply`：选择指定模板，由后端求解器计算出各元件的具体 `[x, y]` 坐标。
3. `POST /api/upload-layout`：将人工确认无误的布局方案存入图数据库，完成经验沉淀，实现系统进化。
