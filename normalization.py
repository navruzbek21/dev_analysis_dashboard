import numpy as np
import pandas as pd


AREA_COL_YEAR = "kod_ploshchadi"
AREA_COL_MONTH = "kod_ploshchadi"
MEST_COL = "mest"
BLOCK_COL = "block"
ALL_BLOCK_VALUE = "__ALL_BLOCK__"
INCLUDE_BLOCK_ROWS_VALUE = "__INCLUDE_BLOCK_ROWS__"


def safe_div(a, b):
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    return np.where((b == 0) | b.isna(), np.nan, a / b)


def validate_area_ngdu_uniqueness(df2, area_col_month=AREA_COL_MONTH):
    area_ngdu = df2[[area_col_month, "ngdu"]].dropna().drop_duplicates()
    conflicts = (
        area_ngdu.groupby(area_col_month)["ngdu"]
        .nunique()
        .reset_index(name="ngdu_count")
        .query("ngdu_count > 1")
    )
    return conflicts


def normalize_data(df2, dfy, area_col_month=AREA_COL_MONTH, area_col_year=AREA_COL_YEAR):
    df2 = df2.copy().replace([np.inf, -np.inf], np.nan)
    dfy = dfy.copy().replace([np.inf, -np.inf], np.nan)

    df2["date"] = pd.to_datetime(df2["date"], errors="coerce")
    if "year" not in df2.columns:
        df2["year"] = df2["date"].dt.year
    df2["year"] = pd.to_numeric(df2["year"], errors="coerce").astype("Int64")
    dfy["year"] = pd.to_numeric(dfy["year"], errors="coerce").astype("Int64")

    for col in ["dob_fond", "nagn_fond", "kin", "niz_otbor", "niz_temp", "kompens_tek", "kompens_nak", "gz", "niz"]:
        if col not in dfy.columns:
            dfy[col] = np.nan

    area_ngdu = (
        df2[[area_col_month, "ngdu"]]
        .dropna()
        .drop_duplicates()
        .rename(columns={area_col_month: area_col_year})
    )
    area_ngdu = area_ngdu.groupby(area_col_year, as_index=False)["ngdu"].first()
    dfy = dfy.merge(area_ngdu, on=area_col_year, how="left")

    if MEST_COL not in dfy.columns and MEST_COL in df2.columns:
        area_mest = (
            df2[[area_col_month, MEST_COL]]
            .dropna()
            .drop_duplicates()
            .rename(columns={area_col_month: area_col_year})
        )
        area_mest = area_mest.groupby(area_col_year, as_index=False)[MEST_COL].first()
        dfy = dfy.merge(area_mest, on=area_col_year, how="left")

    if BLOCK_COL not in dfy.columns:
        dfy[BLOCK_COL] = "all"

    agg_kwargs = {}
    has_debit_pair = {"debit_neft", "debit_liq"}.issubset(df2.columns)
    for col in ["debit_neft", "debit_liq", "debit_vod", "priem", "wc"]:
        if col not in df2.columns:
            continue
        if has_debit_pair and col in {"debit_neft", "debit_liq"}:
            continue
        agg_kwargs[col if col != "wc" else "wc_month_avg"] = (col, "mean")

    yearly_parts = []
    if agg_kwargs:
        yearly_parts.append(
            df2.groupby([area_col_month, "year"], as_index=False)
            .agg(**agg_kwargs)
            .rename(columns={area_col_month: area_col_year})
        )

    if has_debit_pair:
        debit_pair_year = (
            df2.dropna(subset=["debit_neft", "debit_liq"])
            .groupby([area_col_month, "year"], as_index=False)
            .agg(debit_neft=("debit_neft", "mean"), debit_liq=("debit_liq", "mean"))
            .rename(columns={area_col_month: area_col_year})
        )
        yearly_parts.append(debit_pair_year)

    if yearly_parts:
        wells_year = yearly_parts[0]
        for part in yearly_parts[1:]:
            wells_year = wells_year.merge(part, on=[area_col_year, "year"], how="outer")
        dfy = dfy.merge(wells_year, on=[area_col_year, "year"], how="left")

    dfy = dfy.sort_values([area_col_year, "year"])
    if "dobycha_vody_cum" not in dfy.columns and "dobycha_vody" in dfy.columns:
        dfy["dobycha_vody_cum"] = dfy.groupby(area_col_year)["dobycha_vody"].cumsum()
    if "dobycha_nefti_cum" not in dfy.columns and "dobycha_nefti" in dfy.columns:
        dfy["dobycha_nefti_cum"] = dfy.groupby(area_col_year)["dobycha_nefti"].cumsum()
    if "dobycha_liq_cum" not in dfy.columns and "dobycha_liq" in dfy.columns:
        dfy["dobycha_liq_cum"] = dfy.groupby(area_col_year)["dobycha_liq"].cumsum()
    if "zakachka_cum" not in dfy.columns and "zakachka" in dfy.columns:
        dfy["zakachka_cum"] = dfy.groupby(area_col_year)["zakachka"].cumsum()

    dfy["kiz"] = dfy.get("niz_otbor", np.nan)
    dfy["vnf_tek"] = safe_div(dfy.get("dobycha_vody", np.nan), dfy.get("dobycha_nefti", np.nan))
    dfy["vnf_nak"] = safe_div(dfy.get("dobycha_vody_cum", np.nan), dfy.get("dobycha_nefti_cum", np.nan))
    dfy["ratio_dob_nagn"] = safe_div(dfy.get("dob_fond", np.nan), dfy.get("nagn_fond", np.nan))
    dfy["q_priem_q_liq"] = safe_div(dfy.get("priem", np.nan), dfy.get("debit_liq", np.nan))
    dfy["stepen_prokachki"] = 100 * safe_div(dfy.get("zakachka_cum", np.nan), dfy.get("gz", np.nan))
    dfy["stepen_promyvki"] = 100 * safe_div(dfy.get("dobycha_liq_cum", np.nan), dfy.get("gz", np.nan))
    dfy["temp_prokachki"] = 100 * safe_div(dfy.get("zakachka", np.nan), dfy.get("gz", np.nan))
    dfy["temp_promyvki"] = 100 * safe_div(dfy.get("dobycha_liq", np.nan), dfy.get("gz", np.nan))

    return df2, dfy
