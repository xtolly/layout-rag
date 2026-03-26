import csv
import os

# 定义特征的类型和权重
# continuous: 连续物理量，使用 Z-score
# count: 离散计数，使用 Log1p 平滑 + 归一化
# boolean: 二值标识，使用带共缺惩罚的哈明距离
FEATURE_SCHEMA_DEF = {
    "panel_width": {"type": "continuous", "weight": 2.0, "display_name": "面板宽度"},
    "panel_height": {"type": "continuous", "weight": 2.0, "display_name": "面板高度"},
    "panel_area": {"type": "continuous", "weight": 1.5, "display_name": "面板总面积"},
    "panel_aspect_ratio": {"type": "continuous", "weight": 100, "display_name": "面板纵横比"},
    
    "total_parts": {"type": "count", "weight": 3.0, "display_name": "元器件总数"},
    "unique_types": {"type": "count", "weight": 2.0, "display_name": "元件种类数"},
    "total_parts_area": {"type": "continuous", "weight": 2.0, "display_name": "元器件总面积"},
    "fill_ratio": {"type": "continuous", "weight": 2.5, "display_name": "空间填充率"},
    
    "avg_part_width": {"type": "continuous", "weight": 1.0, "display_name": "元件平均宽度"},
    "avg_part_height": {"type": "continuous", "weight": 1.0, "display_name": "元件平均高度"},
    "max_part_width": {"type": "continuous", "weight": 1.0, "display_name": "元件最大宽度"},
    "max_part_height": {"type": "continuous", "weight": 1.0, "display_name": "元件最大高度"},
    "width_std": {"type": "continuous", "weight": 1.0, "display_name": "元件宽度标准差"},
    "height_std": {"type": "continuous", "weight": 1.0, "display_name": "元件高度标准差"},
    
    "has_双电源": {"type": "boolean", "weight": 0.5, "display_name": "含双电源开关"},
    "has_地排": {"type": "boolean", "weight": 0.5, "display_name": "含地排"},
    "has_零排": {"type": "boolean", "weight": 0.5, "display_name": "含零排"},
    "large_part_ratio": {"type": "continuous", "weight": 1.0, "display_name": "大型元件占比"}
}

def load_part_types(file_path="data/part_name.txt"):
    part_types = []
    if not os.path.exists(file_path):
        return part_types
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            t = line.strip()
            if t:
                part_types.append(t)
    return list(set(part_types))

def get_feature_schema(file_path="data/part_name.txt"):
    schema = FEATURE_SCHEMA_DEF.copy()
    part_types = load_part_types(file_path)
    
    # 动态注入类型计数特征
    for pt in part_types:
        feat_name = f"count_{pt}"
        schema[feat_name] = {"type": "count", "weight": 2.5, "display_name": f"{pt} 数量"}
        
    return schema