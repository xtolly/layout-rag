import json
import numpy as np
from typing import List, Dict, Tuple

class VectorStore:
    """
    重构后：本类不再承担本地矩阵存储和相似度计算功能。
    现已蜕变为专门为 Neo4j 向量引擎服务的“特征编码器 (Feature Encoder)”。
    """
    def __init__(self, schema: Dict[str, dict]):
        """
        schema 格式示例: 
        {
            "feature_name": {
                "type": "continuous|count|boolean", 
                "weight": 1.0,
                "default": 0.0  
            }
        }
        """
        self.schema = schema
        self.feature_names = list(schema.keys())
        
        # 特征分组索引
        self.idx_cont = [i for i, f in enumerate(self.feature_names) if schema[f]["type"] == "continuous"]
        self.idx_count = [i for i, f in enumerate(self.feature_names) if schema[f]["type"] == "count"]
        self.idx_bool = [i for i, f in enumerate(self.feature_names) if schema[f]["type"] == "boolean"]
        
        # 提取各组权重 (直接提取，在 encode 时会取平方根)
        self.w_cont = np.array([schema[self.feature_names[i]]["weight"] for i in self.idx_cont])
        self.w_count = np.array([schema[self.feature_names[i]]["weight"] for i in self.idx_count])
        self.w_bool = np.array([schema[self.feature_names[i]]["weight"] for i in self.idx_bool])
        
        # 提取各组默认值
        self.default_values = {f: schema[f].get("default", 0.0) for f in self.feature_names}
        
        # 统计参数 (标尺)
        self.cont_min = np.zeros(len(self.idx_cont))
        self.cont_range = np.ones(len(self.idx_cont))
        self.count_max_log = np.ones(len(self.idx_count))

    def _dict_to_vector(self, feature_dict: dict) -> np.ndarray:
        # 严格根据 Schema 中定义的 default 值进行缺失插补
        return np.array([feature_dict.get(f, self.default_values[f]) for f in self.feature_names], dtype=float)

    def build(self, raw_data_list: List[dict]):
        """
        阶段一：拟合基准参数。
        注意：仅用于计算统计极值，不再本地保存巨大的 Numpy 数据矩阵。
        """
        if not raw_data_list:
            return
            
        # 1. 解析基础矩阵
        matrix = np.array([self._dict_to_vector(item["features"]) for item in raw_data_list])
        
        # 2. 连续特征 (Continuous) -> 获取 Min-Max 标尺
        if self.idx_cont:
            m_cont = matrix[:, self.idx_cont]
            self.cont_min = np.min(m_cont, axis=0)
            cont_max = np.max(m_cont, axis=0)
            self.cont_range = cont_max - self.cont_min
            self.cont_range[self.cont_range == 0] = 1.0
            
        # 3. 计数特征 (Count) -> 获取 Max_log 标尺
        if self.idx_count:
            m_count = matrix[:, self.idx_count]
            m_count_log = np.log1p(np.maximum(m_count, 0)) 
            self.count_max_log = np.max(m_count_log, axis=0)
            self.count_max_log[self.count_max_log == 0] = 1.0

        print("标尺计算完成，可将其保存至磁盘或对单条数据进行 Neo4j 编码。")

    def encode_for_neo4j(self, feature_dict: dict) -> List[float]:
        """
        阶段二：特征编码（骗过 Neo4j 的核心魔术）
        对特征进行归一化，并乘以权重的平方根。返回一维 Float 数组。
        无论是【历史数据入库 Neo4j】，还是【新订单请求查询 Neo4j】，都必须经过此方法！
        """
        q_raw = self._dict_to_vector(feature_dict)
        final_vector = []
        
        # 1. 连续特征: 归一化 + 乘以【权重平方根】
        if self.idx_cont:
            q_cont = np.clip((q_raw[self.idx_cont] - self.cont_min) / self.cont_range, 0.0, 1.0)
            scaled_cont = q_cont * np.sqrt(self.w_cont)
            final_vector.extend(scaled_cont.tolist())
            
        # 2. 计数特征: 归一化 + 乘以【权重平方根】
        if self.idx_count:
            q_count_log = np.log1p(np.maximum(q_raw[self.idx_count], 0))
            q_count = np.clip(q_count_log / self.count_max_log, 0.0, 1.0)
            scaled_count = q_count * np.sqrt(self.w_count)
            final_vector.extend(scaled_count.tolist())
            
        # 3. 布尔特征: 强制截断 + 乘以【权重平方根】
        if self.idx_bool:
            q_bool = np.clip(q_raw[self.idx_bool], 0.0, 1.0)
            scaled_bool = q_bool * np.sqrt(self.w_bool)
            final_vector.extend(scaled_bool.tolist())
            
        return final_vector

    def search_via_neo4j(self, query_features: dict, neo4j_session, top_k: int = 5) -> List[Tuple[str, float]]:
        """
        阶段三：毫秒级在线推荐
        不再使用本地 for 循环比对，直接向 Neo4j 发起原生向量索引检索。
        
        参数:
            query_features: 新订单的特征字典
            neo4j_session: Neo4j 的 active session
            top_k: 需要返回的最相似面板数量
        返回:
            List[Tuple[InstanceID, Score]]
        """
        # 1. 本地特征预缩放编码
        target_vector = self.encode_for_neo4j(query_features)
        
        # 2. 使用 Neo4j HNSW 向量索引查询 (请确保数据库中已创建名为 Panel_Feature_Index 的索引)
        cypher_query = """
        CALL db.index.vector.queryNodes('Panel_Feature_Index', $top_k, $target_vector) 
        YIELD node AS panel, score
        RETURN panel.InstanceID AS instance_id, score
        """
        
        # 3. 移交算力，拉取结果
        result = neo4j_session.run(cypher_query, top_k=top_k, target_vector=target_vector)
        
        return [(record["instance_id"], float(record["score"])) for record in result]

    def save_to_disk(self, filepath: str):
        """仅保存特征 Schema 和拟合出来的标尺极值，彻底抛弃笨重的 .npz 矩阵。"""
        meta_data = {
            "version": "6.0_neo4j_encoder", 
            "schema": self.schema,
            "params": {
                "cont_min": self.cont_min.tolist(),
                "cont_range": self.cont_range.tolist(),
                "count_max_log": self.count_max_log.tolist()
            }
        }
        with open(filepath, 'w+', encoding='utf-8') as f:
            json.dump(meta_data, f, ensure_ascii=False, indent=2)
        print(f"标尺已保存至 {filepath}")

    def load_from_disk(self, filepath: str):
        """恢复基准标尺，让编码器准备就绪。"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        self.schema = data["schema"]
        self.feature_names = list(self.schema.keys())
        self.default_values = {f: self.schema[f].get("default", 0.0) for f in self.feature_names}
        
        # 恢复索引和权重
        self.idx_cont = [i for i, f in enumerate(self.feature_names) if self.schema[f]["type"] == "continuous"]
        self.idx_count = [i for i, f in enumerate(self.feature_names) if self.schema[f]["type"] == "count"]
        self.idx_bool = [i for i, f in enumerate(self.feature_names) if self.schema[f]["type"] == "boolean"]
        
        self.w_cont = np.array([self.schema[self.feature_names[i]]["weight"] for i in self.idx_cont])
        self.w_count = np.array([self.schema[self.feature_names[i]]["weight"] for i in self.idx_count])
        self.w_bool = np.array([self.schema[self.feature_names[i]]["weight"] for i in self.idx_bool])
        
        # 恢复统计极值
        self.cont_min = np.array(data["params"]["cont_min"])
        self.cont_range = np.array(data["params"]["cont_range"])
        self.count_max_log = np.array(data["params"]["count_max_log"])
        
        print("标尺已加载，编码器就绪。")