CREATE UNIQUE INDEX IF NOT EXISTS ux_area_year_dataset_area_year
    ON area_year_metrics (dataset_version, kod_ploshchadi, year);

CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_area_dataset_area_current
    ON dim_area (dataset_version, kod_ploshchadi)
    WHERE is_current = TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS ux_monthly_dataset_area_well_date
    ON monthly_metrics (dataset_version, ploshad, well_uid, date)
    WHERE dataset_version IS NOT NULL AND ploshad IS NOT NULL AND well_uid IS NOT NULL AND date IS NOT NULL;

ALTER TABLE area_year_metrics
    ADD CONSTRAINT ck_area_year_nonnegative_flows CHECK (
        COALESCE(dobycha_nefti, 0) >= 0 AND COALESCE(dobycha_liq, 0) >= 0 AND
        COALESCE(dobycha_vody, 0) >= 0 AND COALESCE(zakachka, 0) >= 0 AND
        COALESCE(dobycha_nefti_cum, 0) >= 0 AND COALESCE(dobycha_liq_cum, 0) >= 0
    ) NOT VALID,
    ADD CONSTRAINT ck_area_year_percent_ranges CHECK (
        (wc IS NULL OR wc BETWEEN 0 AND 100) AND (kin IS NULL OR kin BETWEEN 0 AND 100) AND
        (kiz IS NULL OR kiz BETWEEN 0 AND 100) AND (niz_otbor IS NULL OR niz_otbor BETWEEN 0 AND 100)
    ) NOT VALID,
    ADD CONSTRAINT ck_area_year_nonnegative_funds CHECK (
        COALESCE(dob_fond, 0) >= 0 AND COALESCE(nagn_fond, 0) >= 0
    ) NOT VALID;

ALTER TABLE monthly_metrics
    ADD CONSTRAINT ck_monthly_rates_nonnegative CHECK (
        COALESCE(debit_neft, 0) >= 0 AND COALESCE(debit_liq, 0) >= 0 AND COALESCE(priemistost, 0) >= 0 AND
        (wc IS NULL OR wc BETWEEN 0 AND 100)
    ) NOT VALID;
