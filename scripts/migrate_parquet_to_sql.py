import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, insert

from config import settings
from db import engine
from normalization import AREA_COL_MONTH, AREA_COL_YEAR, MEST_COL, normalize_data, validate_area_ngdu_uniqueness
from repositories.metrics_repository import area_year_metrics, dashboard_metadata, dim_area, monthly_metrics


MONTHLY_COLUMNS = [
    "date",
    "year",
    "ngdu",
    "mest",
    "ploshad",
    "well_uid",
    "debit_neft",
    "debit_liq",
    "debit_vod",
    "priem",
    "wc",
    "dataset_version",
    "loaded_at",
    "source_file",
]

YEAR_COLUMNS = [
    "ngdu",
    "mest",
    "kod_ploshchadi",
    "year",
    "dobycha_nefti",
    "dobycha_liq",
    "dobycha_vody",
    "dobycha_nefti_m3",
    "dobycha_liq_m3",
    "dobycha_vody_m3",
    "zakachka",
    "wc",
    "dob_fond",
    "nagn_fond",
    "kin",
    "niz_otbor",
    "niz_temp",
    "kompens_tek",
    "kompens_nak",
    "gz",
    "niz",
    "wc_month_avg",
    "debit_neft",
    "debit_liq",
    "debit_vod",
    "priem",
    "dobycha_vody_cum",
    "dobycha_nefti_cum",
    "dobycha_liq_cum",
    "dobycha_nefti_cum_m3",
    "dobycha_liq_cum_m3",
    "dobycha_vody_cum_m3",
    "zakachka_cum",
    "kiz",
    "vnf_tek",
    "vnf_nak",
    "ratio_dob_nagn",
    "q_priem_q_liq",
    "stepen_prokachki",
    "stepen_promyvki",
    "temp_prokachki",
    "temp_promyvki",
    "dataset_version",
    "loaded_at",
]


def _ensure_columns(df, columns):
    for column in columns:
        if column not in df.columns:
            df[column] = pd.NA
    return df[columns]


def _prepare_monthly(df2, dataset_version, loaded_at, source_file):
    monthly = df2.copy()
    if "well_uid" not in monthly.columns and "well" in monthly.columns:
        monthly["well_uid"] = monthly["well"]
    monthly["dataset_version"] = dataset_version
    monthly["loaded_at"] = loaded_at
    monthly["source_file"] = str(source_file)
    return _ensure_columns(monthly, MONTHLY_COLUMNS)


def _prepare_dim_area(df2, dataset_version, loaded_at):
    columns = [AREA_COL_MONTH, "ngdu"]
    if MEST_COL in df2.columns:
        columns.append(MEST_COL)
    dim = (
        df2[columns]
        .dropna(subset=[AREA_COL_MONTH, "ngdu"])
        .drop_duplicates()
        .rename(columns={AREA_COL_MONTH: AREA_COL_YEAR})
        .sort_values([AREA_COL_YEAR, "ngdu"])
    )
    if MEST_COL not in dim.columns:
        dim[MEST_COL] = pd.NA
    dim["dataset_version"] = dataset_version
    dim["valid_from"] = loaded_at
    dim["valid_to"] = pd.NaT
    dim["is_current"] = True
    return dim[["kod_ploshchadi", "ngdu", "mest", "dataset_version", "valid_from", "valid_to", "is_current"]]


def migrate(monthly_path, yearly_path, dataset_version, dry_run=False):
    if engine is None:
        raise RuntimeError("DATABASE_URL is required for parquet-to-SQL migration")

    monthly_path = Path(monthly_path)
    yearly_path = Path(yearly_path)
    loaded_at = datetime.now(timezone.utc).replace(tzinfo=None)

    df2 = pd.read_parquet(monthly_path)
    dfy = pd.read_parquet(yearly_path)

    required_monthly = {"date", AREA_COL_MONTH, "ngdu"}
    required_yearly = {AREA_COL_YEAR, "year"}
    missing_monthly = sorted(required_monthly - set(df2.columns))
    missing_yearly = sorted(required_yearly - set(dfy.columns))
    if missing_monthly or missing_yearly:
        raise RuntimeError(f"Missing columns monthly={missing_monthly} yearly={missing_yearly}")

    conflicts = validate_area_ngdu_uniqueness(df2)
    if not conflicts.empty:
        raise RuntimeError("Area to NGDU conflicts detected: " + conflicts.to_json(force_ascii=False, orient="records"))

    normalized_monthly, normalized_year = normalize_data(df2, dfy)
    monthly_out = _prepare_monthly(normalized_monthly, dataset_version, loaded_at, monthly_path)
    yearly_out = _ensure_columns(normalized_year.copy(), YEAR_COLUMNS)
    yearly_out["dataset_version"] = dataset_version
    yearly_out["loaded_at"] = loaded_at
    dim_out = _prepare_dim_area(normalized_monthly, dataset_version, loaded_at)

    report = {
        "dataset_version": dataset_version,
        "monthly_rows": int(len(monthly_out)),
        "year_rows": int(len(yearly_out)),
        "area_rows": int(len(dim_out)),
        "year_min": int(yearly_out["year"].min()) if not yearly_out.empty else None,
        "year_max": int(yearly_out["year"].max()) if not yearly_out.empty else None,
    }

    if dry_run:
        print(json.dumps({"dry_run": True, **report}, ensure_ascii=False, indent=2))
        return report

    with engine.begin() as connection:
        connection.execute(delete(monthly_metrics).where(monthly_metrics.c.dataset_version == dataset_version))
        connection.execute(delete(area_year_metrics).where(area_year_metrics.c.dataset_version == dataset_version))
        connection.execute(delete(dim_area).where(dim_area.c.dataset_version == dataset_version))
        connection.execute(delete(dashboard_metadata).where(dashboard_metadata.c.dataset_name == settings.dataset_name))

        monthly_out.to_sql("monthly_metrics", connection, if_exists="append", index=False, method="multi", chunksize=5000)
        yearly_out.to_sql("area_year_metrics", connection, if_exists="append", index=False, method="multi", chunksize=5000)
        dim_out.to_sql("dim_area", connection, if_exists="append", index=False, method="multi", chunksize=5000)
        connection.execute(
            insert(dashboard_metadata).values(
                dataset_name=settings.dataset_name,
                dataset_version=dataset_version,
                updated_at=loaded_at,
                row_count=len(yearly_out),
                description=f"Loaded from {monthly_path.name} and {yearly_path.name}",
            )
        )

    print(json.dumps({"dry_run": False, **report}, ensure_ascii=False, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description="Migrate Tatneft parquet files to SQL tables.")
    parser.add_argument("--monthly", default=settings.parquet_monthly_path)
    parser.add_argument("--yearly", default=settings.parquet_yearly_path)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    migrate(args.monthly, args.yearly, args.dataset_version, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
