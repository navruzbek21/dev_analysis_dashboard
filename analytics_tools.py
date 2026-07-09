from __future__ import annotations

import html
import math
import re
from functools import lru_cache
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

import gtm_analysis
from config import settings
from filter_utils import normalize_filter_values
from normalization import ALL_BLOCK_VALUE, AREA_COL_MONTH, AREA_COL_YEAR, BLOCK_COL, MEST_COL, safe_div
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
ALLOWED_TOOLS = {"metric_dynamics", "metric_change", "gtm_structure", "gtm_efficiency", "dataset_overview", "table_analysis"}
TABLE_ANALYSIS_AGGS = {"sum", "mean", "median", "min", "max", "count", "nunique"}
TABLE_ANALYSIS_TABLES = {"monthly_raw", "yearly_raw", "yearly", "gtm_level", "result_df", "factor_analysis_df"}


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
                "params": {"metric": list(ALLOWED_METRICS), "filters": {"mest": [], "ngdu": [], "areas": [], "block": None}},
            },
            "metric_change": {
                "description": "Изменение выбранной метрики к предыдущему году, 3 или 5 годам.",
                "params": {"metric": list(ALLOWED_METRICS), "period": list(CHANGE_PERIODS), "filters": {"mest": [], "ngdu": [], "areas": [], "block": None}},
            },
            "gtm_structure": {
                "description": "Структура добычи и дополнительной добычи по направлениям ГТМ.",
                "params": {"hist_type": ["traditional", "cumulative"], "filters": {"mest": [], "areas": [], "block": None}},
            },
            "gtm_efficiency": {
                "description": "Эффективность ГТМ: количество операций, доля эффективных, средние приросты.",
                "params": {"filters": {"mest": [], "ngdu": [], "direction": None, "areas": [], "block": None}},
            },
            "dataset_overview": {
                "description": "Обзор доступных исходных parquet-таблиц и количества строк в текущем/полном срезе.",
                "params": {"filters": {"mest": [], "ngdu": [], "areas": [], "block": None}},
            },
            "table_analysis": {
                "description": "Произвольный безопасный анализ исходных/агрегированных таблиц: фильтры, группировки, агрегации, сортировка, лимит.",
                "tables": sorted(TABLE_ANALYSIS_TABLES),
                "aggregations": sorted(TABLE_ANALYSIS_AGGS),
                "params": {
                    "table": "yearly",
                    "filters": {"mest": [], "ngdu": [], "areas": [], "block": None},
                    "where": {"column_name": ["value"]},
                    "group_by": ["year"],
                    "metrics": [{"column": "dobycha_nefti", "agg": "sum", "alias": "oil_sum"}],
                    "sort_by": "oil_sum",
                    "sort_desc": True,
                    "limit": 50,
                },
            },
        },
        "metrics": ALLOWED_METRICS,
    }


def make_plan_prompt(user_text: str, dashboard_filters: dict[str, Any] | None = None) -> str:
    schema = tools_schema()
    return (
        "Ты аналитический диспетчер дашборда разработки месторождения. "
        "Верни только JSON без markdown. Не пиши SQL. Выбери один инструмент из списка. "
        "Если пользователь просит график/гистограмму/динамику, выбирай подходящий chart tool.\n"
        f"Доступные инструменты и метрики:\n{schema}\n\n"
        f"Текущие фильтры дашборда (используй их, если пользователь ссылается на текущий срез): {dashboard_filters or {}}\n"
        f"Доступные таблицы и колонки для table_analysis:\n{table_schema_summary()}\n"
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
    if any(word in text for word in ["сгрупп", "топ", "top", "сумм", "средн", "максим", "миним", "разрез", "по год", "по нгду", "по площад"]):
        return {"tool": "table_analysis", "params": {"table": "yearly", "filters": {}, "group_by": ["year"], "metrics": [{"column": metric, "agg": "sum"}], "limit": 50}, "explain": True}
    if any(word in text for word in ["таблиц", "исходн", "данные", "датасет"]):
        return {"tool": "dataset_overview", "params": {"filters": {}}, "explain": True}
    return {"tool": "metric_dynamics", "params": {"metric": metric, "filters": {}}, "explain": True}


def make_analysis_plan(user_text: str, dashboard_filters: dict[str, Any] | None = None, llm_plan: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    text = (user_text or "").lower()
    source = "rules"
    if isinstance(llm_plan, dict) and str(llm_plan.get("tool") or "") in ALLOWED_TOOLS:
        plan = {"tool": llm_plan.get("tool"), "params": dict(llm_plan.get("params") if isinstance(llm_plan.get("params"), dict) else {}), "explain": True}
        source = "litellm"
    else:
        plan = _rule_based_plan(text)

    params = plan.get("params") if isinstance(plan.get("params"), dict) else {}
    params = dict(params)
    params["filters"] = _analysis_filters(user_text, dashboard_filters, params.get("filters"))
    plan["params"] = params
    return _normalize_plan(plan), source


def _rule_based_plan(text: str) -> dict[str, Any]:
    metric = _infer_metric(text)
    if any(word in text for word in ["гтм", "грп", "гидроразрыв", "операц", "эффект", "успеш", "прирост"]):
        if any(word in text for word in ["структур", "доп", "дополнитель", "гист", "stack", "стек"]):
            hist_type = "cumulative" if any(word in text for word in ["кумуля", "накоп"]) else "traditional"
            return {"tool": "gtm_structure", "params": {"hist_type": hist_type}, "explain": True}
        return {"tool": "gtm_efficiency", "params": {}, "explain": True}
    if any(word in text for word in ["сгрупп", "топ", "top", "сумм", "средн", "максим", "миним", "разрез", "по год", "по нгду", "по площад"]):
        return {"tool": "table_analysis", "params": {"table": "yearly", "group_by": ["year"], "metrics": [{"column": metric, "agg": "sum"}], "limit": 50}, "explain": True}
    if any(word in text for word in ["таблиц", "исходн", "датасет"]):
        return {"tool": "dataset_overview", "params": {}, "explain": True}
    if any(word in text for word in ["измен", "сравн", "прошл", "прирост", "паден", "сниз", "рост"]):
        period = "5y" if "5" in text else ("3y" if "3" in text else "prev")
        return {"tool": "metric_change", "params": {"metric": metric, "period": period}, "explain": True}
    return {"tool": "metric_dynamics", "params": {"metric": metric}, "explain": True}


def _analysis_filters(user_text: str, dashboard_filters: dict[str, Any] | None, initial_filters: Any = None) -> dict[str, Any]:
    filters = dict(initial_filters) if isinstance(initial_filters, dict) else {}
    context = dashboard_filters if isinstance(dashboard_filters, dict) else {}
    explicit_ngdu = _infer_ngdu_values(user_text)
    explicit_areas = _infer_area_values(user_text, {**context, **filters})
    explicit_directions = _infer_direction_values(user_text)

    if explicit_areas:
        filters = {key: value for key, value in filters.items() if key in {"where"}}
        filters["areas"] = explicit_areas
        if explicit_ngdu:
            filters["ngdu"] = explicit_ngdu
    elif explicit_ngdu:
        filters["ngdu"] = explicit_ngdu
        if _selected_values(context.get("mest")):
            filters["mest"] = context.get("mest")
    else:
        for key in ["mest", "ngdu", "areas", "block"]:
            if not _selected_values(filters.get(key)) and _selected_values(context.get(key)):
                filters[key] = context.get(key)

    if explicit_directions:
        filters["direction"] = explicit_directions[0] if len(explicit_directions) == 1 else explicit_directions
    elif _selected_values(context.get("direction")) and not _selected_values(filters.get("direction")):
        filters["direction"] = context.get("direction")
    return {key: value for key, value in filters.items() if _selected_values(value)}


def _normalize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    tool = str(plan.get("tool") or "metric_dynamics")
    if tool not in ALLOWED_TOOLS:
        tool = "metric_dynamics"
    params = plan.get("params") if isinstance(plan.get("params"), dict) else {}
    params = dict(params)
    if tool in {"metric_dynamics", "metric_change"}:
        params["metric"] = _validate_metric(params.get("metric"))
    if tool == "metric_change" and params.get("period") not in CHANGE_PERIODS:
        params["period"] = "prev"
    return {"tool": tool, "params": params, "explain": bool(plan.get("explain", True))}


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
    if tool == "dataset_overview":
        return dataset_overview(params)
    if tool == "table_analysis":
        return table_analysis(params)
    raise ValueError(f"Инструмент не реализован: {tool}")


def make_explanation_prompt(user_text: str, plan: dict[str, Any], result: ToolResult) -> str:
    rows_preview = result.rows[:30]
    return (
        "Ты аналитик нефтяного дашборда. Дай короткий вывод на русском языке. "
        "Опирайся только на агрегированные данные ниже. Обязательно укажи конкретные числа/годы из строк или сводки. "
        "Если строк нет или source_rows=0, прямо напиши, что в выбранном срезе нет строк, и не делай содержательный вывод. "
        "Не пиши общие фразы вроде «не была отражена в агрегированных данных» без указания фильтров и количества строк. "
        "Не выдумывай причин, если они не следуют из данных. "
        "Структура: 2-4 предложения, затем 1-3 пункта что проверить дальше.\n\n"
        f"Запрос пользователя: {user_text}\n"
        f"План: {plan}\n"
        f"Заголовок результата: {result.title}\n"
        f"Сводка: {result.summary}\n"
        f"Строки: {rows_preview}"
    )


def requires_deterministic_explanation(result: ToolResult) -> bool:
    if not result.rows:
        return True
    source_rows = result.summary.get("source_rows") if isinstance(result.summary, dict) else None
    return source_rows == 0


def fallback_explanation(user_text: str, result: ToolResult) -> str:
    summary = result.summary
    if result.tool in {"metric_dynamics", "metric_change"}:
        label = summary.get("metric_label", "Показатель")
        current = summary.get("last_value")
        change = summary.get("last_change_pct")
        if not result.rows:
            filters = "; ".join(result.notes or []) or "без фильтров"
            return f"В выбранном срезе ({filters}) нет строк для расчета показателя «{label}». Проверьте выбранную площадь/НГДУ/месторождение и наличие данных за нужный период."
        if change is None or not np.isfinite(change):
            return f"Построил агрегированный срез по показателю «{label}»: последнее значение {_fmt_number(current)} за {summary.get('last_year') or 'последний доступный год'}. Недостаточно базы сравнения для корректного процента изменения."
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
    if result.tool == "table_analysis":
        if not result.rows or summary.get("source_rows") == 0:
            filters = "; ".join(result.notes or []) or "без фильтров"
            return (
                f"В выбранном срезе ({filters}) табличный анализ не нашел строк: "
                f"получено {summary.get('row_count', 0)} строк из {summary.get('source_rows', 0)} строк источника. "
                "Проверьте точное название площади/НГДУ и доступность данных за нужный период."
            )
        return (
            f"Выполнил табличный анализ: получено {summary.get('row_count', 0)} строк из {summary.get('source_rows', 0)} строк источника. "
            f"Таблица: {summary.get('table')}; группировка: {summary.get('group_by') or 'без группировки'}."
        )
    if result.tool == "gtm_efficiency":
        if not result.rows or summary.get("gtm_count", 0) == 0:
            filters = "; ".join(result.notes or []) or "без фильтров"
            return f"В выбранном срезе ({filters}) нет строк ГТМ для расчета эффективности. Проверьте направление, площадь/НГДУ и наличие ГТМ в источнике."
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


def has_selected_dashboard_filters(dashboard_filters: dict[str, Any] | None) -> bool:
    if not isinstance(dashboard_filters, dict):
        return False
    return any(_selected_values(dashboard_filters.get(key)) for key in ["mest", "ngdu", "areas", "block"])


def with_note(result: ToolResult, note: str) -> ToolResult:
    notes = list(result.notes or [])
    if note not in notes:
        notes.append(note)
    return ToolResult(
        tool=result.tool,
        title=result.title,
        chart_type=result.chart_type,
        rows=result.rows,
        columns=result.columns,
        summary={**result.summary, "dashboard_filter_recovery": True},
        chart=result.chart,
        notes=notes,
    )


def apply_dashboard_context(plan: dict[str, Any], user_text: str, dashboard_filters: dict[str, Any] | None = None) -> dict[str, Any]:
    out = dict(plan or {})
    params = out.get("params") if isinstance(out.get("params"), dict) else {}
    params = dict(params)
    filters = params.get("filters") if isinstance(params.get("filters"), dict) else {}
    filters = dict(filters)
    context = dashboard_filters if isinstance(dashboard_filters, dict) else {}

    for key in ["mest", "ngdu", "areas", "block"]:
        if not _selected_values(filters.get(key)) and _selected_values(context.get(key)):
            filters[key] = context.get(key)

    inferred_ngdu = _infer_ngdu_values(user_text)
    if inferred_ngdu:
        filters["ngdu"] = inferred_ngdu

    inferred_areas = _infer_area_values(user_text, filters)
    if inferred_areas:
        filters["areas"] = inferred_areas
        if not inferred_ngdu:
            filters.pop("ngdu", None)
            filters.pop("selected_ngdu", None)
        filters.pop("mest", None)
        filters.pop("selected_mest", None)
        filters.pop("block", None)

    inferred_directions = _infer_direction_values(user_text)
    if inferred_directions:
        filters["direction"] = inferred_directions[0] if len(inferred_directions) == 1 else inferred_directions

    params["filters"] = filters
    out["params"] = params
    return out


def _infer_ngdu_values(text: str) -> list[str]:
    matches = re.findall(r"н\s*г\s*д\s*у[^0-9A-Za-zА-Яа-я]*(\d+)", text or "", flags=re.I)
    if not matches:
        return []
    try:
        options = data_service.get_ngdu_options(())
    except Exception:
        return []
    found = []
    for number in matches:
        pattern = re.compile(rf"(?<!\d){re.escape(number)}(?!\d)")
        for option in options:
            if pattern.search(str(option)) and option not in found:
                found.append(option)
    return found


def _infer_area_values(text: str, filters: dict[str, Any]) -> list[str]:
    normalized_text = _normalize_match_text(text)
    if not normalized_text or not any(marker in normalized_text for marker in ["площад", "площ"]):
        return []
    found = _match_options_by_text(_area_options_for_filters(filters), normalized_text, {"площадь", "площади", "площад", "площ"})
    if found:
        return found[:20]
    unconstrained_filters = {**filters, "ngdu": [], "selected_ngdu": [], "mest": [], "selected_mest": []}
    return _match_options_by_text(_area_options_for_filters(unconstrained_filters), normalized_text, {"площадь", "площади", "площад", "площ"})[:20]


def _area_options_for_filters(filters: dict[str, Any]) -> list[Any]:
    options: list[Any] = []
    try:
        options.extend(
            data_service.get_area_options(
                _selected_values(filters.get("ngdu") or filters.get("selected_ngdu")),
                _selected_values(filters.get("mest") or filters.get("selected_mest")),
            )
        )
    except Exception:
        pass
    try:
        dataset = gtm_analysis.get_gtm_dataset()
        for frame_name in ["gtm_level", "result_df"]:
            frame = getattr(dataset, frame_name)
            if "plosh" in frame.columns:
                options.extend(frame["plosh"].dropna().unique().tolist())
    except Exception:
        pass
    deduped: list[Any] = []
    seen = set()
    for option in options:
        key = str(option)
        if key not in seen:
            seen.add(key)
            deduped.append(option)
    return deduped


def _infer_direction_values(text: str) -> list[str]:
    normalized_text = _normalize_match_text(text)
    if not normalized_text:
        return []
    try:
        dataset = gtm_analysis.get_gtm_dataset()
        options = dataset.result_df["направление"].dropna().unique().tolist() if "направление" in dataset.result_df.columns else []
    except Exception:
        options = []
    aliases = {"грп": "грп", "гидроразрыв": "грп", "гидроразрыва": "грп"}
    for source, target in aliases.items():
        if source in normalized_text:
            matched = _match_options_by_text(options, target, set())
            return matched or [target.upper()]
    return _match_options_by_text(options, normalized_text, set())[:5]


def _match_options_by_text(options: list[Any], normalized_text: str, stop_words: set[str]) -> list[Any]:
    scored: list[tuple[int, Any]] = []
    query_tokens = set(normalized_text.split())
    for option in options:
        option_text = _normalize_match_text(option)
        tokens = [token for token in option_text.split() if len(token) >= 3 and token not in stop_words]
        if not option_text or not tokens:
            continue
        score = 0
        if option_text in normalized_text:
            score = len(tokens) + 10
        elif all(token in query_tokens for token in tokens):
            score = len(tokens)
        if score:
            scored.append((score, option))
    if not scored:
        return []
    max_score = max(score for score, _option in scored)
    found: list[Any] = []
    for score, option in scored:
        if score == max_score and option not in found:
            found.append(option)
    return found


def _normalize_match_text(value: Any) -> str:
    text = str(value or "").lower().replace("ё", "е")
    text = re.sub(r"[^0-9a-zа-я]+", " ", text)
    words = []
    for word in text.split():
        for suffix in ["ской", "ской", "ская", "ское", "ский", "ская", "ую", "ой", "ая", "ое", "ые", "ий", "ый"]:
            if len(word) > len(suffix) + 3 and word.endswith(suffix):
                word = word[: -len(suffix)]
                break
        words.append(word)
    return " ".join(words)


def dataset_overview(params: dict[str, Any]) -> ToolResult:
    filters = params.get("filters") if isinstance(params.get("filters"), dict) else {}
    rows = []
    for table in sorted(TABLE_ANALYSIS_TABLES):
        full = _load_table_frame(table, {})
        filtered = _load_table_frame(table, filters)
        rows.append({"table": table, "rows_full": int(full.shape[0]), "rows_filtered": int(filtered.shape[0]), "columns": int(full.shape[1])})
    return ToolResult(
        tool="dataset_overview",
        title="Обзор доступных таблиц",
        chart_type="table",
        rows=_clean_rows(rows),
        columns=["table", "rows_full", "rows_filtered", "columns"],
        summary={"table_count": len(rows), "filtered_by": filters},
        chart=None,
        notes=_filter_notes(filters),
    )


@lru_cache(maxsize=1)
def table_schema_summary() -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for table in sorted(TABLE_ANALYSIS_TABLES):
        try:
            df = _load_table_frame(table, {})
            summary[table] = {"rows": int(df.shape[0]), "columns": list(map(str, df.columns[:40]))}
        except Exception as exc:
            summary[table] = {"error": str(exc)}
    return summary


def table_analysis(params: dict[str, Any]) -> ToolResult:
    table = str(params.get("table") or "yearly").strip()
    if table not in TABLE_ANALYSIS_TABLES:
        table = "yearly"
    filters = params.get("filters") if isinstance(params.get("filters"), dict) else {}
    df = _load_table_frame(table, filters)
    df = _apply_where_filters(df, params.get("where"))
    source_rows = int(df.shape[0])
    group_by = _valid_columns(df, params.get("group_by"), max_count=5)
    metrics = _normalize_table_metrics(df, params.get("metrics"))

    if group_by and metrics:
        work_df = df.copy()
        for metric in metrics:
            if metric["agg"] not in {"count", "nunique"}:
                work_df[metric["column"]] = pd.to_numeric(work_df[metric["column"]], errors="coerce")
        named_aggs = {metric["alias"]: (metric["column"], metric["agg"]) for metric in metrics}
        result_df = work_df.groupby(group_by, dropna=False).agg(**named_aggs).reset_index()
    elif metrics:
        values = {}
        for metric in metrics:
            series = df[metric["column"]]
            values[metric["alias"]] = _aggregate_series(series, metric["agg"])
        result_df = pd.DataFrame([values])
    else:
        display_cols = _valid_columns(df, params.get("columns"), max_count=20) or list(df.columns[:20])
        result_df = df[display_cols].copy()

    sort_by = str(params.get("sort_by") or "").strip()
    if sort_by in result_df.columns:
        result_df = result_df.sort_values(sort_by, ascending=not bool(params.get("sort_desc", True)), na_position="last")
    limit = _safe_limit(params.get("limit"), default=50, maximum=200)
    result_df = result_df.head(limit).replace({np.nan: None})
    rows = _clean_rows(result_df.to_dict("records"))
    columns = list(map(str, result_df.columns))
    return ToolResult(
        tool="table_analysis",
        title=f"Табличный анализ: {table}",
        chart_type="table",
        rows=rows,
        columns=columns,
        summary={
            "table": table,
            "source_rows": source_rows,
            "row_count": len(rows),
            "group_by": group_by,
            "metrics": metrics,
            "sort_by": sort_by or None,
            "limit": limit,
        },
        chart=None,
        notes=_filter_notes(filters),
    )


def _load_table_frame(table: str, filters: dict[str, Any]) -> pd.DataFrame:
    if table == "monthly_raw":
        return _apply_common_filters(pd.read_parquet(settings.parquet_monthly_path), filters, area_col=AREA_COL_MONTH)
    if table == "yearly_raw":
        return _apply_common_filters(pd.read_parquet(settings.parquet_yearly_path), filters, area_col=AREA_COL_YEAR)
    if table == "yearly":
        return _filtered_year_data(filters)
    dataset = gtm_analysis.get_gtm_dataset()
    if table == "gtm_level":
        return _filtered_gtm(filters)
    frame = getattr(dataset, table)
    return _apply_common_filters(frame.copy(), filters, area_col="plosh" if "plosh" in frame.columns else AREA_COL_YEAR)


def _apply_common_filters(df: pd.DataFrame, filters: dict[str, Any], area_col: str) -> pd.DataFrame:
    out = df.copy()
    mest = normalize_filter_values(filters.get("mest") or filters.get("selected_mest") or ())
    ngdu = normalize_filter_values(filters.get("ngdu") or filters.get("selected_ngdu") or ())
    areas = normalize_filter_values(filters.get("areas") or filters.get("plosh") or filters.get("selected_areas") or ())
    blocks = normalize_filter_values(filters.get("block") or filters.get("blocks") or filters.get("selected_blocks") or ())
    if mest and MEST_COL in out.columns:
        out = out[out[MEST_COL].isin(mest)]
    if ngdu and "ngdu" in out.columns:
        out = out[out["ngdu"].isin(ngdu)]
    if areas and area_col in out.columns:
        out = out[out[area_col].isin(areas)]
    if blocks and BLOCK_COL in out.columns and ALL_BLOCK_VALUE not in blocks:
        out = out[out[BLOCK_COL].astype(str).str.strip().isin([str(value).strip() for value in blocks])]
    return out.reset_index(drop=True)


def _apply_where_filters(df: pd.DataFrame, where: Any) -> pd.DataFrame:
    if not isinstance(where, dict):
        return df
    out = df
    for column, raw_values in where.items():
        if column not in out.columns:
            continue
        values = _selected_values(raw_values)
        if values:
            out = out[out[column].isin(values)]
    return out


def _valid_columns(df: pd.DataFrame, columns: Any, max_count: int) -> list[str]:
    values = _selected_values(columns)
    valid = []
    for value in values:
        column = str(value)
        if column in df.columns and column not in valid:
            valid.append(column)
        if len(valid) >= max_count:
            break
    return valid


def _normalize_table_metrics(df: pd.DataFrame, metrics: Any) -> list[dict[str, str]]:
    normalized = []
    if not isinstance(metrics, list):
        return normalized
    for item in metrics[:8]:
        if not isinstance(item, dict):
            continue
        column = str(item.get("column") or "").strip()
        agg = str(item.get("agg") or "sum").strip().lower()
        if column not in df.columns or agg not in TABLE_ANALYSIS_AGGS:
            continue
        alias = str(item.get("alias") or f"{column}_{agg}").strip()
        alias = re.sub(r"[^0-9A-Za-zА-Яа-я_]+", "_", alias)[:64] or f"{column}_{agg}"
        normalized.append({"column": column, "agg": agg, "alias": alias})
    return normalized


def _aggregate_series(series: pd.Series, agg: str) -> Any:
    if agg == "count":
        return int(series.count())
    if agg == "nunique":
        return int(series.nunique(dropna=True))
    numeric = pd.to_numeric(series, errors="coerce")
    if agg == "sum":
        return numeric.sum(skipna=True)
    if agg == "mean":
        return numeric.mean(skipna=True)
    if agg == "median":
        return numeric.median(skipna=True)
    if agg == "min":
        return numeric.min(skipna=True)
    if agg == "max":
        return numeric.max(skipna=True)
    return None


def _safe_limit(value: Any, default: int, maximum: int) -> int:
    try:
        limit = int(value)
    except Exception:
        limit = default
    return max(1, min(limit, maximum))


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
    ngdu = _selected_values(filters.get("ngdu") or filters.get("selected_ngdu"))
    if ngdu and not areas:
        areas = data_service.get_area_options(ngdu, mest)
    block = filters.get("block") or filters.get("selected_blocks") or ALL_BLOCK_VALUE
    dataset = gtm_analysis.get_gtm_dataset()
    data = gtm_analysis.prepare_hist_data(areas or gtm_analysis.ALL, hist_type, dataset, mest or gtm_analysis.ALL, block)
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
    direction = filters.get("direction") or gtm_analysis.ALL
    areas = _selected_values(filters.get("areas") or filters.get("plosh"))
    mest = _selected_values(filters.get("mest") or filters.get("selected_mest"))
    gtm = _filtered_gtm(filters, direction=direction, areas=areas, mest=mest)
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


def _filtered_gtm(filters: dict[str, Any], direction: Any = None, areas: list[Any] | None = None, mest: list[Any] | None = None) -> pd.DataFrame:
    dataset = gtm_analysis.get_gtm_dataset()
    direction_value = direction if direction is not None else (filters.get("direction") or gtm_analysis.ALL)
    mest_values = mest if mest is not None else _selected_values(filters.get("mest") or filters.get("selected_mest"))
    area_values = areas if areas is not None else _selected_values(filters.get("areas") or filters.get("plosh"))
    ngdu_values = _selected_values(filters.get("ngdu") or filters.get("selected_ngdu"))
    block = filters.get("block") or filters.get("selected_blocks") or ALL_BLOCK_VALUE
    if ngdu_values and not area_values:
        area_values = data_service.get_area_options(ngdu_values, mest_values)
    return gtm_analysis.filter_df(dataset.gtm_level, direction_value, area_values or gtm_analysis.ALL, mest_values or gtm_analysis.ALL, block)


def _filtered_year_data(filters: Any) -> pd.DataFrame:
    filter_dict = filters if isinstance(filters, dict) else {}
    ngdu = normalize_filter_values(filter_dict.get("ngdu") or filter_dict.get("selected_ngdu") or ())
    areas = normalize_filter_values(filter_dict.get("areas") or filter_dict.get("plosh") or filter_dict.get("selected_areas") or ())
    mest = normalize_filter_values(filter_dict.get("mest") or filter_dict.get("selected_mest") or ())
    blocks = normalize_filter_values(filter_dict.get("block") or filter_dict.get("blocks") or filter_dict.get("selected_blocks") or ())
    return data_service.get_filtered_year_data(ngdu, areas, mest, blocks)


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
    for key, label in [("ngdu", "НГДУ"), ("areas", "Площади"), ("plosh", "Площади"), ("block", "Блок"), ("direction", "Направление")]:
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
