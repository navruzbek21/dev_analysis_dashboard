from __future__ import annotations

import numpy as np
import pandas as pd

from normalization import AREA_COL_YEAR
from services import data_service

KEY_COLUMNS = ["kod_ploshchadi", "year", "dobycha_nefti", "dobycha_liq", "zakachka", "wc"]
RANGE_0_100 = ["wc", "wc_month_avg", "kin", "kiz", "niz_otbor"]
NON_NEGATIVE = [
    "dobycha_nefti", "dobycha_liq", "dobycha_vody", "zakachka", "dob_fond", "nagn_fond",
    "debit_neft", "debit_liq", "priemistost", "dobycha_nefti_cum", "dobycha_liq_cum",
    "dobycha_vody_cum", "dobycha_nefti_cum_m3", "dobycha_liq_cum_m3", "dobycha_vody_cum_m3",
    "niz", "gz",
]
CUMULATIVE_COLUMNS = [
    "dobycha_nefti_cum", "dobycha_liq_cum", "dobycha_vody_cum",
    "dobycha_nefti_cum_m3", "dobycha_liq_cum_m3", "dobycha_vody_cum_m3",
]


def _issue(severity: str, check: str, message: str, count: int | None = None) -> dict:
    return {"severity": severity, "check": check, "message": message, "count": int(count or 0)}


def get_quality_report(selected_ngdu=(), selected_areas=(), selected_mest=()) -> dict:
    df = data_service.get_filtered_year_data(selected_ngdu, selected_areas, selected_mest)
    issues: list[dict] = []
    if df.empty:
        return {"summary": {"status": "Нет данных", "rows": 0, "areas": 0, "period": "—"}, "issues": [], "null_rates": []}

    area_col = "kod_ploshchadi" if "kod_ploshchadi" in df.columns else (AREA_COL_YEAR if AREA_COL_YEAR in df.columns else None)
    missing = [c for c in KEY_COLUMNS if c not in df.columns]
    if missing:
        issues.append(_issue("high", "missing_columns", f"Нет важных колонок: {', '.join(missing)}", len(missing)))

    null_rates = []
    for col in [c for c in KEY_COLUMNS if c in df.columns]:
        rate = float(df[col].isna().mean() * 100)
        null_rates.append({"column": col, "null_rate_pct": round(rate, 2), "null_count": int(df[col].isna().sum())})
        if rate > 0:
            issues.append(_issue("medium", "null_rate", f"В колонке {col} есть пропуски: {rate:.1f}%", int(df[col].isna().sum())))

    if area_col and "year" in df.columns:
        dup_count = int(df.duplicated([area_col, "year"], keep=False).sum())
        if dup_count:
            issues.append(_issue("high", "duplicate_area_year", f"Дубли на зерне {area_col}+year", dup_count))

    for col in [c for c in RANGE_0_100 if c in df.columns]:
        v = pd.to_numeric(df[col], errors="coerce")
        bad = v.notna() & ~v.between(0, 100)
        if bad.any():
            issues.append(_issue("high", "range_0_100", f"{col} вне диапазона 0..100", int(bad.sum())))

    for col in [c for c in NON_NEGATIVE if c in df.columns]:
        v = pd.to_numeric(df[col], errors="coerce")
        bad = v.notna() & v.lt(0)
        if bad.any():
            issues.append(_issue("high", "non_negative", f"{col} содержит отрицательные значения", int(bad.sum())))

    if area_col and "year" in df.columns:
        ordered = df.sort_values([area_col, "year"])
        for col in [c for c in CUMULATIVE_COLUMNS if c in ordered.columns]:
            vals = pd.to_numeric(ordered[col], errors="coerce")
            diffs = vals.groupby(ordered[area_col]).diff()
            bad = diffs.notna() & diffs.lt(-1e-9)
            if bad.any():
                issues.append(_issue("high", "cumulative_monotonic", f"{col} убывает внутри площади", int(bad.sum())))

    if {"dobycha_liq", "dobycha_nefti", "dobycha_vody"}.issubset(df.columns):
        liq = pd.to_numeric(df["dobycha_liq"], errors="coerce")
        oil = pd.to_numeric(df["dobycha_nefti"], errors="coerce")
        water = pd.to_numeric(df["dobycha_vody"], errors="coerce")
        denom = liq.abs().replace(0, np.nan)
        bad = ((liq - oil - water).abs() / denom).gt(0.05).fillna(False)
        if bad.any():
            issues.append(_issue("medium", "liquid_balance", "Баланс жидкости отличается более чем на 5%", int(bad.sum())))

    status = "Требует исправления" if any(i["severity"] == "high" for i in issues) else ("Есть замечания" if issues else "OK")
    years = pd.to_numeric(df["year"], errors="coerce") if "year" in df.columns else pd.Series(dtype=float)
    period = "—" if years.dropna().empty else f"{int(years.min())}–{int(years.max())}"
    summary = {"status": status, "rows": int(len(df)), "areas": int(df[area_col].nunique()) if area_col else 0, "period": period}
    return {"summary": summary, "issues": issues, "null_rates": null_rates}
