import json
from pathlib import Path
from collections import OrderedDict

def migrate_file(file_path: Path):
    with file_path.open('r', encoding='utf-8') as f:
        try:
            # Use object_pairs_hook=OrderedDict to preserve key order
            data = json.load(f, object_pairs_hook=OrderedDict)
        except json.JSONDecodeError:
            print(f"Skipping {file_path}: invalid JSON")
            return

    modified = False
    new_data = OrderedDict()
    
    for key, value in data.items():
        if key in ("meta", "schema"):
            new_data["scheme"] = value
            modified = True
            print(f"  {file_path.name}: renamed {key} -> scheme")
        else:
            new_data[key] = value

    if modified:
        with file_path.open('w', encoding='utf-8') as f:
            json.dump(new_data, f, ensure_ascii=False, indent=4)

def main():
    templates_root = Path("templates")
    if not templates_root.exists():
        print("Error: templates directory not found")
        return

    print(f"Starting migration in {templates_root}...")
    for json_file in templates_root.rglob("*.json"):
        migrate_file(json_file)
    print("Migration complete.")

if __name__ == "__main__":
    main()
