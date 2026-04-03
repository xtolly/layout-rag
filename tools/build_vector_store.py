import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from layout_rag.config import (  # noqa: E402
    PART_COLOR_PATH,
    get_domain_paths,
    get_feature_schema,
    load_part_types,
)
from layout_rag.domain.distribution_box import DistributionBoxDomain  # noqa: E402
from layout_rag.core.feature_extractor import FeatureExtractor  # noqa: E402
from layout_rag.core.vector_store import VectorStore  # noqa: E402


def main():
    # 初始化业务领域（如需切换业务，替换此处即可）
    domain = DistributionBoxDomain()

    # 根据 domain_key 自动推断业务子目录路径
    paths             = get_domain_paths(domain)
    data_dir          = paths["data_dir"]
    vecdb_dir         = paths["vecdb_dir"]
    vector_store_path = paths["vector_store_path"]

    if not data_dir.exists():
        print(f"错误：模板目录不存在：{data_dir}")
        return

    vecdb_dir.mkdir(parents=True, exist_ok=True)

    # 初始化特征 Schema 与提取器
    print(f"业务领域: {domain.domain_key}")
    print(f"模板目录: {data_dir}")
    print(f"向量库目录: {vecdb_dir}")
    print("加载特征 Schema 与配置提取器...")
    schema     = get_feature_schema(domain, data_dir)
    part_types = load_part_types(domain, data_dir)
    print(f"元件颜色映射已生成至 {PART_COLOR_PATH}，共 {len(part_types)} 种类型")

    extractor = FeatureExtractor(domain, part_types, schema)
    store     = VectorStore(schema)

    # 扫描并提取特征
    print(f"开始从 {data_dir} 加载已处理的布局数据...")
    raw_data_list = []

    for file_path in sorted(data_dir.glob("*.json")):
        try:
            with file_path.open('r', encoding='utf-8') as f:
                layout_sample = json.load(f)

            project_id    = file_path.stem.rsplit('_', maxsplit=1)[-1]
            features_dict = extractor.extract(layout_sample)

            raw_data_list.append({
                "uuid":        layout_sample.get("uuid"),
                "id":          project_id,
                "source_path": str(file_path),
                "features":    features_dict,
            })
        except Exception as e:
            print(f"解析 {file_path} 时发生错误: {e}")

    # 建库与存储
    if raw_data_list:
        print(f"正在构建向量库，共计 {len(raw_data_list)} 条数据...")
        store.build(raw_data_list)
        store.save_to_disk(str(vector_store_path))
        print(f"向量库已成功保存至 {vector_store_path}")
        print(f"特征总维度: {len(schema)}")
    else:
        print("未找到有效的布局 JSON 文件，建库终止。")


if __name__ == "__main__":
    main()