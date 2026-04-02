"""
配电箱业务领域实现。

将原来硬编码在 config.py 和 feature_extractor.py 中的
配电箱专属业务逻辑集中到此处：
  - 特征 Schema 及权重
  - 动态特征来源（柜体类型、面板类型、元件类型）
  - 结构特征（双电源、地排、零排等）
  - 布局约束参数
"""

from __future__ import annotations

from layout_rag.domain.base import BusinessDomain


class DistributionBoxDomain(BusinessDomain):
    """配电箱面板布局业务领域。"""

    # ------------------------------------------------------------------
    # 0. 业务标识 Key
    # ------------------------------------------------------------------

    @property
    def domain_key(self) -> str:
        return "distribution_box"

    # ------------------------------------------------------------------
    # 1. 静态特征 Schema
    # ------------------------------------------------------------------

    @property
    def feature_schema_def(self) -> dict[str, dict]:
        return {
            # 面板尺寸特征
            "panel_width":        {"type": "continuous", "weight": 2.0, "display_name": "面板宽度"},
            "panel_height":       {"type": "continuous", "weight": 2.0, "display_name": "面板高度"},
            "panel_area":         {"type": "continuous", "weight": 1.5, "display_name": "面板总面积"},
            "panel_aspect_ratio": {"type": "continuous", "weight": 2.0, "display_name": "面板纵横比"},
            # 元件统计特征
            "total_parts":        {"type": "count",      "weight": 1.0, "display_name": "元器件总数"},
            "unique_types":       {"type": "count",      "weight": 2.0, "display_name": "元件种类数"},
            "total_parts_area":   {"type": "continuous", "weight": 1.5, "display_name": "元器件总面积"},
            "fill_ratio":         {"type": "continuous", "weight": 1.5, "display_name": "空间填充率"},
            "avg_part_width":     {"type": "continuous", "weight": 1.0, "display_name": "元件平均宽度"},
            "avg_part_height":    {"type": "continuous", "weight": 1.0, "display_name": "元件平均高度"},
            "max_part_width":     {"type": "continuous", "weight": 1.0, "display_name": "元件最大宽度"},
            "max_part_height":    {"type": "continuous", "weight": 1.0, "display_name": "元件最大高度"},
            "width_std":          {"type": "continuous", "weight": 1.0, "display_name": "元件宽度标准差"},
            "height_std":         {"type": "continuous", "weight": 1.0, "display_name": "元件高度标准差"},
            # 结构布尔特征（由 extract_structural_features 填充）
            "has_双电源":          {"type": "boolean",   "weight": 0.5, "display_name": "含双电源开关"},
            "has_地排":            {"type": "boolean",   "weight": 0.5, "display_name": "含地排"},
            "has_零排":            {"type": "boolean",   "weight": 0.5, "display_name": "含零排"},
            # 大型元件比例
            "large_part_ratio":   {"type": "continuous", "weight": 1.0, "display_name": "大型元件占比"},
        }

    # ------------------------------------------------------------------
    # 2. 动态特征来源
    # ------------------------------------------------------------------

    @property
    def dynamic_feature_sources(self) -> dict[str, dict]:
        return {
            "part_type_counts": {
                "source": "parts",
                "field": "part_type",
                "feature_type": "count",
                "weight": 1.0,
                "feature_name_template": "count_{value}",
                "display_name_template": "{value} 数量",
            },
            "cabinet_type_categories": {
                "source": "scheme",
                "field": "cabinet_type",
                "feature_type": "boolean",
                "weight": 5.0,
                "feature_name_template": "cabinet_type_{value}",
                "display_name_template": "柜体类型:{value}",
            },
            "panel_type_categories": {
                "source": "scheme",
                "field": "panel_type",
                "feature_type": "boolean",
                "weight": 5.0,
                "feature_name_template": "panel_type_{value}",
                "display_name_template": "面板类型:{value}",
            },
        }

    # ------------------------------------------------------------------
    # 3. 结构特征提取
    # ------------------------------------------------------------------

    def extract_structural_features(self, parts: list[dict], meta: dict) -> dict[str, float]:
        """
        提取配电箱专属的结构布尔特征：
          - has_双电源：布局中是否包含名称含"双电源"的元件
          - has_地排：是否包含名称含"地排"的元件
          - has_零排：是否包含名称含"零排"的元件
        """
        types_set = {str(p.get("part_type", "")) for p in parts}
        return {
            "has_双电源": 1.0 if any("双电源" in t for t in types_set) else 0.0,
            "has_地排":   1.0 if any("地排"   in t for t in types_set) else 0.0,
            "has_零排":   1.0 if any("零排"   in t for t in types_set) else 0.0,
        }

    # ------------------------------------------------------------------
    # 4. 大型元件阈值
    # ------------------------------------------------------------------

    @property
    def large_part_area_threshold(self) -> float:
        """面积 > 10 000 mm² 视为大型元件（例如断路器、变压器等）。"""
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
        """配电箱标准面板默认尺寸 600mm × 1600mm。"""
        return [600.0, 1600.0]
