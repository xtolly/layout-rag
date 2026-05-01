"""
全局路径与通用工具函数。

此模块仅包含框架级别的路径常量和辅助函数，
不再包含任何业务相关的特征 Schema、动态特征来源定义。
业务相关的配置请参见 layout_rag.domain 子包。
"""
import json
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from layout_rag.domain.base import BusinessDomain

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
PACKAGE_ROOT    = Path(__file__).resolve().parent
SRC_ROOT        = PACKAGE_ROOT.parent
PROJECT_ROOT    = SRC_ROOT.parent
TEMPLATES_ROOT  = PROJECT_ROOT / "templates"   # 所有业务模板的根目录
VECDB_ROOT      = PROJECT_ROOT / "vecdb"        # 所有业务向量库的根目录
STATIC_DIR      = PROJECT_ROOT / "static"
PART_COLOR_PATH = STATIC_DIR / "part.color"
SELECTION_CONFIG_PATH = STATIC_DIR / "configurator_options.json"

# 向下兼容：保留旧名常量，旧代码不会立即报错
DATA_DIR = TEMPLATES_ROOT
VECDB_DIR = VECDB_ROOT


def _normalize_option_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []

    normalized: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


class SelectionConfig(BaseModel):
    """共享选型配置的结构化定义。"""

    cabinet_use_options: list[str] = Field(default_factory=list)
    cabinet_model_options: list[str] = Field(default_factory=list)
    panel_type_options: list[str] = Field(default_factory=list)
    wiring_method_options: list[str] = Field(default_factory=list)
    operation_method_options: list[str] = Field(default_factory=list)
    part_type_options: list[str] = Field(default_factory=list)

    @field_validator(
        "cabinet_use_options",
        "cabinet_model_options",
        "panel_type_options",
        "wiring_method_options",
        "operation_method_options",
        "part_type_options",
        mode="before",
    )
    @classmethod
    def normalize_option_values(cls, value: object) -> list[str]:
        return _normalize_option_list(value)


def load_selection_config(config_path: Path = SELECTION_CONFIG_PATH) -> SelectionConfig:
    """加载选型配置，供前后端共享相同的可选值来源。"""
    raw: object = {}

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return SelectionConfig()

    if not isinstance(raw, dict):
        return SelectionConfig()

    try:
        return SelectionConfig.model_validate(raw)
    except Exception:
        return SelectionConfig()


def get_domain_paths(domain: "BusinessDomain") -> dict[str, Path]:
    """
    根据业务领域的 domain_key 推断文件路径。

    Returns:
        dict with keys:
          - data_dir:         该业务的模板 JSON 子目录
          - vecdb_dir:        该业务的向量库子目录
          - vector_store_path:向量库 JSON 文件路径
    """
    data_dir   = TEMPLATES_ROOT / domain.domain_key
    vecdb_dir  = VECDB_ROOT     / domain.domain_key
    return {
        "data_dir":          data_dir,
        "vecdb_dir":         vecdb_dir,
        "vector_store_path": vecdb_dir / "vector_store.json",
    }


# ---------------------------------------------------------------------------
# 通用数据加载工具
# ---------------------------------------------------------------------------

def iter_layout_samples(data_dir=DATA_DIR):
    """遍历 data_dir 下所有 JSON 布局文件，逐一 yield 解析结果。"""
    for file_path in sorted(Path(data_dir).glob("*.json")):
        try:
            with file_path.open('r', encoding='utf-8') as f:
                yield json.load(f)
        except (OSError, json.JSONDecodeError):
            continue


def load_distinct_values(data_dir=DATA_DIR, source="schema", field=""):
    """
    扫描所有布局样本，收集指定字段的所有不重复值。

    Args:
        data_dir: 布局 JSON 文件目录
        source:   数据来源节点：
                    "schema"       → layout_json["schema"][field]
                    "parts"        → layout_json["schema"]["parts"][*][field]
        field:    目标字段名
    """
    values = set()
    for layout_sample in iter_layout_samples(data_dir):
        schema = layout_sample.get("schema", {})

        if source == "parts":
            # 1. 直接检查 schema.get("parts") (旧版结构兼容)
            for item in schema.get("parts", []):
                value = str(item.get(field, "")).strip()
                if value:
                    values.add(value)
            
            # 2. 检查 schema.get("panels") 下的所有 parts (新版结构适配)
            for panel in schema.get("panels", []):
                for item in panel.get("parts", []):
                    value = str(item.get(field, "")).strip()
                    if value:
                        values.add(value)
        else:  # source == "schema" or fallback
            value = str(schema.get(field, "")).strip()
            if value:
                values.add(value)
    return sorted(values)


def load_part_types(domain: BusinessDomain, data_dir=DATA_DIR) -> list[str]:
    """
    从布局样本中加载该业务领域使用的所有元件类型。

    Args:
        domain:   业务领域实例，用于获取 part_type_counts 的字段配置
        data_dir: 布局 JSON 文件目录
    """
    config = domain.dynamic_feature_sources.get("part_type_counts", {})
    return load_distinct_values(data_dir, source=config.get("source", "parts"), field=config.get("field", "part_type"))


def get_feature_schema(domain: BusinessDomain, data_dir=DATA_DIR) -> dict:
    """
    根据业务领域定义构建完整的特征 Schema（静态 + 动态展开）。

    Args:
        domain:   业务领域实例
        data_dir: 布局 JSON 文件目录，用于扫描动态特征的枚举值
    """
    schema = {name: cfg.copy() for name, cfg in domain.feature_schema_def.items()}
    for source_name, feature_config in domain.dynamic_feature_sources.items():
        values = load_distinct_values(
            data_dir,
            source=feature_config["source"],
            field=feature_config["field"],
        )
        for value in values:
            feat_name = feature_config["feature_name_template"].format(value=value)
            schema[feat_name] = {
                "type":         feature_config["feature_type"],
                "weight":       feature_config["weight"],
                "display_name": feature_config["display_name_template"].format(value=value),
                "dynamic":      True,
                "source":       feature_config["source"],
                "field":        feature_config["field"],
                "source_name":  source_name,
                "value":        value,
            }
    return schema


def load_meta_category_values(domain: BusinessDomain, data_dir=DATA_DIR) -> dict[str, list[str]]:
    """
    为业务领域中所有 boolean 类型的 meta 动态特征，收集各字段的枚举值列表。
    """
    values_by_field: dict[str, list[str]] = {}
    for feature_config in domain.dynamic_feature_sources.values():
        if feature_config["source"] != "meta" or feature_config["feature_type"] != "boolean":
            continue
        field = feature_config["field"]
        values_by_field[field] = load_distinct_values(
            data_dir,
            source=feature_config["source"],
            field=field,
        )
    return values_by_field

def load_part_color_payload(domain: BusinessDomain, file_path=PART_COLOR_PATH) -> dict:
    """从磁盘加载元件颜色映射，文件不存在时返回空映射。"""
    path = Path(file_path)
    fallback = {
        "unknownColor": domain.unknown_part_color,
        "partColorMap": {},
    }
    if not path.exists():
        return fallback
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    
    return payload