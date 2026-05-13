import pytest
import numpy as np
from layout_rag.domain.new_distribution_box import NewDistributionBoxDomain

@pytest.fixture
def domain():
    return NewDistributionBoxDomain()

def test_domain_key(domain):
    assert domain.domain_key == "new_distribution_box"

def test_get_part_types(domain):
    types = domain.get_part_types()
    assert "微型断路器" in types
    assert len(types) > 0

def test_feature_schema_def(domain):
    schema = domain.feature_schema_def
    assert "total_parts" in schema
    assert "count_微型断路器" in schema

def test_extract_features(domain):
    layout_json = {
        "schema": {
            "parts": [
                {"part_type": "微型断路器", "part_size": [18, 80]},
                {"part_type": "微型断路器", "part_size": [18, 80]},
                {"part_type": "塑壳断路器", "part_size": [100, 150]},
            ],
            "box_classify": "配电箱",
            "series": "XM1"
        }
    }
    features = domain.extract_features(layout_json)
    
    assert features["total_parts"] == 3
    assert features["unique_types"] == 2
    assert features["count_微型断路器"] == 2
    assert features["count_塑壳断路器"] == 1
    assert features["box_classify_配电箱"] == 1.0
    assert features["series_XM1"] == 1.0
    assert features["series_HW"] == 0.0

def test_ui_schema(domain):
    ui = domain.ui_schema()
    assert "cabinet_fields" in ui
    assert "panel_fields" in ui
    assert "part_fields" in ui
