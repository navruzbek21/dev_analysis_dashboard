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
from normalization import (
    ALL_BLOCK_VALUE,
    AREA_COL_MONTH,
    AREA_COL_YEAR,
    BLOCK_COL,
    INCLUDE_BLOCK_ROWS_VALUE,
    MEST_COL,
    normalize_data,
    validate_area_ngdu_uniqueness,
)

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
    try:
        conflicts = validate_area_ngdu_uniqueness(df2)
        if not conflicts.empty:
            # normalize_data молча берёт первое НГДУ для конфликтной площади —
            # без этого предупреждения расхождение в данных незаметно.
            logger.warning(
                "Areas mapped to more than one NGDU (first one wins): %s",
                conflicts.to_dict("records"),
            )
    except Exception:
        logger.exception("Area/NGDU uniqueness validation failed")
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


def _block_sort_key(value):
    text = str(value)
    try:
        return (0, int(float(text)))
    except ValueError:
        return (1, text)


def _filter_area_level_rows(df):
    if BLOCK_COL not in df.columns or df.empty:
        return df
    block_text = df[BLOCK_COL].astype(str).str.strip().str.lower()
    area_level = df[BLOCK_COL].isna() | block_text.eq("all") | block_text.eq("")
    if area_level.any():
        return df[area_level]
    return df


def _filter_block_rows(df, selected_blocks):
    selected_blocks = normalize_filter_values(selected_blocks)
    if BLOCK_COL not in df.columns or not selected_blocks:
        return _filter_area_level_rows(df)
    selected_text = {str(value).strip().lower() for value in selected_blocks}
    if INCLUDE_BLOCK_ROWS_VALUE.lower() in selected_text:
        return df
    if ALL_BLOCK_VALUE.lower() in selected_text or "all" in selected_text:
        return _filter_area_level_rows(df)
    block_text = df[BLOCK_COL].astype(str).str.strip().str.lower()
    return df[block_text.isin(selected_text)]


def get_block_options(selected_ngdu, selected_areas, selected_mest=()):
    selected_ngdu = normalize_filter_values(selected_ngdu)
    selected_areas = normalize_filter_values(selected_areas)
    selected_mest = normalize_filter_values(selected_mest)
    dataset_version = get_dataset_version_cached()
    key = build_cache_key(
        "block_options",
        versioned_payload(
            dataset_version,
            {"selected_ngdu": selected_ngdu, "selected_areas": selected_areas, "selected_mest": selected_mest},
        ),
    )

    def load_parquet():
        df = _load_parquet_year_data()
        if BLOCK_COL not in df.columns:
            return []
        if selected_mest and MEST_COL in df.columns:
            df = df[df[MEST_COL].isin(selected_mest)]
        if selected_ngdu and "ngdu" in df.columns:
            df = df[df["ngdu"].isin(selected_ngdu)]
        if selected_areas:
            df = df[df[AREA_COL_YEAR].isin(selected_areas)]
        blocks = []
        for value in df[BLOCK_COL].dropna().unique():
            text = str(value).strip()
            if text and text.lower() != "all":
                blocks.append(text)
        return sorted(set(blocks), key=_block_sort_key)

    return get_or_compute(
        key=key,
        ttl=settings.cache_data_ttl,
        loader=load_parquet,
        serializer=json_to_bytes,
        deserializer=json_from_bytes,
        use_local_cache=True,
    )


def get_filtered_year_data(selected_ngdu, selected_areas, selected_mest=(), selected_blocks=()):
    selected_ngdu = normalize_filter_values(selected_ngdu)
    selected_areas = normalize_filter_values(selected_areas)
    selected_mest = normalize_filter_values(selected_mest)
    selected_blocks = normalize_filter_values(selected_blocks)
    dataset_version = get_dataset_version_cached()
    key = build_cache_key(
        "filtered_year_data",
        versioned_payload(
            dataset_version,
            {
                "selected_ngdu": selected_ngdu,
                "selected_areas": selected_areas,
                "selected_mest": selected_mest,
                "selected_blocks": selected_blocks,
                "block_filter_version": "v1",
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
        df = _filter_block_rows(df, selected_blocks)
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
