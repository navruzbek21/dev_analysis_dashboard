"""Сборка Dash-приложения: создание app, каркас страницы, роуты и регистрация колбэков.

Код по назначению разнесён по модулям:
- theme.py — палитра и темизация фигур;
- common.py — общие константы и помощники вкладок;
- figures/ — построители графиков (main_tab, asset_tab, displacement);
- layouts.py — layout'ы вкладок и каркас страницы;
- callbacks/ — колбэки, регистрируемые через register(app).
"""

from __future__ import annotations

import logging

import dash_bootstrap_components as dbc
from dash import Dash

import gtm_analysis
import litellm_console
from cache_backend import check_redis_connection
from callbacks import asset as asset_callbacks
from callbacks import filters as filters_callbacks
from callbacks import main as main_callbacks
from callbacks import theme_callbacks

# --- Реэкспорт публичного API для тестов и внешних скриптов -----------------
from common import (  # noqa: F401
    ALL_AREAS_VALUE,
    ALL_MEST_VALUE,
    ALL_NGDU_VALUE,
    YEAR_METRICS,
    compact,
    format_visible_pct_label,
)
from config import settings
from figures.asset_tab import tech_dynamics  # noqa: F401
from figures.displacement import (  # noqa: F401
    DISPLACEMENT_TARGET_VNF,
    _annual_vnf_for_displacement_x,
    _linear_coefficients,
    displacement_characteristic_figure,
    normalize_period_value,
)
from figures.main_tab import area_metric_contour_map, change_bar  # noqa: F401
from layouts import asset_tab_layout, main_tab_layout, shell_layout  # noqa: F401
from normalization import ALL_BLOCK_VALUE, AREA_COL_YEAR  # noqa: F401
from services import data_service

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


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
litellm_console.register_routes(server)

app.layout = shell_layout()

theme_callbacks.register(app)
filters_callbacks.register(app)
main_callbacks.register(app)
asset_callbacks.register(app)
gtm_analysis.register_callbacks(app)


@server.route("/health")
def health():
    return {"status": "ok", "data_source": settings.data_source}


@server.route("/ready")
def ready():
    parquet_ok = True
    redis_ok = check_redis_connection()
    try:
        dataset_version = data_service.get_dataset_version_cached()
    except Exception:
        logger.exception("Dataset version readiness check failed")
        dataset_version = None
    status_code = 200 if parquet_ok and dataset_version else 503
    return {
        "status": "ready" if status_code == 200 else "not_ready",
        "parquet": parquet_ok,
        "redis": redis_ok,
        "dataset_version": dataset_version,
    }, status_code


if __name__ == "__main__":
    app.run(debug=settings.app_debug, host=settings.app_host, port=settings.app_port)
