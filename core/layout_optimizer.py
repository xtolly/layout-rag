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
        
        # 保持 Y 轴真实物理间距，不进行等比拉伸
        tpl_size = template_data.get("meta", {}).get("panel_size", [600, 1600])
        scale_x = curr_size[0] / tpl_size[0] if tpl_size[0] > 0 else 1.0
        scale_y = 1.0 

        tpl_dict = defaultdict(list)
        for tp in tpl_parts:
            if tp["part_id"] in tpl_arrange:
                tpl_dict[tp["part_type"]].append(tp)

        matched_parts = []
        unmatched_parts = []
        used_tpl_ids = set()

        sorted_curr_parts = sorted(
            curr_parts, 
            key=lambda cp: cp.get("part_size", [0, 0])[0] * cp.get("part_size", [0, 0])[1], 
            reverse=True
        )

        for cp in sorted_curr_parts:
            c_type = cp["part_type"]
            cw, ch = cp.get("part_size", [0, 0])
            
            best_match = None
            min_diff = float('inf')
            c_ratio = cw / ch if ch > 0 else 1.0

            for tp in tpl_dict.get(c_type, []):
                if tp["part_id"] in used_tpl_ids:
                    continue
                tw, th = tp.get("part_size", [0, 0])
                
                size_dist = math.sqrt((cw - tw)**2 + (ch - th)**2)
                t_ratio = tw / th if th > 0 else 1.0
                ratio_diff = abs(c_ratio - t_ratio) * 200.0
                
                diff = size_dist + ratio_diff
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
                part_info["weight"] = 100 
                matched_parts.append(part_info)
            else:
                unmatched_parts.append(part_info)

        matched_by_type = defaultdict(list)
        for p in matched_parts:
            matched_by_type[p["type"]].append(p)

        anchor_offsets = {} 
        
        # 处理锚点 X 轴溢出问题
        for up in unmatched_parts:
            ptype = up["type"]
            if ptype in matched_by_type and matched_by_type[ptype]:
                best_anchor = None
                min_size_diff = float('inf')
                cw, ch = up["w"], up["h"]
                
                for mp in matched_by_type[ptype]:
                    mw, mh = mp["w"], mp["h"]
                    diff = math.sqrt((cw - mw)**2 + (ch - mh)**2)
                    if diff < min_size_diff:
                        min_size_diff = diff
                        best_anchor = mp
                
                anchor_id = best_anchor["id"]
                if anchor_id not in anchor_offsets:
                    anchor_offsets[anchor_id] = best_anchor["target_x"] + best_anchor["w"] + 5.0

                proposed_x = anchor_offsets[anchor_id]
                if proposed_x + up["w"] > curr_size[0]:
                    # 溢出折行
                    proposed_x = 20.0 
                    best_anchor["target_y"] += up["h"] + 20.0 
                    anchor_offsets[anchor_id] = proposed_x

                up["target_x"] = proposed_x
                up["target_y"] = best_anchor["target_y"]
                up["weight"] = 10
                
                anchor_offsets[anchor_id] = proposed_x + up["w"] + 5.0 
            else:
                up["target_x"] = 50.0
                up["target_y"] = max(0, curr_size[1] - up["h"] - 50.0)
                up["weight"] = 5 
            
            matched_parts.append(up)

        if not matched_parts:
            return project_data
            
        # --- 拓扑硬约束预处理 (地排沉底与全局 Y 轴挤压) ---
        margin = 10.0
        bottom_keywords = ["地排"]
        ground_busbars = [p for p in matched_parts if any(kw in p["type"] for kw in bottom_keywords)]

        if ground_busbars:
            max_gb_h = max(gb["h"] for gb in ground_busbars)
            bottom_y_limit = max(margin, curr_size[1] - max_gb_h - margin)

            for p in matched_parts:
                if any(kw in p["type"] for kw in bottom_keywords):
                    p["target_y"] = bottom_y_limit
                    p["target_x"] = min(max(margin, p["target_x"]), curr_size[0] - p["w"] - margin)
                    p["weight"] = 200 
                else:
                    max_allowed_y = bottom_y_limit - p["h"] - margin
                    if p["target_y"] > max_allowed_y:
                        p["target_y"] = max(margin, max_allowed_y)

        # 执行全局求解
        project_data["arrange"] = self._solve_weighted_layout(matched_parts, curr_size[0], curr_size[1], bottom_keywords)
        return project_data

    def _solve_weighted_layout(self, all_parts, panel_w, panel_h, bottom_keywords=["地排"]):
        model = cp_model.CpModel()
        
        margin = 10.0
        margin_scaled = int(margin * self.scale)
        
        max_x = int(panel_w * self.scale)
        max_y = int(panel_h * self.scale)

        x_vars, y_vars = {}, {}
        x_intervals, y_intervals = [], []
        cost_terms = []
        ground_busbar_ids = set()

        # --- 阶段 1：变量定义与自身软硬约束 ---
        for p in all_parts:
            pid = p["id"]
            w = int(p["w"] * self.scale)
            h = int(p["h"] * self.scale)
            
            if any(kw in p.get("type", "") for kw in bottom_keywords):
                ground_busbar_ids.add(pid)

            min_allowed_x = margin_scaled
            max_allowed_x = max(margin_scaled, max_x - w - margin_scaled)
            min_allowed_y = margin_scaled
            max_allowed_y = max(margin_scaled, max_y - h - margin_scaled)

            if max_allowed_x < min_allowed_x or max_allowed_y < min_allowed_y:
                raise ValueError(f"元件 {pid} 尺寸过大或面板过小，扣除 10mm 边距后无法容纳该元件。")

            x = model.NewIntVar(min_allowed_x, max_allowed_x, f'x_{pid}')
            y = model.NewIntVar(min_allowed_y, max_allowed_y, f'y_{pid}')
            x_vars[pid] = x
            y_vars[pid] = y

            x_end = model.NewIntVar(0, max_x, f'x_end_{pid}')
            y_end = model.NewIntVar(0, max_y, f'y_end_{pid}')
            x_intervals.append(model.NewIntervalVar(x, w, x_end, f'x_int_{pid}'))
            y_intervals.append(model.NewIntervalVar(y, h, y_end, f'y_int_{pid}'))

            tx = int(p["target_x"] * self.scale)
            ty = int(p["target_y"] * self.scale)
            weight = p["weight"]

            tx_clamped = min(max(tx, min_allowed_x), max_allowed_x)
            ty_clamped = min(max(ty, min_allowed_y), max_allowed_y)

            model.AddHint(x, tx_clamped)
            model.AddHint(y, ty_clamped)

            dx = model.NewIntVar(0, max_x, f'dx_{pid}')
            dy = model.NewIntVar(0, max_y, f'dy_{pid}')
            
            model.AddAbsEquality(dx, x - tx_clamped)
            model.AddAbsEquality(dy, y - ty_clamped)
            
            y_penalty_multiplier = 20 
            
            cost_terms.append(weight * dx)
            cost_terms.append(weight * dy * y_penalty_multiplier)

        # --- 阶段 2：全局拓扑硬约束 (必须严格放在循环体外) ---
        if ground_busbar_ids:
            for gid in ground_busbar_ids:
                for p in all_parts:
                    pid = p["id"]
                    if pid not in ground_busbar_ids:
                        h_scaled = int(p["h"] * self.scale)
                        # 其他所有元件底边必须小于等于地排顶边
                        model.Add(y_vars[pid] + h_scaled <= y_vars[gid])

        # 全局无重叠约束
        model.AddNoOverlap2D(x_intervals, y_intervals)
        
        # 目标函数
        model.Minimize(cp_model.LinearExpr.Sum(cost_terms))

        # --- 阶段 3：执行求解 ---
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 10.0
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
            print(f"[严重错误] 面板尺寸过小，或新增的硬约束导致物理空间上无解！状态码: {status}")

        return result_arrange