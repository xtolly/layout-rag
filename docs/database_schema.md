# 数据库结构 (Neo4j Graph Schema)

本文档描述了 Layout-RAG 系统中使用的图数据库模型结构，主要由 `PLMGraphImporter` 负责数据的解析与入库。

![neo4j](images/neo4j.png)

## 1. 核心模型层级

系统采用“分类 -> 模板 -> 实例”的三层解耦架构：

- **Category (分类)**: 业务大类（如：配电箱、断路器）。
- **Template (模板/物料)**: 具体的物料规格（如：型号、物理尺寸、极数等）。
- **Instance (实例)**: 在具体工程项目中的应用（包含坐标位置、向量指纹等）。

---

## 2. 节点定义 (Nodes)

### 2.1 柜体层 (Box)

| 标签 | 属性 | 说明 |
| :--- | :--- | :--- |
| **BoxCategory** | `Name` | 柜体分类（如：配电箱、户箱、表箱等） |
| **BoxTemplate** | `Name`, `Series`, `Width`, `Height`, `Depth`, `DoorType`, `FixUpType`, `InstallType` | 柜体规格定义 |
| **BoxInstance** | `ID`, `Name`, `Industry` | 具体项目中的柜体实例 |

### 2.2 面板层 (Panel)

| 标签 | 属性 | 说明 |
| :--- | :--- | :--- |
| **PanelCategory** | `Name` | 面板分类（如：元件安装板、仪表门） |
| **PanelTemplate** | `Name`, `Width`, `Height` | 面板物理尺寸定义 |
| **PanelInstance** | `ID`, `Name`, `FeatureVector`, `BomFeatureVector`, `NonBomFeatureVector`, `recommendation_count`, `adoption_count` | 存储了用于 RAG 检索的特征向量及统计信息 |

### 2.3 导轨层 (Rail)

| 标签 | 属性 | 说明 |
| :--- | :--- | :--- |
| **Rail** | `Name`, `RailIndex`, `Y_Coordinate`, `TotalRails` | 将面板空间划分为横向排列的导轨 |

### 2.4 元件层 (Component)

| 标签 | 属性 | 说明 |
| :--- | :--- | :--- |
| **ComponentCategory** | `Name` | 元件大类（如：微型断路器、浪涌保护器） |
| **ComponentTemplate** | `Name`, `ModelType`, `Width`, `Height`, `Pole`, `Current` | 核心物料库，存储元件物理参数 |
| **ComponentInstance** | `ID`, `Name`, `X`, `Y`, `Z`, `InLine` | 元件在面板上的精确坐标与安装状态 |

---

## 3. 关系定义 (Relationships)

### 3.1 层级归属

- `(Instance)-[:INSTANCE_OF]->(Template)`: 实例所属的规格。
- `(Template)-[:BELONGS_TO]->(Category)`: 规格所属的大类。
- `(BoxInstance)-[:CONTAINS]->(PanelInstance)`: 柜体包含的面板。
- `(PanelInstance)-[:CONTAINS]->(Rail)`: 面板上的导轨划分。
- `(Rail)-[:CONTAINS]->(ComponentInstance)`: 导轨上安装的元件。

### 3.2 空间拓扑 (Spatial Topology)

- `(Rail)-[:BELOW {Distance}]->(Rail)`: 导轨之间的纵向邻接关系及间距。
- `(ComponentInstance)-[:LEFT_OF {Distance}]->(ComponentInstance)`: 同一导轨内元件的横向排列关系。

### 3.3 挖掘关系 (Mining)

- `(ComponentTemplate)-[:CO_OCCURS_WITH {weight, rule_type}]->(ComponentTemplate)`:
  **核心召回关系**。表示两个型号的元件经常出现在同一个面板中。`weight` 代表共现频次。

---

## 4. 向量索引说明

系统在 `PanelInstance` 的特征属性上建立了 **HNSW 向量索引**，用于实现语义召回。

- 索引字段：`FeatureVector`, `BomFeatureVector`, `NonBomFeatureVector`
- 相似度度量：`EUCLIDEAN` (欧氏距离)
