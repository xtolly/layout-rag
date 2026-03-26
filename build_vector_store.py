import os
import json
import glob
from config import get_feature_schema, load_part_types
from core.vector_store import VectorStore

def main():
    # 1. 路径配置
    txt_path = "data/part_name.txt"
    # 修改 data_dir 为 layouts 目录
    data_dir = "data/layouts/"  
    output_path = "output/vector_store.json"
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 2. 初始化环境
    print("加载特征 Schema 与配置提取器...")
    # 获取包含特征类型和权重的完整字典
    schema = get_feature_schema(txt_path)
    
    # VectorStore 现直接通过 schema 进行初始化
    store = VectorStore(schema)
    
    # 3. 扫描并提取特征
    print(f"开始从 {data_dir} 加载已处理的布局数据...")
    raw_data_list = []
    
    # 修改扫描模式为 *.json (不再是 layout_processed.json，因为已经重命名并平铺)
    search_pattern = os.path.join(data_dir, "*.json")
    file_paths = glob.glob(search_pattern)
    
    for file_path in file_paths:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                layout_sample = json.load(f)
            
            # 从文件名提取 project_id (文件名格式: 项目名称_projectid.json)
            # 或者直接从 layout_sample 的 meta 或 uuid 字段取
            filename = os.path.basename(file_path)
            project_id = filename.split('_')[-1].replace('.json', '')
            
            # 提取特征 (已经在预处理时提取好了，直接取字段)
            # layout_sample["features"] 是列表，需转回字典供 VectorStore 使用
            features_list = layout_sample.get("features", [])
            features_dict = {f["name"]: f["value"] for f in features_list}
            
            raw_data_list.append({
                "uuid": layout_sample.get("uuid"),
                "id": project_id,
                "source_path": file_path, # 记录新路径
                "features": features_dict
            })
        except Exception as e:
            print(f"解析 {file_path} 时发生错误: {e}")
            
    # 4. 建库与存储
    if raw_data_list:
        print(f"正在构建向量库，共计 {len(raw_data_list)} 条数据...")
        store.build(raw_data_list)
        store.save_to_disk(output_path)
        print(f"向量库已成功保存至 {output_path}")
        print(f"特征总维度: {len(schema)}")
    else:
        print("未找到有效的布局 JSON 文件，建库终止。")

if __name__ == "__main__":
    main()