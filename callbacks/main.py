"""Колбэки вкладки «Основные показатели» и шапки с KPI."""

from __future__ import annotations

import time

import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
from dash import Input, Output, html

from common import (
    ALL_AREAS_VALUE,
    ALL_MEST_VALUE,
    ALL_NGDU_VALUE,
    KPI_INJ_BLUE,
    KPI_LIQ_GREEN,
    KPI_OIL_RED,
    KPI_WC_CYAN,
    _filter_key,
    _weighted_wc,
    compact,
    delta_block,
    logger,
    metric_card,
)
from figures import main_tab
from figures.main_tab import area_metric_contour_map, change_bar, crossplot_debit_wc, line_year_metric
from normalization import AREA_COL_YEAR, BLOCK_COL, INCLUDE_BLOCK_ROWS_VALUE
from services import aggregation_service, data_service, figure_service
from theme import apply_runtime_theme, sparkline


def register(app):
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

        # min_count=1: сумма полностью пустой колонки должна давать NaN и "—" на
        # карточке, а не вводящий в заблуждение ноль.
        oil = cur["dobycha_nefti"].sum(min_count=1) if "dobycha_nefti" in cur.columns else np.nan
        liq = cur["dobycha_liq"].sum(min_count=1) if "dobycha_liq" in cur.columns else np.nan
        inj = cur["zakachka"].sum(min_count=1) if "zakachka" in cur.columns else np.nan
        wc_val = _weighted_wc(cur)

        p_oil = prev["dobycha_nefti"].sum(min_count=1) if "dobycha_nefti" in prev.columns and not prev.empty else np.nan
        p_liq = prev["dobycha_liq"].sum(min_count=1) if "dobycha_liq" in prev.columns and not prev.empty else np.nan
        p_inj = prev["zakachka"].sum(min_count=1) if "zakachka" in prev.columns and not prev.empty else np.nan
        p_wc = _weighted_wc(prev)

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



    @app.callback(

        Output("main-area-map", "figure"),
        Output("main-change", "figure"),
        Output("main-line", "figure"),
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
        # d_map — надмножество d (плюс строки блоков): одна выборка вместо двух.
        d_map = data_service.get_filtered_year_data(ngdu_key, area_key, mest_key, [INCLUDE_BLOCK_ROWS_VALUE])
        block_text = d_map[BLOCK_COL].astype(str).str.strip().str.lower() if BLOCK_COL in d_map.columns else pd.Series(dtype=str)
        block_rows = d_map[d_map[BLOCK_COL].notna() & ~block_text.isin(["", "all"])].copy() if BLOCK_COL in d_map.columns else pd.DataFrame()
        # Как в _filter_area_level_rows: если строк уровня площади нет вовсе,
        # работаем по всем строкам, а не по пустому срезу.
        area_level_rows = d_map[~d_map.index.isin(block_rows.index)]
        d = area_level_rows if not area_level_rows.empty else d_map
        d_visual = block_rows if len(area_key) == 1 and not block_rows.empty else d

        # Кэшируем «сырые» (нетемизированные) версии всех четырёх фигур: тогда
        # переключение темы и повторные заходы обслуживаются из кэша, а тема
        # накладывается поверх дёшево.
        base_params = {"metric": metric, "selected_mest": mest_key, "block_visual": not block_rows.empty}

        def cached(name, extra, builder):
            return figure_service.get_cached_figure(name, ngdu_key, area_key, {**base_params, **extra}, builder)

        area_map = cached(
            "main-area-map",
            {"contours": list(main_tab._contours_signature())},
            lambda: area_metric_contour_map(d_map, metric, area_key),
        )
        main_change = cached("main-change", {"period": period}, lambda: change_bar(d_visual, metric, period))
        main_line = cached("main-line", {}, lambda: line_year_metric(d_visual, metric))
        main_cross = cached("main-cross", {}, lambda: crossplot_debit_wc(d_visual))
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
            apply_runtime_theme(area_map, theme),
            apply_runtime_theme(main_change, theme),
            apply_runtime_theme(main_line, theme),
            apply_runtime_theme(main_cross, theme),
        )

