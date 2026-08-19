import json
import logging
from dataclasses import dataclass
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pandas as pd

from cache_backend import build_cache_key, dataframe_from_bytes, dataframe_to_bytes, get_or_compute, versioned_payload
from config import settings
from normalization import AREA_COL_YEAR
from filter_utils import normalize_filter_values
from services import data_service


logger = logging.getLogger(__name__)

try:
    from sklearn.linear_model import LinearRegression
except ImportError:  # pragma: no cover - numpy fallback is deterministic
    LinearRegression = None


PERIODS_ALGORITHM_VERSION = "wc-kiz-dp-linear-sse-v1"


@dataclass(frozen=True)
class PeriodResult:
    data: pd.DataFrame
    segments: tuple
    missing_columns: tuple


def compute_wc_kiz_periods_raw(d, n_periods=6, min_size=5):
    required = ["year", "kiz", "wc"]
    miss = [c for c in required if c not in d.columns]
    if d.empty or miss:
        return PeriodResult(pd.DataFrame(), tuple(), tuple(miss))

    keep_cols = ["year", "kiz", "wc", AREA_COL_YEAR]
    if "ngdu" in d.columns:
        keep_cols.append("ngdu")

    df_seg = d[keep_cols].copy()
    df_seg["__src_index"] = d.index
    df_seg = df_seg.dropna(subset=["year", "kiz", "wc"]).copy()
    if df_seg.empty:
        return PeriodResult(pd.DataFrame(), tuple(), tuple())

    df_seg["year"] = pd.to_numeric(df_seg["year"], errors="coerce")
    df_seg["kiz"] = pd.to_numeric(df_seg["kiz"], errors="coerce")
    df_seg["wc"] = pd.to_numeric(df_seg["wc"], errors="coerce")
    df_seg = (
        df_seg
        .dropna(subset=["year", "kiz", "wc"])
        .sort_values(["year", AREA_COL_YEAR])
        .reset_index(drop=True)
    )
    if df_seg.empty:
        return PeriodResult(pd.DataFrame(), tuple(), tuple())

    def segment_sse(data, start, end):
        part = data.iloc[start:end]
        x = part["kiz"].to_numpy(dtype=float)
        y = part["wc"].to_numpy(dtype=float)
        if len(part) < 2:
            return 0.0
        if LinearRegression is not None:
            model = LinearRegression()
            model.fit(x.reshape(-1, 1), y)
            y_pred = model.predict(x.reshape(-1, 1))
        else:
            x_matrix = np.column_stack([np.ones(len(x)), x])
            coef, *_ = np.linalg.lstsq(x_matrix, y, rcond=None)
            y_pred = x_matrix @ coef
        return float(np.sum((y - y_pred) ** 2))

    def find_best_segments(data, n_segments=6, min_size=5):
        n = len(data)
        n_segments = int(max(1, min(n_segments, n // min_size))) if n >= min_size else 1
        min_size_eff = min_size if n >= min_size else max(1, n)
        if n_segments == 1:
            return [(0, n)]

        sse = np.full((n + 1, n + 1), np.inf)
        for i in range(n):
            for j in range(i + min_size_eff, n + 1):
                sse[i, j] = segment_sse(data, i, j)

        dp = np.full((n_segments + 1, n + 1), np.inf)
        prev = np.full((n_segments + 1, n + 1), -1, dtype=int)
        dp[0, 0] = 0.0

        for k in range(1, n_segments + 1):
            j_min = k * min_size_eff
            for j in range(j_min, n + 1):
                best_value = np.inf
                best_i = -1
                i_min = (k - 1) * min_size_eff
                i_max = j - min_size_eff + 1
                for i in range(i_min, i_max):
                    value = dp[k - 1, i] + sse[i, j]
                    if value < best_value:
                        best_value = value
                        best_i = i
                dp[k, j] = best_value
                prev[k, j] = best_i

        if prev[n_segments, n] < 0:
            return [(0, n)]

        segments = []
        j = n
        for k in range(n_segments, 0, -1):
            i = prev[k, j]
            if i < 0:
                return [(0, n)]
            segments.append((i, j))
            j = i
        return segments[::-1]

    segments = find_best_segments(df_seg, n_segments=n_periods, min_size=min_size)
    df_seg["period_number"] = np.nan
    for period_num, (start, end) in enumerate(segments, start=1):
        df_seg.loc[start:end - 1, "period_number"] = period_num
    df_seg["period_number"] = df_seg["period_number"].astype(int)

    period_info = (
        df_seg.groupby("period_number", as_index=False)
        .agg(year_start=("year", "min"), year_end=("year", "max"))
        .sort_values("period_number")
    )
    period_info["period"] = period_info.apply(
        lambda row: f"Период {int(row['period_number'])}: {int(row['year_start'])}-{int(row['year_end'])} гг.",
        axis=1,
    )
    df_seg = df_seg.merge(period_info[["period_number", "period"]], on="period_number", how="left")
    return PeriodResult(df_seg, tuple((int(start), int(end)) for start, end in segments), tuple())


def period_result_to_bytes(result):
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("data.parquet", dataframe_to_bytes(result.data))
        archive.writestr(
            "meta.json",
            json.dumps(
                {
                    "segments": [list(segment) for segment in result.segments],
                    "missing_columns": list(result.missing_columns),
                },
                ensure_ascii=False,
            ),
        )
    return buffer.getvalue()


def period_result_from_bytes(data):
    with ZipFile(BytesIO(data), "r") as archive:
        df = dataframe_from_bytes(archive.read("data.parquet"))
        meta = json.loads(archive.read("meta.json").decode("utf-8"))
    return PeriodResult(
        data=df,
        segments=tuple(tuple(segment) for segment in meta.get("segments", [])),
        missing_columns=tuple(meta.get("missing_columns", [])),
    )


def get_wc_kiz_periods(selected_ngdu, selected_areas, selected_mest=(), selected_blocks=(), n_periods=6, min_size=5):
    selected_ngdu = normalize_filter_values(selected_ngdu)
    selected_areas = normalize_filter_values(selected_areas)
    selected_mest = normalize_filter_values(selected_mest)
    selected_blocks = normalize_filter_values(selected_blocks)
    dataset_version = data_service.get_dataset_version_cached()
    key = build_cache_key(
        "wc_kiz_periods",
        versioned_payload(
            dataset_version,
            {
                "selected_ngdu": selected_ngdu,
                "selected_areas": selected_areas,
                "selected_mest": selected_mest,
                "selected_blocks": selected_blocks,
                "n_periods": int(n_periods),
                "min_size": int(min_size),
                "algorithm_version": PERIODS_ALGORITHM_VERSION + "-block",
            },
        ),
    )

    def loader():
        d = data_service.get_filtered_year_data(selected_ngdu, selected_areas, selected_mest, selected_blocks)
        return compute_wc_kiz_periods_raw(d, n_periods=n_periods, min_size=min_size)

    result = get_or_compute(
        key=key,
        ttl=settings.cache_periods_ttl,
        loader=loader,
        serializer=period_result_to_bytes,
        deserializer=period_result_from_bytes,
        use_local_cache=True,
        use_redis_lock=True,
    )
    return PeriodResult(result.data.copy(deep=True), tuple(result.segments), tuple(result.missing_columns))
