from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv


@dataclass(frozen=True)
class LiteLLMConfig:
    base_url: str
    chat_url: str
    header_name: str
    header_prefix: str
    api_key: str
    default_model: str
    timeout: int


def load_config() -> LiteLLMConfig:
    load_dotenv()
    base_url = os.getenv("LITELLM_BASE_URL", "https://litellm.tatneft.guru").rstrip("/")
    return LiteLLMConfig(
        base_url=base_url,
        chat_url=os.getenv("LITELLM_CHAT_COMPLETIONS_URL", f"{base_url}/v1/chat/completions"),
        header_name=(os.getenv("LITELLM_AUTH_HEADER_NAME", "Authorization").strip() or "Authorization"),
        header_prefix=os.getenv("LITELLM_AUTH_HEADER_PREFIX", "").strip(),
        api_key=os.getenv("LITELLM_API_KEY", "").strip(),
        default_model=os.getenv("LITELLM_DEFAULT_MODEL", "default").strip() or "default",
        timeout=int(os.getenv("LITELLM_TIMEOUT", "30")),
    )


def auth_header_value(config: LiteLLMConfig) -> str:
    if not config.header_prefix:
        return config.api_key
    return f"{config.header_prefix} {config.api_key}"


def masked(value: str) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def request_json(url: str, config: LiteLLMConfig, payload: dict[str, Any] | None = None) -> tuple[int, str]:
    data = None
    method = "GET"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        method = "POST"
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    req.add_header(config.header_name, auth_header_value(config))
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=config.timeout) as response:
            return response.getcode(), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def connection_error_hint(exc: Exception) -> str:
    text = str(exc)
    parts = [f"ERROR: could not reach LiteLLM endpoint: {text}"]
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError) or isinstance(reason, socket.timeout) or "10060" in text or "timed out" in text.lower():
            parts.append(
                "HINT: connection timed out before LiteLLM answered. Check VPN/corporate network access, "
                "firewall rules, DNS/proxy settings, and whether the configured LiteLLM URL is reachable "
                "from this exact machine/container. If port 80 fails but the site opens in a browser, "
                "use LITELLM_BASE_URL=https://litellm.tatneft.guru and check port 443/proxy settings."
            )
        else:
            parts.append(
                "HINT: this is a network-level error before a LiteLLM HTTP response was received. "
                "Compare with: curl -vk --max-time 30 https://litellm.tatneft.guru/v1/models"
            )
    return "\n".join(parts)


def print_models(body: str) -> None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        print(body[:2000])
        return
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
        return
    ids = [item.get("id") for item in models if isinstance(item, dict) and item.get("id")]
    if not ids:
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
        return
    print("Available model ids:")
    for model_id in ids:
        print(f"- {model_id}")


def extract_chat_message(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()
    if isinstance(payload, dict) and isinstance(payload.get("choices"), list) and payload["choices"]:
        choice = payload["choices"][0]
        if isinstance(choice, dict):
            message = choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"].strip()
            if isinstance(choice.get("text"), str):
                return choice["text"].strip()
    return json.dumps(payload, ensure_ascii=False, indent=2)[:4000]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check LiteLLM availability from this project directory.")
    parser.add_argument("--prompt", help="Also send a chat completion test prompt with LITELLM_DEFAULT_MODEL.")
    args = parser.parse_args()

    config = load_config()
    print(f"LiteLLM base URL: {config.base_url}")
    print(f"Chat completions URL: {config.chat_url}")
    print(f"Auth header: {config.header_name}: {masked(auth_header_value(config))}")
    print(f"Default model: {config.default_model}")
    print(f"Timeout: {config.timeout}s")

    if not config.api_key:
        print("ERROR: LITELLM_API_KEY is empty. Put it into .env or export it before running the check.", file=sys.stderr)
        return 2

    models_url = f"{config.base_url}/v1/models"
    print(f"\nChecking models endpoint: {models_url}")
    try:
        status, body = request_json(models_url, config)
    except Exception as exc:
        print(connection_error_hint(exc), file=sys.stderr)
        return 1
    print(f"HTTP {status}")
    print_models(body)
    if status < 200 or status >= 300:
        return 1

    if args.prompt:
        print("\nChecking chat completions endpoint...")
        payload = {
            "model": config.default_model,
            "messages": [{"role": "user", "content": args.prompt}],
        }
        try:
            status, body = request_json(config.chat_url, config, payload)
        except Exception as exc:
            print(connection_error_hint(exc), file=sys.stderr)
            return 1
        print(f"HTTP {status}")
        if status >= 200 and status < 300:
            print("Assistant message:")
            print(extract_chat_message(body))
        else:
            print(body[:4000])
        if status < 200 or status >= 300:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
