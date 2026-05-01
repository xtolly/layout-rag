"""
通用特征提取器。

通过注入 BusinessDomain 获取业务专属特征定义，
自身不包含任何业务硬编码（字段名、阈值、中文术语等）。
"""

from __future__ import annotations

import numpy as np

from layout_rag.domain.base import BusinessDomain


class FeatureExtractor:
    """
    从布局 JSON 的 meta 节点中提取统计特征向量。

    Args:
        domain:    业务领域实例，提供结构特征提取逻辑、大型元件阈值等。
        part_types: 该业务领域已知的所有元件类型列表（用于固定 count_ 特征维度）。
        schema:    完整特征 Schema 字典（由 get_feature_schema 生成），
                   用于推断 categorical_feature_map（动态 boolean meta 特征）。
    """

    def __init__(
        self,
        domain: BusinessDomain,
        part_types: list[str],
        schema: dict | None = None,
    ):
        self.domain = domain
        self.part_types = part_types

        # 从 schema 中推断出所有 boolean 动态特征的字段 → 枚举值列表映射
        # key: field_name, value: list of enum values
        self.categorical_feature_map: dict[str, list[str]] = {}
        # 同时记录每个字段对应的 source（"meta" | "schema"），用于提取时路由
        self.categorical_feature_source: dict[str, str] = {}
        for src_cfg in domain.dynamic_feature_sources.values():
            if src_cfg["feature_type"] == "boolean" and src_cfg["source"] == "schema":
                field = src_cfg["field"]
                self.categorical_feature_map.setdefault(field, [])
                self.categorical_feature_source[field] = "schema"

        if schema:
            for feature_name in schema:
                for field_name in self.categorical_feature_map:
                    prefix = f"{field_name}_"
                    if feature_name.startswith(prefix):
                        value = feature_name[len(prefix):]
                        if value not in self.categorical_feature_map[field_name]:
                            self.categorical_feature_map[field_name].append(value)

    def extract(self, layout_json: dict) -> dict[str, float]:
        """
        从布局 JSON 中提取完整特征字典。

        特征分组：
          1. 面板几何特征（宽、高、面积、纵横比）
          2. 元件统计特征（总数、种类数、面积统计等）
          3. 元件类型计数特征（count_{part_type}）
          4. 业务结构特征（由 domain.extract_structural_features 提供）
          5. 分类 meta 特征（动态 boolean，如 cabinet_type_XXX）
          6. 大型元件比例
        """
        # 全局统一使用 schema 节点
        schema = layout_json.get("schema", {})
        panel_size = schema.get("panel_size", [0.0, 0.0])
        parts      = schema.get("parts",      [])

        panel_w, panel_h = float(panel_size[0]), float(panel_size[1])
        panel_area = panel_w * panel_h

        features: dict[str, float] = {}

        # ── 1. 面板特征 ──
        features["panel_width"]        = panel_w
        features["panel_height"]       = panel_h
        features["panel_area"]         = panel_area
        features["panel_aspect_ratio"] = panel_w / panel_h if panel_h > 0 else 0.0

        # ── 2. 元件统计特征 ──
        widths  = [p.get("part_size", [0, 0])[0] for p in parts]
        heights = [p.get("part_size", [0, 0])[1] for p in parts]
        areas   = [w * h for w, h in zip(widths, heights)]

        features["total_parts"]      = len(parts)
        features["unique_types"]     = len({p.get("part_type", "") for p in parts})
        features["total_parts_area"] = sum(areas)
        features["fill_ratio"]       = features["total_parts_area"] / panel_area if panel_area > 0 else 0.0
        features["avg_part_width"]   = float(np.mean(widths))  if widths  else 0.0
        features["avg_part_height"]  = float(np.mean(heights)) if heights else 0.0
        features["max_part_width"]   = float(np.max(widths))   if widths  else 0.0
        features["max_part_height"]  = float(np.max(heights))  if heights else 0.0
        features["width_std"]        = float(np.std(widths))   if widths  else 0.0
        features["height_std"]       = float(np.std(heights))  if heights else 0.0

        # ── 3. 元件类型计数特征 ──
        type_counts: dict[str, int] = {pt: 0 for pt in self.part_types}
        for p in parts:
            pt = p.get("part_type", "")
            if pt in type_counts:
                type_counts[pt] += 1
        for pt, count in type_counts.items():
            features[f"count_{pt}"] = count

        # ── 4. 业务结构特征（委托给 domain）──
        features.update(self.domain.extract_structural_features(parts, schema))

        # ── 5. 分类特征（schema boolean）──
        for field_name, values in self.categorical_feature_map.items():
            current_value = str(schema.get(field_name, "")).strip()
            for value in values:
                features[f"{field_name}_{value}"] = 1.0 if current_value == value else 0.0

        # ── 6. 大型元件比例 ──
        threshold = self.domain.large_part_area_threshold
        large_count = sum(1 for a in areas if a > threshold)
        features["large_part_ratio"] = large_count / len(parts) if parts else 0.0

        return features