"""
Оптимизированный Dash-дашборд анализа эффективности ГТМ.

Ожидается, что до запуска приложения уже определены датафреймы:
- result_df
- df_ploshad_year
- df_itog_gtm_2
- factor_analysis_df

Ключевые улучшения относительно исходной версии:
1) расчёт Δqliq/Δqoil по ГТМ вынесен в precompute_gtm_level() и выполняется один раз;
2) общие стили графиков вынесены в функции;
3) исправлена гистограмма для режима plosh='ALL';
4) DataTable обновляет и data, и columns;
5) добавлены KPI-карточки;
6) улучшены hover, легенды, форматирование, адаптивная сетка;
7) меньше копирований датафреймов и повторяющихся groupby/pivot;
8) добавлен визуальный стиль по шаблону презентации Группы «Татнефть»: зелёная
   палитра, фирменные акценты, мягкие карточки и аккуратные stacked/grouped charts.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from dash import dcc, html, Input, Output, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# -----------------------------------------------------------------------------
# Константы визуализации
# -----------------------------------------------------------------------------
ALL = "ALL"
APP_TITLE = "Анализ эффективности ГТМ"
APP_SUBTITLE = "Приросты, эффективность, динамика и структура дополнительной добычи"
PLOT_TEMPLATE = "plotly_white"
ID_PREFIX = "gtm"
APP_DIR = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)

PARQUET_FILES = {
    "result_df": os.getenv("GTM_RESULT_DF_PATH", "result_df.parquet"),
    "df_ploshad_year": os.getenv("GTM_PLOSHAD_YEAR_PATH", "df_ploshad_year.parquet"),
    "df_itog_gtm_2": os.getenv("GTM_ITOG_GTM_PATH", "df_itog_gtm_2.parquet"),
    "factor_analysis_df": os.getenv("GTM_FACTOR_ANALYSIS_PATH", "factor_analysis_df.parquet"),
}

# Палитра в стиле шаблона презентации Группы «Татнефть».
# Базовые цвета взяты из pptx-шаблона: #008E5B, #0A9B69, #D53033,
# #7CC4A3, #C5E5D7, а также стандартные акценты PowerPoint-шаблона.
COLOR = {
    "navy": "#1F2933",          # основной текст, почти чёрный
    "black": "#000000",
    "tat_green": "#008E5B",     # ключевой фирменный зелёный
    "green": "#0A9B69",         # дополнительный зелёный
    "mint": "#7CC4A3",          # мягкий зелёный для вторичных линий
    "mint_light": "#C5E5D7",    # светлая заливка/акцент
    "red": "#D53033",           # фирменный красный акцент
    "red_light": "#F2C0C1",     # светлая красная заливка
    "orange": "#ED7D31",
    "yellow": "#FFC000",
    "blue": "#5B9BD5",
    "deep_green": "#00573A",
    "gray": "#44546A",
    "mid_gray": "#A5A5A5",
    "light_gray": "#E7E6E6",
    "card": "#FFFFFF",
    "paper": "#F7FAF8",
    "grid": "rgba(68, 84, 106, 0.14)",
}

THEME_TOKENS = {
    "light": {
        "card": COLOR["card"],
        "paper": COLOR["paper"],
        "ink": COLOR["navy"],
        "muted": COLOR["gray"],
        "border": "rgba(68,84,106,0.28)",
        "grid": COLOR["grid"],
        "legend_bg": "rgba(255,255,255,0.92)",
        "hover_bg": "white",
    },
    "dark": {
        "card": "#17211D",
        "paper": "#101815",
        "ink": "#E8F0EC",
        "muted": "#A8B9B0",
        "border": "#314138",
        "grid": "rgba(168, 185, 176, 0.16)",
        "legend_bg": "rgba(23,33,29,0.94)",
        "hover_bg": "#1F2B26",
    },
}

CATEGORY_COLORS = {
    "base_dob": "#E7E6E6",
    "ГРП": "#D53033",
    "Углубление ГНО": "#0A9B69",
    "Дострел": "#44546A",
    "ОПЗ": "#7CC4A3",
    "КРС": "#008E5B",
    "Ввод нагнет. скважин": "#00573A",
    "Ввод добыв скважин": "#8C1D20",
    "Промывка": "#C5E5D7",
    "Зарезка": "#ED7D31",
    "Бурение": "#70AD47",
    "Одновременно-раздельная эксплуатация и закачка": "#FFC000",
    "МУН": "#000000",
    "Гидродинамика": "#5B9BD5",
}

FONT_FAMILY = "Inter, Segoe UI, Roboto, Arial, sans-serif"
CARD_CLASS = "border-0 shadow-sm rounded-4"
CARD_STYLE = {"backgroundColor": COLOR["card"], "border": "1px solid rgba(0, 142, 91, 0.12)"}

FACTOR_NAMES = {
    "wcut_factor": "Обводнённость",
    "qliq_factor": "Дебит жидкости",
    "Р_пл_factor": "Пластовое давление",
    "Р_заб_factor": "Забойное давление",
    "Kprod_factor": "Коэф. продуктивности",
}

FACTOR_COLS = list(FACTOR_NAMES)

EFFICIENCY_ALGORITHM_DELTA = "delta"
EFFICIENCY_ALGORITHM_PLAN = "plan"
EFFICIENCY_ALGORITHM_OPTIONS = [
    {"label": "По приросту ΔQнефти > 0", "value": EFFICIENCY_ALGORITHM_DELTA},
    {"label": "По плану: средний Qнефти за 1–3 мес. > 90% qoil_plan", "value": EFFICIENCY_ALGORITHM_PLAN},
]
EFFICIENCY_COLUMNS = {
    EFFICIENCY_ALGORITHM_DELTA: "effective",
    EFFICIENCY_ALGORITHM_PLAN: "effective_plan",
}
EFFICIENCY_SUBTITLES = {
    EFFICIENCY_ALGORITHM_DELTA: "Доля ΔQнефти > 0",
    EFFICIENCY_ALGORITHM_PLAN: "Доля Qфакт 1–3 мес. > 90% плана",
}

# -----------------------------------------------------------------------------
# Утилиты
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class GtmDataset:
    result_df: pd.DataFrame
    df_ploshad_year: pd.DataFrame
    df_itog_gtm_2: pd.DataFrame
    factor_analysis_df: pd.DataFrame
    gtm_level: pd.DataFrame
    errors: tuple[str, ...] = ()


def cid(value: str) -> str:
    return f"{ID_PREFIX}-{value}"


def normalize_efficiency_algorithm(algorithm: str | None) -> str:
    return algorithm if algorithm in EFFICIENCY_COLUMNS else EFFICIENCY_ALGORITHM_DELTA


def efficiency_column(algorithm: str | None) -> str:
    return EFFICIENCY_COLUMNS[normalize_efficiency_algorithm(algorithm)]


def efficiency_subtitle(algorithm: str | None) -> str:
    return EFFICIENCY_SUBTITLES[normalize_efficiency_algorithm(algorithm)]


def normalize_theme(theme: str | None) -> str:
    return "dark" if theme == "dark" else "light"


def apply_runtime_theme(fig: go.Figure, theme: str | None = "light") -> go.Figure:
    theme_name = normalize_theme(theme)
    tokens = THEME_TOKENS[theme_name]
    themed = go.Figure(fig)
    themed.update_layout(
        template="plotly_dark" if theme_name == "dark" else PLOT_TEMPLATE,
        paper_bgcolor=tokens["card"],
        plot_bgcolor=tokens["card"],
        font=dict(family=FONT_FAMILY, size=12, color=tokens["ink"]),
        hoverlabel=dict(bgcolor=tokens["hover_bg"], bordercolor="rgba(0,142,91,0.45)", font_size=12),
        legend=dict(
            font=dict(color=tokens["muted"]),
            bgcolor=tokens["legend_bg"],
            bordercolor="rgba(0,142,91,0.28)",
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


def _resolve_data_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else APP_DIR / path


def _dataset_signature() -> tuple[tuple[str, str, int | None, int | None], ...]:
    signature = []
    for name, raw_path in PARQUET_FILES.items():
        path = _resolve_data_path(raw_path)
        try:
            stat = path.stat()
            signature.append((name, str(path), stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            signature.append((name, str(path), None, None))
    return tuple(signature)


@lru_cache(maxsize=8)
def _load_gtm_dataset(signature: tuple[tuple[str, str, int | None, int | None], ...]) -> GtmDataset:
    frames: dict[str, pd.DataFrame] = {}
    errors: list[str] = []

    for name, path_str, mtime_ns, _size in signature:
        path = Path(path_str)
        if mtime_ns is None:
            frames[name] = pd.DataFrame()
            errors.append(f"Не найден файл {path.name}")
            continue
        try:
            frames[name] = pd.read_parquet(path)
        except Exception as exc:
            logger.exception("Could not read GTM parquet file path=%s", path)
            frames[name] = pd.DataFrame()
            errors.append(f"Не удалось прочитать {path.name}: {exc}")

    result = frames.get("result_df", pd.DataFrame())
    gtm_level = pd.DataFrame()
    if result.empty:
        errors.append("result_df пустой или не загружен")
    else:
        try:
            result = normalize_result_df(result)
            gtm_level = precompute_gtm_level(result)
        except Exception as exc:
            logger.exception("Could not prepare GTM dataset")
            errors.append(f"Не удалось подготовить result_df: {exc}")
            result = pd.DataFrame()

    return GtmDataset(
        result_df=result,
        df_ploshad_year=frames.get("df_ploshad_year", pd.DataFrame()),
        df_itog_gtm_2=frames.get("df_itog_gtm_2", pd.DataFrame()),
        factor_analysis_df=frames.get("factor_analysis_df", pd.DataFrame()),
        gtm_level=gtm_level,
        errors=tuple(errors),
    )


def get_gtm_dataset() -> GtmDataset:
    return _load_gtm_dataset(_dataset_signature())


def dropdown_options_from_df(df: pd.DataFrame, column: str, all_label: str) -> list[dict]:
    if column not in df.columns:
        return [{"label": all_label, "value": ALL}]
    return dropdown_options(df[column], all_label)


def direction_filter_options() -> list[dict]:
    return dropdown_options_from_df(get_gtm_dataset().result_df, "направление", "Все направления")


def _selected_values(value) -> list:
    if isinstance(value, (list, tuple, set, np.ndarray, pd.Series)):
        values = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str) and (item in ("", ALL) or item.startswith("__ALL_")):
                continue
            try:
                if pd.isna(item):
                    continue
            except TypeError:
                pass
            values.append(item)
        return values
    if value is None:
        return []
    if isinstance(value, str) and (value in ("", ALL) or value.startswith("__ALL_")):
        return []
    try:
        if pd.isna(value):
            return []
    except TypeError:
        pass
    return [value]


def data_status_alert(dataset: GtmDataset):
    if not dataset.errors:
        return None
    return dbc.Alert(
        [
            html.Div("Данные ГТМ загружены не полностью", className="fw-semibold"),
            html.Div("; ".join(dataset.errors), className="small mt-1"),
        ],
        color="warning",
        className="mb-4",
    )


def empty_figure(title: str, height: int = 450) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        template=PLOT_TEMPLATE,
        height=height,
        paper_bgcolor=COLOR["paper"],
        plot_bgcolor=COLOR["card"],
        font=dict(family=FONT_FAMILY, color=COLOR["navy"]),
        xaxis={"visible": False},
        yaxis={"visible": False},
        margin=dict(t=45, b=35, l=35, r=35),
        annotations=[
            {
                "text": f"<b>{title}</b><br><span style='font-size:12px;color:#64748B'>Измените фильтры или проверьте входные данные</span>",
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
                "align": "center",
                "font": {"size": 16, "color": COLOR["gray"]},
            }
        ],
    )
    return fig


def apply_common_layout(fig: go.Figure, height: int = 480, legend_y: float = 1.11) -> go.Figure:
    """Единый presentation-ready стиль для всех Plotly-графиков."""
    fig.update_layout(
        template=PLOT_TEMPLATE,
        height=height,
        paper_bgcolor=COLOR["card"],
        plot_bgcolor=COLOR["card"],
        font=dict(family=FONT_FAMILY, size=12, color=COLOR["navy"]),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="white", bordercolor="rgba(0,142,91,0.22)", font_size=12),
        margin=dict(t=70, b=58, l=68, r=72),
        legend=dict(
            title=None,
            orientation="h",
            yanchor="bottom",
            y=legend_y,
            xanchor="center",
            x=0.5,
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="rgba(0,142,91,0.18)",
            borderwidth=1,
            itemclick="toggleothers",
            itemdoubleclick="toggle",
        ),
        title=dict(font=dict(size=16, color=COLOR["navy"]), x=0.02, xanchor="left"),
    )
    fig.update_xaxes(
        showgrid=True,
        gridcolor=COLOR["grid"],
        zeroline=False,
        showline=True,
        linecolor="rgba(68,84,106,0.28)",
        ticks="outside",
        tickfont=dict(color=COLOR["gray"]),
        title=dict(font=dict(color=COLOR["navy"])),
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor=COLOR["grid"],
        zeroline=False,
        showline=True,
        linecolor="rgba(68,84,106,0.28)",
        ticks="outside",
        tickfont=dict(color=COLOR["gray"]),
        title=dict(font=dict(color=COLOR["navy"])),
    )
    return fig


def add_zero_line(fig: go.Figure, opacity: float = 0.55) -> go.Figure:
    fig.add_hline(y=0, line_dash="dot", line_color=COLOR["gray"], opacity=opacity)
    return fig


def style_card_header(title: str, subtitle: str | None = None, icon: str = ""):
    return dbc.CardHeader(
        html.Div(
            [
                html.Div(
                    [
                        html.Span(
                            icon,
                            className="me-2 rounded-circle d-inline-flex align-items-center justify-content-center",
                            style={
                                "width": "28px",
                                "height": "28px",
                                "backgroundColor": COLOR["mint_light"],
                                "color": COLOR["tat_green"],
                                "fontWeight": "800",
                            },
                        ),
                        html.Span(title, className="fw-semibold", style={"color": COLOR["navy"]}),
                    ],
                    className="d-flex align-items-center",
                ),
                html.Div(subtitle, className="small mt-1", style={"color": COLOR["gray"]}) if subtitle else None,
            ],
            style={"borderLeft": f"4px solid {COLOR['tat_green']}", "paddingLeft": "12px"},
        ),
        className="bg-white border-0 pt-3 pb-0",
    )

def dropdown_options(series: pd.Series, all_label: str) -> list[dict]:
    values = sorted(series.dropna().unique(), key=lambda x: str(x))
    return [{"label": all_label, "value": ALL}] + [{"label": str(v), "value": v} for v in values]


def safe_first(s: pd.Series, default=np.nan):
    return s.iloc[0] if len(s) else default


# -----------------------------------------------------------------------------
# Подготовка данных
# -----------------------------------------------------------------------------
def normalize_result_df(df: pd.DataFrame) -> pd.DataFrame:
    """Приводит ключевые столбцы к ожидаемому виду без изменения исходного df."""
    out = df.copy()
    if "gtm_date" not in out.columns and "окончание_работ_факт" in out.columns:
        out = out.rename(columns={"окончание_работ_факт": "gtm_date"})

    for col in ["date", "gtm_date"]:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")

    for col in ["qliq", "qoil", "qoil_plan", "qinj", "wcut", "Р_пл", "Р_заб", "month_offset", "gtm_year", "year"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    return out


def calc_delta_per_gtm(group: pd.DataFrame) -> pd.Series:
    """Расчёт прироста для одной ГТМ: среднее после 1-3 мес минус база до ГТМ."""
    before = group[group["month_offset"] < 0]
    after_1_3 = group[group["month_offset"].isin([1, 2, 3])]

    if before.empty:
        qliq_before = qoil_before = 0.0
    elif before["month_offset"].min() <= -36:
        # Бизнес-правило из исходного кода: если есть очень далёкая история, базу не используем.
        qliq_before = qoil_before = 0.0
    else:
        last_3_before = before[before["month_offset"].isin([-3, -2, -1])]
        base = last_3_before if not last_3_before.empty else before.loc[[before["month_offset"].idxmax()]]
        qliq_before = base["qliq"].mean()
        qoil_before = base["qoil"].mean()

    qoil_after_1_3 = after_1_3["qoil"].mean() if not after_1_3.empty else np.nan
    qoil_plan = group["qoil_plan"].dropna().iloc[0] if "qoil_plan" in group.columns and group["qoil_plan"].notna().any() else np.nan

    if not after_1_3.empty:
        after = after_1_3
    else:
        after_any = group[group["month_offset"] > 0]
        if after_any.empty:
            return pd.Series({
                "Δqliq": np.nan,
                "Δqoil": np.nan,
                "qoil_after_1_3": qoil_after_1_3,
                "qoil_plan": qoil_plan,
                "gtm_year": safe_first(group["gtm_year"]),
                "назначение": safe_first(group.get("назнач_скв_факт", pd.Series(dtype=object)), "Не указано"),
                "направление": safe_first(group.get("направление", pd.Series(dtype=object))),
                "mest": safe_first(group.get("mest", pd.Series(dtype=object))),
                "plosh": safe_first(group.get("plosh", pd.Series(dtype=object))),
            })
        after = after_any.loc[[after_any["month_offset"].idxmin()]]

    return pd.Series({
        "Δqliq": after["qliq"].mean() - qliq_before,
        "Δqoil": after["qoil"].mean() - qoil_before,
        "qoil_after_1_3": qoil_after_1_3,
        "qoil_plan": qoil_plan,
        "gtm_year": safe_first(group["gtm_year"]),
        "назначение": safe_first(group.get("назнач_скв_факт", pd.Series(dtype=object)), "Не указано"),
        "направление": safe_first(group.get("направление", pd.Series(dtype=object))),
        "mest": safe_first(group.get("mest", pd.Series(dtype=object))),
        "plosh": safe_first(group.get("plosh", pd.Series(dtype=object))),
    })


def _first_existing_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    return [col for col in columns if col in df.columns]


def precompute_gtm_level(df: pd.DataFrame) -> pd.DataFrame:
    """Тяжёлый расчёт уровня ГТМ выполняется один раз при старте.

    Векторизованная реализация сохраняет бизнес-правила calc_delta_per_gtm(),
    но не запускает Python-функцию для каждой пары well/gtm_date. На больших
    выгрузках это критично для первого открытия вкладки ГТМ.
    """
    required = {"well", "gtm_date", "month_offset", "qliq", "qoil", "gtm_year"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"В result_df не хватает столбцов: {sorted(missing)}")

    keys = ["well", "gtm_date"]
    work = df.copy()
    work["_row_order"] = np.arange(len(work))
    meta_cols = _first_existing_columns(work, ["gtm_year", "назнач_скв_факт", "направление", "mest", "plosh"])

    groups = work[keys].drop_duplicates().reset_index(drop=True)

    if meta_cols:
        meta = (
            work.sort_values("_row_order")
            .groupby(keys, dropna=False, sort=False)[meta_cols]
            .first()
            .reset_index()
        )
        groups = groups.merge(meta, on=keys, how="left")

    before = work[work["month_offset"].lt(0)]
    before_min = before.groupby(keys, dropna=False, sort=False)["month_offset"].min().rename("before_min")
    before_last3 = (
        before[before["month_offset"].isin([-3, -2, -1])]
        .groupby(keys, dropna=False, sort=False)[["qliq", "qoil"]]
        .mean()
        .rename(columns={"qliq": "qliq_before_last3", "qoil": "qoil_before_last3"})
    )

    if before.empty:
        before_fallback = pd.DataFrame(
            columns=["qliq_before_fallback", "qoil_before_fallback"],
            index=pd.MultiIndex.from_tuples([], names=keys),
        )
    else:
        before_fallback_idx = before.groupby(keys, dropna=False, sort=False)["month_offset"].idxmax()
        before_fallback = (
            before.loc[before_fallback_idx, keys + ["qliq", "qoil"]]
            .set_index(keys)
            .rename(columns={"qliq": "qliq_before_fallback", "qoil": "qoil_before_fallback"})
        )

    base = groups.set_index(keys).join(before_min).join(before_last3).join(before_fallback)
    has_recent_base = base["qliq_before_last3"].notna() | base["qoil_before_last3"].notna()
    use_zero_base = base["before_min"].isna() | base["before_min"].le(-36)
    base["qliq_before"] = np.where(
        use_zero_base,
        0.0,
        np.where(has_recent_base, base["qliq_before_last3"], base["qliq_before_fallback"]),
    )
    base["qoil_before"] = np.where(
        use_zero_base,
        0.0,
        np.where(has_recent_base, base["qoil_before_last3"], base["qoil_before_fallback"]),
    )

    after_1_3 = (
        work[work["month_offset"].isin([1, 2, 3])]
        .groupby(keys, dropna=False, sort=False)[["qliq", "qoil"]]
        .mean()
        .rename(columns={"qliq": "qliq_after_1_3", "qoil": "qoil_after_1_3"})
    )
    after_any = work[work["month_offset"].gt(0)]
    if after_any.empty:
        after_fallback = pd.DataFrame(
            columns=["qliq_after_fallback", "qoil_after_fallback"],
            index=pd.MultiIndex.from_tuples([], names=keys),
        )
    else:
        after_fallback_idx = after_any.groupby(keys, dropna=False, sort=False)["month_offset"].idxmin()
        after_fallback = (
            after_any.loc[after_fallback_idx, keys + ["qliq", "qoil"]]
            .set_index(keys)
            .rename(columns={"qliq": "qliq_after_fallback", "qoil": "qoil_after_fallback"})
        )

    calc = base.join(after_1_3).join(after_fallback)
    calc["qliq_after"] = calc["qliq_after_1_3"].combine_first(calc["qliq_after_fallback"])
    calc["qoil_after"] = calc["qoil_after_1_3"].combine_first(calc["qoil_after_fallback"])
    calc["Δqliq"] = calc["qliq_after"] - calc["qliq_before"]
    calc["Δqoil"] = calc["qoil_after"] - calc["qoil_before"]

    if "qoil_plan" in work.columns:
        plan = work.dropna(subset=["qoil_plan"]).groupby(keys, dropna=False, sort=False)["qoil_plan"].first()
        calc = calc.join(plan)
    else:
        calc["qoil_plan"] = np.nan

    gtm_level = calc.reset_index()
    rename_cols = {"назнач_скв_факт": "назначение"}
    gtm_level = gtm_level.rename(columns=rename_cols)
    keep_cols = [
        "well",
        "gtm_date",
        "Δqliq",
        "Δqoil",
        "qoil_after_1_3",
        "qoil_plan",
        "gtm_year",
        "назначение",
        "направление",
        "mest",
        "plosh",
    ]
    gtm_level = gtm_level[[col for col in keep_cols if col in gtm_level.columns]]
    gtm_level["effective"] = np.where(gtm_level["Δqoil"] > 0, 1, 0)
    if {"qoil_after_1_3", "qoil_plan"}.issubset(gtm_level.columns):
        gtm_level["effective_plan"] = np.where(gtm_level["qoil_after_1_3"] > 0.9 * gtm_level["qoil_plan"], 1, 0)
    else:
        gtm_level["effective_plan"] = 0
    return gtm_level


def filter_df(df: pd.DataFrame, direction=ALL, plosh=ALL, mest=ALL) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    direction_values = _selected_values(direction)
    plosh_values = _selected_values(plosh)
    mest_values = _selected_values(mest)
    if direction_values and "направление" in df.columns:
        mask &= df["направление"].isin(direction_values)
    if plosh_values and "plosh" in df.columns:
        mask &= df["plosh"].isin(plosh_values)
    if mest_values and "mest" in df.columns:
        mask &= df["mest"].isin(mest_values)
    return df.loc[mask]


# -----------------------------------------------------------------------------
# Фигуры
# -----------------------------------------------------------------------------
def make_kpi_cards(gtm_level: pd.DataFrame, algorithm: str | None = EFFICIENCY_ALGORITHM_DELTA) -> list[dbc.Col]:
    eff_col = efficiency_column(algorithm)
    if gtm_level.empty:
        values = {"gtm": 0, "eff": 0, "dq_oil": 0, "dq_liq": 0}
    else:
        values = {
            "gtm": len(gtm_level),
            "eff": 100 * (gtm_level[eff_col].mean()) if eff_col in gtm_level.columns else 0,
            "dq_oil": gtm_level["Δqoil"].mean(skipna=True),
            "dq_liq": gtm_level["Δqliq"].mean(skipna=True),
        }

    cards = [
        ("ГТМ", f"{values['gtm']:,.0f}".replace(",", " "), "Всего в выборке", "#008E5B", "●"),
        ("Эффективность", f"{values['eff']:.1f}%", efficiency_subtitle(algorithm), "#0A9B69", "●"),
        ("Средний ΔQнефти", f"{values['dq_oil']:+.2f}", "т/сут", "#D53033" if values["dq_oil"] < 0 else "#008E5B", "●"),
        ("Средний ΔQжидкости", f"{values['dq_liq']:+.2f}", "т/сут", "#008E5B", "●"),
    ]

    return [
        dbc.Col(
            dbc.Card(
                dbc.CardBody([
                    html.Div([
                        html.Span(dot, style={"color": color, "fontSize": "18px"}, className="me-2"),
                        html.Span(title, className="text-muted small text-uppercase fw-semibold"),
                    ], className="d-flex align-items-center mb-1"),
                    html.H2(value, className="mb-0 fw-bold", style={"color": COLOR["navy"], "letterSpacing": "-0.03em"}),
                    html.Div(subtitle, className="text-muted small mt-1"),
                ]),
                className=f"{CARD_CLASS} h-100",
                style={**CARD_STYLE, "borderLeft": f"5px solid {color}"},
            ),
            md=3,
            sm=6,
            className="mb-3",
        )
        for title, value, subtitle, color, dot in cards
    ]

def fig_delta_and_counts(gtm_level: pd.DataFrame) -> go.Figure:
    if gtm_level.empty:
        return empty_figure("Нет данных для расчёта приростов")

    yearly_avg = (
        gtm_level.groupby("gtm_year", dropna=False)
        .agg(avg_Δqliq=("Δqliq", "mean"), avg_Δqoil=("Δqoil", "mean"))
        .reset_index()
        .sort_values("gtm_year")
    )

    yearly_count = (
        gtm_level.groupby(["gtm_year", "назначение"], dropna=False)
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    for col in ["Добывающая", "Нагнетательная"]:
        if col not in yearly_count.columns:
            yearly_count[col] = 0

    plot_data = yearly_avg.merge(
        yearly_count[["gtm_year", "Добывающая", "Нагнетательная"]], on="gtm_year", how="outer"
    ).fillna(0).sort_values("gtm_year")

    x = plot_data["gtm_year"].astype("Int64").astype(str)
    fig = go.Figure()
    fig.add_bar(
        x=x,
        y=plot_data["avg_Δqliq"],
        name="ΔQ жидкости",
        marker_color=COLOR["green"],
        marker_line=dict(color="white", width=1.2),
        opacity=0.92,
        text=plot_data["avg_Δqliq"].map(lambda v: f"{v:+.1f}"),
        textposition="outside",
        hovertemplate="Год %{x}<br>ΔQ жидкости: %{y:.2f} т/сут<extra></extra>",
    )
    fig.add_bar(
        x=x,
        y=plot_data["avg_Δqoil"],
        name="ΔQ нефти",
        marker_color=COLOR["red"],
        marker_line=dict(color="white", width=1.2),
        opacity=0.88,
        text=plot_data["avg_Δqoil"].map(lambda v: f"{v:+.1f}"),
        textposition="outside",
        hovertemplate="Год %{x}<br>ΔQ нефти: %{y:.2f} т/сут<extra></extra>",
    )
    fig.add_scatter(
        x=x,
        y=plot_data["Добывающая"],
        name="ГТМ на ДС",
        mode="lines+markers+text",
        line=dict(color=COLOR["navy"], width=3.2),
        marker=dict(size=9, line=dict(color="white", width=1.4)),
        text=plot_data["Добывающая"].astype(int),
        textposition="top center",
        yaxis="y2",
        hovertemplate="Год %{x}<br>ГТМ на ДС: %{y:.0f}<extra></extra>",
    )
    fig.add_scatter(
        x=x,
        y=plot_data["Нагнетательная"],
        name="ГТМ на НС",
        mode="lines+markers+text",
        line=dict(color=COLOR["orange"], width=3, dash="dash"),
        marker=dict(size=8, symbol="diamond"),
        text=plot_data["Нагнетательная"].astype(int),
        textposition="bottom center",
        yaxis="y2",
        hovertemplate="Год %{x}<br>ГТМ на НС: %{y:.0f}<extra></extra>",
    )
    fig.update_layout(
        #title="Средние приросты и количество ГТМ по годам",
        barmode="group",
        bargap=0.22,
        bargroupgap=0.08,
        xaxis_title="Год проведения ГТМ",
        yaxis_title="Средний прирост, т/сут",
        yaxis2=dict(title="Количество ГТМ", overlaying="y", side="right", showgrid=False, rangemode="tozero"),
        uniformtext_minsize=10,
        uniformtext_mode="hide",
    )
    add_zero_line(fig)
    return apply_common_layout(fig, height=500)


def fig_efficiency(gtm_level: pd.DataFrame, algorithm: str | None = EFFICIENCY_ALGORITHM_DELTA) -> go.Figure:
    eff_col = efficiency_column(algorithm)
    if gtm_level.empty or "назначение" not in gtm_level.columns or eff_col not in gtm_level.columns:
        return empty_figure("Нет данных по добывающим скважинам")

    df = gtm_level[gtm_level["назначение"].eq("Добывающая")].copy()
    if df.empty:
        return empty_figure("Нет данных по добывающим скважинам")

    yearly = (
        df.groupby(["gtm_year", eff_col], dropna=False)
        .size()
        .rename("n")
        .reset_index()
        .pivot_table(index="gtm_year", columns=eff_col, values="n", fill_value=0)
        .reset_index()
    )
    for col in [0, 1]:
        if col not in yearly.columns:
            yearly[col] = 0
    yearly["total"] = yearly[0] + yearly[1]
    yearly["eff_perc"] = np.where(yearly["total"] > 0, yearly[1] * 100 / yearly["total"], 0)
    yearly = yearly.sort_values("gtm_year")
    x = yearly["gtm_year"].astype("Int64").astype(str)

    fig = go.Figure()
    fig.add_bar(
        x=x,
        y=yearly[1],
        name="Эффективные",
        marker_color=COLOR["green"],
        marker_line=dict(color="white", width=1.2),
        text=yearly[1],
        textposition="inside",
        insidetextanchor="middle",
        hovertemplate="Год %{x}<br>Эффективные: %{y:.0f}<extra></extra>",
    )
    fig.add_bar(
        x=x,
        y=yearly[0],
        name="Неэффективные",
        marker_color=COLOR["red"],
        marker_line=dict(color="white", width=1.2),
        text=yearly[0],
        textposition="inside",
        insidetextanchor="middle",
        hovertemplate="Год %{x}<br>Неэффективные: %{y:.0f}<extra></extra>",
    )
    fig.add_scatter(
        x=x,
        y=yearly["eff_perc"],
        yaxis="y2",
        name="Эффективность, %",
        marker=dict(color=COLOR["blue"], size=9),
        line=dict(color=COLOR["blue"], width=2.5),
        mode="lines+markers+text",
        text=yearly["eff_perc"].map(lambda v: f"{v:.1f}%"),
        textposition="top center",
    )
    fig.update_layout(
        #title="Эффективность ГТМ: структура и доля успешных операций",
        barmode="stack",
        bargap=0.28,
        xaxis_title="Год проведения ГТМ",
        yaxis_title="Количество добывающих скважин",
        yaxis2=dict(title="Эффективность, %", overlaying="y", side="right", showgrid=False, range=[0, 105], ticksuffix="%"),
    )
    return apply_common_layout(fig, height=500)


def _well_kind_mask(df: pd.DataFrame, kind: str) -> pd.Series:
    if "назначение" not in df.columns:
        return pd.Series(False, index=df.index)
    text = df["назначение"].astype(str).str.lower()
    pattern = "нагнет" if kind == "injection" else "добыв"
    return text.str.contains(pattern, na=False)


def fig_gtm_direction_counts(gtm_level: pd.DataFrame, kind: str) -> go.Figure:
    title = "Количество ГТМ по направлениям добывающих скважин" if kind == "production" else "Количество ГТМ по направлениям нагнетательных скважин"
    if gtm_level.empty or "направление" not in gtm_level.columns:
        return empty_figure(f"Нет данных: {title.lower()}", height=430)

    df = gtm_level[_well_kind_mask(gtm_level, kind)].copy()
    if df.empty:
        return empty_figure(f"Нет данных: {title.lower()}", height=430)

    counts = (
        df.groupby("направление", dropna=False)
        .size()
        .rename("Количество ГТМ")
        .reset_index()
        .sort_values("Количество ГТМ", ascending=True)
    )
    counts["направление"] = counts["направление"].fillna("Не указано").astype(str)
    color = COLOR["green"] if kind == "production" else COLOR["blue"]

    fig = go.Figure(
        go.Bar(
            x=counts["Количество ГТМ"],
            y=counts["направление"],
            orientation="h",
            marker_color=color,
            marker_line=dict(color="white", width=1.1),
            text=counts["Количество ГТМ"],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}<br>Количество ГТМ: %{x:.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        xaxis_title="Количество ГТМ",
        yaxis_title="Направление",
        showlegend=False,
        margin=dict(l=148, r=32, t=44, b=48),
    )
    return apply_common_layout(fig, height=430)


def fig_dynamics_by_year(df: pd.DataFrame) -> go.Figure:
    required = {"month_offset", "gtm_year", "qliq", "qoil", "wcut"}
    missing = required - set(df.columns)
    if df.empty or missing:
        return empty_figure("Нет данных в диапазоне ±15 месяцев", height=650)

    df = df[df["month_offset"].between(-15, 15)].copy()
    if df.empty:
        return empty_figure("Нет данных в диапазоне ±15 месяцев", height=650)

    pivot = (
        df.groupby(["gtm_year", "month_offset"], dropna=False)
        .agg(qliq=("qliq", "mean"), qoil=("qoil", "mean"), wcut=("wcut", "mean"))
        .reset_index()
        .sort_values(["gtm_year", "month_offset"])
    )
    years = sorted(pivot["gtm_year"].dropna().unique())
    palette = [COLOR["blue"], COLOR["tat_green"], COLOR["yellow"], COLOR["red"], COLOR["orange"], COLOR["mint"], COLOR["green"], COLOR["gray"]]

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        subplot_titles=("Q жидкости", "Q нефти", "Обводнённость"),
    )
    metrics = [("qliq", "Q жидкости, т/сут"), ("qoil", "Q нефти, т/сут"), ("wcut", "Обводнённость, д.ед.")]

    for i, year in enumerate(years):
        sub = pivot[pivot["gtm_year"].eq(year)]
        color = palette[i % len(palette)]
        name = str(int(year)) if pd.notna(year) else "Без года"
        for row, (metric, _) in enumerate(metrics, start=1):
            fig.add_scatter(
                x=sub["month_offset"],
                y=sub[metric],
                mode="lines+markers",
                name=name,
                legendgroup=name,
                showlegend=(row == 1),
                line=dict(color=color, width=2.4),
                marker=dict(size=5.5, line=dict(color="white", width=0.8)),
                row=row,
                col=1,
            )

    for row in [1, 2, 3]:
        fig.add_vrect(x0=-0.5, x1=0.5, fillcolor=COLOR["yellow"], opacity=0.08, line_width=0, row=row, col=1)
        fig.add_vline(x=0, line_dash="dot", line_color=COLOR["navy"], opacity=0.75, row=row, col=1)
        fig.update_yaxes(title_text=metrics[row - 1][1], row=row, col=1)

    fig.update_xaxes(title_text="Месяц относительно ГТМ", row=3, col=1)
    fig.update_layout(
        template=PLOT_TEMPLATE,
        height=760,
        hovermode="x unified",
        legend_title="Год ГТМ",
        paper_bgcolor=COLOR["card"],
        plot_bgcolor=COLOR["card"],
        font=dict(family=FONT_FAMILY, color=COLOR["navy"]),
        margin=dict(t=78, b=58, l=78, r=42),
    )
    fig.update_xaxes(showgrid=True, gridcolor=COLOR["grid"], linecolor="rgba(68,84,106,0.24)")
    fig.update_yaxes(showgrid=True, gridcolor=COLOR["grid"], linecolor="rgba(68,84,106,0.24)")
    return fig


def fig_cumulative_dynamics(df: pd.DataFrame) -> go.Figure:
    required = {"month_offset", "gtm_year", "qliq", "qoil", "wcut"}
    missing = required - set(df.columns)
    if df.empty or missing:
        return empty_figure("Нет данных в диапазоне ±15 месяцев", height=650)

    df = df[df["month_offset"].between(-15, 15)].copy()
    if df.empty:
        return empty_figure("Нет данных в диапазоне ±15 месяцев", height=650)

    years = sorted(df["gtm_year"].dropna().unique())
    if not years:
        return empty_figure("Нет данных по годам ГТМ", height=650)

    year_to_idx = {y: i for i, y in enumerate(years)}
    df["year_idx"] = df["gtm_year"].map(year_to_idx)
    df["month_offset_cum"] = df["year_idx"] * 31 + (df["month_offset"] + 15)

    agg = (
        df.groupby("month_offset_cum")
        .agg(avg_qliq=("qliq", "mean"), avg_qoil=("qoil", "mean"), avg_wcut=("wcut", "mean"))
        .reset_index()
        .sort_values("month_offset_cum")
    )

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        subplot_titles=("Q жидкости", "Q нефти", "Обводнённость"),
    )
    metrics = [
        ("avg_qliq", "Q жидкости, т/сут", COLOR["green"]),
        ("avg_qoil", "Q нефти, т/сут", COLOR["red"]),
        ("avg_wcut", "Обводнённость, д.ед.", COLOR["blue"]),
    ]

    for row, (metric, ylabel, color) in enumerate(metrics, start=1):
        fig.add_scatter(
            x=agg["month_offset_cum"],
            y=agg[metric],
            mode="lines",
            line=dict(color=color, width=2.7),
            showlegend=False,
            row=row,
            col=1,
        )
        fig.update_yaxes(title_text=ylabel, row=row, col=1)
        for year, idx in year_to_idx.items():
            x0 = idx * 31 + 15
            fig.add_vline(x=x0, line_dash="dash", line_color="#555", opacity=0.65, row=row, col=1)
            if row == 3:
                fig.add_annotation(
                    x=x0,
                    y=-0.22,
                    text=str(int(year)),
                    showarrow=False,
                    font=dict(size=12, color=COLOR["red"]),
                    xref="x3",
                    yref="paper",
                )

    fig.update_xaxes(title_text="Кумулятивный месяц; подпись — год ГТМ", row=3, col=1)
    fig.update_layout(
        template=PLOT_TEMPLATE,
        height=760,
        hovermode="x unified",
        paper_bgcolor=COLOR["card"],
        plot_bgcolor=COLOR["card"],
        font=dict(family=FONT_FAMILY, color=COLOR["navy"]),
        margin=dict(t=78, b=86, l=78, r=42),
    )
    fig.update_xaxes(showgrid=True, gridcolor=COLOR["grid"], linecolor="rgba(68,84,106,0.24)")
    fig.update_yaxes(showgrid=True, gridcolor=COLOR["grid"], linecolor="rgba(68,84,106,0.24)")
    return fig


def prepare_hist_data(plosh=ALL, hist_type="traditional", dataset: GtmDataset | None = None, mest=ALL) -> pd.DataFrame:
    """Данные для stacked bar: базовая добыча + доп. добыча по направлениям."""
    dataset = dataset or get_gtm_dataset()
    plosh_values = _selected_values(plosh)
    mest_values = _selected_values(mest)
    prod = dataset.df_ploshad_year.copy()
    if prod.empty:
        return pd.DataFrame(columns=["year", "Категория", "Добыча нефти, тонн"])
    if mest_values and "mest" in prod.columns:
        prod = prod[prod["mest"].isin(mest_values)]
    if plosh_values and "kod_ploshchadi" in prod.columns:
        prod = prod[prod["kod_ploshchadi"].isin(plosh_values)]
    if "year" not in prod.columns or "dobycha_nefti" not in prod.columns:
        return pd.DataFrame(columns=["year", "Категория", "Добыча нефти, тонн"])
    prod = prod.groupby("year", as_index=False)["dobycha_nefti"].sum()

    gtm = dataset.df_itog_gtm_2.copy().rename(columns={"год_гтм": "gtm_year"})
    if gtm.empty or not {"year", "dop_dob_month", "направление"}.issubset(gtm.columns):
        merged = prod.assign(base_dob=prod["dobycha_nefti"])
        return merged[["year", "base_dob"]].melt(
            id_vars="year", var_name="Категория", value_name="Добыча нефти, тонн"
        )
    if plosh_values and "plosh" in gtm.columns:
        gtm = gtm[gtm["plosh"].isin(plosh_values)]
    if mest_values and "mest" in gtm.columns:
        gtm = gtm[gtm["mest"].isin(mest_values)]

    if hist_type == "traditional" and "gtm_year" in gtm.columns:
        gtm = gtm[gtm["gtm_year"].eq(gtm["year"])]

    gtm_year = (
        gtm.groupby(["направление", "year"], dropna=False)["dop_dob_month"]
        .sum()
        .reset_index()
        .pivot_table(index="year", columns="направление", values="dop_dob_month", fill_value=0)
        .reset_index()
    )

    merged = prod.merge(gtm_year, on="year", how="left").fillna(0)
    gtm_cols = [c for c in merged.columns if c not in ["year", "dobycha_nefti"]]
    merged["dop_dob_sum"] = merged[gtm_cols].sum(axis=1) if gtm_cols else 0
    merged["base_dob"] = merged["dobycha_nefti"] - merged["dop_dob_sum"]
    merged["base_dob"] = merged["base_dob"].clip(lower=0)

    return merged.drop(columns=["dop_dob_sum", "dobycha_nefti"]).melt(
        id_vars="year", var_name="Категория", value_name="Добыча нефти, тонн"
    )


def fig_histogram(plosh=ALL, hist_type="traditional", dataset: GtmDataset | None = None, mest=ALL) -> go.Figure:
    data = prepare_hist_data(plosh, hist_type, dataset, mest)
    data = data[data["Добыча нефти, тонн"].notna()].copy()

    # Гистограмма только с 2020 года
    data["year"] = pd.to_numeric(data["year"], errors="coerce")
    data = data[data["year"] >= 2021].copy()

    if data.empty:
        return empty_figure("Нет данных для гистограммы с 2020 года")

    title = "Кумулятивная структура добычи с 2020 года" if hist_type == "cumulative" else "Структура добычи в год проведения ГТМ с 2020 года"
    data["Категория"] = data["Категория"].replace({"base_dob": "Базовая добыча"})
    category_order = ["Базовая добыча"] + [c for c in CATEGORY_COLORS if c != "base_dob"]
    color_map = {**CATEGORY_COLORS, "Базовая добыча": CATEGORY_COLORS["base_dob"]}

    fig = px.bar(
        data_frame=data,
        x="year",
        y="Добыча нефти, тонн",
        color="Категория",
        category_orders={"Категория": category_order},
        barmode="relative",
        color_discrete_map=color_map,
        title=title,
    )
    fig.update_traces(
        marker_line=dict(color="rgba(255,255,255,0.82)", width=0.7),
        hovertemplate="Год %{x}<br>%{fullData.name}: %{y:,.0f} т<extra></extra>",
    )
    fig.update_layout(
        xaxis_title="Год",
        yaxis_title="Добыча нефти, тонн",
        legend_title_text="Категория",
        bargap=0.18,
    )
    fig.update_xaxes(tickmode="linear", dtick=1)
    return apply_common_layout(fig, height=560, legend_y=1.04)



def make_bad_gtm_table(gtm_level: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    if gtm_level.empty:
        return [], []

    table = (
        gtm_level[gtm_level["Δqoil"].lt(0)]
        .sort_values("Δqoil")
        .assign(
            **{
                "Дата ГТМ": lambda x: pd.to_datetime(x["gtm_date"], errors="coerce").dt.strftime("%Y-%m-%d"),
                "ΔQжидк": lambda x: x["Δqliq"].round(2),
                "ΔQнефти": lambda x: x["Δqoil"].round(2),
            }
        )
        .rename(columns={"well": "Скважина", "gtm_year": "Год ГТМ", "назначение": "Назначение", "направление": "Направление", "plosh": "Площадь"})
    )
    cols = ["Скважина", "Дата ГТМ", "ΔQжидк", "ΔQнефти", "Год ГТМ", "Назначение", "Направление", "Площадь"]
    cols = [c for c in cols if c in table.columns]
    data = table[cols].to_dict("records")
    columns = [{"name": c, "id": c} for c in cols]
    return data, columns


def fig_boxplot_factors(direction=ALL, plosh=ALL, dataset: GtmDataset | None = None, mest=ALL) -> go.Figure:
    dataset = dataset or get_gtm_dataset()
    df = dataset.factor_analysis_df.copy()
    if df.empty:
        return empty_figure("factor_analysis_df не найден или пуст")
    direction_values = _selected_values(direction)
    plosh_values = _selected_values(plosh)
    mest_values = _selected_values(mest)

    if direction_values and "направление" in df.columns:
        df = df[df["направление"].isin(direction_values)]

    if plosh_values and "plosh" in df.columns:
        df = df[df["plosh"].isin(plosh_values)]

    if mest_values and "mest" in df.columns:
        df = df[df["mest"].isin(mest_values)]

    available = [c for c in FACTOR_COLS if c in df.columns]
    if not available or df.empty:
        return empty_figure("Нет данных для распределения факторов")

    long = df[available].melt(var_name="Фактор", value_name="Значение").dropna()
    long["Фактор"] = long["Фактор"].map(FACTOR_NAMES).fillna(long["Фактор"])
    if long.empty:
        return empty_figure("Нет ненулевых значений факторов")

    factor_palette = {
        "Обводнённость": COLOR["red"],
        "Дебит жидкости": COLOR["green"],
        "Пластовое давление": COLOR["blue"],
        "Забойное давление": COLOR["mint"],
        "Коэф. продуктивности": COLOR["yellow"],
    }
    fig = px.box(long, x="Фактор", y="Значение", color="Фактор", points="outliers", color_discrete_map=factor_palette)
    fig.update_traces(boxmean=True, marker=dict(opacity=0.62, size=5), line=dict(width=1.4))
    fig.add_hline(y=0, line_dash="dash", line_color=COLOR["gray"], opacity=0.7)

    q_low, q_high = long["Значение"].quantile([0.01, 0.99])
    if np.isfinite(q_low) and np.isfinite(q_high) and q_low != q_high:
        pad = (q_high - q_low) * 0.15
        fig.update_yaxes(range=[q_low - pad, q_high + pad])

    fig.update_layout(
        title="Распределение факторов эффективности",
        xaxis_title="",
        yaxis_title="Значение фактора",
        showlegend=False,
    )
    return apply_common_layout(fig, height=520)



def make_well_options(direction=ALL, plosh=ALL, dataset: GtmDataset | None = None, mest=ALL) -> list[dict]:
    dataset = dataset or get_gtm_dataset()
    df = filter_df(dataset.result_df, direction, plosh, mest)
    if "well" not in df.columns or df.empty:
        return []

    wells = sorted(df["well"].dropna().unique(), key=lambda x: str(x))
    return [{"label": str(w), "value": w} for w in wells]


def fig_well_history(well, dataset: GtmDataset | None = None) -> go.Figure:
    """История выбранной скважины: дебиты, обводнённость, приемистость и давления + даты ГТМ."""
    dataset = dataset or get_gtm_dataset()
    if well in (None, ""):
        return empty_figure("Выберите скважину", height=620)

    result_df = dataset.result_df
    if "well" not in result_df.columns or "date" not in result_df.columns:
        return empty_figure("В result_df нужны столбцы well и date", height=620)

    df = result_df[result_df["well"].eq(well)].copy()
    df = df[df["date"].notna()].sort_values("date")
    if df.empty:
        return empty_figure(f"Нет данных по скважине {well}", height=620)

    metric_cols = [c for c in ["qliq", "qoil", "qinj", "wcut", "Р_пл", "Р_заб"] if c in df.columns]
    if not metric_cols:
        return empty_figure(f"Нет технологических показателей по скважине {well}", height=620)

    ts = df.groupby("date", as_index=False)[metric_cols].mean().sort_values("date")

    fig = go.Figure()

    # Дебиты и приемистость — линии на основной оси
    line_specs = [
        ("qliq", "Q жидкости", COLOR["green"], "solid"),
        ("qoil", "Q нефти", COLOR["red"], "solid"),
        ("qinj", "Приемистость", COLOR["blue"], "dash"),
    ]
    for col, name, color, dash in line_specs:
        if col in ts.columns and ts[col].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=ts["date"],
                    y=ts[col],
                    mode="lines",
                    name=name,
                    line=dict(color=color, width=2.6, dash=dash),
                    yaxis="y",
                    hovertemplate=f"%{{x|%d.%m.%Y}}<br>{name}: %{{y:,.2f}}<extra></extra>",
                )
            )

    # Обводнённость — отдельная правая ось
    if "wcut" in ts.columns and ts["wcut"].notna().any():
        wcut = ts["wcut"].copy()
        wcut_label = "Обводнённость, %"
        if wcut.max(skipna=True) <= 1.5:
            wcut = wcut * 100
        fig.add_trace(
            go.Scatter(
                x=ts["date"],
                y=wcut,
                mode="lines",
                name="Обводнённость",
                line=dict(color=COLOR["blue"], width=2.3, dash="dot"),
                yaxis="y2",
                hovertemplate="%{x|%d.%m.%Y}<br>Обводнённость: %{y:,.1f}%<extra></extra>",
            )
        )
    else:
        wcut_label = "Обводнённость, %"

    # Давления — точки на третьей оси
    pressure_specs = [
        ("Р_пл", "Р пластовое", COLOR["red"], "circle"),
        ("Р_заб", "Р забойное", COLOR["blue"], "diamond"),
    ]
    for col, name, color, symbol in pressure_specs:
        if col in ts.columns and ts[col].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=ts["date"],
                    y=ts[col],
                    mode="markers",
                    name=name,
                    marker=dict(color=color, size=7, symbol=symbol, line=dict(color="white", width=0.8)),
                    yaxis="y3",
                    hovertemplate=f"%{{x|%d.%m.%Y}}<br>{name}: %{{y:,.1f}} атм<extra></extra>",
                )
            )

    # Вертикальные линии ГТМ с подписью операции
    event_cols = [c for c in ["gtm_date", "вид_операции", "направление"] if c in df.columns]
    if "gtm_date" in event_cols:
        events = df[event_cols].dropna(subset=["gtm_date"]).drop_duplicates().sort_values("gtm_date")
        events = events[events["gtm_date"].between(df["date"].min(), df["date"].max(), inclusive="both")]
        for i, row in events.iterrows():
            event_date = row["gtm_date"]
            op = row.get("вид_операции")
            direction = row.get("направление")
            #label = op if pd.notna(op) and str(op).strip() else direction
            label = direction if pd.notna(direction) and str(direction).strip() else op
            label = str(label) if pd.notna(label) and str(label).strip() else "ГТМ"
            fig.add_vline(
                x=event_date,
                line_width=1.4,
                line_dash="dash",
                line_color=COLOR["red"],
                opacity=0.72,
            )
            fig.add_annotation(
                x=event_date,
                y=0.32,
                xref="x",
                yref="paper",
                text=label,
                showarrow=False,
                textangle=-90,
                xanchor="left",
                yanchor="bottom",
                font=dict(size=16, color=COLOR["red"]),
                bgcolor="rgba(255,255,255,0.78)",
                bordercolor="rgba(213,48,51,0.25)",
                borderwidth=1,
            )

    fig.update_layout(
        title=f"История работы скважины {well}",
        xaxis_title="Дата",
        yaxis=dict(
            title=dict(text="Дебит / приемистость, т/сут или м³/сут", font=dict(color=COLOR["navy"])),
            tickfont=dict(color=COLOR["navy"]),
        ),
        yaxis2=dict(
            title=dict(text=wcut_label, font=dict(color=COLOR["orange"])),
            tickfont=dict(color=COLOR["orange"]),
            overlaying="y",
            side="right",
            showgrid=False,
            rangemode="tozero",
        ),
        yaxis3=dict(
            title=dict(text="Давление, атм", font=dict(color=COLOR["gray"])),
            tickfont=dict(color=COLOR["gray"]),
            overlaying="y",
            side="right",
            anchor="free",
            position=0.97,
            showgrid=False,
        ),
        hovermode="x unified",
        margin=dict(t=92, b=62, l=74, r=132),
    )
    fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
    return apply_common_layout(fig, height=660, legend_y=1.08)


# -----------------------------------------------------------------------------
# Dash page
# -----------------------------------------------------------------------------
def layout():
    dataset = get_gtm_dataset()
    return dbc.Container(
        [
            data_status_alert(dataset),
            html.Div(
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.Label("Направление ГТМ"),
                                dcc.Dropdown(
                                    id=cid("direction-filter"),
                                    options=direction_filter_options(),
                                    value=ALL,
                                    clearable=False,
                                    persistence=True,
                                ),
                            ],
                            md=4,
                        ),
                        dbc.Col(
                            [
                                html.Label("Алгоритм расчёта эффективности"),
                                dcc.RadioItems(
                                    id=cid("efficiency-algorithm"),
                                    options=EFFICIENCY_ALGORITHM_OPTIONS,
                                    value=EFFICIENCY_ALGORITHM_DELTA,
                                    persistence=True,
                                    inputClassName="me-1",
                                    labelClassName="me-3",
                                ),
                            ],
                            md=8,
                        ),
                    ],
                    className="g-3",
                ),
                className="control-panel mb-4",
            ),
            dbc.Row(id=cid("kpi-row"), className="mb-2"),

        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        [
                            style_card_header("ГТМ по направлениям добывающих скважин", "Количество операций в выбранном срезе", "ДС"),
                            dbc.CardBody(dcc.Graph(id=cid("prod-direction-counts"), config={"displayModeBar": False})),
                        ],
                        className=CARD_CLASS,
                        style=CARD_STYLE,
                    ),
                    lg=6,
                    className="mb-4",
                ),
                dbc.Col(
                    dbc.Card(
                        [
                            style_card_header("ГТМ по направлениям нагнетательных скважин", "Количество операций в выбранном срезе", "НС"),
                            dbc.CardBody(dcc.Graph(id=cid("inj-direction-counts"), config={"displayModeBar": False})),
                        ],
                        className=CARD_CLASS,
                        style=CARD_STYLE,
                    ),
                    lg=6,
                    className="mb-4",
                ),
            ],
            className="g-4",
        ),

        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        [style_card_header("Приросты и количество ГТМ", "Средние ΔQ и число операций по годам", "01"), dbc.CardBody(dcc.Graph(id=cid("graph-1"), config={"displayModeBar": False}))],
                        className=CARD_CLASS,
                        style=CARD_STYLE,
                    ),
                    lg=6,
                    className="mb-4",
                ),
                dbc.Col(
                    dbc.Card(
                        [style_card_header("Эффективность ГТМ", "Выбранный алгоритм расчёта эффективности", "02"), dbc.CardBody(dcc.Graph(id=cid("graph-2"), config={"displayModeBar": False}))],
                        className=CARD_CLASS,
                        style=CARD_STYLE,
                    ),
                    lg=6,
                    className="mb-4",
                ),
            ],
            className="g-4",
        ),

        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        [style_card_header("Динамика ±15 месяцев", "Средние qliq, qoil и wcut по годам ГТМ", "03"), dbc.CardBody(dcc.Graph(id=cid("graph-3"), config={"displayModeBar": False}))],
                        className=CARD_CLASS,
                        style=CARD_STYLE,
                    ),
                    lg=6,
                    className="mb-4",
                ),
                dbc.Col(
                    dbc.Card(
                        [style_card_header("Кумулятивная динамика", "Годы ГТМ сшиты в единую временную ось", "04"), dbc.CardBody(dcc.Graph(id=cid("graph-4"), config={"displayModeBar": False}))],
                        className=CARD_CLASS,
                        style=CARD_STYLE,
                    ),
                    lg=6,
                    className="mb-4",
                ),
            ],
            className="g-4",
        ),

        dbc.Row(
            dbc.Col(
                dbc.Card(
                    [
                        style_card_header("Структура добычи и дополнительной добычи", "Stacked bar: база + вклад направлений ГТМ", "05"),
                        dbc.CardBody(
                            [
                                dbc.Row(
                                    dbc.Col(
                                        [
                                            html.Label("Тип доп. добычи", className="fw-semibold small text-muted"),
                                            dcc.Dropdown(
                                                id=cid("hist-type-filter"),
                                                options=[
                                                    {"label": "В год проведения ГТМ", "value": "traditional"},
                                                    {"label": "Кумулятивная", "value": "cumulative"},
                                                ],
                                                value="traditional",
                                                clearable=False,
                                            ),
                                        ],
                                        md=4,
                                    ),
                                    className="mb-3",
                                ),
                                dcc.Graph(id=cid("graph-5"), config={"displayModeBar": False}),
                            ]
                        ),
                    ],
                    className=CARD_CLASS,
                    style=CARD_STYLE,
                ),
                width=12,
            ),
            className="mb-4",
        ),

        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        [
                            style_card_header("Неэффективные ГТМ", "Операции с отрицательным ΔQнефти", "06"),
                            dbc.CardBody(
                                dash_table.DataTable(
                                    id=cid("data-table"),
                                    page_size=12,
                                    sort_action="native",
                                    filter_action="native",
                                    export_format="xlsx",
                                    style_table={"overflowX": "auto", "maxHeight": "520px", "overflowY": "auto"},
                                    fixed_rows={"headers": True},
                                    style_cell={
                                        "textAlign": "left",
                                        "minWidth": "95px",
                                        "maxWidth": "190px",
                                        "whiteSpace": "normal",
                                        "fontFamily": FONT_FAMILY,
                                        "fontSize": 12,
                                        "padding": "9px",
                                        "border": "1px solid #E6F2ED",
                                    },
                                    style_header={
                                        "fontWeight": "700",
                                        "backgroundColor": "#F7FAF8",
                                        "color": COLOR["navy"],
                                        "border": "1px solid #DDEEE6",
                                    },
                                    style_data_conditional=[
                                        {"if": {"row_index": "odd"}, "backgroundColor": "#FBFEFC"},
                                        {"if": {"filter_query": "{ΔQнефти} < -5", "column_id": "ΔQнефти"}, "color": COLOR["red"], "fontWeight": "700"},
                                        {"if": {"state": "active"}, "backgroundColor": "#EAF6F1", "border": "1px solid #7CC4A3"},
                                    ],
                                )
                            ),
                        ],
                        className=f"{CARD_CLASS} h-100",
                        style=CARD_STYLE,
                    ),
                    lg=6,
                    className="mb-4",
                ),
                dbc.Col(
                    dbc.Card(
                        [style_card_header("Факторы эффективности", "Распределения и выбросы по ключевым факторам", "07"), dbc.CardBody(dcc.Graph(id=cid("boxplot-factors"), config={"displayModeBar": False}))],
                        className=f"{CARD_CLASS} h-100",
                        style=CARD_STYLE,
                    ),
                    lg=6,
                    className="mb-4",
                ),
            ],
            className="g-4",
        ),

        dbc.Row(
            dbc.Col(
                dbc.Card(
                    [
                        style_card_header(
                            "История работы выбранной скважины",
                            "Дебиты, обводнённость, приемистость, давления и даты ГТМ",
                            "08",
                        ),
                        dbc.CardBody(
                            [
                                dbc.Row(
                                    dbc.Col(
                                        [
                                            html.Label("Скважина", className="fw-semibold small text-muted"),
                                            dcc.Dropdown(
                                                id=cid("well-history-filter"),
                                                options=[],
                                                value=None,
                                                clearable=False,
                                                placeholder="Выберите скважину",
                                            ),
                                        ],
                                        md=4,
                                    ),
                                    className="mb-3",
                                ),
                                dcc.Graph(id=cid("graph-well-history"), config={"displayModeBar": True}),
                            ]
                        ),
                    ],
                    className=CARD_CLASS,
                    style=CARD_STYLE,
                ),
                width=12,
            ),
            className="mb-4",
        ),
        ],
        fluid=True,
        className="gtm-layout",
        style={"minHeight": "100vh", "paddingBottom": "32px"},
    )


def register_callbacks(app):
    @app.callback(
        Output(cid("kpi-row"), "children"),
        Output(cid("prod-direction-counts"), "figure"),
        Output(cid("inj-direction-counts"), "figure"),
        Output(cid("graph-1"), "figure"),
        Output(cid("graph-2"), "figure"),
        Output(cid("graph-3"), "figure"),
        Output(cid("graph-4"), "figure"),
        Output(cid("data-table"), "data"),
        Output(cid("data-table"), "columns"),
        Output(cid("boxplot-factors"), "figure"),
        Input(cid("direction-filter"), "value"),
        Input(cid("efficiency-algorithm"), "value"),
        Input("area-filter", "value"),
        Input("mest-filter", "value"),
        Input("theme-store", "data"),
    )
    def update_dashboard(direction=ALL, efficiency_algorithm=EFFICIENCY_ALGORITHM_DELTA, plosh=ALL, mest=ALL, theme="light"):
        dataset = get_gtm_dataset()
        filtered_result = filter_df(dataset.result_df, direction, plosh, mest)
        filtered_gtm = filter_df(dataset.gtm_level, direction, plosh, mest)
        direction_values = _selected_values(direction)

        table_data, table_columns = make_bad_gtm_table(filtered_gtm)
        if direction_values:
            production_counts = empty_figure("Гистограмма доступна при выборе всех направлений", height=430)
            injection_counts = empty_figure("Гистограмма доступна при выборе всех направлений", height=430)
        else:
            production_counts = fig_gtm_direction_counts(filtered_gtm, "production")
            injection_counts = fig_gtm_direction_counts(filtered_gtm, "injection")

        return (
            make_kpi_cards(filtered_gtm, efficiency_algorithm),
            apply_runtime_theme(production_counts, theme),
            apply_runtime_theme(injection_counts, theme),
            apply_runtime_theme(fig_delta_and_counts(filtered_gtm), theme),
            apply_runtime_theme(fig_efficiency(filtered_gtm, efficiency_algorithm), theme),
            apply_runtime_theme(fig_dynamics_by_year(filtered_result), theme),
            apply_runtime_theme(fig_cumulative_dynamics(filtered_result), theme),
            table_data,
            table_columns,
            apply_runtime_theme(fig_boxplot_factors(direction, plosh, dataset, mest), theme),
        )

    @app.callback(
        Output(cid("graph-5"), "figure"),
        Input("area-filter", "value"),
        Input("mest-filter", "value"),
        Input(cid("hist-type-filter"), "value"),
        Input("theme-store", "data"),
    )
    def update_histogram(plosh=ALL, mest=ALL, hist_type="traditional", theme="light"):
        return apply_runtime_theme(fig_histogram(plosh, hist_type, get_gtm_dataset(), mest), theme)

    @app.callback(
        Output(cid("well-history-filter"), "options"),
        Output(cid("well-history-filter"), "value"),
        Input(cid("direction-filter"), "value"),
        Input("area-filter", "value"),
        Input("mest-filter", "value"),
    )
    def update_well_history_options(direction=ALL, plosh=ALL, mest=ALL):
        dataset = get_gtm_dataset()
        options = make_well_options(direction, plosh, dataset, mest)
        value = options[0]["value"] if options else None
        return options, value

    @app.callback(
        Output(cid("graph-well-history"), "figure"),
        Input(cid("well-history-filter"), "value"),
        Input("theme-store", "data"),
    )
    def update_well_history_graph(well, theme="light"):
        return apply_runtime_theme(fig_well_history(well, get_gtm_dataset()), theme)
