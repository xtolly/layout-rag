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

* **Python 3.11+**：项目推荐使用 [uv](https://github.com/astral-sh/uv) 进行极速依赖管理。
* **Neo4j 6.x**：需要在本地运行图数据库，默认连接 `neo4j://127.0.0.1:7687`（数据库名默认为 `distributionbox`）。
* **大模型 API**：若需开启 AI 智能体对话功能，请在根目录创建 `.env` 文件并配置 `DASHSCOPE_API_KEY`。

### 2. 安装与启动

```bash
# 1. 安装项目依赖（包含开发环境）
uv sync --dev

# 2. 初始化知识图谱与向量索引
# 读取原始项目数据，抽取拓扑关系并建立 Neo4j HNSW 索引
uv run python tools/new_neo4j.py

# 3. 启动后端 API 服务
uv run uvicorn --app-dir src layout_rag.app:app --host 0.0.0.0 --port 8000 --reload
```

启动后，访问 `http://localhost:8000/` 即可进入可视化布局配置与工作台。

## 自动化测试与质量保障

项目内置了完整的单元测试体系，覆盖了核心算法、特征提取逻辑及业务流程。

### 1. 运行全量测试

```bash
uv run pytest
```

### 2. 查看测试覆盖率

项目使用 `pytest-cov` 进行覆盖率统计：

* **终端摘要报告**：

    ```bash
    uv run pytest --cov=layout_rag --cov-report=term-missing
    ```

* **HTML 交互式报告**（生成后打开 `htmlcov/index.html`）：

    ```bash
    uv run pytest --cov=layout_rag --cov-report=html
    ```

目前核心模块（布局优化、特征转换）的测试覆盖率已达到 **80% 以上**。

## 业务领域切换

系统通过 `BusinessDomain` 基类实现抽象。目前活跃领域为 `NewDistributionBoxDomain` (新配电箱)。如果需要接入新业务（如“低压开关柜”）：

1. 在 `src/layout_rag/domain` 中继承 `BusinessDomain` 并实现抽象方法。
2. 定义该领域的特征 Schema、提取逻辑与布局约束。
3. 在 `app.py` 中实例化新领域并注入 `LayoutService` 即可。

## 桌面端客户端 (Electron)

项目提供了一个基于 Electron 的桌面客户端，用于在工业环境中提供更稳定的原生交互体验。

### 1. 构建环境要求

* **Node.js 18+**：需安装 `npm` 环境。
* **Windows 系统**：目前构建脚本主要面向 Windows 平台。

### 2. 自动构建发布

根目录下提供了 `build_electron.bat` 脚本，可一键完成依赖安装、静态资源链接及客户端打包：

```powershell
# 在项目根目录下运行
.\build_electron.bat
```

**脚本主要流程：**

1. 清理旧的构建产物。
2. 创建 `static` 目录的符号链接（Junction），实现前后端资源共享。
3. 进入 `electron-app` 目录执行 `npm install`。
4. 执行 `npm run build:fast` 生成免安装的二进制文件夹。

构建完成后，产物位于 `electron-app\dist\win-unpacked` 目录下。

## API 集成参考

对于外部工业软件对接，核心流程通常只需调用三个接口：

1. `POST /api/recommend`：传入当前项目数据（BOM + 柜体属性），获取 Top-K 推荐模板及 Gower 相似度分数。
2. `POST /api/apply`：选择指定模板，由后端求解器在满足不重叠约束下，计算出各元件的具体 `[x, y]` 坐标。
3. `POST /api/upload-layout`：将人工确认无误的布局方案存入 Neo4j 图数据库，实现经验的自动闭环沉淀。
