import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()


CODE_CACHE_VERSION = os.getenv("CODE_CACHE_VERSION", "dashboard-cache-v1")


def _get_int(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


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
    data_source: str = os.getenv("DATA_SOURCE", "sql").strip().lower()

    database_url: str = os.getenv("DATABASE_URL", "")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    cache_key_prefix: str = os.getenv("CACHE_KEY_PREFIX", "tatneft_dashboard")

    cache_default_ttl: int = _get_int("CACHE_DEFAULT_TTL", 3600)
    cache_data_ttl: int = _get_int("CACHE_DATA_TTL", 3600)
    cache_agg_ttl: int = _get_int("CACHE_AGG_TTL", 3600)
    cache_periods_ttl: int = _get_int("CACHE_PERIODS_TTL", 21600)
    cache_figure_ttl: int = _get_int("CACHE_FIGURE_TTL", 1800)
    figure_cache_max_bytes: int = _get_int("FIGURE_CACHE_MAX_BYTES", 10 * 1024 * 1024)

    db_pool_size: int = _get_int("DB_POOL_SIZE", 10)
    db_max_overflow: int = _get_int("DB_MAX_OVERFLOW", 20)
    db_pool_recycle: int = _get_int("DB_POOL_RECYCLE", 1800)
    db_pool_timeout: int = _get_int("DB_POOL_TIMEOUT", 30)

    local_cache_ttl: int = _get_int("LOCAL_CACHE_TTL", 60)
    local_cache_maxsize: int = _get_int("LOCAL_CACHE_MAXSIZE", 128)

    parquet_monthly_path: str = os.getenv("PARQUET_MONTHLY_PATH", "df2.parquet")
    parquet_yearly_path: str = os.getenv("PARQUET_YEARLY_PATH", "df_ploshad_year.parquet")
    area_contours_dir: str = os.getenv("AREA_CONTOURS_DIR", "area_contours")
    dataset_name: str = os.getenv("DATASET_NAME", "area_metrics")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    @property
    def is_sql(self):
        return self.data_source == "sql"

    @property
    def is_parquet(self):
        return self.data_source == "parquet"

    @property
    def safe_database_url(self):
        if not self.database_url:
            return ""
        if "@" not in self.database_url:
            return self.database_url
        scheme_and_auth, host = self.database_url.rsplit("@", 1)
        scheme = scheme_and_auth.split("://", 1)[0] if "://" in scheme_and_auth else "db"
        return f"{scheme}://***:***@{host}"

    def validate(self, require_database=None):
        if self.data_source not in {"sql", "parquet"}:
            raise ValueError("DATA_SOURCE must be either 'sql' or 'parquet'")
        if require_database is None:
            require_database = self.app_env.strip().lower() in {"production", "prod", "staging"}
        if require_database and not self.database_url:
            raise RuntimeError("DATABASE_URL is required for this environment")
        if self.is_sql and not self.database_url and self.app_env.strip().lower() not in {"development", "dev", "local", "test"}:
            raise RuntimeError("DATABASE_URL is required when DATA_SOURCE=sql outside development")


settings = Settings()
