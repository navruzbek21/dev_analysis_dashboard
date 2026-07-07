import pandas as pd

from services import data_quality_service


def _patch(monkeypatch, df):
    monkeypatch.setattr(data_quality_service.data_service, "get_filtered_year_data", lambda *args, **kwargs: df)


def test_clean_dataset_ok(monkeypatch):
    df = pd.DataFrame({"kod_ploshchadi": [1, 1], "year": [2023, 2024], "dobycha_nefti": [10, 12], "dobycha_liq": [20, 24], "dobycha_vody": [10, 12], "zakachka": [5, 6], "wc": [50, 50], "kin": [10, 12], "kiz": [20, 22], "niz_otbor": [30, 32], "dobycha_nefti_cum": [10, 22]})
    _patch(monkeypatch, df)
    assert data_quality_service.get_quality_report()["summary"]["status"] == "OK"


def test_duplicates_ranges_negative_monotonic_and_balance(monkeypatch):
    df = pd.DataFrame({"kod_ploshchadi": [1, 1, 1], "year": [2023, 2023, 2024], "dobycha_nefti": [10, -1, 12], "dobycha_liq": [40, 20, 100], "dobycha_vody": [10, 11, 10], "zakachka": [5, 6, 7], "wc": [120, 50, 50], "kin": [10, 11, 12], "kiz": [20, 21, 22], "niz_otbor": [30, 31, 32], "dobycha_nefti_cum": [20, 19, 18]})
    _patch(monkeypatch, df)
    checks = {i["check"] for i in data_quality_service.get_quality_report()["issues"]}
    assert {"duplicate_area_year", "range_0_100", "non_negative", "cumulative_monotonic", "liquid_balance"} <= checks


def test_empty_dataset(monkeypatch):
    _patch(monkeypatch, pd.DataFrame())
    assert data_quality_service.get_quality_report()["summary"]["status"] == "Нет данных"
