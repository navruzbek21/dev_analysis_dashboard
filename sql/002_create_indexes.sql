CREATE INDEX IF NOT EXISTS ix_area_year_ngdu
    ON area_year_metrics (ngdu);

CREATE INDEX IF NOT EXISTS ix_area_year_mest
    ON area_year_metrics (mest);

CREATE INDEX IF NOT EXISTS ix_area_year_area
    ON area_year_metrics (kod_ploshchadi);

CREATE INDEX IF NOT EXISTS ix_area_year_year
    ON area_year_metrics (year);

CREATE INDEX IF NOT EXISTS ix_area_year_area_year
    ON area_year_metrics (kod_ploshchadi, year);

CREATE INDEX IF NOT EXISTS ix_area_year_ngdu_area_year
    ON area_year_metrics (ngdu, kod_ploshchadi, year);

CREATE INDEX IF NOT EXISTS ix_area_year_dataset_area_year
    ON area_year_metrics (dataset_version, kod_ploshchadi, year);

CREATE INDEX IF NOT EXISTS ix_area_year_dataset_mest_ngdu_area
    ON area_year_metrics (dataset_version, mest, ngdu, kod_ploshchadi);

CREATE INDEX IF NOT EXISTS ix_dim_area_dataset_ngdu_area
    ON dim_area (dataset_version, ngdu, kod_ploshchadi);

CREATE INDEX IF NOT EXISTS ix_monthly_area_date
    ON monthly_metrics (ploshad, date);

CREATE INDEX IF NOT EXISTS ix_monthly_ngdu_area_date
    ON monthly_metrics (ngdu, ploshad, date);
