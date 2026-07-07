import numpy as np
import pytest
import pandas as pd

from app import DISPLACEMENT_TARGET_VNF, _annual_vnf_for_displacement_x, _linear_coefficients, displacement_characteristic_figure
from services.aggregation_service import compute_asset_year_aggregate


def test_asset_year_aggregate_keeps_displacement_inputs():
    source = pd.DataFrame(
        {
            "year": [2020, 2020, 2021],
            "dobycha_liq": [10.0, 20.0, 30.0],
            "dobycha_nefti": [5.0, 10.0, 15.0],
            "dobycha_vody": [5.0, 10.0, 15.0],
            "zakachka": [3.0, 4.0, 5.0],
            "dob_fond": [1.0, 2.0, 3.0],
            "nagn_fond": [1.0, 1.0, 1.0],
            "kin": [10.0, 20.0, 30.0],
            "vnf_nak": [2.0, 4.0, 6.0],
            "vnf_tek": [1.0, 3.0, 5.0],
            "dobycha_nefti_cum": [50.0, 100.0, 150.0],
            "dobycha_vody_cum": [999.0, 999.0, 999.0],
            "dobycha_liq_cum": [150.0, 500.0, 1050.0],
        }
    )

    aggregate = compute_asset_year_aggregate(source)

    assert {"kin", "vnf_nak", "vnf_tek", "dobycha_nefti_cum", "dobycha_vody_cum", "dobycha_liq_cum"}.issubset(aggregate.columns)
    first_year = aggregate.loc[aggregate["year"] == 2020].iloc[0]
    assert first_year["kin"] == 15.0
    assert first_year["vnf_tek"] == 1.0
    assert first_year["dobycha_nefti_cum"] == 150.0
    assert first_year["dobycha_liq_cum"] == 650.0
    assert first_year["dobycha_vody_cum"] == 1998.0
    assert first_year["vnf_nak"] == first_year["dobycha_vody_cum"] / first_year["dobycha_nefti_cum"]


def test_displacement_characteristic_extends_trend_to_vnf_49_and_labels_target():
    yearly = pd.DataFrame(
        {
            "year": [2020, 2021, 2022, 2023],
            "kin": [10.0, 12.0, 14.0, 16.0],
            "vnf_nak": [10.0, 20.0, 30.0, 40.0],
            "dobycha_nefti_cum": [1000.0, 4000.0, 7000.0, 10000.0],
            "dobycha_vody_cum": [10000.0, 15000.0, 20000.0, 25000.0],
            "dobycha_liq_cum": [11000.0, 19000.0, 27000.0, 35000.0],
        }
    )

    fig = displacement_characteristic_figure(yearly, "vnf", "ВНФ", [2020, 2023])

    assert fig.layout.yaxis.title.text == "Текущий ВНФ, пласт. условия"
    target_trace = next(trace for trace in fig.data if trace.name == "Прогноз при ВНФ=49")
    assert "Годовой ВНФ=49" in target_trace.text[0]
    assert "Qн=" in target_trace.text[0]
    assert "КИН=" in target_trace.text[0]


def test_displacement_trend_line_goes_from_period_end_to_target():
    yearly = pd.DataFrame(
        {
            "year": [2020, 2021, 2022, 2023],
            "kin": [10.0, 12.0, 14.0, 16.0],
            "vnf_nak": [10.0, 20.0, 30.0, 40.0],

            "dobycha_nefti_cum": [1000.0, 4000.0, 7000.0, 10000.0],
            "dobycha_vody_cum": [10000.0, 15000.0, 20000.0, 25000.0],
            "dobycha_liq_cum": [11000.0, 19000.0, 27000.0, 35000.0],

            "dobycha_nefti_cum": [1000.0, 1200.0, 1400.0, 1600.0],
            "dobycha_vody_cum": [10000.0, 24000.0, 42000.0, 64000.0],
            "dobycha_liq_cum": [11000.0, 25200.0, 43400.0, 65600.0],

        }
    )

    fig = displacement_characteristic_figure(yearly, "maksimov", "Максимов", [2021, 2023])

    trend_trace = next(trace for trace in fig.data if trace.name == "Тренд 2021-2023 до ВНФ=49")
    target_trace = next(trace for trace in fig.data if trace.name == "Прогноз при ВНФ=49")


    trend_a, trend_b = _linear_coefficients(trend_trace.x, trend_trace.y)

    expected_oil_reservoir = yearly.loc[yearly["year"] == 2023, "dobycha_nefti_cum"].iloc[0] / 0.862 * 1.157
    assert trend_trace.x[0] == pytest.approx(expected_oil_reservoir)
    assert trend_trace.x[-1] == target_trace.x[0]
    assert target_trace.customdata[0][0] > yearly["dobycha_nefti_cum"].max()
    assert _annual_vnf_for_displacement_x(target_trace.x[0], trend_a, trend_b, "ln_water_from_oil") == pytest.approx(DISPLACEMENT_TARGET_VNF)
    assert "Годовой ВНФ=49" in target_trace.text[0]

    expected_oil_reservoir = yearly.loc[yearly["year"] == 2023, "dobycha_nefti_cum"].iloc[0] / 0.862 * 1.157
    assert trend_trace.x[0] == pytest.approx(expected_oil_reservoir)
    assert trend_trace.x[-1] == target_trace.x[0]

    assert target_trace.customdata[0][0] > yearly["dobycha_nefti_cum"].max()




def test_displacement_methods_use_original_formula_axes():
    yearly = pd.DataFrame(
        {
            "year": [2020, 2021, 2022],
            "kin": [10.0, 12.0, 14.0],
            "vnf_nak": [10.0, 20.0, 30.0],
            "dobycha_nefti_cum": [1000.0, 1200.0, 1400.0],
            "dobycha_vody_cum": [10000.0, 24000.0, 42000.0],
            "dobycha_liq_cum": [11000.0, 25200.0, 43400.0],
        }
    )

    sazonov = displacement_characteristic_figure(yearly, "sazonov", "Сазонов", [2020, 2022])
    maks = displacement_characteristic_figure(yearly, "maksimov", "Максимов", [2020, 2022])
    pirverdyan = displacement_characteristic_figure(yearly, "ln_vnf", "Пирвердян", [2020, 2022])
    kambarov = displacement_characteristic_figure(yearly, "kambarov", "Камбаров", [2020, 2022])

    taysin = displacement_characteristic_figure(yearly, "taysin_timashov", "Тайсин-Тимашов", [2020, 2022])
    nazarov = displacement_characteristic_figure(yearly, "nazarov_sipachev", "Назаров-Сипачев", [2020, 2022])
    sipachev = displacement_characteristic_figure(yearly, "sipachev_posevich", "Сипачев-Посевич", [2020, 2022])

    assert sazonov.layout.xaxis.title.text == "Vн, пласт. м³"
    assert sazonov.layout.yaxis.title.text == "LN(Vж)"
    assert maks.layout.xaxis.title.text == "Vн, пласт. м³"
    assert maks.layout.yaxis.title.text == "LN(Vв)"
    assert pirverdyan.layout.xaxis.title.text == "Vж^-0.5, пласт. м³"
    assert kambarov.layout.xaxis.title.text == "Vж^-1, пласт. м³"
    assert taysin.layout.xaxis.title.text == "Vж, пласт. м³"
    assert nazarov.layout.xaxis.title.text == "Vв = Vж − Vн, пласт. м³"
    assert sipachev.layout.xaxis.title.text == "Vж, пласт. м³"
    assert taysin.layout.yaxis.title.text == "Vв / Vн"
    assert nazarov.layout.yaxis.title.text == "Vж / Vн"
    assert sipachev.layout.yaxis.title.text == "Vж / Vн"




def test_displacement_uses_m3_inputs_and_formation_volume_coefficients():
    yearly = pd.DataFrame(
        {
            "year": [2020, 2021],
            "kin": [10.0, 12.0],
            "vnf_nak": [1.0, 1.5],
            "dobycha_nefti": [86.2, 86.2],
            "dobycha_vody": [118.5, 237.0],
            "dobycha_nefti_cum": [9999.0, 9999.0],
            "dobycha_vody_cum": [9999.0, 9999.0],
            "dobycha_liq_cum": [9999.0, 9999.0],
            "dobycha_nefti_cum_m3": [100.0, 200.0],
            "dobycha_vody_cum_m3": [100.0, 300.0],
            "dobycha_liq_cum_m3": [200.0, 500.0],
        }
    )

    fig = displacement_characteristic_figure(yearly, "sazonov", "Сазонов", [2020, 2021])
    fact_trace = next(trace for trace in fig.data if trace.name == "Факт")

    assert fact_trace.x[0] == pytest.approx(100.0 * 1.157)
    assert fact_trace.y[0] == pytest.approx(np.log(100.0 * 1.157 + 100.0))


def test_vnf_method_uses_current_reservoir_vnf_on_y_axis():
    yearly = pd.DataFrame(
        {
            "year": [2020, 2021],
            "kin": [10.0, 12.0],
            "vnf_nak": [100.0, 100.0],
            "dobycha_nefti": [86.2, 86.2],
            "dobycha_vody": [118.5, 237.0],
            "dobycha_nefti_m3": [1000.0, 1000.0],
            "dobycha_vody_m3": [9000.0, 9000.0],
            "dobycha_nefti_cum": [86.2, 172.4],
            "dobycha_vody_cum": [118.5, 355.5],
            "dobycha_liq_cum": [204.7, 527.9],
            "dobycha_nefti_cum_m3": [1000.0, 2000.0],
            "dobycha_vody_cum_m3": [9000.0, 18000.0],
            "dobycha_liq_cum_m3": [10000.0, 20000.0],
        }
    )

    fig = displacement_characteristic_figure(yearly, "vnf", "ВНФ", [2020, 2021])
    fact_trace = next(trace for trace in fig.data if trace.name == "Факт")

    assert fig.layout.yaxis.title.text == "Текущий ВНФ, пласт. условия"
    assert fact_trace.x[0] == pytest.approx(1000.0 * 1.157)
    assert fact_trace.y[0] == pytest.approx(1.0 / 1.157)
    assert fact_trace.y[1] == pytest.approx(2.0 / 1.157)

def test_asset_year_aggregate_calculates_missing_cumulative_inputs_for_selected_area():
    source = pd.DataFrame(
        {
            "year": [2020, 2021, 2022],
            "dobycha_liq": [15.0, 30.0, 45.0],
            "dobycha_nefti": [10.0, 20.0, 30.0],
            "dobycha_vody": [5.0, 10.0, 15.0],
            "zakachka": [3.0, 4.0, 5.0],
            "dob_fond": [1.0, 2.0, 3.0],
            "nagn_fond": [1.0, 1.0, 1.0],
            "kin": [10.0, 20.0, 30.0],
        }
    )

    aggregate = compute_asset_year_aggregate(source)

    assert aggregate["dobycha_nefti_cum"].tolist() == [10.0, 30.0, 60.0]
    assert aggregate["dobycha_vody_cum"].tolist() == [5.0, 15.0, 30.0]
    assert aggregate["dobycha_liq_cum"].tolist() == [15.0, 45.0, 90.0]
    assert aggregate["vnf_nak"].tolist() == [0.5, 0.5, 0.5]

    fig = displacement_characteristic_figure(aggregate, "sazonov", "Сазонов", [2020, 2022])

    assert fig.layout.xaxis.title.text == "Vн, пласт. м³"
    assert fig.layout.yaxis.title.text == "LN(Vж)"


