import urllib.error

from scripts.check_litellm import LiteLLMConfig, auth_header_value, connection_error_hint, masked


def test_auth_header_value_without_prefix():
    config = LiteLLMConfig(
        base_url="http://example.test",
        chat_url="http://example.test/v1/chat/completions",
        header_name="X-Key",
        header_prefix="",
        api_key="token",
        default_model="model",
        timeout=30,
    )

    assert auth_header_value(config) == "token"


def test_auth_header_value_with_prefix():
    config = LiteLLMConfig(
        base_url="http://example.test",
        chat_url="http://example.test/v1/chat/completions",
        header_name="Authorization",
        header_prefix="Bearer",
        api_key="token",
        default_model="model",
        timeout=30,
    )

    assert auth_header_value(config) == "Bearer token"


def test_masked_does_not_expose_full_token():
    assert masked("1234567890abcdef") == "1234...cdef"
    assert masked("short") == "***"


def test_connection_error_hint_for_windows_timeout():
    error = urllib.error.URLError(TimeoutError("[WinError 10060] timed out"))

    hint = connection_error_hint(error)

    assert "connection timed out" in hint
    assert "VPN" in hint
    assert "port 443" in hint
    assert "https://litellm.tatneft.guru" in hint
