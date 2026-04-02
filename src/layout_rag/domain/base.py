"""
业务领域抽象基类。

每个业务领域通过继承此类来定义：
  - 特征 Schema（静态 + 动态）
  - 结构化特征的提取逻辑（如 has_XXX 布尔特征）
  - 布局优化器的约束参数
  - 颜色主题等 UI 配置
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BusinessDomain(ABC):
    """
    业务领域配置接口。

    子类需实现所有 abstractmethod，以描述该业务的数据结构、
    特征定义方式及布局约束规则。框架代码（FeatureExtractor、
    LayoutOptimizer、LayoutService）通过此接口保持业务无关。
    """

    # ------------------------------------------------------------------
    # 0. 业务标识 Key（用于推断子目录路径）
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def domain_key(self) -> str:
        """
        业务领域的唯一标识字符串，仅含小写字母、数字和下划线。
        框架用它自动拼接模板目录和向量库目录：
          templates/<domain_key>/
          vecdb/<domain_key>/
        示例："distribution_box"、"switchgear"
        """
        ...

    # ------------------------------------------------------------------
    # 1. 特征 Schema
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def feature_schema_def(self) -> dict[str, dict]:
        """
        静态特征定义字典，格式：
        {
            "feature_name": {
                "type": "continuous" | "count" | "boolean",
                "weight": float,
                "display_name": str,
            }, ...
        }
        """
        ...

    @property
    @abstractmethod
    def dynamic_feature_sources(self) -> dict[str, dict]:
        """
        动态特征来源定义字典，格式：
        {
            "source_group_name": {
                "source": "meta" | "parts",
                "field": str,                         # JSON 字段名
                "feature_type": "boolean" | "count",
                "weight": float,
                "feature_name_template": str,         # 含 {value} 占位符
                "display_name_template": str,         # 含 {value} 占位符
            }, ...
        }
        """
        ...

    # ------------------------------------------------------------------
    # 2. 结构化特征提取（业务自定义的 has_XXX 等特征）
    # ------------------------------------------------------------------

    @abstractmethod
    def extract_structural_features(self, parts: list[dict], meta: dict) -> dict[str, float]:
        """
        从 parts 列表和 meta 字典中提取业务专有的布尔/结构特征。

        Args:
            parts: 元件列表（每项含 part_type、part_size 等字段）
            meta:  布局 JSON 的 meta 节点

        Returns:
            特征名 → 0.0/1.0（或连续值）的字典，
            这些特征将合并到最终特征向量中。
        """
        ...

    # ------------------------------------------------------------------
    # 3. 大型元件判断阈值（影响 large_part_ratio 特征）
    # ------------------------------------------------------------------

    @property
    def large_part_area_threshold(self) -> float:
        """
        判断为"大型元件"的面积阈值（单位与 part_size 一致）。
        默认 10 000，子类可覆盖。
        """
        return 10_000.0

    # ------------------------------------------------------------------
    # 4. 布局优化约束参数
    # ------------------------------------------------------------------

    @property
    def layout_constraints(self) -> dict[str, Any]:
        """
        传递给 LayoutOptimizer 的约束参数字典，支持的键：
          - precision_scale (int):  坐标精度缩放，默认 1
          - margin (float):         面板边距 mm，默认 10.0
          - element_gap (float):    元件间距 mm，默认 0
          - y_penalty (int):        Y 轴惩罚倍数，默认 10
          - solver_time_limit (float): 求解超时秒数，默认 20.0
          - solver_num_workers (int):  并行线程数，默认 8
        子类按需覆盖部分键即可，未覆盖的键使用默认值。
        """
        return {}

    @property
    def default_panel_size(self) -> list[float]:
        """
        当模板或项目数据缺失面板尺寸时使用的默认值 [width, height]（mm）。
        默认 [600, 1600]，子类可覆盖。
        """
        return [600.0, 1600.0]

    # ------------------------------------------------------------------
    # 5. 颜色 / UI 配置
    # ------------------------------------------------------------------

    @property
    def unknown_part_color(self) -> str:
        """未知类型元件的兜底颜色（CSS 颜色字符串）。"""
        return "hsl(215, 16%, 55%)"

    @property
    def color_variants(self) -> tuple[tuple[int, int], ...]:
        """
        颜色变体列表，每项为 (saturation%, lightness%)，
        按黄金角依次生成元件类型色板时循环使用。
        """
        return (
            (72, 38),
            (64, 46),
            (78, 32),
            (58, 54),
        )
