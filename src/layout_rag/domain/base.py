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
        
    def calculate_gower_similarity(self, 
                                   query_features: Dict[str, float], 
                                   template_features: Dict[str, float], 
                                   feature_ranges: Dict[str, float]) -> float:
        """
        通用的加权 Gower 相似度计算器。
        
        基于当前业务域定义的静态和动态 Schema，自动提取权重，并区分连续变量与离散/布尔变量，
        计算异构特征集合之间的高精度相似度。

        Args:
            query_features:    查询项目的特征字典 (键值对)。
            template_features: 数据库模板提取的特征字典 (键值对)。
            feature_ranges:    所有连续特征的全局极差(Ruler)，用于归一化误差。
                               (需从外部 vector_store.json 或配置中传入)

        Returns:
            float: 加权相似度得分 (范围 0.0 ~ 1.0)。
        """
        total_weight = 0.0
        weighted_similarity_sum = 0.0
        
        # 预先构建当前领域所有可能特征的权重和类型查找表
        # 这可以在实例化时缓存，这里为了清晰写在函数内部
        feature_metadata = self._build_feature_metadata_lookup()

        # 为了保证严谨性，我们需要遍历查询向量和模板向量的键集的并集
        # 因为某些动态特征（比如 count_塑壳断路器）可能只存在于其中一方
        all_keys = set(query_features.keys()).union(set(template_features.keys()))

        # 新增一个内部辅助函数，专门处理前缀匹配
        def _get_meta_for_key(k: str, lookup: dict) -> dict:
            # 1. 尝试直接命中静态特征 (如 "panel_width")
            if k in lookup and not lookup[k].get("is_dynamic_prefix"):
                return lookup[k]
            
            # 2. 尝试前缀匹配动态特征 (如 "box_classify_配电箱" 匹配 "box_classify_")
            for _, config in lookup.items():
                if config.get("is_dynamic_prefix"):
                    prefix = config.get("prefix", "___NULL___")
                    if k.startswith(prefix):
                        return config
            
            # 3. 兜底
            return {"weight": 1.0, "type": "continuous"}

        for key in all_keys:
            # 获取特征值
            q_val = float(query_features.get(key, 0.0))
            t_val = float(template_features.get(key, 0.0))
            
            # 2. 查找元数据（权重和类型）
            meta = _get_meta_for_key(key, feature_metadata)
            weight = float(meta.get("weight", 1.0))
            f_type = meta.get("type", "continuous")
            
            
            total_weight += weight
            
            # 3. 根据特征类型计算当前维度的 Gower 相似度 S_ijk
            sim = 0.0
            
            # 连续型变量 (continuous, count 等需要计算绝对误差的)
            if f_type in ("continuous", "count"):
                # 如果这个特征在我们拟合的极差字典中
                range_val = feature_ranges.get(key, 0.0)
                
                if range_val <= 0.0:
                    # 极差为 0 说明全局该特征都一样，只要值相等就是 1.0
                    sim = 1.0 if q_val == t_val else 0.0
                else:
                    # 核心归一化逻辑
                    diff = abs(q_val - t_val)
                    sim = max(0.0, 1.0 - (diff / range_val))
            
            # 离散型/布尔型变量 (boolean) - 严格匹配
            elif f_type == "boolean":
                sim = 1.0 if q_val == t_val else 0.0
                
            else:
                # 兜底：未知类型降级为严等匹配
                sim = 1.0 if q_val == t_val else 0.0
                
            # 4. 累加加权分数
            weighted_similarity_sum += (sim * weight)

        # 5. 返回归一化后的总得分
        if total_weight > 0:
            return weighted_similarity_sum / total_weight
        return 0.0
    
    def _build_feature_metadata_lookup(self) -> Dict[str, Dict]:
        lookup = {}
        
        # 1. 静态特征注入
        for f_name, config in self.feature_schema_def.items():
            lookup[f_name] = {
                "weight": config.get("weight", 1.0),
                "type": config.get("type", "continuous")
            }
            
        # 2. 动态特征注入 (利用你提到的 field 优化)
        for source_key, config in self.dynamic_feature_sources.items():
            f_type = config.get("feature_type", "boolean")
            weight = config.get("weight", 1.0)
            
            # 直接使用 field 加上下划线作为前缀，比解析模板字符串更安全
            field_name = config.get("field", "")
            prefix = f"{field_name}_" 
            
            lookup[source_key] = {
                "weight": weight,
                "type": f_type,
                "is_dynamic_prefix": True,
                "prefix": prefix  # 记录精准的匹配前缀
            }
            
        return lookup