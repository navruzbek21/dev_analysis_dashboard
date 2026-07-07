# Промпт для переноса изменений в другую папку проекта

Ты работаешь в другой папке похожего Dash-проекта для анализа разработки нефтяных месторождений. Нужно перенести набор улучшений из исходной рабочей версии, но не делать слепой overwrite: сначала изучи структуру целевого проекта, затем адаптируй изменения к текущим файлам и локальным паттернам.

## Цель

Сделать веб-приложение более безопасным, воспроизводимым и методически корректным:

- убрать секреты из кода и перевести конфигурацию в `.env`;
- добавить вкладку контроля качества данных;
- улучшить физический смысл агрегаций по активу;
- исправить методику расчета эффективности ГТМ, чтобы неизвестный эффект не считался неэффективным;
- добавить SQL-ограничения качества данных;
- улучшить Docker/Gunicorn/healthcheck;
- добавить воспроизводимые smoke-данные для локального запуска;
- покрыть изменения тестами.

## Общие правила переноса

- Сначала посмотри `git status`, структуру проекта и существующие версии `app.py`, `gtm_analysis.py`, `config.py`, `services/aggregation_service.py`, `qwen_console.py`, Docker-файлов и тестов.
- Не коммить и не удаляй пользовательские изменения без явного запроса.
- Удали/игнорируй `__pycache__`, `*.pyc`, `.venv`, `.env`, `*.parquet`, `*.db`, `*.sqlite`, логи и табличные выгрузки. Эти файлы не должны попадать в git.
- Если в целевой папке структура отличается, сохрани смысл изменений, а не буквальное расположение кода.

## Файлы, которые нужно создать

1. `.env.example`

Добавь пример переменных:

```env
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8048
APP_DEBUG=false
LOG_LEVEL=INFO

DATA_SOURCE=sql
DATABASE_URL=postgresql+psycopg://dashboard:dashboard@localhost:5432/dashboard
REDIS_URL=redis://localhost:6379/0
DATASET_NAME=area_metrics

CACHE_KEY_PREFIX=tatneft_dashboard
CODE_CACHE_VERSION=dashboard-cache-v1
LOCAL_CACHE_TTL=60
LOCAL_CACHE_MAXSIZE=128
CACHE_DATA_TTL=3600
CACHE_AGG_TTL=3600
CACHE_PERIODS_TTL=21600
CACHE_FIGURE_TTL=1800
FIGURE_CACHE_MAX_BYTES=10485760

DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_RECYCLE=1800
DB_POOL_TIMEOUT=30

PARQUET_MONTHLY_PATH=df2.parquet
PARQUET_YEARLY_PATH=df_ploshad_year.parquet

GTM_RESULT_DF_PATH=result_df.parquet
GTM_PLOSHAD_YEAR_PATH=df_ploshad_year.parquet
GTM_ITOG_GTM_PATH=df_itog_gtm_2.parquet
GTM_FACTOR_ANALYSIS_PATH=factor_analysis_df.parquet

QWEN_CONSOLE_ENABLED=false
QWEN_ACCESS_TOKEN=
QWEN_UPSTREAM=https://tatneft.guru/api/http
QWEN_VERIFY_SSL=true
QWEN_TIMEOUT=120
QWEN_DIALOGUE_FIELD=dialogue_uuid
QWEN_MAX_PROMPT_CHARS=16000
QWEN_RATE_LIMIT_PER_MINUTE=30
QWEN_ALLOWED_MODELS=qwen3-32b,qwen2.5-72b,qwen2.5-32b,qwen2.5-14b,qwen2.5-7b
```

2. `services/data_quality_service.py`

Создай сервис контроля качества годового среза. Он должен:

- брать данные через `data_service.get_filtered_year_data(selected_ngdu, selected_areas, selected_mest)`;
- возвращать словарь `{"summary": ..., "issues": ..., "null_rates": ...}`;
- проверять отсутствующие важные колонки;
- считать null-rate по ключевым колонкам;
- ловить дубли на зерне `kod_ploshchadi + year`;
- проверять диапазоны `wc`, `wc_month_avg`, `kin`, `kiz`, `niz_otbor` в пределах `0..100`;
- проверять неотрицательность добычи, закачки, фондов, дебитов, приемистости и накопленных показателей;
- проверять монотонность накопленных показателей внутри площади;
- проверять баланс жидкости: `dobycha_liq ≈ dobycha_nefti + dobycha_vody`, допустимое отклонение 5%;
- для пустой выборки возвращать статус `Нет данных`;
- для high issues возвращать статус `Требует исправления`, иначе `Есть замечания` или `OK`.

3. `sql/005_add_quality_constraints.sql`

Добавь SQL-миграцию для PostgreSQL:

- unique index `ux_area_year_dataset_area_year` на `(dataset_version, kod_ploshchadi, year)` в `area_year_metrics`;
- partial unique index `ux_dim_area_dataset_area_current` на `(dataset_version, kod_ploshchadi)` в `dim_area`, где `is_current = TRUE`;
- partial unique index `ux_monthly_dataset_area_well_date` на `(dataset_version, ploshad, well_uid, date)` в `monthly_metrics`, где ключи не NULL;
- `CHECK NOT VALID` для неотрицательных годовых потоков;
- `CHECK NOT VALID` для диапазонов `wc`, `kin`, `kiz`, `niz_otbor` в `0..100`;
- `CHECK NOT VALID` для неотрицательных фондов;
- `CHECK NOT VALID` для месячных дебитов, приемистости и `wc`.

4. `scripts/create_smoke_gtm_parquet.py`

Добавь воспроизводимый генератор демо-parquet для GTM:

- на выходе создает в корне проекта `result_df.parquet`, `df_ploshad_year.parquet`, `df_itog_gtm_2.parquet`, `factor_analysis_df.parquet`;
- seed по умолчанию `42`;
- минимум 2 месторождения/площади, 18 операций, годы ГТМ 2023-2025;
- в `result_df` нужны колонки `well`, `date`, `gtm_date`, `month_offset`, `qliq`, `qoil`, `qoil_plan`, `qinj`, `wcut`, `Р_пл`, `Р_заб`, `gtm_year`, `year`, `назнач_скв_факт`, `направление`, `mest`, `plosh`, `вид_операции`;
- `month_offset` должен покрывать диапазон `-15..15`;
- часть операций должна быть эффективной, часть неэффективной, часть на нагнетательных скважинах;
- `df_itog_gtm_2` должен содержать `год_гтм`, `year`, `dop_dob_month`, `направление`, `plosh`, `mest`, `well`;
- `factor_analysis_df` должен содержать `wcut_factor`, `qliq_factor`, `Р_пл_factor`, `Р_заб_factor`, `Kprod_factor`.

5. Тесты

Добавь:

- `tests/test_data_quality_service.py` для проверки дублей, диапазонов, отрицательных значений, немонотонных накопленных показателей, баланса жидкости и чистого набора;
- `tests/test_sql_quality_constraints_static.py` для проверки наличия индексов/constraints в `005_add_quality_constraints.sql`;
- обнови существующие тесты по характеристикам вытеснения и статическому контракту, чтобы они проверяли новую вкладку качества и корректную агрегацию.

## Файлы, которые нужно изменить

### `.gitignore`

Добавь:

```gitignore
.venv/
.DS_Store
.env
.env.*
!.env.example
*.parquet
*.csv
*.tsv
*.xlsx
*.xls
*.sqlite
*.db
*.log
```

Оставь `__pycache__/`, `*.py[cod]`, `.pytest_cache/`.

### `config.py`

- Подключи `python-dotenv`: `load_dotenv()` должен вызываться, если пакет установлен.
- `Settings.validate()` должен принимать `require_database=None`.
- Если `require_database is None`, требуй `DATABASE_URL` только для `APP_ENV in {"production", "prod", "staging"}`.
- В development разреши запуск без `DATABASE_URL`, если приложение работает в parquet-режиме или smoke-сценарии.

### `qwen_console.py`

Сделай Qwen-консоль безопасной:

- полностью удалить hardcoded `QWEN_ACCESS_TOKEN`;
- читать `QWEN_ACCESS_TOKEN` из env;
- по умолчанию отключать консоль, если токен не задан;
- добавить `QWEN_CONSOLE_ENABLED`;
- `/qwen-console` при отключенной консоли должен возвращать `503` с понятным текстом;
- `/qwen-console/health` должен показывать, включена ли консоль и настроен ли токен;
- `/qwen-console/api` должен возвращать `503`, если консоль отключена;
- добавить same-origin проверку по `Sec-Fetch-Site`, `Origin`/`Referer`;
- добавить простой in-memory rate limit через `deque` и `monotonic`, env `QWEN_RATE_LIMIT_PER_MINUTE`, default `30`;
- добавить лимит длины промпта `QWEN_MAX_PROMPT_CHARS`, default `16000`, ошибка `413`;
- добавить allowlist моделей `QWEN_ALLOWED_MODELS`; неизвестную модель заменять первой разрешенной;
- не отдавать токен в браузер и не логировать его.

### `services/aggregation_service.py`

Исправь агрегацию годового среза по активу:

- добавь `_weighted_mean(group, value_col, weight_col)`;
- добавь `_ratio_from_sums(grouped, numerator, denominator, multiplier=1.0)`;
- при группировке по `year` суммируй физические объемы: нефть, жидкость, вода, закачка, фонды, `gz`, `niz`, накопленные показатели;
- `wc` считать как `100 * dobycha_vody / dobycha_liq`, если есть вода и жидкость; fallback - среднее `wc` или `wc_month_avg`;
- `vnf_tek` считать как `dobycha_vody / dobycha_nefti`;
- `vnf_nak` считать как `dobycha_vody_cum / dobycha_nefti_cum`;
- `kin` и `kiz` считать как `100 * dobycha_nefti_cum / niz`, если есть `niz`; fallback - weighted mean по `niz`, затем среднее;
- пересчитать `q_priem_q_liq`, `stepen_prokachki`, `stepen_promyvki` из сумм;
- не усреднять доли и отношения там, где нужен ratio of sums.

### `gtm_analysis.py`

Исправь методику эффективности ГТМ:

- если нет базы до ГТМ, `Δqliq` и `Δqoil` должны быть `NaN`, а не расчет от нуля;
- убери правило, которое обнуляло базу при очень далекой истории `month_offset <= -36`;
- `effective` должен быть `NaN`, если `Δqoil` неизвестен; иначе `1`, если `Δqoil > 0`, и `0`, если `Δqoil <= 0`;
- `effective_plan` должен быть `NaN`, если нет факта 1-3 месяцев или плана;
- `apply_efficiency_algorithm()` не должен превращать неизвестное значение в `0`;
- KPI эффективности считай только по валидным `effective`;
- таблица проблемных ГТМ должна показывать только `effective == 0`, а не `NaN`;
- `analytics_tools.gtm_efficiency()` тоже должен исключать `NaN effective` из расчетов эффективности и возвращать `effective_sample`.

### `app.py`

- Импортируй `data_quality_service`.
- Убери неиспользуемые импорты вроде `AREA_COL_MONTH`, `MEST_COL`, если они остались.
- Вызови `settings.validate()` после настройки логирования.
- Функцию `compute_wc_kiz_periods()` не держи дубликатом алгоритма; сделай обертку над `periods_service.compute_wc_kiz_periods_raw(...)`.
- Добавь вкладку `Качество данных` рядом с основными вкладками.
- Добавь `quality_status_card()`, `_quality_table()`, `quality_tab_layout()`.
- Добавь callback `update_quality_report(...)`, который использует глобальные фильтры `mest`, `ngdu`, `area`, вызывает `data_quality_service.get_quality_report(...)` и рендерит:
  - карточки статуса, количества строк, площадей, периода;
  - таблицу проблем качества;
  - таблицу null-rate по ключевым колонкам.
- В `render_tab()` добавь обработку `tab-quality`.

### CSS

В основной CSS, asset CSS и legacy CSS добавь стили:

- `.quality-table-wrap`;
- `.quality-table`;
- `.quality-table th`;
- `.quality-table td`;
- dark theme border handling.

Стили должны быть компактными, без карточек внутри карточек, таблица должна иметь horizontal overflow.

### Dockerfile

- Добавь `PYTHONDONTWRITEBYTECODE=1` и `PYTHONUNBUFFERED=1`.
- Установи `curl` для healthcheck.
- Запускай приложение через Gunicorn:

```dockerfile
CMD ["gunicorn", "app:server", "--bind", "0.0.0.0:8048", "--workers", "4", "--threads", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
```

### `docker-compose.yml`

- По умолчанию используй `DATA_SOURCE=sql`.
- Настрой `DATABASE_URL=postgresql+psycopg://dashboard:dashboard@postgres:5432/dashboard`.
- Добавь `APP_ENV`, `APP_HOST`, `APP_PORT`, `APP_DEBUG`, `REDIS_URL`.
- Отключи Qwen по умолчанию `QWEN_CONSOLE_ENABLED=false`.
- Добавь healthcheck для app через `/health`, для redis через `redis-cli ping`, для postgres через `pg_isready`.
- `app.depends_on` должен ждать healthy postgres и redis.

### `README.md`

В список SQL-миграций добавь:

```bash
psql "$DATABASE_URL" -f sql/005_add_quality_constraints.sql
```

### `requirements.txt`

- Удали `flask-caching`, если код уже использует собственный cache backend и пакет больше не нужен.
- Убедись, что есть `python-dotenv`, `gunicorn`, `psycopg`, `pyarrow`, `redis`, `cachetools`, `orjson`, `dash`, `plotly`, `pandas`, `numpy`, `sqlalchemy`.

### Legacy launcher

В `app_tatneft_g17_g20_diag.py` и `legacy/app_tatneft_g17_g20_diag.py` замени hardcoded host `10.241.112.254` на env:

```python
app.run(
    debug=os.getenv("APP_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"},
    host=os.getenv("APP_HOST", "127.0.0.1"),
    port=int(os.getenv("APP_PORT", "8048")),
)
```

И добавь `import os`.

## Локальные demo-данные и запуск

Если в целевом проекте уже есть `scripts/create_smoke_sqlite.py`, используй его для SQL smoke-базы:

```bash
DATABASE_URL=sqlite:////private/tmp/tatneft_smoke.db REDIS_URL= python -m scripts.create_smoke_sqlite
```

Затем создай GTM parquet:

```bash
python -m scripts.create_smoke_gtm_parquet
```

Запусти локально:

```bash
DATABASE_URL=sqlite:////private/tmp/tatneft_smoke.db REDIS_URL= APP_HOST=127.0.0.1 APP_PORT=8051 APP_DEBUG=false python app.py
```

Проверь:

```bash
curl -fsS http://127.0.0.1:8051/health
curl -fsS http://127.0.0.1:8051/ready
curl -fsSI http://127.0.0.1:8051
```

Ожидаемо:

- `/health`: `{"status":"ok","data_source":"sql"}`;
- `/ready`: `status=ready`, `database=true`, `dataset_version=smoke-v1`; `redis=false` допустим, если `REDIS_URL=` специально пустой;
- главная страница возвращает `HTTP 200`.

## Проверки

После переноса запусти:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q
```

Также проверь вручную в браузере:

- основные вкладки строятся на SQL smoke-данных;
- вкладка `Анализ эффективности ГТМ` видит parquet и строит KPI/графики/таблицу;
- вкладка `Качество данных` реагирует на фильтры;
- Qwen-консоль отключена без токена и не раскрывает секреты.

## Важные методические требования

- Не считать неизвестный эффект ГТМ неэффективным. `NaN` должен исключаться из процента эффективности.
- Не считать базу ГТМ равной нулю, если дооперационной истории нет. Это создает искусственные положительные эффекты.
- Для водонефтяных и фондовых коэффициентов используй физически осмысленные отношения сумм, а не среднее процентов по площадям.
- Валидация качества должна быть видимой пользователю в интерфейсе и частично продублирована SQL constraints.
- Smoke-данные должны быть синтетическими, воспроизводимыми и не попадать в git.

## Что не переносить как бизнес-логику

- Не переносить сгенерированные `*.parquet`, `*.db`, `.venv`, `__pycache__`, `*.pyc`.
- Не восстанавливать удаленные pycache-файлы.
- Не добавлять реальные токены или пароли в код, `.env.example` или README.
