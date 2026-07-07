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

The dashboard console proxies chat requests to LiteLLM. By default it calls the OpenAI-compatible chat-completions endpoint under `http://litellm.tatneft.guru/v1/chat/completions`. Configure the token only through environment variables; do not hard-code it in the repository.

For Docker Compose, put the issued credentials into a local `.env` file next to `docker-compose.yml`:

```dotenv
LITELLM_BASE_URL=http://litellm.tatneft.guru
LITELLM_AUTH_HEADER_NAME=<header key from LiteLLM>
LITELLM_API_KEY=<token from LiteLLM>
# Leave empty if the header value must be exactly the token; keep Bearer for Authorization-style headers.
LITELLM_AUTH_HEADER_PREFIX=
LITELLM_DEFAULT_MODEL=<model name from LiteLLM>
LITELLM_ALLOWED_MODELS=<model-1>,<model-2>
```

For a local shell run, export the same variables before starting the app:

```bash
export LITELLM_BASE_URL=http://litellm.tatneft.guru
export LITELLM_AUTH_HEADER_NAME="<header key from LiteLLM>"
export LITELLM_API_KEY="<token from LiteLLM>"
export LITELLM_AUTH_HEADER_PREFIX=""
export LITELLM_DEFAULT_MODEL="<model name from LiteLLM>"
export LITELLM_ALLOWED_MODELS="<model-1>,<model-2>"
python -m app
```

If Swagger shows a fully qualified chat endpoint different from `/v1/chat/completions`, set `LITELLM_CHAT_COMPLETIONS_URL` explicitly. The console health endpoint `/litellm-console/health` reports the active upstream URL and whether a server-side token is configured.

How to choose LiteLLM values:

- `LITELLM_AUTH_HEADER_PREFIX` depends on the auth scheme in Swagger or in the access note:
  - use `Bearer` only when the request header must look like `Authorization: Bearer <token>`;
  - use an empty value when the request header must look like `<header key from LiteLLM>: <token from LiteLLM>`.
- `LITELLM_DEFAULT_MODEL` is one model id that the console preselects.
- `LITELLM_ALLOWED_MODELS` is the comma-separated list shown in the model dropdown.

To discover model ids, call LiteLLM's OpenAI-compatible model list endpoint with the same header key/token pair:

```bash
BASE_URL=http://litellm.tatneft.guru
HEADER_NAME="<header key from LiteLLM>"
TOKEN="<token from LiteLLM>"
PREFIX=""  # or Bearer for Authorization: Bearer <token>

if [ -n "$PREFIX" ]; then
  HEADER_VALUE="$PREFIX $TOKEN"
else
  HEADER_VALUE="$TOKEN"
fi

curl -sS -H "$HEADER_NAME: $HEADER_VALUE" "$BASE_URL/v1/models"
```

Use the `id` values from the response, for example `LITELLM_DEFAULT_MODEL=<one id>` and `LITELLM_ALLOWED_MODELS=<id-1>,<id-2>`. If `/v1/models` is not present in the local Swagger, use the model-list endpoint name shown there instead.

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
