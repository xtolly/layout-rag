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
from typing import Any, Dict

import numpy as np


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

    @abstractmethod
    def get_part_types(self) -> list[str]:
        """
        返回该业务领域已知的所有元件类型列表（硬编码）。
        用于生成 count_{part_type} 特征的固定维度。

        示例返回值：
          ["剩余电流动作微型断路器", "塑壳断路器", "微型断路器", ...]
        """
        ...

    @abstractmethod
    def extract_features(self, layout_json: dict) -> dict[str, float]:
        """
        从布局 JSON 中提取完整特征字典。
        """

    @abstractmethod
    def ui_schema(self) -> dict:
        """
        返回 UI 元数据，供前端表单和 AI Agent 动态生成工具 schema。

        返回格式：
        {
            "cabinet_fields": [{"key": str, "label": str, "type": "text"|"select"|"number"|"boolean", ...}],
            "panel_fields":   [...],
            "part_fields":    [...],
        }

        select 类型字段必须包含 "options": list[str]。
        """

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
        
    def calculate_gower_similarity(self,
                                   query_features: Dict[str, float],
                                   template_features: Dict[str, float],
                                   feature_ranges: Dict[str, float]) -> float:
        """
        加权 Gower 相似度计算器。

        基于 feature_schema_def 中定义的特征类型和权重，区分连续/计数型与布尔型变量，
        计算异构特征集合之间的加权相似度。

        Args:
            query_features:    查询项目的特征字典。
            template_features: 模板的特征字典。
            feature_ranges:    连续特征的全局极差（用于归一化误差）。

        Returns:
            float: 加权相似度得分 (0.0 ~ 1.0)。
        """
        # 从 feature_schema_def 构建查找表（一次遍历）
        schema = self.feature_schema_def

        all_keys = set(query_features.keys()) | set(template_features.keys())
        total_weight = 0.0
        weighted_sim = 0.0

        for key in all_keys:
            q_val = float(query_features.get(key, 0.0))
            t_val = float(template_features.get(key, 0.0))

            meta = schema.get(key)
            if meta:
                weight = float(meta.get("weight", 1.0))
                f_type = meta.get("type", "continuous")
            else:
                # 未在 schema 中定义的特征，使用默认权重
                weight = 1.0
                f_type = "continuous"

            total_weight += weight

            # 计算单维度 Gower 相似度
            if f_type == "count":
                # count 特征先做 log1p 变换，再用 count_max_log 归一化
                range_val = feature_ranges.get(key, 0.0)
                if range_val <= 0.0:
                    sim = 1.0 if q_val == t_val else 0.0
                else:
                    q_log = np.log1p(max(q_val, 0.0))
                    t_log = np.log1p(max(t_val, 0.0))
                    sim = max(0.0, 1.0 - abs(q_log - t_log) / range_val)
            elif f_type == "continuous":
                range_val = feature_ranges.get(key, 0.0)
                if range_val <= 0.0:
                    sim = 1.0 if q_val == t_val else 0.0
                else:
                    sim = max(0.0, 1.0 - abs(q_val - t_val) / range_val)
            else:
                # boolean / 离散型：严格匹配
                sim = 1.0 if q_val == t_val else 0.0

            weighted_sim += sim * weight

        return weighted_sim / total_weight if total_weight > 0 else 0.0