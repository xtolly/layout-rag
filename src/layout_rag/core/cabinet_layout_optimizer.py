"""
柜体级别布局优化器

将柜体视为画布，将各面板视为可放置元件，使用 CP-SAT 约束求解器进行初始排版。

排版规则
--------
硬约束：
  - 元件不能超出画布（柜体）边界
  - 元件之间不能重叠

软约束（优先级 1 > 2）：
  1. 占位类型的面板（part_type 含 "占位"）：
       - 宽 > 高 → 从上往下排列（权重10000），从左往右排列（权重100）
       - 高 >= 宽 → 从右往左排（权重1000），从上往下排（权重100）
  2. 其他面板 → 从上往下排列（权重10），从左往右排列（权重1）
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ortools.sat.python import cp_model


ZHANWEI_KEYWORD = "占位"

# ---------------------------------------------------------------------------
# 软约束权重
# ---------------------------------------------------------------------------
WEIGHT_ZHANWEI_WIDE_Y = 10000   # 占位(宽>高) 从上往下
WEIGHT_ZHANWEI_WIDE_X = 100     # 占位(宽>高) 从左往右
WEIGHT_ZHANWEI_TALL_X = 10000   # 占位(高>=宽) 从右往左
WEIGHT_ZHANWEI_TALL_Y = 100     # 占位(高>=宽) 从上往下
WEIGHT_OTHER_Y        = 10      # 其他面板 从上往下
WEIGHT_OTHER_X        = 1       # 其他面板 从左往右

def compute_cabinet_arrange(
    cabinet_width: float,
    cabinet_height: float,
    parts: List[Dict[str, Any]],
    solver_time_limit: float = 10.0,
    solver_num_workers: int = 8,
) -> Dict[str, Dict[str, Any]]:
    """
    使用 CP-SAT 约束求解器计算柜体内各面板的布局坐标。

    模型设计：
      • 变量：每个面板的 (x, y) 左上角坐标（整数，单位 mm）
      • 硬约束：
        - 边界：0 ≤ x ≤ cabinet_width − w，y 同理
        - 不重叠：NoOverlap2D
      • 目标：最小化各面板按分类规则的加权位置代价

    Args:
        cabinet_width:  柜体宽度（mm）
        cabinet_height: 柜体高度（mm）
        parts: 面板列表，每项需包含 ``part_id``、``part_size: [w, h]``、
               ``part_type``（可选）字段。
        solver_time_limit: 求解超时（秒）
        solver_num_workers: 求解并行线程数

    Returns:
        arrange: ``{part_id: {"position": [x, y], "rotation": 0}, ...}``

    Raises:
        ValueError: 柜体尺寸不足以放下所有面板时抛出。
    """
    if not parts:
        return {}

    model = cp_model.CpModel()

    max_x = round(cabinet_width)
    max_y = round(cabinet_height)

    x_vars:      Dict[str, cp_model.IntVar] = {}
    y_vars:      Dict[str, cp_model.IntVar] = {}
    x_intervals: list = []
    y_intervals: list = []
    cost_terms:  list = []

    for p in parts:
        pid = p["part_id"]
        w = round(p["part_size"][0])
        h = round(p["part_size"][1])

        # ── 变量定义：左上角坐标 ──
        x_hi = max(0, max_x - w)
        y_hi = max(0, max_y - h)

        x = model.NewIntVar(0, x_hi, f"x_{pid}")
        y = model.NewIntVar(0, y_hi, f"y_{pid}")
        x_vars[pid] = x
        y_vars[pid] = y

        # ── NoOverlap2D 所需的区间变量 ──
        x_intervals.append(model.NewIntervalVar(x, w, x + w, f"xi_{pid}"))
        y_intervals.append(model.NewIntervalVar(y, h, y + h, f"yi_{pid}"))

        # ── 按分类添加软约束代价项 ──
        part_type = p.get("part_type", "")
        is_zhanwei = ZHANWEI_KEYWORD in part_type

        if is_zhanwei and w > h:
            # 占位(宽>高)：从上往下（10000），从左往右（100）
            cost_terms.append(WEIGHT_ZHANWEI_WIDE_Y * y)
            cost_terms.append(WEIGHT_ZHANWEI_WIDE_X * x)

        elif is_zhanwei:
            # 占位(高>=宽)：从右往左（1000），从上往下（100）
            # 从右往左 ⇔ 最大化 x ⇔ 最小化 (x_hi − x)
            neg_x = model.NewIntVar(0, x_hi, f"neg_x_{pid}")
            model.Add(neg_x == x_hi - x)
            cost_terms.append(WEIGHT_ZHANWEI_TALL_X * neg_x)
            cost_terms.append(WEIGHT_ZHANWEI_TALL_Y * y)

        else:
            # 其他面板：从上往下（10），从左往右（1）
            cost_terms.append(WEIGHT_OTHER_Y * y)
            cost_terms.append(WEIGHT_OTHER_X * x)

    # ── 硬约束：不重叠 ──
    model.AddNoOverlap2D(x_intervals, y_intervals)

    # ── 目标：最小化加权位置代价 ──
    model.Minimize(cp_model.LinearExpr.Sum(cost_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = solver_time_limit
    solver.parameters.num_workers = solver_num_workers
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise ValueError(
            f"求解失败：柜体 ({cabinet_width}x{cabinet_height}) "
            f"无法容纳 {len(parts)} 个面板，状态码: {status}"
        )

    return {
        p["part_id"]: {
            "position": [
                round(solver.Value(x_vars[p["part_id"]]), 2),
                round(solver.Value(y_vars[p["part_id"]]), 2),
            ],
            "rotation": 0,
        }
        for p in parts
    }

