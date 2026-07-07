import importlib
import json

import litellm_console


def test_litellm_config_uses_env_token_and_no_embedded_secret(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-token")
    monkeypatch.setenv("LITELLM_AUTH_HEADER_NAME", "X-Test-Key")
    monkeypatch.setenv("LITELLM_AUTH_HEADER_PREFIX", "")
    module = importlib.reload(litellm_console)

    assert module.UPSTREAM == "http://litellm.tatneft.guru/v1/chat/completions"
    assert module.SERVER_TOKEN == "test-token"
    assert module.AUTH_HEADER_NAME == "X-Test-Key"
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


def test_litellm_runtime_has_no_legacy_provider_symbols():
    runtime_files = ["app.py", "litellm_console.py", "docker-compose.yml"]
    for path in runtime_files:
        text = open(path, encoding="utf-8").read().lower()
        assert "qw" + "en" not in text
