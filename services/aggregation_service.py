import logging

import numpy as np
import pandas as pd

from cache_backend import build_cache_key, dataframe_from_bytes, dataframe_to_bytes, get_or_compute, versioned_payload
from config import settings
from filter_utils import normalize_filter_values
from normalization import safe_div
from services import data_service

logger = logging.getLogger(__name__)

BASE_SUM_COLUMNS = ["dobycha_liq", "dobycha_nefti", "zakachka", "dob_fond", "nagn_fond"]


def _weighted_mean_by_year(d, value_col, weight_col):
    """Среднее value_col по годам, взвешенное weight_col (только строки с обоими значениями)."""
    values = pd.to_numeric(d[value_col], errors="coerce")
    weights = pd.to_numeric(d[weight_col], errors="coerce")
    mask = values.notna() & weights.notna() & (weights > 0)
    if not mask.any():
        return None
    part = pd.DataFrame(
        {"year": d.loc[mask, "year"], "num": values[mask] * weights[mask], "den": weights[mask]}
    )
    grouped = part.groupby("year", as_index=False).sum()
    grouped[value_col] = grouped["num"] / grouped["den"]
    return grouped[["year", value_col]]


def compute_asset_year_aggregate(d):
    if d.empty:
        return d.copy()

    # Все базовые показатели условные: набор колонок зависит от исходного parquet,
    # безусловный agg_spec падал с KeyError на усечённых датасетах.
    agg_spec = {col: (col, "sum") for col in BASE_SUM_COLUMNS if col in d.columns}
    if "dobycha_vody" in d.columns:
        agg_spec["dobycha_vody"] = ("dobycha_vody", "sum")
    for col in ["dobycha_nefti_m3", "dobycha_liq_m3", "dobycha_vody_m3"]:
        if col in d.columns:
            agg_spec[col] = (col, "sum")
    # kin/vnf_tek/wc как невзвешенные средние оставляем только фоллбэком:
    # ниже они пересчитываются из сумм (или взвешиваются по запасам).
    if "kin" in d.columns:
        agg_spec["kin"] = ("kin", "mean")
    if "vnf_tek" in d.columns:
        agg_spec["vnf_tek_unweighted"] = ("vnf_tek", "mean")
    for col in [
        "dobycha_nefti_cum",
        "dobycha_liq_cum",
        "dobycha_nefti_cum_m3",
        "dobycha_liq_cum_m3",
        "dobycha_vody_cum_m3",
    ]:
        if col in d.columns:
            agg_spec[col] = (col, "sum")
    if "wc" in d.columns:
        agg_spec["wc_unweighted"] = ("wc", "mean")
    elif "wc_month_avg" in d.columns:
        agg_spec["wc_unweighted"] = ("wc_month_avg", "mean")

    if not agg_spec:
        agg_spec["__rows"] = ("year", "size")
    aggregate = d.groupby("year", as_index=False).agg(**agg_spec).sort_values("year")
    aggregate = aggregate.drop(columns=["__rows"], errors="ignore")
    for col in BASE_SUM_COLUMNS:
        if col not in aggregate.columns:
            aggregate[col] = np.nan

    cumulative_sources = {
        "dobycha_nefti_cum": "dobycha_nefti",
        "dobycha_liq_cum": "dobycha_liq",
        "dobycha_nefti_cum_m3": "dobycha_nefti_m3",
        "dobycha_liq_cum_m3": "dobycha_liq_m3",
    }
    for cumulative_col, annual_col in cumulative_sources.items():
        if cumulative_col not in aggregate.columns and annual_col in aggregate.columns:
            aggregate[cumulative_col] = aggregate[annual_col].cumsum()
    if {"dobycha_liq_cum", "dobycha_nefti_cum"}.issubset(aggregate.columns):
        aggregate["dobycha_vody_cum"] = aggregate["dobycha_liq_cum"] - aggregate["dobycha_nefti_cum"]
        aggregate["vnf_nak"] = safe_div(aggregate["dobycha_vody_cum"], aggregate["dobycha_nefti_cum"])
    if "dobycha_vody_cum_m3" not in aggregate.columns and {"dobycha_liq_cum_m3", "dobycha_nefti_cum_m3"}.issubset(aggregate.columns):
        aggregate["dobycha_vody_cum_m3"] = aggregate["dobycha_liq_cum_m3"] - aggregate["dobycha_nefti_cum_m3"]
    elif "dobycha_vody_cum" not in aggregate.columns and "dobycha_vody" in aggregate.columns:
        aggregate["dobycha_vody_cum"] = aggregate["dobycha_vody"].cumsum()
    # ВНФ текущий актива — вода/нефть из СУММ по срезу; среднее отношений по
    # площадям (vnf_tek_unweighted) остаётся только фоллбэком для лет без добычи.
    if "dobycha_vody" in aggregate.columns:
        water = pd.to_numeric(aggregate["dobycha_vody"], errors="coerce")
    else:
        water = pd.to_numeric(aggregate["dobycha_liq"], errors="coerce") - pd.to_numeric(aggregate["dobycha_nefti"], errors="coerce")
    vnf_from_sums = pd.Series(safe_div(water, aggregate["dobycha_nefti"]), index=aggregate.index)
    if "vnf_tek_unweighted" in aggregate.columns:
        aggregate["vnf_tek"] = vnf_from_sums.combine_first(aggregate["vnf_tek_unweighted"])
        aggregate = aggregate.drop(columns=["vnf_tek_unweighted"])
    else:
        aggregate["vnf_tek"] = vnf_from_sums

    # КИН актива — среднее по площадям, взвешенное геологическими запасами (gz);
    # невзвешенное среднее остаётся фоллбэком для лет без данных о запасах.
    if "kin" in aggregate.columns and "gz" in d.columns:
        weighted_kin = _weighted_mean_by_year(d, "kin", "gz")
        if weighted_kin is not None:
            aggregate = aggregate.merge(weighted_kin.rename(columns={"kin": "__kin_weighted"}), on="year", how="left")
            aggregate["kin"] = aggregate["__kin_weighted"].combine_first(aggregate["kin"])
            aggregate = aggregate.drop(columns=["__kin_weighted"])

    if {"debit_neft", "debit_liq"}.issubset(d.columns):
        debit_year = (
            d.dropna(subset=["debit_neft", "debit_liq"])
            .groupby("year", as_index=False)
            .agg(debit_neft=("debit_neft", "mean"), debit_liq=("debit_liq", "mean"))
        )
        aggregate = aggregate.merge(debit_year, on="year", how="left")
    else:
        if "debit_neft" in d.columns:
            aggregate = aggregate.merge(d.groupby("year", as_index=False).agg(debit_neft=("debit_neft", "mean")), on="year", how="left")
        else:
            aggregate["debit_neft"] = np.nan
        if "debit_liq" in d.columns:
            aggregate = aggregate.merge(d.groupby("year", as_index=False).agg(debit_liq=("debit_liq", "mean")), on="year", how="left")
        else:
            aggregate["debit_liq"] = np.nan

    aggregate["debit_liq_plot"] = np.where(
        aggregate[["debit_neft", "debit_liq"]].notna().all(axis=1) & (aggregate["debit_liq"] < aggregate["debit_neft"]),
        aggregate["debit_neft"],
        aggregate["debit_liq"],
    )
    # Обводнённость актива — 100·(Qж − Qн)/Qж из сумм; невзвешенное среднее
    # обводнённостей площадей (wc_unweighted) — фоллбэк.
    weighted_wc = pd.Series(
        100 * safe_div(
            pd.to_numeric(aggregate["dobycha_liq"], errors="coerce") - pd.to_numeric(aggregate["dobycha_nefti"], errors="coerce"),
            aggregate["dobycha_liq"],
        ),
        index=aggregate.index,
    )
    if "wc_unweighted" in aggregate.columns:
        aggregate["wc"] = weighted_wc.combine_first(aggregate["wc_unweighted"])
        aggregate = aggregate.drop(columns=["wc_unweighted"])
    else:
        aggregate["wc"] = weighted_wc
    aggregate["oil_yoy_pct"] = aggregate["dobycha_nefti"].pct_change() * 100
    aggregate["ratio_dob_nagn"] = safe_div(aggregate["dob_fond"], aggregate["nagn_fond"])
    return aggregate


def get_asset_year_aggregate(selected_ngdu, selected_areas, selected_mest=(), selected_blocks=()):
    selected_ngdu = normalize_filter_values(selected_ngdu)
    selected_areas = normalize_filter_values(selected_areas)
    selected_mest = normalize_filter_values(selected_mest)
    selected_blocks = normalize_filter_values(selected_blocks)
    dataset_version = data_service.get_dataset_version_cached()
    key = build_cache_key(
        "asset_year_aggregate",
        versioned_payload(
            dataset_version,
            {
                "selected_ngdu": selected_ngdu,
                "selected_areas": selected_areas,
                "selected_mest": selected_mest,
                "selected_blocks": selected_blocks,
                "aggregate_version": "asset-year-v4-weighted",
            },
        ),
    )

    def loader():
        d = data_service.get_filtered_year_data(selected_ngdu, selected_areas, selected_mest, selected_blocks)
        return compute_asset_year_aggregate(d)

    result = get_or_compute(
        key=key,
        ttl=settings.cache_agg_ttl,
        loader=loader,
        serializer=dataframe_to_bytes,
        deserializer=dataframe_from_bytes,
        use_local_cache=True,
        use_redis_lock=True,
    )
    return result.copy(deep=True)


def get_header_year_aggregate(selected_ngdu, selected_areas, selected_mest=()):
    return get_asset_year_aggregate(selected_ngdu, selected_areas, selected_mest)
