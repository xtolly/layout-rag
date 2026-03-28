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
        # scale_y = 1.0 
        # 允许 Y 轴等比拉伸
        scale_y = curr_size[1] / tpl_size[1] if tpl_size[1] > 0 else 1.0

        tpl_dict = defaultdict(list)
        for tp in tpl_parts:
            if tp["part_id"] in tpl_arrange:
                tpl_dict[tp["part_type"]].append(tp)

        matched_parts = []
        unmatched_parts = []
        used_tpl_ids = set()

        # 优化点：提前计算面积，避免在 sort 中重复计算
        sorted_curr_parts = sorted(
            curr_parts, 
            key=lambda cp: cp.get("part_size", [0, 0])[0] * cp.get("part_size", [0, 0])[1], 
            reverse=True
        )

        for cp in sorted_curr_parts:
            c_type = cp["part_type"]
            cw, ch = cp.get("part_size", [0, 0])
            
            best_match = None
            min_diff_sq = float('inf')
            c_ratio = cw / ch if ch > 0 else 1.0

            for tp in tpl_dict.get(c_type, []):
                if tp["part_id"] in used_tpl_ids:
                    continue
                tw, th = tp.get("part_size", [0, 0])
                
                # 优化点：移除 sqrt，直接用平方值比较性能更高
                size_dist_sq = (cw - tw)**2 + (ch - th)**2
                t_ratio = tw / th if th > 0 else 1.0
                ratio_diff = abs(c_ratio - t_ratio) * 200.0
                
                # 近似权重结合
                diff = size_dist_sq + (ratio_diff ** 2)
                if diff < min_diff_sq:
                    min_diff_sq = diff
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
                
                part_info["target_x"] = min(max(0, orig_pos[0] * scale_x), max(0, curr_size[0] - cw))
                part_info["target_y"] = min(max(0, orig_pos[1] * scale_y), max(0, curr_size[1] - ch))
                part_info["rotation"] = tpl_arrange[best_match["part_id"]].get("rotation", 0)
                part_info["weight"] = 1000 
                matched_parts.append(part_info)
            else:
                unmatched_parts.append(part_info)

        matched_by_type = defaultdict(list)
        for p in matched_parts:
            matched_by_type[p["type"]].append(p)

        # 修复逻辑错误：使用独立的 cursor 对象追踪排版游标，绝不修改 anchor 本体
        placement_cursors = {} 
        
        for up in unmatched_parts:
            ptype = up["type"]
            if ptype in matched_by_type and matched_by_type[ptype]:
                best_anchor = None
                min_size_diff_sq = float('inf')
                cw, ch = up["w"], up["h"]
                
                for mp in matched_by_type[ptype]:
                    mw, mh = mp["w"], mp["h"]
                    diff_sq = (cw - mw)**2 + (ch - mh)**2
                    if diff_sq < min_size_diff_sq:
                        min_size_diff_sq = diff_sq
                        best_anchor = mp
                
                anchor_id = best_anchor["id"]
                if anchor_id not in placement_cursors:
                    placement_cursors[anchor_id] = {
                        "x": best_anchor["target_x"] + best_anchor["w"],
                        "y": best_anchor["target_y"]
                    }

                proposed_x = placement_cursors[anchor_id]["x"]
                proposed_y = placement_cursors[anchor_id]["y"]

                if proposed_x + up["w"] > curr_size[0]:
                    # 折行逻辑
                    proposed_x = 20.0 
                    proposed_y += up["h"] + 20.0 

                up["target_x"] = proposed_x
                up["target_y"] = proposed_y
                up["weight"] = 10
                
                # 更新游标
                placement_cursors[anchor_id]["x"] = proposed_x + up["w"]
                placement_cursors[anchor_id]["y"] = proposed_y
            else:
                up["target_x"] = 50.0
                up["target_y"] = max(0, curr_size[1] - up["h"] - 50.0)
                up["weight"] = 5 
            
            matched_parts.append(up)

        if not matched_parts:
            return project_data
            
        project_data["arrange"] = self._solve_weighted_layout(matched_parts, curr_size[0], curr_size[1])
        return project_data

    def _solve_weighted_layout(self, all_parts, panel_w, panel_h):
        model = cp_model.CpModel()
        
        margin = 10.0
        margin_scaled = int(margin * self.scale)
        max_x = int(panel_w * self.scale)
        max_y = int(panel_h * self.scale)

        x_vars, y_vars = {}, {}
        x_intervals, y_intervals = [], []
        cost_terms = []

        for p in all_parts:
            pid = p["id"]
            w = int(p["w"] * self.scale)
            h = int(p["h"] * self.scale)

            min_allowed_x = margin_scaled
            max_allowed_x = max(margin_scaled, max_x - w - margin_scaled)
            min_allowed_y = margin_scaled
            max_allowed_y = max(margin_scaled, max_y - h - margin_scaled)

            if max_allowed_x < min_allowed_x or max_allowed_y < min_allowed_y:
                raise ValueError(f"元件 {pid} 尺寸({p['w']}x{p['h']})扣除 10mm 边距后超出面板限制 ({panel_w}x{panel_h})。")

            x = model.NewIntVar(min_allowed_x, max_allowed_x, f'x_{pid}')
            y = model.NewIntVar(min_allowed_y, max_allowed_y, f'y_{pid}')
            x_vars[pid] = x
            y_vars[pid] = y

            x_intervals.append(model.NewIntervalVar(x, w, x + w, f'x_int_{pid}'))
            y_intervals.append(model.NewIntervalVar(y, h, y + h, f'y_int_{pid}'))

            tx_clamped = min(max(int(p["target_x"] * self.scale), min_allowed_x), max_allowed_x)
            ty_clamped = min(max(int(p["target_y"] * self.scale), min_allowed_y), max_allowed_y)
            weight = p["weight"]

            model.AddHint(x, tx_clamped)
            model.AddHint(y, ty_clamped)

            # 优化点：使用不等式构建 L1 范数目标函数，降低求解器生成辅助变量的负担
            dx = model.NewIntVar(0, max_x, f'dx_{pid}')
            dy = model.NewIntVar(0, max_y, f'dy_{pid}')
            model.Add(dx >= x - tx_clamped)
            model.Add(dx >= tx_clamped - x)
            model.Add(dy >= y - ty_clamped)
            model.Add(dy >= ty_clamped - y)
            
            y_penalty_multiplier = 20 
            cost_terms.append(weight * dx)
            cost_terms.append(weight * dy * y_penalty_multiplier)

        # 注意：这里的 NoOverlap2D 保证了边界框不相交。如果你需要元件之间也有 10mm 的真实物理间距，
        # 必须在建立 IntervalVar 时将 size 设为 w + min_spacing_scaled，当前实现仅实现了贴边无重叠。
        model.AddNoOverlap2D(x_intervals, y_intervals)
        
        model.Minimize(cp_model.LinearExpr.Sum(cost_terms))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 60.0
        solver.parameters.num_workers = 4
        
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
            print(f"[严重错误] 面板尺寸过小，状态码: {status}")

        return result_arrange