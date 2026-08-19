"""Характеристики вытеснения: пересчёт в пластовые условия, тренды и прогноз до целевого ВНФ."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from config import settings
from normalization import safe_div
from theme import OP_AMBER, OP_GREEN, OP_MUTED, OP_RED, apply_theme, empty_fig
from theme import rgba_from_hex as _rgba_from_hex

# Физические параметры пересчёта и целевой ВНФ настраиваются через окружение
# (см. config.Settings): для другого месторождения их не нужно править в коде.
DISPLACEMENT_TARGET_VNF = settings.displacement_target_vnf
OIL_DENSITY_T_PER_M3 = settings.oil_density_t_per_m3
WATER_DENSITY_T_PER_M3 = settings.water_density_t_per_m3
OIL_FORMATION_VOLUME_FACTOR = settings.oil_formation_volume_factor
WATER_FORMATION_VOLUME_FACTOR = settings.water_formation_volume_factor
DEFAULT_DISPLACEMENT_PERIOD = [2020, 2025]
DEFAULT_DISPLACEMENT_SLIDER_BOUNDS = (2000, 2035)
DISPLACEMENT_SPECS = [
    ("disp-sazonov", "Характеристика вытеснения: метод Сазонова", "Сазонов", "sazonov"),
    ("disp-maksimov", "Характеристика вытеснения: метод Максимова", "Максимов", "maksimov"),
    ("disp-kambarov", "Характеристика вытеснения: метод Камбарова", "Камбаров", "kambarov"),
    ("disp-taysin-timashov", "Характеристика вытеснения: метод Тайсина-Тимашова", "Тайсин-Тимашов", "taysin_timashov"),
    ("disp-nazarov-sipachev", "Характеристика вытеснения: метод Назарова-Сипачева", "Назаров-Сипачев", "nazarov_sipachev"),
    ("disp-pirverdyan", "Характеристика вытеснения: метод Пирвердяна", "Пирвердян", "ln_vnf"),
    ("disp-sipachev-posevich", "Характеристика вытеснения: метод Сипачева-Посевича", "Сипачев-Посевич", "sipachev_posevich"),
    ("disp-vnf", "Характеристика вытеснения: водонефтяной фактор", "ВНФ", "vnf"),
]



DISPLACEMENT_METHOD_NAMES = {method: method_name for _graph_id, _title, method_name, method in DISPLACEMENT_SPECS}


def _positive_numeric(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values.where(values > 0)


def _series_or_nan(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df.columns:
        return pd.to_numeric(df[column], errors="coerce")
    return pd.Series(np.nan, index=df.index, dtype="float64")


def _surface_oil_m3(df: pd.DataFrame, base_column: str) -> pd.Series:
    direct = _series_or_nan(df, f"{base_column}_m3")
    fallback = _series_or_nan(df, base_column) / OIL_DENSITY_T_PER_M3
    return direct.fillna(fallback)


def _surface_water_m3(df: pd.DataFrame, base_column: str) -> pd.Series:
    direct = _series_or_nan(df, f"{base_column}_m3")
    fallback = _series_or_nan(df, base_column) / WATER_DENSITY_T_PER_M3
    return direct.fillna(fallback)


def _surface_oil_m3_from_mass(df: pd.DataFrame, base_column: str) -> pd.Series:
    return _series_or_nan(df, base_column) / OIL_DENSITY_T_PER_M3


def _surface_water_m3_from_mass(df: pd.DataFrame, base_column: str) -> pd.Series:
    return _series_or_nan(df, base_column) / WATER_DENSITY_T_PER_M3


def _add_displacement_reservoir_volumes(dd: pd.DataFrame) -> pd.DataFrame:
    dd = dd.copy()
    oil_surface = _surface_oil_m3(dd, "dobycha_nefti_cum")
    water_surface = _surface_water_m3(dd, "dobycha_vody_cum")
    vnf_oil_current_surface = _surface_oil_m3_from_mass(dd, "dobycha_nefti")
    vnf_water_current_surface = _surface_water_m3_from_mass(dd, "dobycha_vody")
    vnf_oil_cum_surface = _surface_oil_m3_from_mass(dd, "dobycha_nefti_cum")
    vnf_water_cum_surface = _surface_water_m3_from_mass(dd, "dobycha_vody_cum")

    dd["oil_reservoir_cum"] = oil_surface * OIL_FORMATION_VOLUME_FACTOR
    dd["water_reservoir_cum"] = water_surface * WATER_FORMATION_VOLUME_FACTOR
    dd["liquid_reservoir_cum"] = dd["oil_reservoir_cum"] + dd["water_reservoir_cum"]
    dd["vnf_oil_reservoir_current"] = vnf_oil_current_surface * OIL_FORMATION_VOLUME_FACTOR
    dd["vnf_water_reservoir_current"] = vnf_water_current_surface * WATER_FORMATION_VOLUME_FACTOR
    dd["vnf_oil_reservoir_cum"] = vnf_oil_cum_surface * OIL_FORMATION_VOLUME_FACTOR
    dd["vnf_water_reservoir_cum"] = vnf_water_cum_surface * WATER_FORMATION_VOLUME_FACTOR
    dd["vnf_oil_reservoir_current"] = dd["vnf_oil_reservoir_current"].fillna(dd["vnf_oil_reservoir_cum"].diff().fillna(dd["vnf_oil_reservoir_cum"]))
    dd["vnf_water_reservoir_current"] = dd["vnf_water_reservoir_current"].fillna(dd["vnf_water_reservoir_cum"].diff().fillna(dd["vnf_water_reservoir_cum"]))
    dd["vnf_current_reservoir"] = safe_div(dd["vnf_water_reservoir_current"], dd["vnf_oil_reservoir_current"])
    dd["vnf_cum_reservoir"] = safe_div(dd["vnf_water_reservoir_cum"], dd["vnf_oil_reservoir_cum"])
    return dd


def _displacement_prepare_axes(dd: pd.DataFrame, method: str, vnf_col: str) -> tuple[pd.DataFrame, str, str, str]:
    oil = _positive_numeric(dd["oil_reservoir_cum"])
    water = _positive_numeric(dd["water_reservoir_cum"])
    liquid = _positive_numeric(dd["liquid_reservoir_cum"])
    current_vnf = _positive_numeric(dd["vnf_current_reservoir"])

    if method == "ln_vnf":
        dd["x_method"] = 1 / np.sqrt(liquid)
        dd["y_method"] = oil
        return dd, "Vж^-0.5, пласт. м³", "Vн, пласт. м³", "oil_from_liquid_inv_sqrt"
    if method == "kambarov":
        dd["x_method"] = 1 / liquid
        dd["y_method"] = oil
        return dd, "Vж^-1, пласт. м³", "Vн, пласт. м³", "oil_from_liquid_inv"
    if method == "sazonov":
        dd["x_method"] = oil
        dd["y_method"] = np.log(liquid)
        return dd, "Vн, пласт. м³", "LN(Vж)", "ln_liquid_from_oil"
    if method == "maksimov":
        dd["x_method"] = oil
        dd["y_method"] = np.log(water)
        return dd, "Vн, пласт. м³", "LN(Vв)", "ln_water_from_oil"
    if method == "taysin_timashov":
        dd["x_method"] = liquid
        dd["y_method"] = safe_div(water, oil)
        return dd, "Vж, пласт. м³", "Vв / Vн", "vnf_from_liquid"
    if method == "nazarov_sipachev":
        dd["x_method"] = water
        dd["y_method"] = safe_div(liquid, oil)
        return dd, "Vв = Vж − Vн, пласт. м³", "Vж / Vн", "liquid_oil_ratio_from_water"
    if method == "sipachev_posevich":
        dd["x_method"] = liquid
        dd["y_method"] = safe_div(liquid, oil)
        return dd, "Vж, пласт. м³", "Vж / Vн", "liquid_oil_ratio_from_liquid"
    dd["x_method"] = oil
    dd["y_method"] = current_vnf
    return dd, "Vн, пласт. м³", "Текущий ВНФ, пласт. условия", "current_vnf_from_oil"


def _implied_recoverable_oil(dd: pd.DataFrame) -> float:
    if "kin" not in dd.columns:
        return np.nan
    oil_column = "oil_reservoir_cum" if "oil_reservoir_cum" in dd.columns else "dobycha_nefti_cum"
    if oil_column not in dd.columns:
        return np.nan
    reserve = safe_div(dd[oil_column], dd["kin"] / 100)
    reserve = pd.Series(pd.to_numeric(reserve, errors="coerce")).replace([np.inf, -np.inf], np.nan).dropna()
    reserve = reserve[reserve > 0]
    if reserve.empty:
        return np.nan
    return float(reserve.median())


def _kin_from_oil(target_oil: float, recoverable_oil: float) -> float:
    if not np.isfinite(target_oil) or not np.isfinite(recoverable_oil) or recoverable_oil <= 0:
        return np.nan
    return float(target_oil / recoverable_oil * 100)



def _linear_coefficients(x, y) -> tuple[float, float]:
    x = pd.to_numeric(pd.Series(x), errors="coerce")
    y = pd.to_numeric(pd.Series(y), errors="coerce")
    mask = x.notna() & y.notna()
    if mask.sum() < 2:
        return np.nan, np.nan
    a, b = np.polyfit(x[mask], y[mask], 1)
    return float(a), float(b)


def _annual_vnf_for_displacement_x(x_value: float, a: float, b: float, mode: str) -> float:
    if not all(np.isfinite(v) for v in [x_value, a, b]):
        return np.nan
    if mode in {"vnf_from_oil", "current_vnf_from_oil"}:
        return float(a * x_value + b)
    y_value = a * x_value + b
    if mode == "ln_liquid_from_oil":
        return float(a * np.exp(y_value) - 1)
    if mode == "ln_water_from_oil":
        return float(a * np.exp(y_value))
    if mode == "oil_from_liquid_log":
        liquid = np.exp(x_value)
        return float(liquid / y_value - 1) if y_value > 0 else np.nan
    if mode == "oil_from_water_log":
        water = np.exp(x_value)
        return float(water / y_value) if y_value > 0 else np.nan
    if mode == "oil_from_liquid_inv":
        liquid = 1 / x_value if x_value != 0 else np.nan
        return float(liquid / y_value - 1) if y_value > 0 else np.nan
    if mode == "oil_from_liquid_inv_sqrt":
        liquid = 1 / (x_value**2) if x_value != 0 else np.nan
        return float(liquid / y_value - 1) if y_value > 0 else np.nan
    if mode == "vnf_from_liquid":
        ratio = y_value
        denominator = 1 + ratio
        if denominator == 0:
            return np.nan
        correction = a * x_value / denominator
        if np.isclose(1 - correction, 0):
            return np.nan
        return float((ratio + correction) / (1 - correction))
    if mode == "liquid_oil_ratio_from_water":
        ratio = y_value
        denominator = ratio - 1 - a * x_value
        if np.isclose(denominator, 0):
            return np.nan
        return float((ratio - 1) ** 2 / denominator)
    if mode == "liquid_oil_ratio_from_liquid":
        ratio = y_value
        denominator = ratio - a * x_value
        if np.isclose(denominator, 0):
            return np.nan
        return float(ratio**2 / denominator - 1)
    return np.nan


def _oil_water_from_displacement_x(x_value: float, a: float, b: float, mode: str) -> tuple[float, float]:
    y_value = a * x_value + b
    if mode in {"vnf_from_oil", "current_vnf_from_oil"}:
        oil = x_value
        return float(oil), float(oil * y_value)
    if mode == "ln_liquid_from_oil":
        liquid = np.exp(y_value)
        return float(x_value), float(liquid - x_value)
    if mode == "ln_water_from_oil":
        return float(x_value), float(np.exp(y_value))
    if mode == "oil_from_liquid_log":
        liquid = np.exp(x_value)
        return float(y_value), float(liquid - y_value)
    if mode == "oil_from_water_log":
        return float(y_value), float(np.exp(x_value))
    if mode == "oil_from_liquid_inv":
        liquid = 1 / x_value
        return float(y_value), float(liquid - y_value)
    if mode == "oil_from_liquid_inv_sqrt":
        liquid = 1 / (x_value**2)
        return float(y_value), float(liquid - y_value)
    if mode == "vnf_from_liquid":
        oil = x_value / (1 + y_value)
        return float(oil), float(x_value - oil)
    if mode == "liquid_oil_ratio_from_water":
        oil = x_value / (y_value - 1)
        return float(oil), float(x_value)
    if mode == "liquid_oil_ratio_from_liquid":
        oil = x_value / y_value
        return float(oil), float(x_value - oil)
    return np.nan, np.nan


def _solve_target_x_for_annual_vnf(trend_df: pd.DataFrame, target_vnf: float, mode: str) -> float:
    a, b = _linear_coefficients(trend_df["x_method"], trend_df["y_method"])
    if not np.isfinite(a) or not np.isfinite(b) or a == 0:
        return np.nan
    if mode in {"vnf_from_oil", "current_vnf_from_oil"}:
        return float((target_vnf - b) / a)
    if mode == "ln_liquid_from_oil":
        ratio = (target_vnf + 1) / a
        return float((np.log(ratio) - b) / a) if ratio > 0 else np.nan
    if mode == "ln_water_from_oil":
        ratio = target_vnf / a
        return float((np.log(ratio) - b) / a) if ratio > 0 else np.nan

    ordered = trend_df.sort_values("year")
    x_start = float(ordered["x_method"].iloc[-1])
    if len(ordered) >= 2:
        x_prev = float(ordered["x_method"].iloc[-2])
        direction = np.sign(x_start - x_prev)
    else:
        direction = 1.0
    if direction == 0 or not np.isfinite(direction):
        direction = np.sign(a) or 1.0

    def residual(x_value):
        return _annual_vnf_for_displacement_x(x_value, a, b, mode) - target_vnf

    low = x_start
    f_low = residual(low)
    step = max(abs(x_start) * 0.1, 1.0)
    high = x_start
    f_high = f_low
    for _ in range(80):
        high = high + direction * step
        f_high = residual(high)
        if np.isfinite(f_low) and np.isfinite(f_high) and f_low * f_high <= 0:
            left, right = (low, high) if low <= high else (high, low)
            f_left = residual(left)
            for _ in range(80):
                mid = (left + right) / 2
                f_mid = residual(mid)
                if not np.isfinite(f_mid):
                    break
                if abs(f_mid) < 1e-6:
                    return float(mid)
                if f_left * f_mid <= 0:
                    right = mid
                else:
                    left = mid
                    f_left = f_mid
            return float((left + right) / 2)
        step *= 1.4
    return np.nan

def _displacement_x_from_oil(mode: str, oil_value: float, target_vnf: float) -> float:
    """Координата X характеристики, соответствующая накопленной нефти при целевом ВНФ.

    Единственное место, где закодирована обратная связь «нефть -> X» для всех
    методов: используется и в решателе, и при построении точки прогноза.
    """
    if mode == "oil_from_liquid_log":
        return float(np.log(oil_value * (1 + target_vnf)))
    if mode == "oil_from_liquid_inv":
        return float(1 / (oil_value * (1 + target_vnf)))
    if mode == "oil_from_water_log":
        return float(np.log(oil_value * target_vnf))
    if mode == "oil_from_liquid_inv_sqrt":
        return float(1 / np.sqrt(oil_value * (1 + target_vnf)))
    if mode in {"vnf_from_liquid", "liquid_oil_ratio_from_liquid"}:
        return float(oil_value * (1 + target_vnf))
    if mode == "liquid_oil_ratio_from_water":
        return float(oil_value * target_vnf)
    return float(oil_value)


def _solve_target_oil_from_vnf(model_fn, target_vnf: float, mode: str, oil_min: float, oil_max: float) -> float:
    if not np.isfinite(oil_min) or oil_min <= 0:
        oil_min = 1.0
    if not np.isfinite(oil_max) or oil_max <= oil_min:
        oil_max = oil_min * 2

    def residual(oil_value):
        predicted = float(model_fn([_displacement_x_from_oil(mode, oil_value, target_vnf)])[0])
        if mode in {"vnf_from_oil", "vnf_from_liquid"}:
            return predicted - target_vnf
        if mode in {"liquid_oil_ratio_from_water", "liquid_oil_ratio_from_liquid"}:
            return predicted - (1 + target_vnf)
        return predicted - oil_value

    step = max(abs(oil_max) * 0.5, 1.0)
    low = max(oil_max, 1e-9)
    high = low * 1.5
    for _ in range(40):
        f_low = residual(low)

        f_high = residual(high)
        if np.isfinite(f_low) and np.isfinite(f_high) and f_low * f_high <= 0:
            left, right = low, high
            f_left = f_low
            for _ in range(80):
                mid = (left + right) / 2
                f_mid = residual(mid)
                if not np.isfinite(f_mid):
                    break
                if abs(f_mid) < 1e-6:
                    return float(mid)
                if f_left * f_mid <= 0:
                    right = mid
                else:
                    left = mid
                    f_left = f_mid
            return float((left + right) / 2)
        step *= 1.4
        high = high + step
    return float(high) if np.isfinite(f_high) else np.nan


def normalize_period_value(period_value):
    if not isinstance(period_value, (list, tuple)) or len(period_value) != 2:
        return tuple(DEFAULT_DISPLACEMENT_PERIOD)
    start, end = pd.to_numeric(pd.Series(period_value), errors="coerce").fillna(pd.Series(DEFAULT_DISPLACEMENT_PERIOD)).astype(int)
    return (min(int(start), int(end)), max(int(start), int(end)))


def displacement_characteristic_figure(yearly_agg, method: str, method_name: str, period_value=None):
    if yearly_agg is None or yearly_agg.empty:
        return empty_fig("Нет данных для характеристики вытеснения", height=460)
    vnf_col = "vnf_nak" if "vnf_nak" in yearly_agg.columns else "vnf_tek"
    required = ["year", "kin", vnf_col, "dobycha_nefti_cum", "dobycha_vody_cum", "dobycha_liq_cum"]
    optional_volume_columns = [
        "dobycha_nefti",
        "dobycha_vody",
        "dobycha_nefti_m3",
        "dobycha_vody_m3",
        "dobycha_liq_m3",
        "dobycha_nefti_cum_m3",
        "dobycha_vody_cum_m3",
        "dobycha_liq_cum_m3",
    ]
    available_columns = required + [col for col in optional_volume_columns if col in yearly_agg.columns]
    missing = [col for col in required if col not in yearly_agg.columns]
    if missing:
        return empty_fig(f"Нет данных: {', '.join(missing)}", height=460)

    start_year, end_year = normalize_period_value(period_value)
    dd = yearly_agg[available_columns].copy()
    for col in available_columns:
        dd[col] = pd.to_numeric(dd[col], errors="coerce")
    dd = dd.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    dd = dd[(dd[vnf_col] > 0) & (dd["dobycha_nefti_cum"] > 0)].sort_values("year")
    dd = _add_displacement_reservoir_volumes(dd)
    if dd.empty:
        return empty_fig("Нет точек после фильтрации", height=460)

    dd, x_title, y_title, target_mode = _displacement_prepare_axes(dd, method, vnf_col)
    dd = dd.replace([np.inf, -np.inf], np.nan).dropna(subset=["x_method", "y_method", "kin", "dobycha_nefti_cum"])
    if dd.empty:
        return empty_fig("Нет точек после преобразования характеристики", height=460)

    period_mask = dd["year"].between(start_year, end_year, inclusive="both")
    trend_df = dd[period_mask].dropna(subset=["x_method", "y_method"])
    recoverable_oil = _implied_recoverable_oil(dd)

    fig = go.Figure()
    common_customdata = np.column_stack([dd["year"], dd[vnf_col], dd["dobycha_nefti_cum"], dd["kin"]])
    fig.add_trace(go.Scatter(
        x=dd["x_method"], y=dd["y_method"], mode="markers+lines", name="Факт",
        marker=dict(size=8, color=OP_GREEN), line=dict(color=_rgba_from_hex(OP_GREEN, 0.35), width=1.5),
        customdata=common_customdata,
        hovertemplate="Год %{customdata[0]:.0f}<br>ВНФ %{customdata[1]:.2f}<br>Нак. нефть %{customdata[2]:,.0f} т<br>КИН %{customdata[3]:.2f}%<extra></extra>",
    ))
    if not trend_df.empty:
        fig.add_trace(go.Scatter(
            x=trend_df["x_method"], y=trend_df["y_method"], mode="markers", name=f"Период {start_year}-{end_year}",
            marker=dict(size=11, color=OP_RED, symbol="circle-open", line=dict(width=2)),
            customdata=np.column_stack([trend_df["year"], trend_df[vnf_col], trend_df["dobycha_nefti_cum"], trend_df["kin"]]),
            hovertemplate="Период тренда<br>Год %{customdata[0]:.0f}<br>ВНФ %{customdata[1]:.2f}<br>Нак. нефть %{customdata[2]:,.0f} т<br>КИН %{customdata[3]:.2f}%<extra></extra>",
        ))

    if len(trend_df) >= 2:
        trend_a, trend_b = _linear_coefficients(trend_df["x_method"], trend_df["y_method"])

        def predict(x_values):
            return trend_a * np.asarray(x_values, dtype=float) + trend_b

        last_trend_point = trend_df.sort_values("year").iloc[-1]
        x_start = float(last_trend_point["x_method"])
        target_x = _solve_target_x_for_annual_vnf(trend_df, DISPLACEMENT_TARGET_VNF, target_mode)
        if not np.isfinite(target_x):
            fig.add_annotation(text="Не удалось рассчитать точку годового ВНФ=49", xref="paper", yref="paper", x=0.5, y=0.9, showarrow=False, font=dict(color=OP_MUTED, size=11))
            target_x = x_start
        target_oil, _target_water = _oil_water_from_displacement_x(target_x, trend_a, trend_b, target_mode)
        target_kin = _kin_from_oil(target_oil, recoverable_oil)
        target_x = _displacement_x_from_oil(target_mode, target_oil, DISPLACEMENT_TARGET_VNF)
        target_y = float(predict([target_x])[0])

        x_line = np.array([x_start, target_x], dtype=float)
        y_line = predict(x_line)
        fig.add_trace(go.Scatter(
            x=x_line, y=y_line, mode="lines", name=f"Тренд {start_year}-{end_year} до ВНФ=49",
            line=dict(color=OP_RED, width=2.4, dash="dash"),
            hovertemplate=f"Тренд<br>{y_title} %{{y:,.2f}}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=[target_x], y=[target_y], mode="markers+text", name="Прогноз при ВНФ=49",
            marker=dict(size=12, color=OP_AMBER, symbol="diamond"),
            text=[f"Годовой ВНФ=49; Qн={target_oil:,.0f} т; КИН={target_kin:.2f}%"], textposition="top center",
            customdata=[[target_oil, target_kin]],
            hovertemplate="Годовой ВНФ=49<br>Нак. нефть %{customdata[0]:,.0f} т<br>КИН %{customdata[1]:.2f}%<extra></extra>",
        ))
    else:
        fig.add_annotation(text="Для тренда нужны минимум 2 точки в выбранном периоде", xref="paper", yref="paper", x=0.5, y=0.96, showarrow=False, font=dict(color=OP_MUTED, size=11))

    fig.update_layout(
        xaxis_title=x_title,
        yaxis_title=y_title,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=56, r=28, t=64, b=54),
    )
    return apply_theme(fig, height=460, compact=True)
