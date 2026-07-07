# Tatneft Dash Parquet Dashboard

Dash/Plotly dashboard for Tatneft development analysis. The current codebase uses only local parquet files as the data source.

## Data source

The application reads two parquet files:

- `PARQUET_MONTHLY_PATH` (default: `df2.parquet`) — monthly well-level data.
- `PARQUET_YEARLY_PATH` (default: `df_ploshad_year.parquet`) — yearly area-level metrics.

`services/data_service.py` loads these files with `pandas.read_parquet`, normalizes them through `normalization.py`, and serves cached filter/data slices to the Dash callbacks.

## Files

- `app.py` is the Dash entrypoint and exports `server = app.server`.
- `app_tatneft_g17_g20_diag.py` is the standalone parquet-based legacy-style app.
- `legacy/` contains rollback copies.
- `assets/operator_tatneft_style.css` is auto-loaded by Dash.
- `normalization.py` contains parquet normalization logic.
- `services/*` contains data, aggregate, period, and figure cache services.

## Cache TTL

- L1 local TTL: `LOCAL_CACHE_TTL=60`
- Data/options: `CACHE_DATA_TTL=3600`
- Aggregates: `CACHE_AGG_TTL=3600`
- g16/g20 period result: `CACHE_PERIODS_TTL=21600`
- Figure JSON for `g01`, `g16`, `g20`, `main-change`: `CACHE_FIGURE_TTL=1800`

Cache keys include a parquet dataset version derived from the source file paths, modification times, and sizes.

## Run

Development:

```bash
python -m app
```

Custom parquet paths:

```bash
PARQUET_MONTHLY_PATH=/path/to/df2.parquet \
PARQUET_YEARLY_PATH=/path/to/df_ploshad_year.parquet \
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

Docker:

```bash
docker compose up --build
```

## LiteLLM console

The dashboard tab formerly named Qwen now proxies chat requests to LiteLLM. By default it calls the OpenAI-compatible chat-completions endpoint under `http://litellm.tatneft.guru/v1/chat/completions`. Configure the token only through environment variables; do not hard-code it in the repository.

```bash
export LITELLM_BASE_URL=http://litellm.tatneft.guru
export LITELLM_API_KEY="<your token>"
# If the issued credential requires a non-standard header key, override it:
export LITELLM_AUTH_HEADER_NAME="<header key from LiteLLM>"
# Use an empty prefix when the header value must be exactly the token.
export LITELLM_AUTH_HEADER_PREFIX=Bearer
export LITELLM_DEFAULT_MODEL=qwen2.5-72b
export LITELLM_ALLOWED_MODELS=qwen3-32b,qwen2.5-72b,qwen2.5-32b,qwen2.5-14b,qwen2.5-7b
python -m app
```

If Swagger shows a fully qualified chat endpoint different from `/v1/chat/completions`, set `LITELLM_CHAT_COMPLETIONS_URL` explicitly. The console health endpoint `/qwen-console/health` reports the active upstream URL and whether a server-side token is configured.

## Health checks

- `/health` returns the application status and `data_source: parquet`.
- `/ready` verifies that the parquet dataset version can be resolved and reports Redis availability separately.

## Docker refresh / stale containers

If container logs mention SQL objects such as `dashboard_metadata` or `metrics_repository`, the running container is stale. Recreate the stack and remove orphaned services from the former SQL setup:

```bash
docker compose down --remove-orphans
docker compose up --build --force-recreate
```

The current Compose file has no Postgres service and the runtime code path does not import the SQL repository.

## Tests

```bash
PYTHONPATH=. pytest
```

In minimal environments without pytest:

```bash
PYTHONPATH=. python -m unittest discover -s tests
```

## Rollback

1. Stop the current app.
2. Restore the legacy entrypoint if needed: `cp legacy/app_tatneft_g17_g20_diag.py app.py`.
3. Restore CSS if needed: `cp legacy/operator_tatneft_style.css assets/operator_tatneft_style.css`.
