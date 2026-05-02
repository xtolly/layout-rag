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