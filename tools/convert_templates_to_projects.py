import json
import os
from pathlib import Path
from collections import defaultdict

# 配置路径
SOURCE_DIR = Path("templates/new_distribution_box")
TARGET_DIR = Path("projects/new_distribution_box")

def convert():
    if not SOURCE_DIR.exists():
        print(f"源目录 {SOURCE_DIR} 不存在")
        return

    if not TARGET_DIR.exists():
        TARGET_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 扫描并按 cabinet_id 分组
    cabinet_groups = defaultdict(list)
    
    for json_file in SOURCE_DIR.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            schema = data.get("schema", {})
            cabinet_id = schema.get("cabinet_id")
            if not cabinet_id:
                continue
                
            cabinet_groups[cabinet_id].append(data)
        except Exception as e:
            print(f"解析文件 {json_file} 失败: {e}")

    print(f"共发现 {len(cabinet_groups)} 个柜体")

    # 2. 转换为目标格式并保存
    for cabinet_id, panels_data in cabinet_groups.items():
        # 取第一个面板的 schema 作为柜体基础信息
        base_schema = panels_data[0]["schema"]
        
        # 构造 cabinets 结构
        project_cabinets = []
        
        cabinet_obj = {
            "order": 1,
            "cabinet_id": cabinet_id,
            "cabinet_name": panels_data[0].get("name", cabinet_id),
            "box_classify": base_schema.get("box_classify", "配电柜"),
            "series": base_schema.get("series", ""),
            "cabinet_width": base_schema.get("cabinet_width", 0),
            "cabinet_height": base_schema.get("cabinet_height", 0),
            "cabinet_depth": base_schema.get("cabinet_depth", 0),
            "install_type": base_schema.get("install_type", ""),
            "inline_mode": base_schema.get("inline_mode", ""),
            "fixup_type": base_schema.get("fixup_type", ""),
            "door_type": base_schema.get("door_type", ""),
            "cable_in_out_type": base_schema.get("cable_in_out_type", ""),
            "panels": []
        }
        
        # 填充 panels
        for idx, p_data in enumerate(panels_data):
            p_schema = p_data["schema"]
            panel_obj = {
                "order": idx + 1,
                "panel_id": p_schema.get("panel_id", ""),
                "panel_type": p_schema.get("panel_type", "默认面板"),
                "operation_method": p_schema.get("operation_method", ""),
                "panel_width": p_schema.get("panel_size", [0, 0])[0],
                "panel_height": p_schema.get("panel_size", [0, 0])[1],
                "parts": [],
                "arrange": p_data.get("arrange", {})
            }
            
            # 填充 parts
            for p_idx, part in enumerate(p_schema.get("parts", [])):
                panel_obj["parts"].append({
                    "order": p_idx + 1,
                    "part_type": part.get("part_type", ""),
                    "part_model": part.get("part_model", ""),
                    "part_width": part.get("part_width", part.get("part_size", [0, 0])[0]),
                    "part_height": part.get("part_height", part.get("part_size", [0, 0])[1]),
                    "part_depth": part.get("part_depth", 0),
                    "pole": part.get("pole", ""),
                    "current": part.get("current", ""),
                    "in_line": part.get("in_line", False),
                    "part_id": part.get("part_id", "")
                })
            
            cabinet_obj["panels"].append(panel_obj)
            
        project_cabinets.append(cabinet_obj)
        
        # 最终项目 JSON
        project_json = {
            "cabinets": project_cabinets
        }
        
        # 保存文件 (使用 cabinet_name 或 cabinet_id 作为文件名)
        safe_name = cabinet_obj["cabinet_name"].replace("/", "_").replace("\\", "_")
        target_path = TARGET_DIR / f"{safe_name}.json"
        
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(project_json, f, ensure_ascii=False, indent=2)
            
    print(f"转换完成，项目文件已保存至 {TARGET_DIR}")

if __name__ == "__main__":
    convert()
