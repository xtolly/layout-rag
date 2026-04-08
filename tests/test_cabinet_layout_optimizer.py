from layout_rag.core.cabinet_layout_optimizer import compute_cabinet_arrange


def test_tall_placeholder_prefers_bottom_right_corner() -> None:
    parts = [
        {
            "part_id": "placeholder-1",
            "part_type": "占位面板",
            "part_size": [200, 400],
        }
    ]

    arrange = compute_cabinet_arrange(1000, 2000, parts)

    assert arrange["placeholder-1"]["position"] == [800, 1600]


def test_default_panels_are_above_drawer_panels() -> None:
    parts = [
        {
            "part_id": "default-1",
            "part_type": "默认面板",
            "part_size": [800, 400],
        },
        {
            "part_id": "drawer-1",
            "part_type": "抽屉面板",
            "part_size": [800, 400],
        },
    ]

    arrange = compute_cabinet_arrange(800, 1200, parts)

    assert arrange["default-1"]["position"][1] < arrange["drawer-1"]["position"][1]