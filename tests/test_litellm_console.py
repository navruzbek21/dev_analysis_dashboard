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
