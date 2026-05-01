"""Output analysis to file for proper Unicode."""
import json
from pathlib import Path

fp = Path(__file__).resolve().parents[1] / "templates" / "中船国际数科城项目系统图_grouped.json"
data = json.loads(fp.read_text(encoding="utf-8"))

out = Path(__file__).resolve().parent / "inspect_result.txt"

all_standard_names = set()
all_panel_names = set()
all_install_types = set()

for box in data:
    all_install_types.add(str(box.get("InstallType")))
    for panel in box.get("Panels", []):
        all_panel_names.add(panel.get("PanelName", ""))
        for part in panel.get("Parts", []):
            all_standard_names.add(part.get("StandardName", ""))

lines = []
lines.append(f"Total boxes: {len(data)}")
lines.append(f"\nPanelName values: {sorted(all_panel_names)}")
lines.append(f"\nInstallType values: {sorted(all_install_types)}")
lines.append(f"\nUnique StandardNames ({len(all_standard_names)}):")
for n in sorted(all_standard_names):
    lines.append(f"  - [{n}]")

# Also check which panel has parts (安装板 vs 门板)
panel_with_parts = set()
for box in data:
    for panel in box.get("Panels", []):
        if panel.get("Parts", []):
            panel_with_parts.add(panel.get("PanelName", ""))
lines.append(f"\nPanels that have parts: {sorted(panel_with_parts)}")

# Show box-level field values across all boxes
all_series = sorted(set(str(box.get("Series")) for box in data))
all_box_classify = sorted(set(str(box.get("BoxClassify")) for box in data))
all_door_types = sorted(set(str(box.get("DoorType")) for box in data))
all_fixup_types = sorted(set(str(box.get("FixUpType")) for box in data))
all_inline_modes = sorted(set(str(box.get("InLineMode")) for box in data))
lines.append(f"\nSeries values: {all_series}")
lines.append(f"BoxClassify values: {all_box_classify}")
lines.append(f"DoorType values: {all_door_types}")
lines.append(f"FixUpType values: {all_fixup_types}")
lines.append(f"InLineMode values: {all_inline_modes}")

# Check if InsertPoint is present and meaningful
has_insert = 0
no_insert = 0
for box in data:
    for panel in box.get("Panels", []):
        for part in panel.get("Parts", []):
            if part.get("InsertPoint"):
                has_insert += 1
            else:
                no_insert += 1
lines.append(f"\nParts with InsertPoint: {has_insert}, without: {no_insert}")

out.write_text("\n".join(lines), encoding="utf-8")
print(f"Written to {out}")
