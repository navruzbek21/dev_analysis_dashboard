# Tatneft Dash Parquet Dashboard

Dash/Plotly dashboard for Tatneft development analysis. The current codebase uses only local parquet files as the data source.

## Data source

The application reads two parquet files:

- `PARQUET_MONTHLY_PATH` (default: `df2.parquet`) — monthly well-level data.
- `PARQUET_YEARLY_PATH` (default: `df_ploshad_year.parquet`) — yearly area-level metrics.

`services/data_service.py` loads these files with `pandas.read_parquet`, normalizes them through `normalization.py`, and serves cached filter/data slices to the Dash callbacks.

## Files

- `app.py` is the thin Dash entrypoint: creates the app, wires layout, routes and callback registration; exports `server = app.server`.
- `theme.py` holds the shared palette, plotly template and runtime theming used by every tab.
- `common.py` holds shared tab constants and helpers (metric dictionaries, filter normalization, KPI cards).
- `figures/` contains the figure builders: `main_tab.py`, `asset_tab.py`, `displacement.py`.
- `layouts.py` contains tab layouts and the page shell.
- `callbacks/` contains callback modules registered via `register(app)`: `theme_callbacks.py`, `filters.py`, `main.py`, `asset.py`.
- `gtm_analysis.py` is the GTM efficiency tab (layout + callbacks), `litellm_console.py` the LiteLLM console (page template in `templates/litellm_console.html`).
- `legacy/` contains rollback copies.
- `assets/operator_tatneft_style.css` is auto-loaded by Dash.
- `normalization.py` contains parquet normalization logic.
- `services/*` contains data, aggregate, period, and figure cache services.

## Cache TTL

- L1 local TTL: `LOCAL_CACHE_TTL=60`
- Data/options: `CACHE_DATA_TTL=3600`
- Aggregates: `CACHE_AGG_TTL=3600`
- g16/g20 period result: `CACHE_PERIODS_TTL=21600`
- Figure JSON (main tab figures, `g01`, `g16`, `g20`, GTM tab figures): `CACHE_FIGURE_TTL=1800`

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

The dashboard console proxies chat requests to LiteLLM. By default it calls the OpenAI-compatible chat-completions endpoint under `https://litellm.tatneft.guru/v1/chat/completions`. Configure the token only through environment variables; do not hard-code it in the repository.

For Docker Compose, put the issued credentials into a local `.env` file next to `docker-compose.yml`:

```dotenv
LITELLM_BASE_URL=https://litellm.tatneft.guru
LITELLM_AUTH_HEADER_NAME=<header key from LiteLLM>
LITELLM_API_KEY=<token from LiteLLM>
# Leave empty if the header value must be exactly the token; keep Bearer for Authorization-style headers.
LITELLM_AUTH_HEADER_PREFIX=
# Optional: lower this while diagnosing network/auth issues.
LITELLM_TIMEOUT=30
LITELLM_DEFAULT_MODEL=<model name from LiteLLM>
LITELLM_ALLOWED_MODELS=<model-1>,<model-2>
```

For a local shell run, export the same variables before starting the app:

```bash
export LITELLM_BASE_URL=https://litellm.tatneft.guru
export LITELLM_AUTH_HEADER_NAME="<header key from LiteLLM>"
export LITELLM_API_KEY="<token from LiteLLM>"
export LITELLM_AUTH_HEADER_PREFIX=""
export LITELLM_TIMEOUT=30
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
BASE_URL=https://litellm.tatneft.guru
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

Troubleshooting a long wait followed by `fetch failed`:

1. Check that Compose sees the same values that you put into `.env`:

   ```bash
   docker compose config | sed -n '/LITELLM_/p'
   ```

2. From inside the app container, check that LiteLLM is reachable and that auth works. Use the same header key/token/prefix values as in `.env`:

   ```bash
   docker compose exec app sh -lc '
     if [ -n "$LITELLM_AUTH_HEADER_PREFIX" ]; then
       HEADER_VALUE="$LITELLM_AUTH_HEADER_PREFIX $LITELLM_API_KEY"
     else
       HEADER_VALUE="$LITELLM_API_KEY"
     fi
     curl -v --max-time 30 -H "$LITELLM_AUTH_HEADER_NAME: $HEADER_VALUE" "$LITELLM_BASE_URL/v1/models"
   '
   ```

3. If `curl` hangs or times out from the container, the problem is network/DNS/firewall/proxy access from Docker to LiteLLM, not the browser UI. If it returns `401`/`403`, check `LITELLM_AUTH_HEADER_NAME`, `LITELLM_AUTH_HEADER_PREFIX`, and `LITELLM_API_KEY`.
4. For a custom header key with raw token auth, keep `LITELLM_AUTH_HEADER_PREFIX=` empty. The Compose file intentionally preserves an empty prefix instead of replacing it with `Bearer`.

You can also run the same availability check from the project directory. The script reads `.env`, prints the effective LiteLLM URL/header/model without exposing the full token, calls `/v1/models`, and can optionally send a chat completion test:

```bash
python check_litellm.py
python check_litellm.py --prompt "Ответь одним словом: работает?"
# The implementation also remains available as: python scripts/check_litellm.py
```

When `--prompt` succeeds, the script prints only the assistant message extracted from `choices[0].message.content` instead of dumping provider-specific reasoning fields.

On Windows, `[WinError 10060]` means the TCP connection timed out before any LiteLLM HTTP response was received. In that case, verify VPN/corporate network access and compare with:

```powershell
Test-NetConnection litellm.tatneft.guru -Port 80
Test-NetConnection litellm.tatneft.guru -Port 443
curl.exe -v --max-time 30 http://litellm.tatneft.guru/v1/models
curl.exe -vk --max-time 30 https://litellm.tatneft.guru/v1/models
```

If port `80` fails but the site opens in a browser, the browser may be using HTTPS or a corporate proxy. The default `.env` value should be `LITELLM_BASE_URL=https://litellm.tatneft.guru`. If only the browser works, check Windows proxy settings and export proxy variables for Python/Compose, for example `HTTP_PROXY` and `HTTPS_PROXY`.

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
pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest -q
```

The same checks run in CI (`.github/workflows/ci.yml`) together with `pip-audit`.

## Rollback

1. Stop the current app.
2. Restore the legacy entrypoint if needed: `cp legacy/app_tatneft_g17_g20_diag.py app.py`.
3. Restore CSS if needed: `cp legacy/operator_tatneft_style.css assets/operator_tatneft_style.css`.

### LiteLLM data-analysis mode and dashboard filters

In `Режим → Анализ данных`, the console now sends the current dashboard filter state to the backend along with the question. The current values of `Месторождение`, `НГДУ`, and `Площадь` are stored in the browser under `dashboard-analysis-filters`; the LiteLLM iframe reads that value and includes it as `dashboard_filters` in `/litellm-console/api` requests.

This matters for requests such as `проанализируй эффективность ГТМ по текущему срезу` or `эффективность ГТМ по НГДУ 30`: the backend enriches the LLM-generated plan with the active dashboard filters and also recognizes explicit `НГДУ <номер>` mentions in the text. For GTM tables, where the parquet source is keyed by area rather than directly by `ngdu`, the backend maps the selected NGDU to its available areas before running the GTM aggregation.

The LLM does not receive raw parquet files directly. Instead, it selects one of the safe analytical tools and receives aggregated rows/summaries from the backend. To ask what data is available across the source parquet tables, use a request like `какие исходные таблицы доступны и сколько строк в текущем срезе?`; this uses the `dataset_overview` tool and reports full vs filtered row counts for the loaded yearly and GTM parquet datasets. To let the LLM perform arbitrary analysis over new raw tables, add a dedicated tool in `analytics_tools.py` rather than exposing unrestricted file access.

#### Arbitrary table analysis tool

For broader questions, `Режим → Анализ данных` can use the safe `table_analysis` backend tool. It is deliberately not a Python/SQL execution sandbox. The LLM may choose a table, dashboard filters, equality filters, up to five grouping columns, up to eight aggregations (`sum`, `mean`, `median`, `min`, `max`, `count`, `nunique`), sorting, and a capped row limit. The backend validates every table, column, aggregation, and limit before running pandas operations.

Available table names are: `monthly_raw`, `yearly_raw`, `yearly`, `gtm_level`, `result_df`, and `factor_analysis_df`. Example user requests:

- `Сгруппируй исходные месячные данные по ngdu и посчитай средний debit_neft за текущий срез`
- `Покажи топ-10 площадей по суммарной добыче нефти в yearly`
- `По таблице gtm_level сравни средний Δqoil по направлениям ГТМ`

If a new parquet dataset should be analyzable, add it to `TABLE_ANALYSIS_TABLES` and `_load_table_frame()` in `analytics_tools.py`, then describe the expected columns in tests.

### Block/area-section data

If the source parquet files contain a `block` column, the dashboard treats `block = all` as the whole-area row and numeric/string block values (`1`, `2`, `3`, ...) as section-level rows. Regular area-level dashboards use the `all` rows by default to avoid double-counting area totals and block rows. When a specific block is selected, callbacks filter yearly, asset, and GTM data by that block.

Block contour files can be placed in `area_contours` next to area contours. Use the naming pattern `<area>_<block>.txt`, for example `Альметьевская_1.txt` or `Альметьевская_2.txt`. When exactly one area is selected on the main tab, the map overlays available block contours, labels each block with its number, metric value, remaining recoverable reserves (`niz - dobycha_nefti_cum`), `niz_otbor`, and `Ртек/Рнач`, and keeps working if some areas do not have block data/contours.

The `Анализ по активу` and `Анализ эффективности ГТМ` tabs now include a `Блок/участок площади` dropdown. Choose `Вся площадь` to use the area-level `all` rows, or choose a specific block to build all visible charts for that block. Clicking anywhere inside an area fill applies that area to the global `Площадь` filter; clicking anywhere inside a block fill or on its large transparent center marker opens `Анализ по активу` for the clicked area and selected block.
