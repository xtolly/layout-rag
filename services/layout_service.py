import os
import json
import math
import numpy as np
from typing import List, Dict, Any, Tuple

from core.feature_extractor import FeatureExtractor
from core.vector_store import VectorStore
from config import get_feature_schema, load_part_types
from core.layout_optimizer import LayoutOptimizer

class LayoutService:
    def __init__(self, txt_path: str, vector_db_path: str):
        self.schema_def = get_feature_schema(txt_path)
        self.part_types = load_part_types(txt_path)
        
        self.store = VectorStore(self.schema_def)
        self.store.load_from_disk(vector_db_path)
        self.extractor = FeatureExtractor(self.part_types)

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
            if qc > tc: extra += (qc - tc)
            if tc > qc: missing += (tc - qc)
        return {"matched": matched, "extra": extra, "missing": missing}

    def get_feature_diff_list(self, q_features, t_features) -> List[Dict]:
        """生成详细特征差异比对（带 4 级状态灯）"""
        diff_list = []
        
        for f_name, f_info in self.schema_def.items():
            qv = q_features.get(f_name, 0)
            tv = t_features.get(f_name, 0)
            
            # 转为 Python 原生类型
            if hasattr(qv, "item"): qv = qv.item()
            if hasattr(tv, "item"): tv = tv.item()
            
            if f_name.startswith("count_") and qv == 0 and tv == 0:
                continue
                
            display_name = f_info.get("display_name", f_name)
            f_type = f_info.get("type", "continuous")
            
            # 计算差异等级
            status = "green"
            if f_type == "continuous" or f_type == "count":
                diff_abs = abs(qv - tv)
                base_val = max(abs(qv), abs(tv), 0.001)
                diff_ratio = diff_abs / base_val
                
                if diff_abs < 1e-6: status = "green"
                elif diff_ratio <= 0.15: status = "yellow"
                elif diff_ratio <= 0.45: status = "orange"
                else: status = "red"
            else:
                status = "green" if qv == tv else "red"
                
            diff_list.append({
                "name": f_name,
                "displayName": display_name,
                "uploadedValue": qv,
                "templateValue": tv,
                "status": status
            })
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

    def apply_layout_template(self, template_uuid: str, project_data: dict) -> dict:
        """
        应用推荐方案的排版逻辑：寻找模板中类型一致且尺寸最接近的元件进行坐标迁移
        """
        # 1. 查找模板原始文件
        tpl_entry = next((e for e in self.store.entries if e["uuid"] == template_uuid), None)
        if not tpl_entry:
            return {"project_data": project_data, "template_data": None}
        
        tpl_path = tpl_entry.get("source_path")
        if not tpl_path or not os.path.exists(tpl_path):
            return {"project_data": project_data, "template_data": None}
            
        with open(tpl_path, 'r', encoding='utf-8') as f:
            tpl_data = json.load(f)
            
        layout_optimizer = LayoutOptimizer()
        project_data = layout_optimizer.apply_layout_template(tpl_data, project_data)

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
