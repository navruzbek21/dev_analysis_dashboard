import pandas as pd

from app import DISPLACEMENT_TARGET_VNF, displacement_characteristic_figure
from services.aggregation_service import compute_asset_year_aggregate


def test_asset_year_aggregate_keeps_displacement_inputs():
    source = pd.DataFrame(
        {
            "year": [2020, 2020, 2021],
            "dobycha_liq": [10.0, 20.0, 30.0],
            "dobycha_nefti": [5.0, 10.0, 15.0],
            "zakachka": [3.0, 4.0, 5.0],
            "dob_fond": [1.0, 2.0, 3.0],
            "nagn_fond": [1.0, 1.0, 1.0],
            "kin": [10.0, 20.0, 30.0],
            "vnf_nak": [2.0, 4.0, 6.0],
            "vnf_tek": [1.0, 3.0, 5.0],
        }
    )

    aggregate = compute_asset_year_aggregate(source)

    assert {"kin", "vnf_nak", "vnf_tek"}.issubset(aggregate.columns)
    first_year = aggregate.loc[aggregate["year"] == 2020].iloc[0]
    assert first_year["kin"] == 15.0
    assert first_year["vnf_nak"] == 3.0
    assert first_year["vnf_tek"] == 2.0


def test_displacement_characteristic_extends_trend_to_vnf_49():
    yearly = pd.DataFrame(
        {
            "year": [2020, 2021, 2022, 2023],
            "kin": [10.0, 12.0, 14.0, 16.0],
            "vnf_nak": [10.0, 20.0, 30.0, 40.0],
        }
    )

    fig = displacement_characteristic_figure(yearly, "vnf", "ВНФ", [2020, 2023])

    target_trace = next(trace for trace in fig.data if trace.name == "Прогноз при ВНФ=49")
    assert target_trace.x[0] == DISPLACEMENT_TARGET_VNF
    assert target_trace.y[0] > yearly["kin"].max()
