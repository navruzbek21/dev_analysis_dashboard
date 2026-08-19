# Техническое задание для Codex: перенос текущего Dash-приложения в SQL и многоуровневое кэширование

**Версия инструкции:** 2.0  
**Дата актуализации:** 15 июня 2026 года

## 1. Исходные файлы и источник истины

Работай только с этими двумя исходными файлами:

```text
app_tatneft_g17_g20_diag.py
operator_tatneft_style.css
```

Они являются источником истины для:

- бизнес-логики;
- состава и порядка графиков;
- идентификаторов Dash-компонентов;
- поведения фильтров;
- формул производных показателей;
- алгоритма периодизации;
- цветовой схемы;
- CSS-классов;
- размеров карточек;
- адаптивной вёрстки.

Не используй ранее созданные экспериментальные файлы с названиями `optimized`, `fixed`, `stable` или `labels_*` как основу миграции. Их можно изучать только как историю экспериментов, но итоговая реализация должна сохранять поведение именно `app_tatneft_g17_g20_diag.py` и стили именно `operator_tatneft_style.css`.

Перед изменениями:

```bash
python -m py_compile app_tatneft_g17_g20_diag.py
```

Создай резервные копии:

```text
legacy/app_tatneft_g17_g20_diag.py
legacy/operator_tatneft_style.css
```

Не изменяй файлы в `legacy/`.

---

## 1.1. Цель миграции

Нужно сохранить текущее Dash + Plotly приложение, но:

1. перенести данные из `df2.parquet` и `df_ploshad_year.parquet` в SQL;
2. убрать загрузку и полную нормализацию больших DataFrame из пользовательских callback-ов;
3. добавить L1/L2/L3-кэширование;
4. кэшировать SQL-выборки, агрегаты, периодизацию и выбранные тяжёлые фигуры;
5. исключить повторный расчёт одинаковых результатов;
6. сохранить весь интерфейс и его CSS;
7. обеспечить production-запуск с несколькими worker;
8. сохранить возможность временного запуска от parquet для проверки эквивалентности.

Основная задача — ускорение без изменения пользовательского поведения.

---

## 1.2. Текущая структура приложения, которую необходимо сохранить

### Источники данных

Сейчас приложение загружает:

```python
df2 = pd.read_parquet("df2.parquet")
df_ploshad_year = pd.read_parquet("df_ploshad_year.parquet")
```

Затем выполняет:

```python
df2, dfy = normalize_data(df2, df_ploshad_year)
```

В SQL-режиме приложение не должно выполнять полную `normalize_data()` при старте каждого worker. Нормализацию и создание производных колонок перенеси в ETL/SQL-слой.

### Основные константы

Сохрани смысл:

```python
AREA_COL_YEAR = "kod_ploshchadi"
AREA_COL_MONTH = "ploshad"
WELL_COL = "well_uid" if "well_uid" in df2.columns else "well"
```

В SQL-слое явно зафиксируй соответствие:

```text
monthly_metrics.ploshad             -> area_year_metrics.kod_ploshchadi
monthly_metrics.ngdu                -> area_year_metrics.ngdu
monthly_metrics.year                -> area_year_metrics.year
```

### Текущие пользовательские показатели

Список `YEAR_METRICS`:

```text
dobycha_nefti  — Добыча нефти, т
dobycha_liq    — Добыча жидкости, т
zakachka       — Закачка воды, м³
wc             — Обводнённость, %
dob_fond       — Действующий добывающий фонд
nagn_fond      — Действующий нагнетательный фонд
```

Список режимов `CHANGE_PERIODS`:

```text
prev — к прошлому году
3y   — динамика YoY за 3 года
5y   — динамика YoY за 5 лет
```

Не переименовывай внутренние значения `prev`, `3y`, `5y`.

---

## 1.3. Контракт Dash-компонентов

Сохрани следующие ID. Их изменение допускается только при одновременном обновлении всех callback-ов и автотестов.

### Глобальные фильтры

```text
ngdu-filter
area-filter
reset-filters
scenario-tabs
```

### Заголовок и KPI

```text
dataset-badge
executive-kpi
```

### Динамический контейнер вкладок

```text
scenario-content
```

### Фильтры вкладки «Основные показатели»

```text
main-metric
change-period
```

### Графики вкладки «Основные показатели»

```text
main-bar
main-line
main-change
main-cross
```

### Графики вкладки «Анализ по активу»

```text
g01
g02
g03
g04
g05
g06
g07
g08
g09
g10
g11
g12
g13
g14
g15
g16
g17
g18
g19
g20
g21
g22
```

В текущей реализации компоненты графиков создаются динамически внутри:

```python
dcc.Loading(html.Div(id="scenario-content"), ...)
```

через callback:

```python
render_tab(active_tab)
```

и приложение использует:

```python
suppress_callback_exceptions=True
```

### Важное ограничение по рефакторингу callback-ов

Не разделяй `update_asset()` на множество callback-ов, пока графики остаются динамическими внутри `scenario-content`.

Допустимы два безопасных варианта:

#### Вариант A — минимальный риск

Сохранить:

- динамический `render_tab`;
- единый callback `update_asset`;
- порядок Outputs;
- `suppress_callback_exceptions=True`.

Оптимизацию выполнять внутри service-слоя и кэша.

#### Вариант B — статический layout

Сначала разместить обе вкладки в постоянном layout, а показывать/скрывать их стилями. После этого можно разделять callback-и. Этот вариант разрешён только после интеграционных тестов всех 22 графиков.

По умолчанию используй вариант A.

---

## 1.4. Точная карта callback-ов

Сохрани поведение следующих callback-ов.

### `reset_ngdu_filter`

```text
Input:  reset-filters.n_clicks
Output: ngdu-filter.value
```

В SQL-режиме должен возвращать актуальный список НГДУ из закэшированного справочника, а не глобальный `ALL_NGDU`, сформированный из parquet.

### `sync_area_options_and_tab`

```text
Inputs:
- ngdu-filter.value
- area-filter.value
- reset-filters.n_clicks
- scenario-tabs.active_tab

Outputs:
- area-filter.options
- area-filter.value
- scenario-tabs.active_tab
```

Сохрани текущие правила:

1. список площадей зависит от выбранных НГДУ;
2. при сбросе выбираются все допустимые площади и открывается `tab-main`;
3. при ручном переходе в `tab-asset` должна оставаться ровно одна площадь;
4. при выборе новой площади в `tab-asset` multi-dropdown фактически работает как одиночный;
5. если выбрана ровно одна площадь, допускается автоматическое переключение в `tab-asset`;
6. недоступные после смены НГДУ площади удаляются из `value`.

Список площадей получать через кэшируемый repository-запрос `SELECT DISTINCT`, а не фильтрацией полного DataFrame.

### `update_header`

```text
Inputs:
- ngdu-filter.value
- area-filter.value

Outputs:
- dataset-badge.children
- executive-kpi.children
```

Сохрани четыре KPI:

```text
Добыча нефти
Добыча жидкости
Закачка воды
Обводнённость
```

Сохрани sparkline, индикаторы `led-green`, `led-amber`, `led-red` и расчёт дельты к предыдущему году.

### `render_tab`

```text
Input:  scenario-tabs.active_tab
Output: scenario-content.children
```

Сохрани названия вкладок:

```text
Основные показатели
Анализ по активу
```

### `update_main`

```text
Inputs:
- ngdu-filter.value
- area-filter.value
- main-metric.value
- change-period.value

Outputs:
- main-bar.figure
- main-line.figure
- main-change.figure
- main-cross.figure
```

### `update_asset`

```text
Inputs:
- ngdu-filter.value
- area-filter.value

Outputs:
- g01.figure
- g02.figure
- g03.figure
- g11.figure
- затем все графики из ANALYSIS_SPECS в текущем порядке
```

Порядок возвращаемого списка фигур должен строго совпадать с порядком Outputs.

---

## 1.5. Точная карта графиков

### Вкладка «Основные показатели»

| ID | Функция | Назначение |
|---|---|---|
| `main-bar` | `bar_last_year` | последний год по площадям |
| `main-line` | `line_year_metric` | динамика метрики по годам |
| `main-change` | `change_bar` | изменение показателя |
| `main-cross` | `crossplot_debit_wc` | дебит нефти vs обводнённость |

### Вкладка «Анализ по активу»

| ID | Функция/логика |
|---|---|
| `g01` | `tech_dynamics` |
| `g02` | `fund_dynamics` |
| `g03` | `fund_ratio_dynamics` |
| `g04` | дебит жидкости от КИЗ |
| `g05` | дебит жидкости от степени промывки |
| `g06` | фонд скважин от КИН |
| `g07` | ВНФ накопленный от КИН |
| `g08` | компенсация текущая от КИН |
| `g09` | дебит нефти от КИЗ |
| `g10` | ВНФ накопленный от накопленной добычи нефти |
| `g11` | `pumping_washing_vs_kin` |
| `g12` | темп отбора от НИЗ от КИН |
| `g13` | обводнённость от КИН, с OLS trendline |
| `g14` | дебит нефти от КИН |
| `g15` | дебит нефти от накопленной добычи нефти |
| `g16` | `segmented_wc_kiz` |
| `g17` | `niz_otbor_vs_wc_identity` |
| `g18` | соотношение доб/наг от КИН |
| `g19` | дебит жидкости от степени прокачки |
| `g20` | `ratio_vs_q_by_wc_kiz_periods` |
| `g21` | компенсация текущая от КИН |
| `g22` | КИН от `LN(ВНФ тек.)`, с OLS trendline |

Не менять порядок и заголовки без отдельного требования.

---

## 1.6. Контракт расчётных колонок

### Колонки, приходящие из месячной таблицы

Минимально используются:

```text
date
year
ploshad
ngdu
well_uid или well
debit_neft
debit_liq
debit_vod
priem
wc
```

### Колонки годовой таблицы

Минимально используются:

```text
kod_ploshchadi
year
dobycha_nefti
dobycha_liq
dobycha_vody
zakachka
wc
dob_fond
nagn_fond
kin
niz_otbor
niz_temp
kompens_tek
kompens_nak
gz
niz
```

### Колонки, которые `normalize_data()` создаёт или дополняет

```text
ngdu
wc_month_avg
debit_neft
debit_liq
debit_vod
priem
dobycha_vody_cum
dobycha_nefti_cum
dobycha_liq_cum
zakachka_cum
kiz
vnf_tek
vnf_nak
ratio_dob_nagn
q_priem_q_liq
stepen_prokachki
stepen_promyvki
temp_prokachki
temp_promyvki
```

### Формулы, которые необходимо сохранить

```python
kiz = niz_otbor

vnf_tek = dobycha_vody / dobycha_nefti
vnf_nak = dobycha_vody_cum / dobycha_nefti_cum

ratio_dob_nagn = dob_fond / nagn_fond
q_priem_q_liq = priem / debit_liq

stepen_prokachki = 100 * zakachka_cum / gz
stepen_promyvki = 100 * dobycha_liq_cum / gz

temp_prokachki = 100 * zakachka / gz
temp_promyvki = 100 * dobycha_liq / gz
```

Во всех делениях сохранить поведение `safe_div`:

- знаменатель 0 → `NaN`;
- знаменатель `NaN` → `NaN`;
- не допускать `inf` и `-inf`.

### Дебиты нефти и жидкости

Текущий код рассчитывает средние `debit_neft` и `debit_liq` на одинаковом наборе строк:

```python
df2.dropna(subset=["debit_neft", "debit_liq"])
```

Это обязательное правило. В SQL-агрегации не рассчитывай эти средние независимо по разным наборам `NULL`.

Для PostgreSQL можно использовать `FILTER`, `CASE WHEN` или CTE. Для SQL Server — `CASE WHEN`.

Логика должна гарантировать, что обе средние рассчитаны по строкам, где заполнены одновременно оба значения.

### Связь площадь → НГДУ

Текущий код строит связь так:

```python
df2[[ploshad, ngdu]]
.dropna()
.drop_duplicates()
.groupby(ploshad)["ngdu"]
.first()
```

Это скрытое предположение «одна площадь относится к одному НГДУ».

Перед миграцией:

1. выполни проверку количества НГДУ на одну площадь;
2. сформируй отчёт по конфликтам;
3. если конфликтов нет — создай справочник `dim_area`;
4. если конфликты есть — не используй `.first()` молча, а останови ETL либо согласуй правило.

Рекомендуемая таблица:

```text
dim_area
--------
area_id
kod_ploshchadi
ngdu
valid_from
valid_to
is_current
dataset_version
```

---

## 1.7. Алгоритм периодизации g16/g20

Текущий `compute_wc_kiz_periods()`:

1. использует `year`, `kiz`, `wc`;
2. сортирует по `year`, затем по `kod_ploshchadi`;
3. строит сегменты динамическим программированием;
4. минимизирует сумму SSE линейной модели `wc = a + b * kiz`;
5. по умолчанию использует:
   - `n_periods=6`;
   - `min_size=5`;
6. при наличии `sklearn` использует `LinearRegression`;
7. при отсутствии `sklearn` использует `numpy.linalg.lstsq`;
8. возвращает:
   - DataFrame с периодами;
   - список сегментов;
   - список отсутствующих колонок.

Сейчас этот тяжёлый расчёт вызывается отдельно в:

```text
segmented_wc_kiz
ratio_vs_q_by_wc_kiz_periods
```

В новой реализации:

- выполнить его один раз на комбинацию фильтров;
- закэшировать;
- передать один `PeriodResult` в g16 и g20;
- включить в ключ `n_periods`, `min_size`, dataset version и версию алгоритма;
- не менять математический алгоритм до появления parity-тестов.

Оптимизацию SSE через префиксные суммы разрешается делать только вторым этапом и только после сравнения сегментов со старой реализацией.

---

## 1.8. Особые требования к g16, g17 и g20

### g16

Сохранить:

- диапазоны обеих осей `[0, 100]`;
- диагональ `y = x`;
- зелёную и красную полупрозрачные зоны;
- цвета по периодам;
- вертикальные границы периодов;
- подписи `Граница N`;
- легенду периодов;
- meta:
  - `segmentation_method`;
  - `n_periods`;
  - `min_size`.

### g17

Сохранить:

- отсутствие trendline;
- диагональ `y = x`;
- текущие подписи осей;
- цвет точек по площади.

### g20

Сохранить:

- окраску точек по тем же периодам, что и g16;
- отсутствие trendline;
- диагональ `y = x`;
- начало осей X и Y с 0;
- легенду периодов.

---

## 1.9. Видимые подписи над столбцами

Речь идёт о тексте над столбцами, а не hover.

Обязательно проверить:

1. `main-change` в режимах `prev`, `3y`, `5y`;
2. нижнюю гистограмму `Δ нефти YoY` внутри `g01`.

Не полагайся только на:

```python
texttemplate="%{y:+.1f}%"
```

Для надёжного результата создай общий helper:

```python
def format_visible_pct_label(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return f"{float(value):+.1f}%"
```

Передавай в `go.Bar` или в trace готовый строковый массив:

```python
text=[format_visible_pct_label(v) for v in values]
texttemplate="%{text}"
```

Тест должен проверять именно `trace.text` в figure JSON:

```text
+12.3%
-4.8%
0.0%
```

а не только `texttemplate`.

Не изменяй числовой `y` ради форматирования текста. Округление подписи не должно менять высоту столбца.

---

## 1.10. Известные точки потери производительности в текущем Python-файле

Codex должен зафиксировать baseline и устранить следующие причины:

1. `df2.parquet` и `df_ploshad_year.parquet` читаются целиком при старте каждого worker.
2. `normalize_data()` выполняет merge, groupby и cumulative calculations в Python.
3. `filter_year_data()` делает `dfy.copy()` при каждом callback.
4. `sync_area_options_and_tab()` делает ещё один `dfy.copy()`.
5. `update_header`, `update_main` и `update_asset` отдельно фильтруют один набор данных.
6. `tech_dynamics`, `fund_dynamics`, `fund_ratio_dynamics` повторяют агрегации по `year`.
7. `compute_wc_kiz_periods()` вызывается отдельно для g16 и g20.
8. `update_asset()` строит более 20 Plotly-фигур при каждом изменении фильтра.
9. готовые фигуры сериализуются повторно;
10. приложение запускается с `debug=True`;
11. host `10.241.112.254` и port `8048` жёстко заданы;
12. импорт `ruptures` в текущем файле не используется;
13. `LAST_YEAR` и `WELL_COL` требуют проверки фактического использования;
14. глобальные `ALL_NGDU` и `ALL_AREAS` формируются только при старте и не учитывают обновление SQL-версии данных.

Устраняй эти проблемы без изменения пользовательского результата.

---

## 1.11. CSS и визуальный контракт

Файл `operator_tatneft_style.css` является обязательной частью приложения.

Размести его так:

```text
assets/operator_tatneft_style.css
```

Dash должен автоматически загрузить этот файл. Дополнительно можно явно указать:

```python
app = Dash(
    __name__,
    assets_folder="assets",
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
)
```

Не встраивай весь CSS строкой в Python.

### Критические CSS-классы

Не переименовывай без одновременного обновления layout:

```text
shell
topbar
brand-title
accent
brand-subtitle
dataset-badge
live-dot
control-panel
btn-reset
metric-card
metric-title
metric-value
metric-unit
metric-delta
delta-up
delta-down
delta-flat
status-led
led-green
led-amber
led-red
panel-card
section-caption
dash-chart
compact-chart
```

### Сохраняемые визуальные свойства

Сохранить:

- зелёную палитру Татнефть;
- CSS variables `--op-*`;
- sticky topbar;
- левую зелёную полосу;
- карточки без скругления;
- границы и тени;
- KPI LED-индикаторы;
- pulse-анимацию с `prefers-reduced-motion`;
- стили Bootstrap tabs;
- адаптивность на 1200 px и 720 px;
- минимальные высоты графиков;
- видимый overflow карточек, необходимый для подписей над столбцами.

Особенно не менять:

```css
.panel-card {
  overflow: visible;
}
```

Иначе подписи `textposition="outside"` могут обрезаться.

### React Select

CSS использует селекторы:

```text
.Select-control
.Select--multi
.Select-value
.Select-menu-outer
.VirtualizedSelectOption
.VirtualizedSelectFocusedOption
```

При обновлении Dash/dcc версия React Select может изменить DOM-классы. Поэтому:

- зафиксируй версии Dash и `dash-bootstrap-components`;
- добавь визуальный smoke-test dropdown;
- не считать миграцию завершённой, пока стили dropdown не проверены в браузере.

### Montserrat

Текущий `index_string` подключает Montserrat через Google Fonts и содержит preconnect.

Сохрани подключение либо используй системные fallback:

```text
"Montserrat", "Segoe UI", Arial, sans-serif
```

Не добавляй в репозиторий сторонние файлы шрифтов без проверки лицензии и корпоративной политики.

### Производительность CSS

Не удаляй стили ради ускорения без измерений. Основная задержка текущего приложения возникает в Python/SQL/Plotly, а не в тенях или градиентах.

---

## 1.12. Текущий Plotly-контракт

Сохрани шаблон:

```text
tatneft_light
```

Сохрани:

- `PALETTE`;
- `HEAT_SCALE`;
- цвета `TN_*`;
- шрифты;
- фон;
- оси;
- легенды;
- hoverlabel;
- `apply_theme`;
- `empty_fig`;
- размеры 440 px, 560 px и 650 px;
- `responsive=True`;
- `displayModeBar=False`.

Не кэшируй объект `go.Figure` через pickle. Кэшируй только:

```python
fig.to_plotly_json()
```

При возврате из кэша Dash может принимать dict.

---

## 1.13. Обязательная стратегия миграции именно для текущего приложения

### Шаг 1 — parity до рефакторинга UI

Сначала:

- перенеси данные в SQL;
- добавь repository;
- добавь кэш;
- сохрани существующие layout-функции и callback-и;
- замени только получение данных.

Не разделяй layout и callback-и на первом этапе.

### Шаг 2 — кэш общих данных

Для одного изменения фильтров `update_header`, `update_main` и `update_asset` должны получать одинаковую SQL-выборку из общего L2-кэша.

### Шаг 3 — кэш агрегатов

Отдельно кэшировать:

```text
header_year_aggregate
main_metric_area_year
asset_year_aggregate
wc_kiz_periods
```

### Шаг 4 — фигуры

После замеров кэшировать:

```text
g01
g16
g20
main-change
```

### Шаг 5 — optional callback refactor

Только после прохождения browser smoke-tests можно:

- сделать статические вкладки;
- разделить `update_asset`;
- добавить ленивую загрузку.

---

## 1.14. SQL-таблицы, адаптированные под текущий код

Помимо общих таблиц из последующих разделов, реализуй следующую схему.

### `dim_area`

```text
area_id
kod_ploshchadi
ngdu
dataset_version
valid_from
valid_to
is_current
```

### `monthly_metrics`

```text
date
year
ngdu
ploshad
well_uid
debit_neft
debit_liq
debit_vod
priem
wc
dataset_version
loaded_at
```

Если исходник использует `well` вместо `well_uid`, ETL должен привести его к `well_uid`.

### `area_year_metrics`

```text
ngdu
kod_ploshchadi
year

dobycha_nefti
dobycha_liq
dobycha_vody
zakachka
wc

dob_fond
nagn_fond
kin
niz_otbor
niz_temp
kompens_tek
kompens_nak
gz
niz

wc_month_avg
debit_neft
debit_liq
debit_vod
priem

dobycha_vody_cum
dobycha_nefti_cum
dobycha_liq_cum
zakachka_cum

kiz
vnf_tek
vnf_nak
ratio_dob_nagn
q_priem_q_liq
stepen_prokachki
stepen_promyvki
temp_prokachki
temp_promyvki

dataset_version
loaded_at
```

Рекомендуемый уникальный ключ:

```text
(dataset_version, ngdu, kod_ploshchadi, year)
```

Если проверка данных подтверждает, что площадь уникально принадлежит одному НГДУ, допустим:

```text
(dataset_version, kod_ploshchadi, year)
```

---

## 1.15. Тестовая матрица интерфейса

После каждого этапа автоматически или вручную проверить:

### Фильтры

- загрузка всех НГДУ;
- зависимый список площадей;
- сброс;
- переход `tab-main` → `tab-asset`;
- одиночный выбор площади на `tab-asset`;
- возврат на `tab-main`;
- persistence dropdown.

### Основная вкладка

Для каждого `YEAR_METRICS`:

- `main-bar`;
- `main-line`;
- `main-change` в `prev`;
- `main-change` в `3y`;
- `main-change` в `5y`;
- `main-cross`.

### Анализ по активу

Проверить наличие figure для каждого ID `g01`–`g22`, включая `g11`.

Проверить:

- g13 и g22 имеют trendline;
- g17 не имеет trendline и имеет `y=x`;
- g16 имеет периоды и границы;
- g20 использует те же периоды;
- g20 начинается с 0;
- g01 содержит обе строки subplot и `Δ нефти YoY`.

### CSS

Проверить:

- CSS-файл отвечает HTTP 200;
- topbar sticky;
- цвета CSS variables применены;
- dropdown стилизован;
- карточки имеют верхнюю/левую зелёную полосу;
- подписи над столбцами не обрезаются;
- mobile media query не ломает layout.

---

## 1.16. Критерии эквивалентности SQL и parquet

Для одинаковых фильтров сравнить:

```text
число строк
min/max year
список ngdu
список площадей
dobycha_nefti
dobycha_liq
dobycha_vody
zakachka
wc
debit_neft
debit_liq
debit_vod
priem
dob_fond
nagn_fond
kin
kiz
vnf_tek
vnf_nak
ratio_dob_nagn
q_priem_q_liq
```

Проверить как минимум:

```text
все данные
одно НГДУ
одна площадь
несколько площадей
площадь с пропусками
ранние годы
последние 5 лет
```

Для float использовать согласованный tolerance:

```python
rtol=1e-9
atol=1e-9
```

Если SQL использует фиксированную decimal-точность, tolerance документировать.

---

## 2. Главные ограничения

### Обязательно

- Оставить Dash и Plotly.
- Использовать SQLAlchemy 2.x.
- Поддержать PostgreSQL и Microsoft SQL Server через `DATABASE_URL`.
- Использовать Redis как общий кэш между процессами приложения.
- Использовать локальный in-process TTL-кэш как первый уровень.
- Не хранить большие DataFrame в `dcc.Store`.
- Не создавать SQL Engine внутри callback.
- Не создавать Redis-клиент внутри callback.
- Не выполнять `normalize_data()` при каждом запуске callback.
- Не выполнять тяжёлое определение периодов отдельно для g16 и g20.
- Не строить повторно одинаковую фигуру при тех же фильтрах и версии данных.
- Использовать только параметризованные SQL-запросы.
- Все секреты получать из переменных окружения.
- `debug=False` в production.
- Добавить тесты и измерение времени выполнения.

### Не делать

- Не использовать глобальный mutable DataFrame, который изменяется callback-ами.
- Не передавать весь набор данных в браузер.
- Не использовать `cache.clear()` как основной механизм инвалидации.
- Не использовать небезопасное формирование SQL через конкатенацию пользовательских значений.
- Не кэшировать результаты без учёта версии данных.
- Не менять расчётные формулы без отдельного документированного обоснования.
- Не заменять Plotly на другой графический движок в рамках этой задачи.

---

## 3. Целевая архитектура

```text
Исходные parquet / ETL-источник
              │
              ▼
       SQL staging tables
              │
              ▼
  monthly_metrics / area_year_metrics
              │
              ▼
 dashboard_metadata.dataset_version
              │
              ▼
       SQLAlchemy repository
              │
              ▼
   L1 cache: process-local TTLCache
              │
              ▼
      L2 cache: shared Redis
              │
              ▼
 Data service / aggregation service
              │
              ▼
 Period segmentation service
              │
              ▼
 Figure service / cached Plotly JSON
              │
              ▼
          Dash callbacks
              │
              ▼
            Browser
```

Многоуровневое кэширование должно включать:

1. **L1 — in-process TTL cache**
   - короткий TTL;
   - небольшой размер;
   - только самые горячие небольшие результаты;
   - отдельный кэш у каждого worker.

2. **L2 — Redis shared cache**
   - общий для всех worker;
   - кэш SQL-выборок, агрегатов и периодов;
   - TTL от 15 минут до нескольких часов в зависимости от типа данных.

3. **L3 — кэш подготовленных Plotly-фигур**
   - только для тяжёлых и часто повторяемых графиков;
   - хранить `figure.to_plotly_json()`, а не объект Figure;
   - обязательно учитывать фильтры, версию данных и версию функции построения.

4. **Версионирование данных**
   - ключи кэша должны включать `dataset_version`;
   - после обновления SQL старая версия кэша автоматически перестаёт использоваться.

---

## 4. Предлагаемая структура проекта

Сохрани исходные файлы в `legacy/`, а рабочий проект организуй так:

```text
project/
├── app.py
├── config.py
├── db.py
├── cache_backend.py
├── requirements.txt
├── .env.example
├── README.md
├── docker-compose.yml
├── assets/
│   └── operator_tatneft_style.css
├── legacy/
│   ├── app_tatneft_g17_g20_diag.py
│   └── operator_tatneft_style.css
├── sql/
│   ├── 001_create_tables.sql
│   ├── 002_create_indexes.sql
│   ├── 003_create_views.sql
│   └── 004_seed_metadata.sql
├── scripts/
│   ├── migrate_parquet_to_sql.py
│   ├── compare_parquet_sql.py
│   ├── refresh_aggregates.py
│   └── clear_old_cache.py
├── repositories/
│   ├── __init__.py
│   └── metrics_repository.py
├── services/
│   ├── __init__.py
│   ├── data_service.py
│   ├── aggregation_service.py
│   ├── periods_service.py
│   └── figure_service.py
├── figures/
│   ├── __init__.py
│   ├── common.py
│   ├── main_figures.py
│   └── asset_figures.py
├── callbacks/
│   ├── __init__.py
│   ├── filters.py
│   ├── header.py
│   ├── main_tab.py
│   └── asset_tab.py
└── tests/
    ├── test_cache_keys.py
    ├── test_repository.py
    ├── test_parquet_sql_parity.py
    ├── test_periods_cache.py
    ├── test_visible_bar_labels.py
    ├── test_figures.py
    ├── test_callbacks.py
    └── test_assets.py
```

На первом этапе допускается оставить layout, callbacks и figures в `app.py`, если это уменьшает риск поломки динамического layout. Выносить их по модулям нужно постепенно, с тестами после каждого шага.

Обязательные правила:

- `assets/operator_tatneft_style.css` должен совпадать с исходным CSS, кроме документированных исправлений;
- `app.py` должен экспортировать `app` и `server = app.server`;
- `legacy/` не импортируется production-кодом;
- SQL, кэш и ETL не должны зависеть от Dash UI;
- функции фигур не должны самостоятельно обращаться в SQL или Redis.

---

## 5. Зависимости

Обнови `requirements.txt`:

```text
dash
dash-bootstrap-components
plotly
pandas
numpy
sqlalchemy>=2.0
flask-caching
redis
cachetools
orjson
pyarrow
python-dotenv
gunicorn; platform_system != "Windows"
waitress; platform_system == "Windows"
psycopg[binary]; platform_system != "Windows"
pyodbc
scikit-learn
pytest
pytest-mock
```

Не подключай одновременно ненужные SQL-драйверы в production-окружении. В README опиши отдельные варианты установки для PostgreSQL и SQL Server.

---

## 6. Конфигурация через переменные окружения

Создай `.env.example`:

```dotenv
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8048
APP_DEBUG=false

# PostgreSQL example:
# DATABASE_URL=postgresql+psycopg://dashboard_user:password@localhost:5432/dashboard

# SQL Server example:
# DATABASE_URL=mssql+pyodbc://dashboard_user:password@server/database?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes

DATABASE_URL=

REDIS_URL=redis://localhost:6379/0
CACHE_KEY_PREFIX=tatneft_dashboard
CACHE_DEFAULT_TTL=3600
CACHE_DATA_TTL=3600
CACHE_AGG_TTL=3600
CACHE_PERIODS_TTL=21600
CACHE_FIGURE_TTL=1800

DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_RECYCLE=1800
DB_POOL_TIMEOUT=30

LOCAL_CACHE_TTL=60
LOCAL_CACHE_MAXSIZE=128

LOG_LEVEL=INFO
```

Создай `config.py` с dataclass или Pydantic-подобной конфигурацией без добавления тяжёлой зависимости.

Требования:

- проверить обязательность `DATABASE_URL`;
- предоставить безопасные значения по умолчанию;
- не логировать пароли;
- поддерживать отдельные TTL;
- хранить `CODE_CACHE_VERSION`, например:

```python
CODE_CACHE_VERSION = "dashboard-cache-v1"
```

Эта версия должна меняться при изменении логики расчётов или фигур.

---

## 7. SQL-модель данных

### 7.1. Таблица метаданных

Создай таблицу:

```sql
CREATE TABLE dashboard_metadata (
    dataset_name VARCHAR(100) PRIMARY KEY,
    dataset_version VARCHAR(100) NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    row_count BIGINT NULL,
    description VARCHAR(500) NULL
);
```

Для SQL Server адаптируй типы времени при необходимости.

Используй строку:

```text
dataset_name = 'area_metrics'
```

`dataset_version` должен обновляться только после успешной полной загрузки данных.

Пример версии:

```text
2026-06-15T18:30:00Z
```

или UUID.

### 7.2. Месячная таблица

Создай `monthly_metrics`. Состав полей должен соответствовать фактическим данным `df2`.

Минимально нужны:

```text
date
year
ngdu
ploshad
well_uid
debit_neft
debit_liq
debit_vod
priem
wc
```

Также перенеси все поля, которые используются в действующем приложении или могут понадобиться для повторной агрегации.

Добавь технические поля:

```text
loaded_at
source_file
dataset_version
```

Уникальный ключ определить после анализа фактической гранулярности. Предпочтительно:

```text
(date, ploshad, well_uid)
```

но не создавать ограничение, пока не проверено отсутствие легитимных дублей.

### 7.3. Годовая таблица

Создай `area_year_metrics`.

Основной ключ:

```text
(kod_ploshchadi, year)
```

Если одна площадь может относиться к нескольким НГДУ в одном году, используй:

```text
(ngdu, kod_ploshchadi, year)
```

Поля должны включать все показатели, используемые приложением:

```text
ngdu
kod_ploshchadi
year
dobycha_nefti
dobycha_liq
dobycha_vody
zakachka
wc
wc_month_avg
debit_neft
debit_liq
debit_vod
priem
dob_fond
nagn_fond
kin
kiz
niz_otbor
niz_temp
kompens_tek
kompens_nak
gz
niz
dobycha_vody_cum
dobycha_nefti_cum
dobycha_liq_cum
zakachka_cum
vnf_tek
vnf_nak
ratio_dob_nagn
q_priem_q_liq
stepen_prokachki
stepen_promyvki
temp_prokachki
temp_promyvki
dataset_version
loaded_at
```

Числовые поля хранить с типами, достаточными для точности расчётов. Не использовать `FLOAT` для значений, где критична фиксированная точность, без явного обоснования.

---

## 8. SQL-индексы

Добавь индексы:

```sql
CREATE INDEX ix_area_year_ngdu
    ON area_year_metrics (ngdu);

CREATE INDEX ix_area_year_area
    ON area_year_metrics (kod_ploshchadi);

CREATE INDEX ix_area_year_year
    ON area_year_metrics (year);

CREATE INDEX ix_area_year_area_year
    ON area_year_metrics (kod_ploshchadi, year);

CREATE INDEX ix_area_year_ngdu_area_year
    ON area_year_metrics (ngdu, kod_ploshchadi, year);
```

Для `monthly_metrics`:

```sql
CREATE INDEX ix_monthly_area_date
    ON monthly_metrics (ploshad, date);

CREATE INDEX ix_monthly_ngdu_area_date
    ON monthly_metrics (ngdu, ploshad, date);
```

После создания таблиц проверь планы выполнения для типовых запросов.

Не создавай чрезмерное количество индексов без замеров: индексы ускоряют чтение, но замедляют загрузку данных.

---

## 9. Скрипт миграции parquet → SQL

Создай `scripts/migrate_parquet_to_sql.py`.

Скрипт должен:

1. Принять пути к `df2.parquet` и `df_ploshad_year.parquet`.
2. Прочитать данные.
3. Применить текущую нормализацию только один раз вне Dash.
4. Проверить типы.
5. Проверить обязательные столбцы.
6. Проверить дубли.
7. Рассчитать производные показатели.
8. Записать данные во временные staging-таблицы.
9. Проверить количество строк и контрольные суммы.
10. В транзакции заменить production-данные.
11. Обновить `dashboard_metadata.dataset_version`.
12. После успешной загрузки вывести отчёт.

CLI:

```bash
python -m scripts.migrate_parquet_to_sql \
  --monthly df2.parquet \
  --yearly df_ploshad_year.parquet \
  --dataset-version 2026-06-15-v1
```

Добавь `--dry-run`.

При ошибке production-таблицы и `dataset_version` не должны меняться.

---

## 10. SQLAlchemy Engine

Создай `db.py`.

Engine создаётся ровно один раз при импорте приложения:

```python
from sqlalchemy import create_engine

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle,
    pool_timeout=settings.db_pool_timeout,
    future=True,
)
```

Для SQLite в тестах параметры пула могут отличаться.

Создай функцию проверки:

```python
def check_database_connection() -> bool:
    ...
```

Создай контекстный helper:

```python
def connection_scope():
    ...
```

Не держи соединение открытым дольше выполнения конкретного запроса.

---

## 11. Repository-слой

Создай `repositories/metrics_repository.py`.

Он должен содержать только SQL-доступ и не строить фигуры.

Минимальные функции:

```python
get_dataset_version() -> str

get_all_ngdu(dataset_version: str) -> list[str]

get_areas_for_ngdu(
    selected_ngdu: tuple[str, ...],
    dataset_version: str,
) -> list[str]

load_year_metrics(
    selected_ngdu: tuple[str, ...],
    selected_areas: tuple[str, ...],
    dataset_version: str,
) -> pd.DataFrame
```

Используй SQLAlchemy Core и параметризованные условия.

Рекомендуемый подход:

```python
stmt = select(area_year_metrics)

if selected_ngdu:
    stmt = stmt.where(area_year_metrics.c.ngdu.in_(selected_ngdu))

if selected_areas:
    stmt = stmt.where(
        area_year_metrics.c.kod_ploshchadi.in_(selected_areas)
    )

stmt = stmt.where(
    area_year_metrics.c.dataset_version == dataset_version
).order_by(
    area_year_metrics.c.kod_ploshchadi,
    area_year_metrics.c.year,
)
```

Выбирай только реально используемые столбцы, а не `SELECT *`.

Добавь логирование длительности SQL-запроса.

---

## 12. Нормализация фильтров

Кэш-ключ не должен зависеть от порядка выбора элементов.

Создай:

```python
def normalize_filter_values(values) -> tuple[str, ...]:
    if not values:
        return tuple()
    return tuple(sorted({str(value) for value in values}))
```

Для площади сохрани исходный тип, если он числовой. Главное — единое детерминированное представление.

Все callback-и перед вызовом service-слоя должны нормализовать фильтры.

---

## 13. Генерация ключей кэша

Создай `cache_backend.py`.

Ключ должен включать:

- префикс приложения;
- тип объекта;
- `dataset_version`;
- `CODE_CACHE_VERSION`;
- нормализованные фильтры;
- параметры функции;
- версию конкретного расчёта при необходимости.

Пример:

```python
import hashlib
import json

def build_cache_key(namespace: str, payload: dict) -> str:
    normalized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{settings.cache_key_prefix}:{namespace}:{digest}"
```

---

## 14. L1 in-process cache

Используй `cachetools.TTLCache`.

```python
from cachetools import TTLCache
from threading import RLock

local_cache = TTLCache(
    maxsize=settings.local_cache_maxsize,
    ttl=settings.local_cache_ttl,
)
local_cache_lock = RLock()
```

Кэшировать в L1:

- `dataset_version` на 15–60 секунд;
- список НГДУ;
- список площадей для НГДУ;
- небольшие годовые агрегаты;
- готовые JSON-фигуры только при небольшом размере.

Не хранить в L1 очень большие DataFrame в большом количестве.

---

## 15. L2 Redis cache

Создай единый Redis-клиент:

```python
from redis import Redis

redis_client = Redis.from_url(
    settings.redis_url,
    decode_responses=False,
    socket_connect_timeout=3,
    socket_timeout=5,
    health_check_interval=30,
)
```

Если Redis временно недоступен:

- приложение не должно падать;
- выполнить SQL/расчёт напрямую;
- записать warning в лог;
- L1 продолжает работать.

---

## 16. Сериализация DataFrame

Не сохраняй DataFrame в Redis как JSON.

Используй Parquet bytes через `pyarrow`:

```python
from io import BytesIO

def dataframe_to_bytes(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    df.to_parquet(buffer, index=False, engine="pyarrow")
    return buffer.getvalue()

def dataframe_from_bytes(data: bytes) -> pd.DataFrame:
    return pd.read_parquet(BytesIO(data), engine="pyarrow")
```

Для небольших структур используй `orjson`.

Для Plotly-фигур сохраняй `figure.to_plotly_json()`.

---

## 17. Универсальный cache-aside helper

Реализуй:

```python
def get_or_compute(
    *,
    key: str,
    ttl: int,
    loader,
    serializer,
    deserializer,
    use_local_cache: bool = True,
):
    ...
```

Алгоритм:

1. Проверить L1.
2. Если miss — проверить Redis.
3. Если Redis hit — десериализовать, положить в L1, вернуть.
4. Если miss — выполнить `loader()`.
5. Сериализовать результат.
6. Записать в Redis.
7. Положить в L1.
8. Вернуть результат.

Логировать cache level, hit/miss, elapsed time и payload size.

---

## 18. Защита от cache stampede

Для тяжёлых ключей используй Redis-lock:

```python
with redis_client.lock(
    f"{key}:lock",
    timeout=120,
    blocking_timeout=10,
):
    # повторно проверить Redis после получения lock
    # затем выполнить расчёт
```

Применить минимум к:

- расчёту периодов разработки;
- построению тяжёлых фигур g16/g20;
- большим SQL-агрегатам.

---

## 19. Data service

Создай `services/data_service.py`.

Функции:

```python
get_dataset_version_cached() -> str
get_ngdu_options() -> list[str]
get_area_options(selected_ngdu: tuple[str, ...]) -> list[str]
get_filtered_year_data(
    selected_ngdu: tuple[str, ...],
    selected_areas: tuple[str, ...],
) -> pd.DataFrame
```

`get_filtered_year_data()` должен получать dataset version, строить cache key, проверять L1/L2 и только при miss обращаться в repository.

Запрети изменять возвращённый кэшированный DataFrame inplace.

---

## 20. Кэш агрегатов

Создай `services/aggregation_service.py`.

Один раз на комбинацию фильтров рассчитывать `aggregate_asset_year(d)`.

Возвращаемый DataFrame должен содержать всё, что нужно g01, g02, g03 и KPI.

Не выполнять отдельные одинаковые `groupby("year")` в разных функциях графиков.

---

## 21. Кэш периодов разработки

Создай `services/periods_service.py`.

Публичная функция:

```python
get_wc_kiz_periods(
    selected_ngdu: tuple[str, ...],
    selected_areas: tuple[str, ...],
    n_periods: int = 6,
    min_size: int = 5,
) -> PeriodResult
```

`PeriodResult` оформить dataclass:

```python
@dataclass(frozen=True)
class PeriodResult:
    data: pd.DataFrame
    segments: tuple[tuple[int, int], ...]
    missing_columns: tuple[str, ...]
```

Требования:

- `compute_wc_kiz_periods()` вызывается только при cache miss;
- g16 и g20 используют один `PeriodResult`;
- key включает `n_periods`, `min_size`, dataset version и code version;
- использовать Redis lock;
- не выполнять расчёт дважды внутри одного callback.

---

## 22. Кэш фигур

Создай `services/figure_service.py`.

Сначала кэшировать:

- g01;
- g16;
- g20;
- «Изменение показателя»;
- при необходимости `Δ нефти YoY` как часть g01.

Кэшировать JSON:

```python
fig.to_plotly_json()
```

Публичная функция:

```python
get_cached_figure(
    figure_name: str,
    selected_ngdu: tuple[str, ...],
    selected_areas: tuple[str, ...],
    params: dict,
) -> dict
```

Ключ должен учитывать figure name, dataset version, code version, filters, metric, period и параметры периодизации.

Не кэшировать фигуру, если её JSON превышает заданный лимит, например 5–10 MB.

---

## 23. Изменение callback-ов

Один callback не должен:

- несколько раз читать SQL;
- повторно фильтровать одинаковый DataFrame;
- повторно рассчитывать один и тот же агрегат;
- повторно рассчитывать периоды.

Пример:

```python
@app.callback(
    [...outputs...],
    Input("ngdu-filter", "value"),
    Input("area-filter", "value"),
)
def update_asset(selected_ngdu, selected_areas):
    ngdu_key = normalize_filter_values(selected_ngdu)
    area_key = normalize_filter_values(selected_areas)

    d = data_service.get_filtered_year_data(ngdu_key, area_key)
    yearly_agg = aggregation_service.get_asset_year_aggregate(
        ngdu_key,
        area_key,
    )
    periods = periods_service.get_wc_kiz_periods(
        ngdu_key,
        area_key,
        n_periods=6,
        min_size=5,
    )

    # g16 и g20 используют periods
    # g01, g02 и g03 используют yearly_agg
    # остальные используют d
```

Сохрани защиту каждого графика от падения через `safe_build`, но логируй stack trace и имя графика.

---

## 24. `dcc.Store`

Разрешено хранить только:

- dataset version;
- нормализованный ключ фильтров;
- короткий cache token;
- UI-state.

Не хранить:

- полный DataFrame;
- все точки графиков;
- JSON всех фигур;
- результат периодизации на тысячи строк.

---

## 25. Работа с Plotly

Для scatter-графиков с большим количеством точек использовать `render_mode="webgl"`, но отдельно проверить графики с trendline.

Уменьшить размер figure JSON:

- не передавать ненужные колонки в `customdata`;
- не передавать длинные тексты;
- не дублировать данные;
- отключить лишние hover-поля;
- не добавлять тысячи annotations.

Установить `orjson`.

---

## 26. Инвалидация кэша

Основной механизм — версия данных.

После успешного ETL:

1. загрузить новые строки;
2. проверить данные;
3. обновить `dataset_version`;
4. commit;
5. приложение начинает использовать новые ключи.

Старые ключи остаются до TTL и больше не читаются.

Создай `scripts/clear_old_cache.py` для удаления ключей старых версий по prefix.

---

## 27. Обновление данных

Добавь `scripts/refresh_aggregates.py`.

Он должен:

- загрузить новые месячные данные;
- пересчитать только затронутые площади/годы, если это возможно;
- обновить годовую таблицу;
- проверить агрегаты;
- создать новую dataset version;
- обновить metadata в одной транзакции.

Если incremental update слишком сложен для первой версии, реализуй staging + swap.

---

## 28. Логирование и профилирование

Для каждого callback логировать:

```text
callback_name
dataset_version
ngdu_count
area_count
db_ms
l1_hit
redis_hit
aggregation_ms
periods_ms
figures_ms
serialization_ms
total_ms
```

Добавь `/health` и `/ready`.

`/ready` проверяет SQL, Redis и наличие dataset version.

---

## 29. Production-запуск

### Linux

```bash
gunicorn app:server \
  --bind 0.0.0.0:8048 \
  --workers 4 \
  --threads 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
```

В `app.py` экспортировать:

```python
server = app.server
```

### Windows

```bash
waitress-serve \
  --host=0.0.0.0 \
  --port=8048 \
  app:server
```

В production использовать `debug=False`.

---

## 30. Docker Compose для разработки

Создай `docker-compose.yml` минимум с Redis и PostgreSQL:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: dashboard
      POSTGRES_USER: dashboard
      POSTGRES_PASSWORD: dashboard
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7
    ports:
      - "6379:6379"
    command: ["redis-server", "--appendonly", "yes"]

volumes:
  postgres_data:
```

---

## 31. Тесты

Покрыть тестами:

### Ключи кэша

- порядок НГДУ не влияет на ключ;
- порядок площадей не влияет на ключ;
- изменение dataset version меняет ключ;
- изменение code version меняет ключ;
- изменение `n_periods` меняет ключ.

### Repository

- SQL параметризован;
- фильтры применяются корректно;
- пустой фильтр не создаёт `IN ()`;
- возвращаются только нужные столбцы;
- сортировка стабильна.

### Cache hit

- первый вызов обращается в SQL;
- второй вызов с теми же параметрами не обращается в SQL;
- при Redis hit результат возвращается без SQL;
- при недоступном Redis работает fallback;
- после смены dataset version выполняется новый SQL-запрос.

### Периоды

- g16 и g20 получают один и тот же результат;
- `compute_wc_kiz_periods()` вызывается один раз на cache miss;
- повторный вызов не пересчитывает периоды;
- изменение `min_size` создаёт другой ключ.

### Фигуры

- возвращается Plotly-compatible dict;
- текущие названия trace сохранены;
- оси и диапазоны g17/g20 сохранены;
- у g20 оси начинаются с 0;
- видимые подписи над столбцами округляются до 1 знака;
- hover не влияет на visible labels;
- пустые данные возвращают `empty_fig`.

### Callback-и

- один callback не выполняет повторный SQL;
- все Output получают значение;
- исключение одного графика не ломает остальные;
- переключение вкладок не сбрасывает фильтры.

---

## 32. Замеры производительности

До изменений зафиксировать baseline:

```text
startup time
first page load
cold filter request
warm filter request
g16 calculation time
g20 calculation time
figure JSON size
SQL query count per callback
memory per worker
```

После изменений повторить замеры.

Минимальные критерии:

- повторный запрос с теми же фильтрами не выполняет SQL;
- повторный запрос g16/g20 не выполняет периодизацию;
- g16 и g20 используют один результат;
- warm response минимум в 3 раза быстрее cold response либо укладывается в согласованный SLA;
- Redis-кэш общий между worker;
- при отключённом Redis приложение остаётся функциональным;
- после смены dataset version старый результат не отображается.

---

## 33. План реализации по этапам

### Этап 1. Анализ

1. Найди все используемые столбцы.
2. Найди все повторяющиеся `groupby`.
3. Найди все места загрузки parquet.
4. Найди все функции, изменяющие DataFrame inplace.
5. Найди самые тяжёлые графики и расчёты.
6. Зафиксируй baseline.

### Этап 2. SQL

1. Создай DDL.
2. Создай migration script.
3. Перенеси parquet в staging.
4. Проверь данные.
5. Создай production-таблицы.
6. Создай индексы.
7. Создай metadata/version.

### Этап 3. Repository

1. Добавь SQLAlchemy Engine.
2. Реализуй repository.
3. Замени чтение parquet на repository.
4. Сохрани fallback на parquet только за feature flag.

### Этап 4. Кэш данных

1. Реализуй L1.
2. Подключи Redis.
3. Реализуй cache-aside.
4. Кэшируй dataset version, options и filtered data.
5. Добавь versioned keys.

### Этап 5. Кэш расчётов

1. Кэшируй годовой агрегат.
2. Кэшируй периоды.
3. Убери повторные groupby.
4. Передавай один PeriodResult в g16/g20.

### Этап 6. Кэш фигур

1. Измерь время и размер JSON.
2. Выбери тяжёлые фигуры.
3. Кэшируй их по отдельности.
4. Не кэшируй маленькие фигуры без необходимости.

### Этап 7. Production

1. Добавь health checks.
2. Добавь логирование.
3. Добавь тесты.
4. Отключи debug.
5. Настрой Gunicorn/Waitress.
6. Проверь несколько worker.
7. Обнови README.

---

## 34. Обратная совместимость

До завершения миграции добавь feature flag:

```dotenv
DATA_SOURCE=sql
```

Поддерживаемые значения:

```text
sql
parquet
```

При `DATA_SOURCE=parquet` приложение может использовать прежнюю загрузку для сравнения, но этот режим не должен быть production-default.

Добавь тест, сравнивающий ключевые агрегаты SQL и parquet.

---

## 35. Безопасность

- Создать отдельного SQL-пользователя только с правами `SELECT` для Dash.
- Права записи нужны только ETL-скрипту.
- Не хранить пароль в коде.
- Не выводить DATABASE_URL полностью в лог.
- Не принимать произвольный SQL от пользователя.
- Ограничить размер Redis-кэша.
- Настроить TTL.
- Redis не выставлять напрямую в публичную сеть.
- Настроить firewall и аутентификацию Redis в production.

---

## 35.1. Дополнительные критерии готовности для двух исходных файлов

Помимо общих критериев, обязательно:

- `operator_tatneft_style.css` находится в `assets/`;
- все CSS-классы из текущего layout сохранены;
- `panel-card` сохраняет `overflow: visible`;
- `app.index_string` сохраняет meta/css/scripts placeholders;
- Bootstrap остаётся подключён;
- Montserrat или корректный fallback отображается;
- динамический `scenario-content` работает без отсутствующих Output;
- все `g01`–`g22` отображаются;
- число Outputs `update_asset` равно числу возвращаемых фигур;
- `compute_wc_kiz_periods()` не вызывается два раза для g16/g20;
- `main-change` и `Δ нефти YoY` имеют готовые строки в `trace.text` с одним знаком после запятой;
- SQL-режим и parquet-режим дают одинаковые контрольные показатели;
- первый cold-запрос логируется как cache miss;
- повторный запрос с теми же фильтрами логируется как Redis/L1 hit;
- смена `dataset_version` исключает использование старых результатов;
- отключение Redis не ломает UI;
- CSS возвращается сервером и не зависит от текущей рабочей директории.

---

## 36. Критерии готовности

Задача считается завершённой, если:

- приложение больше не читает parquet в production-режиме;
- SQL Engine создаётся один раз;
- Redis-клиент создаётся один раз;
- фильтры читают данные из SQL;
- есть индексы;
- есть dataset version;
- кэш-ключи включают dataset version и code version;
- есть L1 и Redis L2;
- есть кэш агрегатов;
- есть кэш периодов;
- g16 и g20 используют общий PeriodResult;
- тяжёлые фигуры могут кэшироваться;
- большие DataFrame не отправляются в `dcc.Store`;
- приложение работает при недоступном Redis;
- приложение работает с несколькими worker;
- есть тесты;
- есть migration script;
- есть `.env.example`;
- есть production-команда запуска;
- README содержит инструкции запуска, миграции, обновления данных и очистки старого кэша;
- внешний вид и бизнес-логика текущего дашборда сохранены.

---

## 36.1. Файлы, которые нельзя потерять при миграции

Codex обязан сохранить и включить в итоговый diff:

```text
legacy/app_tatneft_g17_g20_diag.py
legacy/operator_tatneft_style.css
assets/operator_tatneft_style.css
```

Если CSS изменён, Codex должен перечислить каждое изменение и причину.

Если функция или callback из исходного Python-файла удалены, в отчёте должна быть указана их новая реализация и parity-тест.

---

## 37. Ожидаемые файлы результата

```text
app.py
config.py
db.py
cache_backend.py
requirements.txt
.env.example
README.md
docker-compose.yml
sql/001_create_tables.sql
sql/002_create_indexes.sql
sql/003_create_views.sql
scripts/migrate_parquet_to_sql.py
scripts/refresh_aggregates.py
scripts/clear_old_cache.py
repositories/metrics_repository.py
services/data_service.py
services/aggregation_service.py
services/periods_service.py
services/figure_service.py
callbacks/*.py
tests/*.py
```

---

## 38. Формат отчёта Codex после выполнения

В конце работы Codex должен вывести:

1. список изменённых файлов;
2. краткое описание архитектуры;
3. схему SQL;
4. список кэшируемых объектов и TTL;
5. правила инвалидации;
6. команды запуска;
7. команды миграции;
8. команды тестирования;
9. результаты baseline и final benchmark;
10. известные ограничения;
11. дальнейшие рекомендации.

---

## 39. Порядок работы Codex

Перед изменением кода:

1. Прочитай весь текущий файл приложения.
2. Составь карту callback-ов и зависимостей.
3. Определи фактические столбцы.
4. Не удаляй существующую рабочую логику.
5. Делай изменения маленькими проверяемыми этапами.
6. После каждого этапа запускай тесты.
7. Проверяй импорт и синтаксис:

```bash
python -m compileall .
```

8. Запусти приложение локально.
9. Проверь обе вкладки и все графики.
10. Проверь повторный выбор одинаковых фильтров.
11. Убедись по логам, что повторный запрос не идёт в SQL.
12. Убедись, что g16/g20 не пересчитывают периоды повторно.

При неоднозначности выбирай решение, которое:

- сохраняет текущую бизнес-логику;
- минимизирует объём переписывания;
- допускает rollback;
- имеет тест;
- измеримо улучшает производительность.


---

## 40. Готовый запрос для запуска работы в Codex

```text
Используй файлы app_tatneft_g17_g20_diag.py и operator_tatneft_style.css как единственный источник истины.

Выполни миграцию текущего Dash-приложения на SQLAlchemy + SQL + L1 TTLCache + Redis + выборочный кэш Plotly-фигур строго по документу CODEX_DASH_SQL_MULTILEVEL_CACHE_UPDATED_FOR_CURRENT_APP.md.

Сначала создай legacy-копии и baseline-тесты. Не меняй UI, CSS-классы, IDs компонентов, порядок Outputs, поведение фильтров, g16/g17/g20 и видимые подписи над столбцами.

На первом этапе сохрани динамический scenario-content и единый update_asset callback. Оптимизируй доступ к данным и расчёты через service/cache слой. Не разделяй callback-и, пока не создан статический layout и не пройдены browser smoke-tests.

Обязательно:
- помести operator_tatneft_style.css в assets/;
- перенеси normalize_data в ETL;
- сохрани расчёт дебитов на одинаковой базе строк;
- проверь однозначность связи площадь → НГДУ;
- используй dataset_version в каждом ключе;
- кэшируй один PeriodResult для g16 и g20;
- не отправляй DataFrame в dcc.Store;
- не меняй высоты и CSS overflow карточек;
- проверь все графики g01–g22;
- добавь тест trace.text для main-change и Δ нефти YoY;
- добавь parquet/sql parity-тест;
- предоставь benchmark cold/warm.

После каждого этапа запускай:
python -m compileall .
pytest

В конце предоставь список файлов, SQL-схему, TTL, правила инвалидации, команды миграции, запуска, тестов, benchmark и rollback.
```
