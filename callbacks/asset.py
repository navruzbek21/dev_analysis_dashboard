"""Колбэки вкладки «Анализ по активу»: основные графики, доп. метрики, характеристики вытеснения."""

from __future__ import annotations

import time

from dash import MATCH, Input, Output, ctx

from common import ALL_AREAS_VALUE, ALL_MEST_VALUE, ALL_NGDU_VALUE, _block_filter_key, _filter_key, logger
from figures.asset_tab import (
    ADDITIONAL_ANALYSIS_SPECS,
    _build_analysis_figure,
    fund_dynamics,
    fund_ratio_dynamics,
    pumping_washing_vs_kin,
    ratio_vs_q_by_wc_kiz_periods,
    segmented_wc_kiz,
    tech_dynamics,
)
from figures.displacement import DISPLACEMENT_METHOD_NAMES, displacement_characteristic_figure
from services import aggregation_service, data_service, figure_service, periods_service
from theme import apply_runtime_theme, empty_fig


def register(app):
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
        Input("asset-block-filter", "value"),
        Input("theme-store", "data"),
    )
    def update_asset(selected_mest, selected_ngdu, selected_areas, selected_block, theme):
        started = time.perf_counter()
        mest_key = _filter_key(selected_mest, ALL_MEST_VALUE)
        ngdu_key = _filter_key(selected_ngdu, ALL_NGDU_VALUE)
        area_key = _filter_key(selected_areas, ALL_AREAS_VALUE)
        block_key = _block_filter_key(selected_block)
        d = data_service.get_filtered_year_data(ngdu_key, area_key, mest_key, block_key)
        yearly_agg = aggregation_service.get_asset_year_aggregate(ngdu_key, area_key, mest_key, block_key)
        period_result = periods_service.get_wc_kiz_periods(ngdu_key, area_key, mest_key, block_key, n_periods=6, min_size=5)

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
                    {"selected_mest": mest_key, "selected_blocks": block_key},
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
                    {"selected_mest": mest_key, "selected_blocks": block_key, "n_periods": 6, "min_size": 5},
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
                    {"selected_mest": mest_key, "selected_blocks": block_key, "n_periods": 6, "min_size": 5},
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
        Input("asset-block-filter", "value"),
        Input("theme-store", "data"),
    )
    def update_additional_asset_metrics(n_clicks, selected_mest, selected_ngdu, selected_areas, selected_block, theme):
        if not n_clicks:
            hidden_figs = [empty_fig("Нажмите кнопку «Построить дополнительные метрики»")] * len(ADDITIONAL_ANALYSIS_SPECS)
            return [{"display": "none"}] + hidden_figs

        started = time.perf_counter()
        mest_key = _filter_key(selected_mest, ALL_MEST_VALUE)
        ngdu_key = _filter_key(selected_ngdu, ALL_NGDU_VALUE)
        area_key = _filter_key(selected_areas, ALL_AREAS_VALUE)
        block_key = _block_filter_key(selected_block)
        d = data_service.get_filtered_year_data(ngdu_key, area_key, mest_key, block_key)
        period_result = periods_service.get_wc_kiz_periods(ngdu_key, area_key, mest_key, block_key, n_periods=6, min_size=5)

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



    @app.callback(
        Output({"type": "disp-graph", "method": MATCH}, "figure"),
        Input("build-extra-metrics", "n_clicks"),
        Input({"type": "disp-period", "method": MATCH}, "value"),
        Input("mest-filter", "value"),
        Input("ngdu-filter", "value"),
        Input("area-filter", "value"),
        Input("asset-block-filter", "value"),
        Input("theme-store", "data"),
    )
    def update_displacement_figure(n_clicks, period_value, selected_mest, selected_ngdu, selected_areas, selected_block, theme):
        """Одна карточка характеристики вытеснения на вызов.

        MATCH-колбэк вместо общего на 8 графиков: движение слайдера периода
        пересчитывает только свою характеристику, а не все карточки вкладки.
        """
        if not n_clicks:
            return empty_fig("Нажмите кнопку «Построить дополнительные метрики»")

        outputs = ctx.outputs_list
        if isinstance(outputs, list):
            outputs = outputs[0]
        method = outputs["id"]["method"]
        method_name = DISPLACEMENT_METHOD_NAMES.get(method, method)

        started = time.perf_counter()
        mest_key = _filter_key(selected_mest, ALL_MEST_VALUE)
        ngdu_key = _filter_key(selected_ngdu, ALL_NGDU_VALUE)
        area_key = _filter_key(selected_areas, ALL_AREAS_VALUE)
        block_key = _block_filter_key(selected_block)
        try:
            yearly_agg = aggregation_service.get_asset_year_aggregate(ngdu_key, area_key, mest_key, block_key)
            fig = displacement_characteristic_figure(yearly_agg, method, method_name, period_value)
        except Exception:
            logger.exception("Displacement figure build failed method=%s", method)
            fig = empty_fig(f"Ошибка построения характеристики: {method_name}")
        logger.info(
            "callback=update_displacement_figure method=%s total_ms=%.1f",
            method,
            (time.perf_counter() - started) * 1000,
        )
        return apply_runtime_theme(fig, theme)

