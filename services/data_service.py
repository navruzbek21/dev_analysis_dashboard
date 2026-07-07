import logging
import os
from functools import lru_cache

import pandas as pd

from cache_backend import (
    build_cache_key,
    dataframe_from_bytes,
    dataframe_to_bytes,
    get_or_compute,
    json_from_bytes,
    json_to_bytes,
    versioned_payload,
)
from config import settings
from filter_utils import normalize_filter_values
from normalization import AREA_COL_YEAR, AREA_COL_MONTH, MEST_COL, normalize_data


logger = logging.getLogger(__name__)


def _parquet_dataset_version():
    paths = [settings.parquet_monthly_path, settings.parquet_yearly_path]
    parts = []
    for path in paths:
        if os.path.exists(path):
            parts.append(f"{path}:{os.path.getmtime(path):.0f}:{os.path.getsize(path)}")
        else:
            parts.append(f"{path}:missing")
    return "parquet:" + "|".join(parts)


@lru_cache(maxsize=1)
def _load_parquet_year_data():
    df2 = pd.read_parquet(settings.parquet_monthly_path)
    dfy = pd.read_parquet(settings.parquet_yearly_path)
    _, normalized_year = normalize_data(df2, dfy, area_col_month=AREA_COL_MONTH, area_col_year=AREA_COL_YEAR)
    return normalized_year


def get_dataset_version_cached():
    return _parquet_dataset_version()


def get_mest_options():
    dataset_version = get_dataset_version_cached()
    key = build_cache_key("mest_options", versioned_payload(dataset_version, {"dataset_name": settings.dataset_name}))

    def load_parquet():
        df = _load_parquet_year_data()
        if MEST_COL not in df.columns:
            return []
        return sorted([x for x in df[MEST_COL].dropna().unique()])

    return get_or_compute(
        key=key,
        ttl=settings.cache_data_ttl,
        loader=load_parquet,
        serializer=json_to_bytes,
        deserializer=json_from_bytes,
        use_local_cache=True,
    )


def get_ngdu_options(selected_mest=()):
    selected_mest = normalize_filter_values(selected_mest)
    dataset_version = get_dataset_version_cached()
    key = build_cache_key(
        "ngdu_options",
        versioned_payload(dataset_version, {"dataset_name": settings.dataset_name, "selected_mest": selected_mest}),
    )

    def load_parquet():
        df = _load_parquet_year_data()
        if selected_mest and MEST_COL in df.columns:
            df = df[df[MEST_COL].isin(selected_mest)]
        return sorted([x for x in df["ngdu"].dropna().unique()])

    return get_or_compute(
        key=key,
        ttl=settings.cache_data_ttl,
        loader=load_parquet,
        serializer=json_to_bytes,
        deserializer=json_from_bytes,
        use_local_cache=True,
    )


def get_area_options(selected_ngdu, selected_mest=()):
    selected_ngdu = normalize_filter_values(selected_ngdu)
    selected_mest = normalize_filter_values(selected_mest)
    dataset_version = get_dataset_version_cached()
    key = build_cache_key(
        "area_options",
        versioned_payload(dataset_version, {"selected_ngdu": selected_ngdu, "selected_mest": selected_mest}),
    )

    def load_parquet():
        df = _load_parquet_year_data()
        if selected_mest and MEST_COL in df.columns:
            df = df[df[MEST_COL].isin(selected_mest)]
        if selected_ngdu:
            df = df[df["ngdu"].isin(selected_ngdu)]
        return sorted([x for x in df[AREA_COL_YEAR].dropna().unique()])

    return get_or_compute(
        key=key,
        ttl=settings.cache_data_ttl,
        loader=load_parquet,
        serializer=json_to_bytes,
        deserializer=json_from_bytes,
        use_local_cache=True,
    )


def get_filtered_year_data(selected_ngdu, selected_areas, selected_mest=()):
    selected_ngdu = normalize_filter_values(selected_ngdu)
    selected_areas = normalize_filter_values(selected_areas)
    selected_mest = normalize_filter_values(selected_mest)
    dataset_version = get_dataset_version_cached()
    key = build_cache_key(
        "filtered_year_data",
        versioned_payload(
            dataset_version,
            {
                "selected_ngdu": selected_ngdu,
                "selected_areas": selected_areas,
                "selected_mest": selected_mest,
            },
        ),
    )

    def load_parquet():
        df = _load_parquet_year_data()
        if selected_mest and MEST_COL in df.columns:
            df = df[df[MEST_COL].isin(selected_mest)]
        if selected_ngdu:
            df = df[df["ngdu"].isin(selected_ngdu)]
        if selected_areas:
            df = df[df[AREA_COL_YEAR].isin(selected_areas)]
        return df.reset_index(drop=True)

    df = get_or_compute(
        key=key,
        ttl=settings.cache_data_ttl,
        loader=load_parquet,
        serializer=dataframe_to_bytes,
        deserializer=dataframe_from_bytes,
        use_local_cache=True,
        use_redis_lock=True,
    )
    return df.copy(deep=True)
