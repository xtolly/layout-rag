import math
from collections import defaultdict
from ortools.sat.python import cp_model

class LayoutOptimizer:
    def __init__(self, precision_scale=10):
        self.scale = precision_scale

    def apply_layout_template(self, template_data: dict, project_data: dict) -> dict:
        curr_parts = project_data.get("meta", {}).get("parts", [])
        curr_size = project_data.get("meta", {}).get("panel_size", [600, 1600])
        tpl_parts = template_data.get("meta", {}).get("parts", [])
        tpl_arrange = template_data.get("arrange", {})
        tpl_size = template_data.get("meta", {}).get("panel_size", [600, 1600])

        scale_x = curr_size[0] / tpl_size[0] if tpl_size[0] > 0 else 1.0
        scale_y = curr_size[1] / tpl_size[1] if tpl_size[1] > 0 else 1.0

        # --- 1. 基础匹配逻辑 (保留上一次修复的最近邻匹配) ---
        tpl_dict = defaultdict(list)
        for tp in tpl_parts:
            if tp["part_id"] in tpl_arrange:
                tpl_dict[tp["part_type"]].append(tp)

        matched_parts = []
        unmatched_parts = []
        used_tpl_ids = set()

        for cp in curr_parts:
            c_type = cp["part_type"]
            cw, ch = cp.get("part_size", [0, 0])
            
            best_match = None
            min_diff = float('inf')

            for tp in tpl_dict.get(c_type, []):
                if tp["part_id"] in used_tpl_ids:
                    continue
                tw, th = tp.get("part_size", [0, 0])
                diff = math.sqrt((cw - tw)**2 + (ch - th)**2)
                if diff < min_diff:
                    min_diff = diff
                    best_match = tp

            part_info = {
                "id": cp["part_id"],
                "type": c_type,
                "w": cw,
                "h": ch,
                "rotation": 0
            }

            if best_match:
                used_tpl_ids.add(best_match["part_id"])
                orig_pos = tpl_arrange[best_match["part_id"]]["position"]
                part_info["target_x"] = min(max(0, orig_pos[0] * scale_x), curr_size[0] - cw)
                part_info["target_y"] = min(max(0, orig_pos[1] * scale_y), curr_size[1] - ch)
                part_info["rotation"] = tpl_arrange[best_match["part_id"]].get("rotation", 0)
                part_info["weight"] = 100  # 原有模板元件：高权重，强制贴合
                matched_parts.append(part_info)
            else:
                unmatched_parts.append(part_info)

        # --- 2. 启发式锚点生成 (处理新增元件) ---
        # 统计已有类型的分布边界
        matched_extents = {}
        for p in matched_parts:
            ptype = p["type"]
            if ptype not in matched_extents:
                matched_extents[ptype] = {"max_x": 0.0, "sum_y": 0.0, "count": 0}
            matched_extents[ptype]["max_x"] = max(matched_extents[ptype]["max_x"], p["target_x"] + p["w"])
            matched_extents[ptype]["sum_y"] += p["target_y"]
            matched_extents[ptype]["count"] += 1

        unmatched_by_type = defaultdict(list)
        for up in unmatched_parts:
            unmatched_by_type[up["type"]].append(up)

        # 为新增元件分配虚拟期望坐标
        for ptype, up_list in unmatched_by_type.items():
            if ptype in matched_extents:
                # 如果面板上有同类：安排在同类簇的右侧，沿 Y 轴均值水平排布
                start_x = matched_extents[ptype]["max_x"] + 10.0 # 预留 10mm 间隙
                start_y = matched_extents[ptype]["sum_y"] / matched_extents[ptype]["count"]
            else:
                # 如果是全新的类型：默认扔到面板底部安全区域 (留出 50mm 边距)
                start_x = 50.0
                start_y = max(0, curr_size[1] - 150.0)

            current_x = start_x
            for up in up_list:
                # 防止虚拟坐标超出面板右侧边界
                up["target_x"] = min(current_x, curr_size[0] - up["w"])
                up["target_y"] = min(start_y, curr_size[1] - up["h"])
                up["weight"] = 10  # 新增元件：低权重，允许求解器为其寻找附近无重叠的空位
                
                matched_parts.append(up)
                current_x += up["w"] + 5.0 # 水平间距 5mm

        if not matched_parts:
            return project_data

        # --- 3. 执行全局求解 ---
        project_data["arrange"] = self._solve_weighted_layout(matched_parts, curr_size[0], curr_size[1])
        return project_data

    def _solve_weighted_layout(self, all_parts, panel_w, panel_h):
        model = cp_model.CpModel()
        max_x = int(panel_w * self.scale)
        max_y = int(panel_h * self.scale)

        x_vars, y_vars = {}, {}
        x_intervals, y_intervals = [], []
        cost_terms = []

        # 构建硬约束
        for p in all_parts:
            pid = p["id"]
            w = int(p["w"] * self.scale)
            h = int(p["h"] * self.scale)

            x = model.NewIntVar(0, max(0, max_x - w), f'x_{pid}')
            y = model.NewIntVar(0, max(0, max_y - h), f'y_{pid}')
            x_vars[pid] = x
            y_vars[pid] = y

            x_end = model.NewIntVar(0, max_x, f'x_end_{pid}')
            y_end = model.NewIntVar(0, max_y, f'y_end_{pid}')
            x_intervals.append(model.NewIntervalVar(x, w, x_end, f'x_int_{pid}'))
            y_intervals.append(model.NewIntervalVar(y, h, y_end, f'y_int_{pid}'))

            # 构建软约束 (结合预处理分配的权重)
            tx = int(p["target_x"] * self.scale)
            ty = int(p["target_y"] * self.scale)
            weight = p["weight"]

            dx = model.NewIntVar(0, max_x, f'dx_{pid}')
            dy = model.NewIntVar(0, max_y, f'dy_{pid}')
            
            model.AddAbsEquality(dx, x - tx)
            model.AddAbsEquality(dy, y - ty)
            
            cost_terms.append(weight * dx)
            cost_terms.append(weight * dy)

        model.AddNoOverlap2D(x_intervals, y_intervals)
        model.Minimize(sum(cost_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 10.0
        status = solver.Solve(model)

        result_arrange = {}
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            for p in all_parts:
                pid = p["id"]
                result_arrange[pid] = {
                    "position": [
                        round(solver.Value(x_vars[pid]) / self.scale, 2),
                        round(solver.Value(y_vars[pid]) / self.scale, 2)
                    ],
                    "rotation": p.get("rotation", 0)
                }
        else:
            print(f"[严重错误] 面板尺寸过小，物理上无法满足排版！状态码: {status}")

        return result_arrange