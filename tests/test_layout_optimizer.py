import pytest
from layout_rag.core.layout_optimizer import LayoutOptimizer
from layout_rag.domain.base import BusinessDomain

class StubDomain(BusinessDomain):
    @property
    def domain_key(self) -> str: return "stub"
    def get_part_types(self) -> list[str]: return []
    @property
    def feature_schema_def(self) -> dict: return {}
    def extract_features(self, layout_json: dict) -> dict: return {}
    def ui_schema(self) -> dict: return {}
    @property
    def default_panel_size(self) -> list[float]: return [500.0, 800.0]

@pytest.fixture
def optimizer():
    domain = StubDomain()
    return LayoutOptimizer(domain, margin=10.0, element_gap=5.0)

def test_compute_scale(optimizer):
    # curr [500, 800], tpl [250, 400] -> scale [2.0, 2.0]
    sx, sy = optimizer._compute_scale([500.0, 800.0], [250.0, 400.0])
    assert sx == 2.0
    assert sy == 2.0

    # Test division by zero fallback
    sx, sy = optimizer._compute_scale([500.0, 800.0], [0.0, 0.0])
    assert sx == 1.0
    assert sy == 1.0

def test_clamp_target(optimizer):
    # panel=100, part=20, margin=10 -> range [10, 100-20-10=70]
    assert optimizer._clamp_target(5.0, 20.0, 100.0) == 10.0
    assert optimizer._clamp_target(50.0, 20.0, 100.0) == 50.0
    assert optimizer._clamp_target(80.0, 20.0, 100.0) == 70.0

def test_physical_size():
    # 0 deg: (w, h)
    assert LayoutOptimizer._physical_size(10.0, 20.0, 0) == (10.0, 20.0)
    # 90 deg: (h, w)
    assert LayoutOptimizer._physical_size(10.0, 20.0, 90) == (20.0, 10.0)
    # 270 deg: (h, w)
    assert LayoutOptimizer._physical_size(10.0, 20.0, 270) == (20.0, 10.0)
    # 180 deg: (w, h)
    assert LayoutOptimizer._physical_size(10.0, 20.0, 180) == (10.0, 20.0)

def test_compute_match_diff():
    # Identical
    diff = LayoutOptimizer._compute_match_diff(100, 200, 100, 200)
    assert diff == 0.0

    # Different size, same ratio
    diff1 = LayoutOptimizer._compute_match_diff(100, 200, 50, 100)
    # Different ratio
    diff2 = LayoutOptimizer._compute_match_diff(100, 200, 100, 100)
    assert diff2 > diff1

def test_match_parts_to_template(optimizer):
    curr_parts = [
        {"part_id": "p1", "part_type": "T1", "part_size": [50, 50]},
        {"part_id": "p2", "part_type": "T1", "part_size": [100, 100]},
    ]
    tpl_parts = [
        {"part_id": "tp1", "part_type": "T1", "part_size": [60, 60]},
    ]
    tpl_arrange = {
        "tp1": {"position": [10, 10], "rotation": 0}
    }
    # scale_x=1, scale_y=1, panel_size=[500, 800]
    matched, unmatched = optimizer._match_parts_to_template(
        curr_parts, tpl_parts, tpl_arrange, 1.0, 1.0, [500, 800]
    )
    
    # p2 is larger, so it should match tp1 (sorted by area)
    assert len(matched) == 1
    assert matched[0]["id"] == "p2"
    assert len(unmatched) == 1
    assert unmatched[0]["id"] == "p1"

def test_solve_layout_simple(optimizer):
    all_parts = [
        {
            "id": "p1", "type": "T1", "w": 50.0, "h": 50.0, 
            "target_x": 10.0, "target_y": 10.0, "weight": 1000
        },
        {
            "id": "p2", "type": "T1", "w": 50.0, "h": 50.0, 
            "target_x": 12.0, "target_y": 10.0, "weight": 1000
        }
    ]
    # These two overlap if at targets. solver should push p2 away.
    # margin=10, gap=5.
    # p1 at [10, 10], p2 should be at least [10+50+5, 10] = [65, 10]
    res = optimizer._solve_layout(all_parts, 500, 800)
    
    assert "p1" in res
    assert "p2" in res
    p1_pos = res["p1"]["position"]
    p2_pos = res["p2"]["position"]
    
    # Check non-overlap
    assert (p2_pos[0] >= p1_pos[0] + 50 + 5) or (p1_pos[0] >= p2_pos[0] + 50 + 5) or \
           (p2_pos[1] >= p1_pos[1] + 50 + 5) or (p1_pos[1] >= p2_pos[1] + 50 + 5)

def test_solve_layout_impossible(optimizer):
    all_parts = [
        {"id": "p1", "type": "T1", "w": 600.0, "h": 50.0, "target_x": 0.0, "target_y": 0.0, "weight": 1}
    ]
    with pytest.raises(ValueError, match="尺寸.*超出面板限制"):
        optimizer._solve_layout(all_parts, 500, 800)

def test_assign_cursor_target(optimizer):
    part = {"w": 50, "h": 50, "id": "p2"}
    anchors = [{"id": "p1", "w": 50, "h": 50, "target_x": 10, "target_y": 10}]
    cursors = {}
    panel_size = [500, 800]
    
    optimizer._assign_cursor_target(part, anchors, cursors, panel_size)
    
    # Next to p1 (10 + 50 = 60)
    assert part["target_x"] == 60
    assert part["target_y"] == 10
    assert "p1" in cursors
    assert cursors["p1"]["x"] == 60 + 50 # 110

def test_assign_cursor_target_overflow(optimizer):
    # margin = 10
    part = {"w": 450, "h": 50, "id": "p2"}
    # p1 at 10,10 width 100. next x = 110. 110 + 450 = 560 > 500 - 10 = 490
    anchors = [{"id": "p1", "w": 100, "h": 50, "target_x": 10, "target_y": 10}]
    cursors = {}
    panel_size = [500, 800]
    
    optimizer._assign_cursor_target(part, anchors, cursors, panel_size)
    
    # Should wrap to next line
    assert part["target_x"] == 10 # margin
    assert part["target_y"] == 10 + 50 + 5 # y + row_max_h + gap

def test_find_cluster_anchor(optimizer):
    part = {"w": 50, "h": 50}
    anchors = [
        {"id": "p1", "w": 50, "h": 50, "target_y": 10},
        {"id": "p2", "w": 50, "h": 50, "target_y": 100},
        {"id": "p3", "w": 50, "h": 50, "target_y": 10}, # p1 and p3 are in the same cluster
    ]
    best = optimizer._find_cluster_anchor(part, anchors, 800)
    assert best["id"] in ["p1", "p3"]

def test_build_fallback_type_index(optimizer):
    fallback_templates = [{
        "uuid": "tpl1",
        "schema": {"parts": [{"part_id": "tp1", "part_type": "T1", "part_size": [50, 50]}], "panel_size": [500, 800]},
        "arrange": {"tp1": {"position": [10, 10]}}
    }]
    index = optimizer._build_fallback_type_index(fallback_templates, [500, 800])
    assert "T1" in index
    assert index["T1"][0]["candidate_id"] == "tpl1:tp1"
    assert index["T1"][0]["target_x"] == 10
