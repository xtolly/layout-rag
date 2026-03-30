import json
from pathlib import Path


LAYOUTS_DIR = Path("data/layouts")


def update_layout_name(file_path: Path) -> bool:
    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    expected_name = file_path.stem
    if data.get("name") == expected_name:
        return False

    updated_data = dict(data)
    updated_data["name"] = expected_name

    with file_path.open("w", encoding="utf-8") as file:
        json.dump(updated_data, file, ensure_ascii=False, indent=4)
        file.write("\n")

    return True


def main() -> None:
    if not LAYOUTS_DIR.exists():
        raise FileNotFoundError(f"Layouts directory not found: {LAYOUTS_DIR}")

    updated_count = 0
    for file_path in sorted(LAYOUTS_DIR.glob("*.json")):
        if update_layout_name(file_path):
            updated_count += 1

    print(f"Updated {updated_count} layout files in {LAYOUTS_DIR}")


if __name__ == "__main__":
    main()