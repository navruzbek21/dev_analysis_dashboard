from datetime import datetime

import pandas as pd
from sqlalchemy import delete, insert

from config import settings
from db import engine
from repositories.metrics_repository import area_year_metrics, dashboard_metadata, dim_area, metadata


def create_smoke_dataset(dataset_version="smoke-v1"):
    if engine is None:
        raise RuntimeError("Set DATABASE_URL=sqlite:////path/to/smoke.db before running this script")

    metadata.create_all(engine)
    loaded_at = datetime.utcnow()
    rows = []
    for area_index, (ngdu, mest, area) in enumerate(
        [("НГДУ-1", "Месторождение-1", "Площадь-1"), ("НГДУ-2", "Месторождение-2", "Площадь-2")],
        start=1,
    ):
        oil_cum = 0.0
        liq_cum = 0.0
        water_cum = 0.0
        inj_cum = 0.0
        for offset, year in enumerate(range(2014, 2026), start=1):
            oil = 1000 + area_index * 120 + offset * 25
            liq = oil * (1.25 + offset * 0.015)
            water = liq - oil
            inj = 850 + area_index * 100 + offset * 32
            oil_cum += oil
            liq_cum += liq
            water_cum += water
            inj_cum += inj
            wc = min(95.0, 25 + offset * 3 + area_index)
            niz_otbor = min(92.0, 18 + offset * 4 + area_index)
            gz = 50000 + area_index * 4000
            row = {
                "ngdu": ngdu,
                "mest": mest,
                "kod_ploshchadi": area,
                "year": year,
                "dobycha_nefti": oil,
                "dobycha_liq": liq,
                "dobycha_vody": water,
                "zakachka": inj,
                "wc": wc,
                "dob_fond": 20 + area_index + offset,
                "nagn_fond": 8 + area_index + offset * 0.4,
                "kin": min(70.0, 12 + offset * 3 + area_index),
                "niz_otbor": niz_otbor,
                "niz_temp": 2 + offset * 0.25,
                "kompens_tek": 85 + offset * 1.5,
                "kompens_nak": 90 + offset,
                "gz": gz,
                "niz": 20000 + offset * 500,
                "wc_month_avg": wc,
                "debit_neft": 4.0 + offset * 0.25,
                "debit_liq": 6.0 + offset * 0.35,
                "debit_vod": 2.0 + offset * 0.1,
                "priem": 5.5 + offset * 0.25,
                "dobycha_vody_cum": water_cum,
                "dobycha_nefti_cum": oil_cum,
                "dobycha_liq_cum": liq_cum,
                "zakachka_cum": inj_cum,
                "kiz": niz_otbor,
                "vnf_tek": water / oil,
                "vnf_nak": water_cum / oil_cum,
                "ratio_dob_nagn": (20 + area_index + offset) / (8 + area_index + offset * 0.4),
                "q_priem_q_liq": (5.5 + offset * 0.25) / (6.0 + offset * 0.35),
                "stepen_prokachki": 100 * inj_cum / gz,
                "stepen_promyvki": 100 * liq_cum / gz,
                "temp_prokachki": 100 * inj / gz,
                "temp_promyvki": 100 * liq / gz,
                "dataset_version": dataset_version,
                "loaded_at": loaded_at,
            }
            rows.append(row)

    yearly = pd.DataFrame(rows)
    dim = yearly[["kod_ploshchadi", "ngdu", "mest", "dataset_version"]].drop_duplicates().copy()
    dim.insert(0, "area_id", range(1, len(dim) + 1))
    dim["valid_from"] = loaded_at
    dim["valid_to"] = pd.NaT
    dim["is_current"] = True

    with engine.begin() as connection:
        connection.execute(delete(area_year_metrics).where(area_year_metrics.c.dataset_version == dataset_version))
        connection.execute(delete(dim_area).where(dim_area.c.dataset_version == dataset_version))
        connection.execute(delete(dashboard_metadata).where(dashboard_metadata.c.dataset_name == settings.dataset_name))
        yearly.to_sql("area_year_metrics", connection, if_exists="append", index=False)
        dim.to_sql("dim_area", connection, if_exists="append", index=False)
        connection.execute(
            insert(dashboard_metadata).values(
                dataset_name=settings.dataset_name,
                dataset_version=dataset_version,
                updated_at=loaded_at,
                row_count=len(yearly),
                description="Synthetic smoke-test dataset",
            )
        )
    print({"database_url": settings.safe_database_url, "dataset_version": dataset_version, "rows": len(yearly)})


if __name__ == "__main__":
    create_smoke_dataset()
