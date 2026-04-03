"""
低压开关柜业务领域实现。

对应模板目录：templates/lowvoltage_cabinet/
对应向量库目录：vecdb/lowvoltage_cabinet/

数据结构说明：
  低压柜模板 JSON 的字段存储在 ``scheme`` 节点（统一全项目入口键）。
  FeatureExtractor 已支持 source="scheme" 路由。
"""

from __future__ import annotations

from layout_rag.domain.base import BusinessDomain


class LowvoltageCabinetDomain(BusinessDomain):
    """低压开关柜面板布局业务领域。"""

    # ------------------------------------------------------------------
    # 0. 业务标识 Key（决定模板目录和向量库目录）
    # ------------------------------------------------------------------

    @property
    def domain_key(self) -> str:
        return "lowvoltage_cabinet"

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
            # 大型元件比例
            "large_part_ratio":   {"type": "continuous", "weight": 1.0, "display_name": "大型元件占比"},
        }

    # ------------------------------------------------------------------
    # 2. 动态特征来源
    # ------------------------------------------------------------------

    @property
    def dynamic_feature_sources(self) -> dict[str, dict]:
        return {
            # ── 每种元件类型的数量（来自 scheme.parts）──
            "part_type_counts": {
                "source": "parts",         # 统一由 FeatureExtractor 路由到 scheme.parts
                "field": "part_type",
                "feature_type": "count",
                "weight": 1.0,
                "feature_name_template": "count_{value}",
                "display_name_template": "{value} 数量",
            },
            # ── 柜体用途（进线柜 / 出线柜 / …）──
            "cabinet_use_categories": {
                "source": "scheme",
                "field": "cabinet_use",
                "feature_type": "boolean",
                "weight": 5.0,
                "feature_name_template": "cabinet_use_{value}",
                "display_name_template": "柜体用途:{value}",
            },
            # ── 柜体型号（GCK / GCS / MNS / GGD）──
            "cabinet_model_categories": {
                "source": "scheme",
                "field": "cabinet_model",
                "feature_type": "boolean",
                "weight": 4.0,
                "feature_name_template": "cabinet_model_{value}",
                "display_name_template": "柜体型号:{value}",
            },
            # ── 进出线方式（上进上出 / 上进下出 / …）──
            "cabinet_wiring_method_categories": {
                "source": "scheme",
                "field": "cabinet_wiring_method",
                "feature_type": "boolean",
                "weight": 3.0,
                "feature_name_template": "cabinet_wiring_method_{value}",
                "display_name_template": "进出线方式:{value}",
            },
            # ── 面板类型（默认面板 / 抽屉面板）──
            "panel_type_categories": {
                "source": "scheme",
                "field": "panel_type",
                "feature_type": "boolean",
                "weight": 5.0,
                "feature_name_template": "panel_type_{value}",
                "display_name_template": "面板类型:{value}",
            },
            # ── 操作方式（手动机构 / 电动操作 / 抽屉式）──
            "panel_operation_method_categories": {
                "source": "scheme",
                "field": "panel_operation_method",
                "feature_type": "boolean",
                "weight": 3.0,
                "feature_name_template": "panel_operation_method_{value}",
                "display_name_template": "操作方式:{value}",
            },
        }

    # ------------------------------------------------------------------
    # 3. 结构特征提取（无业务专属结构特征）
    # ------------------------------------------------------------------

    def extract_structural_features(self, parts: list[dict], meta: dict) -> dict[str, float]:
        return {}

    # ------------------------------------------------------------------
    # 4. 大型元件阈值
    # ------------------------------------------------------------------

    @property
    def large_part_area_threshold(self) -> float:
        """面积 > 15 000 mm² 视为大型元件（开关柜内框架断路器体积更大）。"""
        return 15_000.0

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
            "solver_time_limit":  30.0,
            "solver_num_workers": 8,
        }

    @property
    def default_panel_size(self) -> list[float]:
        """低压开关柜标准面板默认尺寸 800mm × 2000mm。"""
        return [800.0, 2000.0]
