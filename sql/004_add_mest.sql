ALTER TABLE dim_area
    ADD COLUMN IF NOT EXISTS mest VARCHAR(255) NULL;

ALTER TABLE monthly_metrics
    ADD COLUMN IF NOT EXISTS mest VARCHAR(255) NULL;

ALTER TABLE area_year_metrics
    ADD COLUMN IF NOT EXISTS mest VARCHAR(255) NULL;

CREATE INDEX IF NOT EXISTS ix_area_year_dataset_mest_ngdu_area
    ON area_year_metrics (dataset_version, mest, ngdu, kod_ploshchadi);
