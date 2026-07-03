import pandas as pd

from app import DISPLACEMENT_TARGET_VNF, displacement_characteristic_figure


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
