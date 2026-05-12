import os
import sys

# 动态将 src 添加到 sys.path，保证可以正常导包
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from layout_rag.core.neo4j_client import neo4j_client
from layout_rag.domain.new_distribution_box import NewDistributionBoxDomain
from layout_rag.core.plm_importer import PLMGraphImporter

def main():
    print("==========================================")
    print("          图数据库清空与初始化工具          ")
    print("==========================================")
    
    print("\n[1] 开始清空图数据库节点与关系...")
    neo4j_client.clear_database()
    print("✅ 数据库已成功清空。")

    print("\n[2] 开始初始化向量索引...")
    domain = NewDistributionBoxDomain()
    importer = PLMGraphImporter(neo4j_client, domain)

    # 直接从 VectorStore 的内部属性中获取维度大小
    # 因为特征的全量 schema 已经在领域类中被静态定义，VectorStore 初始化时就已经算好了
    full_dim = len(importer.vector_store.feature_names)
    bom_dim = importer.vector_store.bom_dimension
    non_bom_dim = importer.vector_store.non_bom_dimension
    
    # 该方法内部已包含 DROP INDEX 逻辑，因此不存在冲突
    neo4j_client.create_vector_index_if_not_exists(full_dim, bom_dim, non_bom_dim)
    
    print(f"✅ 向量索引重建完成！")
    print(f"   - 综合维度: {full_dim}")
    print(f"   - BOM 维度: {bom_dim}")
    print(f"   - 非BOM维度: {non_bom_dim}")
    print("\n🎉 清理操作完成！现在这是一个全新的空数据库。")

if __name__ == "__main__":
    main()
