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
        self.store.load_ruler(str(vector_store_path))
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

        # 1. 扩大召回（宽进）：向 Neo4j 发起向量检索，获取更多的候选集
        # 建议把 top_k 乘以一个倍数，比如 3 倍或 5 倍，确保不会漏掉好数据
        recall_k = top_k * 5 
        search_results = neo4j_client.search_similar_panel(query_vector, recall_k)
        
        if not search_results:
            return []
            
        panel_ids = [r["panel_id"] for r in search_results]

        # 2. 第二步：批量从数据库获取这些面板的完整拓扑数据
        details_from_db = neo4j_client.get_layouts_by_ids(panel_ids)

        # 获取用于 Gower 计算的极差字典
        feature_ranges = self.store.get_feature_ranges()

        templates = []
        for tpl_data in details_from_db:
            tpl_meta = tpl_data.get("schema", {})
            panel_id = tpl_meta.get("panel_id")
            
            # 提取模板特征
            tpl_features = self.extractor.extract(tpl_data)

            # ====== 核心修复：调用领域基类的 Gower 算法进行精排算分 ======
            # self.domain 是 NewDistributionBoxDomain 的实例
            exact_similarity = self.domain.calculate_gower_similarity(
                query_features=query_features, 
                template_features=tpl_features, 
                feature_ranges=feature_ranges
            )
            # 转换为百分比整数
            final_score = round(exact_similarity * 100)
            # ====================================================

            # 计算前端展示用的差异列表
            query_parts = project_data.get("schema", {}).get("parts", [])
            template_parts = tpl_meta.get("parts", [])
            diff_info = self.calculate_diff_info(query_parts, template_parts)
            feature_diffs = self.get_feature_diff_list(query_features, t_features=tpl_features)

            templates.append({
                "uuid":         tpl_data["uuid"],
                "name":         tpl_data.get("name"),
                "score":        final_score,  # 使用新的高精度得分
                "showFeatures": False,
                "schema":       tpl_meta,
                "diffInfo":     diff_info,
                "featureDiffs": feature_diffs,
                "arrange":      tpl_data.get("arrange", {}),
            })

        # 3. 精排截断（严出）：按 Gower 算出的高精度综合评分降序排列
        templates.sort(key=lambda x: x["score"], reverse=True)
        
        # 只返回前端请求的数量 (Top K)
        return templates[:top_k]

    # ------------------------------------------------------------------
    # BOM 智能推荐（多路召回 + 精排）
    # ------------------------------------------------------------------

    def recommend_bom(self, project_data: dict, top_n: int = 20) -> list:
        """
        多路召回 + 精排的 BOM 推荐引擎（互补模式）。
        只推荐当前面板缺少的元件，目标是补全一份完整 BOM。
        """
        # ── 阶段 1：状态感知 ──
        query_features = self.extractor.extract(project_data)
        env_vector = self.store.encode_for_neo4j(query_features, mode="not_from_bom")
        bom_vector = self.store.encode_for_neo4j(query_features, mode="from_bom")

        current_parts = project_data.get("schema", {}).get("parts", [])
        current_models = {p.get("part_model", "") for p in current_parts if p.get("part_model")}
        current_types = {p.get("part_type", "") for p in current_parts if p.get("part_type")}
        has_inline = any(p.get("in_line") for p in current_parts)
        has_outline = any(not p.get("in_line") for p in current_parts)

        is_cold = len(current_models) == 0

        if is_cold:
            w_env, w_bom, w_graph = 1.0, 0.0, 0.0
        else:
            w_env, w_bom, w_graph = 0.3, 0.4, 0.3

        # ── 阶段 2：多路召回 ──
        env_results = neo4j_client.search_similar_panel_non_bom(env_vector, top_n)
        env_score_map = {r["panel_id"]: r["score"] for r in env_results}
        env_panel_ids = [r["panel_id"] for r in env_results]

        bom_score_map, bom_panel_ids = {}, []
        if not is_cold:
            bom_results = neo4j_client.search_similar_panel_bom(bom_vector, top_n)
            bom_score_map = {r["panel_id"]: r["score"] for r in bom_results}
            bom_panel_ids = [r["panel_id"] for r in bom_results]

        graph_neighbors = []
        if not is_cold:
            graph_neighbors = neo4j_client.get_co_occurring_parts(list(current_models))

        # ── 阶段 3：聚合 ──
        all_panel_ids = list(set(env_panel_ids + bom_panel_ids))
        panels_data = neo4j_client.get_layouts_by_ids(all_panel_ids) if all_panel_ids else []
        panel_data_map = {p["uuid"]: p for p in panels_data}

        max_env_score = max(env_score_map.values()) if env_score_map else 1.0
        max_bom_score = max(bom_score_map.values()) if bom_score_map else 1.0

        candidates: Dict[tuple, dict] = {}

        def _ensure_candidate(part_type: str, model: str, part_detail: dict = None):
            key = (part_type, model)
            if key not in candidates:
                candidates[key] = {
                    "part_type": part_type,
                    "part_model": model,
                    "part_width": part_detail.get("part_size", [0, 0])[0] if part_detail else 0,
                    "part_height": part_detail.get("part_size", [0, 0])[1] if part_detail else 0,
                    "pole": part_detail.get("pole", "") if part_detail else "",
                    "current": part_detail.get("current", "") if part_detail else "",
                    "in_line": part_detail.get("in_line", False) if part_detail else False,
                    "sources": [],
                    "env_score": 0.0,
                    "bom_score": 0.0,
                    "graph_weight": 0,
                    "source_panels": [],
                    "appear_count": 0,
                }
            return candidates[key]

        def _process_panel_parts(pid, score_map, max_score, channel_name):
            panel = panel_data_map.get(pid)
            if not panel:
                return
            s = score_map.get(pid, 0.0) / max_score if max_score > 0 else 0.0
            for part in panel.get("schema", {}).get("parts", []):
                model = part.get("part_model", "")
                ptype = part.get("part_type", "")
                if not model or not ptype:
                    continue
                if model in current_models:
                    continue
                c = _ensure_candidate(ptype, model, part)
                if channel_name == "env":
                    c["env_score"] = max(c["env_score"], s)
                else:
                    c["bom_score"] = max(c["bom_score"], s)
                if channel_name not in c["sources"]:
                    c["sources"].append(channel_name)
                if pid not in c["source_panels"]:
                    c["source_panels"].append(pid)
                c["appear_count"] += 1

        for pid in env_panel_ids:
            _process_panel_parts(pid, env_score_map, max_env_score, "env")
        for pid in bom_panel_ids:
            _process_panel_parts(pid, bom_score_map, max_bom_score, "bom")

        max_graph_weight = 1
        if graph_neighbors:
            max_graph_weight = max(n["weight"] for n in graph_neighbors) if graph_neighbors else 1
            for neighbor in graph_neighbors:
                model = neighbor["part_model"]
                if not model or model in current_models:
                    continue
                full_name = neighbor.get("full_name", "")
                part_type = full_name.split("_")[0] if "_" in full_name else ""
                if not part_type:
                    continue
                c = _ensure_candidate(part_type, model)
                c["graph_weight"] = max(c["graph_weight"], neighbor["weight"])
                if "graph" not in c["sources"]:
                    c["sources"].append("graph")
                c["appear_count"] += 1

        # ── 阶段 4：互补过滤 + 精排 ──

        best_per_type: Dict[str, dict] = {}
        for _, c in candidates.items():
            ptype = c["part_type"]
            if ptype in current_types:
                continue

            active_weight = 0.0
            weighted_sum = 0.0
            if "env" in c["sources"]:
                active_weight += w_env
                weighted_sum += w_env * c["env_score"]
            if "bom" in c["sources"]:
                active_weight += w_bom
                weighted_sum += w_bom * c["bom_score"]
            if "graph" in c["sources"]:
                s_graph = math.log(1 + c["graph_weight"]) / math.log(1 + max_graph_weight) if max_graph_weight > 0 else 0
                active_weight += w_graph
                weighted_sum += w_graph * s_graph

            confidence = round(weighted_sum / active_weight * 100) if active_weight > 0 else 0
            confidence = min(confidence, 100)

            if c["in_line"] and not has_inline:
                confidence = min(confidence + 15, 100)
            elif not c["in_line"] and not has_outline:
                confidence = min(confidence + 15, 100)

            c["confidence"] = confidence

            if ptype not in best_per_type or confidence > best_per_type[ptype]["confidence"]:
                best_per_type[ptype] = c

        results = sorted(best_per_type.values(), key=lambda x: (-x["in_line"], -x["confidence"]))

        return [{
            "part_type":      c["part_type"],
            "part_model":     c["part_model"],
            "part_width":     c["part_width"],
            "part_height":    c["part_height"],
            "pole":           c["pole"],
            "current":        c["current"],
            "in_line":        c["in_line"],
            "confidence":     c["confidence"],
            "recommended_qty": 1,
            "sources":        c["sources"],
            "source_panels":  c["source_panels"][:5],
        } for c in results]

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
