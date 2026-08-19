import hashlib
import json
import logging
import time
from io import BytesIO
from threading import RLock

from config import CODE_CACHE_VERSION, settings

logger = logging.getLogger(__name__)

try:
    from cachetools import TTLCache
except ImportError:  # pragma: no cover - fallback for incomplete local envs
    TTLCache = None

try:
    from redis import Redis
except ImportError:  # pragma: no cover - fallback for incomplete local envs
    Redis = None

try:
    import orjson
except ImportError:  # pragma: no cover - json fallback keeps app functional
    orjson = None


_MISS = object()


class _FallbackTTLCache:
    def __init__(self, maxsize, ttl):
        self.maxsize = maxsize
        self.ttl = ttl
        self._data = {}

    def __getitem__(self, key):
        expires_at, value = self._data[key]
        if expires_at < time.time():
            del self._data[key]
            raise KeyError(key)
        return value

    def __setitem__(self, key, value):
        if len(self._data) >= self.maxsize:
            oldest = min(self._data, key=lambda item: self._data[item][0])
            del self._data[oldest]
        self._data[key] = (time.time() + self.ttl, value)

    def pop(self, key, default=None):
        return self._data.pop(key, default)


local_cache = (
    TTLCache(maxsize=settings.local_cache_maxsize, ttl=settings.local_cache_ttl)
    if TTLCache is not None
    else _FallbackTTLCache(maxsize=settings.local_cache_maxsize, ttl=settings.local_cache_ttl)
)
local_cache_lock = RLock()


def _create_redis_client():
    if not settings.redis_url:
        logger.warning("REDIS_URL is empty; L2 cache is disabled")
        return None
    if Redis is None:
        logger.warning("redis package is not installed; L2 cache is disabled")
        return None
    try:
        return Redis.from_url(
            settings.redis_url,
            decode_responses=False,
            socket_connect_timeout=3,
            socket_timeout=5,
            health_check_interval=30,
        )
    except Exception:
        logger.exception("Could not create Redis client; L2 cache is disabled")
        return None


redis_client = _create_redis_client()


def build_cache_key(namespace, payload):
    normalized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{settings.cache_key_prefix}:{namespace}:{digest}"


def _local_get(key):
    with local_cache_lock:
        try:
            return local_cache[key]
        except KeyError:
            return _MISS


def _local_set(key, value):
    with local_cache_lock:
        local_cache[key] = value


def json_to_bytes(value):
    if orjson is not None:
        try:
            return orjson.dumps(value, option=orjson.OPT_SERIALIZE_NUMPY)
        except TypeError:
            logger.debug("orjson could not serialize value; falling back to PlotlyJSONEncoder", exc_info=True)
    try:
        from plotly.utils import PlotlyJSONEncoder
        return json.dumps(value, ensure_ascii=False, cls=PlotlyJSONEncoder).encode("utf-8")
    except Exception:
        return json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")


def json_from_bytes(data):
    if orjson is not None:
        return orjson.loads(data)
    return json.loads(data.decode("utf-8"))


def dataframe_to_bytes(df):
    buffer = BytesIO()
    df.to_parquet(buffer, index=False, engine="pyarrow")
    return buffer.getvalue()


def dataframe_from_bytes(data):
    import pandas as pd

    return pd.read_parquet(BytesIO(data), engine="pyarrow")


def get_or_compute(
    *,
    key,
    ttl,
    loader,
    serializer,
    deserializer,
    use_local_cache=True,
    use_redis_lock=False,
    max_bytes=None,
):
    started = time.perf_counter()
    if use_local_cache:
        local_value = _local_get(key)
        if local_value is not _MISS:
            logger.info("cache hit level=L1 key=%s elapsed_ms=%.1f", key, (time.perf_counter() - started) * 1000)
            return local_value

    redis_value = None
    if redis_client is not None:
        try:
            redis_value = redis_client.get(key)
        except Exception:
            logger.warning("Redis read failed key=%s; using fallback", key, exc_info=True)

    if redis_value is not None:
        value = deserializer(redis_value)
        if use_local_cache:
            _local_set(key, value)
        logger.info("cache hit level=Redis key=%s bytes=%s elapsed_ms=%.1f", key, len(redis_value), (time.perf_counter() - started) * 1000)
        return value

    def compute_and_store():
        value = loader()
        try:
            data = serializer(value)
        except Exception:
            logger.warning("Cache serialization failed key=%s; returning uncached value", key, exc_info=True)
            return value

        data_size = len(data)
        if max_bytes is not None and data_size > max_bytes:
            logger.info("cache skip key=%s bytes=%s max_bytes=%s", key, data_size, max_bytes)
            return value

        if redis_client is not None:
            try:
                redis_client.setex(key, int(ttl), data)
            except Exception:
                logger.warning("Redis write failed key=%s; L1/fallback remains usable", key, exc_info=True)

        if use_local_cache:
            _local_set(key, value)
        logger.info("cache miss key=%s bytes=%s elapsed_ms=%.1f", key, data_size, (time.perf_counter() - started) * 1000)
        return value

    if not use_redis_lock or redis_client is None:
        return compute_and_store()

    lock = None
    try:
        lock = redis_client.lock(f"{key}:lock", timeout=120, blocking_timeout=10)
        with lock:
            try:
                redis_value = redis_client.get(key)
            except Exception:
                redis_value = None
            if redis_value is not None:
                value = deserializer(redis_value)
                if use_local_cache:
                    _local_set(key, value)
                return value
            return compute_and_store()
    except Exception:
        logger.warning("Redis lock failed key=%s; computing without distributed lock", key, exc_info=True)
        return compute_and_store()


def versioned_payload(dataset_version, extra=None):
    payload = {
        "dataset_version": dataset_version,
        "code_version": CODE_CACHE_VERSION,
    }
    if extra:
        payload.update(extra)
    return payload


def check_redis_connection():
    if redis_client is None:
        return False
    try:
        return bool(redis_client.ping())
    except Exception:
        logger.exception("Redis readiness check failed")
        return False
