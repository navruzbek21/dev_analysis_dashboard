import logging
import time

import pandas as pd

from config import settings
from db import connection_scope


logger = logging.getLogger(__name__)

try:
    from sqlalchemy import (
        BigInteger,
        Boolean,
        Column,
        DateTime,
        Float,
        Integer,
        MetaData,
        String,
        Table,
        inspect,
        select,
    )
except ImportError:  # pragma: no cover - compile-only local env fallback
    BigInteger = Boolean = Column = DateTime = Float = Integer = MetaData = String = Table = inspect = select = None


YEAR_METRIC_COLUMNS = [
    "ngdu",
    "mest",
    "kod_ploshchadi",
    "year",
    "dobycha_nefti",
    "dobycha_liq",
    "dobycha_vody",
    "dobycha_nefti_m3",
    "dobycha_liq_m3",
    "dobycha_vody_m3",
    "zakachka",
    "wc",
    "dob_fond",
    "nagn_fond",
    "kin",
    "niz_otbor",
    "niz_temp",
    "kompens_tek",
    "kompens_nak",
    "gz",
    "niz",
    "wc_month_avg",
    "debit_neft",
    "debit_liq",
    "debit_vod",
    "priem",
    "dobycha_vody_cum",
    "dobycha_nefti_cum",
    "dobycha_liq_cum",
    "dobycha_nefti_cum_m3",
    "dobycha_liq_cum_m3",
    "dobycha_vody_cum_m3",
    "zakachka_cum",
    "kiz",
    "vnf_tek",
    "vnf_nak",
    "ratio_dob_nagn",
    "q_priem_q_liq",
    "stepen_prokachki",
    "stepen_promyvki",
    "temp_prokachki",
    "temp_promyvki",
    "dataset_version",
]


if MetaData is not None:
    metadata = MetaData()
    dashboard_metadata = Table(
        "dashboard_metadata",
        metadata,
        Column("dataset_name", String(100), primary_key=True),
        Column("dataset_version", String(100), nullable=False),
        Column("updated_at", DateTime, nullable=False),
        Column("row_count", BigInteger),
        Column("description", String(500)),
    )
    dim_area = Table(
        "dim_area",
        metadata,
        Column("area_id", BigInteger, primary_key=True),
        Column("kod_ploshchadi", String(255), nullable=False),
        Column("ngdu", String(255), nullable=False),
        Column("mest", String(255)),
        Column("dataset_version", String(100), nullable=False),
        Column("valid_from", DateTime),
        Column("valid_to", DateTime),
        Column("is_current", Boolean, nullable=False),
    )
    monthly_metrics = Table(
        "monthly_metrics",
        metadata,
        Column("date", DateTime),
        Column("year", Integer),
        Column("ngdu", String(255)),
        Column("mest", String(255)),
        Column("ploshad", String(255)),
        Column("well_uid", String(255)),
        Column("debit_neft", Float),
        Column("debit_liq", Float),
        Column("debit_vod", Float),
        Column("priem", Float),
        Column("wc", Float),
        Column("dataset_version", String(100), nullable=False),
        Column("loaded_at", DateTime),
        Column("source_file", String(500)),
    )
    area_year_metrics = Table(
        "area_year_metrics",
        metadata,
        Column("ngdu", String(255)),
        Column("mest", String(255)),
        Column("kod_ploshchadi", String(255)),
        Column("year", Integer),
        Column("dobycha_nefti", Float),
        Column("dobycha_liq", Float),
        Column("dobycha_vody", Float),
        Column("dobycha_nefti_m3", Float),
        Column("dobycha_liq_m3", Float),
        Column("dobycha_vody_m3", Float),
        Column("zakachka", Float),
        Column("wc", Float),
        Column("dob_fond", Float),
        Column("nagn_fond", Float),
        Column("kin", Float),
        Column("niz_otbor", Float),
        Column("niz_temp", Float),
        Column("kompens_tek", Float),
        Column("kompens_nak", Float),
        Column("gz", Float),
        Column("niz", Float),
        Column("wc_month_avg", Float),
        Column("debit_neft", Float),
        Column("debit_liq", Float),
        Column("debit_vod", Float),
        Column("priem", Float),
        Column("dobycha_vody_cum", Float),
        Column("dobycha_nefti_cum", Float),
        Column("dobycha_liq_cum", Float),
        Column("dobycha_nefti_cum_m3", Float),
        Column("dobycha_liq_cum_m3", Float),
        Column("dobycha_vody_cum_m3", Float),
        Column("zakachka_cum", Float),
        Column("kiz", Float),
        Column("vnf_tek", Float),
        Column("vnf_nak", Float),
        Column("ratio_dob_nagn", Float),
        Column("q_priem_q_liq", Float),
        Column("stepen_prokachki", Float),
        Column("stepen_promyvki", Float),
        Column("temp_prokachki", Float),
        Column("temp_promyvki", Float),
        Column("dataset_version", String(100), nullable=False),
        Column("loaded_at", DateTime),
    )
else:
    metadata = dashboard_metadata = dim_area = monthly_metrics = area_year_metrics = None


def _require_sqlalchemy():
    if select is None:
        raise RuntimeError("SQLAlchemy is required for repository access")


def _timed_query(label, func):
    started = time.perf_counter()
    result = func()
    logger.info("sql query=%s elapsed_ms=%.1f", label, (time.perf_counter() - started) * 1000)
    return result


def _existing_area_year_columns(connection):
    if inspect is None:
        return set(area_year_metrics.c.keys())
    try:
        return {column["name"] for column in inspect(connection).get_columns(area_year_metrics.name)}
    except Exception:
        logger.debug("Could not inspect area_year_metrics columns; using declared schema", exc_info=True)
        return set(area_year_metrics.c.keys())


def _apply_mest_filter(stmt, selected_mest, available_columns):
    if selected_mest and "mest" in available_columns:
        return stmt.where(area_year_metrics.c.mest.in_(tuple(selected_mest)))
    return stmt


def get_dataset_version():
    _require_sqlalchemy()

    def run():
        stmt = (
            select(dashboard_metadata.c.dataset_version)
            .where(dashboard_metadata.c.dataset_name == settings.dataset_name)
            .limit(1)
        )
        with connection_scope() as connection:
            value = connection.execute(stmt).scalar_one_or_none()
        if not value:
            raise RuntimeError(f"dataset_version for {settings.dataset_name!r} was not found")
        return str(value)

    return _timed_query("get_dataset_version", run)


def get_all_mest(dataset_version):
    _require_sqlalchemy()

    def run():
        with connection_scope() as connection:
            available_columns = _existing_area_year_columns(connection)
            if "mest" not in available_columns:
                return []
            stmt = (
                select(area_year_metrics.c.mest)
                .distinct()
                .where(area_year_metrics.c.dataset_version == dataset_version)
                .where(area_year_metrics.c.mest.is_not(None))
                .order_by(area_year_metrics.c.mest)
            )
            return [row[0] for row in connection.execute(stmt).all()]

    return _timed_query("get_all_mest", run)


def get_all_ngdu(dataset_version, selected_mest=()):
    _require_sqlalchemy()

    def run():
        with connection_scope() as connection:
            available_columns = _existing_area_year_columns(connection)
            stmt = (
                select(area_year_metrics.c.ngdu)
                .distinct()
                .where(area_year_metrics.c.dataset_version == dataset_version)
                .where(area_year_metrics.c.ngdu.is_not(None))
            )
            stmt = _apply_mest_filter(stmt, selected_mest, available_columns)
            stmt = stmt.order_by(area_year_metrics.c.ngdu)
            return [row[0] for row in connection.execute(stmt).all()]

    return _timed_query("get_all_ngdu", run)


def get_areas_for_ngdu(selected_ngdu, dataset_version, selected_mest=()):
    _require_sqlalchemy()

    def run():
        with connection_scope() as connection:
            available_columns = _existing_area_year_columns(connection)
            stmt = (
                select(area_year_metrics.c.kod_ploshchadi)
                .distinct()
                .where(area_year_metrics.c.dataset_version == dataset_version)
                .where(area_year_metrics.c.kod_ploshchadi.is_not(None))
            )
            stmt = _apply_mest_filter(stmt, selected_mest, available_columns)
            if selected_ngdu:
                stmt = stmt.where(area_year_metrics.c.ngdu.in_(tuple(selected_ngdu)))
            stmt = stmt.order_by(area_year_metrics.c.kod_ploshchadi)
            return [row[0] for row in connection.execute(stmt).all()]

    return _timed_query("get_areas_for_ngdu", run)


def load_year_metrics(selected_ngdu, selected_areas, dataset_version, selected_mest=()):
    _require_sqlalchemy()

    def run():
        with connection_scope() as connection:
            available_columns = _existing_area_year_columns(connection)
            selected_columns = [column for column in YEAR_METRIC_COLUMNS if column in available_columns]
            columns = [area_year_metrics.c[column] for column in selected_columns]
            stmt = select(*columns).where(area_year_metrics.c.dataset_version == dataset_version)
            stmt = _apply_mest_filter(stmt, selected_mest, available_columns)
            if selected_ngdu:
                stmt = stmt.where(area_year_metrics.c.ngdu.in_(tuple(selected_ngdu)))
            if selected_areas:
                stmt = stmt.where(area_year_metrics.c.kod_ploshchadi.in_(tuple(selected_areas)))
            stmt = stmt.order_by(area_year_metrics.c.kod_ploshchadi, area_year_metrics.c.year)
            df = pd.read_sql_query(stmt, connection)
        if "mest" not in df.columns:
            df["mest"] = pd.NA
        return df

    return _timed_query("load_year_metrics", run)

