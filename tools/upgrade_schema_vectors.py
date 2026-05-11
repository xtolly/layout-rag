import json
import sys
import os
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from layout_rag.core.neo4j_client import neo4j_client
from layout_rag.core.plm_importer import PLMGraphImporter
from layout_rag.domain.new_distribution_box import NewDistributionBoxDomain

def upgrade_vectors():
    print("=== 开始更新图数据库特征向量 ===")
    
    # 1. 实例化 Importer 和 VectorStore
    domain = NewDistributionBoxDomain()
    importer = PLMGraphImporter(neo4j_client, domain)
    
    # 显式重建 Vector Index
    dummy_sample = {
        "schema": {
            "cabinet_width": 0, "cabinet_height": 0, "cabinet_depth": 0,
            "install_type": "", "inline_mode": "", "fixup_type": "",
            "door_type": "", "cable_in_out_type": "", "box_classify": "",
            "panel_size": [0, 0], "parts": []
        }
    }
    feature_dict = domain.extract_features(dummy_sample)
    full_dim = len(importer.vector_store.encode_for_neo4j(feature_dict))
    bom_dim = importer.vector_store.bom_dimension
    non_bom_dim = importer.vector_store.non_bom_dimension
    neo4j_client.create_vector_index_if_not_exists(full_dim, bom_dim, non_bom_dim)
    
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'templates', 'new_distribution_box')
    if not os.path.exists(data_dir):
        print(f"错误: 找不到模板目录 {data_dir}")
        return

    # 2. 读取所有历史 JSON 文件
    all_data = []
    for filename in os.listdir(data_dir):
        if filename.endswith(".json"):
            file_path = os.path.join(data_dir, filename)
            with open(file_path, 'r', encoding='utf-8') as f:
                all_data.append(json.load(f))

    print(f"共发现 {len(all_data)} 个原始方案，开始重算向量...")

    updates = []
    for data in all_data:
        schema = data.get("schema", {})
        panel_id = schema.get("panel_id")
        if not panel_id:
            continue
            
        try:
            # 使用最新的 Schema 和静态标尺提取向量
            feature_dict = importer.domain.extract_features(data)
            vector_list = importer.vector_store.encode_for_neo4j(feature_dict)
            bom_vector_list = importer.vector_store.encode_for_neo4j(feature_dict, mode="from_bom")
            non_bom_vector_list = importer.vector_store.encode_for_neo4j(feature_dict, mode="not_from_bom")
            
            updates.append({
                "panel_id": panel_id,
                "vector_list": vector_list,
                "bom_vector_list": bom_vector_list,
                "non_bom_vector_list": non_bom_vector_list
            })
        except Exception as e:
            print(f"[警告] 面板 {panel_id} 重新编码失败: {e}")
            
    if not updates:
        print("[提示] 没有找到可更新的面板向量。")
        return
        
    # 3. 批量更新 Neo4j
    cypher = """
    UNWIND $updates AS u
    MATCH (pi:PanelInstance {ID: u.panel_id})
    SET pi.FeatureVector = u.vector_list,
        pi.BomFeatureVector = u.bom_vector_list,
        pi.NonBomFeatureVector = u.non_bom_vector_list
    """
    try:
        with neo4j_client.driver.session(database=neo4j_client.database) as session:
            session.run(cypher, updates=updates)
        print(f"[SUCCESS] 成功升级了 {len(updates)} 个面板的特征向量维度！")
    except Exception as e:
        print(f"[ERROR] 更新向量至数据库失败: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    upgrade_vectors()
