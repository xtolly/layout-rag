import os
import json
import math
from typing import List, Dict, Optional

from layout_rag.domain.base import BusinessDomain
from layout_rag.config import (
    get_domain_paths,
    get_feature_schema,
    load_part_color_payload,
    load_part_types,
)
from layout_rag.core.feature_extractor import FeatureExtractor
from layout_rag.core.layout_optimizer import LayoutOptimizer
from layout_rag.core.vector_store import VectorStore
from layout_rag.core.neo4j_client import Neo4jClient, neo4j_client

class LayoutService:
    """
    布局服务主类。

    Args:
        domain: 业务领域实例，描述该业务的特征 Schema、约束参数等。
                数据目录和向量库路径由 domain.domain_key 自动推断：
                  templates/<domain_key>/
                  vecdb/<domain_key>/vector_store.json
    """

    def __init__(self, domain: BusinessDomain):
        self.domain = domain

        paths = get_domain_paths(domain)
        data_dir         = paths["data_dir"]
        vector_store_path = paths["vector_store_path"]

        self.schema_def = get_feature_schema(domain, str(data_dir))
        self.part_types = load_part_types(domain, str(data_dir))

        self.store = VectorStore(self.schema_def)
        self.store.load_from_disk(str(vector_store_path))
        self.extractor = FeatureExtractor(domain, self.part_types, self.schema_def)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _to_python_value(value):
        if hasattr(value, "item"):
            return value.item()
        return value

    @staticmethod
    def _resolve_feature_status(q_value, t_value, feature_type: str) -> str:
        if feature_type in {"continuous", "count"}:
            diff_abs  = abs(q_value - t_value)
            base_val  = max(abs(q_value), abs(t_value), 0.001)
            diff_ratio = diff_abs / base_val

            if diff_abs <= 1e-6:
                return "green"
            if diff_ratio <= 0.15:
                return "yellow"
            if diff_ratio <= 0.45:
                return "orange"
            return "red"

        return "green" if q_value == t_value else "red"

    def _load_template_data(self, template_id: str) -> Optional[dict]:
        """从 Neo4j 数据库加载指定 ID 的布局模板数据。"""
        return neo4j_client.get_layout_by_id(template_id)

    def _load_other_templates(self, template_uuids: List[str], selected_uuid: str) -> List[dict]:
        templates, seen = [], set()
        for uuid in (template_uuids or []):
            if not uuid or uuid == selected_uuid or uuid in seen:
                continue
            seen.add(uuid)
            tpl = self._load_template_data(uuid)
            if tpl:
                templates.append(tpl)
        return templates

    # ------------------------------------------------------------------
    # 核心业务方法
    # ------------------------------------------------------------------

    def calculate_diff_info(self, query_parts: list, template_parts: list) -> dict:
        """计算零件组成差异（matched / extra / missing）。"""
        q_counts: dict = {}
        for p in query_parts:
            pt = p.get("part_type")
            q_counts[pt] = q_counts.get(pt, 0) + 1

        t_counts: dict = {}
        for p in template_parts:
            pt = p.get("part_type")
            t_counts[pt] = t_counts.get(pt, 0) + 1

        all_types = set(list(q_counts.keys()) + list(t_counts.keys()))
        matched = extra = missing = 0
        for pt in all_types:
            qc, tc = q_counts.get(pt, 0), t_counts.get(pt, 0)
            matched += min(qc, tc)
            if qc > tc:
                extra   += qc - tc
            if tc > qc:
                missing += tc - qc
        return {"matched": matched, "extra": extra, "missing": missing}

    def get_feature_diff_list(self, q_features, t_features) -> List[Dict]:
        """生成详细特征差异比对（按权重降序）。"""
        diff_list = []
        for f_name, f_info in self.schema_def.items():
            qv = self._to_python_value(q_features.get(f_name, 0))
            tv = self._to_python_value(t_features.get(f_name, 0))

            diff_list.append({
                "name":          f_name,
                "type":          f_info.get("type", "continuous"),
                "weight":        self._to_python_value(f_info.get("weight", 0)),
                "dynamic":       f_info.get("dynamic", False),
                "source":        f_info.get("source"),
                "field":         f_info.get("field"),
                "sourceName":    f_info.get("source_name"),
                "featureValue":  f_info.get("value"),
                "displayName":   f_info.get("display_name", f_name),
                "uploadedValue": qv,
                "templateValue": tv,
                "status":        self._resolve_feature_status(qv, tv, f_info.get("type", "continuous")),
            })

        diff_list.sort(key=lambda item: (-item["weight"], not item["dynamic"], item["name"]))
        return diff_list

    def search_recommendations(self, project_data: dict, top_k: int = 10) -> list:
        """执行推荐搜索全流程，采用“搜 ID + 批量取详情”两步走。"""
        query_features = self.extractor.extract(project_data)
        query_vector = self.store.encode_for_neo4j(query_features)

        # 1. 第一步：向 Neo4j 发起向量检索，仅召回 ID 和分数
        search_results = neo4j_client.search_similar_panel(query_vector, top_k)
        if not search_results:
            return []
            
        panel_ids = [r["panel_id"] for r in search_results]
        scores_map = {r["panel_id"]: r["score"] for r in search_results}

        # 2. 第二步：批量从数据库获取这些面板的完整拓扑数据
        details_from_db = neo4j_client.get_layouts_by_ids(panel_ids)

        templates = []
        for tpl_data in details_from_db:
            tpl_meta = tpl_data.get("schema", {})
            panel_id = tpl_meta.get("panel_id")
            
            # 提取特征用于差异比对
            tpl_features = self.extractor.extract(tpl_data)

            # 计算零件和特征差异
            query_parts = project_data.get("schema", {}).get("parts", [])
            template_parts = tpl_meta.get("parts", [])
            diff_info = self.calculate_diff_info(query_parts, template_parts)
            feature_diffs = self.get_feature_diff_list(query_features, t_features=tpl_features)

            # 综合评分：结合向量得分和零件数量差异
            # 使用 scores_map 找回该 ID 对应的向量得分
            score = round(scores_map.get(panel_id, 0.0) * 100)

            templates.append({
                "uuid":         tpl_data["uuid"],
                "name":         tpl_data.get("name"),
                "score":        score,
                "showFeatures": False,
                "schema":       tpl_meta,
                "diffInfo":     diff_info,
                "featureDiffs": feature_diffs,
                "arrange":      tpl_data.get("arrange", {}),
            })

        # 按综合评分降序排列
        templates.sort(key=lambda x: x["score"], reverse=True)
        return templates

    def get_part_color_map(self) -> Dict[str, object]:
        return load_part_color_payload(self.domain)

    def apply_layout_template(
        self,
        template_uuid: str,
        project_data: dict,
        other_template_uuids: List[str] | None = None,
    ) -> dict:
        """
        应用推荐方案的排版逻辑：寻找模板中类型一致且尺寸最接近的元件进行坐标迁移。
        """
        tpl_data = self._load_template_data(template_uuid)
        if not tpl_data:
            return {"project_data": project_data, "template_data": None}

        other_templates = self._load_other_templates(other_template_uuids or [], template_uuid)

        # 从业务领域获取布局约束参数
        constraints = self.domain.layout_constraints
        layout_optimizer = LayoutOptimizer(
            domain              = self.domain,
            precision_scale     = constraints.get("precision_scale",    1),
            margin              = constraints.get("margin",             10.0),
            element_gap         = constraints.get("element_gap",        0.0),
            y_penalty           = constraints.get("y_penalty",          10),
            solver_time_limit   = constraints.get("solver_time_limit",  20.0),
            solver_num_workers  = constraints.get("solver_num_workers",  8),
        )

        project_data = layout_optimizer.apply_layout_template(
            tpl_data,
            project_data,
            fallback_templates=other_templates,
        )

        return {
            "template_data": tpl_data,
            "project_data":  project_data,
        }
