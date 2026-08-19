import numpy as np
import pandas as pd
import pytest

from gtm_analysis import precompute_gtm_level
from litellm_console import MAX_MESSAGES, SlidingWindowRateLimiter, normalize_messages
from normalization import safe_div
from services.aggregation_service import compute_asset_year_aggregate


def test_safe_div_accepts_scalar_and_array_denominators():
    series = pd.Series([10.0, 20.0])
    assert np.isnan(safe_div(series, np.nan)).all()
    assert np.isnan(safe_div(series, 0)).all()
    result = safe_div(series, np.array([2.0, 0.0]))
    assert result[0] == 5.0 and np.isnan(result[1])
    assert safe_div(10.0, 4.0) == 2.5


def test_asset_watercut_is_production_weighted():
    # Маленькая площадь с высокой обводнённостью не должна перетягивать
    # обводнённость актива: 100*(Qж-Qн)/Qж из сумм, а не среднее wc площадей.
    source = pd.DataFrame(
        {
            "year": [2020, 2020],
            "dobycha_liq": [1000.0, 10.0],
            "dobycha_nefti": [900.0, 1.0],
            "zakachka": [0.0, 0.0],
            "dob_fond": [1.0, 1.0],
            "nagn_fond": [1.0, 1.0],
            "wc": [10.0, 90.0],
        }
    )
    aggregate = compute_asset_year_aggregate(source)
    expected = 100 * (1010.0 - 901.0) / 1010.0
    assert aggregate.loc[0, "wc"] == pytest.approx(expected)


def test_aggregate_survives_trimmed_dataset():
    source = pd.DataFrame({"year": [2020, 2021], "kin": [10.0, 12.0]})
    aggregate = compute_asset_year_aggregate(source)
    assert list(aggregate["year"]) == [2020, 2021]
    assert aggregate["dobycha_nefti"].isna().all()


def test_rate_limiter_blocks_after_burst():
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    assert all(limiter.allow("client") for _ in range(3))
    assert not limiter.allow("client")
    assert limiter.allow("other-client")


def test_normalize_messages_caps_history_and_length():
    messages = [{"role": "user", "content": f"msg-{i}" + "x" * 20000} for i in range(MAX_MESSAGES + 10)]
    normalized = normalize_messages(messages, "fallback")
    assert len(normalized) == MAX_MESSAGES
    assert all(len(item["content"]) <= 16000 for item in normalized)
    assert normalize_messages(None, "fallback") == [{"role": "user", "content": "fallback"}]


def test_precompute_gtm_level_keeps_business_rules():
    # Правила прежней построчной реализации calc_delta_per_gtm:
    # база — среднее за месяцы -3..-1; при истории глубже -36 база обнуляется;
    # без месяцев после ГТМ прирост не определён.
    frame = pd.DataFrame(
        [
            # Скважина A: обычная база и факт 1-3 мес.
            {"well": "A", "gtm_date": "2021-01-01", "month_offset": -3, "qliq": 10.0, "qoil": 5.0, "gtm_year": 2021},
            {"well": "A", "gtm_date": "2021-01-01", "month_offset": -1, "qliq": 14.0, "qoil": 7.0, "gtm_year": 2021},
            {"well": "A", "gtm_date": "2021-01-01", "month_offset": 1, "qliq": 20.0, "qoil": 11.0, "gtm_year": 2021},
            {"well": "A", "gtm_date": "2021-01-01", "month_offset": 2, "qliq": 22.0, "qoil": 13.0, "gtm_year": 2021},
            # Скважина B: далёкая история => база 0.
            {"well": "B", "gtm_date": "2021-01-01", "month_offset": -40, "qliq": 50.0, "qoil": 30.0, "gtm_year": 2021},
            {"well": "B", "gtm_date": "2021-01-01", "month_offset": 1, "qliq": 8.0, "qoil": 4.0, "gtm_year": 2021},
            # Скважина C: нет данных после ГТМ => прирост NaN.
            {"well": "C", "gtm_date": "2021-01-01", "month_offset": -1, "qliq": 9.0, "qoil": 3.0, "gtm_year": 2021},
        ]
    )
    frame["gtm_date"] = pd.to_datetime(frame["gtm_date"])

    level = precompute_gtm_level(frame).set_index("well")

    assert level.loc["A", "Δqliq"] == pytest.approx(21.0 - 12.0)
    assert level.loc["A", "Δqoil"] == pytest.approx(12.0 - 6.0)
    assert level.loc["B", "Δqoil"] == pytest.approx(4.0)
    assert np.isnan(level.loc["C", "Δqoil"])
