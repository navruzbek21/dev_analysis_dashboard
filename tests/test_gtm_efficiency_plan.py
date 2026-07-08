import pandas as pd

from gtm_analysis import EFFICIENCY_PLAN, apply_efficiency_algorithm, precompute_gtm_level


def test_plan_efficiency_uses_average_qoil_after_gtm_against_plan_threshold():
    df = pd.DataFrame(
        [
            {"well": "w1", "gtm_date": "2024-01-01", "month_offset": -1, "qliq": 10, "qoil": 8, "qoil_plan": 10, "gtm_year": 2024},
            {"well": "w1", "gtm_date": "2024-01-01", "month_offset": 1, "qliq": 10, "qoil": 9.2, "qoil_plan": 10, "gtm_year": 2024},
            {"well": "w1", "gtm_date": "2024-01-01", "month_offset": 2, "qliq": 10, "qoil": 9.1, "qoil_plan": 10, "gtm_year": 2024},
            {"well": "w1", "gtm_date": "2024-01-01", "month_offset": 3, "qliq": 10, "qoil": 9.0, "qoil_plan": 10, "gtm_year": 2024},
            {"well": "w2", "gtm_date": "2024-01-01", "month_offset": -1, "qliq": 10, "qoil": 8, "qoil_plan": 10, "gtm_year": 2024},
            {"well": "w2", "gtm_date": "2024-01-01", "month_offset": 1, "qliq": 10, "qoil": 8.9, "qoil_plan": 10, "gtm_year": 2024},
            {"well": "w2", "gtm_date": "2024-01-01", "month_offset": 2, "qliq": 10, "qoil": 9.0, "qoil_plan": 10, "gtm_year": 2024},
            {"well": "w2", "gtm_date": "2024-01-01", "month_offset": 3, "qliq": 10, "qoil": 9.0, "qoil_plan": 10, "gtm_year": 2024},
        ]
    )
    df["gtm_date"] = pd.to_datetime(df["gtm_date"])

    gtm_level = precompute_gtm_level(df).sort_values("well").reset_index(drop=True)

    assert gtm_level["qoil_after_1_3"].round(3).tolist() == [9.1, 8.967]
    assert gtm_level["effective_plan"].tolist() == [1, 0]
    assert apply_efficiency_algorithm(gtm_level, EFFICIENCY_PLAN)["effective"].tolist() == [1, 0]


def test_gtm_filter_df_filters_block_when_present():
    from gtm_analysis import filter_df

    df = pd.DataFrame(
        {
            "направление": ["A", "A", "B"],
            "plosh": ["p1", "p1", "p1"],
            "mest": ["m1", "m1", "m1"],
            "block": ["1", "2", "1"],
            "value": [10, 20, 30],
        }
    )

    filtered = filter_df(df, direction="A", plosh="p1", mest="m1", block="2")

    assert filtered["value"].tolist() == [20]
