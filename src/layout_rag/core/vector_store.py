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

        # 统计参数 (静态业务标尺) - 强校验配置完整性
        try:
            self.cont_min = np.array([schema[self.feature_names[i]]["min"] for i in self.idx_cont], dtype=float)
            cont_max = np.array([schema[self.feature_names[i]]["max"] for i in self.idx_cont], dtype=float)
        except KeyError as e:
            raise ValueError(f"配置错误：特征领域中的连续特征缺少边界定义 {e}，必须提供 'min' 和 'max'")

        self.cont_range = cont_max - self.cont_min
        self.cont_range[self.cont_range == 0] = 1.0 # 防止除零

        try:
            max_counts = np.array([schema[self.feature_names[i]]["max_count"] for i in self.idx_count], dtype=float)
        except KeyError as e:
            raise ValueError(f"配置错误：特征领域中的计数特征缺少边界定义 {e}，必须提供 'max_count'")

        self.count_max_log = np.log1p(max_counts)
        self.count_max_log[self.count_max_log == 0] = 1.0 # 防止除零
        
        # 标尺已就绪
        self.encoder_ready = True

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