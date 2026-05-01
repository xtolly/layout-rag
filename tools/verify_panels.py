import json
from pathlib import Path

# Pick the first json file in the directory
output_dir = Path(r"e:\Documents\Code\layout-rag\templates\new_distribution_box")
json_file = next(output_dir.glob("*.json"))

print(f"Checking file: {json_file.name}")
data = json.loads(json_file.read_text(encoding="utf-8"))

schema = data.get("schema", {})
panels = schema.get("panels", [])

for i, p in enumerate(panels):
    print(f"\n--- Panel {i} ---")
    print(f"ID: {p.get('panel_id')}")
    print(f"Type: {p.get('panel_type')}")
    print(f"Size: {p.get('panel_size')}")
    parts_count = len(p.get('parts', []))
    print(f"Parts count: {parts_count}")
    if parts_count > 0:
        print(f"First part: {p['parts'][0].get('type')}")
