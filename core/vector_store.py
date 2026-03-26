import json
import numpy as np
from typing import List, Dict, Tuple

class VectorStore:
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
        
        # 提取各组权重
        self.w_cont = np.array([schema[self.feature_names[i]]["weight"] for i in self.idx_cont])
        self.w_count = np.array([schema[self.feature_names[i]]["weight"] for i in self.idx_count])
        self.w_bool = np.array([schema[self.feature_names[i]]["weight"] for i in self.idx_bool])
        
        # 提取各组默认值
        self.default_values = {f: schema[f].get("default", 0.0) for f in self.feature_names}
        
        # 统计参数
        self.cont_min = np.zeros(len(self.idx_cont))
        self.cont_range = np.ones(len(self.idx_cont))
        self.count_max_log = np.ones(len(self.idx_count))
        
        self.entries = []
        self.db_matrix_cont = np.array([])
        self.db_matrix_count = np.array([])
        self.db_matrix_bool = np.array([])

    def _dict_to_vector(self, feature_dict: dict) -> np.ndarray:
        # 严格根据 Schema 中定义的 default 值进行缺失插补
        return np.array([feature_dict.get(f, self.default_values[f]) for f in self.feature_names], dtype=float)

    def build(self, raw_data_list: List[dict]):
        if not raw_data_list:
            return
            
        self.entries = []
            
        # 1. 解析基础矩阵
        matrix = np.array([self._dict_to_vector(item["features"]) for item in raw_data_list])
        
        # 2. 连续特征 (Continuous) -> Min-Max
        if self.idx_cont:
            m_cont = matrix[:, self.idx_cont]
            self.cont_min = np.min(m_cont, axis=0)
            cont_max = np.max(m_cont, axis=0)
            self.cont_range = cont_max - self.cont_min
            self.cont_range[self.cont_range == 0] = 1.0
            self.db_matrix_cont = (m_cont - self.cont_min) / self.cont_range
            
        # 3. 计数特征 (Count) -> Log1p + Max缩放
        if self.idx_count:
            m_count = matrix[:, self.idx_count]
            m_count_log = np.log1p(np.maximum(m_count, 0)) 
            self.count_max_log = np.max(m_count_log, axis=0)
            self.count_max_log[self.count_max_log == 0] = 1.0
            self.db_matrix_count = m_count_log / self.count_max_log
            
        # 4. 布尔特征 (Boolean) -> 强制截断，清洗脏数据
        if self.idx_bool:
            self.db_matrix_bool = np.clip(matrix[:, self.idx_bool], 0.0, 1.0)
            
        # 5. 存储元数据 (仅保留 uuid 和 source_path)
        for i, item in enumerate(raw_data_list):
            self.entries.append({
                "uuid": item.get("uuid"),
                "source_path": item["source_path"]
            })

    def search(self, query_features: dict, top_k: int = 3) -> List[Tuple[dict, float]]:
        if not self.entries:
            return []
            
        q_raw = self._dict_to_vector(query_features)
        total_dist_sq = np.zeros(len(self.entries))
        
        # 1. 连续特征距离计算
        if self.idx_cont:
            q_cont = np.clip((q_raw[self.idx_cont] - self.cont_min) / self.cont_range, 0.0, 1.0)
            diff_cont = self.db_matrix_cont - q_cont
            total_dist_sq += np.sum((diff_cont ** 2) * self.w_cont, axis=1)
            
        # 2. 计数特征距离计算
        if self.idx_count:
            q_count_log = np.log1p(np.maximum(q_raw[self.idx_count], 0))
            q_count = np.clip(q_count_log / self.count_max_log, 0.0, 1.0)
            diff_count = self.db_matrix_count - q_count
            total_dist_sq += np.sum((diff_count ** 2) * self.w_count, axis=1)
            
        # 3. 布尔特征距离计算
        if self.idx_bool:
            q_bool = np.clip(q_raw[self.idx_bool], 0.0, 1.0)
            diff_bool = self.db_matrix_bool - q_bool
            total_dist_sq += np.sum((diff_bool ** 2) * self.w_bool, axis=1)
            
        # 4. 融合最终距离
        final_distances = np.sqrt(total_dist_sq)
        
        # 5. 排序输出
        actual_top_k = min(top_k, len(self.entries))
        
        if actual_top_k == len(self.entries):
            top_indices = np.argsort(final_distances)
        else:
            top_indices = np.argpartition(final_distances, actual_top_k - 1)[:actual_top_k]
            top_indices = top_indices[np.argsort(final_distances[top_indices])]
            
        return [(self.entries[idx], float(final_distances[idx])) for idx in top_indices]

    def save_to_disk(self, filepath: str):
        meta_data = {
            "version": 5, 
            "schema": self.schema,
            "params": {
                "cont_min": self.cont_min.tolist(),
                "cont_range": self.cont_range.tolist(),
                "count_max_log": self.count_max_log.tolist()
            },
            "entries": self.entries
        }
        
        # 1. 保存 JSON 元数据
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(meta_data, f, ensure_ascii=False, indent=2)
            
        # 2. 保存压缩后的二进制 Numpy 矩阵包
        npz_path = filepath + ".npz"
        np.savez_compressed(
            npz_path,
            cont=self.db_matrix_cont,
            count=self.db_matrix_count,
            bool=self.db_matrix_bool
        )

    def load_from_disk(self, filepath: str):
        # 1. 加载 JSON 元数据
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        self.schema = data["schema"]
        self.feature_names = list(self.schema.keys())
        self.default_values = {f: self.schema[f].get("default", 0.0) for f in self.feature_names}
        
        # 重建索引和权重
        self.idx_cont = [i for i, f in enumerate(self.feature_names) if self.schema[f]["type"] == "continuous"]
        self.idx_count = [i for i, f in enumerate(self.feature_names) if self.schema[f]["type"] == "count"]
        self.idx_bool = [i for i, f in enumerate(self.feature_names) if self.schema[f]["type"] == "boolean"]
        
        self.w_cont = np.array([self.schema[self.feature_names[i]]["weight"] for i in self.idx_cont])
        self.w_count = np.array([self.schema[self.feature_names[i]]["weight"] for i in self.idx_count])
        self.w_bool = np.array([self.schema[self.feature_names[i]]["weight"] for i in self.idx_bool])
        
        # 恢复统计参数
        self.cont_min = np.array(data["params"]["cont_min"])
        self.cont_range = np.array(data["params"]["cont_range"])
        self.count_max_log = np.array(data["params"]["count_max_log"])
        
        self.entries = data["entries"]
        
        # 2. 从 .npz 压缩包中恢复矩阵数据
        npz_path = filepath + ".npz"
        with np.load(npz_path) as npz_file:
            self.db_matrix_cont = npz_file['cont']
            self.db_matrix_count = npz_file['count']
            self.db_matrix_bool = npz_file['bool']