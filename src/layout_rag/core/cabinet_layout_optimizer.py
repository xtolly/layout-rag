"""
柜体级别布局优化器

将柜体视为画布，将各面板视为可放置元件进行初始排版。

排版规则
--------
硬约束：
  - 元件不能超出画布（柜体）边界
  - 元件之间不能重叠

软约束（优先级 1 > 2）：
  1. 占位面板（part_type 含 "占位"）：
       - 宽 > 高 → 从上往下排列（竖向堆叠，主列）
       - 高 >= 宽 → 从右向左排列（横向并排，占右侧区域）
  2. 其他面板 → 从上往下排列（竖向堆叠，主列）

放置策略：
  - 右侧区域：所有"高 >= 宽"占位面板，从右往左横向排列，顶部对齐
  - 主列区域（剩余宽度）：占位面板（宽 > 高）优先，其他面板其次，
    均从上往下堆叠，水平居中于主列
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


ZHANWEI_KEYWORD = "占位"


def _overlaps(ax: float, ay: float, aw: float, ah: float,
              bx: float, by: float, bw: float, bh: float) -> bool:
    """判断两个矩形是否重叠（边重合不算）。"""
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def compute_cabinet_arrange(
    cabinet_width: float,
    cabinet_height: float,
    parts: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    计算柜体内各面板的初始布局坐标。

    Args:
        cabinet_width:  柜体宽度（mm）
        cabinet_height: 柜体高度（mm）
        parts: 面板列表，每项需包含 ``part_id``、``part_size: [w, h]``、
               ``part_type``（可选）字段。

    Returns:
        arrange: ``{part_id: {"position": [x, y], "rotation": 0}, ...}``
    """
    # ── 1. 分类 ──────────────────────────────────────────────
    zhanwei_wide: List[Dict] = []   # 占位面板，宽 > 高 → 主列从上往下（优先级 1）
    zhanwei_tall: List[Dict] = []   # 占位面板，高 >= 宽 → 右侧从右往左（优先级 1）
    others:       List[Dict] = []   # 其他面板 → 主列从上往下（优先级 2）

    for p in parts:
        w, h = p["part_size"]
        if ZHANWEI_KEYWORD in p.get("part_type", ""):
            if w > h:
                zhanwei_wide.append(p)
            else:
                zhanwei_tall.append(p)
        else:
            others.append(p)

    # ── 2. 计算右侧区域宽度 ───────────────────────────────────
    right_zone_width = sum(p["part_size"][0] for p in zhanwei_tall)
    main_zone_width  = max(0.0, cabinet_width - right_zone_width)

    arrange: Dict[str, Dict[str, Any]] = {}

    # ── 3. 右侧区域：占位面板（高 >= 宽），从右往左横向排列 ──
    x = cabinet_width
    for p in zhanwei_tall:
        w, h = p["part_size"]
        x -= w
        # 纵向居中于柜体
        y = max(0.0, (cabinet_height - h) / 2)
        arrange[p["part_id"]] = {"position": [round(x, 2), round(y, 2)], "rotation": 0}

    # ── 4. 主列：占位面板（宽 > 高）优先，然后其他面板，从上往下 ─
    y = 0.0
    for p in zhanwei_wide + others:
        w, h = p["part_size"]
        # 水平居中于主列区域
        x_pos = max(0.0, (main_zone_width - w) / 2)
        arrange[p["part_id"]] = {"position": [round(x_pos, 2), round(y, 2)], "rotation": 0}
        y += h

    return arrange


def validate_arrange(
    cabinet_width: float,
    cabinet_height: float,
    parts: List[Dict[str, Any]],
    arrange: Dict[str, Dict[str, Any]],
) -> List[str]:
    """
    检查 arrange 是否违反硬约束，返回违规描述列表（空列表表示合法）。

    Args:
        cabinet_width:  柜体宽度
        cabinet_height: 柜体高度
        parts:          面板列表（同 ``compute_cabinet_arrange``）
        arrange:        待检查的布局字典

    Returns:
        violations: 违规描述列表
    """
    violations: List[str] = []
    placed: List[Tuple[str, float, float, float, float]] = []

    for p in parts:
        pid = p["part_id"]
        if pid not in arrange:
            continue
        w, h = p["part_size"]
        x, y = arrange[pid]["position"]

        # 边界检查
        if x < 0 or y < 0 or x + w > cabinet_width or y + h > cabinet_height:
            violations.append(
                f"部件 {pid} ({p.get('part_type','?')}) 超出柜体边界："
                f" pos=({x}, {y}), size=({w}x{h}), cabinet=({cabinet_width}x{cabinet_height})"
            )

        # 重叠检查
        for (qid, qx, qy, qw, qh) in placed:
            if _overlaps(x, y, w, h, qx, qy, qw, qh):
                violations.append(f"部件 {pid} 与 {qid} 重叠")

        placed.append((pid, x, y, w, h))

    return violations
