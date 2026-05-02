import json
import sys
import os
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# 假设这些是你已有的领域类和配置
from layout_rag.domain.new_distribution_box import NewDistributionBoxDomain
from layout_rag.core.feature_extractor import FeatureExtractor
from layout_rag.core.vector_store import VectorStore
from layout_rag.config import get_domain_paths, get_feature_schema, load_part_types
from layout_rag.core.neo4j_client import Neo4jClient, neo4j_client

# ==========================================
# 2. 辅助工具函数：安全解析与聚类
# ==========================================
def safe_float(val, default=0.0):
    """安全地将各种可能的空值或非法字符串转换为浮点数"""
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def group_components_by_y_with_tolerance(parts, arrange, tolerance=2.0):
    """
    带容差的 Y 坐标聚类算法，将元件分排 (Rail)。
    tolerance: 允许的Y坐标偏差范围（例如 2.0 mm 依然算作同一排）
    """
    parts_with_pos = []
    for p in parts:
        pid = p.get("part_id")
        pos = arrange.get(pid, {}).get("position", [0.0, 0.0])
        # 记录原始的部件信息以及提取出的X,Y坐标
        parts_with_pos.append({"part": p, "x": safe_float(pos[0]), "y": safe_float(pos[1])})

    # 根据 Y 坐标从大到小排序 (若画布原点在左上角导致 Y 向下递增，可改为 reverse=False)
    parts_with_pos.sort(key=lambda item: item["y"], reverse=True)

    rails = []
    if not parts_with_pos:
        return rails

    current_rail = [parts_with_pos[0]]
    current_y_avg = parts_with_pos[0]["y"]

    for item in parts_with_pos[1:]:
        # 如果 Y 坐标的差值在容差范围内，认为在同一排
        if abs(item["y"] - current_y_avg) <= tolerance:
            current_rail.append(item)
        else:
            rails.append(current_rail)
            current_rail = [item]
            current_y_avg = item["y"]
            
    if current_rail:
        rails.append(current_rail)

    # 每一排内部按 X 坐标从小到大排序
    for rail in rails:
        rail.sort(key=lambda item: item["x"])

    return rails


# ==========================================
# 3. 核心业务类：PLM 图数据导入器
# ==========================================
class PLMGraphImporter:
    def __init__(self, db_client: Neo4jClient):
        self.db_client = db_client
        
        # 初始化特征提取与编码组件
        self.domain = NewDistributionBoxDomain()
        paths = get_domain_paths(self.domain)
        self.schema = get_feature_schema(self.domain, paths["data_dir"])
        self.part_types = load_part_types(self.domain, paths["data_dir"])
        
        self.extractor = FeatureExtractor(self.domain, self.part_types, self.schema)
        self.vector_store = VectorStore(self.schema)
        self.vector_store_path = str(paths["vector_store_path"])
        
        try:
            # 修复：只加载不保存，避免初始化时误覆盖有效标尺
            self.vector_store.load_ruler(self.vector_store_path)
            self.encoder_ready = True
            
            # --- 通过提取“空数据”来动态推断向量维度，并创建索引 ---
            self._init_vector_index()
            
        except FileNotFoundError:
            print("提示：标尺文件 (store.json) 暂不存在，将在本次导入的阶段一自动生成。")
            self.encoder_ready = False

    def _init_vector_index(self):
        """使用空数据样本探测特征提取器的实际输出维度，并通知DB建立索引"""
        dummy_sample = {
            "schema": {
                "cabinet_width": 0, "cabinet_height": 0, "cabinet_depth": 0,
                "install_type": "", "inline_mode": "", "fixup_type": "",
                "door_type": "", "cable_in_out_type": "", "box_classify": "",
                "panel_size": [0, 0],
                "parts": []
            }
        }
        try:
            feature_dict = self.extractor.extract(dummy_sample)
            full_dim = len(self.vector_store.encode_for_neo4j(feature_dict))
            bom_dim = self.vector_store.bom_dimension
            non_bom_dim = self.vector_store.non_bom_dimension

            print(f"[初始化] 向量维度 — 全量: {full_dim}, BOM: {bom_dim}, 非BOM: {non_bom_dim}")
            self.db_client.create_vector_index_if_not_exists(full_dim, bom_dim, non_bom_dim)
        except Exception as e:
            print(f"[警告] 自动探测特征向量维度失败，将不会自动创建索引。原因: {e}")

    def import_plm_data(self, data):
        """解析并使用批处理显式事务导入全量数据"""
        box_data = self._prepare_box_data(data)
        if not box_data["box_id"]:
            print("数据中缺少箱体 UUID，跳过导入。")
            return
            
        panels_data, rails_data, comps_data, rel_below_data, rel_left_data = self._prepare_internal_data(data)

        # 传递给事务执行器
        self.db_client.execute_write_transaction(
            self._execute_batch_import_tx, 
            box_data, panels_data, rails_data, comps_data, rel_below_data, rel_left_data
        )
        print(f"[SUCCESS] 配电箱 {box_data['box_id']} (包含其面板拓扑) 批量导入成功！")
        
    def build_co_occurrence_graph(self, min_freq=2):
        """
        利用 Neo4j 内部运算，在 ComponentTemplate 之间建立频繁共现边。
        min_freq: 最小共现阈值。只为在同一面板中共同出现超过该次数的元件型号建立关联。
        """
        print(f"\n--- 阶段三：正在图数据库内挖掘并建立元件共现关系 (阈值 >= {min_freq}) ---")

        # Cypher 逻辑解析：
        # 1. 找到同一个 PanelInstance 下所有的 ComponentInstance 及其对应的 ComponentTemplate
        # 2. WHERE t1.Name < t2.Name 确保只计算一次 A-B 组合，避免重复和自环
        # 3. 按 Name 聚合防止冗余节点分流，统计共同出现的面板数
        # 4. 过滤掉低于阈值的组合
        # 5. 在两个模板之间建立 CO_OCCURS_WITH 边，并记录频次权重
        cypher = """
        MATCH (t1:ComponentTemplate)<-[:INSTANCE_OF]-(c1:ComponentInstance)<-[:CONTAINS]-(:Rail)<-[:CONTAINS]-(p:PanelInstance)
        MATCH (p)-[:CONTAINS]->(:Rail)-[:CONTAINS]->(c2:ComponentInstance)-[:INSTANCE_OF]->(t2:ComponentTemplate)
        // 修复：使用 elementId 进行比较去重
        WHERE elementId(t1) < elementId(t2) 
        WITH t1, t2, count(DISTINCT p) AS freq
        WHERE freq >= $min_freq
        MERGE (t1)-[r:CO_OCCURS_WITH]->(t2)
        SET r.weight = freq, r.rule_type = '同一面板'
        RETURN count(r) AS created_edges
        """

        try:
            with self.db_client.driver.session(database=self.db_client.database) as session:
                result = session.run(cypher, min_freq=min_freq)
                summary = result.consume()
                created = summary.counters.relationships_created
                set_props = summary.counters.properties_set
                print(f"[SUCCESS] 共现关系网构建完成，新建 {created} 条边，更新 {set_props} 个属性。")
        except Exception as e:
            print(f"[ERROR] 构建共现关系时发生异常: {e}")
            traceback.print_exc()
            
    def _prepare_box_data(self, data):
        """解析 Box 级别的数据"""
        schema = data.get("schema", {})
        # 优先使用 cabinet_id 作为箱体唯一标识，确保同一柜子的不同面板合并
        box_id = schema.get("cabinet_id") or data.get("uuid")
        
        w = safe_float(schema.get("cabinet_width"))
        h = safe_float(schema.get("cabinet_height"))
        d = safe_float(schema.get("cabinet_depth"))
        
        door_type = schema.get("door_type", "")
        fixup_type = schema.get("fixup_type", "")
        inline_mode = schema.get("inline_mode", "")
        install_type = schema.get("install_type", "")
        
        box_cat_name = "配电箱"
        box_series = schema.get("series", "未知系列")
        bt_name = f"{box_cat_name}_{box_series}_{w}x{h}x{d}_{door_type}_{fixup_type}_{inline_mode}_{install_type}"
        bi_name = f"{bt_name}_{box_id}"

        return {
            "box_id": box_id,
            "cat_name": box_cat_name,
            "bt_name": bt_name,
            "bi_name": bi_name,
            "series": box_series,
            "w": w, "h": h, "d": d,
            "door_type": door_type, "fixup_type": fixup_type,
            "inline_mode": inline_mode, "install_type": install_type,
            "cable_in_out_type": schema.get("cable_in_out_type", ""),
            "box_classify": schema.get("box_classify", "")
        }

    def _prepare_internal_data(self, data):
        """提取 Panel, Rail 和 Component 的全量拓扑信息，用于批量写入"""
        schema = data.get("schema", {})
        box_id = schema.get("cabinet_id")
        
        panels_param = []
        rails_param = []
        comps_param = []
        rel_below_param = []
        rel_left_param = []

        panel_id = schema.get("panel_id")
        if not panel_id:
            return panels_param, rails_param, comps_param, rel_below_param, rel_left_param

        panel_cat_name = schema.get("panel_type", "未知面板")
        panel_arrange = data.get("arrange", {})
        pw, ph = schema.get("panel_size", [0, 0])
        pw, ph = safe_float(pw), safe_float(ph)
        
        pt_name = f"{panel_cat_name}_{pw}x{ph}x0"
        pi_name = f"{pt_name}_{panel_id}"

        # 特征向量编码（全量 + BOM 子集 + 非 BOM 子集）
        vector_list = []
        bom_vector_list = []
        non_bom_vector_list = []
        if self.encoder_ready:
            try:
                feature_dict = self.extractor.extract(data)
                vector_list = self.vector_store.encode_for_neo4j(feature_dict)
                bom_vector_list = self.vector_store.encode_for_neo4j(feature_dict, mode="from_bom")
                non_bom_vector_list = self.vector_store.encode_for_neo4j(feature_dict, mode="not_from_bom")
            except Exception as e:
                print(f"[警告] 特征提取失败: {e}")

        panels_param.append({
            "panel_id": panel_id,
            "cat_name": panel_cat_name,
            "pt_name": pt_name,
            "pi_name": pi_name,
            "w": pw, "h": ph,
            "vector_list": vector_list,
            "bom_vector_list": bom_vector_list,
            "non_bom_vector_list": non_bom_vector_list,
            "box_id": box_id
        })

        parts = schema.get("parts", [])
        if not parts:
            return panels_param, rails_param, comps_param, rel_below_param, rel_left_param

        # 使用带容差的 Y 轴聚类算法
        clustered_rails = group_components_by_y_with_tolerance(parts, panel_arrange, tolerance=2.0)
        total_rails = len(clustered_rails)
        prev_rail_name = None

        for rail_idx, rail_items in enumerate(clustered_rails):
            rail_name = f"{rail_idx + 1}排"
            # 均值 Y 坐标
            y_coord = sum(item["y"] for item in rail_items) / len(rail_items)
            
            rails_param.append({
                "panel_id": panel_id,
                "rail_name": rail_name,
                "rail_idx": rail_idx,
                "y_coord": round(y_coord, 2),
                "total_rails": total_rails
            })

            if prev_rail_name:
                # 获取上一排的 y 坐标 (粗略计算距离)
                prev_y = next((r["y_coord"] for r in rails_param if r["rail_name"] == prev_rail_name and r["panel_id"] == panel_id), y_coord)
                rel_below_param.append({
                    "panel_id": panel_id,
                    "prev_rail": prev_rail_name,
                    "curr_rail": rail_name,
                    "dist": abs(prev_y - y_coord)
                })
            prev_rail_name = rail_name

            # 处理 Rail 内部所在的 Components
            prev_part_id = None
            for item in rail_items:
                part = item["part"]
                part_id = part.get("part_id")
                
                comp_cat_name = part.get("part_type", "未知分类")
                comp_type = part.get("part_model", "未知型号")
                psz = part.get("part_size", [0, 0])
                cw, ch = safe_float(psz[0]), safe_float(psz[1])
                cd = 0.0
                pole = part.get("pole", "")
                current = part.get("current", "")
                
                ct_name = f"{comp_cat_name}_{comp_type}_{cw}x{ch}x{cd}_{pole}_{current}"
                ci_name = f"{ct_name}_{part_id}"

                comps_param.append({
                    "panel_id": panel_id,
                    "rail_name": rail_name,
                    "part_id": part_id,
                    "cat_name": comp_cat_name,
                    "ct_name": ct_name,
                    "ci_name": ci_name,
                    "comp_type": comp_type,
                    "w": cw, "h": ch, "d": cd,
                    "pole": pole, "current": current,
                    "x": item["x"], "y": item["y"], "z": 0.0,
                    "inline": part.get("in_line", False)
                })

                if prev_part_id:
                    prev_pos = panel_arrange.get(prev_part_id, {}).get("position", [0.0, 0.0])
                    rel_left_param.append({
                        "panel_id": panel_id,
                        "rail_name": rail_name, # 用于限制作用域
                        "prev_id": prev_part_id,
                        "curr_id": part_id,
                        "dist": round(abs(item["x"] - safe_float(prev_pos[0])), 2)
                    })
                prev_part_id = part_id

        return panels_param, rails_param, comps_param, rel_below_param, rel_left_param

    @staticmethod
    def _execute_batch_import_tx(tx, box, panels, rails, comps, rel_below, rel_left):
        """Neo4j 事务函数：使用 UNWIND 批量执行 Cypher"""
        
        # 1. 建立 Box 体系 (单次执行)
        tx.run("""
            MERGE (bc:BoxCategory {Name: $cat_name})
            MERGE (bt:BoxTemplate {Name: $bt_name})
            SET bt.Series = $series, bt.Width = $w, bt.Height = $h, bt.Depth = $d,
                bt.DoorType = $door_type, bt.FixUpType = $fixup_type, 
                bt.InLineMode = $inline_mode, bt.InstallType = $install_type,
                bt.CableInOutType = $cable_in_out_type, bt.BoxClassify = $box_classify
            MERGE (bt)-[:BELONGS_TO]->(bc)
            MERGE (bi:BoxInstance {ID: $box_id})
            SET bi.Name = $bi_name, bi.Industry = ''
            MERGE (bi)-[:INSTANCE_OF]->(bt)
        """, **box)

        # 2. 批量建立 Panel 体系
        if panels:
            tx.run("""
                UNWIND $panels AS p
                MATCH (bi:BoxInstance {ID: p.box_id})
                MERGE (pc:PanelCategory {Name: p.cat_name})
                MERGE (pt:PanelTemplate {Name: p.pt_name})
                SET pt.Width = p.w, pt.Height = p.h, pt.Depth = 0
                MERGE (pt)-[:BELONGS_TO]->(pc)
                
                MERGE (pi:PanelInstance {ID: p.panel_id})
                SET pi.Name = p.pi_name,
                    pi.FeatureVector = p.vector_list,
                    pi.BomFeatureVector = p.bom_vector_list,
                    pi.NonBomFeatureVector = p.non_bom_vector_list
                MERGE (pi)-[:INSTANCE_OF]->(pt)
                MERGE (bi)-[:CONTAINS]->(pi)
            """, panels=panels)

        # 3. 批量建立 Rail 体系
        if rails:
            tx.run("""
                UNWIND $rails AS r
                MATCH (pi:PanelInstance {ID: r.panel_id})
                MERGE (pi)-[:CONTAINS]->(rail:Rail {Name: r.rail_name})
                SET rail.RailIndex = r.rail_idx, rail.Y_Coordinate = r.y_coord, rail.TotalRails = r.total_rails
            """, rails=rails)

        # 4. 批量建立 Component 体系
        if comps:
            tx.run("""
                UNWIND $comps AS c
                // 限定匹配路径防止 ID 重复导致串台
                MATCH (pi:PanelInstance {ID: c.panel_id})-[:CONTAINS]->(rail:Rail {Name: c.rail_name})
                
                MERGE (cc:ComponentCategory {Name: c.cat_name})
                MERGE (ct:ComponentTemplate {Name: c.ct_name})
                SET ct.ModelType = c.comp_type, ct.Width = c.w, ct.Height = c.h, ct.Depth = c.d, 
                    ct.Pole = c.pole, ct.Current = c.current
                MERGE (ct)-[:BELONGS_TO]->(cc)
                
                MERGE (ci:ComponentInstance {ID: c.part_id})
                SET ci.Name = c.ci_name, ci.X = c.x, ci.Y = c.y, ci.Z = c.z, ci.InLine = c.inline
                MERGE (ci)-[:INSTANCE_OF]->(ct)
                
                MERGE (rail)-[:CONTAINS]->(ci)
            """, comps=comps)

        # 5. 批量建立上下轨距拓扑 (BELOW)
        if rel_below:
            tx.run("""
                UNWIND $rel_below AS rel
                MATCH (pi:PanelInstance {ID: rel.panel_id})-[:CONTAINS]->(r1:Rail {Name: rel.prev_rail})
                MATCH (pi)-[:CONTAINS]->(r2:Rail {Name: rel.curr_rail})
                MERGE (r1)-[r:BELOW]->(r2)
                SET r.Distance = rel.dist
            """, rel_below=rel_below)

        # 6. 批量建立元件左右拓扑 (LEFT_OF)
        if rel_left:
            tx.run("""
                UNWIND $rel_left AS rel
                // 严谨的基于路径匹配，确保匹配的是当前面板、当前轨道内的特定组件
                MATCH (pi:PanelInstance {ID: rel.panel_id})-[:CONTAINS]->(:Rail {Name: rel.rail_name})-[:CONTAINS]->(prev:ComponentInstance {ID: rel.prev_id})
                MATCH (pi)-[:CONTAINS]->(:Rail {Name: rel.rail_name})-[:CONTAINS]->(curr:ComponentInstance {ID: rel.curr_id})
                MERGE (prev)-[r:LEFT_OF]->(curr)
                SET r.Distance = rel.dist
            """, rel_left=rel_left)


# ================= 测试运行 =================
if __name__ == "__main__":

    data_dir = os.path.join(os.path.dirname(__file__), '..', 'templates', 'new_distribution_box')
    
    if not os.path.exists(data_dir):
        print(f"错误: 找不到目录 {data_dir}")
        exit(1)

    # 联调期间清空历史
    neo4j_client.clear_database()
    
    importer = PLMGraphImporter(neo4j_client)

    # 预加载所有 JSON 数据
    all_data = []
    for filename in os.listdir(data_dir):
        if filename.endswith(".json"):
            file_path = os.path.join(data_dir, filename)
            with open(file_path, 'r', encoding='utf-8') as f:
                all_data.append(json.load(f))

    # ========================================================
    # 阶段一：全局特征收集与标尺拟合 (解决标尺塌陷)
    # ========================================================
    print("\n--- 阶段一：执行全量特征收集与标尺拟合 ---")
    all_raw_features = []
    for data in all_data:
        try:
            # 仅提取字典格式的特征，用于统计极值
            feature_dict = importer.extractor.extract(data)
            all_raw_features.append({"features": feature_dict})
        except Exception as e:
            print(f"[警告] 数据提取失败，跳过拟合: {e}")
            
    if all_raw_features:
        # 拟合标尺并持久化
        importer.encoder_ready = importer.vector_store.fit_and_save_ruler(importer.vector_store_path, all_raw_features)
        # 此时有了维度数据，可顺畅建立 Neo4j 的欧氏距离索引
        importer._init_vector_index()
    else:
        print("[错误] 未提取到任何有效特征，无法完成标尺拟合！")
        exit(1)

    # ========================================================
    # 阶段二：使用正确极值进行特征编码与入库
    # ========================================================
    print("\n--- 阶段二：开始执行全量数据特征编码与 Neo4j 拓扑入库 ---")
    count = 0
    for data in all_data:
        try:
            importer.import_plm_data(data)
            count += 1
        except Exception as e:
            print(f"处理失败跳过，原因: {e}")
    
    print(f"\n[OK] 导入完成，共成功处理并编码 {count} 个模板文件。")
    
    # ========================================================
    # 阶段三：挖掘图谱，构建型号之间的共现网络
    # ========================================================
    # 设定阈值：例如至少在2个以上不同的面板里共同出现过，才认为是有效的电气配套逻辑
    importer.build_co_occurrence_graph(min_freq=2)