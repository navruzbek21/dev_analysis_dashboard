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
