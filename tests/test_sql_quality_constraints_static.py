from pathlib import Path

SQL = Path("sql/005_add_quality_constraints.sql").read_text()


def test_quality_indexes_present():
    assert "ux_area_year_dataset_area_year" in SQL
    assert "ux_dim_area_dataset_area_current" in SQL and "WHERE is_current = TRUE" in SQL
    assert "ux_monthly_dataset_area_well_date" in SQL


def test_quality_checks_not_valid_present():
    assert "ck_area_year_nonnegative_flows" in SQL
    assert "ck_area_year_percent_ranges" in SQL
    assert "ck_area_year_nonnegative_funds" in SQL
    assert "ck_monthly_rates_nonnegative" in SQL
    assert SQL.count("NOT VALID") >= 4
