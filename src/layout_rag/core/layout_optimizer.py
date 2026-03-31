"""
布局优化器 —— 基于模板映射 + CP-SAT 约束求解的电气柜元件自动排版。

整体流程分为 **坐标映射** 和 **约束求解** 两个阶段：

  坐标映射阶段  按以下优先级为每个待排元件分配一个"期望位置 (target)"和置信权重：
  ┌─────────────────────────────────────────────────────────────────────┐
  │  优先级 1 — 主模板精确映射 (weight=1000)                           │
  │    按 part_type 匹配，贪心选尺寸+宽高比最接近的模板元件，           │
  │    等比缩放坐标到当前面板尺寸。                                     │
  │                                                                     │
  │  优先级 2 — 备选模板补位 (weight=120)                               │
  │    仅当主模板中完全没有该 part_type 时，才从其他推荐模板借坐标。     │
  │                                                                     │
  │  优先级 3 — 同类型游标续排 (weight=10)                              │
  │    主模板已有同类型锚点，把新增元件沿最近锚点向右续排，溢出则折行。  │
  │                                                                     │
  │  优先级 4 — 默认兜底 (weight=5)                                     │
  │    无任何参考，放到面板底部边距附近，交给求解器兜底。                │
  └─────────────────────────────────────────────────────────────────────┘

  约束求解阶段  使用 OR-Tools CP-SAT 在满足以下硬约束的前提下，
  最小化所有元件到其 target 的加权 L1 距离：
    • 面板边距约束：元件不能触碰面板边缘
    • 不重叠约束：任意两个元件的膨胀矩形（含间距）不交叉
"""

import math
from collections import defaultdict
from ortools.sat.python import cp_model


# ---------------------------------------------------------------------------
# 权重常量：数值越大，求解器越倾向保持该元件的期望位置不变。
# ---------------------------------------------------------------------------
WEIGHT_PRIMARY = 1000   # 主模板精确映射
WEIGHT_FALLBACK = 120   # 备选模板补位
WEIGHT_CURSOR = 10      # 同类型游标续排
WEIGHT_CURSOR_REL = 200 # 游标元件相对锚点的位置约束（解决锚点被挤走后游标脱节）
WEIGHT_DEFAULT = 5      # 无参考兜底

# 默认面板尺寸 (mm)，当模板或项目数据缺失时使用。
_DEFAULT_PANEL_SIZE = [600, 1600]


class LayoutOptimizer:
    """
    电气柜面板布局优化器。

    将参考模板的排版方案迁移到当前项目：先将模板中同类型、尺寸相近的元件坐标
    映射到当前面板，再通过 CP-SAT 约束求解器在满足不重叠和边距约束的前提下，
    求出与期望位置偏差最小的最终布局。

    Args:
        precision_scale: 浮点坐标转整数的缩放因子（CP-SAT 仅支持整数）。
                         默认 1.0 表示精度 1mm。
        margin:          面板四周保留的最小边距 (mm)。
        element_gap:     任意两个元件之间的最小间距 (mm)。
        y_penalty:       Y 轴偏移的惩罚倍数。>1 时让求解器优先水平位移而非垂直位移，
                         使同一行的元件尽量保持在同一水平线上。
    """

    def __init__(
        self,
        precision_scale: int = 1,
        margin: float = 10.0,
        element_gap: float = 0,
        y_penalty: int = 10,
    ):
        self.scale = precision_scale
        self.margin = margin
        self.element_gap = element_gap
        self.y_penalty = y_penalty

    # ===================================================================
    #  公共方法
    # ===================================================================

    def apply_layout_template(
        self,
        template_data: dict,
        project_data: dict,
        fallback_templates: list[dict] | None = None,
    ) -> dict:
        """
        核心入口：将模板排版方案迁移到当前项目。

        Args:
            template_data:      主参考模板（含 meta.parts / arrange）。
            project_data:       当前项目数据（含 meta.parts / meta.panel_size），
                                排版结果直接写入 project_data["arrange"]。
            fallback_templates: 其他推荐模板列表，用于补充主模板缺失的 part_type。

        Returns:
            更新了 ``arrange`` 字段的 project_data。
        """
        curr_parts = project_data.get("meta", {}).get("parts", [])
        curr_size = project_data.get("meta", {}).get("panel_size", _DEFAULT_PANEL_SIZE)
        tpl_parts = template_data.get("meta", {}).get("parts", [])
        tpl_arrange = template_data.get("arrange", {})
        tpl_size = template_data.get("meta", {}).get("panel_size", _DEFAULT_PANEL_SIZE)

        # 坐标缩放因子：模板面板 → 当前面板
        scale_x, scale_y = self._compute_scale(curr_size, tpl_size)

        # ── 阶段 1：主模板精确匹配 ──
        matched, unmatched = self._match_parts_to_template(
            curr_parts, tpl_parts, tpl_arrange, scale_x, scale_y, curr_size,
        )

        # ── 阶段 2：为未匹配元件分配期望位置 ──
        fallback_index = self._build_fallback_type_index(fallback_templates or [], curr_size)
        all_parts = self._resolve_unmatched_targets(
            matched, unmatched, fallback_index, curr_size,
        )

        if not all_parts:
            return project_data

        # ── 阶段 3：CP-SAT 约束求解 ──
        project_data["arrange"] = self._solve_layout(all_parts, curr_size[0], curr_size[1])
        return project_data

    # ===================================================================
    #  阶段 1：主模板精确匹配
    # ===================================================================

    def _match_parts_to_template(
        self,
        curr_parts: list[dict],
        tpl_parts: list[dict],
        tpl_arrange: dict,
        scale_x: float,
        scale_y: float,
        panel_size: list[float],
    ) -> tuple[list[dict], list[dict]]:
        """
        将当前项目的每个元件与主模板中**同类型、尺寸最接近**的元件一一配对。

        匹配策略：
          1. 按元件面积从大到小排序，优先为大元件锁定模板配对。
          2. 对每个元件，在模板的同 part_type 候选中选 _compute_match_diff 最小的。
          3. 已配对的模板元件不再参与后续匹配（贪心一对一）。

        Returns:
            (matched, unmatched) — matched 带有 target 坐标和 WEIGHT_PRIMARY，
            unmatched 仅含基本尺寸信息，待后续阶段补充。
        """
        # 按 part_type 将有排版信息的模板元件归类
        tpl_by_type: dict[str, list[dict]] = defaultdict(list)
        for tp in tpl_parts:
            if tp["part_id"] in tpl_arrange:
                tpl_by_type[tp["part_type"]].append(tp)

        # 按面积降序，大元件优先匹配
        sorted_parts = sorted(
            curr_parts,
            key=lambda p: p.get("part_size", [0, 0])[0] * p.get("part_size", [0, 0])[1],
            reverse=True,
        )

        matched: list[dict] = []
        unmatched: list[dict] = []
        used_tpl_ids: set[str] = set()

        for cp in sorted_parts:
            part_type = cp["part_type"]
            cw, ch = cp.get("part_size", [0, 0])

            # 在同类型模板元件中找尺寸最接近的
            best_tp = self._find_best_match(
                cw, ch, tpl_by_type.get(part_type, []), used_tpl_ids,
            )

            info = self._make_part_info(cp)

            if best_tp:
                used_tpl_ids.add(best_tp["part_id"])
                arrange = tpl_arrange[best_tp["part_id"]]
                info["target_x"] = self._clamp_target(arrange["position"][0] * scale_x, cw, panel_size[0])
                info["target_y"] = self._clamp_target(arrange["position"][1] * scale_y, ch, panel_size[1])
                info["rotation"] = arrange.get("rotation", 0)
                info["weight"] = WEIGHT_PRIMARY
                matched.append(info)
            else:
                unmatched.append(info)

        return matched, unmatched

    # ===================================================================
    #  阶段 2：为未匹配元件分配期望位置
    # ===================================================================

    def _resolve_unmatched_targets(
        self,
        matched: list[dict],
        unmatched: list[dict],
        fallback_index: dict[str, list[dict]],
        panel_size: list[float],
    ) -> list[dict]:
        """
        按优先级 2→3→4 为每个 unmatched 元件分配 target 坐标。

        处理顺序：
          - 若主模板中完全没有该 part_type → 尝试从 fallback_index 补位
          - 若主模板中已有同类型锚点 → 游标续排（向右追加，溢出折行）
          - 都没有 → 放到面板底部边距内兜底
        """
        # 按类型索引已匹配元件，作为游标续排的锚点参考
        anchors_by_type: dict[str, list[dict]] = defaultdict(list)
        for p in matched:
            anchors_by_type[p["type"]].append(p)
        primary_types = set(anchors_by_type.keys())

        placement_cursors: dict[str, dict] = {}     # anchor_id → {x, y, row_max_h} 游标位置
        used_fallback_ids: set[str] = set()

        # 按类型排序，确保同类型元件连续处理，从而链式复用同一个游标
        for part in sorted(unmatched, key=lambda p: p["type"]):
            ptype = part["type"]

            # ── 优先级 2：备选模板补位 ──
            if ptype not in primary_types:
                candidate = self._find_best_fallback_candidate(
                    part, fallback_index.get(ptype, []), used_fallback_ids,
                )
                if candidate:
                    used_fallback_ids.add(candidate["candidate_id"])
                    part["target_x"] = self._clamp_target(candidate["target_x"], part["w"], panel_size[0])
                    part["target_y"] = self._clamp_target(candidate["target_y"], part["h"], panel_size[1])
                    part["rotation"] = candidate.get("rotation", 0)
                    part["weight"] = WEIGHT_FALLBACK
                    matched.append(part)
                    anchors_by_type[ptype].append(part)
                    continue

            # ── 优先级 3：同类型游标续排 ──
            if anchors_by_type.get(ptype):
                self._assign_cursor_target(part, anchors_by_type[ptype], placement_cursors, panel_size)
                part["weight"] = WEIGHT_CURSOR
                matched.append(part)
                anchors_by_type[ptype].append(part)
                continue

            # ── 优先级 4：默认兜底 ──
            part["target_x"] = self.margin
            part["target_y"] = max(self.margin, panel_size[1] - part["h"] - self.margin)
            part["weight"] = WEIGHT_DEFAULT
            matched.append(part)
            anchors_by_type[ptype].append(part)

        return matched

    def _assign_cursor_target(
        self,
        part: dict,
        same_type_anchors: list[dict],
        cursors: dict[str, dict],
        panel_size: list[float],
    ) -> None:
        """
        沿同类型元件最密集的聚簇向右续排，X 溢出时折行，Y 溢出时钳位到底部。

        锚点选择策略（解决 "多余元件应和同类型放一起" 的问题）：
          1. 优先复用已有游标 —— 若之前已有同类型锚点创建了游标，继续在其后追加，
             保证同类型元件链式排布在同一区域。
          2. 若无已有游标，选择所在行同类型邻居最多的锚点（最密集聚簇），
             而非仅按尺寸最近选取，避免多余元件散落到不相关的位置。

        游标结构 {x, y, row_max_h}：
          - x, y: 下一个元件的放置坐标
          - row_max_h: 当前行已放置元件（含锚点）的最大物理高度，
                       折行时用它递增 Y，避免与高矮不一的元件重叠。
        """
        part_pw, part_ph = self._physical_size(part["w"], part["h"], part.get("rotation", 0))

        # ── 策略 1：优先复用已有游标，确保同类型元件连续排列 ──
        active_anchor = None
        for a in same_type_anchors:
            if a["id"] in cursors:
                active_anchor = a
                break

        # ── 策略 2：无已有游标时，选最密集聚簇中的锚点 ──
        if active_anchor is None:
            active_anchor = self._find_cluster_anchor(part, same_type_anchors, panel_size[1])

        anchor_id = active_anchor["id"]
        anchor_pw, anchor_ph = self._physical_size(
            active_anchor["w"], active_anchor["h"], active_anchor.get("rotation", 0),
        )

        # 初始化游标：锚点右侧边缘开始，row_max_h 设为锚点高度
        if anchor_id not in cursors:
            cursors[anchor_id] = {
                "x": active_anchor["target_x"] + anchor_pw,
                "y": active_anchor["target_y"],
                "row_max_h": anchor_ph,
            }

        cursor = cursors[anchor_id]
        x, y = cursor["x"], cursor["y"]

        # X 溢出 → 折行：Y 递增当前行最大高度
        if x + part_pw > panel_size[0] - self.margin:
            x = self.margin
            y += cursor["row_max_h"] + self.element_gap
            cursor["row_max_h"] = 0  # 新行重置

        # Y 溢出 → 钳位到面板底部可行域
        if y + part_ph > panel_size[1] - self.margin:
            y = max(self.margin, panel_size[1] - part_ph - self.margin)

        part["target_x"] = x
        part["target_y"] = y
        part["anchor_id"] = anchor_id
        part["anchor_offset_x"] = x - active_anchor["target_x"]
        part["anchor_offset_y"] = y - active_anchor["target_y"]

        # 推进游标，更新当前行最大高度
        cursor["x"] = x + part_pw
        cursor["y"] = y
        cursor["row_max_h"] = max(cursor["row_max_h"], part_ph)

    def _find_cluster_anchor(
        self,
        part: dict,
        same_type_anchors: list[dict],
        panel_h: float,
    ) -> dict:
        """
        在同类型锚点中，选择位于最密集水平行的那个。

        通过统计每个锚点在 Y 方向上的同类邻居数量来判断聚簇密度，
        优先选邻居最多的（最大聚簇），同等密度时选尺寸最接近的。
        """
        if len(same_type_anchors) <= 1:
            return same_type_anchors[0]

        candidates = [a for a in same_type_anchors if "target_y" in a]
        if not candidates:
            return same_type_anchors[0]

        _, part_ph = self._physical_size(part["w"], part["h"], part.get("rotation", 0))
        y_tolerance = max(part_ph, panel_h * 0.03, 10.0)

        best = candidates[0]
        best_neighbors = -1
        best_size_diff = math.inf

        for anchor in candidates:
            ay = anchor["target_y"]
            neighbors = sum(
                1 for a in candidates if abs(a["target_y"] - ay) <= y_tolerance
            )
            size_diff = (part["w"] - anchor["w"]) ** 2 + (part["h"] - anchor["h"]) ** 2

            if neighbors > best_neighbors or (
                neighbors == best_neighbors and size_diff < best_size_diff
            ):
                best_neighbors = neighbors
                best_size_diff = size_diff
                best = anchor

        return best

    # ===================================================================
    #  阶段 3：CP-SAT 约束求解
    # ===================================================================

    def _solve_layout(
        self,
        all_parts: list[dict],
        panel_w: float,
        panel_h: float,
    ) -> dict[str, dict]:
        """
        使用 OR-Tools CP-SAT 求解器计算最终布局。

        模型设计：
          • 变量：每个元件的 (x, y) 左上角坐标
          • 硬约束：
            - 边距约束：x ∈ [margin, panel_w - w - margin]，y 同理
            - 不重叠：通过 NoOverlap2D 保证膨胀后的矩形（含 element_gap）不交叉
          • 目标函数：最小化 ∑ weight_i * (|x_i - tx_i| + y_penalty * |y_i - ty_i|)
            用 L1 范数代替 L2 以保持线性可解性。

        Raises:
            ValueError: 面板尺寸不足以放下所有元件时抛出。
        """
        model = cp_model.CpModel()

        margin_s = int(self.margin * self.scale)
        gap_s = int(self.element_gap * self.scale)
        max_x_s = int(panel_w * self.scale)
        max_y_s = int(panel_h * self.scale)

        x_vars: dict[str, cp_model.IntVar] = {}
        y_vars: dict[str, cp_model.IntVar] = {}
        x_intervals: list[cp_model.IntervalVar] = []
        y_intervals: list[cp_model.IntervalVar] = []
        cost_terms: list = []

        for p in all_parts:
            pid = p["id"]
            pw, ph = self._physical_size(p["w"], p["h"], p.get("rotation", 0))
            w_s = int(pw * self.scale)
            h_s = int(ph * self.scale)

            # ── 变量域 ──
            x_lo, x_hi = margin_s, max(margin_s, max_x_s - w_s - margin_s)
            y_lo, y_hi = margin_s, max(margin_s, max_y_s - h_s - margin_s)

            if x_hi < x_lo or y_hi < y_lo:
                raise ValueError(
                    f"元件 {pid} 尺寸({pw}x{ph})扣除边距后超出面板限制 ({panel_w}x{panel_h})。"
                )

            x = model.NewIntVar(x_lo, x_hi, f"x_{pid}")
            y = model.NewIntVar(y_lo, y_hi, f"y_{pid}")
            x_vars[pid] = x
            y_vars[pid] = y

            # ── 膨胀 Interval（实现元件间距）──
            x_intervals.append(model.NewIntervalVar(x, w_s + gap_s, x + w_s + gap_s, f"xi_{pid}"))
            y_intervals.append(model.NewIntervalVar(y, h_s + gap_s, y + h_s + gap_s, f"yi_{pid}"))

            # ── 目标项：加权 L1 距离 ──
            tx = min(max(int(p["target_x"] * self.scale), x_lo), x_hi)
            ty = min(max(int(p["target_y"] * self.scale), y_lo), y_hi)
            w_coeff = p["weight"]

            # Hint 引导求解初值，加速收敛
            model.AddHint(x, tx)
            model.AddHint(y, ty)

            # |x - tx| 的线性化：dx >= x - tx, dx >= tx - x
            dx = model.NewIntVar(0, max_x_s, f"dx_{pid}")
            dy = model.NewIntVar(0, max_y_s, f"dy_{pid}")
            model.Add(dx >= x - tx)
            model.Add(dx >= tx - x)
            model.Add(dy >= y - ty)
            model.Add(dy >= ty - y)

            cost_terms.append(w_coeff * dx)
            cost_terms.append(w_coeff * dy * self.y_penalty)

            # ── 相对位置约束：游标元件跟随锚点移动 ──
            anchor_id = p.get("anchor_id")
            if anchor_id and anchor_id in x_vars:
                expected_ox = int(p["anchor_offset_x"] * self.scale)
                expected_oy = int(p["anchor_offset_y"] * self.scale)
                anchor_x = x_vars[anchor_id]
                anchor_y = y_vars[anchor_id]

                rel_dx = model.NewIntVar(0, max_x_s, f"rel_dx_{pid}")
                rel_dy = model.NewIntVar(0, max_y_s, f"rel_dy_{pid}")
                model.Add(rel_dx >= (x - anchor_x) - expected_ox)
                model.Add(rel_dx >= expected_ox - (x - anchor_x))
                model.Add(rel_dy >= (y - anchor_y) - expected_oy)
                model.Add(rel_dy >= expected_oy - (y - anchor_y))

                cost_terms.append(WEIGHT_CURSOR_REL * rel_dx)
                cost_terms.append(WEIGHT_CURSOR_REL * rel_dy * self.y_penalty)

        # ── 全局约束 ──
        model.AddNoOverlap2D(x_intervals, y_intervals)

        # ── 求解 ──
        model.Minimize(cp_model.LinearExpr.Sum(cost_terms))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 20.0
        solver.parameters.num_workers = 8
        status = solver.Solve(model)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise ValueError(
                f"求解失败：面板 ({panel_w}x{panel_h}) 无法容纳 {len(all_parts)} 个元件，状态码: {status}"
            )

        return {
            p["id"]: {
                "position": [
                    round(solver.Value(x_vars[p["id"]]) / self.scale, 2),
                    round(solver.Value(y_vars[p["id"]]) / self.scale, 2),
                ],
                "rotation": p.get("rotation", 0),
            }
            for p in all_parts
        }

    # ===================================================================
    #  内部工具方法
    # ===================================================================

    @staticmethod
    def _compute_scale(
        curr_size: list[float],
        tpl_size: list[float],
    ) -> tuple[float, float]:
        """计算模板面板到当前面板的 X/Y 缩放因子。"""
        sx = curr_size[0] / tpl_size[0] if tpl_size[0] > 0 else 1.0
        sy = curr_size[1] / tpl_size[1] if tpl_size[1] > 0 else 1.0
        return sx, sy

    def _clamp_target(self, value: float, part_span: float, panel_span: float) -> float:
        """将坐标裁剪到求解器可行域 [margin, panel_span - part_span - margin]。"""
        lo = self.margin
        hi = max(lo, panel_span - part_span - self.margin)
        return min(max(lo, value), hi)

    @staticmethod
    def _compute_match_diff(curr_w: float, curr_h: float, tpl_w: float, tpl_h: float) -> float:
        """
        衡量两个元件的尺寸差异度（越小越匹配）。

        使用归一化相对误差，使不同绝对尺寸的元件之间可以公平比较：
          1. 宽高的相对误差平方和 — 惩罚尺寸偏离
          2. 宽高比差的平方 — 惩罚形状差异，防止面积接近但形状迥异的误匹配

        两项权重通过 ratio_weight 平衡，默认 4.0 表示形状一致性略重于尺寸接近度。
        """
        base_w = max(abs(tpl_w), abs(curr_w), 1.0)
        base_h = max(abs(tpl_h), abs(curr_h), 1.0)
        rel_size_sq = ((curr_w - tpl_w) / base_w) ** 2 + ((curr_h - tpl_h) / base_h) ** 2

        curr_ratio = curr_w / curr_h if curr_h > 0 else 1.0
        tpl_ratio = tpl_w / tpl_h if tpl_h > 0 else 1.0
        ratio_diff_sq = (curr_ratio - tpl_ratio) ** 2

        ratio_weight = 4.0
        return rel_size_sq + ratio_weight * ratio_diff_sq

    @staticmethod
    def _physical_size(w: float, h: float, rotation: int) -> tuple[float, float]:
        """根据旋转角度返回实际占用的 (宽, 高)。90°/270° 时宽高互换。"""
        if rotation in (90, 270):
            return h, w
        return w, h

    @staticmethod
    def _make_part_info(cp: dict) -> dict:
        """从原始 part dict 构建内部标准化的 part_info 字典。"""
        cw, ch = cp.get("part_size", [0, 0])
        return {
            "id": cp["part_id"],
            "type": cp["part_type"],
            "w": cw,
            "h": ch,
            "rotation": 0,
        }

    @staticmethod
    def _find_best_match(
        cw: float,
        ch: float,
        candidates: list[dict],
        used_ids: set[str],
    ) -> dict | None:
        """在候选列表中找尺寸最接近且未被使用的模板元件。"""
        best, best_diff = None, math.inf
        for tp in candidates:
            if tp["part_id"] in used_ids:
                continue
            tw, th = tp.get("part_size", [0, 0])
            diff = LayoutOptimizer._compute_match_diff(cw, ch, tw, th)
            if diff < best_diff:
                best_diff = diff
                best = tp
        return best

    def _build_fallback_type_index(
        self,
        fallback_templates: list[dict],
        curr_size: list[float],
    ) -> dict[str, list[dict]]:
        """
        将备选模板按 part_type 建立索引。

        每个候选包含等比缩放后的 target 坐标，用于在主模板缺失该类型时提供参考位置。
        """
        index: dict[str, list[dict]] = defaultdict(list)

        for tpl in fallback_templates:
            tpl_parts = tpl.get("meta", {}).get("parts", [])
            tpl_arrange = tpl.get("arrange", {})
            tpl_size = tpl.get("meta", {}).get("panel_size", _DEFAULT_PANEL_SIZE)
            sx, sy = self._compute_scale(curr_size, tpl_size)
            tpl_uuid = tpl.get("uuid", "")

            for tp in tpl_parts:
                part_id = tp.get("part_id")
                arrange = tpl_arrange.get(part_id)
                if not part_id or not arrange:
                    continue

                tw, th = tp.get("part_size", [0, 0])
                index[tp.get("part_type")].append({
                    "candidate_id": f"{tpl_uuid}:{part_id}",
                    "w": tw,
                    "h": th,
                    "target_x": self._clamp_target(arrange["position"][0] * sx, tw, curr_size[0]),
                    "target_y": self._clamp_target(arrange["position"][1] * sy, th, curr_size[1]),
                    "rotation": arrange.get("rotation", 0),
                })

        return index

    @staticmethod
    def _find_best_fallback_candidate(
        part: dict,
        candidates: list[dict],
        used_ids: set[str],
    ) -> dict | None:
        """
        从备选模板候选中找尺寸最接近且未被使用的。

        同一候选只使用一次，确保缺失类型的多个元件分散参考不同模板位置。
        """
        best, best_diff = None, math.inf
        for c in candidates:
            if c["candidate_id"] in used_ids:
                continue
            diff = LayoutOptimizer._compute_match_diff(part["w"], part["h"], c["w"], c["h"])
            if diff < best_diff:
                best_diff = diff
                best = c
        return best