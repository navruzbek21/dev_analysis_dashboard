import logging
from copy import deepcopy

from cache_backend import build_cache_key, get_or_compute, json_from_bytes, json_to_bytes, versioned_payload
from config import settings
from filter_utils import normalize_filter_values
from services import data_service

logger = logging.getLogger(__name__)


def _figure_to_json_dict(figure):
    if hasattr(figure, "to_plotly_json"):
        return figure.to_plotly_json()
    return figure


def get_cached_figure(figure_name, selected_ngdu, selected_areas, params, builder, use_lock=False):
    selected_ngdu = normalize_filter_values(selected_ngdu)
    selected_areas = normalize_filter_values(selected_areas)
    dataset_version = data_service.get_dataset_version_cached()
    key = build_cache_key(
        "figure",
        versioned_payload(
            dataset_version,
            {
                "figure_name": figure_name,
                "selected_ngdu": selected_ngdu,
                "selected_areas": selected_areas,
                "params": params or {},
                "figure_version": "plotly-figure-cache-v1",
            },
        ),
    )

    result = get_or_compute(
        key=key,
        ttl=settings.cache_figure_ttl,
        loader=lambda: _figure_to_json_dict(builder()),
        serializer=json_to_bytes,
        deserializer=json_from_bytes,
        use_local_cache=True,
        use_redis_lock=use_lock,
        max_bytes=settings.figure_cache_max_bytes,
    )
    return deepcopy(result)
