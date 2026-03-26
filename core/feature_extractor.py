import numpy as np

class FeatureExtractor:
    def __init__(self, part_types):
        self.part_types = part_types

    def extract(self, layout_json: dict) -> dict:
        """
        从布局 JSON 的 meta 节点中提取统计特征。
        """
        meta = layout_json.get("meta", {})
        panel_size = meta.get("panel_size", [0.0, 0.0])
        parts = meta.get("parts", [])
            
        panel_w, panel_h = panel_size[0], panel_size[1]
        panel_area = panel_w * panel_h
        
        features = {}
        
        # 1. 面板特征
        features["panel_width"] = panel_w
        features["panel_height"] = panel_h
        features["panel_area"] = panel_area
        features["panel_aspect_ratio"] = panel_w / panel_h if panel_h > 0 else 0
        
        # 2. 元件统计特征
        widths = [p.get("part_size", [0, 0])[0] for p in parts]
        heights = [p.get("part_size", [0, 0])[1] for p in parts]
        areas = [w * h for w, h in zip(widths, heights)]
        
        features["total_parts"] = len(parts)
        features["unique_types"] = len(set(p.get("part_type", "") for p in parts))
        features["total_parts_area"] = sum(areas)
        features["fill_ratio"] = features["total_parts_area"] / panel_area if panel_area > 0 else 0
        features["avg_part_width"] = np.mean(widths) if widths else 0
        features["avg_part_height"] = np.mean(heights) if heights else 0
        features["max_part_width"] = np.max(widths) if widths else 0
        features["max_part_height"] = np.max(heights) if heights else 0
        features["width_std"] = np.std(widths) if widths else 0
        features["height_std"] = np.std(heights) if heights else 0
        
        # 3. 类型分布特征 (严格按照配置好的类型列表提取)
        type_counts = {pt: 0 for pt in self.part_types}
        for p in parts:
            pt = p.get("part_type", "")
            if pt in type_counts:
                type_counts[pt] += 1
                
        for pt, count in type_counts.items():
            features[f"count_{pt}"] = count
            
        # 4. 结构特征
        types_set = set(p.get("part_type", "") for p in parts)
        features["has_双电源"] = 1.0 if any("双电源" in t for t in types_set) else 0.0
        features["has_地排"] = 1.0 if any("地排" in t for t in types_set) else 0.0
        features["has_零排"] = 1.0 if any("零排" in t for t in types_set) else 0.0
        
        large_parts_count = sum(1 for a in areas if a > 10000.0)
        features["large_part_ratio"] = large_parts_count / len(parts) if parts else 0
        
        return features