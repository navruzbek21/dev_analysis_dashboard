# Tatneft Dash SQL Migration

This project keeps the original Dash/Plotly UI contract from `app_tatneft_g17_g20_diag.py` and moves production data access to SQLAlchemy, SQL, local L1 TTL cache, Redis L2 cache, cached aggregates, cached period segmentation, and selective Plotly figure JSON caching.

## Files

- `legacy/app_tatneft_g17_g20_diag.py` and `legacy/operator_tatneft_style.css` are immutable rollback copies.
- `app.py` is the migrated Dash entrypoint and exports `server = app.server`.
- `assets/operator_tatneft_style.css` is an exact copy of the source CSS and is auto-loaded by Dash.
- `normalization.py` contains the former parquet normalization logic for ETL and parity mode.
- `repositories/metrics_repository.py` contains SQLAlchemy Core queries only.
- `services/*` contains data, aggregate, period, and figure cache services.

## SQL Schema

Create the schema and indexes once, then keep reusing the same database connection string:

```bash
export DATABASE_URL=postgresql://dashboard:dashboard@localhost:5432/dashboard
psql "$DATABASE_URL" -f sql/001_create_tables.sql
psql "$DATABASE_URL" -f sql/002_create_indexes.sql
psql "$DATABASE_URL" -f sql/003_create_views.sql
psql "$DATABASE_URL" -f sql/004_add_mest.sql  # for existing databases
```

The schema scripts are idempotent (`IF NOT EXISTS` / replaceable views), so rerunning them is safe, but not required on every application start. In Docker Compose, Postgres stores data in the named `postgres_data` volume; use `docker compose stop` / `docker compose up -d` to keep the existing database, and only use `docker compose down -v` when you intentionally want to delete it and recreate it from scratch.

After the schema and data are loaded, start the app with the same `DATABASE_URL` and `DATA_SOURCE=sql`; SQLAlchemy creates a connection pool to the existing database instead of creating a new database.


### Existing local PostgreSQL database

If the data already exists in a local PostgreSQL database, do not create a new database. Point `DATABASE_URL` at that database and either run the app against the canonical dashboard tables or migrate from the existing parquet-named tables once. For example, when the local database is `romashka_devon` and it contains tables named like the parquet files (`df2` and `df_ploshad_year`):

```bash
export DATABASE_URL=postgresql://localhost:5432/romashka_devon
python -m scripts.migrate_parquet_to_sql \
  --source sql-tables \
  --monthly-table df2 \
  --yearly-table df_ploshad_year \
  --dataset-version romashka-devon-v1

DATA_SOURCE=sql DATABASE_URL=$DATABASE_URL python -m app
```

The app reads the canonical SQL tables (`dashboard_metadata`, `dim_area`, `monthly_metrics`, and `area_year_metrics`). The `--source sql-tables` mode keeps the existing `df2` / `df_ploshad_year` tables intact and creates or refreshes only the app tables for the selected `dataset_version`.

The logical tables are:

- `dashboard_metadata(dataset_name, dataset_version, updated_at, row_count, description)`
- `dim_area(kod_ploshchadi, ngdu, dataset_version, valid_from, valid_to, is_current)`
- `monthly_metrics(date, year, ngdu, ploshad, well_uid, debit_*, priem, wc, dataset_version, loaded_at)`
- `area_year_metrics(...)` with normalized annual metrics and derived columns used by the dashboard.

## Cache TTL

- L1 local TTL: `LOCAL_CACHE_TTL=60`
- SQL data/options: `CACHE_DATA_TTL=3600`
- Aggregates: `CACHE_AGG_TTL=3600`
- g16/g20 period result: `CACHE_PERIODS_TTL=21600`
- Figure JSON for `g01`, `g16`, `g20`, `main-change`: `CACHE_FIGURE_TTL=1800`

Cache keys include `dataset_version` and `CODE_CACHE_VERSION`. Invalidation is version-based: a successful ETL load updates `dashboard_metadata.dataset_version`, and old Redis keys naturally expire.

## Migration

```bash
python -m scripts.migrate_parquet_to_sql \
  --monthly df2.parquet \
  --yearly df_ploshad_year.parquet \
  --dataset-version 2026-06-15-v1 \
  --dry-run

python -m scripts.migrate_parquet_to_sql \
  --monthly df2.parquet \
  --yearly df_ploshad_year.parquet \
  --dataset-version 2026-06-15-v1
```

The ETL checks area to NGDU uniqueness before loading and preserves the legacy rule that `debit_neft` and `debit_liq` are averaged on rows where both values are present.

## Run

Development:

```bash
cp .env.example .env
docker compose up -d postgres redis
python -m app
```

Linux production:

```bash
gunicorn app:server \
  --bind 0.0.0.0:8048 \
  --workers 4 \
  --threads 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
```

Windows production:

```bash
waitress-serve --host=0.0.0.0 --port=8048 app:server
```

## Parquet Parity Mode

Use only for validation:

```bash
DATA_SOURCE=parquet python -m app
python -m scripts.compare_parquet_sql --dataset-version 2026-06-15-v1
```

Production default is `DATA_SOURCE=sql`.

## Tests

```bash
python -m compileall .
pytest
```

In minimal environments without pytest, the static baseline tests can run with:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/codex_pycache python3 -m unittest discover -s tests
```

## Benchmark

Record before and after:

- startup time
- first page load
- cold filter request
- warm filter request
- g16 calculation time
- g20 calculation time
- figure JSON size
- SQL query count per callback
- memory per worker

Warm requests should hit L1 or Redis and avoid SQL; g16 and g20 must share one cached `PeriodResult`.

For a wiring-only local smoke test when real parquet files are not present:

```bash
DATABASE_URL=sqlite:////private/tmp/tatneft_smoke.db REDIS_URL= \
  python -m scripts.create_smoke_sqlite

DATABASE_URL=sqlite:////private/tmp/tatneft_smoke.db REDIS_URL= \
  APP_HOST=127.0.0.1 APP_PORT=8051 python app.py
```

This synthetic dataset is only for UI/callback smoke tests. Use `scripts.compare_parquet_sql` against the real parquet and SQL data for parity.

## Rollback

1. Stop the migrated app.
2. Restore the legacy entrypoint if needed:
   `cp legacy/app_tatneft_g17_g20_diag.py app.py`
3. Restore CSS if needed:
   `cp legacy/operator_tatneft_style.css assets/operator_tatneft_style.css`
4. Use `DATA_SOURCE=parquet` for temporary parity checks.
