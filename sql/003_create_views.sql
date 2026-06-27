CREATE OR REPLACE VIEW v_current_area_year_metrics AS
SELECT aym.*
FROM area_year_metrics aym
JOIN dashboard_metadata dm
  ON dm.dataset_name = 'area_metrics'
 AND dm.dataset_version = aym.dataset_version;

CREATE OR REPLACE VIEW v_current_dim_area AS
SELECT da.*
FROM dim_area da
JOIN dashboard_metadata dm
  ON dm.dataset_name = 'area_metrics'
 AND dm.dataset_version = da.dataset_version
WHERE da.is_current = TRUE;
