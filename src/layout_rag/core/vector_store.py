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

        # 按 BOM 来源分区索引
        self.idx_from_bom = [i for i, f in enumerate(self.feature_names) if schema[f].get("from_bom", False)]
        self.idx_not_from_bom = [i for i, f in enumerate(self.feature_names) if not schema[f].get("from_bom", False)]

        # 统计参数 (标尺)
        self.cont_min = np.zeros(len(self.idx_cont))
        self.cont_range = np.ones(len(self.idx_cont))
        self.count_max_log = np.ones(len(self.idx_count))

    def _dict_to_vector(self, feature_dict: dict) -> np.ndarray:
        # 严格根据 Schema 中定义的 default 值进行缺失插补
        return np.array([feature_dict.get(f, self.default_values[f]) for f in self.feature_names], dtype=float)


    def encode_for_neo4j(self, feature_dict: dict, mode: str | None = None) -> List[float]:
        """
        特征编码 (欧氏距离适配版本)
        对特征进行严格的 [0, 1] 归一化，并乘以权重的平方根以实现加权欧氏距离计算。

        mode:
          None           -- 全量向量
          "from_bom"     -- 仅 BOM 特征子向量
          "not_from_bom" -- 仅非 BOM 特征子向量
        """
        q_raw = self._dict_to_vector(feature_dict)
        final_vector = np.zeros(len(self.feature_names), dtype=float)

        # 1. 连续特征: 严格归一化到 [0, 1]
        if self.idx_cont:
            q_cont = np.clip((q_raw[self.idx_cont] - self.cont_min) / self.cont_range, 0.0, 1.0)
            final_vector[self.idx_cont] = q_cont * np.sqrt(self.w_cont)

        # 2. 计数特征: 严格归一化到 [0, 1]
        if self.idx_count:
            q_count_log = np.log1p(np.maximum(q_raw[self.idx_count], 0))
            q_count = np.clip(q_count_log / self.count_max_log, 0.0, 1.0)
            final_vector[self.idx_count] = q_count * np.sqrt(self.w_count)

        # 3. 布尔特征: 截断保持 [0, 1]
        if self.idx_bool:
            q_bool = np.clip(q_raw[self.idx_bool], 0.0, 1.0)
            final_vector[self.idx_bool] = q_bool * np.sqrt(self.w_bool)

        # 按模式裁剪子向量
        if mode == "from_bom":
            return final_vector[self.idx_from_bom].tolist()
        elif mode == "not_from_bom":
            return final_vector[self.idx_not_from_bom].tolist()
        return final_vector.tolist()

    @property
    def bom_dimension(self) -> int:
        return len(self.idx_from_bom)

    @property
    def non_bom_dimension(self) -> int:
        return len(self.idx_not_from_bom)

    def fit_and_save_ruler(self, filepath: str, raw_data_list: List[dict]):
        """
        基于历史数据拟合统计极值（标尺）并持久化到磁盘。
        """
        if not raw_data_list:
            print("[错误] 未提取到任何有效特征，无法完成标尺拟合！")
            return False

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

        # 4. 持久化标尺
        meta_data = {
            "version": "6.1_stat_params_only",
            "params": {
                "cont_min": self.cont_min.tolist(),
                "cont_range": self.cont_range.tolist(),
                "count_max_log": self.count_max_log.tolist()
            }
        }
        with open(filepath, 'w+', encoding='utf-8') as f:
            json.dump(meta_data, f, ensure_ascii=False, indent=2)
        print(f"标尺拟合完成并已保存至 {filepath}")
        return True

    def load_ruler(self, filepath: str):
        """
        从磁盘恢复基准标尺极值。
        特征配置(Schema)和权重完全由初始化时传入的 Python 源码主导。
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        params = data.get("params", {})
        
        # 提取极值
        saved_cont_min = np.array(params.get("cont_min", []))
        
        # 防呆校验：如果代码里增删了特征，导致维度和硬盘里的旧标尺对不上，必须报错阻止
        saved_count_max_log = np.array(params.get("count_max_log", []))
        if len(self.idx_cont) > 0 and len(self.idx_cont) != len(saved_cont_min):
            raise ValueError(
                f"连续特征维度不匹配：代码 {len(self.idx_cont)} vs 标尺 {len(saved_cont_min)}。\n"
                "请删除旧的 vector_store.json 并重新运行拟合。"
            )
        if len(self.idx_count) > 0 and len(self.idx_count) != len(saved_count_max_log):
            raise ValueError(
                f"计数特征维度不匹配：代码 {len(self.idx_count)} vs 标尺 {len(saved_count_max_log)}。\n"
                "请删除旧的 vector_store.json 并重新运行拟合。"
            )
            
        # 恢复统计极值
        self.cont_min = saved_cont_min
        self.cont_range = np.array(params.get("cont_range", []))
        self.count_max_log = saved_count_max_log
        
        print("纯净标尺极值加载完毕，特征权重已完全听从 Python 代码指挥。")

    def get_feature_ranges(self) -> dict[str, float]:
        """
        获取连续型和计数型特征的全局极差 (Ruler)。
        直接从 VectorStore 的内部 numpy 数组 (cont_range, count_max_log) 中提取，
        并映射回具体的特征键名，供 Gower 算法进行精确归一化计算。
        """
        ranges_dict = {}

        # 1. 映射连续型特征的极差 (cont_range)
        # self.idx_cont 记录了连续特征在 feature_names 中的位置
        for i, f_idx in enumerate(self.idx_cont):
            feature_name = self.feature_names[f_idx]
            if i < len(self.cont_range):
                ranges_dict[feature_name] = float(self.cont_range[i])

        # 2. 映射计数型特征的极差 (count_max_log)
        # 注意：由于你的向量化逻辑对 count 特征使用了 log1p 处理，
        # 这里的极差返回的是对数化后的最大值。
        for i, f_idx in enumerate(self.idx_count):
            feature_name = self.feature_names[f_idx]
            if i < len(self.count_max_log):
                ranges_dict[feature_name] = float(self.count_max_log[i])

        return ranges_dict