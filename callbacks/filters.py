"""Колбэки глобальных фильтров, вкладок и выбора блока."""

from __future__ import annotations

from dash import Input, Output, State, ctx, no_update
from dash.exceptions import PreventUpdate

import gtm_analysis
import litellm_console
from common import (
    ALL_AREAS_VALUE,
    ALL_MEST_VALUE,
    ALL_NGDU_VALUE,
    _as_list,
    _block_filter_key,
    _filter_key,
    _normalize_block_value,
    _options_with_all,
    _selected_or_all,
)
from layouts import asset_tab_layout, main_tab_layout
from normalization import ALL_BLOCK_VALUE
from services import data_service


def register(app):
    @app.callback(
        Output("dashboard-analysis-filters", "data"),
        Output("analysis-filter-sync", "children"),
        Input("mest-filter", "value"),
        Input("ngdu-filter", "value"),
        Input("area-filter", "value"),
        Input("selected-block-store", "data"),
    )
    def sync_analysis_filters_store(selected_mest, selected_ngdu, selected_areas, selected_block):
        payload = {
            "mest": _filter_key(selected_mest, ALL_MEST_VALUE),
            "ngdu": _filter_key(selected_ngdu, ALL_NGDU_VALUE),
            "areas": _filter_key(selected_areas, ALL_AREAS_VALUE),
        }
        block_key = _block_filter_key(selected_block)
        if block_key:
            payload["block"] = block_key
        return payload, ""


    @app.callback(
        Output("mest-filter", "options"),
        Output("mest-filter", "value"),
        Output("ngdu-filter", "options"),
        Output("ngdu-filter", "value"),
        Output("area-filter", "options"),
        Output("area-filter", "value"),
        Output("scenario-tabs", "active_tab"),
        Output("selected-block-store", "data"),
        Input("mest-filter", "value"),
        Input("ngdu-filter", "value"),
        Input("area-filter", "value"),
        Input("reset-filters", "n_clicks"),
        Input("scenario-tabs", "active_tab"),
        State("selected-block-store", "data"),
    )
    def sync_global_filters(selected_mest, selected_ngdu, selected_areas, _reset_clicks, active_tab, stored_block):
        trigger = ctx.triggered_id
        selected_block = _normalize_block_value(stored_block)

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
            selected_block = ALL_BLOCK_VALUE
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
            selected_block,
        )


    @app.callback(
        Output("area-filter", "value", allow_duplicate=True),
        Output("scenario-tabs", "active_tab", allow_duplicate=True),
        Output("selected-block-store", "data", allow_duplicate=True),
        Input("main-area-map", "clickData"),
        prevent_initial_call=True,
    )
    def select_area_or_block_from_map(map_click):
        point = (map_click or {}).get("points") or [{}]
        custom = point[0].get("customdata") or []
        if not custom:
            raise PreventUpdate
        selected_block = _normalize_block_value(custom[3] if len(custom) > 3 else ALL_BLOCK_VALUE)
        active_tab = "tab-asset" if selected_block != ALL_BLOCK_VALUE else "tab-main"
        return [custom[0]], active_tab, selected_block


    @app.callback(
        Output("selected-block-store", "data", allow_duplicate=True),
        Input("asset-block-filter", "value"),
        State("selected-block-store", "data"),
        prevent_initial_call=True,
    )
    def sync_selected_block_from_asset_filter(asset_block, stored_block):
        # Store и dropdown блока обновляют друг друга; без проверки на равенство
        # цепочка store -> options/value -> store зацикливается и лишний раз
        # дёргает тяжёлые графики вкладки актива.
        new_value = _normalize_block_value(asset_block)
        if new_value == _normalize_block_value(stored_block):
            raise PreventUpdate
        return new_value


    @app.callback(Output("scenario-content", "children"), Input("scenario-tabs", "active_tab"))
    def render_tab(active_tab):
        if active_tab == "tab-gtm":
            return gtm_analysis.layout()
        if active_tab == "tab-litellm":
            return litellm_console.layout()
        if active_tab == "tab-asset":
            return asset_tab_layout()
        return main_tab_layout()


    @app.callback(
        Output("asset-block-filter", "options"),
        Output("asset-block-filter", "value"),
        Input("mest-filter", "value"),
        Input("ngdu-filter", "value"),
        Input("area-filter", "value"),
        Input("selected-block-store", "data"),
        State("asset-block-filter", "value"),
    )
    def update_asset_block_options(selected_mest, selected_ngdu, selected_areas, selected_block, current_value):
        mest_key = _filter_key(selected_mest, ALL_MEST_VALUE)
        ngdu_key = _filter_key(selected_ngdu, ALL_NGDU_VALUE)
        area_key = _filter_key(selected_areas, ALL_AREAS_VALUE)
        blocks = data_service.get_block_options(ngdu_key, area_key, mest_key)
        options = [{"label": "Вся площадь", "value": ALL_BLOCK_VALUE}] + [{"label": f"Блок {block}", "value": block} for block in blocks]
        selected = _normalize_block_value(selected_block)
        if selected not in {option["value"] for option in options}:
            selected = ALL_BLOCK_VALUE
        # Не переустанавливаем value без необходимости: setProps триггерит
        # колбэки даже при неизменном значении и раскручивает цикл со store.
        if selected == _normalize_block_value(current_value):
            return options, no_update
        return options, selected

