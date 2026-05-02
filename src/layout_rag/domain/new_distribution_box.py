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

import numpy as np

class NewDistributionBoxDomain(BusinessDomain):
    """新配电箱面板布局业务领域（中船国际数科城项目）。"""

    # ------------------------------------------------------------------
    # 0. 业务标识 Key（决定模板目录和向量库目录）
    # ------------------------------------------------------------------

    @property
    def domain_key(self) -> str:
        return "new_distribution_box"

    def get_part_types(self) -> list[str]:
        """返回新配电箱领域的所有元件类型（硬编码）。"""
        return [
            "剩余电流动作微型断路器",
            "剩余电流式电气火灾监控探测器",
            "双电源自动转换开关",
            "塑壳断路器",
            "微型断路器",
            "接触器",
            "浪涌后备保护器",
            "热继电器",
            "电涌保护器",
            "电源监控",
            "电能表",
        ]

    # ------------------------------------------------------------------
    # 1. 静态特征 Schema
    # ------------------------------------------------------------------

    @property
    def feature_schema_def(self) -> dict[str, dict]:
        part_types = self.get_part_types()
        features = {
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
            # ── 箱体分类（field 标记 schema 来源字段，extract_features 自动提取）──
            "box_classify_配电箱":     {"type": "boolean", "weight": 3.0, "display_name": "箱体分类:配电箱",     "from_bom": False, "field": "box_classify"},
            "box_classify_户箱":       {"type": "boolean", "weight": 3.0, "display_name": "箱体分类:户箱",       "from_bom": False, "field": "box_classify"},
            "box_classify_标准电表箱": {"type": "boolean", "weight": 3.0, "display_name": "箱体分类:标准电表箱", "from_bom": False, "field": "box_classify"},
            "box_classify_非标电表箱": {"type": "boolean", "weight": 3.0, "display_name": "箱体分类:非标电表箱", "from_bom": False, "field": "box_classify"},
            # ── 箱体系列 ──
            "series_DNB": {"type": "boolean", "weight": 1.0, "display_name": "系列:DNB", "from_bom": False, "field": "series"},
            "series_HW":  {"type": "boolean", "weight": 1.0, "display_name": "系列:HW",  "from_bom": False, "field": "series"},
            "series_MZ":  {"type": "boolean", "weight": 1.0, "display_name": "系列:MZ",  "from_bom": False, "field": "series"},
            "series_XM1": {"type": "boolean", "weight": 1.0, "display_name": "系列:XM1", "from_bom": False, "field": "series"},
            "series_XM2": {"type": "boolean", "weight": 1.0, "display_name": "系列:XM2", "from_bom": False, "field": "series"},
            # ── 进线方式 ──
            "inline_mode_进线器件上置": {"type": "boolean", "weight": 2.0, "display_name": "进线方式:进线器件上置", "from_bom": False, "field": "inline_mode"},
            "inline_mode_进线器件左置": {"type": "boolean", "weight": 2.0, "display_name": "进线方式:进线器件左置", "from_bom": False, "field": "inline_mode"},
            # ── 安装方式 ──
            "install_type_户内暗装": {"type": "boolean", "weight": 2.0, "display_name": "安装方式:户内暗装", "from_bom": False, "field": "install_type"},
            "install_type_户内挂墙": {"type": "boolean", "weight": 2.0, "display_name": "安装方式:户内挂墙", "from_bom": False, "field": "install_type"},
            "install_type_户内落地": {"type": "boolean", "weight": 2.0, "display_name": "安装方式:户内落地", "from_bom": False, "field": "install_type"},
            "install_type_户外挂墙": {"type": "boolean", "weight": 2.0, "display_name": "安装方式:户外挂墙", "from_bom": False, "field": "install_type"},
            "install_type_户外落地": {"type": "boolean", "weight": 2.0, "display_name": "安装方式:户外落地", "from_bom": False, "field": "install_type"},
            # ── 固定方式 ──
            "fixup_type_板式安装": {"type": "boolean", "weight": 2.0, "display_name": "固定方式:板式安装", "from_bom": False, "field": "fixup_type"},
            "fixup_type_梁式安装": {"type": "boolean", "weight": 2.0, "display_name": "固定方式:梁式安装", "from_bom": False, "field": "fixup_type"},
            # ── 门型 ──
            "door_type_左开门": {"type": "boolean", "weight": 2.0, "display_name": "门型:左开门", "from_bom": False, "field": "door_type"},
            "door_type_右开门": {"type": "boolean", "weight": 2.0, "display_name": "门型:右开门", "from_bom": False, "field": "door_type"},
            "door_type_双开门": {"type": "boolean", "weight": 2.0, "display_name": "门型:双开门", "from_bom": False, "field": "door_type"},
            # ── 电缆进出方式 ──
            "cable_in_out_type_上进下出": {"type": "boolean", "weight": 2.0, "display_name": "进出线方式:上进下出", "from_bom": False, "field": "cable_in_out_type"},
            "cable_in_out_type_上进上出_左侧出线": {"type": "boolean", "weight": 2.0, "display_name": "进出线方式:上进上出-左侧出线", "from_bom": False, "field": "cable_in_out_type"},
            "cable_in_out_type_上进上出_右侧出线": {"type": "boolean", "weight": 2.0, "display_name": "进出线方式:上进上出-右侧出线", "from_bom": False, "field": "cable_in_out_type"},
            "cable_in_out_type_下进下出_左侧进线": {"type": "boolean", "weight": 2.0, "display_name": "进出线方式:下进下出-左侧进线", "from_bom": False, "field": "cable_in_out_type"},
            "cable_in_out_type_下进下出_右侧进线": {"type": "boolean", "weight": 2.0, "display_name": "进出线方式:下进下出-右侧进线", "from_bom": False, "field": "cable_in_out_type"},
            "cable_in_out_type_下进上出_左进右出": {"type": "boolean", "weight": 2.0, "display_name": "进出线方式:下进上出-左进右出", "from_bom": False, "field": "cable_in_out_type"},
            "cable_in_out_type_下进上出_右进左出": {"type": "boolean", "weight": 2.0, "display_name": "进出线方式:下进上出-右进左出", "from_bom": False, "field": "cable_in_out_type"},
        }
        
        # ── 元件类型计数（BOM）──
        for part_type in part_types:
            features[f"count_{part_type}"] = {"type": "count", "weight": 5.0, "display_name": f"{part_type} 数量", "from_bom": True}
        return features

    # ------------------------------------------------------------------
    # 2. 特征提取
    # ------------------------------------------------------------------

    def extract_features(self, layout_json: dict) -> dict[str, float]:
        """
        从布局 JSON 中提取完整特征字典。

        特征分组：
          1. 面板几何特征（宽、高、面积、纵横比）
          2. 元件统计特征（总数、种类数、面积统计等）
          3. 元件类型计数特征（count_{part_type}）
          4. 业务结构特征（由 extract_structural_features 提供）
          5. 分类 schema 特征（boolean，如 box_classify_XXX）
          6. 大型元件比例
        """
        schema = layout_json.get("schema", {})
        panel_size = schema.get("panel_size", [0.0, 0.0])
        parts      = schema.get("parts", [])

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
        part_types = self.get_part_types()
        type_counts: dict[str, int] = {pt: 0 for pt in part_types}
        for p in parts:
            pt = p.get("part_type", "")
            if pt in type_counts:
                type_counts[pt] += 1
        for pt, count in type_counts.items():
            features[f"count_{pt}"] = count

        # ── 5. 分类特征（feature_schema_def 中带 field 的 boolean 自动提取）──
        for feature_name, fconfig in self.feature_schema_def.items():
            field = fconfig.get("field")
            if not field:
                continue
            # 将连字符统一为下划线，与 feature_schema_def 中的键名一致
            current_value = str(schema.get(field, "")).strip().replace("-", "_")
            prefix = f"{field}_"
            if feature_name.startswith(prefix):
                value = feature_name[len(prefix):]
                features[feature_name] = 1.0 if current_value == value else 0.0

        return features

    def ui_schema(self) -> dict:
        """定义前端 UI 需要展示和编辑的字段元数据"""
        return {
            "cabinet_fields": [
                {"key": "cabinet_name", "label": "柜体名称", "type": "text", "editable": True},
                {"key": "box_classify", "label": "箱体分类", "type": "select", "options": ["配电箱", "户箱", "标准电表箱", "非标电表箱"], "editable": True, "default": "配电箱"},
                {"key": "series", "label": "箱体系列", "type": "select", "options": ["XM1", "XM2", "MZ", "HW", "DNB"], "editable": True, "default": "XM1"},
                {"key": "inline_mode", "label": "进线方式", "type": "select", "options": ["进线器件上置", "进线器件左置"], "editable": True, "default": "进线器件上置"},
                {"key": "install_type", "label": "安装方式", "type": "select", "options": ["户内暗装", "户内挂墙", "户内落地", "户外挂墙", "户外落地"], "editable": True, "default": "户内暗装"},
                {"key": "fixup_type", "label": "固定方式", "type": "select", "options": ["板式安装", "梁式安装"], "editable": True, "default": "板式安装"},
                {"key": "door_type", "label": "门型", "type": "select", "options": ["左开门", "右开门", "双开门"], "editable": True, "default": "左开门"},
                {"key": "cable_in_out_type", "label": "进出线方式", "type": "select", "options": ["上进下出", "上进上出-左侧出线", "上进上出-右侧出线", "下进下出-左侧进线", "下进下出-右侧进线", "下进上出-左进右出", "下进上出-右进左出"], "editable": True, "default": "上进下出"},
                {"key": "cabinet_width", "label": "宽度(W)", "type": "number", "editable": True, "default": 500},
                {"key": "cabinet_height", "label": "高度(H)", "type": "number", "editable": True, "default": 800},
                {"key": "cabinet_depth", "label": "深度(D)", "type": "number", "editable": True, "default": 200},
            ],
            "panel_fields": [
                {"key": "panel_type", "label": "面板类型", "type": "select", "options": ["安装板", "门板"], "editable": True, "default": "安装板"},
                {"key": "panel_width", "label": "宽度(W)", "type": "number", "editable": True, "default": 500},
                {"key": "panel_height", "label": "高度(H)", "type": "number", "editable": True, "default": 800},
            ],
            "part_fields": [
                {"key": "in_line", "label": "进出线", "type": "boolean", "editable": True},
                {"key": "part_type", "label": "元件类型", "type": "text", "editable": True},
                {"key": "part_model", "label": "元件型号", "type": "text", "editable": True},
                {"key": "pole", "label": "极数", "type": "text", "editable": True},
                {"key": "current", "label": "额定电流", "type": "text", "editable": True},
                {"key": "part_width", "label": "宽(w)", "type": "number", "editable": True, "default": 60},
                {"key": "part_height", "label": "高(h)", "type": "number", "editable": True, "default": 80},
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
