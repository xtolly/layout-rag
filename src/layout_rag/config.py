import json
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PACKAGE_ROOT.parent
PROJECT_ROOT = SRC_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data" / "layouts"
VECDB_DIR = PROJECT_ROOT / "vecdb"
STATIC_DIR = PROJECT_ROOT / "static"
VECTOR_STORE_PATH = VECDB_DIR / "vector_store.json"
PART_COLOR_PATH = STATIC_DIR / "part.color"

UNKNOWN_PART_COLOR = "hsl(215, 16%, 55%)"
_COLOR_VARIANTS = (
    (72, 38),
    (64, 46),
    (78, 32),
    (58, 54),
)

# 定义特征的类型和权重
# continuous: 连续物理量，使用 Z-score
# count: 离散计数，使用 Log1p 平滑 + 归一化
# boolean: 二值标识，使用带共缺惩罚的哈明距离
FEATURE_SCHEMA_DEF = {
    "panel_width": {"type": "continuous", "weight": 2.0, "display_name": "面板宽度"},
    "panel_height": {"type": "continuous", "weight": 2.0, "display_name": "面板高度"},
    "panel_area": {"type": "continuous", "weight": 1.5, "display_name": "面板总面积"},
    "panel_aspect_ratio": {"type": "continuous", "weight": 2, "display_name": "面板纵横比"},
    
    "total_parts": {"type": "count", "weight": 1.0, "display_name": "元器件总数"},
    "unique_types": {"type": "count", "weight": 2.0, "display_name": "元件种类数"},
    "total_parts_area": {"type": "continuous", "weight": 1.5, "display_name": "元器件总面积"},
    "fill_ratio": {"type": "continuous", "weight": 1.5, "display_name": "空间填充率"},
    
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
        "weight": 1.0,
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

def iter_layout_samples(data_dir=DATA_DIR):
    for file_path in sorted(Path(data_dir).glob("*.json")):
        try:
            with file_path.open('r', encoding='utf-8') as f:
                yield json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

def load_distinct_values(data_dir=DATA_DIR, source="meta", field=""):
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

def load_part_types(data_dir=DATA_DIR):
    config = DYNAMIC_FEATURE_SOURCES["part_type_counts"]
    return load_distinct_values(data_dir, source=config["source"], field=config["field"])

def generate_distinct_colors(count: int):
    if count <= 0:
        return []

    golden_angle = 137.508
    colors = []
    for index in range(count):
        saturation, lightness = _COLOR_VARIANTS[index % len(_COLOR_VARIANTS)]
        hue = (index * golden_angle) % 360
        colors.append(f"hsl({hue:.3f}, {saturation}%, {lightness}%)")

    return colors

def build_part_color_payload(part_types):
    normalized_part_types = sorted({str(part_type).strip() for part_type in part_types if str(part_type).strip()})
    colors = generate_distinct_colors(len(normalized_part_types))
    part_color_map = {
        part_type: colors[index]
        for index, part_type in enumerate(normalized_part_types)
    }
    return {
        "unknownColor": UNKNOWN_PART_COLOR,
        "partColorMap": part_color_map,
    }

def save_part_color_payload(part_types, output_path=PART_COLOR_PATH):
    payload = build_part_color_payload(part_types)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload

def load_part_color_payload(file_path=PART_COLOR_PATH):
    path = Path(file_path)
    fallback_payload = {
        "unknownColor": UNKNOWN_PART_COLOR,
        "partColorMap": {},
    }

    if not path.exists():
        return fallback_payload

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback_payload

    part_color_map = payload.get("partColorMap")
    if not isinstance(part_color_map, dict):
        part_color_map = {}

    return {
        "unknownColor": str(payload.get("unknownColor") or UNKNOWN_PART_COLOR),
        "partColorMap": {
            str(part_type): str(color)
            for part_type, color in part_color_map.items()
            if str(part_type).strip() and str(color).strip()
        },
    }

def load_meta_category_values(data_dir=DATA_DIR):
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

def get_feature_schema(data_dir=DATA_DIR):
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