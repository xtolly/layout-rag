"""
将低压开关柜 scheme 数据构建为 Neo4j 图数据库。

数据源：projects/lowvoltage_cabinet/scheme_*.json（完整柜体层级）
数据库：lowvoltagecabinet @ neo4j://127.0.0.1:7687

用法：
    python tools/build_neo4j.py [--password <pwd>] [--clear]

图模型（6 类节点 + 11 种关系）：
    节点：
        CabinetTemplate  (cabinet_use, cabinet_model)
        CabinetInstance   (cabinet_id, width, height, depth, wiring_method, ...)
        PanelTemplate     (panel_type, operation_method)
        PanelInstance      (panel_id, size_w, size_h, position_y, order, 特征属性...)
        PartTemplate      (part_type, part_model, size_w, size_h)
        PartInstance       (part_id, position_x, position_y, rotation)
    关系：
        HAS_INSTANCE, CONTAINS_PANEL(order, position_x, position_y),
        CONTAINS_PART, ADJACENT_TO, SAME_ROW, SAME_COLUMN,
        ADJACENT_PANEL(gap), USED_IN, CO_OCCURS_WITH(panel_type, weight),
        CO_OCCURS_IN_CABINET(weight), TYPICAL_BOM(avg_qty, min_qty, max_qty)
"""

import argparse
import json
import math
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

try:
    from neo4j import GraphDatabase
except ImportError:
    print("错误：pip install neo4j"); sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "projects" / "lowvoltage_cabinet"

ADJACENCY_THRESHOLD = 150
ROW_TOLERANCE = 30
COLUMN_TOLERANCE = 30
PANEL_ADJACENCY_GAP = 50  # 面板间距 ≤ 此值认为邻接


def load_schemes() -> list[dict]:
    """加载所有 scheme JSON 文件。"""
    schemes = []
    for fp in sorted(DATA_DIR.glob("scheme_*.json")):
        if "no_arrange" in fp.name:
            continue
        try:
            with fp.open("r", encoding="utf-8") as f:
                data = json.load(f)
            data["_source"] = fp.name
            schemes.append(data)
        except Exception as e:
            print(f"  ✗ {fp.name}: {e}")
    return schemes


def euclidean(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)


def compute_center(pos, w, h):
    return pos[0] + w/2.0, pos[1] + h/2.0


def cabinet_tkey(cab): return f"{cab.get('cabinet_use','')}|{cab.get('cabinet_model','')}"
def cabinet_vkey(cab): return f"{cabinet_tkey(cab)}|{cab.get('cabinet_width',0)}|{cab.get('cabinet_height',0)}|{cab.get('wiring_method','')}"
def panel_tkey(pan): return f"{pan.get('panel_type','')}|{pan.get('operation_method','')}"
def panel_vkey(pan): return f"{panel_tkey(pan)}|{pan.get('panel_width',0)}|{pan.get('panel_height',0)}|{pan.get('main_circuit_current','')}"
def part_tkey(p): return f"{p.get('part_type','')}|{p.get('part_model','')}"


def extract_panel_features(panel: dict) -> dict:
    """从面板数据中提取推荐用特征（参考 feature_extractor.py）。"""
    parts = panel.get("parts", [])
    pw = panel.get("panel_width", 0)
    ph = panel.get("panel_height", 0)
    panel_area = pw * ph

    widths  = [p.get("part_width", 0) for p in parts]
    heights = [p.get("part_height", 0) for p in parts]
    areas   = [w*h for w, h in zip(widths, heights)]

    feat = {}
    feat["total_parts"]      = len(parts)
    feat["unique_types"]     = len({p.get("part_type","") for p in parts})
    feat["total_parts_area"] = sum(areas)
    feat["fill_ratio"]       = feat["total_parts_area"] / panel_area if panel_area > 0 else 0.0
    feat["panel_aspect_ratio"] = pw / ph if ph > 0 else 0.0

    if widths:
        feat["avg_part_width"]  = sum(widths) / len(widths)
        feat["max_part_width"]  = max(widths)
    if heights:
        feat["avg_part_height"] = sum(heights) / len(heights)
        feat["max_part_height"] = max(heights)

    # 大型元件比例 (面积 > 10000)
    large = sum(1 for a in areas if a > 10000)
    feat["large_part_ratio"] = large / len(parts) if parts else 0.0

    # 主回路电流（归一化用）
    mcc = panel.get("main_circuit_current")
    if mcc is not None:
        feat["main_circuit_current"] = float(mcc)

    return feat


class Neo4jBuilder:
    def __init__(self, uri, user, password, database):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.db = database
        self._cab_tpls = {}
        self._cab_vars = {}
        self._pan_tpls = {}
        self._pan_vars = {}
        self._part_tpls = {}

    def close(self): self.driver.close()

    def _run(self, q, **p):
        with self.driver.session(database=self.db) as s:
            s.run(q, **p)

    def create_constraints(self):
        for label, prop in [
            ("CabinetTemplate","template_key"), ("CabinetVariant","variant_key"), ("CabinetInstance","cabinet_id"),
            ("PanelTemplate","template_key"), ("PanelVariant","variant_key"), ("PanelInstance","panel_id"),
            ("PartTemplate","template_key"), ("PartInstance","part_id"),
        ]:
            self._run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE")
        print("  ✓ 约束已创建")

    def clear(self):
        self._run("MATCH (n) DETACH DELETE n")
        print("  ✓ 数据库已清空")

    def ingest_scheme(self, scheme: dict):
        source = scheme.get("_source", "")
        for cab in scheme.get("cabinets", []):
            self._ingest_cabinet(cab, source)

    def _ingest_cabinet(self, cab: dict, source: str):
        # -- 柜体模板 --
        ctk = cabinet_tkey(cab)
        cab_use = cab.get("cabinet_use", "")
        cab_model = cab.get("cabinet_model", "")
        if ctk not in self._cab_tpls:
            self._cab_tpls[ctk] = True
            self._run("""
                MERGE (ct:CabinetTemplate {template_key: $tk})
                ON CREATE SET ct.name=$name, ct.cabinet_use=$use, ct.cabinet_model=$model
            """, tk=ctk, name=cab_use, use=cab_use, model=cab_model)

        # -- 柜体变体 --
        cvk = cabinet_vkey(cab)
        cw = cab.get("cabinet_width", 0)
        ch = cab.get("cabinet_height", 0)
        cd = cab.get("cabinet_depth")
        wm = cab.get("wiring_method", "")
        if cvk not in self._cab_vars:
            self._cab_vars[cvk] = True
            self._run("""
                MATCH (ct:CabinetTemplate {template_key: $tk})
                MERGE (cv:CabinetVariant {variant_key: $vk})
                ON CREATE SET cv.name=$name, cv.cabinet_use=$use, cv.cabinet_model=$model,
                    cv.width=$w, cv.height=$h, cv.depth=$d, cv.wiring_method=$wm
                MERGE (ct)-[:HAS_VARIANT]->(cv)
            """, tk=ctk, vk=cvk, name=f"{cab_use}-{cw}x{ch}", use=cab_use, model=cab_model, w=cw, h=ch, d=cd, wm=wm)

        # -- 柜体实例 --
        cid = cab.get("cabinet_id", "")
        cname = cab.get("cabinet_name", "")
        self._run("""
            MERGE (ci:CabinetInstance {cabinet_id: $cid})
            ON CREATE SET ci.name=$name, ci.cabinet_name=$cname, ci.source_file=$src
        """, cid=cid, name=f"{cab_use}-{cname}" if cname else cab_use,
            cname=cname, src=source)

        # -- HAS_INSTANCE --
        self._run("""
            MATCH (cv:CabinetVariant {variant_key:$vk})
            MATCH (ci:CabinetInstance {cabinet_id:$cid})
            MERGE (cv)-[:HAS_INSTANCE]->(ci)
        """, vk=cvk, cid=cid)

        # -- 面板处理 --
        panels = cab.get("panels", [])
        cab_arrange = cab.get("arrange", {})
        panel_infos = []  # (panel_id, position_y, panel_height, panel_data, ptk)

        pan_vkeys_in_cab = []

        for pan in panels:
            pid = pan.get("panel_id", "")
            ptk = panel_tkey(pan)
            pvk = panel_vkey(pan)
            pan_vkeys_in_cab.append(pvk)
            p_type = pan.get("panel_type", "")
            op_method = pan.get("operation_method", "")
            pw = pan.get("panel_width", 0)
            ph = pan.get("panel_height", 0)
            arr = cab_arrange.get(pid, {})
            pos = arr.get("position", [0, 0])
            order_val = pan.get("order", 0)

            # 面板模板
            if ptk not in self._pan_tpls:
                self._pan_tpls[ptk] = True
                self._run("""
                    MERGE (pt:PanelTemplate {template_key:$tk})
                    ON CREATE SET pt.name=$name, pt.panel_type=$ptype, pt.operation_method=$om
                """, tk=ptk, name=p_type, ptype=p_type, om=op_method)

            # 面板变体
            if pvk not in self._pan_vars:
                self._pan_vars[pvk] = True
                self._run("""
                    MATCH (pt:PanelTemplate {template_key:$tk})
                    MERGE (pv:PanelVariant {variant_key:$vk})
                    ON CREATE SET pv.name=$name, pv.panel_type=$ptype, pv.operation_method=$om,
                        pv.size_w=$pw, pv.size_h=$ph, 
                        pv.main_circuit_current=$mcc, pv.main_circuit_poles=$mcp
                    MERGE (pt)-[:HAS_VARIANT]->(pv)
                """, tk=ptk, vk=pvk, name=f"{p_type}-{pw}x{ph}", ptype=p_type, om=op_method,
                    pw=pw, ph=ph, mcc=pan.get("main_circuit_current"), mcp=pan.get("main_circuit_poles"))

            # -- 元件预处理 & BOM 统计 --
            parts = pan.get("parts", [])
            part_tkeys_in_panel = [part_tkey(p) for p in parts]
            from collections import Counter
            type_counts = Counter(part_tkeys_in_panel)
            # 确保签名顺序无关性
            bom_summary = sorted([f"{k}:{v}" for k, v in type_counts.items()])

            # 提取时间戳，用于推荐平局时的最新原则决胜
            import re
            m = re.search(r"(\d{13})", source)
            created_at = int(m.group(1)) if m else 0

            # 面板实例（含特征属性）
            features = extract_panel_features(pan)
            feat_sets = ", ".join([f"pi.feat_{k}=${k}" for k in features])
            cypher = f"""
                MERGE (pi:PanelInstance {{panel_id:$pid}})
                ON CREATE SET pi.name=$name, pi.size_w=$pw, pi.size_h=$ph,
                    pi.position_x=$px, pi.position_y=$py, pi.order_val=$order_val,
                    pi.bom_keys=$bom_keys,
                    pi.created_at=$created_at,
                    pi.source_file=$src
                    {', ' + feat_sets if feat_sets else ''}
            """
            params = dict(
                pid=pid, name=f"{p_type}-{pw}x{ph}-实例",
                pw=pw, ph=ph,
                px=pos[0], py=pos[1], order_val=order_val, src=source,
                bom_keys=bom_summary,
                created_at=created_at,
                **features
            )
            self._run(cypher, **params)

            # PanelVariant -> PanelInstance
            self._run("""
                MATCH (pv:PanelVariant {variant_key:$vk})
                MATCH (pi:PanelInstance {panel_id:$pid})
                MERGE (pv)-[:HAS_INSTANCE]->(pi)
            """, vk=pvk, pid=pid)

            # CabinetInstance -> PanelInstance (移除关系上的坐标冗余)
            self._run("""
                MATCH (ci:CabinetInstance {cabinet_id:$cid})
                MATCH (pi:PanelInstance {panel_id:$pid})
                MERGE (ci)-[:CONTAINS_PANEL]->(pi)
            """, cid=cid, pid=pid)

            # USED_IN (Variant 级别)
            self._run("""
                MATCH (pv:PanelVariant {variant_key:$pvk})
                MATCH (cv:CabinetVariant {variant_key:$cvk})
                MERGE (pv)-[:USED_IN]->(cv)
            """, pvk=pvk, cvk=cvk)

            panel_infos.append((pid, pos[0], pos[1], pw, ph, pan, pvk))

            # -- 元件处理 --
            part_arrange = pan.get("arrange", {})
            part_centers = []

            for part in parts:
                partid = part.get("part_id", "")
                pk = part_tkey(part)
                psw = part.get("part_width", 0)
                psh = part.get("part_height", 0)

                # 元件模板
                if pk not in self._part_tpls:
                    self._part_tpls[pk] = True
                    pt_str = part.get("part_type", "")
                    pm_str = part.get("part_model", "")
                    tname = f"{pt_str}({pm_str})" if pm_str else pt_str
                    self._run("""
                        MERGE (ptpl:PartTemplate {template_key:$tk})
                        ON CREATE SET ptpl.name=$name, ptpl.part_type=$pt,
                            ptpl.part_model=$pm, ptpl.size_w=$sw, ptpl.size_h=$sh
                    """, tk=pk, name=tname, pt=pt_str, pm=pm_str, sw=psw, sh=psh)

                # 元件实例
                parr = part_arrange.get(partid, {})
                ppos = parr.get("position", [0,0])
                rot = parr.get("rotation", 0)
                iname = f"{part.get('part_type','')}-实例"
                self._run("""
                    MERGE (pi:PartInstance {part_id:$pid})
                    ON CREATE SET pi.name=$name,
                        pi.position_x=$px, pi.position_y=$py, pi.rotation=$rot
                """, pid=partid, name=iname, px=ppos[0], py=ppos[1], rot=rot)

                # PartTemplate -> PartInstance
                self._run("""
                    MATCH (ptpl:PartTemplate {template_key:$pk})
                    MATCH (pi:PartInstance {part_id:$pid})
                    MERGE (ptpl)-[:HAS_INSTANCE]->(pi)
                """, pk=pk, pid=partid)

                # PanelInstance -> PartInstance
                self._run("""
                    MATCH (pan:PanelInstance {panel_id:$panid})
                    MATCH (pi:PartInstance {part_id:$pid})
                    MERGE (pan)-[:CONTAINS_PART]->(pi)
                """, panid=pid, pid=partid)

                cx, cy = compute_center(ppos, psw, psh)
                part_centers.append((partid, ppos[0], ppos[1], psw, psh, cx, cy))

            # 元件空间拓扑
            self._build_part_topology(part_centers)

        # 面板拓扑（同柜内面板的空间邻接）
        self._build_panel_topology(panel_infos)

    def _build_part_topology(self, parts_info):
        """元件空间拓扑：方向(left/right/above/below) + 边到边间距。"""
        n = len(parts_info)
        for i in range(n):
            pid_a, x_a, y_a, w_a, h_a, cx_a, cy_a = parts_info[i]
            for j in range(i+1, n):
                pid_b, x_b, y_b, w_b, h_b, cx_b, cy_b = parts_info[j]

                # 边到边间距
                h_gap = max(0, max(x_b - (x_a + w_a), x_a - (x_b + w_b)))  # 水平
                v_gap = max(0, max(y_b - (y_a + h_a), y_a - (y_b + h_b)))  # 垂直

                # 方向判定：从 a 看 b 在哪个方向（主方向取位移较大的轴）
                dx = cx_b - cx_a
                dy = cy_b - cy_a
                if abs(dx) >= abs(dy):
                    direction = "right" if dx > 0 else "left"
                else:
                    direction = "below" if dy > 0 else "above"

                center_dist = euclidean((cx_a, cy_a), (cx_b, cy_b))

                if center_dist <= ADJACENCY_THRESHOLD:
                    self._run("""
                        MATCH (a:PartInstance {part_id:$a}) MATCH (b:PartInstance {part_id:$b})
                        MERGE (a)-[r:ADJACENT_TO]-(b)
                        ON CREATE SET r.distance=$d, r.direction=$dir,
                            r.h_gap=$hg, r.v_gap=$vg
                    """, a=pid_a, b=pid_b, d=round(center_dist,2),
                        dir=direction, hg=round(h_gap,2), vg=round(v_gap,2))

                if abs(cy_a - cy_b) <= ROW_TOLERANCE:
                    self._run("""
                        MATCH (a:PartInstance {part_id:$a}) MATCH (b:PartInstance {part_id:$b})
                        MERGE (a)-[r:SAME_ROW]-(b)
                        ON CREATE SET r.y_diff=$yd, r.h_gap=$hg, r.direction=$dir
                    """, a=pid_a, b=pid_b, d=round(abs(cy_a-cy_b),2),
                        yd=round(abs(cy_a-cy_b),2), hg=round(h_gap,2),
                        dir="right" if cx_b > cx_a else "left")

                if abs(cx_a - cx_b) <= COLUMN_TOLERANCE:
                    self._run("""
                        MATCH (a:PartInstance {part_id:$a}) MATCH (b:PartInstance {part_id:$b})
                        MERGE (a)-[r:SAME_COLUMN]-(b)
                        ON CREATE SET r.x_diff=$xd, r.v_gap=$vg, r.direction=$dir
                    """, a=pid_a, b=pid_b, d=round(abs(cx_a-cx_b),2),
                        xd=round(abs(cx_a-cx_b),2), vg=round(v_gap,2),
                        dir="below" if cy_b > cy_a else "above")

    def _build_panel_topology(self, panel_infos):
        """面板实例之间的拓扑：支持上下堆叠和左右并排。"""
        n = len(panel_infos)
        for i in range(n):
            pid_a, x_a, y_a, w_a, h_a, _, _ = panel_infos[i]
            right_a  = x_a + w_a
            bottom_a = y_a + h_a
            for j in range(i+1, n):
                pid_b, x_b, y_b, w_b, h_b, _, _ = panel_infos[j]
                right_b  = x_b + w_b
                bottom_b = y_b + h_b

                # X 轴重叠检测
                x_overlap = max(0, min(right_a, right_b) - max(x_a, x_b))
                # Y 轴重叠检测
                y_overlap = max(0, min(bottom_a, bottom_b) - max(y_a, y_b))

                # 上下关系：X 有重叠，Y 无重叠
                if x_overlap > 0 and y_overlap == 0:
                    v_gap = max(y_a - bottom_b, y_b - bottom_a)
                    if v_gap <= PANEL_ADJACENCY_GAP:
                        if y_a < y_b:
                            self._run("""
                                MATCH (a:PanelInstance {panel_id:$a})
                                MATCH (b:PanelInstance {panel_id:$b})
                                MERGE (a)-[r:ADJACENT_PANEL]->(b)
                                ON CREATE SET r.gap=$gap, r.direction='below', r.x_overlap=$xo
                            """, a=pid_a, b=pid_b, gap=round(v_gap,2), xo=round(x_overlap,2))
                        else:
                            self._run("""
                                MATCH (a:PanelInstance {panel_id:$a})
                                MATCH (b:PanelInstance {panel_id:$b})
                                MERGE (b)-[r:ADJACENT_PANEL]->(a)
                                ON CREATE SET r.gap=$gap, r.direction='below', r.x_overlap=$xo
                            """, a=pid_a, b=pid_b, gap=round(v_gap,2), xo=round(x_overlap,2))

                # 左右关系：Y 有重叠，X 无重叠
                elif y_overlap > 0 and x_overlap == 0:
                    h_gap = max(x_a - right_b, x_b - right_a)
                    if h_gap <= PANEL_ADJACENCY_GAP:
                        if x_a < x_b:
                            self._run("""
                                MATCH (a:PanelInstance {panel_id:$a})
                                MATCH (b:PanelInstance {panel_id:$b})
                                MERGE (a)-[r:ADJACENT_PANEL]->(b)
                                ON CREATE SET r.gap=$gap, r.direction='right', r.y_overlap=$yo
                            """, a=pid_a, b=pid_b, gap=round(h_gap,2), yo=round(y_overlap,2))
                        else:
                            self._run("""
                                MATCH (a:PanelInstance {panel_id:$a})
                                MATCH (b:PanelInstance {panel_id:$b})
                                MERGE (b)-[r:ADJACENT_PANEL]->(a)
                                ON CREATE SET r.gap=$gap, r.direction='right', r.y_overlap=$yo
                            """, a=pid_a, b=pid_b, gap=round(h_gap,2), yo=round(y_overlap,2))

    def print_stats(self):
        print("\n📊 图数据库统计：")
        with self.driver.session(database=self.db) as s:
            for label in ["CabinetTemplate","CabinetVariant","CabinetInstance",
                          "PanelTemplate","PanelVariant","PanelInstance",
                          "PartTemplate","PartInstance"]:
                r = s.run(f"MATCH (n:{label}) RETURN count(n) AS c")
                print(f"  {label:20s}: {r.single()['c']}")
            print()
            for rel in ["HAS_VARIANT","HAS_INSTANCE","CONTAINS_PANEL","CONTAINS_PART",
                        "ADJACENT_TO","SAME_ROW","SAME_COLUMN","ADJACENT_PANEL",
                        "USED_IN"]:
                r = s.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c")
                print(f"  [{rel:25s}]: {r.single()['c']}")


def main():
    parser = argparse.ArgumentParser(description="低压开关柜 scheme → Neo4j 图数据库")
    parser.add_argument("--uri", default="neo4j://127.0.0.1:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default="a3213964")
    parser.add_argument("--database", default="lowvoltagecabinet")
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("  低压开关柜 scheme → Neo4j 图数据库构建")
    print("=" * 60)
    print(f"  数据目录: {DATA_DIR}")

    schemes = load_schemes()
    if not schemes:
        print("未找到 scheme 文件"); return
    print(f"✓ 已加载 {len(schemes)} 个 scheme 文件\n")

    builder = Neo4jBuilder(args.uri, args.user, args.password, args.database)
    try:
        builder.create_constraints()
        if args.clear:
            builder.clear()

        print("\n写入图数据...")
        for i, sch in enumerate(schemes, 1):
            src = sch.get("_source", "")
            cabs = len(sch.get("cabinets", []))
            print(f"  [{i}/{len(schemes)}] {src} ({cabs} 个柜体)")
            builder.ingest_scheme(sch)

        builder.print_stats()
        print("\n✅ 图数据库构建完成！")
    except Exception as e:
        print(f"\n❌ 失败: {e}")
        raise
    finally:
        builder.close()


if __name__ == "__main__":
    main()
