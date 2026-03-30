import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from layout_rag.config import (  # noqa: E402
    DATA_DIR,
    PART_COLOR_PATH,
    VECDB_DIR,
    VECTOR_STORE_PATH,
    get_feature_schema,
    load_part_types,
    save_part_color_payload,
)
from layout_rag.core.feature_extractor import FeatureExtractor  # noqa: E402
from layout_rag.core.vector_store import VectorStore  # noqa: E402

def main():
    VECDB_DIR.mkdir(exist_ok=True)

    # 2. 初始化环境
    print("加载特征 Schema 与配置提取器...")
    schema = get_feature_schema(DATA_DIR)
    part_types = load_part_types(DATA_DIR)
    save_part_color_payload(part_types, PART_COLOR_PATH)
    print(f"元件颜色映射已生成至 {PART_COLOR_PATH}，共 {len(part_types)} 种类型")
    extractor = FeatureExtractor(part_types, schema)
    store = VectorStore(schema)
    
    # 3. 扫描并提取特征
    print(f"开始从 {DATA_DIR} 加载已处理的布局数据...")
    raw_data_list = []

    for file_path in sorted(DATA_DIR.glob("*.json")):
        try:
            with file_path.open('r', encoding='utf-8') as f:
                layout_sample = json.load(f)

            project_id = file_path.stem.rsplit('_', maxsplit=1)[-1]
            features_dict = extractor.extract(layout_sample)

            raw_data_list.append({
                "uuid": layout_sample.get("uuid"),
                "id": project_id,
                "source_path": str(file_path),
                "features": features_dict
            })
        except Exception as e:
            print(f"解析 {file_path} 时发生错误: {e}")
            
    # 4. 建库与存储
    if raw_data_list:
        print(f"正在构建向量库，共计 {len(raw_data_list)} 条数据...")
        store.build(raw_data_list)
        store.save_to_disk(str(VECTOR_STORE_PATH))
        print(f"向量库已成功保存至 {VECTOR_STORE_PATH}")
        print(f"特征总维度: {len(schema)}")
    else:
        print("未找到有效的布局 JSON 文件，建库终止。")

if __name__ == "__main__":
    main()