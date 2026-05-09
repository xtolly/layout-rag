import json
import sys
import os
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# 假设这些是你已有的领域类和配置
from layout_rag.domain.new_distribution_box import NewDistributionBoxDomain
from layout_rag.core.vector_store import VectorStore
from layout_rag.config import get_domain_paths
from layout_rag.core.neo4j_client import Neo4jClient, neo4j_client

from layout_rag.core.plm_importer import PLMGraphImporter

# ================= 测试运行 =================
if __name__ == "__main__":

    data_dir = os.path.join(os.path.dirname(__file__), '..', 'templates', 'new_distribution_box')
    
    if not os.path.exists(data_dir):
        print(f"错误: 找不到目录 {data_dir}")
        exit(1)

    # 联调期间清空历史
    neo4j_client.clear_database()
    
    domain = NewDistributionBoxDomain()
    importer = PLMGraphImporter(neo4j_client, domain)

    # 预加载所有 JSON 数据
    all_data = []
    for filename in os.listdir(data_dir):
        if filename.endswith(".json"):
            file_path = os.path.join(data_dir, filename)
            with open(file_path, 'r', encoding='utf-8') as f:
                all_data.append(json.load(f))

    # 阶段一已废弃，标尺现由业务静态边界定义，VectorStore在初始化时即已准备就绪。

    # ========================================================
    # 阶段二：使用正确极值进行特征编码与入库
    # ========================================================
    print("\n--- 阶段二：开始执行全量数据特征编码与 Neo4j 拓扑入库 ---")
    count = 0
    for data in all_data:
        try:
            importer.import_plm_data(data)
            count += 1
        except Exception as e:
            print(f"处理失败跳过，原因: {e}")
    
    print(f"\n[OK] 导入完成，共成功处理并编码 {count} 个模板文件。")
    
    # ========================================================
    # 阶段三：挖掘图谱，构建型号之间的共现网络
    # ========================================================
    # 设定阈值：例如至少在2个以上不同的面板里共同出现过，才认为是有效的电气配套逻辑
    importer.build_co_occurrence_graph(min_freq=2)