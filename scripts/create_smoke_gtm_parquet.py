from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd


def build(seed: int = 42):
    rng = np.random.default_rng(seed)
    mests = ["Месторождение A", "Месторождение B"]
    ploshes = ["Площадь 1", "Площадь 2"]
    ops = []
    rows = []
    for i in range(18):
        mest = mests[i % 2]; plosh = ploshes[i % 2]; year = 2023 + i % 3
        well = f"W{i+1:03d}"; is_inj = i % 6 == 0
        effective = i % 3 == 0
        gtm_date = pd.Timestamp(year=year, month=(i % 12) + 1, day=15)
        base_oil = rng.uniform(8, 20); base_liq = base_oil / rng.uniform(0.35, 0.75)
        delta = rng.uniform(2, 8) if effective else rng.uniform(-5, -0.5)
        if is_inj: delta = 0
        for mo in range(-15, 16):
            date = gtm_date + pd.DateOffset(months=mo)
            oil = base_oil + (delta if mo > 0 else 0) + rng.normal(0, 0.5)
            liq = max(oil + rng.uniform(4, 15), 0)
            rows.append({"well": well, "date": date, "gtm_date": gtm_date, "month_offset": mo, "qliq": liq, "qoil": max(oil, 0), "qoil_plan": base_oil + max(delta, 1), "qinj": rng.uniform(20, 80) if is_inj else 0, "wcut": 100*(liq-max(oil,0))/liq if liq else 0, "Р_пл": rng.uniform(120, 180), "Р_заб": rng.uniform(60, 120), "gtm_year": year, "year": date.year, "назнач_скв_факт": "НАГ" if is_inj else "ДОБ", "направление": "Ввод нагнет. скважин" if is_inj else ("ГРП" if effective else "ОПЗ"), "mest": mest, "plosh": plosh, "вид_операции": "smoke"})
        ops.append({"год_гтм": year, "year": year, "dop_dob_month": max(delta, 0)*30, "направление": "Ввод нагнет. скважин" if is_inj else ("ГРП" if effective else "ОПЗ"), "plosh": plosh, "mest": mest, "well": well})
    result_df = pd.DataFrame(rows)
    years = []
    for y in range(2021, 2026):
        for mest, plosh in zip(mests, ploshes):
            years.append({"year": y, "mest": mest, "plosh": plosh, "dobycha_nefti": rng.uniform(10000, 20000), "dobycha_liq": rng.uniform(25000, 50000), "zakachka": rng.uniform(10000, 40000)})
    factor = pd.DataFrame({"well": [o["well"] for o in ops], "wcut_factor": rng.normal(size=18), "qliq_factor": rng.normal(size=18), "Р_пл_factor": rng.normal(size=18), "Р_заб_factor": rng.normal(size=18), "Kprod_factor": rng.normal(size=18)})
    return result_df, pd.DataFrame(years), pd.DataFrame(ops), factor


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--seed", type=int, default=42); ap.add_argument("--out", default=".")
    args = ap.parse_args(); out = Path(args.out)
    for name, df in zip(["result_df.parquet", "df_ploshad_year.parquet", "df_itog_gtm_2.parquet", "factor_analysis_df.parquet"], build(args.seed)):
        df.to_parquet(out / name, index=False)
        print(out / name)

if __name__ == "__main__":
    main()
