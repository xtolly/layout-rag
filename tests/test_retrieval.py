import json
from pathlib import Path
import pytest

from layout_rag.config import (
    build_part_color_payload,
    get_feature_schema,
    load_part_color_payload,
    load_part_types,
    save_part_color_payload,
)
from layout_rag.core.feature_extractor import FeatureExtractor
from layout_rag.core.vector_store import VectorStore



def _make_layout(
    name: str,
    uuid: str,
    panel_size: list[float],
    cabinet_type: str,
    panel_type: str,
    parts: list[dict],
) -> dict:
    return {
        "name": name,
        "uuid": uuid,
        "meta": {
            "cabinet_type": cabinet_type,
            "panel_type": panel_type,
            "panel_size": panel_size,
            "parts": parts,
        },
        "arrange": {},
    }


def _write_layout(file_path: Path, layout: dict) -> None:
    file_path.write_text(
        json.dumps(layout, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@pytest.fixture()
def sample_layout_dataset(tmp_path: Path) -> dict:
    data_dir = tmp_path / "templates"
    data_dir.mkdir()

    layout_a = _make_layout(
        name="layout_a",
        uuid="layout-a",
        panel_size=[600.0, 1600.0],
        cabinet_type="配电柜",
        panel_type="安装板",
        parts=[
            {"part_id": "a1", "part_type": "微型断路器", "part_size": [50.0, 40.0]},
            {"part_id": "a2", "part_type": "微型断路器", "part_size": [55.0, 40.0]},
            {"part_id": "a3", "part_type": "双电源自动转换开关", "part_size": [120.0, 110.0]},
        ],
    )
    layout_b = _make_layout(
        name="layout_b",
        uuid="layout-b",
        panel_size=[620.0, 1600.0],
        cabinet_type="配电柜",
        panel_type="安装板",
        parts=[
            {"part_id": "b1", "part_type": "微型断路器", "part_size": [52.0, 40.0]},
            {"part_id": "b2", "part_type": "微型断路器", "part_size": [54.0, 42.0]},
            {"part_id": "b3", "part_type": "双电源自动转换开关", "part_size": [118.0, 112.0]},
        ],
    )
    layout_c = _make_layout(
        name="layout_c",
        uuid="layout-c",
        panel_size=[800.0, 2000.0],
        cabinet_type="动力柜",
        panel_type="门板",
        parts=[
            {"part_id": "c1", "part_type": "塑壳断路器", "part_size": [180.0, 160.0]},
            {"part_id": "c2", "part_type": "浪涌保护器", "part_size": [90.0, 130.0]},
        ],
    )

    layouts = [layout_a, layout_b, layout_c]
    for layout in layouts:
        _write_layout(data_dir / f"{layout['name']}.json", layout)

    return {
        "data_dir": data_dir,
        "layouts": layouts,
    }


def _build_store(data_dir: Path, layouts: list[dict]) -> tuple[dict, list[str], FeatureExtractor, VectorStore]:
    schema = get_feature_schema(data_dir)
    part_types = load_part_types(data_dir)
    extractor = FeatureExtractor(part_types, schema)
    store = VectorStore(schema)
    store.build(
        [
            {
                "uuid": layout["uuid"],
                "source_path": str(data_dir / f"{layout['name']}.json"),
                "features": extractor.extract(layout),
            }
            for layout in layouts
        ]
    )
    return schema, part_types, extractor, store


def test_feature_schema_includes_dynamic_features(sample_layout_dataset: dict) -> None:
    schema = get_feature_schema(sample_layout_dataset["data_dir"])

    assert "count_微型断路器" in schema
    assert "count_双电源自动转换开关" in schema
    assert "count_塑壳断路器" in schema
    assert "cabinet_type_配电柜" in schema
    assert "cabinet_type_动力柜" in schema
    assert "panel_type_安装板" in schema
    assert "panel_type_门板" in schema


def test_feature_extractor_returns_expected_values(sample_layout_dataset: dict) -> None:
    layout = sample_layout_dataset["layouts"][0]
    schema, part_types, _, _ = _build_store(sample_layout_dataset["data_dir"], sample_layout_dataset["layouts"])
    extractor = FeatureExtractor(part_types, schema)

    features = extractor.extract(layout)

    assert features["panel_width"] == pytest.approx(600.0)
    assert features["panel_height"] == pytest.approx(1600.0)
    assert features["total_parts"] == 3
    assert features["unique_types"] == 2
    assert features["count_微型断路器"] == 2
    assert features["count_双电源自动转换开关"] == 1
    assert features["has_双电源"] == 1.0
    assert features["cabinet_type_配电柜"] == 1.0
    assert features["panel_type_安装板"] == 1.0
    assert features["panel_type_门板"] == 0.0


def test_vector_store_ranks_identical_layout_first(sample_layout_dataset: dict) -> None:
    layouts = sample_layout_dataset["layouts"]
    _, _, extractor, store = _build_store(sample_layout_dataset["data_dir"], layouts)
    query_layout = layouts[0]

    results = store.search(extractor.extract(query_layout), top_k=3)

    assert len(results) == 3
    assert results[0][0]["uuid"] == query_layout["uuid"]
    assert results[0][1] == pytest.approx(0.0)
    assert results[1][0]["uuid"] == layouts[1]["uuid"]
    assert results[1][1] < results[2][1]


def test_vector_store_can_save_and_load_without_changing_results(tmp_path: Path, sample_layout_dataset: dict) -> None:
    layouts = sample_layout_dataset["layouts"]
    schema, _, extractor, store = _build_store(sample_layout_dataset["data_dir"], layouts)
    query_features = extractor.extract(layouts[1])
    output_path = tmp_path / "vector_store.json"

    original_results = store.search(query_features, top_k=3)
    store.save_to_disk(str(output_path))

    loaded_store = VectorStore(schema)
    loaded_store.load_from_disk(str(output_path))
    loaded_results = loaded_store.search(query_features, top_k=3)

    assert [entry["uuid"] for entry, _ in loaded_results] == [
        entry["uuid"] for entry, _ in original_results
    ]
    assert [distance for _, distance in loaded_results] == pytest.approx(
        [distance for _, distance in original_results]
    )


def test_part_color_payload_matches_distinct_part_types(sample_layout_dataset: dict, tmp_path: Path) -> None:
    part_types = load_part_types(sample_layout_dataset["data_dir"])
    payload = build_part_color_payload(part_types)
    output_path = tmp_path / "part.color"

    assert payload["unknownColor"]
    assert set(payload["partColorMap"].keys()) == {
        "双电源自动转换开关",
        "塑壳断路器",
        "浪涌保护器",
        "微型断路器",
    }
    assert len(set(payload["partColorMap"].values())) == len(payload["partColorMap"])

    save_part_color_payload(part_types, output_path)
    loaded_payload = load_part_color_payload(output_path)

    assert loaded_payload == payload