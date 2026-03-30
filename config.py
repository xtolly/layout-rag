import glob
import json
import os

# 定义特征的类型和权重
# continuous: 连续物理量，使用 Z-score
# count: 离散计数，使用 Log1p 平滑 + 归一化
# boolean: 二值标识，使用带共缺惩罚的哈明距离
FEATURE_SCHEMA_DEF = {
    "panel_width": {"type": "continuous", "weight": 2.0, "display_name": "面板宽度"},
    "panel_height": {"type": "continuous", "weight": 2.0, "display_name": "面板高度"},
    "panel_area": {"type": "continuous", "weight": 1.5, "display_name": "面板总面积"},
    "panel_aspect_ratio": {"type": "continuous", "weight": 2, "display_name": "面板纵横比"},
    
    "total_parts": {"type": "count", "weight": 2.0, "display_name": "元器件总数"},
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

DYNAMIC_FEATURE_SOURCES = {
    "part_type_counts": {
        "source": "parts",
        "field": "part_type",
        "feature_type": "count",
        "weight": 2.0,
        "feature_name_template": "count_{value}",
        "display_name_template": "{value} 数量"
    },
    "cabinet_type_categories": {
        "source": "meta",
        "field": "cabinet_type",
        "feature_type": "boolean",
        "weight": 5.0,
        "feature_name_template": "cabinet_type_{value}",
        "display_name_template": "柜体类型:{value}"
    },
    "panel_type_categories": {
        "source": "meta",
        "field": "panel_type",
        "feature_type": "boolean",
        "weight": 5.0,
        "feature_name_template": "panel_type_{value}",
        "display_name_template": "面板类型:{value}"
    }
}

def iter_layout_samples(data_dir="data/layouts"):
    search_pattern = os.path.join(data_dir, "*.json")

    for file_path in glob.glob(search_pattern):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                yield json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

def load_distinct_values(data_dir="data/layouts", source="meta", field=""):
    values = set()

    for layout_sample in iter_layout_samples(data_dir):
        meta = layout_sample.get("meta", {})
        if source == "parts":
            for item in meta.get("parts", []):
                value = str(item.get(field, "")).strip()
                if value:
                    values.add(value)
        else:
            value = str(meta.get(field, "")).strip()
            if value:
                values.add(value)

    return sorted(values)

def load_part_types(data_dir="data/layouts"):
    config = DYNAMIC_FEATURE_SOURCES["part_type_counts"]
    return load_distinct_values(data_dir, source=config["source"], field=config["field"])

def load_meta_category_values(data_dir="data/layouts"):
    values_by_field = {}

    for feature_config in DYNAMIC_FEATURE_SOURCES.values():
        if feature_config["source"] != "meta" or feature_config["feature_type"] != "boolean":
            continue
        field = feature_config["field"]
        values_by_field[field] = load_distinct_values(
            data_dir,
            source=feature_config["source"],
            field=field
        )

    return values_by_field

def get_feature_schema(data_dir="data/layouts"):
    schema = {name: config.copy() for name, config in FEATURE_SCHEMA_DEF.items()}
    for feature_config in DYNAMIC_FEATURE_SOURCES.values():
        values = load_distinct_values(
            data_dir,
            source=feature_config["source"],
            field=feature_config["field"]
        )
        for value in values:
            feat_name = feature_config["feature_name_template"].format(value=value)
            schema[feat_name] = {
                "type": feature_config["feature_type"],
                "weight": feature_config["weight"],
                "display_name": feature_config["display_name_template"].format(value=value),
                "dynamic": True,
                "source": feature_config["source"],
                "field": feature_config["field"],
                "source_name": next(
                    name for name, candidate in DYNAMIC_FEATURE_SOURCES.items() if candidate is feature_config
                ),
                "value": value
            }
        
    return schema