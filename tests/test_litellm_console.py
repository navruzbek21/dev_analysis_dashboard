import importlib
import json

import litellm_console


def test_litellm_config_uses_env_token_and_no_embedded_secret(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-token")
    monkeypatch.setenv("LITELLM_AUTH_HEADER_NAME", "X-Test-Key")
    monkeypatch.setenv("LITELLM_AUTH_HEADER_PREFIX", "")
    module = importlib.reload(litellm_console)

    assert module.UPSTREAM == "https://litellm.tatneft.guru/v1/chat/completions"
    assert module.SERVER_TOKEN == "test-token"
    assert module.AUTH_HEADER_NAME == "X-Test-Key"
    assert module.make_auth_header_value("test-token") == "test-token"


def test_litellm_default_auth_prefix_is_empty(monkeypatch):
    monkeypatch.delenv("LITELLM_AUTH_HEADER_PREFIX", raising=False)
    module = importlib.reload(litellm_console)

    assert module.AUTH_HEADER_PREFIX == ""
    assert module.make_auth_header_value("test-token") == "test-token"


def test_extract_litellm_openai_chat_completion():
    raw = json.dumps({"choices": [{"message": {"content": "Ответ LiteLLM"}}]}, ensure_ascii=False)
    assert litellm_console.extract_litellm_message(raw) == "Ответ LiteLLM"


def test_render_page_injects_litellm_models(monkeypatch):
    monkeypatch.setenv("LITELLM_DEFAULT_MODEL", "model-a")
    monkeypatch.setenv("LITELLM_ALLOWED_MODELS", "model-a,model-b")
    module = importlib.reload(litellm_console)
    page = module.render_page()

    assert 'const DEFAULT_MODEL = "model-a";' in page
    assert 'const MODELS = ["model-a", "model-b"];' in page
    assert "Консоль LiteLLM" in page
    assert '<select class="litellm-model-input" id="modelInput"></select>' in page
    assert "<datalist" not in page
    assert "modelList" not in page
    assert "AbortController" in page


def test_litellm_runtime_has_no_legacy_provider_symbols():
    runtime_files = ["app.py", "litellm_console.py", "docker-compose.yml"]
    for path in runtime_files:
        text = open(path, encoding="utf-8").read().lower()
        assert "qw" + "en" not in text


def test_litellm_loads_dotenv_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_AUTH_HEADER_NAME", raising=False)
    monkeypatch.delenv("LITELLM_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("LITELLM_ALLOWED_MODELS", raising=False)
    tmp_path.joinpath(".env").write_text(
        "LITELLM_API_KEY=dotenv-token\n"
        "LITELLM_AUTH_HEADER_NAME=x-litellm-api-key\n"
        "LITELLM_DEFAULT_MODEL=qwen3.6-35b-a3b\n"
        "LITELLM_ALLOWED_MODELS=qwen3-32b,qwen3.6-35b-a3b\n",
        encoding="utf-8",
    )

    module = importlib.reload(litellm_console)

    assert module.SERVER_TOKEN == "dotenv-token"
    assert module.AUTH_HEADER_NAME == "x-litellm-api-key"
    assert module.DEFAULT_MODEL == "qwen3.6-35b-a3b"
    assert module.ALLOWED_MODELS == ["qwen3-32b", "qwen3.6-35b-a3b"]
    page = module.render_page()
    assert 'const DEFAULT_MODEL = "qwen3.6-35b-a3b";' in page
    assert 'const MODELS = ["qwen3-32b", "qwen3.6-35b-a3b"];' in page
    assert 'function normalizeStoredModel(model)' in page


def test_normalize_messages_accepts_litellm_chat_history():
    messages = [
        {"role": "user", "content": "Первый вопрос"},
        {"role": "assistant", "content": "Первый ответ"},
        {"role": "tool", "content": "ignored"},
        {"role": "user", "content": "Второй вопрос"},
    ]

    assert litellm_console.normalize_messages(messages, "fallback") == [
        {"role": "user", "content": "Первый вопрос"},
        {"role": "assistant", "content": "Первый ответ"},
        {"role": "user", "content": "Второй вопрос"},
    ]


def test_normalize_messages_falls_back_to_text():
    assert litellm_console.normalize_messages([], "fallback") == [{"role": "user", "content": "fallback"}]


def test_render_page_reads_dashboard_filters_for_analysis():
    page = litellm_console.render_page()

    assert 'function readDashboardFilters()' in page
    assert 'payload.dashboard_filters = readDashboardFilters();' in page


def test_run_analysis_passes_dashboard_filters(monkeypatch):
    captured = {"prompts": []}

    def fake_prompt(prompt, model):
        captured["prompts"].append(prompt)
        return None

    def fake_apply(plan, text, filters):
        captured["filters"] = filters
        return {"tool": "dataset_overview", "params": {"filters": filters or {}}}

    def fake_execute(plan):
        return litellm_console.analytics_tools.ToolResult(
            tool="dataset_overview",
            title="Обзор",
            chart_type="table",
            rows=[],
            columns=[],
            summary={},
        )

    monkeypatch.setattr(litellm_console, "litellm_prompt", fake_prompt)
    monkeypatch.setattr(litellm_console.analytics_tools, "apply_dashboard_context", fake_apply)
    monkeypatch.setattr(litellm_console.analytics_tools, "execute_plan", fake_execute)

    litellm_console.run_analysis("проанализируй текущий срез", "model-a", {"ngdu": ["НГДУ 30"]})

    assert any("Текущие фильтры дашборда" in prompt for prompt in captured["prompts"])
    assert captured["filters"] == {"ngdu": ["НГДУ 30"]}


def test_run_analysis_uses_deterministic_explanation_for_empty_data(monkeypatch):
    captured = {"explanation_prompts": 0}

    def fake_prompt(prompt, model):
        if "Ты аналитик нефтяного дашборда" in prompt:
            captured["explanation_prompts"] += 1
            return "На основе предоставленных данных можно сделать вывод, что данные не отражены."
        return '{"tool":"metric_dynamics","params":{"metric":"dobycha_nefti","filters":{}},"explain":true}'

    def fake_execute(plan):
        return litellm_console.analytics_tools.ToolResult(
            tool="metric_dynamics",
            title="Динамика: Добыча нефти",
            chart_type="line",
            rows=[],
            columns=["year", "value", "change_pct"],
            summary={"metric_label": "Добыча нефти", "last_year": None, "last_value": None, "last_change_pct": None},
            notes=["Площади: Альметьевская"],
        )

    monkeypatch.setattr(litellm_console, "SERVER_TOKEN", "token")
    monkeypatch.setattr(litellm_console, "litellm_prompt", fake_prompt)
    monkeypatch.setattr(litellm_console.analytics_tools, "execute_plan", fake_execute)

    payload = litellm_console.run_analysis("добыча нефти за последний год по Альметьевской площади", "model-a")

    assert captured["explanation_prompts"] == 0
    assert "нет строк" in payload["message"]
    assert "Альметьевская" in payload["message"]


def test_run_analysis_recovers_when_dashboard_filters_are_empty(monkeypatch):
    calls = []

    def fake_prompt(prompt, model):
        if "Ты аналитический диспетчер" in prompt:
            return '{"tool":"metric_dynamics","params":{"metric":"dobycha_nefti","filters":{}},"explain":true}'
        return None

    def fake_execute(plan):
        calls.append(plan)
        filters = plan.get("params", {}).get("filters", {})
        if filters.get("areas"):
            return litellm_console.analytics_tools.ToolResult(
                tool="metric_dynamics",
                title="Динамика: Добыча нефти",
                chart_type="line",
                rows=[],
                columns=["year", "value", "change_pct"],
                summary={"metric_label": "Добыча нефти"},
                notes=["Площади: Неточная площадь"],
            )
        return litellm_console.analytics_tools.ToolResult(
            tool="metric_dynamics",
            title="Динамика: Добыча нефти",
            chart_type="line",
            rows=[{"year": 2025, "value": 100.0, "change_pct": 5.0}],
            columns=["year", "value", "change_pct"],
            summary={"metric_label": "Добыча нефти", "last_year": 2025, "last_value": 100.0, "last_change_pct": 5.0},
            notes=[],
        )

    monkeypatch.setattr(litellm_console, "SERVER_TOKEN", "token")
    monkeypatch.setattr(litellm_console, "litellm_prompt", fake_prompt)
    monkeypatch.setattr(litellm_console.analytics_tools, "execute_plan", fake_execute)

    payload = litellm_console.run_analysis("проанализируй добычу нефти", "model-a", {"areas": ["Неточная площадь"]})

    assert len(calls) == 2
    assert payload["analysis"]["summary"]["dashboard_filter_recovery"] is True
    assert payload["analysis"]["rows"] == [{"year": 2025, "value": 100.0, "change_pct": 5.0}]
    assert any("Фильтры текущего дашборда не дали строк" in note for note in payload["analysis"]["notes"])
