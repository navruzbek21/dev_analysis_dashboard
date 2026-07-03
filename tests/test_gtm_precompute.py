import numpy as np
import pandas as pd

import gtm_analysis


def test_precompute_gtm_level_matches_group_apply_business_rules():
    df = pd.DataFrame(
        [
            {
                "well": "A",
                "gtm_date": "2024-01-01",
                "month_offset": -3,
                "qliq": 10,
                "qoil": 5,
                "gtm_year": 2024,
                "назнач_скв_факт": "Добывающая",
                "направление": "ГРП",
                "mest": "M1",
                "plosh": "P1",
                "qoil_plan": 8,
            },
            {
                "well": "A",
                "gtm_date": "2024-01-01",
                "month_offset": -2,
                "qliq": 12,
                "qoil": 6,
                "gtm_year": 2024,
                "назнач_скв_факт": "Добывающая",
                "направление": "ГРП",
                "mest": "M1",
                "plosh": "P1",
                "qoil_plan": 8,
            },
            {
                "well": "A",
                "gtm_date": "2024-01-01",
                "month_offset": 1,
                "qliq": 20,
                "qoil": 9,
                "gtm_year": 2024,
                "назнач_скв_факт": "Добывающая",
                "направление": "ГРП",
                "mest": "M1",
                "plosh": "P1",
                "qoil_plan": 8,
            },
            {
                "well": "A",
                "gtm_date": "2024-01-01",
                "month_offset": 2,
                "qliq": 22,
                "qoil": 10,
                "gtm_year": 2024,
                "назнач_скв_факт": "Добывающая",
                "направление": "ГРП",
                "mest": "M1",
                "plosh": "P1",
                "qoil_plan": 8,
            },
            {
                "well": "B",
                "gtm_date": "2024-02-01",
                "month_offset": -5,
                "qliq": 10,
                "qoil": 7,
                "gtm_year": 2024,
                "назнач_скв_факт": "Нагнетательная",
                "направление": "ОПЗ",
                "mest": "M2",
                "plosh": "P2",
                "qoil_plan": 20,
            },
            {
                "well": "B",
                "gtm_date": "2024-02-01",
                "month_offset": 4,
                "qliq": 13,
                "qoil": 8,
                "gtm_year": 2024,
                "назнач_скв_факт": "Нагнетательная",
                "направление": "ОПЗ",
                "mest": "M2",
                "plosh": "P2",
                "qoil_plan": 20,
            },
            {
                "well": "C",
                "gtm_date": "2024-03-01",
                "month_offset": -40,
                "qliq": 99,
                "qoil": 99,
                "gtm_year": 2024,
                "назнач_скв_факт": "Добывающая",
                "направление": "КРС",
                "mest": "M3",
                "plosh": "P3",
                "qoil_plan": 1,
            },
            {
                "well": "C",
                "gtm_date": "2024-03-01",
                "month_offset": 1,
                "qliq": 3,
                "qoil": 2,
                "gtm_year": 2024,
                "назнач_скв_факт": "Добывающая",
                "направление": "КРС",
                "mest": "M3",
                "plosh": "P3",
                "qoil_plan": 1,
            },
        ]
    )
    df["gtm_date"] = pd.to_datetime(df["gtm_date"])

    expected = (
        df.groupby(["well", "gtm_date"], dropna=False, sort=False, group_keys=False)
        .apply(gtm_analysis.calc_delta_per_gtm)
        .reset_index()
    )
    expected["effective"] = np.where(expected["Δqoil"] > 0, 1, 0)
    expected["effective_plan"] = np.where(expected["qoil_after_1_3"] > 0.9 * expected["qoil_plan"], 1, 0)
    expected = expected.rename(columns={"назнач_скв_факт": "назначение"})

    actual = gtm_analysis.precompute_gtm_level(df)
    columns = ["well", "Δqliq", "Δqoil", "qoil_after_1_3", "qoil_plan", "effective", "effective_plan"]

    pd.testing.assert_frame_equal(expected[columns], actual[columns], check_dtype=False)
