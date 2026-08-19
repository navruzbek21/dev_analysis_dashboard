import os
from dataclasses import dataclass

# Меняйте версию при изменении семантики расчётов: она входит в каждый
# кэш-ключ и разом инвалидирует устаревшие значения в Redis.
CODE_CACHE_VERSION = os.getenv("CODE_CACHE_VERSION", "dashboard-cache-v2")


def _get_int(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Переменная окружения {name} должна быть целым числом, получено {value!r}") from exc


def _get_float(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Переменная окружения {name} должна быть числом, получено {value!r}") from exc


def _get_bool(name, default=False):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = _get_int("APP_PORT", 8048)
    app_debug: bool = _get_bool("APP_DEBUG", False)
    data_source: str = "parquet"

    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    cache_key_prefix: str = os.getenv("CACHE_KEY_PREFIX", "tatneft_dashboard")

    cache_default_ttl: int = _get_int("CACHE_DEFAULT_TTL", 3600)
    cache_data_ttl: int = _get_int("CACHE_DATA_TTL", 3600)
    cache_agg_ttl: int = _get_int("CACHE_AGG_TTL", 3600)
    cache_periods_ttl: int = _get_int("CACHE_PERIODS_TTL", 21600)
    cache_figure_ttl: int = _get_int("CACHE_FIGURE_TTL", 1800)
    figure_cache_max_bytes: int = _get_int("FIGURE_CACHE_MAX_BYTES", 10 * 1024 * 1024)

    local_cache_ttl: int = _get_int("LOCAL_CACHE_TTL", 60)
    local_cache_maxsize: int = _get_int("LOCAL_CACHE_MAXSIZE", 128)

    # Физика пересчёта поверхностных объёмов в пластовые и целевой годовой ВНФ
    # для характеристик вытеснения. Значения по умолчанию — для текущего актива;
    # для другого месторождения задаются через окружение.
    displacement_target_vnf: float = _get_float("DISPLACEMENT_TARGET_VNF", 49.0)
    oil_density_t_per_m3: float = _get_float("OIL_DENSITY_T_PER_M3", 0.862)
    water_density_t_per_m3: float = _get_float("WATER_DENSITY_T_PER_M3", 1.185)
    oil_formation_volume_factor: float = _get_float("OIL_FORMATION_VOLUME_FACTOR", 1.157)
    water_formation_volume_factor: float = _get_float("WATER_FORMATION_VOLUME_FACTOR", 1.0)

    parquet_monthly_path: str = os.getenv("PARQUET_MONTHLY_PATH", "df2.parquet")
    parquet_yearly_path: str = os.getenv("PARQUET_YEARLY_PATH", "df_ploshad_year.parquet")
    area_contours_dir: str = os.getenv("AREA_CONTOURS_DIR", "area_contours")
    dataset_name: str = os.getenv("DATASET_NAME", "area_metrics")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    def validate(self):
        if self.data_source != "parquet":
            raise ValueError("Only parquet data source is supported")


settings = Settings()
