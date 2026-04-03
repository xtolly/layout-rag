"""
根据 configurator_options.json 中的 part_type_options，
为每种元件类型生成颜色差异最大化的 HSL 颜色，写入 static/part.color。

算法：
  - 色相：黄金角递增（137.508°），确保任意相邻两个颜色色相距离最大
  - 饱和度/亮度：循环使用若干组组合，增加同色相段内的感知差异
"""

import json
from pathlib import Path

# 黄金角（度）
GOLDEN_ANGLE = 137.508

# (饱和度%, 亮度%) 组合循环，增加同色调段内的感知差异
SL_VARIANTS = [
    (72, 38),  # 深饱和
    (60, 50),  # 中性
    (80, 32),  # 深鲜艳
    (55, 58),  # 浅柔和
    (85, 42),  # 高饱和
    (50, 62),  # 粉调
    (68, 44),  # 均衡
    (76, 36),  # 重色
    (62, 54),  # 亮中调
]

UNKNOWN_COLOR = "hsl(215, 16%, 55%)"


def generate_colors(part_types: list[str]) -> dict[str, str]:
    color_map: dict[str, str] = {}
    for i, pt in enumerate(part_types):
        hue = (i * GOLDEN_ANGLE) % 360
        sat, light = SL_VARIANTS[i % len(SL_VARIANTS)]
        color_map[pt] = f"hsl({hue:.3f}, {sat}%, {light}%)"
    return color_map


def main() -> None:
    root = Path(__file__).parent.parent
    options_path = root / "static" / "configurator_options.json"
    color_path   = root / "static" / "part.color"

    with open(options_path, encoding="utf-8") as f:
        options = json.load(f)

    part_types = options.get("part_type_options", [])
    if not part_types:
        print("未找到 part_type_options，请检查文件内容。")
        return

    color_map = generate_colors(part_types)
    output = {
        "unknownColor": UNKNOWN_COLOR,
        "partColorMap": color_map,
    }

    with open(color_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"已生成 {len(color_map)} 种颜色 → {color_path}")
    for name, color in color_map.items():
        print(f"  {name:30s}  {color}")


if __name__ == "__main__":
    main()
