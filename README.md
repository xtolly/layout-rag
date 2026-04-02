# Layout RAG

基于历史电气柜布局模板检索与约束求解的元件布局推荐系统。

项目包含三部分能力：

- 基于布局 JSON 的特征提取与向量检索
- 基于相似模板的布局迁移与候选方案推荐
- 基于 OR-Tools CP-SAT 的最终坐标求解与前端微调

适用场景：上传一份新的柜体/面板元件清单后，从历史案例中召回相似模板，并将模板排版迁移到当前项目，再由人工进行可视化微调。

## 功能概览

- 布局样本建库：扫描 templates 下的历史布局 JSON，提取特征并构建向量库
- 相似模板推荐：按照连续特征、计数特征、布尔特征的加权距离进行召回排序
- 模板布局迁移：优先匹配同类型且尺寸最接近的元件坐标
- 兜底布局求解：对无法直接映射的元件使用备选模板、游标续排和 CP-SAT 约束求解
- 前端交互：内置静态页面，可上传 JSON、查看推荐模板、选择方案并微调布局

## 目录结构

```text
layout-rag/
|-- src/
|   `-- layout_rag/
|       |-- api/
|       |   |-- __init__.py
|       |   `-- endpoints.py
|       |-- core/
|       |   |-- __init__.py
|       |   |-- feature_extractor.py
|       |   |-- layout_optimizer.py
|       |   `-- vector_store.py
|       |-- services/
|       |   |-- __init__.py
|       |   `-- layout_service.py
|       |-- __init__.py
|       |-- app.py
|       `-- config.py
|-- scripts/
|   `-- build_vector_store.py
|-- tests/
|   |-- conftest.py
|   `-- test_retrieval.py
|-- data/
|   |-- box/
|-- templates/
|-- vecdb/
|   |-- vector_store.json
|   `-- vector_store.json.npz
|-- static/
|   |-- index.html
|   |-- tailwind.js
|   `-- vue.global.js
|-- pyproject.toml
`-- README.md
```

分层说明：

- src/layout_rag：应用源码，按 api / services / core 分层
- scripts：一次性或运维类脚本
- tests：测试与检索验证脚本
- data：原始样本
- templates：布局 JSON 数据集
- vecdb：生成的向量库产物
- static：前端静态资源

## 核心流程

### 1. 特征提取

FeatureExtractor 从布局 JSON 的 meta 节点提取两类特征：

- 固定特征：面板尺寸、元件数量、面积、宽高统计、结构布尔特征
- 动态特征：按 templates 中出现过的 part_type、cabinet_type、panel_type 自动扩展

动态特征定义位于 src/layout_rag/config.py。每次新增数据类型或调整 schema 后，都应重新建库。

### 2. 向量检索

VectorStore 将特征按三类分别处理：

- continuous：Min-Max 归一化
- count：Log1p 后按最大值缩放
- boolean：截断为 0/1 后计算布尔距离

最终距离为加权欧氏距离，返回最相似的历史模板。

### 3. 布局迁移

LayoutService 在推荐阶段会：

- 对候选模板重新提取特征并生成差异说明
- 结合元件组成差异计算推荐分数
- 返回模板 meta、arrange 和 featureDiffs 给前端

### 4. 约束求解

LayoutOptimizer 的流程如下：

1. 主模板精确匹配：同类型、尺寸最接近元件优先复用模板坐标
2. 备选模板补位：主模板缺失某类元件时，借用其他推荐模板坐标
3. 同类型游标续排：沿已有锚点继续排布同类新增元件
4. CP-SAT 求解：在边距、不重叠等硬约束下最小化偏移量

## 数据格式

历史布局样本位于 templates，基本结构如下：

```json
{
	"name": "项目名称_uuid后缀",
	"uuid": "ef29f756-682b-437e-9544-8298e6efc9d0",
	"meta": {
		"cabinet_type": "配电柜",
		"panel_type": "安装板",
		"panel_size": [600.0, 1600.0],
		"parts": [
			{
				"part_id": "136B1C",
				"part_type": "微型断路器",
				"part_size": [57.0, 40.0]
			}
		]
	},
	"arrange": {
		"136B1C": {
			"position": [24.0, 60.0],
			"rotation": 0
		}
	}
}
```

字段约定：

- meta.parts 是检索和排版的核心输入
- arrange 是历史模板的参考坐标，键为 part_id
- panel_size 单位默认为 mm

## 快速开始

### 1. 安装依赖

如果使用 uv：

```bash
uv sync --dev
```

如果使用 pip：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
pip install pytest
```

说明：

- uv 依赖使用 dependency-groups 管理，开发依赖通过 uv sync --dev 同步
- pip 不识别 dependency-groups，因此需要单独安装 pytest 这类开发工具

### 2. 构建向量库

```bash
uv run python scripts/build_vector_store.py
```

执行后会生成：

- vecdb/vector_store.json：schema、统计参数和条目元数据
- vecdb/vector_store.json.npz：压缩后的特征矩阵

### 3. 启动服务

```bash
uv run uvicorn --app-dir src layout_rag.app:app --host 0.0.0.0 --port 8000 --reload
```

或直接使用已安装命令：

```bash
uvicorn --app-dir src layout_rag.app:app --host 0.0.0.0 --port 8000 --reload
```

启动后访问：

- http://127.0.0.1:8000
- http://127.0.0.1:8000/docs

## 测试与验证

### 检索验证

```bash
uv run pytest tests/test_retrieval.py
```

该测试文件现在是标准 pytest 单元测试，覆盖动态特征生成、特征提取、检索排序以及向量库存取一致性。

## API 说明

### GET /api/schema

返回当前动态展开后的特征 schema。

### POST /api/recommend

输入当前项目布局 JSON，返回推荐模板列表：

```json
{
	"templates": [
		{
			"uuid": "...",
			"name": "...",
			"score": 87,
			"meta": {},
			"arrange": {},
			"diffInfo": {},
			"featureDiffs": []
		}
	]
}
```

### POST /api/apply

请求体：

```json
{
	"template_uuid": "主模板 UUID",
	"other_template_uuids": ["备选模板 UUID"],
	"project_data": {}
}
```

返回值包含：

- template_data：所选模板数据
- project_data：写入 arrange 后的项目数据

### POST /api/submit

接收人工微调后的最终布局，当前默认仅回显成功状态。

## 常用脚本

```bash
uv run python scripts/build_vector_store.py
uv run pytest tests/test_retrieval.py
```

## 开发建议

- 修改 src/layout_rag/config.py 中的 schema 或动态特征逻辑后，必须重建 vecdb/vector_store.json
- 如果新增了 part_type、cabinet_type 或 panel_type，建库前先确保样本 JSON 已落到 templates
- vecdb 目录下的向量库属于构建产物，建议在数据或特征变化后重新生成
- 当前前端为静态页面，适合原型验证；如果后续演进，可将 static 独立为单独前端工程

## 后续可扩展方向

- 增加正式的 pytest 单元测试与回归测试集
- 为 API 请求体补充 Pydantic 模型定义
- 为向量库引入版本校验和增量重建策略
- 将静态前端拆分为独立的前端应用与构建流程
