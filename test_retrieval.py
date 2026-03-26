import os
import json
import random
import glob
from core.feature_extractor import FeatureExtractor
from core.vector_store import VectorStore
from config import get_feature_schema, load_part_types

def test_retrieval():
    # 1. 路径配置
    txt_path = "data/part_name.txt"
    vector_db_path = "output/vector_store.json" # 这里保持json后缀，load_from_disk会自动去读对应的.npz
    data_dir = "data/layouts/"
    
    # 2. 加载配置与向量库
    print("正在加载配置与向量库...")
    schema = get_feature_schema(txt_path)
    part_types = load_part_types(txt_path)
    
    store = VectorStore(schema)
    if not os.path.exists(vector_db_path):
        print(f"错误：向量库文件 {vector_db_path} 不存在，请先运行 build_vector_store.py")
        return
    store.load_from_disk(vector_db_path)
    
    extractor = FeatureExtractor(part_types)
    
    # 3. 随机抽取一个历史案例作为 Query
    all_files = glob.glob(os.path.join(data_dir, "*.json"), recursive=True)
    if not all_files:
        print("未找到测试数据！")
        return
    
    test_file = random.choice(all_files)
    project_id = os.path.basename(os.path.dirname(test_file))
    print(f"\n[测试输入] 选择项目 ID: {project_id}")
    print(f"[文件路径]: {test_file}")
    
    with open(test_file, 'r', encoding='utf-8') as f:
        query_json = json.load(f)
    
    # 提取特征
    query_features = extractor.extract(query_json)
    
    # 4. 执行检索
    top_k = 5
    results = store.search(query_features, top_k=top_k)
    
    # 5. 验证结果
    print(f"\n检索 Top-{top_k} 结果:")
    print("-" * 80)
    print(f"{'排名':<4} | {'距离':<10} | {'项目 ID':<10} | {'相似度评价'}")
    print("-" * 80)
    
    for i, (entry, distance) in enumerate(results):
        is_self = " (原件本身)" if entry["uuid"] == project_id else ""
        
        # 简单逻辑：距离越小越相似
        if distance == 0:
            status = "完美匹配"
        elif distance < 1.0:
            status = "高度相似"
        elif distance < 3.0:
            status = "比较相似"
        else:
            status = "一般相似"
            
        print(f"{i+1:<4} | {distance:<10.4f} | {entry['uuid']:<10} | {status}{is_self}")

    # 6. 具体特征对比 (取 Top-1 相似项，排除自身)
    best_match = None
    for entry, distance in results:
        if entry["uuid"] != project_id:
            best_match = (entry, distance)
            break
            
    if best_match:
        m_entry, m_dist = best_match
        print(f"\n[深度对比] 原始项目 {project_id} vs 最相似项目 {m_entry['uuid']} (总距离: {m_dist:.4f})")
        print("-" * 100)
        print(f"{'特征分类':<10} | {'特征名称':<25} | {'Query 值':<15} | {'匹配项值':<15} | {'差异'}")
        print("-" * 100)
        
        # 核心修改：通过召回的 source_path 反查原始特征（符合生产架构）
        m_source_path = m_entry["source_path"]
        if os.path.exists(m_source_path):
            with open(m_source_path, 'r', encoding='utf-8') as f:
                m_json = json.load(f)
            m_features_dict = extractor.extract(m_json)
        else:
            print(f"警告：找不到匹配项的源文件 {m_source_path}，无法进行特征对比。")
            return
            
        # 严谨对待默认值补全
        q_vector = [query_features.get(f, store.default_values.get(f, 0.0)) for f in store.feature_names]
        m_vector = [m_features_dict.get(f, store.default_values.get(f, 0.0)) for f in store.feature_names]
        
        # 分组定义
        groups = {
            "面板特征": ["panel_width", "panel_height", "panel_area", "panel_aspect_ratio"],
            "统计算法": ["total_parts", "unique_types", "total_parts_area", "fill_ratio", "large_part_ratio"],
            "尺寸分布": ["avg_part_width", "avg_part_height", "max_part_width", "max_part_height", "width_std", "height_std"],
            "结构特征": ["has_双电源", "has_地排", "has_零排"]
        }
        
        # 记录已打印的特征
        handled = set()
        for g_name, f_list in groups.items():
            for f_name in f_list:
                if f_name in store.feature_names:
                    idx = store.feature_names.index(f_name)
                    q_val, m_val = q_vector[idx], m_vector[idx]
                    diff = abs(q_val - m_val)
                    print(f"{g_name:<10} | {f_name:<25} | {q_val:<15.2f} | {m_val:<15.2f} | {diff:.2f}")
                    handled.add(f_name)
                    
        # 打印类型计数特征 (如果有差异则打印，或者打印前 N 个)
        count_feats = [f for f in store.feature_names if f.startswith("count_")]
        is_first_count = True
        for f_name in count_feats:
            idx = store.feature_names.index(f_name)
            q_val, m_val = q_vector[idx], m_vector[idx]
            if q_val > 0 or m_val > 0: # 只打印有数值的
                name_display = "类型分布" if is_first_count else ""
                print(f"{name_display:<10} | {f_name:<25} | {q_val:<15.2f} | {m_val:<15.2f} | {abs(q_val-m_val):.2f}")
                is_first_count = False
                handled.add(f_name)
    print("-" * 100)

if __name__ == "__main__":
    test_retrieval()