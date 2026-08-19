"""Фигуры вкладки «Анализ по активу»: динамика, фонды, аналитические scatter-карточки."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from common import format_visible_pct_label
from normalization import AREA_COL_YEAR, safe_div
from services import aggregation_service, periods_service
from theme import (
    OP_BORDER,
    OP_GREEN,
    OP_GREEN_DEEP,
    OP_GRID,
    OP_MUTED,
    OP_RED,
    PALETTE,
    TN_DEBIT_LIQ_PURPLE,
    TN_DEBIT_OIL_RED,
    TN_FUND_BLUE,
    TN_INJ_BLUE,
    TN_LIQ_GREEN,
    TN_OIL_BURGUNDY,
    TN_WC_CYAN,
    apply_theme,
    empty_fig,
)


def tech_dynamics(d, yearly_agg=None):
    if d.empty and (yearly_agg is None or yearly_agg.empty):
        return empty_fig()
    a = yearly_agg.copy() if yearly_agg is not None else aggregation_service.compute_asset_year_aggregate(d)
    if "wc" not in a.columns:
        a["wc"] = np.nan

    if "oil_yoy_pct" not in a.columns:
        a["oil_yoy_pct"] = pd.to_numeric(a["dobycha_nefti"], errors="coerce").pct_change() * 100
    a["oil_yoy_color"] = np.where(a["oil_yoy_pct"] >= 0, OP_GREEN, OP_RED)

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.07,
        row_heights=[0.80, 0.20],
        specs=[[{"secondary_y": True}], [{}]],
    )

    primary_lines = [
        ("dobycha_liq", "Добыча жидкости", TN_LIQ_GREEN),
        ("dobycha_nefti", "Добыча нефти", TN_OIL_BURGUNDY),
        ("zakachka", "Закачка", TN_INJ_BLUE),
    ]
    for col, name, color in primary_lines:
        fig.add_trace(
            go.Scatter(
                x=a["year"],
                y=a[col],
                mode="lines+markers",
                name=name,
                line=dict(color=color, width=2.2),
                marker=dict(color=color, size=6),
            ),
            row=1,
            col=1,
            secondary_y=False,
        )

    secondary_lines = [
        ("wc", "Обводнённость", TN_WC_CYAN, "solid"),
        ("debit_liq_plot", "Дебит жидкости", TN_DEBIT_LIQ_PURPLE, "dot"),
        ("debit_neft", "Дебит нефти", TN_DEBIT_OIL_RED, "dot"),
    ]
    for col, name, color, dash in secondary_lines:
        fig.add_trace(
            go.Scatter(
                x=a["year"],
                y=a[col],
                mode="lines+markers",
                name=name,
                line=dict(color=color, width=2.0, dash=dash),
                marker=dict(color=color, size=6),
            ),
            row=1,
            col=1,
            secondary_y=True,
        )

    # Фонд скважин вынесен на третью вертикальную ось.
    fig.add_trace(
        go.Bar(
            x=a["year"],
            y=a["dob_fond"],
            name="Доб. фонд",
            opacity=0.25,
            marker_color=OP_GREEN_DEEP,
            xaxis="x",
            yaxis="y4",
        )
    )
    fig.add_trace(
        go.Bar(
            x=a["year"],
            y=a["nagn_fond"],
            name="Нагн. фонд",
            opacity=0.25,
            marker_color=TN_FUND_BLUE,
            xaxis="x",
            yaxis="y4",
        )
    )

    yoy = a.dropna(subset=["oil_yoy_pct"]).copy()
    fig.add_trace(
        go.Bar(
            x=yoy["year"],
            y=yoy["oil_yoy_pct"],
            name="Δ нефти YoY",
            marker_color=yoy["oil_yoy_color"],
            text=[format_visible_pct_label(v) for v in yoy["oil_yoy_pct"]],
            texttemplate="%{text}",
            textposition="outside",
            cliponaxis=False,
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    fig.update_yaxes(title_text="Добыча / закачка", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Дебит / обводнённость", row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Δ нефти, %", row=2, col=1)
    fig.update_xaxes(title_text="Год", row=2, col=1)

    # Диапазон малой гистограммы считаем по изменениям за последние 15 лет.
    yoy_15 = yoy[yoy["year"] >= int(a["year"].max()) - 14]["oil_yoy_pct"].dropna()
    if not yoy_15.empty:
        y_min = float(yoy_15.min())
        y_max = float(yoy_15.max())
        if y_min == y_max:
            pad = max(abs(y_min) * 0.10, 1.0)
        else:
            pad = (y_max - y_min) * 0.12
        fig.update_yaxes(range=[y_min - pad, y_max + pad], row=2, col=1)

    fig.update_layout(
        barmode="group",
        bargap=0.22,
        bargroupgap=0.08,
        xaxis=dict(domain=[0.0, 0.84]),
        xaxis2=dict(domain=[0.0, 0.84]),
        yaxis4=dict(
            title=dict(text="Фонд, скв.", font=dict(color=OP_MUTED)),
            tickfont=dict(color=OP_MUTED),
            overlaying="y",
            side="right",
            anchor="free",
            position=0.92,
            showgrid=False,
            zeroline=False,
        ),
        shapes=[
            dict(
                type="line",
                xref="x2",
                yref="y3",
                x0=a["year"].min(),
                x1=a["year"].max(),
                y0=0,
                y1=0,
                line=dict(color=OP_BORDER, width=1),
            )
        ],
        legend=dict(orientation="h", yanchor="bottom", y=1.03, xanchor="left", x=0),
    )
    return apply_theme(fig, height=650)

def fund_dynamics(d, yearly_agg=None):
    if d.empty and (yearly_agg is None or yearly_agg.empty):
        return empty_fig()
    a = yearly_agg.copy() if yearly_agg is not None else aggregation_service.compute_asset_year_aggregate(d)
    fig = go.Figure()
    fig.add_bar(x=a["year"], y=a["dob_fond"], name="Добывающий фонд", marker_color=OP_GREEN)
    fig.add_bar(x=a["year"], y=a["nagn_fond"], name="Нагнетательный фонд", marker_color=TN_FUND_BLUE)
    fig.update_layout(barmode="group", xaxis_title="Год", yaxis_title="Скважины")
    return apply_theme(fig)


def fund_ratio_dynamics(d, yearly_agg=None):
    if d.empty and (yearly_agg is None or yearly_agg.empty):
        return empty_fig()
    a = yearly_agg.copy() if yearly_agg is not None else aggregation_service.compute_asset_year_aggregate(d)
    if "ratio_dob_nagn" not in a.columns:
        a["ratio_dob_nagn"] = safe_div(a["dob_fond"], a["nagn_fond"])
    fig = px.bar(a, x="year", y="ratio_dob_nagn", text_auto=".2f")
    fig.update_layout(xaxis_title="Год", yaxis_title="Доб/Нагн")
    return apply_theme(fig)


def scatter_metric(d, x, y, title, x_title=None, y_title=None, log_x=False, show_trendline=False):
    cols = [x, y, AREA_COL_YEAR, "year"]
    miss = [c for c in cols if c not in d.columns]
    if d.empty or miss:
        return empty_fig(f"Нет данных: {', '.join(miss)}")
    dd = d.dropna(subset=[x, y]).copy()
    if log_x:
        dd = dd[dd[x] > 0]
        dd[x] = np.log(dd[x])
        x_title = x_title or f"LN({x})"
    if dd.empty:
        return empty_fig("Нет точек после фильтрации")

    kwargs = dict(x=x, y=y, color=AREA_COL_YEAR, hover_data=["year"])
    if show_trendline:
        kwargs["trendline"] = "ols"
    fig = px.scatter(dd, **kwargs)
    fig.update_traces(marker=dict(size=7, opacity=0.82), selector=dict(mode="markers"))

    # Trendline оставляем только на выбранных аналитических карточках.
    # Дополнительные legend items от линий скрываем, чтобы не перегружать карточку.
    for tr in fig.data:
        if getattr(tr, "mode", None) == "lines":
            tr.showlegend = False
            tr.line.width = 1.4
    fig.update_layout(xaxis_title=x_title or x, yaxis_title=y_title or y)
    return apply_theme(fig, height=440, compact=True)






def add_identity_line(fig, dd, x, y, axis_from_zero=False, name="y = x"):
    """Добавляет диагональную пунктирную линию y=x и при необходимости фиксирует оси от 0."""
    vals = pd.concat([
        pd.to_numeric(dd[x], errors="coerce"),
        pd.to_numeric(dd[y], errors="coerce"),
    ]).replace([np.inf, -np.inf], np.nan).dropna()

    if vals.empty:
        return fig

    max_val = float(vals.max())
    min_val = float(vals.min())
    start = 0.0 if axis_from_zero else min(0.0, min_val)
    end = max(1.0, max_val) * 1.05

    fig.add_trace(
        go.Scatter(
            x=[start, end],
            y=[start, end],
            mode="lines",
            line=dict(color="#4B5563", width=1.5, dash="dash"),
            name=name,
            hoverinfo="skip",
            showlegend=False,
        )
    )

    if axis_from_zero:
        fig.update_xaxes(range=[0, end])
        fig.update_yaxes(range=[0, end])

    return fig


def niz_otbor_vs_wc_identity(d):
    """Карточка 17: Отбор от НИЗ от обводнённости без тренда, с диагональю y=x."""
    x = "wc"
    y = "niz_otbor"
    cols = [x, y, AREA_COL_YEAR, "year"]
    miss = [c for c in cols if c not in d.columns]
    if d.empty or miss:
        return empty_fig(f"Нет данных: {', '.join(miss)}", height=440)

    dd = d.dropna(subset=[x, y]).copy()
    if dd.empty:
        return empty_fig("Нет точек после фильтрации", height=440)

    fig = px.scatter(
        dd,
        x=x,
        y=y,
        color=AREA_COL_YEAR,
        hover_data=["year"],
        labels={
            x: "Обводнённость, %",
            y: "Отбор от НИЗ, %",
            AREA_COL_YEAR: "Площадь",
            "year": "Год",
        },
    )
    fig.update_traces(marker=dict(size=7, opacity=0.84), selector=dict(mode="markers"))
    add_identity_line(fig, dd, x, y, axis_from_zero=False, name="y = x")
    fig.update_layout(xaxis_title="Обводнённость, %", yaxis_title="Отбор от НИЗ, %")
    return apply_theme(fig, height=440, compact=True)

def segmented_wc_kiz(d, n_periods=6, min_size=5, period_result=None):
    """Карточка 16: Обводнённость от КИЗ с оптимальным разбиением на периоды."""
    if period_result is None:
        period_result = periods_service.compute_wc_kiz_periods_raw(d, n_periods=n_periods, min_size=min_size)
    df_seg = period_result.data.copy()
    segments = list(period_result.segments)
    miss = list(period_result.missing_columns)
    if miss:
        return empty_fig(f"Нет данных: {', '.join(miss)}", height=440)
    if df_seg.empty:
        return empty_fig("Нет точек после фильтрации", height=440)

    hover_data = {
        "year": True,
        "kiz": ":.1f",
        "wc": ":.1f",
        "period_number": False,
        "__src_index": False,
    }
    if AREA_COL_YEAR in df_seg.columns:
        hover_data[AREA_COL_YEAR] = True
    if "ngdu" in df_seg.columns:
        hover_data["ngdu"] = True

    fig = px.scatter(
        df_seg,
        x="kiz",
        y="wc",
        color="period",
        color_discrete_sequence=PALETTE,
        hover_data=hover_data,
        labels={
            "kiz": "Коэффициент извлечения запасов, %",
            "wc": "Обводнённость, %",
            "period": "Выявленный период",
            "year": "Год",
            AREA_COL_YEAR: "Площадь",
            "ngdu": "НГДУ",
        },
    )

    # Полупрозрачные зоны относительно диагонали y = x:
    # выше линии — зона повышенной обводнённости, ниже — более благоприятная зона.
    zone_green = go.Scatter(
        x=[0, 100, 100, 0],
        y=[0, 0, 100, 0],
        fill="toself",
        mode="lines",
        line=dict(width=0),
        fillcolor="rgba(0, 142, 91, 0.10)",
        name="Ниже диагонали",
        hoverinfo="skip",
        showlegend=False,
    )
    zone_red = go.Scatter(
        x=[0, 0, 100, 0],
        y=[0, 100, 100, 0],
        fill="toself",
        mode="lines",
        line=dict(width=0),
        fillcolor="rgba(213, 48, 51, 0.10)",
        name="Выше диагонали",
        hoverinfo="skip",
        showlegend=False,
    )
    diagonal = go.Scatter(
        x=[0, 100],
        y=[0, 100],
        mode="lines",
        line=dict(color="#6B7280", width=1.6, dash="dash"),
        name="Граница y = x",
        hoverinfo="skip",
        showlegend=False,
    )

    fig = go.Figure(data=[zone_green, zone_red, diagonal] + list(fig.data), layout=fig.layout)

    # Вертикальные пунктирные линии по границам найденных периодов.
    # Поскольку ось X — КИЗ, граница ставится по среднему КИЗ между соседними периодами.
    boundary_x_values = []
    for _, end in segments[:-1]:
        if 0 < end < len(df_seg):
            left_x = df_seg.iloc[end - 1]["kiz"]
            right_x = df_seg.iloc[end]["kiz"]
            boundary_x = float(np.nanmean([left_x, right_x]))
            if np.isfinite(boundary_x):
                boundary_x_values.append(boundary_x)

    for idx, boundary_x in enumerate(boundary_x_values, start=1):
        fig.add_vline(
            x=boundary_x,
            line_width=1.2,
            line_dash="dash",
            line_color="#4B5563",
            opacity=0.75,
        )
        fig.add_annotation(
            x=boundary_x,
            y=98,
            text=f"Граница {idx}",
            showarrow=False,
            textangle=-90,
            font=dict(size=9, color="#4B5563"),
            xanchor="right",
            yanchor="top",
        )

    fig.update_traces(
        marker=dict(size=10, opacity=0.92, line=dict(width=1, color="#1F2B25")),
        selector=dict(mode="markers"),
    )
    fig.update_xaxes(range=[0, 100], dtick=10, showgrid=True, gridcolor=OP_GRID, title_text="КИЗ, %")
    fig.update_yaxes(range=[0, 100], dtick=10, showgrid=True, gridcolor=OP_GRID, title_text="Обводнённость, %")
    fig.update_layout(
        legend_title_text="Периоды разработки",
        legend=dict(orientation="h", yanchor="top", y=-0.24, xanchor="left", x=0, font=dict(size=9.5, color=OP_MUTED)),
        meta=dict(segmentation_method="dynamic_programming_linear_sse", n_periods=len(segments), min_size=min_size),
    )
    return apply_theme(fig, height=440, compact=True)


def ratio_vs_q_by_wc_kiz_periods(d, period_result=None):
    """Карточка 20: Доб/наг от Qприем/Qжидк с окраской по периодам из карточки 16."""
    x = "q_priem_q_liq"
    y = "ratio_dob_nagn"
    required = [x, y, "year", "kiz", "wc"]
    miss = [c for c in required if c not in d.columns]
    if d.empty or miss:
        return empty_fig(f"Нет данных: {', '.join(miss)}", height=440)

    if period_result is None:
        period_result = periods_service.compute_wc_kiz_periods_raw(d)
    df_periods = period_result.data.copy()
    period_miss = list(period_result.missing_columns)
    if period_miss or df_periods.empty:
        # Если периоды невозможно рассчитать, возвращаем обычный график с трендом.
        return scatter_metric(
            d,
            x=x,
            y=y,
            title="20. Соотношение доб/наг от Qприем/Qжидк",
            x_title="Qприем/Qжидк",
            y_title="Доб/Нагн",
            show_trendline=False,
        )

    period_map = df_periods[["__src_index", "period", "period_number"]].drop_duplicates("__src_index")
    dd = d.copy()
    dd["__src_index"] = d.index
    dd = dd.merge(period_map, on="__src_index", how="left")
    dd = dd.dropna(subset=[x, y, "period"]).copy()
    if dd.empty:
        return empty_fig("Нет точек после фильтрации", height=440)

    hover_data = {
        "year": True,
        x: ":.2f",
        y: ":.2f",
        "period_number": False,
        "__src_index": False,
    }
    if AREA_COL_YEAR in dd.columns:
        hover_data[AREA_COL_YEAR] = True
    if "ngdu" in dd.columns:
        hover_data["ngdu"] = True

    fig = px.scatter(
        dd,
        x=x,
        y=y,
        color="period",
        color_discrete_sequence=PALETTE,
        hover_data=hover_data,
        labels={
            x: "Qприем/Qжидк",
            y: "Доб/Нагн",
            "period": "Период разработки",
            "year": "Год",
            AREA_COL_YEAR: "Площадь",
            "ngdu": "НГДУ",
        },
    )
    fig.update_traces(marker=dict(size=7, opacity=0.84), selector=dict(mode="markers"))

    add_identity_line(fig, dd, x, y, axis_from_zero=True, name="y = x")

    fig.update_layout(
        xaxis_title="Qприем/Qжидк",
        yaxis_title="Доб/Нагн",
        legend_title_text="Периоды разработки",
        legend=dict(orientation="h", yanchor="top", y=-0.24, xanchor="left", x=0, font=dict(size=9.5, color=OP_MUTED)),
    )
    return apply_theme(fig, height=440, compact=True)


def pumping_washing_vs_kin(d):
    if d.empty or "kin" not in d.columns:
        return empty_fig()
    dd = d.dropna(subset=["kin"]).copy()
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    for col, name in [("stepen_prokachki", "Степень прокачки"), ("stepen_promyvki", "Степень промывки")]:
        if col in dd.columns:
            fig.add_trace(go.Scatter(x=dd["kin"], y=dd[col], mode="markers", name=name, text=dd[AREA_COL_YEAR]), secondary_y=False)
    for col, name in [("temp_prokachki", "Темп прокачки"), ("temp_promyvki", "Темп промывки")]:
        if col in dd.columns:
            fig.add_trace(go.Scatter(x=dd["kin"], y=dd[col], mode="markers", name=name, text=dd[AREA_COL_YEAR]), secondary_y=True)
    fig.update_layout(xaxis_title="КИН, %")
    fig.update_yaxes(title_text="Степень, %", secondary_y=False)
    fig.update_yaxes(title_text="Темп, %/год", secondary_y=True)
    return apply_theme(fig, height=560)






ANALYSIS_SPECS = [
    ("g04", "debit_liq", "kiz", "4. Дебит жидкости от КИЗ", "КИЗ, %", "Дебит жидкости, т/сут"),
    ("g05", "debit_liq", "stepen_promyvki", "5. Дебит жидкости от степени промывки", "Степень промывки, %", "Дебит жидкости, т/сут"),
    ("g06", "dob_fond", "kin", "6. Фонд скважин от КИН", "КИН, %", "Добывающий фонд"),
    ("g07", "vnf_nak", "kin", "7. ВНФ накопленный от КИН", "КИН, %", "ВНФ нак."),
    ("g08", "kompens_tek", "kin", "8. Компенсация текущая от КИН", "КИН, %", "Компенсация текущая, %"),
    ("g09", "debit_neft", "kiz", "9. Дебит нефти от КИЗ", "КИЗ, %", "Дебит нефти, т/сут"),
    ("g10", "vnf_nak", "dobycha_nefti_cum", "10. ВНФ нак. от накопленной добычи нефти", "Накопленная добыча нефти, т", "ВНФ нак."),
    ("g12", "niz_temp", "kin", "12. Темп отбора от НИЗ от КИН", "КИН, %", "Темп отбора от НИЗ, %"),
    ("g13", "wc", "kin", "13. Обводнённость от КИН", "КИН, %", "Обводнённость, %"),
    ("g14", "debit_neft", "kin", "14. Дебит нефти от КИН", "КИН, %", "Дебит нефти, т/сут"),
    ("g15", "debit_neft", "dobycha_nefti_cum", "15. Дебит нефти от накопленной добычи нефти", "Накопленная добыча нефти, т", "Дебит нефти, т/сут"),
    ("g16", "wc", "kiz", "16. Обводнённость от КИЗ", "КИЗ, %", "Обводнённость, %"),
    ("g17", "niz_otbor", "wc", "17. Отбор от НИЗ от обводнённости", "Обводнённость, %", "Отбор от НИЗ, %"),
    ("g18", "ratio_dob_nagn", "kin", "18. Соотношение доб/наг от КИН", "КИН, %", "Доб/Нагн"),
    ("g19", "debit_liq", "stepen_prokachki", "19. Дебит жидкости от степени прокачки", "Степень прокачки, %", "Дебит жидкости, т/сут"),
    ("g20", "ratio_dob_nagn", "q_priem_q_liq", "20. Соотношение доб/наг от Qприем/Qжидк", "Qприем/Qжидк", "Доб/Нагн"),
    ("g21", "kompens_tek", "kin", "21. Компенсация текущая от КИН", "КИН, %", "Компенсация текущая, %"),
    ("g22", "kin", "vnf_tek", "22. КИН от LN(ВНФ тек.)", "LN(ВНФ тек.)", "КИН, %"),
]

PRIMARY_ASSET_SPEC_IDS = {"g16", "g20"}
ADDITIONAL_ANALYSIS_SPECS = [spec for spec in ANALYSIS_SPECS if spec[0] not in PRIMARY_ASSET_SPEC_IDS]


def _build_analysis_figure(spec_id, y, x, title, x_title, y_title, d, period_result):
    if spec_id == "g17":
        return niz_otbor_vs_wc_identity(d)
    if spec_id == "g16":
        return segmented_wc_kiz(d, period_result=period_result)
    if spec_id == "g20":
        return ratio_vs_q_by_wc_kiz_periods(d, period_result=period_result)
    return scatter_metric(
        d,
        x=x,
        y=y,
        title=title,
        x_title=x_title,
        y_title=y_title,
        log_x=(spec_id == "g22"),
        show_trendline=(spec_id in {"g13", "g22"}),
    )

