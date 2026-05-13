import pytest
import numpy as np
from layout_rag.core.vector_store import VectorStore

@pytest.fixture
def schema():
    return {
        "f_cont": {"type": "continuous", "weight": 1.0, "min": 0.0, "max": 100.0},
        "f_count": {"type": "count", "weight": 4.0, "max_count": 10},
        "f_bool": {"type": "boolean", "weight": 2.0},
        "f_bom": {"type": "boolean", "weight": 1.0, "from_bom": True}
    }

@pytest.fixture
def store(schema):
    return VectorStore(schema)

def test_vector_store_init_fail():
    bad_schema = {"f1": {"type": "continuous", "weight": 1.0}}
    with pytest.raises(ValueError, match="缺少边界定义"):
        VectorStore(bad_schema)

def test_encode_for_neo4j(store):
    feats = {
        "f_cont": 50.0,    # norm = 0.5, weight=1.0 -> 0.5 * sqrt(1) = 0.5
        "f_count": 2,     # log1p(2)/log1p(10) = 1.0986 / 2.3979 approx 0.458
                           # weight=4.0 -> 0.458 * sqrt(4) = 0.916
        "f_bool": 1.0,    # norm = 1.0, weight=2.0 -> 1.0 * sqrt(2) approx 1.414
        "f_bom": 0.0      # norm = 0.0, weight=1.0 -> 0.0
    }
    
    vec = store.encode_for_neo4j(feats)
    assert len(vec) == 4
    assert vec[0] == pytest.approx(0.5)
    
    expected_count = (np.log1p(2) / np.log1p(10)) * np.sqrt(4.0)
    assert vec[1] == pytest.approx(expected_count)
    
    assert vec[2] == pytest.approx(np.sqrt(2.0))
    assert vec[3] == 0.0

def test_encode_mode_from_bom(store):
    feats = {"f_bom": 1.0, "f_bool": 1.0}
    # f_bom is from_bom
    vec = store.encode_for_neo4j(feats, mode="from_bom")
    assert len(vec) == 1
    assert vec[0] == pytest.approx(1.0) # weight 1.0, val 1.0

def test_get_feature_ranges(store):
    ranges = store.get_feature_ranges()
    assert ranges["f_cont"] == 100.0
    assert ranges["f_count"] == pytest.approx(np.log1p(10))
