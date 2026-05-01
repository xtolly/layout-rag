"""
将中船国际数科城项目系统图_grouped.json 拆分为独立的模板 JSON 文件。

输出目录：templates/new_distribution_box/
每个箱柜输出一个 JSON 文件，数据结构对齐 distribution_box 的模板格式：
  {
      "name": "<项目名>_<box_id>",
      "uuid": "<box_id>",
      "schema": {
          "industry": "",
          "box_classify": "配电箱",       # 来自 BoxClassify 枚举
          "series": "XM1",               # 来自 Series
          "install_type": "户内挂墙",     # 来自 InstallType 枚举
          "inline_mode": "进线器件上置",  # 来自 InLineMode 枚举
          "fixup_type": "板式安装",       # 来自 FixUpType 枚举
          "door_type": "左开门",          # 来自 DoorType 枚举
          "panel_size": [500, 800],
          "parts": [
              {
                  "part_id": "<GUID>",
                  "part_type": "塑壳断路器",
                  "part_size": [104.7, 161.2]
              }, ...
          ]
      },
      "arrange": {
          "<part_id>": {"position": [x, y], "rotation": 0}, ...
      },
      "features": [
          {"name": "panel_width", "value": 500.0}, ...
      ]
  }
"""

import json
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from layout_rag.domain.new_distribution_box import NewDistributionBoxDomain
from layout_rag.core.feature_extractor import FeatureExtractor

# ── 枚举映射表（与 new_neo4j.py 保持一致）──
BOX_CLASSIFY_ENUM = {
    0: "配电箱", 1: "户箱", 2: "标准电表箱", 3: "非标电表箱"
}
INLINE_MODE_ENUM = {0: "进线器件上置", 1: "进线器件左置"}
FIXUP_TYPE_ENUM = {0: "板式安装", 1: "梁式安装"}
DOOR_TYPE_ENUM = {0: "左开门", 1: "右开门", 2: "双开门"}
INSTALL_TYPE_ENUM = {
    "户内暗装": "户内暗装", "户内挂墙": "户内挂墙", "户内落地": "户内落地",
    "户外挂墙": "户外挂墙", "户外落地": "户外落地",
    0: "户内暗装", 1: "户内挂墙", 2: "户内落地", 3: "户外挂墙", 4: "户外落地",
    -1: "未知"
}
CABLE_IN_OUT_TYPE_ENUM = {
    0: "上进下出", 1: "上进上出-左侧出线", 2: "上进上出-右侧出线",
    3: "下进下出-左侧进线", 4: "下进下出-右侧进线",
    5: "下进上出-左进右出", 6: "下进上出-右进左出"
}


INPUT_FILE = PROJECT_ROOT / "templates" / "中船国际数科城项目系统图_grouped.json"
OUTPUT_DIR = PROJECT_ROOT / "templates" / "new_distribution_box"
PROJECT_NAME = "中船国际数科城项目系统图"


def convert_box_to_panels(box: dict) -> list[dict]:
    """将一个 grouped-JSON box 转换为多个面板模板 JSON（每面板一个文件）。"""

    cabinet_id = str(uuid.uuid4())
    cabinet_width = float(box.get("BoxWidth", 0))
    cabinet_height = float(box.get("BoxHeight", 0))
    cabinet_depth = float(box.get("BoxDepth", 0))

    # 解析枚举业务属性
    box_classify = BOX_CLASSIFY_ENUM.get(box.get("BoxClassify"), str(box.get("BoxClassify", "")))
    series = box.get("Series", "")
    install_type = INSTALL_TYPE_ENUM.get(box.get("InstallType"), str(box.get("InstallType", "")))
    inline_mode = INLINE_MODE_ENUM.get(box.get("InLineMode"), str(box.get("InLineMode", "")))
    fixup_type = FIXUP_TYPE_ENUM.get(box.get("FixUpType"), str(box.get("FixUpType", "")))
    door_type = DOOR_TYPE_ENUM.get(box.get("DoorType"), str(box.get("DoorType", "")))
    cable_in_out_type = CABLE_IN_OUT_TYPE_ENUM.get(box.get("CableInOutType"), str(box.get("CableInOutType", "")))

    panel_templates = []
    
    for panel in box.get("Panels", []):
        panel_name = panel.get("PanelName", "未知面板")
        panel_id = str(uuid.uuid4())
        
        panel_parts = []
        panel_arrange = {}
        raw_parts = panel.get("Parts", [])
        
        for rp in raw_parts:
            # UUID 重新分配
            part_id = str(uuid.uuid4())
            standard_name = rp.get("StandardName", "未知")
            w = float(rp.get("Width", 0))
            h = float(rp.get("Height", 0))

            part_item = {
                "part_id": part_id,
                "part_type": standard_name,
                "part_size": [w, h],
                "part_model": rp.get("Type", "未知"),
                "pole": rp.get("Pole", ""),
                "current": rp.get("Current", ""),
                "in_line": rp.get("InLine", False),
                "part_type_code": rp.get("PartType", 0),
                "is_guide_part": rp.get("IsGuidePart", False),
            }
            panel_parts.append(part_item)

            # 构建 panel 内部的 arrange 布局信息 (从中心点转换为左上角)
            insert_point = rp.get("InsertPoint", {})
            cx = abs(float(insert_point.get("X", 0)))
            cy = abs(float(insert_point.get("Y", 0)))
            panel_arrange[part_id] = {
                "position": [round(cx - w / 2, 2), round(cy - h / 2, 2)],
                "rotation": int(rp.get("Angle", 0)),
            }
        
        # if not panel_parts:
        #     continue

        schema = {
            "cabinet_id": cabinet_id,
            "industry": "",
            "box_classify": box_classify,
            "series": series,
            "cabinet_width": cabinet_width,
            "cabinet_height": cabinet_height,
            "cabinet_depth": cabinet_depth,
            "install_type": install_type,
            "inline_mode": inline_mode,
            "fixup_type": fixup_type,
            "door_type": door_type,
            "cable_in_out_type": cable_in_out_type,
            "panel_id": panel_id,
            "panel_type": panel_name,
            "panel_size": [cabinet_width, cabinet_height],
            "parts": panel_parts
        }

        file_uuid = str(uuid.uuid4())
        name = f"{PROJECT_NAME}_{cabinet_id[:8].lower()}_{panel_id[:8].lower()}"

        panel_templates.append({
            "name": name,
            "uuid": file_uuid,
            "schema": schema,
            "arrange": panel_arrange
        })

    return panel_templates

def main():
    data = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    
    # 每次运行先清空输出目录
    if OUTPUT_DIR.exists():
        import shutil
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 第一遍：转换所有箱柜，收集所有模板
    templates: list[dict] = []
    all_part_types: set[str] = set()

    for box in data:
        panel_templates = convert_box_to_panels(box)
        templates.extend(panel_templates)
        for temp in panel_templates:
            for part in temp["schema"]["parts"]:
                all_part_types.add(part["part_type"])

    sorted_part_types = sorted(all_part_types)
    print(f"共生成 {len(templates)} 个面板模板文件，包含 {len(sorted_part_types)} 种元件类型")
    print(f"元件类型: {sorted_part_types}")

    # 第二遍：提取特征并保存
    for template in templates:
        filename = f"{template['name']}.json"
        output_path = OUTPUT_DIR / filename

        output_path.write_text(
            json.dumps(template, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )

    print(f"\n[OK] Generated {len(templates)} template files to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
