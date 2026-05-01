import json
import os

input_file = r'e:\Documents\Code\layout-rag\templates\中船国际数科城项目系统图_result.json'
output_file = r'e:\Documents\Code\layout-rag\templates\中船国际数科城项目系统图_grouped.json'

def group_parts():
    if not os.path.exists(input_file):
        print(f"错误: 找不到文件 {input_file}")
        return

    # 使用 utf-8-sig 处理可能存在的 BOM
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"解析 JSON 出错: {e}")
            return

    # 加载原始文件以获取缺失的 CableInOutType (因为 _result.json 丢失了该字段)
    base_file = r'e:\Documents\Code\layout-rag\templates\中船国际数科城项目系统图.json'
    cable_lookup = {}
    if os.path.exists(base_file):
        with open(base_file, 'r', encoding='utf-8') as f:
            base_data = json.load(f)
            # 原始文件根节点是字典，包含 'Boxes' 列表
            boxes = base_data.get("Boxes", [])
            for b in boxes:
                if isinstance(b, dict) and b.get("ID"):
                    cable_lookup[b["ID"]] = b.get("CableInOutType")

    result = []

    # 遍历每个 Box
    for box in data:
        if not isinstance(box, dict):
            continue
            
        box_copy = box.copy()
        
        # 补充 CableInOutType
        box_id = box.get("ID")
        if box_id in cable_lookup:
            box_copy["CableInOutType"] = cable_lookup[box_id]
        
        # 收集面板的固有属性
        panel_props = {}
        for panel_key in ['MountPanel', 'DoorPanel', 'ProtectiveDoorPanel']:
            p_data = box.get(panel_key)
            if p_data and isinstance(p_data, dict):
                p_name = p_data.get('Name')
                if p_name:
                    panel_props[p_name] = p_data
        
        def flatten_parts(parts):
            flat_list = []
            for p in parts:
                p_copy = p.copy()
                connect_parts = p_copy.pop("ConnectPart", [])
                flat_list.append(p_copy)
                if connect_parts and isinstance(connect_parts, list):
                    flat_list.extend(flatten_parts(connect_parts))
            return flat_list

        panel_parts = {}
        part_list = box.get("PartList")
        
        # 如果 PartList 存在且为列表
        if isinstance(part_list, list):
            flat_part_list = flatten_parts(part_list)
            for part in flat_part_list:
                panel_name = part.get("PanelName", "未指定面板")
                if panel_name not in panel_parts:
                    panel_parts[panel_name] = []
                panel_parts[panel_name].append(part)
                
        panels = []
        all_panel_names = set(panel_parts.keys()).union(set(panel_props.keys()))
        
        for p_name in all_panel_names:
            p_dict = panel_props.get(p_name, {}).copy()
            p_dict["PanelName"] = p_name
            p_dict["Parts"] = panel_parts.get(p_name, [])
            
            # 移除面板内部可能导致冗余或旧结构的字段
            p_dict.pop("Name", None)
            p_dict.pop("InLinePartBranchDic", None)
            p_dict.pop("OutLinePartBranchDic", None)
            p_dict.pop("InLineConnectPartRow", None)
            p_dict.pop("SecondarySchemaList", None)
            p_dict.pop("PartList", None)
            
            panels.append(p_dict)
            
        box_copy["Panels"] = panels
        
        # 移除已转换的旧字段及用户不需要的列表
        box_copy.pop("PartList", None)
        box_copy.pop("OtherPartList", None)
        box_copy.pop("MountPanel", None)
        box_copy.pop("DoorPanel", None)
        box_copy.pop("ProtectiveDoorPanel", None)
        box_copy.pop("InLinePartList", None)
        box_copy.pop("OutLinePartList", None)
        box_copy.pop("SecondaryCircuitList", None)
        box_copy.pop("GuideList", None)
            
        result.append(box_copy)

    # 保存新文件
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

    print(f"处理完成！已按照 Box -> Panel -> Part 结构分组并另存为:\n{output_file}")

if __name__ == "__main__":
    group_parts()
