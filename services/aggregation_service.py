import logging

import numpy as np

from cache_backend import build_cache_key, dataframe_from_bytes, dataframe_to_bytes, get_or_compute, versioned_payload
from config import settings
from normalization import safe_div
from services import data_service


logger = logging.getLogger(__name__)


def _weighted_mean(group, value_col, weight_col):
    values = group[value_col] if value_col in group else None
    weights = group[weight_col] if weight_col in group else None
    if values is None or weights is None:
        return np.nan
    mask = values.notna() & weights.notna() & weights.gt(0)
    if not mask.any():
        return values.mean(skipna=True)
    return float(np.average(values[mask], weights=weights[mask]))


def _ratio_from_sums(grouped, numerator, denominator, multiplier=1.0):
    if numerator not in grouped.columns or denominator not in grouped.columns:
        return np.nan
    return multiplier * safe_div(grouped[numerator], grouped[denominator])


def compute_asset_year_aggregate(d):
    if d.empty:
        return d.copy()

    sum_cols = [
        "dobycha_liq", "dobycha_nefti", "dobycha_vody", "zakachka", "dob_fond", "nagn_fond",
        "gz", "niz", "dobycha_nefti_cum", "dobycha_liq_cum", "dobycha_vody_cum",
        "dobycha_nefti_m3", "dobycha_liq_m3", "dobycha_vody_m3", "dobycha_nefti_cum_m3",
        "dobycha_liq_cum_m3", "dobycha_vody_cum_m3", "priemistost", "niz_otbor",
    ]
    agg_spec = {col: (col, "sum") for col in sum_cols if col in d.columns}
    for col in ["debit_neft", "debit_liq"]:
        if col in d.columns:
            agg_spec[col] = (col, "mean")
    aggregate = d.groupby("year", as_index=False).agg(**agg_spec).sort_values("year")

    if "dobycha_vody" not in aggregate.columns and {"dobycha_liq", "dobycha_nefti"}.issubset(aggregate.columns):
        aggregate["dobycha_vody"] = aggregate["dobycha_liq"] - aggregate["dobycha_nefti"]
    if {"dobycha_vody", "dobycha_liq"}.issubset(aggregate.columns):
        aggregate["wc"] = _ratio_from_sums(aggregate, "dobycha_vody", "dobycha_liq", 100.0)
    elif "wc" in d.columns:
        aggregate = aggregate.merge(d.groupby("year", as_index=False).agg(wc=("wc", "mean")), on="year", how="left")
    elif "wc_month_avg" in d.columns:
        aggregate = aggregate.merge(d.groupby("year", as_index=False).agg(wc=("wc_month_avg", "mean")), on="year", how="left")
    else:
        aggregate["wc"] = np.nan

    if {"dobycha_vody", "dobycha_nefti"}.issubset(aggregate.columns):
        aggregate["vnf_tek"] = _ratio_from_sums(aggregate, "dobycha_vody", "dobycha_nefti")
    cumulative_sources = {"dobycha_nefti_cum": "dobycha_nefti", "dobycha_liq_cum": "dobycha_liq", "dobycha_vody_cum": "dobycha_vody", "dobycha_nefti_cum_m3": "dobycha_nefti_m3", "dobycha_liq_cum_m3": "dobycha_liq_m3", "dobycha_vody_cum_m3": "dobycha_vody_m3"}
    for cumulative_col, annual_col in cumulative_sources.items():
        if cumulative_col not in aggregate.columns and annual_col in aggregate.columns:
            aggregate[cumulative_col] = aggregate[annual_col].cumsum()
    if {"dobycha_vody_cum", "dobycha_nefti_cum"}.issubset(aggregate.columns):
        aggregate["vnf_nak"] = _ratio_from_sums(aggregate, "dobycha_vody_cum", "dobycha_nefti_cum")

    for col in ["kin", "kiz"]:
        if "niz" in aggregate.columns and "dobycha_nefti_cum" in aggregate.columns:
            aggregate[col] = _ratio_from_sums(aggregate, "dobycha_nefti_cum", "niz", 100.0)
        elif col in d.columns:
            wm = d.groupby("year").apply(lambda g: _weighted_mean(g, col, "niz") if "niz" in g.columns else g[col].mean()).rename(col).reset_index()
            aggregate = aggregate.drop(columns=[col], errors="ignore").merge(wm, on="year", how="left")

    if {"zakachka", "dobycha_liq"}.issubset(aggregate.columns):
        aggregate["q_priem_q_liq"] = _ratio_from_sums(aggregate, "zakachka", "dobycha_liq")
    if {"zakachka", "dobycha_liq_cum"}.issubset(aggregate.columns):
        aggregate["stepen_prokachki"] = _ratio_from_sums(aggregate, "zakachka", "dobycha_liq_cum", 100.0)
    if {"zakachka", "dobycha_vody_cum"}.issubset(aggregate.columns):
        aggregate["stepen_promyvki"] = _ratio_from_sums(aggregate, "zakachka", "dobycha_vody_cum", 100.0)

    for col in ["debit_neft", "debit_liq"]:
        if col not in aggregate.columns:
            aggregate[col] = np.nan
    aggregate["debit_liq_plot"] = np.where(aggregate[["debit_neft", "debit_liq"]].notna().all(axis=1) & (aggregate["debit_liq"] < aggregate["debit_neft"]), aggregate["debit_neft"], aggregate["debit_liq"])
    aggregate["oil_yoy_pct"] = aggregate["dobycha_nefti"].pct_change() * 100 if "dobycha_nefti" in aggregate.columns else np.nan
    aggregate["ratio_dob_nagn"] = safe_div(aggregate["dob_fond"], aggregate["nagn_fond"]) if {"dob_fond", "nagn_fond"}.issubset(aggregate.columns) else np.nan
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
