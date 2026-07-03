from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots
try:
    from sklearn.linear_model import LinearRegression
except ImportError:
    LinearRegression = None
from dash import Dash, dcc, html, Input, Output, State, ctx
import dash_bootstrap_components as dbc

from cache_backend import check_redis_connection
from config import settings
from db import check_database_connection
from filter_utils import normalize_filter_values
from normalization import AREA_COL_MONTH, AREA_COL_YEAR, MEST_COL, safe_div
from services import aggregation_service, data_service, figure_service, periods_service
import gtm_analysis
import qwen_console


logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)

WELL_COL = "well_uid"

# =============================================================================
# 2. ВИЗУАЛЬНАЯ СИСТЕМА «ТАТНЕФТЬ»
# -----------------------------------------------------------------------------
# Палитра и типографика сняты с презентационного шаблона:
# основной зелёный #008E5B, акцентный зелёный #00B473, красный #D53033,
# светлый фон и шрифт Montserrat.
# =============================================================================

OP_BG = "#F7F8F5"
OP_CARD = "#FFFFFF"
OP_CARD2 = "#F1F5EF"
OP_BORDER = "#DDE7E1"
OP_GRID = "#E5EDE8"
OP_INK = "#1F2B25"
OP_MUTED = "#6F7D76"
OP_GREEN = "#008E5B"
OP_GREEN_DEEP = "#006B45"
OP_GREEN_LIGHT = "#C5E5D7"
OP_AMBER = "#F2B84B"
OP_RED = "#D53033"
PALETTE = [OP_GREEN, "#00B473", OP_RED, "#7CB342", "#44546A", OP_AMBER, "#7E8C86", "#B8D9CC", OP_GREEN_DEEP]
HEAT_SCALE = [[0.0, "#EEF5F1"], [0.45, OP_GREEN_LIGHT], [0.75, OP_GREEN], [1.0, OP_RED]]

THEME_TOKENS = {
    "light": {
        "card": OP_CARD,
        "ink": OP_INK,
        "muted": OP_MUTED,
        "border": OP_BORDER,
        "grid": OP_GRID,
        "legend_bg": "rgba(255,255,255,0)",
        "hover_bg": "#FFFFFF",
    },
    "dark": {
        "card": "#17211D",
        "ink": "#E8F0EC",
        "muted": "#A8B9B0",
        "border": "#314138",
        "grid": "rgba(168, 185, 176, 0.16)",
        "legend_bg": "rgba(23,33,29,0)",
        "hover_bg": "#1F2B26",
    },
}

# Дополнительные цвета для графика технологической динамики
TN_LIQ_GREEN = "#008E5B"      # добыча жидкости
TN_OIL_BURGUNDY = "#7A1F2B"   # добыча нефти
TN_INJ_BLUE = "#1F77B4"       # закачка
TN_WC_CYAN = "#45B8D8"        # обводнённость
TN_DEBIT_LIQ_PURPLE = "#7E57C2"
TN_DEBIT_OIL_RED = "#D53033"
TN_FUND_BLUE = "#2F80ED"

FONT_BODY = "Montserrat, Segoe UI, Arial, sans-serif"
FONT_MONO = "Montserrat, Segoe UI, Arial, sans-serif"

pio.templates["tatneft_light"] = go.layout.Template(
    layout=go.Layout(
        font=dict(family=FONT_BODY, color=OP_INK, size=12),
        paper_bgcolor=OP_CARD,
        plot_bgcolor=OP_CARD,
        colorway=PALETTE,
        margin=dict(l=62, r=28, t=62, b=58),
        title=dict(font=dict(size=14, color=OP_GREEN, family=FONT_BODY), x=0.0, xanchor="left", yanchor="top", y=0.98),
        xaxis=dict(showgrid=False, zeroline=False, linecolor=OP_BORDER, tickcolor=OP_BORDER, tickfont=dict(family=FONT_BODY, size=10.5, color=OP_MUTED), title=dict(font=dict(color=OP_MUTED))),
        yaxis=dict(showgrid=True, gridcolor=OP_GRID, zeroline=False, linecolor=OP_BORDER, tickcolor=OP_BORDER, tickfont=dict(family=FONT_BODY, size=10.5, color=OP_MUTED), title=dict(font=dict(color=OP_MUTED))),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10.5, color=OP_MUTED), bgcolor="rgba(255,255,255,0)"),
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor=OP_GREEN, font=dict(color=OP_INK, family=FONT_BODY, size=11)),
        colorscale=dict(sequential=HEAT_SCALE),
    )
)
pio.templates.default = "tatneft_light"


def normalize_theme(theme: str | None) -> str:
    return "dark" if theme == "dark" else "light"


def apply_runtime_theme(fig, theme: str | None = "light"):
    theme_name = normalize_theme(theme)
    tokens = THEME_TOKENS[theme_name]
    themed = go.Figure(fig)
    themed.update_layout(
        paper_bgcolor=tokens["card"],
        plot_bgcolor=tokens["card"],
        font=dict(family=FONT_BODY, color=tokens["ink"], size=12),
        legend=dict(
            font=dict(color=tokens["muted"]),
            bgcolor=tokens["legend_bg"],
            bordercolor=tokens["border"],
        ),
        hoverlabel=dict(
            bgcolor=tokens["hover_bg"],
            bordercolor=OP_GREEN,
            font=dict(color=tokens["ink"], family=FONT_BODY, size=11),
        ),
    )
    axis_names = [
        axis_name
        for axis_name in themed.to_plotly_json().get("layout", {})
        if axis_name.startswith(("xaxis", "yaxis"))
    ]
    for axis_name in axis_names:
        if axis_name.startswith(("xaxis", "yaxis")):
            themed.update_layout(
                **{
                    axis_name: dict(
                        gridcolor=tokens["grid"],
                        linecolor=tokens["border"],
                        tickcolor=tokens["border"],
                        tickfont=dict(color=tokens["muted"]),
                        title=dict(font=dict(color=tokens["muted"])),
                    )
                }
            )
    for annotation in themed.layout.annotations or ():
        annotation.update(font=dict(color=tokens["muted"]))
    return themed

YEAR_METRICS = {
    "dobycha_nefti": "Добыча нефти, т",
    "dobycha_liq": "Добыча жидкости, т",
    "zakachka": "Закачка воды, м³",
    "wc": "Обводнённость, %",
    "dob_fond": "Действующий добывающий фонд",
    "nagn_fond": "Действующий нагнетательный фонд",
}
CHANGE_PERIODS = {
    "prev": "к прошлому году",
    "3y": "динамика YoY за 3 года",
    "5y": "динамика YoY за 5 лет",
}

DEFAULT_MAIN_METRIC = "dobycha_nefti" if "dobycha_nefti" in YEAR_METRICS else next(iter(YEAR_METRICS))

ALL_MEST_VALUE = "__ALL_MEST__"
ALL_NGDU_VALUE = "__ALL_NGDU__"
ALL_AREAS_VALUE = "__ALL_AREAS__"

KPI_OIL_RED = OP_RED
KPI_LIQ_GREEN = OP_GREEN
KPI_INJ_BLUE = TN_INJ_BLUE
KPI_WC_CYAN = TN_WC_CYAN


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, np.ndarray, pd.Series)):
        return [item for item in value if item is not None]
    return [value]


def _filter_key(value, all_value):
    values = _as_list(value)
    concrete_values = [item for item in values if item != all_value]
    if not concrete_values:
        return tuple()
    return normalize_filter_values(concrete_values)


def _options_with_all(values, all_label, all_value):
    return [{"label": all_label, "value": all_value}] + [{"label": str(value), "value": value} for value in values]


def _selected_or_all(value, allowed_values, all_value):
    values = _as_list(value)
    if not values:
        return [all_value]
    values = [item for item in values if item != all_value]
    allowed = set(allowed_values)
    selected = [item for item in values if item in allowed]
    return selected or [all_value]


def _rgba_from_hex(color, alpha):
    if not isinstance(color, str) or not color.startswith("#") or len(color) != 7:
        return color
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"


def compact(value):
    if value is None or pd.isna(value):
        return "—"
    value = float(value)
    av = abs(value)
    if av >= 1_000_000:
        return f"{value / 1_000_000:.1f} млн"
    if av >= 1_000:
        return f"{value / 1_000:.1f} тыс."
    if av >= 100:
        return f"{value:.0f}"
    return f"{value:.1f}" if value % 1 else f"{value:.0f}"


def format_visible_pct_label(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{float(value):+.1f}%"


def _safe_initial_options(loader, label):
    try:
        return loader()
    except Exception:
        logger.exception("Could not load initial %s options", label)
        return []


ALL_MEST = _safe_initial_options(data_service.get_mest_options, "mest")
ALL_NGDU = _safe_initial_options(lambda: data_service.get_ngdu_options(tuple()), "ngdu")
ALL_AREAS = _safe_initial_options(lambda: data_service.get_area_options(tuple(), tuple()), "area")
LAST_YEAR = None


def filter_year_data(selected_ngdu, selected_areas, selected_mest=()):
    return data_service.get_filtered_year_data(
        _filter_key(selected_ngdu, ALL_NGDU_VALUE),
        _filter_key(selected_areas, ALL_AREAS_VALUE),
        _filter_key(selected_mest, ALL_MEST_VALUE),
    )


def apply_theme(fig, height=None, compact=False):
    # Высота задаётся одновременно контейнеру dcc.Graph и Plotly layout.
    # Заголовки внутри Plotly не используем: название уже есть в шапке карточки.
    layout_kwargs = dict(
        template="tatneft_light",
        autosize=True,
        title=None,
        margin=dict(l=62, r=34, t=30, b=74),
    )
    if compact:
        layout_kwargs.update(
            margin=dict(l=54, r=22, t=24, b=58),
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.24,
                xanchor="left",
                x=0,
                font=dict(size=9.5, color=OP_MUTED),
                bgcolor="rgba(255,255,255,0)",
                itemwidth=30,
            ),
        )
    if height is not None:
        layout_kwargs["height"] = int(str(height).replace("px", ""))
    fig.update_layout(**layout_kwargs)
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    return fig


def empty_fig(title="Нет данных", height=None):
    fig = go.Figure()
    fig.add_annotation(text=title, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font=dict(size=14, color=OP_MUTED))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return apply_theme(fig, height=height)


def sparkline(x, y, color=OP_GREEN):
    fig = go.Figure(go.Scatter(x=list(x), y=list(y), mode="lines", line=dict(color=color, width=2), fill="tozeroy", hoverinfo="skip"))
    if color.startswith("#") and len(color) == 7:
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        fig.update_traces(fillcolor=f"rgba({r},{g},{b},0.12)")
    fig.update_layout(
        height=46,
        margin=dict(l=0, r=0, t=2, b=0),
        paper_bgcolor="rgba(255,255,255,0)",
        plot_bgcolor="rgba(255,255,255,0)",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        showlegend=False,
    )
    return fig


def delta_block(cur, prev, unit_pp=False, positive_is_bad=False):
    if pd.isna(prev) or pd.isna(cur) or (not unit_pp and prev == 0):
        return html.Div("нет базы сравнения", className="metric-delta delta-flat")
    if unit_pp:
        d = cur - prev
        txt = f"{d:+.1f} п.п. к пред. году"
    else:
        d = (cur - prev) / abs(prev) * 100
        txt = f"{d:+.1f}% к пред. году"
    if positive_is_bad:
        cls = "delta-down" if d > 0 else ("delta-up" if d < 0 else "delta-flat")
    else:
        cls = "delta-up" if d > 0 else ("delta-down" if d < 0 else "delta-flat")
    arrow = "▲ " if d > 0 else ("▼ " if d < 0 else "— ")
    return html.Div(arrow + txt, className=f"metric-delta {cls}")


def metric_card(title, value, unit, delta, spark_fig, led="led-green", accent_color=OP_GREEN):
    return html.Div(
        [
            html.Span(className=f"status-led {led}"),
            html.Div(title, className="metric-title"),
            html.Div([value, html.Span(unit, className="metric-unit")], className="metric-value"),
            delta,
            dcc.Graph(figure=spark_fig, config={"displayModeBar": False, "staticPlot": True}, style={"height": "46px", "marginTop": "8px"}),
        ],
        className="metric-card",
        style={"--metric-color": accent_color, "--metric-light": _rgba_from_hex(accent_color, 0.16)},
    )


def bar_last_year(d, metric):
    if d.empty or metric not in d.columns:
        return empty_fig()
    ly = int(d["year"].max())
    x = d[d["year"] == ly].copy()
    fig = px.bar(x, x=AREA_COL_YEAR, y=metric, color=AREA_COL_YEAR, text_auto=".2s")
    fig.update_layout(xaxis_title="Площадь", yaxis_title=YEAR_METRICS[metric])
    return apply_theme(fig)


def line_year_metric(d, metric):
    if d.empty or metric not in d.columns:
        return empty_fig()
    fig = px.line(d, x="year", y=metric, color=AREA_COL_YEAR, markers=True)
    fig.update_layout(xaxis_title="Год", yaxis_title=YEAR_METRICS[metric])
    return apply_theme(fig)


def _aggregate_metric_by_area_year(d, metric):
    """Агрегация выбранного показателя по годам внутри каждой выбранной площади."""
    # Процентные и средние показатели нельзя суммировать.
    mean_metrics = {"wc", "wc_month_avg", "debit_neft", "debit_liq", "debit_vod", "priem"}
    agg_func = "mean" if metric in mean_metrics else "sum"

    dd = (
        d.dropna(subset=[AREA_COL_YEAR, "year", metric])
        .groupby([AREA_COL_YEAR, "year"], as_index=False)
        .agg(value=(metric, agg_func))
        .sort_values([AREA_COL_YEAR, "year"])
    )
    dd["prev_value"] = dd.groupby(AREA_COL_YEAR)["value"].shift(1)
    dd["change_pct"] = 100 * safe_div(dd["value"] - dd["prev_value"], dd["prev_value"])
    dd["year"] = dd["year"].astype(int)
    dd["year_label"] = dd["year"].astype(str)
    return dd


def change_bar(d, metric, period):
    if d.empty or metric not in d.columns:
        return empty_fig()

    ly = int(d["year"].max())

    # Режимы 3y/5y: показываем YoY-изменение отдельно по каждой выбранной площади.
    # Годы выводятся на оси X в порядке возрастания.
    if period in {"3y", "5y"}:
        n_years = 3 if period == "3y" else 5
        dd = _aggregate_metric_by_area_year(d, metric)
        dd = (
            dd[(dd["year"] >= ly - n_years + 1) & (dd["year"] <= ly)]
            .dropna(subset=["change_pct"])
            .sort_values(["year", AREA_COL_YEAR])
        )

        if dd.empty:
            return empty_fig("Недостаточно данных для год-к-году по выбранным площадям")

        year_order = [str(y) for y in sorted(dd["year"].unique())]
        area_order = sorted(dd[AREA_COL_YEAR].dropna().unique())

        fig = px.bar(
            dd,
            x="year_label",
            y="change_pct",
            color=AREA_COL_YEAR,
            barmode="group",
            text=[format_visible_pct_label(v) for v in dd["change_pct"]],
            category_orders={"year_label": year_order, AREA_COL_YEAR: area_order},
            hover_data={
                AREA_COL_YEAR: True,
                "year_label": True,
                "value": ":,.2f",
                "prev_value": ":,.2f",
                "change_pct": ":.2f",
                "year": False,
            },
        )
        fig.update_traces(texttemplate="%{text}", textposition="outside", cliponaxis=False)
        fig.update_layout(
            xaxis_title="Год",
            yaxis_title="Изменение к предыдущему году, %",
            legend_title_text="Площадь",
            bargap=0.22,
            bargroupgap=0.08,
        )
        fig.update_xaxes(type="category", categoryorder="array", categoryarray=year_order)
        fig.add_hline(y=0, line_width=1, line_dash="dot", line_color=OP_MUTED)
        return apply_theme(fig)

    # Режим prev оставляем как было: срез последнего года по площадям к предыдущему году.
    rows = []
    for area, g in d.groupby(AREA_COL_YEAR):
        g = g.sort_values("year")
        curr = g.loc[g["year"] == ly, metric]
        if curr.empty:
            continue
        curr = curr.iloc[0]
        base_s = g.loc[g["year"] == ly - 1, metric]
        base = base_s.iloc[0] if not base_s.empty else np.nan
        rows.append({AREA_COL_YEAR: area, "change_pct": 100 * safe_div(pd.Series([curr - base]), pd.Series([base]))[0]})

    dd = pd.DataFrame(rows).dropna(subset=["change_pct"])
    if dd.empty:
        return empty_fig("Недостаточно данных для сравнения")

    fig = px.bar(dd, x=AREA_COL_YEAR, y="change_pct", color=AREA_COL_YEAR, text=[format_visible_pct_label(v) for v in dd["change_pct"]])
    fig.update_traces(texttemplate="%{text}", textposition="outside", cliponaxis=False)
    fig.update_layout(
        xaxis_title="Площадь",
        yaxis_title="Изменение, %",
    )
    fig.add_hline(y=0, line_width=1, line_dash="dot", line_color=OP_MUTED)
    return apply_theme(fig)


def crossplot_debit_wc(d):
    if d.empty:
        return empty_fig()
    ly = int(d["year"].max())
    x = d[d["year"] == ly].copy()
    if "debit_neft" not in x.columns:
        return empty_fig("Нет данных по debit_neft")
    x["wc_plot"] = x["wc"].combine_first(x["wc_month_avg"]) if "wc_month_avg" in x.columns and "wc" in x.columns else x.get("wc", np.nan)
    size_col = "dobycha_nefti" if "dobycha_nefti" in x.columns else None
    fig = px.scatter(
        x,
        x="wc_plot",
        y="debit_neft",
        color=AREA_COL_YEAR,
        size=size_col,
        hover_data=[c for c in [AREA_COL_YEAR, "ngdu", "dobycha_nefti", "debit_liq"] if c in x.columns],
        labels={"wc_plot": "Средняя обводнённость, %", "debit_neft": "Средний дебит нефти, т/сут"},
    )
    fig.update_layout()
    return apply_theme(fig)


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


DISPLACEMENT_CHARACTERISTICS = {
    "pirverdyan": {
        "x_column": "dobycha_liq_cum",
        "x_transform": "inv_sqrt",
        "y_column": "dobycha_nefti_cum",
        "x_title": "1 / √Qж нак.",
        "y_title": "Qн нак., т",
        "formula": "Qн = A + B / √Qж",
    },
    "wor": {
        "x_column": "dobycha_nefti_cum",
        "y_column": "vnf_tek",
        "y_transform": "ln",
        "x_title": "Qн нак., т",
        "y_title": "LN(ВНФ тек.)",
        "formula": "LN(ВНФ) = A + B · Qн",
    },
    "kambarov": {
        "x_column": "dobycha_liq_cum",
        "x_transform": "inverse",
        "y_column": "dobycha_nefti_cum",
        "x_title": "1 / Qж нак.",
        "y_title": "Qн нак., т",
        "formula": "Qн = A + B / Qж",
    },
    "sazonov": {
        "x_column": "dobycha_liq_cum",
        "x_transform": "ln",
        "y_column": "dobycha_nefti_cum",
        "x_title": "LN(Qж нак.)",
        "y_title": "Qн нак., т",
        "formula": "Qн = A + B · LN(Qж)",
    },
    "maximov": {
        "x_column": "dobycha_vody_cum",
        "x_transform": "ln",
        "y_column": "dobycha_nefti_cum",
        "x_title": "LN(Qв нак.)",
        "y_title": "Qн нак., т",
        "formula": "Qн = A + B · LN(Qв)",
    },
}


def _transform_displacement_series(series, transform):
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if transform == "ln":
        return np.log(values.where(values > 0))
    if transform == "inverse":
        return 1 / values.where(values > 0)
    if transform == "inv_sqrt":
        return 1 / np.sqrt(values.where(values > 0))
    return values


def _normalize_year_bound(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def displacement_characteristic(d, method_key, title, year_start=None, year_end=None):
    """График характеристики вытеснения по выбранной площади/фильтру."""
    config = DISPLACEMENT_CHARACTERISTICS[method_key]
    x_col = config["x_column"]
    y_col = config["y_column"]
    required = [x_col, y_col, AREA_COL_YEAR, "year"]
    miss = [c for c in required if c not in d.columns]
    if d.empty or miss:
        return empty_fig(f"Нет данных: {', '.join(miss)}", height=440)

    year_start = _normalize_year_bound(year_start)
    year_end = _normalize_year_bound(year_end)
    if year_start is not None and year_end is not None and year_start > year_end:
        year_start, year_end = year_end, year_start

    dd = d[required + [c for c in ["ngdu", "mest"] if c in d.columns]].copy()
    dd["year"] = pd.to_numeric(dd["year"], errors="coerce")
    if year_start is not None:
        dd = dd[dd["year"] >= year_start]
    if year_end is not None:
        dd = dd[dd["year"] <= year_end]
    if dd.empty:
        return empty_fig("Нет точек в выбранном периоде", height=440)

    dd["x_value"] = _transform_displacement_series(dd[x_col], config.get("x_transform"))
    dd["y_value"] = _transform_displacement_series(dd[y_col], config.get("y_transform"))
    dd = dd.replace([np.inf, -np.inf], np.nan).dropna(subset=["x_value", "y_value"]).sort_values([AREA_COL_YEAR, "year"])
    if dd.empty:
        return empty_fig("Нет точек после фильтрации", height=440)

    hover_data = {
        "year": True,
        "x_value": ":.4f",
        "y_value": ":.2f",
        AREA_COL_YEAR: True,
    }
    if "ngdu" in dd.columns:
        hover_data["ngdu"] = True
    if "mest" in dd.columns:
        hover_data["mest"] = True

    fig = px.scatter(
        dd,
        x="x_value",
        y="y_value",
        color=AREA_COL_YEAR,
        hover_data=hover_data,
        trendline="ols",
        labels={
            "x_value": config["x_title"],
            "y_value": config["y_title"],
            AREA_COL_YEAR: "Площадь",
            "year": "Год",
            "ngdu": "НГДУ",
            "mest": "Месторождение",
        },
    )
    fig.update_traces(marker=dict(size=7, opacity=0.84), selector=dict(mode="markers"))
    for tr in fig.data:
        if getattr(tr, "mode", None) == "lines":
            tr.showlegend = False
            tr.line.width = 1.6
            tr.line.dash = "dash"
    period_label = ""
    if year_start is not None or year_end is not None:
        period_label = f"; период: {year_start or '…'}–{year_end or '…'}"
    fig.update_layout(
        title=dict(text=f"{title}<br><sup>{config['formula']}{period_label}</sup>"),
        xaxis_title=config["x_title"],
        yaxis_title=config["y_title"],
    )
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

def compute_wc_kiz_periods(d, n_periods=6, min_size=5):
    """Возвращает данные с периодами разработки, рассчитанными по зависимости wc = a + b * kiz.

    Периоды считаются один раз и могут использоваться в разных карточках:
    - g16: Обводнённость от КИЗ;
    - g20: Доб/наг от Qприем/Qжидк, окраска точек по тем же периодам.
    """
    required = ["year", "kiz", "wc"]
    miss = [c for c in required if c not in d.columns]
    if d.empty or miss:
        return pd.DataFrame(), [], miss

    keep_cols = ["year", "kiz", "wc", AREA_COL_YEAR]
    if "ngdu" in d.columns:
        keep_cols.append("ngdu")

    df_seg = d[keep_cols].copy()
    df_seg["__src_index"] = d.index
    df_seg = df_seg.dropna(subset=["year", "kiz", "wc"]).copy()
    if df_seg.empty:
        return pd.DataFrame(), [], []

    df_seg["year"] = pd.to_numeric(df_seg["year"], errors="coerce")
    df_seg["kiz"] = pd.to_numeric(df_seg["kiz"], errors="coerce")
    df_seg["wc"] = pd.to_numeric(df_seg["wc"], errors="coerce")
    df_seg = (
        df_seg
        .dropna(subset=["year", "kiz", "wc"])
        .sort_values(["year", AREA_COL_YEAR])
        .reset_index(drop=True)
    )
    if df_seg.empty:
        return pd.DataFrame(), [], []

    def segment_sse(data, start, end):
        """Ошибка линейной регрессии wc = a + b * kiz на участке [start, end)."""
        part = data.iloc[start:end]
        x = part["kiz"].to_numpy(dtype=float)
        y = part["wc"].to_numpy(dtype=float)

        if len(part) < 2:
            return 0.0

        if LinearRegression is not None:
            model = LinearRegression()
            model.fit(x.reshape(-1, 1), y)
            y_pred = model.predict(x.reshape(-1, 1))
        else:
            # Fallback без sklearn: обычная МНК-регрессия y = a + b*x.
            X = np.column_stack([np.ones(len(x)), x])
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            y_pred = X @ coef

        return float(np.sum((y - y_pred) ** 2))

    def find_best_segments(data, n_segments=6, min_size=5):
        """Оптимальное разбиение временного ряда на n_segments периодов."""
        n = len(data)
        n_segments = int(max(1, min(n_segments, n // min_size))) if n >= min_size else 1
        min_size_eff = min_size if n >= min_size else max(1, n)

        if n_segments == 1:
            return [(0, n)]

        sse = np.full((n + 1, n + 1), np.inf)
        for i in range(n):
            for j in range(i + min_size_eff, n + 1):
                sse[i, j] = segment_sse(data, i, j)

        dp = np.full((n_segments + 1, n + 1), np.inf)
        prev = np.full((n_segments + 1, n + 1), -1, dtype=int)
        dp[0, 0] = 0.0

        for k in range(1, n_segments + 1):
            j_min = k * min_size_eff
            for j in range(j_min, n + 1):
                best_value = np.inf
                best_i = -1
                i_min = (k - 1) * min_size_eff
                i_max = j - min_size_eff + 1
                for i in range(i_min, i_max):
                    value = dp[k - 1, i] + sse[i, j]
                    if value < best_value:
                        best_value = value
                        best_i = i
                dp[k, j] = best_value
                prev[k, j] = best_i

        if prev[n_segments, n] < 0:
            return [(0, n)]

        segments = []
        j = n
        for k in range(n_segments, 0, -1):
            i = prev[k, j]
            if i < 0:
                return [(0, n)]
            segments.append((i, j))
            j = i

        return segments[::-1]

    segments = find_best_segments(df_seg, n_segments=n_periods, min_size=min_size)

    df_seg["period_number"] = np.nan
    for period_num, (start, end) in enumerate(segments, start=1):
        df_seg.loc[start:end - 1, "period_number"] = period_num
    df_seg["period_number"] = df_seg["period_number"].astype(int)

    period_info = (
        df_seg.groupby("period_number", as_index=False)
        .agg(year_start=("year", "min"), year_end=("year", "max"))
        .sort_values("period_number")
    )
    period_info["period"] = period_info.apply(
        lambda row: f"Период {int(row['period_number'])}: {int(row['year_start'])}-{int(row['year_end'])} гг.",
        axis=1,
    )
    df_seg = df_seg.merge(period_info[["period_number", "period"]], on="period_number", how="left")
    return df_seg, segments, []


def segmented_wc_kiz(d, n_periods=6, min_size=5, period_result=None):
    """Карточка 16: Обводнённость от КИЗ с оптимальным разбиением на периоды."""
    if period_result is None:
        df_seg, segments, miss = compute_wc_kiz_periods(d, n_periods=n_periods, min_size=min_size)
    else:
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
        df_periods, _segments, period_miss = compute_wc_kiz_periods(d)
    else:
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
    ("g_disp_pirverdyan", None, None, "23. Характеристика вытеснения по Пирвердяну", "1 / √Qж нак.", "Qн нак., т"),
    ("g_disp_wor", None, None, "24. Характеристика по водонефтяному фактору", "Qн нак., т", "LN(ВНФ тек.)"),
    ("g_disp_kambarov", None, None, "25. Характеристика вытеснения по Камбарову", "1 / Qж нак.", "Qн нак., т"),
    ("g_disp_sazonov", None, None, "26. Характеристика вытеснения по Сазонову", "LN(Qж нак.)", "Qн нак., т"),
    ("g_disp_maximov", None, None, "27. Характеристика вытеснения по Максимову", "LN(Qв нак.)", "Qн нак., т"),
]

PRIMARY_ASSET_SPEC_IDS = {"g16", "g20"}
ADDITIONAL_ANALYSIS_SPECS = [spec for spec in ANALYSIS_SPECS if spec[0] not in PRIMARY_ASSET_SPEC_IDS]


def filters_layout():
    """Глобальные фильтры, влияющие на вкладки дашборда."""
    return html.Div(
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.Label("Месторождение"),
                        dcc.Dropdown(
                            id="mest-filter",
                            options=_options_with_all(ALL_MEST, "Все месторождения", ALL_MEST_VALUE),
                            value=[ALL_MEST_VALUE],
                            multi=True,
                            persistence=True,
                        ),
                    ],
                    lg=3,
                    md=6,
                ),
                dbc.Col(
                    [
                        html.Label("НГДУ"),
                        dcc.Dropdown(
                            id="ngdu-filter",
                            options=_options_with_all(ALL_NGDU, "Все НГДУ", ALL_NGDU_VALUE),
                            value=[ALL_NGDU_VALUE],
                            multi=True,
                            persistence=True,
                        ),
                    ],
                    lg=3,
                    md=6,
                ),
                dbc.Col(
                    [
                        html.Label("Площадь"),
                        dcc.Dropdown(
                            id="area-filter",
                            options=_options_with_all(ALL_AREAS, "Все площади", ALL_AREAS_VALUE),
                            value=[ALL_AREAS_VALUE],
                            multi=True,
                            persistence=True,
                        ),
                    ],
                    lg=4,
                    md=8,
                ),
                dbc.Col(
                    [
                        html.Label("Фильтры"),
                        html.Button("Сбросить", id="reset-filters", n_clicks=0, className="btn-reset"),
                    ],
                    lg=2,
                    md=4,
                ),
            ],
            className="g-3",
        ),
        className="control-panel mb-4",
    )


def main_tab_filters_layout():
    """Фильтры, применяемые только к вкладке «Основные показатели»."""
    return html.Div(
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.Label("Показатель"),
                        dcc.Dropdown(
                            id="main-metric",
                            options=[{"label": v, "value": k} for k, v in YEAR_METRICS.items()],
                            value=DEFAULT_MAIN_METRIC,
                            clearable=False,
                        ),
                    ],
                    md=6,
                ),
                dbc.Col(
                    [
                        html.Label("Сравнение"),
                        dcc.Dropdown(
                            id="change-period",
                            options=[{"label": v, "value": k} for k, v in CHANGE_PERIODS.items()],
                            value="prev",
                            clearable=False,
                        ),
                    ],
                    md=6,
                ),
            ],
            className="g-3",
        ),
        className="control-panel main-tab-controls mb-4",
    )


def graph_card(title, graph_id, height="380px", compact=False):
    # style["height"] задаёт реальную высоту DOM-контейнера,
    # а не только CSS-переменную. Так Dash/Plotly корректнее пересчитывают размер.
    return html.Div(
        [
            html.Div(title, className="section-caption"),
            dcc.Graph(
                id=graph_id,
                className="dash-chart compact-chart" if compact else "dash-chart",
                style={"height": height, "width": "100%"},
                responsive=True,
                config={"responsive": True, "displayModeBar": False},
            ),
        ],
        className="panel-card",
    )


def main_tab_layout():
    return html.Div(
        [
            main_tab_filters_layout(),
            dbc.Row(
                [
                    dbc.Col(graph_card("Показатель за последний год по площадям", "main-bar"), lg=6, className="mb-4"),
                    dbc.Col(graph_card("Динамика показателя по годам", "main-line"), lg=6, className="mb-4"),
                ]
            ),
            dbc.Row(
                [
                    dbc.Col(graph_card("Изменение показателя", "main-change"), lg=6, className="mb-4"),
                    dbc.Col(graph_card("Дебит нефти vs обводнённость", "main-cross"), lg=6, className="mb-4"),
                ]
            ),
        ]
    )


def asset_tab_layout():
    return html.Div(
        [
            dbc.Row([dbc.Col(graph_card("1. Динамика основных технологических показателей разработки", "g01", "650px"), lg=12, className="mb-4")]),
            dbc.Row(
                [
                    dbc.Col(graph_card("2. Динамика действующего фонда", "g02"), lg=6, className="mb-4"),
                    dbc.Col(graph_card("3. Динамика соотношения фонда", "g03"), lg=6, className="mb-4"),
                ]
            ),
            dbc.Row(
                [
                    dbc.Col(graph_card("16. Обводнённость от КИЗ", "g16", "440px", compact=True), lg=6, md=12, className="mb-4"),
                    dbc.Col(graph_card("17. Соотношение доб/наг от Qприем/Qжидк", "g20", "440px", compact=True), lg=6, md=12, className="mb-4"),
                ]
            ),
            dbc.Row([dbc.Col(graph_card("11. Степень прокачки/промывки и темпы от КИН", "g11", "560px"), lg=12, className="mb-4")]),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Label("Период характеристик вытеснения: с"),
                            dcc.Input(
                                id="displacement-year-start",
                                type="number",
                                min=1900,
                                max=2200,
                                step=1,
                                placeholder="2020",
                                className="form-control",
                            ),
                        ],
                        lg=3,
                        md=6,
                        className="mb-3",
                    ),
                    dbc.Col(
                        [
                            html.Label("по"),
                            dcc.Input(
                                id="displacement-year-end",
                                type="number",
                                min=1900,
                                max=2200,
                                step=1,
                                placeholder="2025",
                                className="form-control",
                            ),
                        ],
                        lg=3,
                        md=6,
                        className="mb-3",
                    ),
                    dbc.Col(
                        html.Div(
                            html.Button("Построить дополнительные метрики", id="build-extra-metrics", n_clicks=0, className="btn-reset extra-metrics-button"),
                            className="extra-metrics-actions",
                        ),
                        lg=6,
                        className="mb-3",
                    ),
                ],
                align="end",
                className="mb-1",
            ),
            html.Div(
                [
                    dbc.Row(
                        [
                            dbc.Col(graph_card(spec[3], spec[0], "440px", compact=True), lg=6, md=12, className="mb-4")
                            for spec in ADDITIONAL_ANALYSIS_SPECS
                        ]
                    ),
                ],
                id="additional-metrics-container",
                style={"display": "none"},
            ),
        ]
    )


app = Dash(
    __name__,
    assets_folder="assets",
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
)
app.title = "Дашборд разработки · Татнефть"
app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    </head>
    <body>
        {%app_entry%}
        <footer>{%config%}{%scripts%}{%renderer%}</footer>
    </body>
</html>
"""
server = app.server
qwen_console.register_routes(server)
gtm_analysis.register_callbacks(app)


@server.route("/health")
def health():
    return {"status": "ok", "data_source": settings.data_source}


@server.route("/ready")
def ready():
    db_ok = True if settings.is_parquet else check_database_connection()
    redis_ok = check_redis_connection()
    try:
        dataset_version = data_service.get_dataset_version_cached()
    except Exception:
        logger.exception("Dataset version readiness check failed")
        dataset_version = None
    status_code = 200 if db_ok and dataset_version else 503
    return {
        "status": "ready" if status_code == 200 else "not_ready",
        "database": db_ok,
        "redis": redis_ok,
        "dataset_version": dataset_version,
    }, status_code

app.layout = html.Div(
    [
        dcc.Store(id="theme-store", storage_type="local", data="light"),
        html.Div(
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.H1([html.Span("Группа Татнефть"), html.Span(" · разработка месторождения", className="accent")], className="brand-title"),
                            html.Div("Добыча · закачка · обводнённость · фонд · КИН/КИЗ", className="brand-subtitle"),
                        ],
                        md=7,
                    ),
                    dbc.Col(
                        html.Div(
                            [
                                html.Button(
                                    "Темная тема",
                                    id="theme-toggle",
                                    n_clicks=0,
                                    className="theme-toggle",
                                    title="Переключить тему",
                                    **{"aria-label": "Переключить темный режим"},
                                ),
                                html.Div(id="dataset-badge", className="dataset-badge"),
                            ],
                            className="topbar-actions",
                        ),
                        md=5,
                        className="text-end",
                    ),
                ],
                align="center",
            ),
            className="topbar",
        ),
        dbc.Container(
            [
                filters_layout(),
                html.Div(id="executive-kpi", className="mb-4"),
                dbc.Tabs(
                    id="scenario-tabs",
                    active_tab="tab-main",
                    className="mb-3",
                    children=[
                        dbc.Tab(label="Основные показатели", tab_id="tab-main"),
                        dbc.Tab(label="Анализ по активу", tab_id="tab-asset"),
                        dbc.Tab(label="Анализ эффективности ГТМ", tab_id="tab-gtm"),
                        dbc.Tab(label="Консоль Qwen", tab_id="tab-qwen"),
                    ],
                ),
                dcc.Loading(html.Div(id="scenario-content"), type="circle", color=OP_GREEN),
            ],
            fluid=True,
            className="py-4 px-4",
        ),
    ],
    id="app-shell",
    className="shell theme-light",
)


@app.callback(
    Output("theme-store", "data"),
    Input("theme-toggle", "n_clicks"),
    State("theme-store", "data"),
    prevent_initial_call=True,
)
def toggle_theme(_clicks, current_theme):
    return "light" if normalize_theme(current_theme) == "dark" else "dark"


@app.callback(
    Output("app-shell", "className"),
    Output("theme-toggle", "children"),
    Output("theme-toggle", "title"),
    Input("theme-store", "data"),
)
def apply_app_theme(theme):
    theme_name = normalize_theme(theme)
    is_dark = theme_name == "dark"
    return (
        f"shell theme-{theme_name}",
        "Светлая тема" if is_dark else "Темная тема",
        "Переключить на светлую тему" if is_dark else "Переключить на темную тему",
    )


@app.callback(
    Output("mest-filter", "options"),
    Output("mest-filter", "value"),
    Output("ngdu-filter", "options"),
    Output("ngdu-filter", "value"),
    Output("area-filter", "options"),
    Output("area-filter", "value"),
    Output("scenario-tabs", "active_tab"),
    Input("mest-filter", "value"),
    Input("ngdu-filter", "value"),
    Input("area-filter", "value"),
    Input("reset-filters", "n_clicks"),
    Input("scenario-tabs", "active_tab"),
)
def sync_global_filters(selected_mest, selected_ngdu, selected_areas, _reset_clicks, active_tab):
    trigger = ctx.triggered_id

    if trigger == "reset-filters":
        selected_mest = [ALL_MEST_VALUE]
        selected_ngdu = [ALL_NGDU_VALUE]
        selected_areas = [ALL_AREAS_VALUE]
        active_tab = "tab-main"

    mest_values = data_service.get_mest_options()
    mest_value = _selected_or_all(selected_mest, mest_values, ALL_MEST_VALUE)
    mest_key = _filter_key(mest_value, ALL_MEST_VALUE)

    ngdu_values = data_service.get_ngdu_options(mest_key)
    ngdu_value = _selected_or_all(selected_ngdu, ngdu_values, ALL_NGDU_VALUE)
    ngdu_key = _filter_key(ngdu_value, ALL_NGDU_VALUE)

    area_values = data_service.get_area_options(ngdu_key, mest_key)
    area_value = _selected_or_all(selected_areas, area_values, ALL_AREAS_VALUE)
    area_key = _filter_key(area_value, ALL_AREAS_VALUE)

    if trigger == "area-filter" and len(area_key) == 1:
        active_tab = "tab-asset"
    elif trigger == "reset-filters":
        active_tab = "tab-main"

    if active_tab == "tab-asset":
        selected_area_values = [
            item
            for item in _as_list(selected_areas)
            if item != ALL_AREAS_VALUE and item in set(area_values)
        ]
        if trigger == "area-filter" and selected_area_values:
            area_value = [selected_area_values[-1]]
        elif len(_filter_key(area_value, ALL_AREAS_VALUE)) != 1:
            area_value = [area_values[0]] if area_values else [ALL_AREAS_VALUE]
        area_key = _filter_key(area_value, ALL_AREAS_VALUE)

    return (
        _options_with_all(mest_values, "Все месторождения", ALL_MEST_VALUE),
        mest_value,
        _options_with_all(ngdu_values, "Все НГДУ", ALL_NGDU_VALUE),
        ngdu_value,
        _options_with_all(area_values, "Все площади", ALL_AREAS_VALUE),
        area_value,
        active_tab,
    )


@app.callback(
    Output("dataset-badge", "children"),
    Output("executive-kpi", "children"),
    Input("mest-filter", "value"),
    Input("ngdu-filter", "value"),
    Input("area-filter", "value"),
)
def update_header(selected_mest, selected_ngdu, selected_areas):
    started = time.perf_counter()
    mest_key = _filter_key(selected_mest, ALL_MEST_VALUE)
    ngdu_key = _filter_key(selected_ngdu, ALL_NGDU_VALUE)
    area_key = _filter_key(selected_areas, ALL_AREAS_VALUE)
    d = data_service.get_filtered_year_data(ngdu_key, area_key, mest_key)
    if d.empty:
        return [html.Span(className="live-dot"), "нет данных"], dbc.Row(
            [dbc.Col(html.Div([html.Div("Нет данных", className="metric-title"), html.Div("—", className="metric-value")], className="metric-card"), md=12)]
        )

    ly = int(d["year"].max())
    cur = d[d["year"] == ly]
    prev = d[d["year"] == ly - 1]

    oil = cur["dobycha_nefti"].sum() if "dobycha_nefti" in cur.columns else np.nan
    liq = cur["dobycha_liq"].sum() if "dobycha_liq" in cur.columns else np.nan
    inj = cur["zakachka"].sum() if "zakachka" in cur.columns else np.nan
    wc_val = cur["wc"].mean() if "wc" in cur.columns else np.nan

    p_oil = prev["dobycha_nefti"].sum() if "dobycha_nefti" in prev.columns and not prev.empty else np.nan
    p_liq = prev["dobycha_liq"].sum() if "dobycha_liq" in prev.columns and not prev.empty else np.nan
    p_inj = prev["zakachka"].sum() if "zakachka" in prev.columns and not prev.empty else np.nan
    p_wc = prev["wc"].mean() if "wc" in prev.columns and not prev.empty else np.nan

    by_year = aggregation_service.get_header_year_aggregate(ngdu_key, area_key, mest_key).rename(
        columns={"dobycha_nefti": "oil", "dobycha_liq": "liq", "zakachka": "inj"}
    )

    led_oil = "led-green" if pd.isna(p_oil) or oil >= p_oil else "led-red"
    led_wc = "led-green" if pd.notna(wc_val) and wc_val < 60 else ("led-amber" if pd.notna(wc_val) and wc_val < 80 else "led-red")

    ngdu_label = f"{len(ngdu_key)} НГДУ" if ngdu_key else "Все НГДУ"
    mest_label = f"{len(mest_key)} мест." if mest_key else "Все месторождения"
    badge = [html.Span(className="live-dot"), f"{ly} · {cur[AREA_COL_YEAR].nunique()} площ. · {ngdu_label} · {mest_label}"]
    cards = dbc.Row(
        [
            dbc.Col(metric_card("Добыча нефти", compact(oil), "т", delta_block(oil, p_oil), sparkline(by_year["year"], by_year["oil"], KPI_OIL_RED), led_oil, KPI_OIL_RED), lg=3, md=6, className="mb-3"),
            dbc.Col(metric_card("Добыча жидкости", compact(liq), "т", delta_block(liq, p_liq), sparkline(by_year["year"], by_year["liq"], KPI_LIQ_GREEN), "led-green", KPI_LIQ_GREEN), lg=3, md=6, className="mb-3"),
            dbc.Col(metric_card("Закачка воды", compact(inj), "м³", delta_block(inj, p_inj), sparkline(by_year["year"], by_year["inj"], KPI_INJ_BLUE), "led-green", KPI_INJ_BLUE), lg=3, md=6, className="mb-3"),
            dbc.Col(metric_card("Обводнённость", compact(wc_val), "%", delta_block(wc_val, p_wc, unit_pp=True, positive_is_bad=True), sparkline(by_year["year"], by_year["wc"], KPI_WC_CYAN), led_wc, KPI_WC_CYAN), lg=3, md=6, className="mb-3"),
        ]
    )
    logger.info(
        "callback=update_header mest_count=%s ngdu_count=%s area_count=%s total_ms=%.1f",
        len(mest_key),
        len(ngdu_key),
        len(area_key),
        (time.perf_counter() - started) * 1000,
    )
    return badge, cards


@app.callback(Output("scenario-content", "children"), Input("scenario-tabs", "active_tab"))
def render_tab(active_tab):
    if active_tab == "tab-gtm":
        return gtm_analysis.layout()
    if active_tab == "tab-qwen":
        return qwen_console.layout()
    if active_tab == "tab-asset":
        return asset_tab_layout()
    return main_tab_layout()


@app.callback(
    Output("main-bar", "figure"),
    Output("main-line", "figure"),
    Output("main-change", "figure"),
    Output("main-cross", "figure"),
    Input("mest-filter", "value"),
    Input("ngdu-filter", "value"),
    Input("area-filter", "value"),
    Input("main-metric", "value"),
    Input("change-period", "value"),
    Input("theme-store", "data"),
)
def update_main(selected_mest, selected_ngdu, selected_areas, metric, period, theme):
    started = time.perf_counter()
    mest_key = _filter_key(selected_mest, ALL_MEST_VALUE)
    ngdu_key = _filter_key(selected_ngdu, ALL_NGDU_VALUE)
    area_key = _filter_key(selected_areas, ALL_AREAS_VALUE)
    d = data_service.get_filtered_year_data(ngdu_key, area_key, mest_key)
    main_change = figure_service.get_cached_figure(
        "main-change",
        ngdu_key,
        area_key,
        {"metric": metric, "period": period, "selected_mest": mest_key},
        lambda: change_bar(d, metric, period),
    )
    logger.info(
        "callback=update_main mest_count=%s ngdu_count=%s area_count=%s metric=%s period=%s total_ms=%.1f",
        len(mest_key),
        len(ngdu_key),
        len(area_key),
        metric,
        period,
        (time.perf_counter() - started) * 1000,
    )
    return (
        apply_runtime_theme(bar_last_year(d, metric), theme),
        apply_runtime_theme(line_year_metric(d, metric), theme),
        apply_runtime_theme(main_change, theme),
        apply_runtime_theme(crossplot_debit_wc(d), theme),
    )


def _build_analysis_figure(spec_id, y, x, title, x_title, y_title, d, period_result, displacement_year_start=None, displacement_year_end=None):
    if spec_id == "g17":
        return niz_otbor_vs_wc_identity(d)
    if spec_id == "g16":
        return segmented_wc_kiz(d, period_result=period_result)
    if spec_id == "g20":
        return ratio_vs_q_by_wc_kiz_periods(d, period_result=period_result)
    if spec_id.startswith("g_disp_"):
        return displacement_characteristic(
            d,
            spec_id.removeprefix("g_disp_"),
            title,
            year_start=displacement_year_start,
            year_end=displacement_year_end,
        )
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


@app.callback(
    Output("g01", "figure"),
    Output("g02", "figure"),
    Output("g03", "figure"),
    Output("g16", "figure"),
    Output("g20", "figure"),
    Output("g11", "figure"),
    Input("mest-filter", "value"),
    Input("ngdu-filter", "value"),
    Input("area-filter", "value"),
    Input("theme-store", "data"),
)
def update_asset(selected_mest, selected_ngdu, selected_areas, theme):
    started = time.perf_counter()
    mest_key = _filter_key(selected_mest, ALL_MEST_VALUE)
    ngdu_key = _filter_key(selected_ngdu, ALL_NGDU_VALUE)
    area_key = _filter_key(selected_areas, ALL_AREAS_VALUE)
    d = data_service.get_filtered_year_data(ngdu_key, area_key, mest_key)
    yearly_agg = aggregation_service.get_asset_year_aggregate(ngdu_key, area_key, mest_key)
    period_result = periods_service.get_wc_kiz_periods(ngdu_key, area_key, mest_key, n_periods=6, min_size=5)

    def safe_build(name, builder):
        try:
            return builder()
        except Exception:
            logger.exception("Figure build failed name=%s", name)
            return empty_fig(f"Ошибка построения {name}")

    figs = [
        safe_build(
            "g01",
            lambda: figure_service.get_cached_figure(
                "g01",
                ngdu_key,
                area_key,
                {"selected_mest": mest_key},
                lambda: tech_dynamics(d, yearly_agg),
                use_lock=True,
            ),
        ),
        safe_build("g02", lambda: fund_dynamics(d, yearly_agg)),
        safe_build("g03", lambda: fund_ratio_dynamics(d, yearly_agg)),
        safe_build(
            "g16",
            lambda: figure_service.get_cached_figure(
                "g16",
                ngdu_key,
                area_key,
                {"selected_mest": mest_key, "n_periods": 6, "min_size": 5},
                lambda: segmented_wc_kiz(d, period_result=period_result),
                use_lock=True,
            ),
        ),
        safe_build(
            "g20",
            lambda: figure_service.get_cached_figure(
                "g20",
                ngdu_key,
                area_key,
                {"selected_mest": mest_key, "n_periods": 6, "min_size": 5},
                lambda: ratio_vs_q_by_wc_kiz_periods(d, period_result=period_result),
                use_lock=True,
            ),
        ),
        safe_build("g11", lambda: pumping_washing_vs_kin(d)),
    ]
    logger.info(
        "callback=update_asset mest_count=%s ngdu_count=%s area_count=%s figures=%s total_ms=%.1f",
        len(mest_key),
        len(ngdu_key),
        len(area_key),
        len(figs),
        (time.perf_counter() - started) * 1000,
    )
    return [apply_runtime_theme(fig, theme) for fig in figs]


@app.callback(
    Output("additional-metrics-container", "style"),
    *[Output(spec[0], "figure") for spec in ADDITIONAL_ANALYSIS_SPECS],
    Input("build-extra-metrics", "n_clicks"),
    Input("mest-filter", "value"),
    Input("ngdu-filter", "value"),
    Input("area-filter", "value"),
    Input("displacement-year-start", "value"),
    Input("displacement-year-end", "value"),
    Input("theme-store", "data"),
)
def update_additional_asset_metrics(n_clicks, selected_mest, selected_ngdu, selected_areas, displacement_year_start, displacement_year_end, theme):
    if not n_clicks:
        hidden_figs = [empty_fig("Нажмите кнопку «Построить дополнительные метрики»")] * len(ADDITIONAL_ANALYSIS_SPECS)
        return [{"display": "none"}] + hidden_figs

    started = time.perf_counter()
    mest_key = _filter_key(selected_mest, ALL_MEST_VALUE)
    ngdu_key = _filter_key(selected_ngdu, ALL_NGDU_VALUE)
    area_key = _filter_key(selected_areas, ALL_AREAS_VALUE)
    d = data_service.get_filtered_year_data(ngdu_key, area_key, mest_key)
    yearly_agg = aggregation_service.get_asset_year_aggregate(ngdu_key, area_key, mest_key)
    period_result = periods_service.get_wc_kiz_periods(ngdu_key, area_key, mest_key, n_periods=6, min_size=5)

    def safe_build(name, builder):
        try:
            return builder()
        except Exception:
            logger.exception("Figure build failed name=%s", name)
            return empty_fig(f"Ошибка построения {name}")

    figs = []
    for spec_id, y, x, title, x_title, y_title in ADDITIONAL_ANALYSIS_SPECS:
        figs.append(
            safe_build(
                spec_id,
                lambda spec_id=spec_id, y=y, x=x, title=title, x_title=x_title, y_title=y_title: _build_analysis_figure(
                    spec_id,
                    y,
                    x,
                    title,
                    x_title,
                    y_title,
                    d,
                    period_result,
                    displacement_year_start,
                    displacement_year_end,
                ),
            )
        )
    logger.info(
        "callback=update_additional_asset_metrics mest_count=%s ngdu_count=%s area_count=%s figures=%s total_ms=%.1f",
        len(mest_key),
        len(ngdu_key),
        len(area_key),
        len(figs),
        (time.perf_counter() - started) * 1000,
    )
    return [{"display": "block"}] + [apply_runtime_theme(fig, theme) for fig in figs]


if __name__ == "__main__":
    app.run(debug=settings.app_debug, host=settings.app_host, port=settings.app_port)
