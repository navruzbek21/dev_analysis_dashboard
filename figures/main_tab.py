"""Фигуры вкладки «Основные показатели»: динамика, изменение, карта площадей."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from common import (
    AREA_CONTOUR_EXTENSIONS,
    YEAR_METRICS,
    _normalize_area_name,
    _normalize_block_value,
    _split_contour_name,
    compact,
    format_visible_pct_label,
    logger,
)
from config import settings
from filter_utils import normalize_filter_values
from normalization import ALL_BLOCK_VALUE, AREA_COL_YEAR, BLOCK_COL, safe_div
from theme import HEAT_SCALE, OP_GREEN_DEEP, OP_INK, OP_MUTED, OP_RED, apply_theme, empty_fig


def line_year_metric(d, metric):
    if d.empty or metric not in d.columns:
        return empty_fig()
    group_col, legend_title = _main_chart_group(d)
    fig = px.line(d, x="year", y=metric, color=group_col, markers=True)
    fig.update_layout(xaxis_title="Год", yaxis_title=YEAR_METRICS[metric], legend_title_text=legend_title)
    return apply_theme(fig)


def _main_chart_group(d: pd.DataFrame) -> tuple[str, str]:
    if BLOCK_COL in d.columns:
        block_text = d[BLOCK_COL].astype(str).str.strip()
        has_blocks = d[BLOCK_COL].notna() & ~block_text.str.lower().isin(["", "all"])
        if has_blocks.any():
            if "__block_label__" not in d.columns:
                d["__block_label__"] = "Блок " + block_text
            return "__block_label__", "Блок"
    return AREA_COL_YEAR, "Площадь"


def _aggregate_metric_by_area_year(d, metric):
    """Агрегация выбранного показателя по годам внутри каждой выбранной площади."""
    # Процентные и средние показатели нельзя суммировать.
    mean_metrics = {"wc", "wc_month_avg", "debit_neft", "debit_liq", "debit_vod", "priem"}
    agg_func = "mean" if metric in mean_metrics else "sum"

    work = d.copy()
    group_col, _legend_title = _main_chart_group(work)
    dd = (
        work.dropna(subset=[group_col, "year", metric])
        .groupby([group_col, "year"], as_index=False)
        .agg(value=(metric, agg_func))
        .sort_values([group_col, "year"])
    )
    dd["prev_value"] = dd.groupby(group_col)["value"].shift(1)
    dd["change_pct"] = 100 * safe_div(dd["value"] - dd["prev_value"], dd["prev_value"])
    dd["year"] = dd["year"].astype(int)
    dd["year_label"] = dd["year"].astype(str)
    return dd, group_col, _legend_title


def change_bar(d, metric, period):
    if d.empty or metric not in d.columns:
        return empty_fig()

    ly = int(d["year"].max())

    # Режимы 3y/5y: показываем YoY-изменение отдельно по каждой выбранной площади.
    # Годы выводятся на оси X в порядке возрастания.
    if period in {"3y", "5y"}:
        n_years = 3 if period == "3y" else 5
        dd, group_col, legend_title = _aggregate_metric_by_area_year(d, metric)
        dd = (
            dd[(dd["year"] >= ly - n_years + 1) & (dd["year"] <= ly)]
            .dropna(subset=["change_pct"])
            .sort_values(["year", group_col])
        )

        if dd.empty:
            return empty_fig("Недостаточно данных для год-к-году по выбранным площадям")

        year_order = [str(y) for y in sorted(dd["year"].unique())]
        area_order = sorted(dd[group_col].dropna().unique())

        fig = px.bar(
            dd,
            x="year_label",
            y="change_pct",
            color=group_col,
            barmode="group",
            text=[format_visible_pct_label(v) for v in dd["change_pct"]],
            category_orders={"year_label": year_order, group_col: area_order},
            hover_data={
                group_col: True,
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
            legend_title_text=legend_title,
            bargap=0.22,
            bargroupgap=0.08,
        )
        fig.update_xaxes(type="category", categoryorder="array", categoryarray=year_order)
        fig.add_hline(y=0, line_width=1, line_dash="dot", line_color=OP_MUTED)
        return apply_theme(fig)

    # Режим prev оставляем как было: срез последнего года по площадям к предыдущему году.
    rows = []
    work = d.copy()
    group_col, legend_title = _main_chart_group(work)
    for area, g in work.groupby(group_col):
        g = g.sort_values("year")
        curr = g.loc[g["year"] == ly, metric]
        if curr.empty:
            continue
        curr = curr.iloc[0]
        base_s = g.loc[g["year"] == ly - 1, metric]
        base = base_s.iloc[0] if not base_s.empty else np.nan
        rows.append({group_col: area, "change_pct": 100 * safe_div(pd.Series([curr - base]), pd.Series([base]))[0]})

    dd = pd.DataFrame(rows).dropna(subset=["change_pct"])
    if dd.empty:
        return empty_fig("Недостаточно данных для сравнения")

    fig = px.bar(dd, x=group_col, y="change_pct", color=group_col, text=[format_visible_pct_label(v) for v in dd["change_pct"]])
    fig.update_traces(texttemplate="%{text}", textposition="outside", cliponaxis=False)
    fig.update_layout(
        xaxis_title=legend_title,
        yaxis_title="Изменение, %",
        legend_title_text=legend_title,
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
    group_col, legend_title = _main_chart_group(x)
    size_col = "dobycha_nefti" if "dobycha_nefti" in x.columns else None
    fig = px.scatter(
        x,
        x="wc_plot",
        y="debit_neft",
        color=group_col,
        size=size_col,
        hover_data=[c for c in [group_col, AREA_COL_YEAR, BLOCK_COL, "ngdu", "dobycha_nefti", "debit_liq"] if c in x.columns],
        labels={"wc_plot": "Средняя обводнённость, %", "debit_neft": "Средний дебит нефти, т/сут"},
    )
    fig.update_layout(legend_title_text=legend_title)
    return apply_theme(fig)


def _read_irap_classic_ascii_contour(path: Path) -> pd.DataFrame:
    """Читает контур площади из IRAP classic ASCII с тремя числовыми колонками X/Y/Z."""
    rows = []
    with path.open("r", encoding="utf-8", errors="ignore") as file:
        for line in file:
            parts = line.replace(",", " ").split()
            if len(parts) < 3:
                continue
            try:
                x, y, z = (float(parts[0]), float(parts[1]), float(parts[2]))
            except ValueError:
                continue
            if np.isfinite(x) and np.isfinite(y):
                rows.append((x, y, z))
    return pd.DataFrame(rows, columns=["x", "y", "z"])


def _contours_dir() -> Path:
    contour_dir = Path(settings.area_contours_dir)
    if not contour_dir.is_absolute():
        # figures/ лежит на уровень ниже корня приложения.
        contour_dir = Path(__file__).resolve().parent.parent / contour_dir
    return contour_dir


def _contours_signature() -> tuple:
    """Сигнатура каталога контуров: (path, mtime, size) каждого файла.

    Ключ кэша: добавили или заменили файл контура — кэш инвалидируется сам,
    без рестарта приложения (в отличие от прежнего lru_cache(maxsize=1)).
    """
    contour_dir = _contours_dir()
    if not contour_dir.exists():
        return (str(contour_dir), None)
    entries = []
    for path in sorted(p for p in contour_dir.rglob("*") if p.is_file() and p.suffix.lower() in AREA_CONTOUR_EXTENSIONS):
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((str(path), stat.st_mtime_ns, stat.st_size))
    return (str(contour_dir), tuple(entries))


def _load_area_contours() -> dict[str, dict]:
    return _load_area_contours_cached(_contours_signature())


@lru_cache(maxsize=4)
def _load_area_contours_cached(signature: tuple) -> dict[str, dict]:
    contour_dir, entries = signature
    if entries is None:
        logger.info("Area contours directory does not exist: %s", contour_dir)
        return {}

    contours = {}
    for path_str, _mtime_ns, _size in entries:
        path = Path(path_str)
        points = _read_irap_classic_ascii_contour(path)
        if len(points) < 3:
            logger.warning("Area contour file has fewer than 3 points: %s", path)
            continue
        area_name, block = _split_contour_name(path.stem)
        contour = {"area": area_name, "block": block, "path": str(path), "points": points}
        if block:
            contours[f"{_normalize_area_name(area_name)}::{block}"] = contour
        else:
            contours[_normalize_area_name(area_name)] = contour
    return contours


def _latest_metric_by_area(d: pd.DataFrame, metric: str, block_mode: str = "area") -> pd.DataFrame:
    if d.empty or metric not in d.columns:
        return pd.DataFrame(columns=[AREA_COL_YEAR, BLOCK_COL, "value", "year"])
    ly = int(d["year"].max())
    current = d[d["year"] == ly].dropna(subset=[AREA_COL_YEAR, metric]).copy()
    if current.empty:
        return pd.DataFrame(columns=[AREA_COL_YEAR, BLOCK_COL, "value", "year"])
    if BLOCK_COL not in current.columns:
        current[BLOCK_COL] = "all"
    block_text = current[BLOCK_COL].astype(str).str.strip().str.lower()
    if block_mode == "block":
        current = current[current[BLOCK_COL].notna() & ~block_text.isin(["", "all"])].copy()
        group_cols = [AREA_COL_YEAR, BLOCK_COL]
    else:
        area_level = current[BLOCK_COL].isna() | block_text.isin(["", "all"])
        if area_level.any():
            current = current[area_level].copy()
        group_cols = [AREA_COL_YEAR]
    mean_metrics = {"wc", "wc_month_avg", "debit_neft", "debit_liq", "debit_vod", "priem"}
    agg_func = "mean" if metric in mean_metrics else "sum"
    result = current.groupby(group_cols, as_index=False).agg(value=(metric, agg_func))
    if BLOCK_COL not in result.columns:
        result[BLOCK_COL] = "all"
    result["year"] = ly
    return result


def _block_annotation_metrics(d: pd.DataFrame, area, block, year) -> list[str]:
    if d.empty or BLOCK_COL not in d.columns:
        return []
    block_text = d[BLOCK_COL].astype(str).str.strip()
    part = d[d[AREA_COL_YEAR].eq(area) & block_text.eq(str(block).strip())].copy()
    if part.empty:
        return []
    part["year"] = pd.to_numeric(part["year"], errors="coerce")
    current = part[part["year"].eq(year)].copy()
    if current.empty:
        current = part[part["year"].eq(part["year"].max())].copy()
    row = current.iloc[0]
    lines = []
    if "niz" in row and "dobycha_nefti_cum" in row and pd.notna(row.get("niz")) and pd.notna(row.get("dobycha_nefti_cum")):
        lines.append(f"Ост. НИЗ: {compact(float(row['niz']) - float(row['dobycha_nefti_cum']))}")
    if "niz_otbor" in row and pd.notna(row.get("niz_otbor")):
        lines.append(f"Котб НИЗ: {float(row['niz_otbor']):.2f}")
    pressure_col = "Р_пл" if "Р_пл" in part.columns else ("p_pl" if "p_pl" in part.columns else None)
    if pressure_col:
        first_pressure = pd.to_numeric(part.sort_values("year")[pressure_col], errors="coerce").dropna()
        current_pressure = pd.to_numeric(current[pressure_col], errors="coerce").dropna()
        if not first_pressure.empty and not current_pressure.empty and first_pressure.iloc[0] != 0:
            lines.append(f"Ртек/Рнач: {current_pressure.iloc[0] / first_pressure.iloc[0]:.2f}")
    return lines


def area_metric_contour_map(d: pd.DataFrame, metric: str, selected_areas=()):
    if d.empty or metric not in d.columns:
        return empty_fig("Нет данных для карты площадей")

    contours = _load_area_contours()
    if not contours:
        return empty_fig(f"Нет контуров площадей. Укажите IRAP ASCII файлы в {settings.area_contours_dir}")

    values = _latest_metric_by_area(d, metric)
    if values.empty:
        return empty_fig("Нет значений показателя для карты площадей")

    values["area_key"] = values[AREA_COL_YEAR].map(_normalize_area_name)
    value_by_key = values.set_index("area_key").to_dict("index")
    selected_area_values = normalize_filter_values(selected_areas)
    single_area = selected_area_values[0] if len(selected_area_values) == 1 else None
    block_values = pd.DataFrame()
    if single_area:
        block_source = d[d[AREA_COL_YEAR].eq(single_area)] if AREA_COL_YEAR in d.columns else d
        block_values = _latest_metric_by_area(block_source, metric, block_mode="block")

    matched_keys = [key for key in value_by_key if key in contours]
    block_rows = []
    for row in block_values.to_dict("records"):
        block = _normalize_block_value(row.get(BLOCK_COL))
        block_key = f"{_normalize_area_name(row.get(AREA_COL_YEAR))}::{block}"
        if block != ALL_BLOCK_VALUE and block_key in contours:
            block_rows.append((block_key, row))
    if not matched_keys and not block_rows:
        return empty_fig("Нет совпадений между названиями площадей и файлами контуров")

    metric_values = np.array(
        [float(value_by_key[key]["value"]) for key in matched_keys] + [float(row["value"]) for _key, row in block_rows],
        dtype=float,
    )
    finite_values = metric_values[np.isfinite(metric_values)]
    if finite_values.size == 0:
        return empty_fig("Нет числовых значений показателя для карты площадей")
    vmin, vmax = float(np.nanmin(finite_values)), float(np.nanmax(finite_values))
    denom = vmax - vmin

    fig = go.Figure()
    annotations = []
    click_x = []
    click_y = []
    click_text = []
    click_customdata = []

    def add_contour_trace(key, row, is_block=False):
        contour = contours[key]
        points = contour["points"]
        area_value = float(row["value"])
        norm_value = 0.5 if denom == 0 else (area_value - vmin) / denom
        fill_color = px.colors.sample_colorscale(HEAT_SCALE, [float(np.clip(norm_value, 0, 1))])[0]
        x = points["x"].tolist()
        y = points["y"].tolist()
        if x[0] != x[-1] or y[0] != y[-1]:
            x.append(x[0])
            y.append(y[0])

        area_label = row[AREA_COL_YEAR]
        block = _normalize_block_value(row.get(BLOCK_COL))
        label_text = f"Блок {block}" if is_block else str(area_label)
        annotation_lines = _block_annotation_metrics(d, area_label, block, row["year"]) if is_block else []
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines",
                name=label_text,
                fill="toself",
                fillcolor=fill_color,
                hoveron="fills+points",
                line=dict(color=OP_RED if is_block else OP_GREEN_DEEP, width=2.0 if is_block else 1.4),
                customdata=[[area_label, area_value, int(row["year"]), block if is_block else ALL_BLOCK_VALUE]] * len(x),
                hovertemplate="Площадь %{customdata[0]}<br>"
                + ("Блок %{customdata[3]}<br>" if is_block else "")
                + "Год %{customdata[2]}<br>"
                + f"{YEAR_METRICS.get(metric, metric)}: "
                + "%{customdata[1]:,.2f}<extra></extra>",
                showlegend=False,
            )
        )
        annotations.append(
            dict(
                x=float(points["x"].mean()),
                y=float(points["y"].mean()),
                text="<br>".join(([f"{label_text}: {compact(area_value)}"] if is_block else [label_text, compact(area_value)]) + annotation_lines),
                showarrow=False,
                font=dict(size=11, color=OP_INK),
                bgcolor="rgba(255,255,255,0.72)",
                bordercolor="rgba(0,0,0,0.08)",
                borderpad=3,
                captureevents=False,
            )
        )
        click_x.append(float(points["x"].mean()))
        click_y.append(float(points["y"].mean()))
        click_text.append(label_text)
        click_customdata.append([area_label, area_value, int(row["year"]), block if is_block else ALL_BLOCK_VALUE])

    for key in matched_keys:
        add_contour_trace(key, value_by_key[key], is_block=False)
    for key, row in block_rows:
        add_contour_trace(key, row, is_block=True)

    if click_x:
        fig.add_trace(
            go.Scatter(
                x=click_x,
                y=click_y,
                mode="markers+text",
                text=click_text,
                textposition="middle center",
                marker=dict(size=56, color="rgba(0,142,91,0.04)", line=dict(color="rgba(0,107,69,0.35)", width=1)),
                customdata=click_customdata,
                hovertemplate="Площадь %{customdata[0]}<br>"
                + "Блок %{customdata[3]}<br>"
                + f"{YEAR_METRICS.get(metric, metric)}: "
                + "%{customdata[1]:,.2f}<extra></extra>",
                showlegend=False,
            )
        )

    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(
                colorscale=HEAT_SCALE,
                cmin=vmin,
                cmax=vmax,
                color=[vmin],
                colorbar=dict(title=YEAR_METRICS.get(metric, metric), thickness=14, len=0.78),
                showscale=True,
            ),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.update_layout(
        xaxis_title="X",
        yaxis_title="Y",
        annotations=annotations,
        margin=dict(l=42, r=84, t=30, b=42),
    )
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    return apply_theme(fig, height=520)

