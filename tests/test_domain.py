import pytest
import numpy as np
from layout_rag.domain.base import BusinessDomain

class StubDomain(BusinessDomain):
    @property
    def domain_key(self) -> str:
        return "stub"

    def get_part_types(self) -> list[str]:
        return ["TypeA", "TypeB"]

    @property
    def feature_schema_def(self) -> dict[str, dict]:
        return {
            "feat_cont": {"type": "continuous", "weight": 1.0},
            "feat_count": {"type": "count", "weight": 2.0},
            "feat_bool": {"type": "boolean", "weight": 1.0},
        }

    def extract_features(self, layout_json: dict) -> dict[str, float]:
        return {}

    def ui_schema(self) -> dict:
        return {}

def test_gower_similarity_identical():
    domain = StubDomain()
    features = {"feat_cont": 10.0, "feat_count": 5, "feat_bool": 1.0}
    ranges = {"feat_cont": 100.0, "feat_count": 10.0}
    
    sim = domain.calculate_gower_similarity(features, features, ranges)
    assert sim == pytest.approx(1.0)

def test_gower_similarity_boolean():
    domain = StubDomain()
    f1 = {"feat_bool": 1.0}
    f2 = {"feat_bool": 0.0}
    ranges = {}
    
    sim = domain.calculate_gower_similarity(f1, f2, ranges)
    assert sim == 0.0

def test_gower_similarity_continuous():
    domain = StubDomain()
    # weight = 1.0
    f1 = {"feat_cont": 10.0}
    f2 = {"feat_cont": 20.0}
    ranges = {"feat_cont": 100.0}
    
    # sim = 1 - |10-20|/100 = 0.9
    sim = domain.calculate_gower_similarity(f1, f2, ranges)
    assert sim == pytest.approx(0.9)

def test_gower_similarity_count():
    domain = StubDomain()
    # weight = 2.0
    f1 = {"feat_count": 0} # ln(1) = 0
    f2 = {"feat_count": 2} # ln(3) approx 1.0986
    ranges = {"feat_count": 2.3} # ln(10) approx 2.3
    
    # sim = 1 - |0 - 1.0986| / 2.3 approx 0.522
    sim = domain.calculate_gower_similarity(f1, f2, ranges)
    expected_sim = 1.0 - (np.log1p(2) - np.log1p(0)) / 2.3
    assert sim == pytest.approx(expected_sim)

def test_gower_similarity_mixed():
    domain = StubDomain()
    f1 = {"feat_cont": 10.0, "feat_bool": 1.0} # weights: 1.0, 1.0
    f2 = {"feat_cont": 20.0, "feat_bool": 1.0}
    ranges = {"feat_cont": 100.0}
    
    # sim_cont = 0.9, sim_bool = 1.0
    # weighted_sim = (0.9 * 1.0 + 1.0 * 1.0) / (1.0 + 1.0) = 0.95
    sim = domain.calculate_gower_similarity(f1, f2, ranges)
    assert sim == pytest.approx(0.95)
