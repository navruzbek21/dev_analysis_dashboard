from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = [
    ROOT / "app.py",
    ROOT / "config.py",
    ROOT / "services" / "data_service.py",
    ROOT / "docker-compose.yml",
]


def test_runtime_never_imports_sql_repository_or_db_layer():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in RUNTIME_FILES)

    forbidden_tokens = [
        "metrics_repository",
        "from db import",
        "import db",
        "DATABASE_URL",
        "dashboard_metadata",
        "DATA_SOURCE=sql",
    ]
    for token in forbidden_tokens:
        assert token not in combined


def test_data_service_reads_parquet_directly():
    source = (ROOT / "services" / "data_service.py").read_text(encoding="utf-8")

    assert "pd.read_parquet(settings.parquet_monthly_path)" in source
    assert "pd.read_parquet(settings.parquet_yearly_path)" in source
    assert "get_dataset_version_cached" in source
    assert "metrics_repository" not in source


def test_config_forces_parquet_mode():
    source = (ROOT / "config.py").read_text(encoding="utf-8")

    assert 'data_source: str = "parquet"' in source
    assert "Only parquet data source is supported" in source
    assert "database_url" not in source


def test_apply_dashboard_context_uses_current_dashboard_filters(monkeypatch):
    import analytics_tools

    monkeypatch.setattr(analytics_tools.data_service, "get_ngdu_options", lambda selected_mest=(): ["НГДУ 30", "НГДУ 31"])
    plan = {"tool": "gtm_efficiency", "params": {"filters": {}}}

    enriched = analytics_tools.apply_dashboard_context(plan, "эффективность ГТМ", {"mest": ["m1"], "ngdu": ["НГДУ 30"], "areas": []})

    assert enriched["params"]["filters"] == {"mest": ["m1"], "ngdu": ["НГДУ 30"]}


def test_apply_dashboard_context_infers_ngdu_from_text(monkeypatch):
    import analytics_tools

    monkeypatch.setattr(analytics_tools.data_service, "get_ngdu_options", lambda selected_mest=(): ["НГДУ 30", "НГДУ 31"])
    plan = {"tool": "gtm_efficiency", "params": {"filters": {}}}

    enriched = analytics_tools.apply_dashboard_context(plan, "эффективность ГТМ по НГДУ 30", {})

    assert enriched["params"]["filters"]["ngdu"] == ["НГДУ 30"]


def test_table_analysis_groups_and_aggregates(monkeypatch):
    import pandas as pd
    import analytics_tools

    df = pd.DataFrame(
        {
            "year": [2024, 2024, 2025],
            "ngdu": ["НГДУ 30", "НГДУ 31", "НГДУ 30"],
            "dobycha_nefti": [10.0, 20.0, 30.0],
        }
    )
    monkeypatch.setattr(analytics_tools, "_load_table_frame", lambda table, filters: df.copy())

    result = analytics_tools.table_analysis(
        {
            "table": "yearly",
            "where": {"ngdu": ["НГДУ 30"]},
            "group_by": ["year"],
            "metrics": [{"column": "dobycha_nefti", "agg": "sum", "alias": "oil"}],
            "sort_by": "year",
            "sort_desc": False,
        }
    )

    assert result.tool == "table_analysis"
    assert result.columns == ["year", "oil"]
    assert result.rows == [{"year": 2024, "oil": 10.0}, {"year": 2025, "oil": 30.0}]


def test_table_analysis_rejects_unknown_columns_and_caps_limit(monkeypatch):
    import pandas as pd
    import analytics_tools

    df = pd.DataFrame({"year": [2024, 2025], "value": [1, 2]})
    monkeypatch.setattr(analytics_tools, "_load_table_frame", lambda table, filters: df.copy())

    result = analytics_tools.table_analysis(
        {
            "table": "yearly",
            "group_by": ["missing"],
            "metrics": [{"column": "missing", "agg": "sum"}],
            "columns": ["year", "missing", "value"],
            "limit": 999,
        }
    )

    assert result.columns == ["year", "value"]
    assert result.summary["limit"] == 200


def test_apply_dashboard_context_infers_area_from_user_text(monkeypatch):
    import analytics_tools

    monkeypatch.setattr(analytics_tools.data_service, "get_area_options", lambda ngdu, mest: ["Альметьевская", "Березовская"])
    plan = {"tool": "metric_dynamics", "params": {"metric": "dobycha_nefti", "filters": {}}}

    enriched = analytics_tools.apply_dashboard_context(plan, "Добыча нефти по Альметьевской площади за последний год", {})

    assert enriched["params"]["filters"]["areas"] == ["Альметьевская"]
