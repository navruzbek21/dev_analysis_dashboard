from __future__ import annotations

import json
import logging
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from dash import html
from dotenv import load_dotenv
from flask import Response, jsonify, request

import analytics_tools

load_dotenv(os.getenv("ENV_FILE", ".env"))

logger = logging.getLogger(__name__)


LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "https://litellm.tatneft.guru").rstrip("/")
UPSTREAM = os.getenv("LITELLM_CHAT_COMPLETIONS_URL", f"{LITELLM_BASE_URL}/v1/chat/completions")
VERIFY_SSL = os.getenv("LITELLM_VERIFY_SSL", "true").strip().lower() not in {"0", "false", "no"}
CA_BUNDLE = os.getenv("LITELLM_CA_BUNDLE", "").strip()
TIMEOUT = int(os.getenv("LITELLM_TIMEOUT", "120"))
DEFAULT_MODEL = os.getenv("LITELLM_DEFAULT_MODEL", "default")
ALLOWED_MODELS = [
    model.strip()
    for model in os.getenv("LITELLM_ALLOWED_MODELS", "default").split(",")
    if model.strip()
]
AUTH_HEADER_NAME = os.getenv("LITELLM_AUTH_HEADER_NAME", "Authorization").strip() or "Authorization"
AUTH_HEADER_PREFIX = os.getenv("LITELLM_AUTH_HEADER_PREFIX", "").strip()
SERVER_TOKEN = os.getenv("LITELLM_API_KEY", "").strip()

# Защита прокси-endpoint'а: серверный токен LiteLLM тратится на каждый запрос,
# поэтому вход ограничиваем по размеру и частоте. Аутентификацию пользователей
# дашборда следует выполнять на уровне reverse-proxy перед приложением.
MAX_TEXT_CHARS = int(os.getenv("LITELLM_MAX_TEXT_CHARS", "32000"))
MAX_MESSAGES = int(os.getenv("LITELLM_MAX_MESSAGES", "40"))
MAX_MESSAGE_CHARS = int(os.getenv("LITELLM_MAX_MESSAGE_CHARS", "16000"))
RATE_LIMIT_REQUESTS = int(os.getenv("LITELLM_RATE_LIMIT_REQUESTS", "20"))
RATE_LIMIT_WINDOW_S = int(os.getenv("LITELLM_RATE_LIMIT_WINDOW_S", "60"))


class SlidingWindowRateLimiter:
    """Простой in-memory rate-limit на клиента (для одного процесса/воркера)."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, client_id: str) -> bool:
        if self.max_requests <= 0:
            return True
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = [ts for ts in self._hits.get(client_id, []) if ts > cutoff]
            if len(hits) >= self.max_requests:
                self._hits[client_id] = hits
                return False
            hits.append(now)
            self._hits[client_id] = hits
            if len(self._hits) > 10_000:
                self._hits = {
                    key: values
                    for key, values in self._hits.items()
                    if values and values[-1] > cutoff
                }
            return True


_rate_limiter = SlidingWindowRateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_S)


# HTML/CSS/JS консоли живут в templates/litellm_console.html, а не в
# python-строке: файл читается на каждый запрос страницы (страница открывается
# редко, зато шаблон можно править без рестарта).
_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "litellm_console.html"


def _load_template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def layout():
    return html.Div(
        html.Div(
            html.Iframe(
                src="/litellm-console",
                title="Консоль LiteLLM",
                className="litellm-console-frame",
            ),
            className="litellm-console-shell panel-card",
        ),
        className="litellm-console-tab",
    )


def make_auth_header_value(token: str) -> str:
    if not AUTH_HEADER_PREFIX:
        return token
    return f"{AUTH_HEADER_PREFIX} {token}"


def make_ctx(verify: bool) -> ssl.SSLContext:
    # LITELLM_CA_BUNDLE позволяет доверять внутреннему корпоративному CA
    # вместо отключения проверки сертификата целиком.
    ctx = ssl.create_default_context(cafile=CA_BUNDLE or None)
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def normalize_messages(messages, fallback_text: str) -> list[dict[str, str]]:
    normalized = []
    if isinstance(messages, list):
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role not in {"system", "user", "assistant"}:
                continue
            if not isinstance(content, str) or not content.strip():
                continue
            normalized.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})
    if normalized:
        # Клиентский буфер истории не является границей доверия — режем и здесь.
        return normalized[-MAX_MESSAGES:]
    return [{"role": "user", "content": fallback_text[:MAX_MESSAGE_CHARS]}]


def forward(token: str, text: str, model: str, dialogue_uuid: str | None = None, messages=None) -> dict:
    payload = {"model": model, "messages": normalize_messages(messages, text)}
    if dialogue_uuid:
        payload["user"] = dialogue_uuid
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def attempt(verify: bool):
        req = urllib.request.Request(UPSTREAM, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        req.add_header(AUTH_HEADER_NAME, make_auth_header_value(token))
        req.add_header("User-Agent", "tatneft-dashboard-litellm-console")
        try:
            with urllib.request.urlopen(req, context=make_ctx(verify), timeout=TIMEOUT) as resp:
                return resp.getcode(), resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    try:
        status, response_text = attempt(VERIFY_SSL)
        return {"upstream_status": status, "body": response_text}
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            # Никогда не откатываемся на соединение без проверки сертификата:
            # по нему уходит токен. Для внутреннего CA задайте LITELLM_CA_BUNDLE,
            # осознанное отключение проверки — только LITELLM_VERIFY_SSL=false.
            logger.error("SSL verification failed for LiteLLM upstream %s: %s", UPSTREAM, reason)
            return {
                "error": (
                    "SSL-проверка не пройдена. Укажите корпоративный сертификат через "
                    "LITELLM_CA_BUNDLE или осознанно задайте LITELLM_VERIFY_SSL=false."
                ),
                "kind": "ssl",
            }
        return {"error": str(reason), "kind": "network"}
    except Exception as exc:
        return {"error": str(exc), "kind": "network"}

def extract_litellm_message(raw_body: str) -> str:
    try:
        payload = json.loads(raw_body or "{}")
    except Exception:
        return (raw_body or "").strip()
    result = payload.get("result") if isinstance(payload, dict) else payload
    if isinstance(payload, dict) and isinstance(payload.get("choices"), list) and payload["choices"]:
        choice = payload["choices"][0]
        if isinstance(choice, dict):
            message = choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"].strip()
            if isinstance(choice.get("text"), str):
                return choice["text"].strip()
    if isinstance(result, dict):
        error = result.get("error_info") or result.get("error")
        if error:
            return error.get("message", str(error)) if isinstance(error, dict) else str(error)
        for key in ["message", "response", "text", "answer", "content", "output", "reply", "completion"]:
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return json.dumps(result, ensure_ascii=False)
    if isinstance(result, str):
        return result.strip()
    return json.dumps(result, ensure_ascii=False)


def litellm_prompt(prompt: str, model: str) -> str | None:
    token = SERVER_TOKEN.strip()
    if not token:
        return None
    result = forward(token, prompt, model)
    if result.get("error"):
        return None
    status = result.get("upstream_status")
    if status and (status < 200 or status >= 300):
        return None
    return extract_litellm_message(result.get("body") or "")


def run_analysis(text: str, model: str, dashboard_filters: dict | None = None) -> dict:
    raw_llm_plan = None
    plan_answer = litellm_prompt(analytics_tools.make_plan_prompt(text, dashboard_filters), model)
    if plan_answer:
        raw_llm_plan = analytics_tools.parse_plan(plan_answer)

    plan, plan_source = analytics_tools.make_analysis_plan(text, dashboard_filters, raw_llm_plan)
    result = analytics_tools.execute_plan(plan)

    if analytics_tools.requires_deterministic_explanation(result) and analytics_tools.has_selected_dashboard_filters(dashboard_filters):
        base_plan, _base_source = analytics_tools.make_analysis_plan(text, None, raw_llm_plan)
        fallback_result = analytics_tools.execute_plan(base_plan)
        if not analytics_tools.requires_deterministic_explanation(fallback_result):
            result = analytics_tools.with_note(
                fallback_result,
                "Фильтры текущего дашборда не дали строк; показан срез без этих фильтров.",
            )
            plan = base_plan

    explanation = None
    if not analytics_tools.requires_deterministic_explanation(result) and SERVER_TOKEN.strip():
        explanation = litellm_prompt(analytics_tools.make_explanation_prompt(text, plan, result), model)
    if not explanation:
        explanation = analytics_tools.fallback_explanation(text, result)
    return analytics_tools.result_to_payload(result, explanation, plan, plan_source)


def render_page() -> str:
    # Клиент ждёт чуть дольше сервера, чтобы не бросать запрос,
    # который upstream ещё обрабатывает.
    return (
        _load_template()
        .replace("__DEFAULT_MODEL__", json.dumps(DEFAULT_MODEL, ensure_ascii=False))
        .replace("__ALLOWED_MODELS__", json.dumps(ALLOWED_MODELS or [DEFAULT_MODEL], ensure_ascii=False))
        .replace("__CLIENT_TIMEOUT_MS__", str((TIMEOUT + 5) * 1000))
    )


def register_routes(server):
    @server.route("/litellm-console")
    def litellm_console_page():
        return Response(render_page(), content_type="text/html; charset=utf-8")

    @server.route("/litellm-console/health")
    def litellm_console_health():
        return jsonify({"ok": True, "upstream": UPSTREAM, "token_configured": bool(SERVER_TOKEN)})

    @server.route("/litellm-console/api", methods=["POST"])
    def litellm_console_api():
        client_id = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        if not _rate_limiter.allow(client_id):
            return jsonify({"error": "Слишком много запросов, попробуйте позже", "kind": "rate_limit"}), 429

        data = request.get_json(silent=True) or {}
        mode = (data.get("mode") or "chat").strip()
        token = SERVER_TOKEN.strip()
        text = data.get("text") or ""
        model = (data.get("model") or DEFAULT_MODEL).strip()
        dialogue_uuid = (data.get("dialogue_uuid") or "").strip() or None
        messages = data.get("messages")

        if not isinstance(text, str) or not text.strip():
            return jsonify({"error": "Пустой запрос", "kind": "client"}), 400
        if len(text) > MAX_TEXT_CHARS:
            return jsonify({"error": f"Запрос длиннее {MAX_TEXT_CHARS} символов", "kind": "client"}), 413
        if ALLOWED_MODELS and model not in ALLOWED_MODELS:
            model = DEFAULT_MODEL

        if mode == "analysis":
            try:
                return jsonify(run_analysis(text, model, data.get("dashboard_filters")))
            except Exception as exc:
                return jsonify({"error": str(exc), "kind": "analysis"}), 500

        if not token:
            return jsonify({"error": "Токен LiteLLM не настроен на сервере", "kind": "config"}), 500

        result = forward(token, text, model, dialogue_uuid, messages)
        return jsonify(result), 200 if not result.get("error") else 502
