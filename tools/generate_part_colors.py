import sys
import os
from pathlib import Path
import json
import colorsys

# 将 src 目录添加到 Python 路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from layout_rag.domain import NewDistributionBoxDomain
from layout_rag.config import PART_COLOR_PATH, STATIC_DIR

def generate_colors(count):
    """
    通过在 HSL 空间均匀分布色相来生成色差较大的颜色。
    """
    colors = []
    if count <= 0:
        return []
        
    for i in range(count):
        # 均匀分布色相 (Hue)
        h = i / count
        # 颜色不要太鲜艳（降低饱和度），整体暗一些（降低亮度）
        s = 0.45
        l = 0.35
        
        # HSL 转 RGB (0-1)
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        
        # 转为 HEX 格式
        hex_color = "#{:02x}{:02x}{:02x}".format(
            int(r * 255),
            int(g * 255),
            int(b * 255)
        )
        colors.append(hex_color)
    return colors

def main():
    # 1. 实例化业务领域
    domain = NewDistributionBoxDomain()
    
    # 2. 从 Domain 获取元件类型列表
    print("正在从 Domain 模型获取元件类型列表...")
    part_types = domain.get_part_types()
    
    print(f"找到 {len(part_types)} 种元件类型。")
    
    # 3. 生成颜色
    colors = generate_colors(len(part_types))
    
    # 4. 构建映射
    part_color_map = {}
    for pt, color in zip(part_types, colors):
        part_color_map[pt] = color
        print(f"  - {pt}: {color}")
        
    # 5. 构建最终 payload
    payload = {
        "unknownColor": domain.unknown_part_color,
        "partColorMap": part_color_map
    }
    
    # 6. 确保目录存在并写入文件
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    with open(PART_COLOR_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        
    print(f"\n成功生成颜色映射文件: {PART_COLOR_PATH}")

if __name__ == "__main__":
    main()
