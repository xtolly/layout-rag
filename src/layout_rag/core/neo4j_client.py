from neo4j import GraphDatabase
import traceback
from typing import List, Dict, Optional, cast, LiteralString

# ==========================================
# 1. 独立的基础图数据库访问类 (Neo4jClient)
# ==========================================
class Neo4jClient:
    """封装 Neo4j 连接与核心事务逻辑"""
    def __init__(self, uri, user, password, database):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database
        self.verify_connectivity()

    def verify_connectivity(self):
        try:
            self.driver.verify_connectivity()
            print(f"成功连接至 Neo4j 数据库 [{self.database}]")
        except Exception as e:
            print(f"Neo4j 连接失败: {e}")
            raise

    def close(self):
        self.driver.close()

    def clear_database(self):
        """清空当前数据库中的所有节点和关系（仅测试期使用）"""
        try:
            with self.driver.session(database=self.database) as session:
                session.run("MATCH (n) DETACH DELETE n")
            print("已清空历史数据。")
        except Exception as e:
            print("清空数据库失败！")
            traceback.print_exc()

    def create_vector_index_if_not_exists(self, full_dim: int, bom_dim: int, non_bom_dim: int):
        """强制删除并重新创建全部三个向量索引。"""
        indexes = [
            ("panel_vector_index",   "FeatureVector",      full_dim),
            ("bom_vector_index",     "BomFeatureVector",    bom_dim),
            ("non_bom_vector_index", "NonBomFeatureVector", non_bom_dim),
        ]

        with self.driver.session(database=self.database) as session:
            for index_name, prop_name, dim in indexes:
                if dim <= 0:
                    print(f"[跳过] 向量索引 '{index_name}' 维度为 0，跳过创建。")
                    continue
                # 删除旧索引
                drop_query = cast(LiteralString, "DROP INDEX " + index_name)
                try:
                    session.run(drop_query)
                    print(f"[初始化] 已删除旧的向量索引 '{index_name}'")
                except Exception:
                    pass
                # 创建新索引
                create_query = cast(LiteralString, (
                    "CREATE VECTOR INDEX " + index_name
                    + " FOR (p:PanelInstance) ON (p." + prop_name + ")"
                    + " OPTIONS { indexConfig: {"
                    + " `vector.dimensions`: " + str(dim)
                    + ", `vector.similarity_function`: 'euclidean'"
                    + "} }"
                ))
                try:
                    session.run(create_query)
                    print(f"[初始化] 向量索引 '{index_name}' (维度: {dim}, euclidean) 重建完毕。")
                except Exception as e:
                    print(f"创建向量索引 '{index_name}' 失败: {e}")
                    traceback.print_exc()

    def execute_write_transaction(self, work_func, *args, **kwargs):
        """执行显式写事务，发生异常自动回滚"""
        with self.driver.session(database=self.database) as session:
            try:
                return session.execute_write(work_func, *args, **kwargs)
            except Exception as e:
                print(f"事务执行失败并已回滚，错误信息: {e}")
                traceback.print_exc()
                raise
            
    def execute_write_query(self, query: str, parameters: dict) -> list:
        """
        执行带有重试机制的单条 Cypher 写操作查询
        
        :param query: Cypher 查询语句
        :param parameters: 查询参数字典
        :return: 查询结果记录的列表 (包含 dict)
        """
        parameters = parameters or {}
        
        # 定义一个内部的事务函数，供 execute_write 调用
        def _tx_run_query(tx, q, params):
            result = tx.run(q, params)
            # 将 Neo4j 的 Record 对象转换为标准的 Python 字典列表
            return [record.data() for record in result]

        # 确保使用 session 来管理连接
        # 注意：如果你的架构中显式指定了 database，请在 session() 中传入 database=self.database_name
        with self.driver.session() as session:
            # execute_write 会自动处理死锁重试和连接中断重连
            result_data = session.execute_write(_tx_run_query, query, parameters)
            return result_data
        
    def _record_to_layout_json(self, record) -> dict:
        """将 Neo4j 查询记录转换为标准布局 JSON 结构。"""
        raw_parts = record["raw_parts"]
        parts = []
        arrange = {}
        for rp in raw_parts:
            if not rp: continue
            pid = rp["part_id"]
            parts.append({
                "part_id": pid,
                "part_type": rp["part_type"],
                "part_size": [rp["part_width"], rp["part_height"]],
                "part_model": rp["part_model"],
                "pole": rp["pole"] if rp["pole"] else "NA",
                "current": rp["current"] if rp["current"] else "NA",
                "in_line": rp["in_line"],
                "part_type_code": 1,
                "is_guide_part": False
            })
            arrange[pid] = {"position": [rp["x"], rp["y"]], "rotation": 0}

        res = {
            "name": record["box_name"],
            "uuid": record["panel_id"],
            "schema": {
                "cabinet_id": record["box_uuid"],
                "industry": record["industry"],
                "box_classify": record["box_classify"],
                "series": record["series"],
                "cabinet_width": record["cabinet_width"],
                "cabinet_height": record["cabinet_height"],
                "cabinet_depth": record["cabinet_depth"],
                "install_type": record["install_type"],
                "inline_mode": record["inline_mode"],
                "fixup_type": record["fixup_type"],
                "door_type": record["door_type"],
                "cable_in_out_type": record["cable_in_out_type"],
                "panel_id": record["panel_id"],
                "panel_type": record["panel_type"],
                "panel_size": [record["panel_width"], record["panel_height"]],
                "parts": parts
            },
            "arrange": arrange
        }
        if "score" in record and record["score"] is not None:
            res["score"] = record["score"]
        return res

    def search_similar_panel(self, query_vector: list[float], top_n: int = 5) -> list[dict]:
        """第一步：向量搜索，仅返回 ID 和分数。"""
        # 使用 Neo4j 最新的原生 SEARCH 语法替代已废弃的 CALL 过程
        cypher_query = """
        MATCH (pi:PanelInstance)
        SEARCH pi IN (VECTOR INDEX panel_vector_index FOR $query_vector LIMIT $topn ) SCORE AS score
        RETURN pi.ID AS panel_id, score
        ORDER BY score DESC
        """
        with self.driver.session(database=self.database) as session:
            records = session.run(cypher_query, topn=top_n, query_vector=query_vector)
            return [{"panel_id": r["panel_id"], "score": r["score"]} for r in records]

    def search_similar_panel_bom(self, query_vector: list[float], top_n: int = 5) -> list[dict]:
        """使用 BOM 子向量索引搜索。"""
        cypher_query = """
        MATCH (pi:PanelInstance)
        SEARCH pi IN (VECTOR INDEX bom_vector_index FOR $query_vector LIMIT $topn) SCORE AS score
        RETURN pi.ID AS panel_id, score
        ORDER BY score DESC
        """
        with self.driver.session(database=self.database) as session:
            records = session.run(cypher_query, topn=top_n, query_vector=query_vector)
            return [{"panel_id": r["panel_id"], "score": r["score"]} for r in records]

    def search_similar_panel_non_bom(self, query_vector: list[float], top_n: int = 5) -> list[dict]:
        """使用非 BOM 子向量索引搜索。"""
        cypher_query = """
        MATCH (pi:PanelInstance)
        SEARCH pi IN (VECTOR INDEX non_bom_vector_index FOR $query_vector LIMIT $topn) SCORE AS score
        RETURN pi.ID AS panel_id, score
        ORDER BY score DESC
        """
        with self.driver.session(database=self.database) as session:
            records = session.run(cypher_query, topn=top_n, query_vector=query_vector)
            return [{"panel_id": r["panel_id"], "score": r["score"]} for r in records]

    def get_layouts_by_ids(self, panel_ids: list[str]) -> list[dict]:
        """第二步：批量获取详情。"""
        cypher_query = """
        UNWIND range(0, size($panel_ids)-1) AS idx
        WITH $panel_ids[idx] AS pid, idx
        MATCH (pi:PanelInstance) WHERE pi.ID = pid
        WITH pi, idx, null AS score

        MATCH (bi:BoxInstance)-[:CONTAINS]->(pi)
        MATCH (bi)-[:INSTANCE_OF]->(bt:BoxTemplate)
        MATCH (pi)-[:INSTANCE_OF]->(pt:PanelTemplate)-[:BELONGS_TO]->(pc:PanelCategory)

        OPTIONAL MATCH (pi)-[:CONTAINS]->(r:Rail)-[:CONTAINS]->(ci:ComponentInstance)-[:INSTANCE_OF]->(ct:ComponentTemplate)-[:BELONGS_TO]->(cc:ComponentCategory)

        WITH bi, bt, pi, pt, pc, score, idx,
            collect(CASE WHEN ci IS NOT NULL THEN {
                part_id: ci.ID,
                part_type: cc.Name,
                part_width: ct.Width,
                part_height: ct.Height,
                part_model: ct.ModelType,
                pole: ct.Pole,
                current: ct.Current,
                in_line: ci.InLine,
                x: ci.X,
                y: ci.Y
            } ELSE null END) AS raw_parts

        RETURN
            bi.Name AS box_name, bi.ID AS box_uuid, bi.Industry AS industry,
            bt.BoxClassify AS box_classify, bt.Series AS series,
            bt.Width AS cabinet_width, bt.Height AS cabinet_height, bt.Depth AS cabinet_depth,
            bt.InstallType AS install_type, bt.InLineMode AS inline_mode,
            bt.FixUpType AS fixup_type, bt.DoorType AS door_type,
            bt.CableInOutType AS cable_in_out_type,
            pi.ID AS panel_id, pc.Name AS panel_type,
            pt.Width AS panel_width, pt.Height AS panel_height,
            raw_parts, score
        ORDER BY idx
        """
        with self.driver.session(database=self.database) as session:
            records = session.run(cypher_query, panel_ids=panel_ids)
            return [self._record_to_layout_json(r) for r in records]

    def get_layout_by_id(self, panel_id: str) -> Optional[dict]:
        """获取单个详情。"""
        res = self.get_layouts_by_ids([panel_id])
        return res[0] if res else None

    def get_co_occurring_parts(self, current_models: list[str], min_weight: int = 2) -> list[dict]:
        """
        通过 CO_OCCURS_WITH 图谱查找与当前元件型号高频共现的邻居元件。
        使用 ModelType 匹配（非 Name），因为前端传入的是型号而非完整模板名。
        """
        if not current_models:
            return []
        cypher = """
        MATCH (t1:ComponentTemplate)-[r:CO_OCCURS_WITH]->(t2:ComponentTemplate)
        WHERE t1.ModelType IN $current_models AND r.weight >= $min_weight
        RETURN t2.ModelType AS part_model,
               t2.Name AS full_name,
               max(r.weight) AS max_weight
        ORDER BY max_weight DESC
        """
        with self.driver.session(database=self.database) as session:
            records = session.run(cypher, current_models=current_models, min_weight=min_weight)
            return [{"part_model": r["part_model"], "full_name": r["full_name"], "weight": r["max_weight"]} for r in records]

neo4j_client = Neo4jClient("neo4j://127.0.0.1:7687", "neo4j", "a3213964", "distributionbox")