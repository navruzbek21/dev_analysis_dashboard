"""Layout'ы вкладок и каркас страницы."""

from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
from dash import dcc, html

from common import (
    ALL_AREAS,
    ALL_AREAS_VALUE,
    ALL_MEST,
    ALL_MEST_VALUE,
    ALL_NGDU,
    ALL_NGDU_VALUE,
    CHANGE_PERIODS,
    DEFAULT_MAIN_METRIC,
    YEAR_METRICS,
    _options_with_all,
    logger,
)
from figures.asset_tab import ADDITIONAL_ANALYSIS_SPECS
from figures.displacement import DEFAULT_DISPLACEMENT_SLIDER_BOUNDS, DISPLACEMENT_SPECS
from normalization import ALL_BLOCK_VALUE
from services import data_service
from theme import OP_GREEN


def _displacement_slider_bounds() -> tuple[int, int]:
    """Границы слайдеров периода тренда — из фактических лет данных."""
    try:
        d = data_service.get_filtered_year_data((), (), ())
        years = pd.to_numeric(d.get("year"), errors="coerce").dropna()
        if not years.empty:
            return int(years.min()), int(years.max())
    except Exception:
        logger.exception("Could not compute displacement slider bounds")
    return DEFAULT_DISPLACEMENT_SLIDER_BOUNDS


def displacement_card(title, method, slider_bounds=None):
    # id-словари позволяют обновлять каждую характеристику отдельным
    # MATCH-колбэком: движение одного слайдера не пересчитывает соседние карточки.
    slider_min, slider_max = slider_bounds or DEFAULT_DISPLACEMENT_SLIDER_BOUNDS
    default_period = [max(slider_min, slider_max - 5), slider_max]
    return html.Div(
        [
            html.Div(title, className="section-caption"),
            html.Div("Период для построения линии тренда", className="small text-muted mb-2"),
            dcc.RangeSlider(
                id={"type": "disp-period", "method": method},
                min=slider_min,
                max=slider_max,
                step=1,
                value=default_period,
                marks={year: str(year) for year in range(slider_min, slider_max + 1, 5)},
                allowCross=False,
                tooltip={"placement": "bottom", "always_visible": False},
            ),
            dcc.Graph(
                id={"type": "disp-graph", "method": method},
                className="dash-chart compact-chart",
                style={"height": "460px", "width": "100%"},
                responsive=True,
                config={"responsive": True, "displayModeBar": False},
            ),
        ],
        className="panel-card",
    )



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
                    dbc.Col(
                        graph_card("Карта площадей по выбранному показателю", "main-area-map", height="1140px"),
                        lg=6,
                        className="mb-4",
                    ),
                    dbc.Col(
                        [
                            graph_card("Изменение показателя", "main-change"),
                            html.Div(className="mb-4"),
                            graph_card("Динамика показателя по годам", "main-line"),
                            html.Div(className="mb-4"),
                            graph_card("Дебит нефти vs обводнённость", "main-cross"),
                        ],
                        lg=6,
                        className="mb-4",
                    ),


                ]
            ),
        ]
    )


def asset_tab_layout():
    slider_bounds = _displacement_slider_bounds()
    return html.Div(
        [
            html.Div(
                dbc.Row(
                    dbc.Col(
                        [
                            html.Label("Блок/участок площади"),
                            dcc.Dropdown(
                                id="asset-block-filter",
                                options=[{"label": "Вся площадь", "value": ALL_BLOCK_VALUE}],
                                value=ALL_BLOCK_VALUE,
                                clearable=False,
                            ),
                        ],
                        md=4,
                    ),
                    className="g-3",
                ),
                className="control-panel mb-4",
            ),
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
            html.Div(
                html.Button("Построить дополнительные метрики", id="build-extra-metrics", n_clicks=0, className="btn-reset extra-metrics-button"),
                className="extra-metrics-actions mb-4",
            ),
            html.Div(
                [
                    dbc.Row(
                        [
                            dbc.Col(graph_card(spec[3], spec[0], "440px", compact=True), lg=6, md=12, className="mb-4")
                            for spec in ADDITIONAL_ANALYSIS_SPECS
                        ]
                    ),
                    html.Div("Характеристики вытеснения по выбранной площади", className="section-caption mt-3 mb-3"),
                    dbc.Row(
                        [
                            dbc.Col(displacement_card(title, method, slider_bounds), lg=6, md=12, className="mb-4")
                            for _graph_id, title, _method_name, method in DISPLACEMENT_SPECS
                        ]
                    ),
                ],
                id="additional-metrics-container",
                style={"display": "none"},
            ),
        ]
    )




def shell_layout():
    return html.Div(
        [
            dcc.Store(id="theme-store", storage_type="local", data="light"),
            dcc.Store(id="dashboard-analysis-filters", storage_type="local"),
            dcc.Store(id="selected-block-store", storage_type="session", data=ALL_BLOCK_VALUE),
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
                            dbc.Tab(label="Консоль LiteLLM", tab_id="tab-litellm"),
                        ],
                    ),
                    dcc.Loading(html.Div(id="scenario-content"), type="circle", color=OP_GREEN),
                    html.Div(id="analysis-filter-sync", style={"display": "none"}),
                    html.Div(id="theme-broadcast", style={"display": "none"}),
                ],
                fluid=True,
                className="py-4 px-4",
            ),
        ],
        id="app-shell",
        className="shell theme-light",
    )

