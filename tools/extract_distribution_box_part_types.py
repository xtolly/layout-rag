import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "templates" / "distribution_box"
DEFAULT_OUTPUT = PROJECT_ROOT / "tools" / "distribution_box_part_types.txt"


def extract_part_types(source_dir: Path) -> list[str]:
    part_types: set[str] = set()

    for json_file in sorted(source_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(f"Skipping invalid file: {json_file}")
            continue

        scheme = data.get("scheme", {})
        for part in scheme.get("parts", []):
            part_type = str(part.get("part_type", "") or "").strip()
            if part_type:
                part_types.add(part_type)

    return sorted(part_types)


def main() -> None:
    output_path = DEFAULT_OUTPUT
    output_path.parent.mkdir(parents=True, exist_ok=True)

    part_types = extract_part_types(SOURCE_DIR)
    output_path.write_text("\n".join(part_types) + "\n", encoding="utf-8")

    print(f"Extracted {len(part_types)} unique part types to: {output_path}")


if __name__ == "__main__":
    main()