import pytest
import sys
from unittest.mock import MagicMock, patch

# Force mock neo4j and dashscope before any imports
mock_neo4j_client = MagicMock()
mock_neo4j_module = MagicMock()
sys.modules["neo4j"] = MagicMock()
sys.modules["dashscope"] = MagicMock()

# Mock the core client module
mock_client_mod = MagicMock()
mock_client_mod.neo4j_client = mock_neo4j_client
sys.modules["layout_rag.core.neo4j_client"] = mock_client_mod

# Now we can import the service
from layout_rag.services.layout_service import LayoutService
from layout_rag.domain.base import BusinessDomain

class StubDomain(BusinessDomain):
    @property
    def domain_key(self) -> str: return "stub"
    def get_part_types(self) -> list[str]: return ["T1", "T2"]
    @property
    def feature_schema_def(self) -> dict: 
        return {
            "f1": {"type": "continuous", "weight": 1.0, "display_name": "F1", "min": 0.0, "max": 1000.0},
            "f2": {"type": "boolean", "weight": 2.0, "display_name": "F2"},
        }
    def extract_features(self, layout_json: dict) -> dict: return {}
    def ui_schema(self) -> dict: return {}

@pytest.fixture
def service():
    return LayoutService(StubDomain())

def test_resolve_feature_status(service):
    # Continuous
    assert service._resolve_feature_status(100, 100, "continuous") == "green"
    assert service._resolve_feature_status(100, 110, "continuous") == "yellow"
    assert service._resolve_feature_status(100, 130, "continuous") == "orange"
    assert service._resolve_feature_status(100, 200, "continuous") == "red"

    # Boolean
    assert service._resolve_feature_status(1.0, 1.0, "boolean") == "green"
    assert service._resolve_feature_status(1.0, 0.0, "boolean") == "red"

def test_calculate_diff_info(service):
    query_parts = [
        {"part_type": "T1"},
        {"part_type": "T1"},
        {"part_type": "T2"},
    ]
    template_parts = [
        {"part_type": "T1"},
        {"part_type": "T3"},
    ]
    res = service.calculate_diff_info(query_parts, template_parts)
    assert res == {"matched": 1, "extra": 2, "missing": 1}

def test_get_feature_diff_list(service):
    q_feats = {"f1": 100.0, "f2": 1.0}
    t_feats = {"f1": 200.0, "f2": 1.0}
    
    diffs = service.get_feature_diff_list(q_feats, t_feats)
    
    assert len(diffs) == 2
    assert diffs[0]["name"] == "f2"
    assert diffs[0]["status"] == "green"
    
    assert diffs[1]["name"] == "f1"
    assert diffs[1]["status"] == "red"

def test_search_recommendations(service):
    # Mock search results
    mock_neo4j_client.search_similar_panel.return_value = [{"panel_id": "p1", "score": 0.9}]
    
    # Mock details from DB
    mock_neo4j_client.get_layouts_by_ids.return_value = [{
        "uuid": "tpl1",
        "name": "Template 1",
        "schema": {
            "panel_id": "p1",
            "parts": [{"part_type": "T1"}]
        },
        "arrange": {}
    }]
    
    project_data = {
        "schema": {
            "parts": [{"part_type": "T1"}]
        }
    }
    
    # Mock domain methods used in search
    service.domain.extract_features = MagicMock(return_value={"f1": 100.0})
    service.domain.calculate_gower_similarity = MagicMock(return_value=0.95)
    
    # We also need to mock store methods
    service.store.get_feature_ranges = MagicMock(return_value={"f1": 1000.0})
    service.store.encode_for_neo4j = MagicMock(return_value=[0.1, 0.2])

    recs = service.search_recommendations(project_data, top_k=1)
    
    assert len(recs) == 1
    assert recs[0]["uuid"] == "tpl1"
    assert recs[0]["match_score"] == 95.0

def test_apply_layout_template(service):
    # Mock template data
    mock_neo4j_client.get_layout_by_id.return_value = {
        "uuid": "tpl1",
        "schema": {"parts": [], "panel_size": [500, 800]},
        "arrange": {}
    }
    
    project_data = {
        "schema": {"parts": [], "panel_size": [500, 800]}
    }
    
    # Mock LayoutOptimizer to avoid complex logic
    with patch('layout_rag.services.layout_service.LayoutOptimizer') as MockOptimizer:
        instance = MockOptimizer.return_value
        instance.apply_layout_template.return_value = {"arrange": {"p1": {"position": [10, 10]}}}
        
        res = service.apply_layout_template("tpl1", project_data)
        
        assert "project_data" in res
        assert "template_data" in res
        assert res["project_data"]["arrange"] == {"p1": {"position": [10, 10]}}

def test_recommend_bom(service):
    # Mock Neo4j responses for multiple recall channels
    mock_neo4j_client.search_similar_panel_non_bom.return_value = [{"panel_id": "p1", "score": 0.8}]
    mock_neo4j_client.search_similar_panel_bom.return_value = [{"panel_id": "p2", "score": 0.7}]
    mock_neo4j_client.get_co_occurring_parts.return_value = [
        {"part_model": "M1", "full_name": "T1_M1", "weight": 5}
    ]
    
    mock_neo4j_client.get_layouts_by_ids.return_value = [
        {
            "uuid": "p1",
            "schema": {"parts": [{"part_type": "T1", "part_model": "M1", "part_size": [10, 10]}]}
        },
        {
            "uuid": "p2",
            "schema": {"parts": [{"part_type": "T1", "part_model": "M1", "part_size": [10, 10]}]}
        }
    ]
    
    project_data = {
        "schema": {"parts": []} # cold start
    }
    
    service.store.encode_for_neo4j = MagicMock(return_value=[0.1])
    service.domain.extract_features = MagicMock(return_value={})
    
    recs = service.recommend_bom(project_data)
    
    assert len(recs) > 0
    assert recs[0]["part_model"] == "M1"
    assert "confidence" in recs[0]
