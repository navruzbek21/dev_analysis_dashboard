"""Общие константы и мелкие помощники вкладок дашборда.

Всё, что нужно одновременно фигурам, layout'ам и колбэкам: словари метрик,
служебные значения «все выбраны», нормализация фильтров и KPI-карточки.
"""

from __future__ import annotations

import logging
import re

import numpy as np
import pandas as pd
from dash import dcc, html

from filter_utils import normalize_filter_values
from normalization import ALL_BLOCK_VALUE
from services import data_service
from theme import OP_GREEN, OP_RED, TN_INJ_BLUE, TN_WC_CYAN
from theme import rgba_from_hex as _rgba_from_hex

logger = logging.getLogger(__name__)

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
AREA_CONTOUR_EXTENSIONS = {".asc", ".dat", ".txt", ".irap", ".xyz", ".csv"}

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


def _weighted_wc(frame: pd.DataFrame) -> float:
    """Обводнённость среза, взвешенная по добыче: 100·(Qж − Qн)/Qж по суммам.

    Невзвешенное среднее обводнённостей площадей систематически искажает
    обводнённость актива, когда площади сильно различаются по добыче.
    Фоллбэк — среднее по колонке wc, если добычи в срезе нет.
    """
    if frame.empty:
        return np.nan
    if {"dobycha_liq", "dobycha_nefti"}.issubset(frame.columns):
        liq = pd.to_numeric(frame["dobycha_liq"], errors="coerce").sum(min_count=1)
        oil = pd.to_numeric(frame["dobycha_nefti"], errors="coerce").sum(min_count=1)
        if pd.notna(liq) and pd.notna(oil) and liq > 0:
            return float(100 * (liq - oil) / liq)
    if "wc" in frame.columns:
        return frame["wc"].mean()
    return np.nan


def format_visible_pct_label(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{float(value):+.1f}%"


def _normalize_area_name(value) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"[^0-9a-zа-яё]+", "", text.casefold())


def _split_contour_name(stem: str) -> tuple[str, str | None]:
    match = re.match(r"^(?P<area>.+)_(?P<block>\d+(?:\.\d+)?)$", stem)
    if match:
        return match.group("area"), match.group("block")
    return stem, None


def _normalize_block_value(value) -> str:
    if value in (None, "", ALL_BLOCK_VALUE):
        return ALL_BLOCK_VALUE
    text = str(value).strip()
    return ALL_BLOCK_VALUE if text.lower() == "all" else text


def _block_filter_key(value):
    block = _normalize_block_value(value)
    return [] if block == ALL_BLOCK_VALUE else [block]


def _safe_initial_options(loader, label):
    try:
        return loader()
    except Exception:
        logger.exception("Could not load initial %s options", label)
        return []


ALL_MEST = _safe_initial_options(data_service.get_mest_options, "mest")
ALL_NGDU = _safe_initial_options(lambda: data_service.get_ngdu_options(tuple()), "ngdu")
ALL_AREAS = _safe_initial_options(lambda: data_service.get_area_options(tuple(), tuple()), "area")



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

