import logging

import numpy as np

from cache_backend import build_cache_key, dataframe_from_bytes, dataframe_to_bytes, get_or_compute, versioned_payload
from config import settings
from normalization import safe_div
from services import data_service


logger = logging.getLogger(__name__)


def compute_asset_year_aggregate(d):
    if d.empty:
        return d.copy()

    agg_spec = dict(
        dobycha_liq=("dobycha_liq", "sum"),
        dobycha_nefti=("dobycha_nefti", "sum"),
        zakachka=("zakachka", "sum"),
        dob_fond=("dob_fond", "sum"),
        nagn_fond=("nagn_fond", "sum"),
    )
    if "dobycha_vody" in d.columns:
        agg_spec["dobycha_vody"] = ("dobycha_vody", "sum")
    for col in ["dobycha_nefti_m3", "dobycha_liq_m3", "dobycha_vody_m3"]:
        if col in d.columns:
            agg_spec[col] = (col, "sum")
    for col in ["kin", "vnf_tek"]:
        if col in d.columns:
            agg_spec[col] = (col, "mean")
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
        agg_spec["wc"] = ("wc", "mean")
    elif "wc_month_avg" in d.columns:
        agg_spec["wc"] = ("wc_month_avg", "mean")

    aggregate = d.groupby("year", as_index=False).agg(**agg_spec).sort_values("year")

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
    if "vnf_tek" not in aggregate.columns and {"dobycha_vody", "dobycha_nefti"}.issubset(aggregate.columns):
        aggregate["vnf_tek"] = safe_div(aggregate["dobycha_vody"], aggregate["dobycha_nefti"])

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
    if "wc" not in aggregate.columns:
        aggregate["wc"] = np.nan
    aggregate["oil_yoy_pct"] = aggregate["dobycha_nefti"].pct_change() * 100
    aggregate["ratio_dob_nagn"] = safe_div(aggregate["dob_fond"], aggregate["nagn_fond"])
    return aggregate


def get_asset_year_aggregate(selected_ngdu, selected_areas, selected_mest=()):
    selected_ngdu = data_service.normalize_filter_values(selected_ngdu)
    selected_areas = data_service.normalize_filter_values(selected_areas)
    selected_mest = data_service.normalize_filter_values(selected_mest)
    dataset_version = data_service.get_dataset_version_cached()
    key = build_cache_key(
        "asset_year_aggregate",
        versioned_payload(
            dataset_version,
            {
                "selected_ngdu": selected_ngdu,
                "selected_areas": selected_areas,
                "selected_mest": selected_mest,
                "aggregate_version": "asset-year-v2",
            },
        ),
    )

    def loader():
        d = data_service.get_filtered_year_data(selected_ngdu, selected_areas, selected_mest)
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
