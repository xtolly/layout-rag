"""
新配电箱业务领域实现。

数据来源：中船国际数科城项目系统图
对应模板目录：templates/new_distribution_box/
对应向量库目录：vecdb/new_distribution_box/

特征设计说明：
  本领域在 distribution_box.py 的空间特征与元件分布特征基础上，
  融合 new_neo4j.py 中定义的配电箱业务属性（箱体分类、系列、安装方式、
  进线方式、固定方式、门型）形成完整特征体系。

  静态特征：
    - 面板尺寸特征（panel_width/height/area/aspect_ratio）
    - 元件统计特征（total_parts, unique_types, ...）
    - 结构布尔特征（has_双电源, has_浪涌后备保护器, has_电涌保护器 等）
    - 大型元件比例（large_part_ratio）

  动态特征（从 schema 节点自动展开）：
    - 元件类型计数（count_{StandardName}）
    - 箱体分类（box_classify_配电箱 / box_classify_户箱 / ...）
    - 箱体系列（series_XM1 / series_XM2 / ...）
    - 安装方式（install_type_户内挂墙 / install_type_户外挂墙 / ...）
    - 进线方式（inline_mode_进线器件上置 / inline_mode_进线器件左置）
    - 固定方式（fixup_type_板式安装 / ...）
    - 门型（door_type_左开门 / ...）
"""

from __future__ import annotations

from layout_rag.domain.base import BusinessDomain


class NewDistributionBoxDomain(BusinessDomain):
    """新配电箱面板布局业务领域（中船国际数科城项目）。"""

    # ------------------------------------------------------------------
    # 0. 业务标识 Key（决定模板目录和向量库目录）
    # ------------------------------------------------------------------

    @property
    def domain_key(self) -> str:
        return "new_distribution_box"

    # ------------------------------------------------------------------
    # 1. 静态特征 Schema
    # ------------------------------------------------------------------

    @property
    def feature_schema_def(self) -> dict[str, dict]:
        return {
            # ── 面板尺寸特征（非 BOM）──
            "panel_width":        {"type": "continuous", "weight": 1.0, "display_name": "面板宽度",   "from_bom": False},
            "panel_height":       {"type": "continuous", "weight": 1.0, "display_name": "面板高度",   "from_bom": False},
            "panel_area":         {"type": "continuous", "weight": 1.0, "display_name": "面板总面积", "from_bom": False},
            "panel_aspect_ratio": {"type": "continuous", "weight": 1.0, "display_name": "面板纵横比", "from_bom": False},
            # ── 元件统计特征（BOM）──
            "total_parts":        {"type": "count",      "weight": 1.0, "display_name": "元器件总数",   "from_bom": True},
            "unique_types":       {"type": "count",      "weight": 1.0, "display_name": "元件种类数",   "from_bom": True},
            "total_parts_area":   {"type": "continuous", "weight": 1.0, "display_name": "元器件总面积", "from_bom": True},
            "fill_ratio":         {"type": "continuous", "weight": 1.0, "display_name": "空间填充率",   "from_bom": True},
            "avg_part_width":     {"type": "continuous", "weight": 1.0, "display_name": "元件平均宽度", "from_bom": True},
            "avg_part_height":    {"type": "continuous", "weight": 1.0, "display_name": "元件平均高度", "from_bom": True},
            "max_part_width":     {"type": "continuous", "weight": 1.0, "display_name": "元件最大宽度", "from_bom": True},
            "max_part_height":    {"type": "continuous", "weight": 1.0, "display_name": "元件最大高度", "from_bom": True},
            "width_std":          {"type": "continuous", "weight": 1.0, "display_name": "元件宽度标准差", "from_bom": True},
            "height_std":         {"type": "continuous", "weight": 1.0, "display_name": "元件高度标准差", "from_bom": True},
            # ── 大型元件比例（BOM）──
            "large_part_ratio":   {"type": "continuous", "weight": 1.0, "display_name": "大型元件占比", "from_bom": True},
        }

    # ------------------------------------------------------------------
    # 2. 动态特征来源
    # ------------------------------------------------------------------

    @property
    def dynamic_feature_sources(self) -> dict[str, dict]:
        return {
            # ── 每种元件类型的数量（来自 BOM）──
            "part_type_counts": {
                "source": "parts",
                "field": "part_type",
                "feature_type": "count",
                "weight": 0.5,
                "feature_name_template": "count_{value}",
                "display_name_template": "{value} 数量",
                "from_bom": True,
            },
            # ── 箱体分类（非 BOM）──
            "box_classify_categories": {
                "source": "schema",
                "field": "box_classify",
                "feature_type": "boolean",
                "weight": 5.0,
                "feature_name_template": "box_classify_{value}",
                "display_name_template": "箱体分类:{value}",
                "from_bom": False,
            },
            # ── 箱体系列 ──
            "series_categories": {
                "source": "schema",
                "field": "series",
                "feature_type": "boolean",
                "weight": 3.0,
                "feature_name_template": "series_{value}",
                "display_name_template": "系列:{value}",
                "from_bom": False,
            },
            # ── 进线方式 ──
            "inline_mode_categories": {
                "source": "schema",
                "field": "inline_mode",
                "feature_type": "boolean",
                "weight": 3.0,
                "feature_name_template": "inline_mode_{value}",
                "display_name_template": "进线方式:{value}",
                "from_bom": False,
            },
            # ── 安装方式 ──
            "install_type_categories": {
                "source": "schema",
                "field": "install_type",
                "feature_type": "boolean",
                "weight": 3.0,
                "feature_name_template": "install_type_{value}",
                "display_name_template": "安装方式:{value}",
                "from_bom": False,
            },
            # ── 固定方式 ──
            "fixup_type_categories": {
                "source": "schema",
                "field": "fixup_type",
                "feature_type": "boolean",
                "weight": 3.0,
                "feature_name_template": "fixup_type_{value}",
                "display_name_template": "固定方式:{value}",
                "from_bom": False,
            },
            # ── 门型 ──
            "door_type_categories": {
                "source": "schema",
                "field": "door_type",
                "feature_type": "boolean",
                "weight": 3.0,
                "feature_name_template": "door_type_{value}",
                "display_name_template": "门型:{value}",
                "from_bom": False,
            },
            # ── 电缆进出方式 ──
            "cable_in_out_type_categories": {
                "source": "schema",
                "field": "cable_in_out_type",
                "feature_type": "boolean",
                "weight": 3.0,
                "feature_name_template": "cable_in_out_type_{value}",
                "display_name_template": "进出线方式:{value}",
                "from_bom": False,
            },
        }

    # ------------------------------------------------------------------
    # 3. 结构特征提取
    # ------------------------------------------------------------------

    def extract_structural_features(self, parts: list[dict], meta: dict) -> dict[str, float]:
        """提取特定的结构布尔特征。"""

        return {}

    def ui_schema(self) -> dict:
        """定义前端 UI 需要展示和编辑的字段元数据"""
        return {
            "cabinet_fields": [
                {"key": "cabinet_name", "label": "柜体名称", "type": "text", "editable": True},
                {"key": "box_classify", "label": "箱体分类", "type": "select", "options": ["配电箱", "户箱", "标准电表箱", "非标电表箱"], "editable": True},
                {"key": "series", "label": "箱体系列", "type": "select", "options": ["XM1", "XM2", "MZ", "HW", "DNB"], "editable": True},
                {"key": "inline_mode", "label": "进线方式", "type": "select", "options": ["进线器件上置", "进线器件左置"], "editable": True},
                {"key": "install_type", "label": "安装方式", "type": "select", "options": ["户内暗装", "户内挂墙", "户内落地", "户外挂墙", "户外落地"], "editable": True},
                {"key": "fixup_type", "label": "固定方式", "type": "select", "options": ["板式安装", "梁式安装"], "editable": True},
                {"key": "door_type", "label": "门型", "type": "select", "options": ["左开门", "右开门", "双开门"], "editable": True},
                {"key": "cable_in_out_type", "label": "进出线方式", "type": "select", "options": ["上进下出", "上进上出-左侧出线", "上进上出-右侧出线", "下进下出-左侧进线", "下进下出-右侧进线", "下进上出-左进右出", "下进上出-右进左出"], "editable": True},
                {"key": "cabinet_width", "label": "宽度(W)", "type": "number", "editable": True},
                {"key": "cabinet_height", "label": "高度(H)", "type": "number", "editable": True},
                {"key": "cabinet_depth", "label": "深度(D)", "type": "number", "editable": True},
            ],
            "panel_fields": [
                {"key": "panel_type", "label": "面板类型", "type": "select", "options": ["安装板", "门板"], "editable": True},
                {"key": "panel_width", "label": "宽度(W)", "type": "number", "editable": True},
                {"key": "panel_height", "label": "高度(H)", "type": "number", "editable": True},
            ],
            "part_fields": [
                {"key": "part_type", "label": "元件类型", "type": "text", "editable": True},
                {"key": "part_model", "label": "元件型号", "type": "text", "editable": True},
                {"key": "pole", "label": "极数", "type": "text", "editable": True},
                {"key": "current", "label": "额定电流", "type": "text", "editable": True},
                {"key": "part_width", "label": "宽(w)", "type": "number", "editable": True},
                {"key": "part_height", "label": "高(h)", "type": "number", "editable": True},
            ]
        }

    # ------------------------------------------------------------------
    # 4. 大型元件阈值
    # ------------------------------------------------------------------

    @property
    def large_part_area_threshold(self) -> float:
        """面积 > 10 000 mm² 视为大型元件（如塑壳断路器、双电源开关等）。"""
        return 10_000.0

    # ------------------------------------------------------------------
    # 5. 布局约束参数
    # ------------------------------------------------------------------

    @property
    def layout_constraints(self) -> dict:
        return {
            "precision_scale":    1,
            "margin":             10.0,
            "element_gap":        0.0,
            "y_penalty":          10,
            "solver_time_limit":  20.0,
            "solver_num_workers": 8,
        }

    @property
    def default_panel_size(self) -> list[float]:
        """新配电箱标准面板默认尺寸 500mm × 800mm。"""
        return [500.0, 800.0]
