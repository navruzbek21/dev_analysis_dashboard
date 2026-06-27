from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

import gtm_analysis
from filter_utils import normalize_filter_values
from normalization import AREA_COL_YEAR, safe_div
from services import data_service


ALLOWED_METRICS = {
    "dobycha_nefti": "Добыча нефти",
    "dobycha_liq": "Добыча жидкости",
    "zakachka": "Закачка воды",
    "wc": "Обводненность",
    "debit_neft": "Дебит нефти",
    "debit_liq": "Дебит жидкости",
    "dob_fond": "Добывающий фонд",
    "nagn_fond": "Нагнетательный фонд",
    "kin": "КИН",
    "kiz": "КИЗ",
}

MEAN_METRICS = {"wc", "debit_neft", "debit_liq", "kin", "kiz"}
CHANGE_PERIODS = {"prev": 1, "3y": 3, "5y": 5}
ALLOWED_TOOLS = {"metric_dynamics", "metric_change", "gtm_structure", "gtm_efficiency"}


@dataclass(frozen=True)
class ToolResult:
    tool: str
    title: str
    chart_type: str
    rows: list[dict[str, Any]]
    columns: list[str]
    summary: dict[str, Any]
    chart: dict[str, Any] | None = None
    notes: list[str] | None = None


def tools_schema() -> dict[str, Any]:
    return {
        "tools": {
            "metric_dynamics": {
                "description": "Динамика выбранной метрики по годам.",
                "params": {"metric": list(ALLOWED_METRICS), "filters": {"mest": [], "ngdu": [], "areas": []}},
            },
            "metric_change": {
                "description": "Изменение выбранной метрики к предыдущему году, 3 или 5 годам.",
                "params": {"metric": list(ALLOWED_METRICS), "period": list(CHANGE_PERIODS), "filters": {"mest": [], "ngdu": [], "areas": []}},
            },
            "gtm_structure": {
                "description": "Структура добычи и дополнительной добычи по направлениям ГТМ.",
                "params": {"hist_type": ["traditional", "cumulative"], "filters": {"mest": [], "areas": []}},
            },
            "gtm_efficiency": {
                "description": "Эффективность ГТМ: количество операций, доля эффективных, средние приросты.",
                "params": {"filters": {"mest": [], "direction": None, "areas": []}},
            },
        },
        "metrics": ALLOWED_METRICS,
    }


def make_plan_prompt(user_text: str) -> str:
    schema = tools_schema()
    return (
        "Ты аналитический диспетчер дашборда разработки месторождения. "
        "Верни только JSON без markdown. Не пиши SQL. Выбери один инструмент из списка. "
        "Если пользователь просит график/гистограмму/динамику, выбирай подходящий chart tool.\n"
        f"Доступные инструменты и метрики:\n{schema}\n\n"
        "Формат ответа:\n"
        '{"tool":"metric_dynamics","params":{"metric":"dobycha_nefti","period":"prev",'
        '"hist_type":"traditional","filters":{"ngdu":[],"areas":[],"direction":null}},'
        '"explain":true}\n\n'
        f"Запрос пользователя: {user_text}"
    )


def parse_plan(raw_text: str) -> dict[str, Any] | None:
    if not raw_text:
        return None
    text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S | re.I)
    if fenced:
        text = fenced.group(1).strip()
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        text = text[first:last + 1]
    try:
        import json

        value = json.loads(text)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def fallback_plan(user_text: str) -> dict[str, Any]:
    text = user_text.lower()
    metric = _infer_metric(text)
    if "гтм" in text and any(word in text for word in ["структур", "доп", "дополнитель", "гист", "stack", "стек"]):
        hist_type = "cumulative" if any(word in text for word in ["кумуля", "накоп"]) else "traditional"
        return {"tool": "gtm_structure", "params": {"hist_type": hist_type, "filters": {}}, "explain": True}
    if "гтм" in text and any(word in text for word in ["эффект", "успеш", "прирост", "операц"]):
        return {"tool": "gtm_efficiency", "params": {"filters": {}}, "explain": True}
    if any(word in text for word in ["измен", "сравн", "прошл", "прирост", "паден", "сниз", "рост"]):
        period = "5y" if "5" in text else ("3y" if "3" in text else "prev")
        return {"tool": "metric_change", "params": {"metric": metric, "period": period, "filters": {}}, "explain": True}
    return {"tool": "metric_dynamics", "params": {"metric": metric, "filters": {}}, "explain": True}


def execute_plan(plan: dict[str, Any]) -> ToolResult:
    tool = str(plan.get("tool") or "").strip()
    if tool not in ALLOWED_TOOLS:
        raise ValueError(f"Неизвестный аналитический инструмент: {tool or 'не указан'}")
    params = plan.get("params") if isinstance(plan.get("params"), dict) else {}
    if tool == "metric_dynamics":
        return metric_dynamics(params)
    if tool == "metric_change":
        return metric_change(params)
    if tool == "gtm_structure":
        return gtm_structure(params)
    if tool == "gtm_efficiency":
        return gtm_efficiency(params)
    raise ValueError(f"Инструмент не реализован: {tool}")


def make_explanation_prompt(user_text: str, plan: dict[str, Any], result: ToolResult) -> str:
    rows_preview = result.rows[:30]
    return (
        "Ты аналитик нефтяного дашборда. Дай короткий вывод на русском языке. "
        "Опирайся только на агрегированные данные ниже. Не выдумывай причин, если они не следуют из данных. "
        "Структура: 2-4 предложения, затем 1-3 пункта что проверить дальше.\n\n"
        f"Запрос пользователя: {user_text}\n"
        f"План: {plan}\n"
        f"Заголовок результата: {result.title}\n"
        f"Сводка: {result.summary}\n"
        f"Строки: {rows_preview}"
    )


def fallback_explanation(user_text: str, result: ToolResult) -> str:
    summary = result.summary
    if result.tool in {"metric_dynamics", "metric_change"}:
        label = summary.get("metric_label", "Показатель")
        current = summary.get("last_value")
        change = summary.get("last_change_pct")
        if change is None or not np.isfinite(change):
            return f"Построил агрегированный срез по показателю «{label}». Недостаточно базы сравнения для корректного процента изменения."
        direction = "вырос" if change > 0 else ("снизился" if change < 0 else "не изменился")
        return (
            f"Показатель «{label}» в последнем доступном году {direction} на {change:+.1f}% к базе сравнения. "
            f"Последнее значение: {_fmt_number(current)}. Проверьте вклад по площадям и сопоставьте динамику с изменениями фонда, закачки и обводненности."
        )
    if result.tool == "gtm_structure":
        total = summary.get("total")
        top_category = summary.get("top_category")
        return (
            f"Построена структура добычи и дополнительной добычи по ГТМ. "
            f"Суммарное значение в срезе: {_fmt_number(total)}; крупнейшая категория: {top_category or 'не определена'}. "
            "Для интерпретации стоит сравнить вклад направлений ГТМ с базовой добычей по годам."
        )
    if result.tool == "gtm_efficiency":
        return (
            f"В выборке {summary.get('gtm_count', 0)} ГТМ, доля эффективных операций {summary.get('efficiency_pct', 0):.1f}%. "
            f"Средний прирост нефти: {summary.get('avg_delta_oil', 0):+.2f} т/сут. "
            "Следующий шаг - сравнить эффективность по направлениям и площадям."
        )
    return "Построил аналитический срез по доступным агрегированным данным."


def result_to_payload(result: ToolResult, explanation: str, plan: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "kind": "analysis",
        "message": explanation,
        "analysis": {
            "title": result.title,
            "tool": result.tool,
            "chart_type": result.chart_type,
            "columns": result.columns,
            "rows": result.rows[:200],
            "row_count": len(result.rows),
            "summary": result.summary,
            "chart": result.chart,
            "notes": result.notes or [],
            "plan": plan,
            "plan_source": source,
        },
    }


def metric_dynamics(params: dict[str, Any]) -> ToolResult:
    metric = _validate_metric(params.get("metric"))
    data = _filtered_year_data(params.get("filters"))
    grouped = _aggregate_year_metric(data, metric)
    rows = _clean_rows(grouped.to_dict("records"))
    label = ALLOWED_METRICS[metric]
    summary = _metric_summary(grouped, label)
    return ToolResult(
        tool="metric_dynamics",
        title=f"Динамика: {label}",
        chart_type="line",
        rows=rows,
        columns=["year", "value", "change_pct"],
        summary=summary,
        chart=_chart_payload("line", rows, x="year", y="value", label=label),
        notes=_filter_notes(params.get("filters")),
    )


def metric_change(params: dict[str, Any]) -> ToolResult:
    metric = _validate_metric(params.get("metric"))
    period = str(params.get("period") or "prev")
    if period not in CHANGE_PERIODS:
        period = "prev"
    data = _filtered_year_data(params.get("filters"))
    grouped = _aggregate_year_metric(data, metric)
    offset = CHANGE_PERIODS[period]
    grouped["base_value"] = grouped["value"].shift(offset)
    grouped["change_pct"] = 100 * safe_div(grouped["value"] - grouped["base_value"], grouped["base_value"])
    rows = _clean_rows(grouped.replace({np.nan: None}).to_dict("records"))
    label = ALLOWED_METRICS[metric]
    summary = _metric_summary(grouped, label)
    summary["period"] = period
    return ToolResult(
        tool="metric_change",
        title=f"Изменение: {label}",
        chart_type="bar",
        rows=rows,
        columns=["year", "value", "base_value", "change_pct"],
        summary=summary,
        chart=_chart_payload("bar", rows, x="year", y="change_pct", label=f"{label}, изменение %"),
        notes=_filter_notes(params.get("filters")),
    )


def gtm_structure(params: dict[str, Any]) -> ToolResult:
    hist_type = str(params.get("hist_type") or "traditional")
    if hist_type not in {"traditional", "cumulative"}:
        hist_type = "traditional"
    filters = params.get("filters") if isinstance(params.get("filters"), dict) else {}
    areas = _selected_values(filters.get("areas") or filters.get("plosh"))
    mest = _selected_values(filters.get("mest") or filters.get("selected_mest"))
    dataset = gtm_analysis.get_gtm_dataset()
    data = gtm_analysis.prepare_hist_data(areas or gtm_analysis.ALL, hist_type, dataset, mest or gtm_analysis.ALL)
    if data.empty:
        rows: list[dict[str, Any]] = []
    else:
        data = data.copy()
        data["year"] = pd.to_numeric(data["year"], errors="coerce")
        data = data[data["year"].ge(2021)].copy()
        data["Категория"] = data["Категория"].replace({"base_dob": "Базовая добыча"})
        data = data.groupby(["year", "Категория"], as_index=False)["Добыча нефти, тонн"].sum()
        data = data.sort_values(["year", "Категория"])
        rows = _clean_rows(data.to_dict("records"))
    total_by_category: dict[str, float] = {}
    for row in rows:
        category = str(row.get("Категория"))
        total_by_category[category] = total_by_category.get(category, 0.0) + float(row.get("Добыча нефти, тонн") or 0)
    top_category = max(total_by_category, key=total_by_category.get) if total_by_category else None
    summary = {
        "hist_type": hist_type,
        "total": sum(total_by_category.values()),
        "top_category": top_category,
        "category_count": len(total_by_category),
        "year_count": len({row.get("year") for row in rows}),
    }
    return ToolResult(
        tool="gtm_structure",
        title="Структура добычи и дополнительной добычи",
        chart_type="stacked_bar",
        rows=rows,
        columns=["year", "Категория", "Добыча нефти, тонн"],
        summary=summary,
        chart=_chart_payload("stacked_bar", rows, x="year", y="Добыча нефти, тонн", color="Категория", label="Добыча нефти, тонн"),
        notes=_filter_notes(filters),
    )


def gtm_efficiency(params: dict[str, Any]) -> ToolResult:
    filters = params.get("filters") if isinstance(params.get("filters"), dict) else {}
    dataset = gtm_analysis.get_gtm_dataset()
    direction = filters.get("direction") or gtm_analysis.ALL
    areas = _selected_values(filters.get("areas") or filters.get("plosh"))
    mest = _selected_values(filters.get("mest") or filters.get("selected_mest"))
    gtm = gtm_analysis.filter_df(dataset.gtm_level, direction, areas or gtm_analysis.ALL, mest or gtm_analysis.ALL)
    if gtm.empty:
        rows: list[dict[str, Any]] = []
        summary = {"gtm_count": 0, "efficiency_pct": 0.0, "avg_delta_oil": 0.0, "avg_delta_liq": 0.0}
    else:
        yearly = (
            gtm.groupby("gtm_year", dropna=False)
            .agg(
                gtm_count=("effective", "size"),
                effective_count=("effective", "sum"),
                avg_delta_oil=("Δqoil", "mean"),
                avg_delta_liq=("Δqliq", "mean"),
            )
            .reset_index()
            .rename(columns={"gtm_year": "year"})
            .sort_values("year")
        )
        yearly["efficiency_pct"] = np.where(yearly["gtm_count"].gt(0), yearly["effective_count"] * 100 / yearly["gtm_count"], 0)
        rows = _clean_rows(yearly.to_dict("records"))
        summary = {
            "gtm_count": int(gtm.shape[0]),
            "efficiency_pct": float(100 * gtm["effective"].mean()),
            "avg_delta_oil": float(gtm["Δqoil"].mean(skipna=True)),
            "avg_delta_liq": float(gtm["Δqliq"].mean(skipna=True)),
        }
    return ToolResult(
        tool="gtm_efficiency",
        title="Эффективность ГТМ",
        chart_type="bar",
        rows=rows,
        columns=["year", "gtm_count", "effective_count", "efficiency_pct", "avg_delta_oil", "avg_delta_liq"],
        summary=summary,
        chart=_chart_payload("bar", rows, x="year", y="efficiency_pct", label="Эффективность, %"),
        notes=_filter_notes(filters),
    )


def _filtered_year_data(filters: Any) -> pd.DataFrame:
    filter_dict = filters if isinstance(filters, dict) else {}
    ngdu = normalize_filter_values(filter_dict.get("ngdu") or filter_dict.get("selected_ngdu") or ())
    areas = normalize_filter_values(filter_dict.get("areas") or filter_dict.get("plosh") or filter_dict.get("selected_areas") or ())
    mest = normalize_filter_values(filter_dict.get("mest") or filter_dict.get("selected_mest") or ())
    return data_service.get_filtered_year_data(ngdu, areas, mest)


def _aggregate_year_metric(data: pd.DataFrame, metric: str) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame(columns=["year", "value", "change_pct"])
    if "year" not in data.columns or metric not in data.columns:
        missing = ", ".join([col for col in ["year", metric] if col not in data.columns])
        raise ValueError(f"В данных нет нужных колонок: {missing}")
    agg = "mean" if metric in MEAN_METRICS else "sum"
    grouped = (
        data.dropna(subset=["year", metric])
        .groupby("year", as_index=False)
        .agg(value=(metric, agg))
        .sort_values("year")
    )
    grouped["change_pct"] = 100 * safe_div(grouped["value"] - grouped["value"].shift(1), grouped["value"].shift(1))
    return grouped.replace({np.nan: None})


def _metric_summary(grouped: pd.DataFrame, label: str) -> dict[str, Any]:
    if grouped.empty:
        return {"metric_label": label, "last_year": None, "last_value": None, "last_change_pct": None, "min_value": None, "max_value": None}
    last = grouped.iloc[-1]
    change = last.get("change_pct")
    values = pd.to_numeric(grouped["value"], errors="coerce").dropna()
    return {
        "metric_label": label,
        "last_year": _json_scalar(last.get("year")),
        "last_value": _json_scalar(last.get("value")),
        "last_change_pct": _json_scalar(change),
        "min_value": _json_scalar(values.min()) if not values.empty else None,
        "max_value": _json_scalar(values.max()) if not values.empty else None,
        "year_count": int(grouped.shape[0]),
    }


def _chart_payload(chart_type: str, rows: list[dict[str, Any]], x: str, y: str, label: str, color: str | None = None) -> dict[str, Any]:
    return {
        "type": chart_type,
        "x": x,
        "y": y,
        "color": color,
        "label": label,
        "svg": _svg_chart(chart_type, rows, x, y, label, color),
    }


def _svg_chart(chart_type: str, rows: list[dict[str, Any]], x: str, y: str, label: str, color: str | None = None) -> str:
    if not rows:
        return _empty_svg("Нет данных")
    if chart_type == "stacked_bar" and color:
        return _stacked_svg(rows, x, y, color, label)
    return _single_series_svg(rows, x, y, label, chart_type)


def _single_series_svg(rows: list[dict[str, Any]], x: str, y: str, label: str, chart_type: str) -> str:
    points = []
    for row in rows:
        xv = row.get(x)
        yv = _to_float(row.get(y))
        if xv is not None and yv is not None:
            points.append((str(int(xv)) if isinstance(xv, (int, float)) and float(xv).is_integer() else str(xv), yv))
    if not points:
        return _empty_svg("Нет числовых данных")
    width, height = 760, 300
    left, right, top, bottom = 58, 20, 24, 42
    plot_w, plot_h = width - left - right, height - top - bottom
    y_values = [p[1] for p in points]
    ymin = min(0.0, min(y_values))
    ymax = max(0.0, max(y_values))
    if math.isclose(ymin, ymax):
        ymax = ymin + 1
    zero_y = top + plot_h - ((0 - ymin) / (ymax - ymin)) * plot_h
    step = plot_w / max(len(points), 1)
    bar_w = max(8, min(42, step * 0.62))
    elems = [_svg_base(width, height), f'<text x="{left}" y="18" class="title">{html.escape(label)}</text>']
    elems.append(f'<line x1="{left}" y1="{zero_y:.1f}" x2="{width - right}" y2="{zero_y:.1f}" class="axis"/>')
    line_points = []
    for idx, (label_x, value) in enumerate(points):
        cx = left + step * idx + step / 2
        cy = top + plot_h - ((value - ymin) / (ymax - ymin)) * plot_h
        if chart_type == "bar":
            y0 = min(cy, zero_y)
            h = abs(zero_y - cy)
            fill = "#008E5B" if value >= 0 else "#D53033"
            elems.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" height="{max(h, 1):.1f}" fill="{fill}" opacity="0.88"/>')
        else:
            line_points.append(f"{cx:.1f},{cy:.1f}")
            elems.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="#008E5B"/>')
        if idx % max(1, len(points) // 8) == 0 or idx == len(points) - 1:
            elems.append(f'<text x="{cx:.1f}" y="{height - 18}" class="tick" text-anchor="middle">{html.escape(label_x)}</text>')
    if chart_type != "bar" and len(line_points) > 1:
        elems.append(f'<polyline points="{" ".join(line_points)}" fill="none" stroke="#008E5B" stroke-width="3"/>')
    elems.append(_svg_close())
    return "".join(elems)


def _stacked_svg(rows: list[dict[str, Any]], x: str, y: str, color: str, label: str) -> str:
    years = sorted({row.get(x) for row in rows if row.get(x) is not None})
    categories = sorted({str(row.get(color)) for row in rows if row.get(color) is not None})
    if not years or not categories:
        return _empty_svg("Нет данных")
    matrix: dict[Any, dict[str, float]] = {year: {cat: 0.0 for cat in categories} for year in years}
    for row in rows:
        year = row.get(x)
        cat = str(row.get(color))
        value = _to_float(row.get(y)) or 0.0
        if year in matrix and cat in matrix[year]:
            matrix[year][cat] += max(value, 0.0)
    totals = [sum(matrix[year].values()) for year in years]
    ymax = max(totals) or 1.0
    width, height = 760, 330
    left, right, top, bottom = 58, 160, 24, 42
    plot_w, plot_h = width - left - right, height - top - bottom
    step = plot_w / max(len(years), 1)
    bar_w = max(10, min(44, step * 0.62))
    palette = ["#E7E6E6", "#008E5B", "#00B473", "#D53033", "#7CB342", "#44546A", "#F2B84B", "#7E8C86", "#B8D9CC", "#006B45"]
    elems = [_svg_base(width, height), f'<text x="{left}" y="18" class="title">{html.escape(label)}</text>']
    for idx, year in enumerate(years):
        cx = left + step * idx + step / 2
        y_cursor = top + plot_h
        for cat_idx, cat in enumerate(categories):
            value = matrix[year][cat]
            h = (value / ymax) * plot_h
            if h <= 0:
                continue
            y_cursor -= h
            elems.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{y_cursor:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{palette[cat_idx % len(palette)]}" opacity="0.9"/>')
        if idx % max(1, len(years) // 8) == 0 or idx == len(years) - 1:
            elems.append(f'<text x="{cx:.1f}" y="{height - 18}" class="tick" text-anchor="middle">{html.escape(str(int(year) if isinstance(year, (int, float)) else year))}</text>')
    legend_x = width - right + 22
    for cat_idx, cat in enumerate(categories[:10]):
        y_pos = top + 16 + cat_idx * 19
        elems.append(f'<rect x="{legend_x}" y="{y_pos - 10}" width="10" height="10" fill="{palette[cat_idx % len(palette)]}"/>')
        elems.append(f'<text x="{legend_x + 16}" y="{y_pos}" class="legend">{html.escape(cat[:24])}</text>')
    elems.append(_svg_close())
    return "".join(elems)


def _svg_base(width: int, height: int) -> str:
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" class="analysis-chart-svg" xmlns="http://www.w3.org/2000/svg">'
        "<style>"
        ".title{font:700 13px Montserrat,Arial;fill:var(--op-green,#008E5B)}"
        ".tick,.legend{font:600 10px Montserrat,Arial;fill:var(--op-muted,#6F7D76)}"
        ".axis{stroke:var(--op-border,#DDE7E1);stroke-width:1}"
        "</style>"
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="var(--op-card,#fff)"/>'
    )


def _svg_close() -> str:
    return "</svg>"


def _empty_svg(text: str) -> str:
    safe_text = html.escape(text)
    return (
        '<svg viewBox="0 0 760 180" role="img" class="analysis-chart-svg" xmlns="http://www.w3.org/2000/svg">'
        '<rect width="760" height="180" fill="var(--op-card,#fff)"/>'
        f'<text x="380" y="92" text-anchor="middle" style="font:700 14px Montserrat,Arial;fill:var(--op-muted,#6F7D76)">{safe_text}</text>'
        "</svg>"
    )


def _validate_metric(metric: Any) -> str:
    metric_value = str(metric or "").strip()
    return metric_value if metric_value in ALLOWED_METRICS else "dobycha_nefti"


def _infer_metric(text: str) -> str:
    aliases = [
        ("dobycha_liq", ["жидк", "добыча жидкости"]),
        ("zakachka", ["закач", "вод"]),
        ("wc", ["обвод", "водо"]),
        ("debit_neft", ["дебит неф"]),
        ("debit_liq", ["дебит жид"]),
        ("dob_fond", ["добывающий фонд", "доб фонд"]),
        ("nagn_fond", ["нагнет", "нагн фонд"]),
        ("kin", ["кин"]),
        ("kiz", ["киз"]),
        ("dobycha_nefti", ["нефт", "добыч"]),
    ]
    for metric, words in aliases:
        if any(word in text for word in words):
            return metric
    return "dobycha_nefti"


def _selected_values(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if item not in (None, "", "ALL")]
    if isinstance(value, str) and value.strip() in {"", "ALL"}:
        return []
    return [value]


def _filter_notes(filters: Any) -> list[str]:
    filter_dict = filters if isinstance(filters, dict) else {}
    notes = []
    for key, label in [("ngdu", "НГДУ"), ("areas", "Площади"), ("plosh", "Площади"), ("direction", "Направление")]:
        values = _selected_values(filter_dict.get(key))
        if values:
            notes.append(f"{label}: {', '.join(map(str, values[:8]))}")
    return notes


def _clean_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: _json_scalar(value) for key, value in row.items()} for row in rows]


def _json_scalar(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def _to_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _fmt_number(value: Any) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "нет данных"
    if abs(numeric) >= 1_000_000:
        return f"{numeric / 1_000_000:.1f} млн"
    if abs(numeric) >= 1_000:
        return f"{numeric / 1_000:.1f} тыс."
    return f"{numeric:.1f}"
