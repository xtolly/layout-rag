import os
import json
import math
from typing import List, Dict, Optional

from core.feature_extractor import FeatureExtractor
from core.vector_store import VectorStore
from config import get_feature_schema, load_part_types
from core.layout_optimizer import LayoutOptimizer

class LayoutService:
    def __init__(self, data_dir: str, vector_db_path: str):
        self.schema_def = get_feature_schema(data_dir)
        self.part_types = load_part_types(data_dir)
        
        self.store = VectorStore(self.schema_def)
        self.store.load_from_disk(vector_db_path)
        self.extractor = FeatureExtractor(self.part_types, self.schema_def)

    @staticmethod
    def _to_python_value(value):
        if hasattr(value, "item"):
            return value.item()
        return value

    @staticmethod
    def _resolve_feature_status(q_value, t_value, feature_type: str) -> str:
        if feature_type in {"continuous", "count"}:
            diff_abs = abs(q_value - t_value)
            base_val = max(abs(q_value), abs(t_value), 0.001)
            diff_ratio = diff_abs / base_val

            if diff_abs < 1e-6:
                return "green"
            if diff_ratio <= 0.15:
                return "yellow"
            if diff_ratio <= 0.45:
                return "orange"
            return "red"

        return "green" if q_value == t_value else "red"

    def _load_template_data(self, template_uuid: str) -> Optional[dict]:
        tpl_entry = next((entry for entry in self.store.entries if entry.get("uuid") == template_uuid), None)
        if not tpl_entry:
            return None

        tpl_path = tpl_entry.get("source_path")
        if not tpl_path or not os.path.exists(tpl_path):
            return None

        with open(tpl_path, 'r', encoding='utf-8') as f:
            tpl_data = json.load(f)

        tpl_data.setdefault("uuid", template_uuid)
        return tpl_data

    def _load_other_templates(self, template_uuids: List[str], selected_uuid: str) -> List[dict]:
        templates = []
        seen = set()

        for template_uuid in template_uuids or []:
            if not template_uuid or template_uuid == selected_uuid or template_uuid in seen:
                continue

            seen.add(template_uuid)
            tpl_data = self._load_template_data(template_uuid)
            if tpl_data:
                templates.append(tpl_data)

        return templates

    def calculate_diff_info(self, query_parts: list, template_parts: list) -> dict:
        """计算零件组成差异"""
        q_counts = {}
        for p in query_parts:
            pt = p.get("part_type")
            q_counts[pt] = q_counts.get(pt, 0) + 1
            
        t_counts = {}
        for p in template_parts:
            pt = p.get("part_type")
            t_counts[pt] = t_counts.get(pt, 0) + 1
            
        all_types = set(list(q_counts.keys()) + list(t_counts.keys()))
        matched, extra, missing = 0, 0, 0
        for pt in all_types:
            qc, tc = q_counts.get(pt, 0), t_counts.get(pt, 0)
            matched += min(qc, tc)
            if qc > tc:
                extra += (qc - tc)
            if tc > qc:
                missing += (tc - qc)
        return {"matched": matched, "extra": extra, "missing": missing}

    def get_feature_diff_list(self, q_features, t_features) -> List[Dict]:
        """生成详细特征差异比对（带 4 级状态灯）"""
        diff_list = []
        
        for f_name, f_info in self.schema_def.items():
            qv = self._to_python_value(q_features.get(f_name, 0))
            tv = self._to_python_value(t_features.get(f_name, 0))
                
            display_name = f_info.get("display_name", f_name)
            f_type = f_info.get("type", "continuous")
            status = self._resolve_feature_status(qv, tv, f_type)
                
            diff_list.append({
                "name": f_name,
                "type": f_type,
                "dynamic": f_info.get("dynamic", False),
                "source": f_info.get("source"),
                "field": f_info.get("field"),
                "sourceName": f_info.get("source_name"),
                "featureValue": f_info.get("value"),
                "displayName": display_name,
                "uploadedValue": qv,
                "templateValue": tv,
                "status": status
            })

        diff_list.sort(key=lambda item: (not item["dynamic"], item["name"]))
        return diff_list

    def search_recommendations(self, project_data: dict, top_k: int = 10) -> list:
        """执行推荐搜索全流程"""
        current_uuid = project_data.get("uuid")
        query_features = self.extractor.extract(project_data)
        
        top_k_results = self.store.search(query_features, top_k=top_k)
        
        templates = []
        for entry, distance in top_k_results:
            if current_uuid and entry.get("uuid") == current_uuid:
                continue
                
            source_path = entry.get("source_path")
            if not source_path or not os.path.exists(source_path):
                continue
                
            with open(source_path, 'r', encoding='utf-8') as f:
                tpl_data = json.load(f)
        
            tpl_meta = tpl_data.get("meta", {})
            tpl_arrange = tpl_data.get("arrange", {})
            tpl_features = self.extractor.extract(tpl_data)
                
            # 计算差异和评分
            diff_info = self.calculate_diff_info(project_data["meta"]["parts"], tpl_meta.get("parts", []))
            feature_diffs = self.get_feature_diff_list(query_features, t_features=tpl_features)
            
            # 评分模型
            safe_distance = max(0.0, distance) + diff_info["extra"] * 0.1
            score = min(100, round(100 * math.exp(-safe_distance / 4.0)))
            
            
            templates.append({
                "uuid": entry["uuid"],
                "name": tpl_data.get("name"),
                "score": score,
                "showFeatures": False,
                "meta": tpl_meta,
                "diffInfo": diff_info,
                "featureDiffs": feature_diffs,
                "arrange": tpl_arrange
            })
            
        # 按照评分排序
        templates.sort(key=lambda x: x["score"], reverse=True)
            
        return templates

    def apply_layout_template(self, template_uuid: str, project_data: dict, other_template_uuids: List[str] | None = None) -> dict:
        """
        应用推荐方案的排版逻辑：寻找模板中类型一致且尺寸最接近的元件进行坐标迁移
        """
        tpl_data = self._load_template_data(template_uuid)
        if not tpl_data:
            return {"project_data": project_data, "template_data": None}

        other_templates = self._load_other_templates(other_template_uuids or [], template_uuid)
            
        layout_optimizer = LayoutOptimizer()
        project_data = layout_optimizer.apply_layout_template(
            tpl_data,
            project_data,
            fallback_templates=other_templates,
        )

        # 导出调试数据：只保留 meta 与 arrange 
        # def dump_debug_file(data, filename):
        #     debug_json = {
        #         "meta": data.get("meta", {}),
        #         "arrange": data.get("arrange", {})
        #     }
        #     with open(filename, 'w', encoding='utf-8') as f:
        #         json.dump(debug_json, f, indent=4, ensure_ascii=False)
        
        # try:
        #     dump_debug_file(tpl_data, 'debug_tpl.json')
        #     dump_debug_file(project_data, 'debug_project.json')
        # except Exception as e:
        #     print(f"警告: 导出调试文件失败: {e}")

        # 5. 兜底填充 features 
        if not project_data.get("features"):
            project_data["features"] = self.extractor.extract(project_data)
            
        return {
            "template_data" : tpl_data,
            "project_data" : project_data
        }
