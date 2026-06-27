import argparse
import json

import numpy as np
import pandas as pd

from normalization import AREA_COL_YEAR, normalize_data
from repositories import metrics_repository


COMPARE_COLUMNS = [
    "dobycha_nefti",
    "dobycha_liq",
    "dobycha_vody",
    "zakachka",
    "wc",
    "debit_neft",
    "debit_liq",
    "debit_vod",
    "priem",
    "dob_fond",
    "nagn_fond",
    "kin",
    "kiz",
    "vnf_tek",
    "vnf_nak",
    "ratio_dob_nagn",
    "q_priem_q_liq",
]


def compare(monthly, yearly, dataset_version, selected_ngdu=(), selected_areas=()):
    df2 = pd.read_parquet(monthly)
    dfy = pd.read_parquet(yearly)
    _, parquet_year = normalize_data(df2, dfy)
    if selected_ngdu:
        parquet_year = parquet_year[parquet_year["ngdu"].isin(selected_ngdu)]
    if selected_areas:
        parquet_year = parquet_year[parquet_year[AREA_COL_YEAR].isin(selected_areas)]

    sql_year = metrics_repository.load_year_metrics(tuple(selected_ngdu), tuple(selected_areas), dataset_version)
    report = {
        "row_count_parquet": int(len(parquet_year)),
        "row_count_sql": int(len(sql_year)),
        "year_min_parquet": int(parquet_year["year"].min()) if not parquet_year.empty else None,
        "year_max_parquet": int(parquet_year["year"].max()) if not parquet_year.empty else None,
        "year_min_sql": int(sql_year["year"].min()) if not sql_year.empty else None,
        "year_max_sql": int(sql_year["year"].max()) if not sql_year.empty else None,
        "columns": {},
    }
    parquet_sorted = parquet_year.sort_values([AREA_COL_YEAR, "year"]).reset_index(drop=True)
    sql_sorted = sql_year.sort_values([AREA_COL_YEAR, "year"]).reset_index(drop=True)
    for column in COMPARE_COLUMNS:
        if column not in parquet_sorted.columns or column not in sql_sorted.columns:
            report["columns"][column] = "missing"
            continue
        if len(parquet_sorted) != len(sql_sorted):
            report["columns"][column] = False
            continue
        ok = np.allclose(
            pd.to_numeric(parquet_sorted[column], errors="coerce"),
            pd.to_numeric(sql_sorted[column], errors="coerce"),
            rtol=1e-9,
            atol=1e-9,
            equal_nan=True,
        )
        report["columns"][column] = bool(ok)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description="Compare normalized parquet metrics with SQL metrics.")
    parser.add_argument("--monthly", default="df2.parquet")
    parser.add_argument("--yearly", default="df_ploshad_year.parquet")
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--ngdu", action="append", default=[])
    parser.add_argument("--area", action="append", default=[])
    args = parser.parse_args()
    compare(args.monthly, args.yearly, args.dataset_version, tuple(args.ngdu), tuple(args.area))


if __name__ == "__main__":
    main()
