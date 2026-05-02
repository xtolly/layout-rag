"""
全局路径与通用工具函数。

此模块仅包含框架级别的路径常量和辅助函数，
不再包含任何业务相关的特征 Schema、动态特征来源定义。
业务相关的配置请参见 layout_rag.domain 子包。
"""
import json
from pathlib import Path

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

# 向下兼容：保留旧名常量，旧代码不会立即报错
DATA_DIR = TEMPLATES_ROOT
VECDB_DIR = VECDB_ROOT


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