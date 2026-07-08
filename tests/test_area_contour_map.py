from types import SimpleNamespace

import pandas as pd

import app

from app import AREA_COL_YEAR, area_metric_contour_map, main_tab_layout


def _collect_component_ids(component):
    ids = []
    if isinstance(component, (list, tuple)):
        for child in component:
            ids.extend(_collect_component_ids(child))
        return ids
    component_id = getattr(component, "id", None)
    if component_id:
        ids.append(component_id)
    children = getattr(component, "children", None)
    if children is not None:
        ids.extend(_collect_component_ids(children))
    return ids


def test_main_tab_has_single_left_area_map_and_no_legacy_bottom_histogram():
    ids = _collect_component_ids(main_tab_layout())

    assert ids.count("main-area-map") == 1
    assert "main-bar" not in ids
    assert ids.index("main-area-map") < ids.index("main-change") < ids.index("main-line") < ids.index("main-cross")


def test_main_callback_outputs_match_visible_main_tab_graphs():
    main_callback_key = next(
        key for key in app.app.callback_map
        if "main-area-map.figure" in key and "main-cross.figure" in key
    )

    assert main_callback_key == "..main-area-map.figure...main-change.figure...main-line.figure...main-cross.figure.."


def test_area_metric_contour_map_fills_irap_contour_and_labels_value(tmp_path, monkeypatch):
    contour_dir = tmp_path / "area_contours"
    contour_dir.mkdir()
    (contour_dir / "Площадь 1.asc").write_text(
        "0 0 0\n10 0 0\n10 5 0\n0 5 0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(app, "settings", SimpleNamespace(area_contours_dir=str(contour_dir)))
    app._load_area_contours.cache_clear()

    data = pd.DataFrame(
        {
            AREA_COL_YEAR: ["Площадь 1", "Площадь 1"],
            "year": [2025, 2026],
            "dobycha_nefti": [10.0, 25.0],
        }
    )

    fig = area_metric_contour_map(data, "dobycha_nefti")

    area_trace = next(trace for trace in fig.data if trace.name == "Площадь 1")
    assert area_trace.fill == "toself"
    assert area_trace.fillcolor
    assert fig.layout.annotations[0].text == "Площадь 1<br>25"


def test_area_metric_contour_map_aggregates_current_year_by_area(tmp_path, monkeypatch):
    contour_dir = tmp_path / "area_contours"
    contour_dir.mkdir()
    (contour_dir / "area-a.dat").write_text("0 0 0\n1 0 0\n1 1 0\n0 1 0\n", encoding="utf-8")
    monkeypatch.setattr(app, "settings", SimpleNamespace(area_contours_dir=str(contour_dir)))
    app._load_area_contours.cache_clear()

    data = pd.DataFrame(
        {
            AREA_COL_YEAR: ["area-a", "area-a", "area-a"],
            "year": [2025, 2026, 2026],
            "zakachka": [100.0, 10.0, 15.0],
        }
    )

    fig = area_metric_contour_map(data, "zakachka")

    area_trace = next(trace for trace in fig.data if trace.name == "area-a")
    assert area_trace.customdata[0][1] == 25.0
    assert fig.layout.annotations[0].text == "area-a<br>25"


def test_area_metric_contour_map_overlays_selected_area_blocks(tmp_path, monkeypatch):
    contour_dir = tmp_path / "area_contours"
    contour_dir.mkdir()
    (contour_dir / "Альметьевская.txt").write_text("0 0 0\n4 0 0\n4 4 0\n0 4 0\n", encoding="utf-8")
    (contour_dir / "Альметьевская_1.txt").write_text("0 0 0\n2 0 0\n2 4 0\n0 4 0\n", encoding="utf-8")
    (contour_dir / "Альметьевская_2.txt").write_text("2 0 0\n4 0 0\n4 4 0\n2 4 0\n", encoding="utf-8")
    monkeypatch.setattr(app, "settings", SimpleNamespace(area_contours_dir=str(contour_dir)))
    app._load_area_contours.cache_clear()

    data = pd.DataFrame(
        {
            AREA_COL_YEAR: ["Альметьевская", "Альметьевская", "Альметьевская"],
            "block": ["all", "1", "2"],
            "year": [2026, 2026, 2026],
            "dobycha_nefti": [100.0, 40.0, 60.0],
        }
    )

    fig = area_metric_contour_map(data, "dobycha_nefti", ["Альметьевская"])

    assert {trace.name for trace in fig.data if getattr(trace, "fill", None) == "toself"} >= {"Альметьевская", "Блок 1", "Блок 2"}
    block_trace = next(trace for trace in fig.data if trace.name == "Блок 1")
    assert block_trace.customdata[0][0] == "Альметьевская"
    assert block_trace.customdata[0][3] == "1"


def test_block_contour_labels_include_reserves_pressure_and_click_marker(tmp_path, monkeypatch):
    contour_dir = tmp_path / "area_contours"
    contour_dir.mkdir()
    (contour_dir / "Area.txt").write_text("0 0 0\n4 0 0\n4 4 0\n0 4 0\n", encoding="utf-8")
    (contour_dir / "Area_1.txt").write_text("0 0 0\n2 0 0\n2 4 0\n0 4 0\n", encoding="utf-8")
    monkeypatch.setattr(app, "settings", SimpleNamespace(area_contours_dir=str(contour_dir)))
    app._load_area_contours.cache_clear()

    data = pd.DataFrame(
        {
            AREA_COL_YEAR: ["Area", "Area", "Area"],
            "block": ["all", "1", "1"],
            "year": [2026, 2025, 2026],
            "dobycha_nefti": [100.0, 20.0, 30.0],
            "niz": [1000.0, 500.0, 500.0],
            "dobycha_nefti_cum": [300.0, 100.0, 150.0],
            "niz_otbor": [0.3, 0.2, 0.35],
            "Р_пл": [120.0, 100.0, 80.0],
        }
    )

    fig = area_metric_contour_map(data, "dobycha_nefti", ["Area"])

    block_annotation = next(annotation.text for annotation in fig.layout.annotations if "Блок 1" in annotation.text)
    assert "Ост. НИЗ: 350" in block_annotation
    assert "Котб НИЗ: 0.35" in block_annotation
    assert "Ртек/Рнач: 0.80" in block_annotation
    click_trace = next(trace for trace in fig.data if getattr(trace, "mode", None) == "markers+text")
    assert [row[3] for row in click_trace.customdata] == [app.ALL_BLOCK_VALUE, "1"]


def test_contour_fill_and_labels_are_clickable(tmp_path, monkeypatch):
    contour_dir = tmp_path / "area_contours"
    contour_dir.mkdir()
    (contour_dir / "Area.txt").write_text("0 0 0\n4 0 0\n4 4 0\n0 4 0\n", encoding="utf-8")
    monkeypatch.setattr(app, "settings", SimpleNamespace(area_contours_dir=str(contour_dir)))
    app._load_area_contours.cache_clear()

    data = pd.DataFrame({AREA_COL_YEAR: ["Area"], "year": [2026], "dobycha_nefti": [100.0]})

    fig = area_metric_contour_map(data, "dobycha_nefti", [])

    contour_trace = next(trace for trace in fig.data if trace.name == "Area")
    assert contour_trace.hoveron == "fills+points"
    assert fig.layout.annotations[0].captureevents is False
    click_trace = next(trace for trace in fig.data if getattr(trace, "mode", None) == "markers+text")
    assert click_trace.marker.size == 56


def test_map_click_uses_separate_callback_to_avoid_initial_missing_tab_inputs():
    sync_key = next(key for key in app.app.callback_map if "mest-filter.options" in key and "selected-block-store.data" in key)
    sync_inputs = {item["id"] for item in app.app.callback_map[sync_key]["inputs"]}

    assert "main-area-map" not in sync_inputs
    assert "asset-block-filter" not in sync_inputs

    map_callback = next(
        meta for meta in app.app.callback_map.values()
        if any(item["id"] == "main-area-map" and item["property"] == "clickData" for item in meta["inputs"])
    )
    outputs = {str(item) for item in map_callback["output"]}
    assert {"area-filter.value", "scenario-tabs.active_tab", "selected-block-store.data"}.issubset(outputs)
