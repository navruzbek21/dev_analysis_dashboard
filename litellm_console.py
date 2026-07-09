from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request

from dash import html
from flask import Response, jsonify, request
from dotenv import load_dotenv

import analytics_tools


load_dotenv(os.getenv("ENV_FILE", ".env"))


LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "https://litellm.tatneft.guru").rstrip("/")
UPSTREAM = os.getenv("LITELLM_CHAT_COMPLETIONS_URL", f"{LITELLM_BASE_URL}/v1/chat/completions")
VERIFY_SSL = os.getenv("LITELLM_VERIFY_SSL", "true").strip().lower() not in {"0", "false", "no"}
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


HTML_TEMPLATE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Консоль LiteLLM</title>
<style>
:root {
  --op-bg: #F7F8F5;
  --op-card: #FFFFFF;
  --op-card-2: #F1F5EF;
  --op-border: #DDE7E1;
  --op-grid: #E5EDE8;
  --op-ink: #1F2B25;
  --op-muted: #6F7D76;
  --op-green: #008E5B;
  --op-green-2: #00B473;
  --op-green-deep: #006B45;
  --op-green-light: #C5E5D7;
  --op-red: #D53033;
  --op-red-light: #F2C0C1;
  --op-amber: #F2B84B;
  --font-body: "Montserrat", "Segoe UI", Arial, sans-serif;
  --font-mono: "Montserrat", "Segoe UI", Arial, sans-serif;
  --shadow: 0 10px 28px rgba(0, 68, 43, .06);
}

:root[data-theme="dark"] {
  --op-bg: #101815;
  --op-card: #17211D;
  --op-card-2: #1F2B26;
  --op-border: #314138;
  --op-grid: #24352D;
  --op-ink: #E8F0EC;
  --op-muted: #A8B9B0;
  --op-green: #20C987;
  --op-green-2: #32D89B;
  --op-green-deep: #0A9B69;
  --op-green-light: #245B44;
  --op-red: #FF6B70;
  --op-red-light: #4A2428;
  --op-amber: #F2C66D;
  --shadow: 0 10px 28px rgba(0, 0, 0, .24);
}

* { box-sizing: border-box; }
html,
body {
  width: 100%;
  height: 100%;
  margin: 0;
  overflow: hidden;
  background: var(--op-bg);
  color: var(--op-ink);
  font-family: var(--font-body);
}

button,
input,
select,
textarea {
  font: inherit;
}

.litellm-shell {
  display: grid;
  grid-template-columns: 286px minmax(0, 1fr);
  width: 100%;
  height: 100vh;
  background: var(--op-bg);
}

.litellm-sidebar {
  min-width: 0;
  border-right: 1px solid var(--op-border);
  background: var(--op-card);
  display: flex;
  flex-direction: column;
}

.litellm-brand {
  border-left: 6px solid var(--op-green);
  padding: 16px 16px 14px 18px;
  border-bottom: 1px solid var(--op-border);
}

.litellm-brand-title {
  color: var(--op-green);
  font-size: 1rem;
  font-weight: 800;
  letter-spacing: .02em;
  text-transform: uppercase;
}

.litellm-brand-subtitle {
  margin-top: 4px;
  color: var(--op-muted);
  font-size: .78rem;
  font-weight: 500;
}

.litellm-new-chat {
  margin: 14px 14px 8px;
  padding: 10px 12px;
  border: 1px solid var(--op-green);
  border-radius: 0;
  background: var(--op-green);
  color: #FFFFFF;
  cursor: pointer;
  font-weight: 800;
  transition: background .15s, border-color .15s, transform .15s;
}

.litellm-new-chat:hover {
  background: var(--op-green-deep);
  border-color: var(--op-green-deep);
  transform: translateY(-1px);
}

.litellm-chat-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 4px 10px 10px;
}

.litellm-chat-item {
  display: flex;
  gap: 8px;
  align-items: center;
  min-height: 48px;
  padding: 8px 9px;
  margin-bottom: 4px;
  border: 1px solid transparent;
  cursor: pointer;
}

.litellm-chat-item:hover {
  background: var(--op-card-2);
}

.litellm-chat-item.active {
  background: var(--op-card-2);
  border-color: var(--op-green-light);
  border-left: 4px solid var(--op-green);
}

.litellm-chat-meta {
  flex: 1;
  min-width: 0;
}

.litellm-chat-title {
  overflow: hidden;
  color: var(--op-ink);
  font-size: .86rem;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.litellm-chat-model {
  margin-top: 2px;
  color: var(--op-muted);
  font-family: var(--font-mono);
  font-size: .68rem;
}

.litellm-chat-delete {
  width: 28px;
  height: 28px;
  border: 0;
  background: transparent;
  color: var(--op-muted);
  cursor: pointer;
  opacity: 0;
}

.litellm-chat-item:hover .litellm-chat-delete {
  opacity: 1;
}

.litellm-chat-delete:hover {
  color: var(--op-red);
  background: var(--op-red-light);
}

.litellm-settings {
  border-top: 1px solid var(--op-border);
  padding: 13px 14px 14px;
}

.litellm-field {
  display: block;
  margin-bottom: 10px;
}

.litellm-field:last-child {
  margin-bottom: 0;
}

.litellm-label {
  display: block;
  margin-bottom: 6px;
  color: var(--op-green);
  font-size: .67rem;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}

.litellm-control {
  width: 100%;
  min-height: 38px;
  border: 1px solid var(--op-border);
  border-radius: 0;
  background: var(--op-card);
  color: var(--op-ink);
  outline: 0;
  padding: 8px 10px;
}

.litellm-control:focus {
  border-color: var(--op-green);
  box-shadow: 0 0 0 3px rgba(0, 142, 91, .08);
}

.litellm-main {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.litellm-topbar {
  flex: none;
  display: grid;
  grid-template-columns: auto minmax(160px, 1fr) minmax(150px, 240px) auto;
  gap: 10px;
  align-items: center;
  padding: 12px 14px;
  border-bottom: 1px solid var(--op-border);
  background: var(--op-card);
}

.litellm-sidebar-toggle {
  display: none;
  width: 38px;
  height: 38px;
  border: 1px solid var(--op-border);
  background: var(--op-card);
  color: var(--op-green);
  cursor: pointer;
  font-weight: 800;
}

.litellm-title-input,
.litellm-model-input {
  width: 100%;
  min-height: 38px;
  border: 1px solid var(--op-border);
  background: var(--op-card);
  color: var(--op-ink);
  outline: 0;
  padding: 8px 10px;
  font-weight: 700;
}

.litellm-title-input:focus,
.litellm-model-input:focus {
  border-color: var(--op-green);
  box-shadow: 0 0 0 3px rgba(0, 142, 91, .08);
}

.litellm-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--op-muted);
  font-size: .74rem;
  font-weight: 700;
  white-space: nowrap;
}

.litellm-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--op-muted);
}

.litellm-dot.ok { background: var(--op-green-2); }
.litellm-dot.warn { background: var(--op-amber); }
.litellm-dot.err { background: var(--op-red); }
.litellm-dot.busy {
  background: var(--op-green);
  animation: litellmPulse 1s ease-in-out infinite;
}

@keyframes litellmPulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: .4; transform: scale(.7); }
}

.litellm-feed {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background:
    linear-gradient(90deg, rgba(0,142,91,.05) 0 1px, transparent 1px),
    linear-gradient(180deg, rgba(0,142,91,.04) 0 1px, transparent 1px),
    var(--op-bg);
  background-size: 22px 22px;
}

.litellm-thread {
  width: min(920px, 100%);
  margin: 0 auto;
  padding: 18px;
}

.litellm-empty {
  margin-top: 46px;
  padding: 24px;
  border: 1px solid var(--op-border);
  border-left: 6px solid var(--op-green);
  background: var(--op-card);
  color: var(--op-muted);
  box-shadow: var(--shadow);
}

.litellm-empty strong {
  display: block;
  margin-bottom: 4px;
  color: var(--op-green);
  text-transform: uppercase;
}

.litellm-msg {
  margin-bottom: 14px;
  border: 1px solid var(--op-border);
  background: var(--op-card);
  box-shadow: var(--shadow);
}

.litellm-msg.user {
  border-left: 5px solid var(--op-amber);
}

.litellm-msg.bot {
  border-left: 5px solid var(--op-green);
}

.litellm-msg.error {
  border-left-color: var(--op-red);
}

.litellm-msg-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--op-border);
  background: var(--op-card-2);
  color: var(--op-muted);
  font-size: .72rem;
  font-weight: 800;
  letter-spacing: .06em;
  text-transform: uppercase;
}

.litellm-msg-head .litellm-copy {
  margin-left: auto;
}

.litellm-copy {
  border: 1px solid var(--op-border);
  background: var(--op-card);
  color: var(--op-muted);
  cursor: pointer;
  padding: 4px 8px;
  font-size: .68rem;
  font-weight: 800;
}

.litellm-copy:hover {
  border-color: var(--op-green);
  color: var(--op-green);
}

.litellm-msg-body {
  padding: 13px 14px;
  color: var(--op-ink);
  font-size: .92rem;
  line-height: 1.62;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.litellm-msg-body.rich {
  white-space: normal;
}

.litellm-msg-body p { margin: 0 0 10px; }
.litellm-msg-body h2,
.litellm-msg-body h3,
.litellm-msg-body h4 {
  margin: 14px 0 8px;
  color: var(--op-green);
}
.litellm-msg-body ul,
.litellm-msg-body ol {
  margin: 0 0 10px;
  padding-left: 22px;
}
.litellm-msg-body pre {
  overflow: auto;
  margin: 0 0 12px;
  padding: 12px;
  background: #0E1726;
  color: #D9E2EC;
}
.litellm-msg-body code {
  font-family: var(--font-mono);
}
.litellm-msg-body code:not(pre code) {
  border: 1px solid var(--op-border);
  background: var(--op-card-2);
  padding: 1px 5px;
}
.litellm-msg-body a {
  color: var(--op-green);
}

.analysis-result {
  display: grid;
  gap: 12px;
}

.analysis-card {
  border: 1px solid var(--op-border);
  background: var(--op-card-2);
  padding: 12px;
}

.analysis-card-title {
  margin-bottom: 8px;
  color: var(--op-green);
  font-size: .78rem;
  font-weight: 800;
  letter-spacing: .06em;
  text-transform: uppercase;
}

.analysis-chart {
  overflow-x: auto;
  background: var(--op-card);
}

.analysis-chart-svg {
  display: block;
  width: 100%;
  min-width: 560px;
  height: auto;
}

.analysis-table-wrap {
  overflow: auto;
  max-height: 260px;
  border: 1px solid var(--op-border);
}

.analysis-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--op-card);
  font-size: .78rem;
}

.analysis-table th,
.analysis-table td {
  padding: 7px 8px;
  border-bottom: 1px solid var(--op-border);
  text-align: left;
  vertical-align: top;
}

.analysis-table th {
  position: sticky;
  top: 0;
  background: var(--op-card-2);
  color: var(--op-green);
  font-weight: 800;
}

.analysis-notes {
  color: var(--op-muted);
  font-size: .78rem;
}

.litellm-reasoning {
  margin: 0 0 12px;
  border: 1px solid var(--op-border);
  background: var(--op-card-2);
}
.litellm-reasoning summary {
  cursor: pointer;
  padding: 8px 10px;
  color: var(--op-green);
  font-weight: 800;
}
.litellm-reasoning-body {
  border-top: 1px solid var(--op-border);
  padding: 10px;
}

.litellm-composer-wrap {
  flex: none;
  border-top: 1px solid var(--op-border);
  background: var(--op-card);
  padding: 12px 14px;
}

.litellm-composer {
  width: min(920px, 100%);
  margin: 0 auto;
  border: 1px solid var(--op-border);
  border-left: 6px solid var(--op-green);
  background: var(--op-card);
  box-shadow: var(--shadow);
}

.litellm-prompt {
  display: block;
  width: 100%;
  min-height: 58px;
  max-height: 220px;
  resize: none;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--op-ink);
  padding: 13px 14px 5px;
  line-height: 1.55;
}

.litellm-composer-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 8px 10px 10px 14px;
}

.litellm-hint {
  color: var(--op-muted);
  font-size: .72rem;
  font-weight: 600;
}

.litellm-send {
  min-width: 126px;
  border: 1px solid var(--op-green);
  background: var(--op-green);
  color: #FFFFFF;
  cursor: pointer;
  padding: 9px 14px;
  font-weight: 800;
}

.litellm-send:hover {
  background: var(--op-green-deep);
  border-color: var(--op-green-deep);
}

.litellm-send:disabled {
  cursor: wait;
  opacity: .65;
}

.litellm-backdrop {
  display: none;
}

@media (max-width: 760px) {
  .litellm-shell {
    grid-template-columns: 1fr;
  }
  .litellm-sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 30;
    width: 286px;
    transform: translateX(-100%);
    transition: transform .18s ease;
  }
  .litellm-shell.sidebar-open .litellm-sidebar {
    transform: none;
  }
  .litellm-backdrop {
    position: fixed;
    inset: 0;
    z-index: 20;
    background: rgba(0, 0, 0, .36);
  }
  .litellm-shell.sidebar-open .litellm-backdrop {
    display: block;
  }
  .litellm-sidebar-toggle {
    display: inline-block;
  }
  .litellm-topbar {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .litellm-model-input,
  .litellm-status {
    grid-column: 1 / -1;
  }
  .litellm-hint {
    display: none;
  }
}
</style>
</head>
<body>
<div class="litellm-shell" id="litellmShell">
  <aside class="litellm-sidebar">
    <div class="litellm-brand">
      <div class="litellm-brand-title">Консоль LiteLLM</div>
      <div class="litellm-brand-subtitle">Прокси LiteLLM внутри дашборда</div>
    </div>
    <button class="litellm-new-chat" id="newChatBtn" type="button">Новый чат</button>
    <div class="litellm-chat-list" id="chatList"></div>
    <div class="litellm-settings">
      <label class="litellm-field">
        <span class="litellm-label">Режим</span>
        <select class="litellm-control" id="workMode">
          <option value="chat">Чат LiteLLM</option>
          <option value="analysis">Анализ данных</option>
        </select>
      </label>
      <label class="litellm-field">
        <span class="litellm-label">Память</span>
        <select class="litellm-control" id="memoryMode">
          <option value="context">Контекст в запросе</option>
          <option value="server">Сессия LiteLLM</option>
          <option value="off">Без памяти</option>
        </select>
      </label>
    </div>
  </aside>
  <div class="litellm-backdrop" id="backdrop"></div>
  <main class="litellm-main">
    <header class="litellm-topbar">
      <button class="litellm-sidebar-toggle" id="sidebarToggle" type="button">☰</button>
      <input class="litellm-title-input" id="chatTitle" placeholder="Новый чат" spellcheck="false">
      <select class="litellm-model-input" id="modelInput"></select>
      <div class="litellm-status"><span class="litellm-dot ok" id="statusDot"></span><span id="statusText">готов</span></div>
    </header>
    <div class="litellm-feed" id="feed"><div class="litellm-thread" id="thread"></div></div>
    <div class="litellm-composer-wrap">
      <div class="litellm-composer">
        <textarea class="litellm-prompt" id="prompt" rows="1" placeholder="Напишите запрос..."></textarea>
        <div class="litellm-composer-foot">
          <span class="litellm-hint">Enter отправляет, Shift+Enter переносит строку</span>
          <button class="litellm-send" id="sendBtn" type="button">Отправить</button>
        </div>
      </div>
    </div>
  </main>
</div>
<script>
const LS_KEY = "litellm_console_dashboard_v1";
const DEFAULT_MODEL = __DEFAULT_MODEL__;
const MODELS = __ALLOWED_MODELS__;
const $ = selector => document.querySelector(selector);

const shell = $("#litellmShell");
const chatList = $("#chatList");
const thread = $("#thread");
const feed = $("#feed");
const workModeEl = $("#workMode");
const memoryEl = $("#memoryMode");
const titleEl = $("#chatTitle");
const modelEl = $("#modelInput");
const promptEl = $("#prompt");
const sendBtn = $("#sendBtn");
const statusText = $("#statusText");
const statusDot = $("#statusDot");

let busy = false;
let state = { chats: [], activeId: null, workMode: "chat", memoryMode: "context", lastModel: DEFAULT_MODEL };

function decodeDashStore(value) {
  if (!value) return "light";
  try {
    const parsed = JSON.parse(value);
    return parsed === "dark" ? "dark" : "light";
  } catch (_) {
    return value === "dark" ? "dark" : "light";
  }
}

function syncTheme() {
  document.documentElement.dataset.theme = decodeDashStore(localStorage.getItem("theme-store"));
}

window.addEventListener("storage", event => {
  if (event.key === "theme-store") syncTheme();
});
syncTheme();
setInterval(syncTheme, 1000);

function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

function blankChat() {
  return { id: uid(), title: "", model: state.lastModel || DEFAULT_MODEL, messages: [], dialogueUuid: null, createdAt: Date.now() };
}

function activeChat() {
  return state.chats.find(chat => chat.id === state.activeId);
}

function normalizeStoredModel(model) {
  if (!model || model === "default") return DEFAULT_MODEL;
  if (MODELS.length && !MODELS.includes(model)) return DEFAULT_MODEL;
  return model;
}

function load() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) state = Object.assign(state, JSON.parse(raw));
  } catch (_) {}
  if (!Array.isArray(state.chats)) state.chats = [];
  if (!state.workMode) state.workMode = "chat";
  if (!state.memoryMode) state.memoryMode = "context";
  state.lastModel = normalizeStoredModel(state.lastModel);
  state.chats.forEach(chat => { chat.model = normalizeStoredModel(chat.model); });
  delete state.token;
  if (!state.chats.length) {
    const chat = blankChat();
    state.chats.push(chat);
    state.activeId = chat.id;
  }
  if (!state.activeId || !state.chats.find(chat => chat.id === state.activeId)) {
    state.activeId = state.chats[0].id;
  }
}

function save() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(state)); } catch (_) {}
}

function setStatus(text, kind) {
  statusText.textContent = text;
  statusDot.className = "litellm-dot" + (kind ? " " + kind : "");
}

function refreshStatus() {
  setStatus(state.workMode === "analysis" ? "анализ данных" : "готов", "ok");
}

function fmtTime(ts) {
  return new Date(ts).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function escapeHtml(value) {
  return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function mdInline(value) {
  let text = value.replace(/`([^`]+)`/g, "<code>$1</code>");
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return text;
}

function renderMarkdown(markdown) {
  const lines = escapeHtml(markdown || "").replace(/\r\n/g, "\n").split("\n");
  let html = "";
  let paragraph = [];
  let listType = null;

  function flushParagraph() {
    if (!paragraph.length) return;
    html += "<p>" + mdInline(paragraph.join(" ")) + "</p>";
    paragraph = [];
  }

  function closeList() {
    if (!listType) return;
    html += "</" + listType + ">";
    listType = null;
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^```/.test(line)) {
      flushParagraph();
      closeList();
      const code = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) {
        code.push(lines[i]);
        i += 1;
      }
      html += "<pre><code>" + code.join("\n") + "</code></pre>";
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeList();
      const level = heading[1].length + 1;
      html += "<h" + level + ">" + mdInline(heading[2]) + "</h" + level + ">";
      continue;
    }
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      if (listType !== "ul") {
        closeList();
        html += "<ul>";
        listType = "ul";
      }
      html += "<li>" + mdInline(bullet[1]) + "</li>";
      continue;
    }
    const numbered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (numbered) {
      flushParagraph();
      if (listType !== "ol") {
        closeList();
        html += "<ol>";
        listType = "ol";
      }
      html += "<li>" + mdInline(numbered[1]) + "</li>";
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      closeList();
      continue;
    }
    closeList();
    paragraph.push(line.trim());
  }
  flushParagraph();
  closeList();
  return html || "<p></p>";
}

function readDashboardFilters() {
  try {
    if (window.parent && window.parent !== window && window.parent.localStorage) {
      const raw = window.parent.localStorage.getItem("dashboard-analysis-filters");
      if (raw) return JSON.parse(raw);
    }
  } catch (_) {}
  try {
    const raw = localStorage.getItem("dashboard-analysis-filters");
    return raw ? JSON.parse(raw) : {};
  } catch (_) { return {}; }
}

function parseResult(raw) {
  let payload;
  try { payload = JSON.parse(raw); } catch (_) { return { message: (raw || "").trim() || "(пустой ответ)" }; }
  if (payload && typeof payload === "object" && Array.isArray(payload.choices) && payload.choices.length) {
    const choice = payload.choices[0] || {};
    const content = choice.message && typeof choice.message.content === "string" ? choice.message.content : choice.text;
    if (typeof content === "string" && content.trim()) return { message: content.trim() };
  }
  const result = payload && typeof payload === "object" && payload.result && typeof payload.result === "object" ? payload.result : payload;
  if (result && typeof result === "object") {
    const error = result.error_info ?? result.error;
    if (error) return { error: typeof error === "string" ? error : (error.message || JSON.stringify(error)) };
    const keys = ["message", "response", "text", "answer", "content", "output", "reply", "completion"];
    let message = "";
    for (const key of keys) {
      if (typeof result[key] === "string" && result[key].trim()) {
        message = result[key];
        break;
      }
    }
    if (!message) message = JSON.stringify(result, null, 2);
    return {
      message: message.trim(),
      reasoning: typeof result.reasoning === "string" ? result.reasoning.trim() : "",
      docs: Array.isArray(result.docs) ? result.docs : [],
      dialogueUuid: typeof result.dialogue_uuid === "string" ? result.dialogue_uuid : ""
    };
  }
  return { message: typeof result === "string" ? result : JSON.stringify(result, null, 2) };
}

function scrollBottom() {
  feed.scrollTop = feed.scrollHeight;
}

function messageNode(message) {
  const outer = document.createElement("article");
  outer.className = "litellm-msg " + (message.role === "user" ? "user" : "bot") + (message.error ? " error" : "");
  const head = document.createElement("div");
  head.className = "litellm-msg-head";
  const who = document.createElement("span");
  who.textContent = message.role === "user" ? "Вы" : (message.error ? "Ошибка" : (message.model || "LiteLLM"));
  const meta = document.createElement("span");
  meta.textContent = fmtTime(message.ts);
  const copy = document.createElement("button");
  copy.className = "litellm-copy";
  copy.type = "button";
  copy.textContent = "копировать";
  copy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(message.text || "");
      copy.textContent = "скопировано";
      setTimeout(() => copy.textContent = "копировать", 1200);
    } catch (_) {}
  };
  head.append(who, meta, copy);
  const body = document.createElement("div");
  body.className = "litellm-msg-body";
  if (message.role === "bot" && !message.error && message.analysis) {
    body.classList.add("rich");
    body.append(renderAnalysis(message.text || "", message.analysis));
  } else if (message.role === "bot" && !message.error) {
    body.classList.add("rich");
    body.innerHTML = renderMarkdown(message.text || "");
  } else {
    body.textContent = message.text || "";
  }
  outer.append(head, body);
  return outer;
}

function renderAnalysis(text, analysis) {
  const wrap = document.createElement("div");
  wrap.className = "analysis-result";
  const narrative = document.createElement("div");
  narrative.innerHTML = renderMarkdown(text || "");
  wrap.append(narrative);

  if (analysis && analysis.chart && analysis.chart.svg) {
    const chartCard = document.createElement("section");
    chartCard.className = "analysis-card";
    const title = document.createElement("div");
    title.className = "analysis-card-title";
    title.textContent = analysis.title || "График";
    const chart = document.createElement("div");
    chart.className = "analysis-chart";
    chart.innerHTML = analysis.chart.svg;
    chartCard.append(title, chart);
    wrap.append(chartCard);
  }

  if (analysis && Array.isArray(analysis.rows) && analysis.rows.length) {
    const tableCard = document.createElement("section");
    tableCard.className = "analysis-card";
    const title = document.createElement("div");
    title.className = "analysis-card-title";
    title.textContent = "Данные";
    const tableWrap = document.createElement("div");
    tableWrap.className = "analysis-table-wrap";
    const table = document.createElement("table");
    table.className = "analysis-table";
    const columns = Array.isArray(analysis.columns) && analysis.columns.length ? analysis.columns : Object.keys(analysis.rows[0]);
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    columns.forEach(column => {
      const th = document.createElement("th");
      th.textContent = column;
      headRow.append(th);
    });
    thead.append(headRow);
    const tbody = document.createElement("tbody");
    analysis.rows.slice(0, 60).forEach(row => {
      const tr = document.createElement("tr");
      columns.forEach(column => {
        const td = document.createElement("td");
        td.textContent = formatCell(row[column]);
        tr.append(td);
      });
      tbody.append(tr);
    });
    table.append(thead, tbody);
    tableWrap.append(table);
    tableCard.append(title, tableWrap);
    if (analysis.row_count > 60) {
      const more = document.createElement("div");
      more.className = "analysis-notes";
      more.textContent = "Показаны первые 60 строк из " + analysis.row_count + ".";
      tableCard.append(more);
    }
    wrap.append(tableCard);
  }

  if (analysis && Array.isArray(analysis.notes) && analysis.notes.length) {
    const notes = document.createElement("div");
    notes.className = "analysis-notes";
    notes.textContent = analysis.notes.join(" · ");
    wrap.append(notes);
  }
  return wrap;
}

function formatCell(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "";
    return Math.abs(value) >= 100 ? value.toLocaleString("ru-RU", { maximumFractionDigits: 0 }) : value.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
  }
  return String(value);
}

function pendingNode(model) {
  const node = messageNode({ role: "bot", text: "Запрос отправлен...", ts: Date.now(), model });
  node.classList.add("pending");
  node.querySelector(".litellm-msg-body").textContent = "Запрос отправлен...";
  return node;
}

function renderSidebar() {
  chatList.innerHTML = "";
  state.chats.forEach(chat => {
    const item = document.createElement("div");
    item.className = "litellm-chat-item" + (chat.id === state.activeId ? " active" : "");
    const meta = document.createElement("div");
    meta.className = "litellm-chat-meta";
    const title = document.createElement("div");
    title.className = "litellm-chat-title";
    title.textContent = chat.title || "Новый чат";
    const model = document.createElement("div");
    model.className = "litellm-chat-model";
    model.textContent = chat.model || DEFAULT_MODEL;
    meta.append(title, model);
    const del = document.createElement("button");
    del.className = "litellm-chat-delete";
    del.type = "button";
    del.title = "Удалить чат";
    del.textContent = "×";
    del.onclick = event => {
      event.stopPropagation();
      deleteChat(chat.id);
    };
    item.append(meta, del);
    item.onclick = () => selectChat(chat.id);
    chatList.append(item);
  });
}

function renderThread() {
  const chat = activeChat();
  thread.innerHTML = "";
  if (!chat.messages.length) {
    const empty = document.createElement("div");
    empty.className = "litellm-empty";
    empty.innerHTML = "<strong>Новый чат</strong><span>Задайте первый вопрос.</span>";
    thread.append(empty);
    return;
  }
  chat.messages.forEach(message => thread.append(messageNode(message)));
  scrollBottom();
}

function renderModels() {
  const values = MODELS.length ? MODELS : [DEFAULT_MODEL];
  modelEl.innerHTML = "";
  values.forEach(model => {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    modelEl.append(option);
  });
}

function renderActive() {
  const chat = activeChat();
  renderModels();
  titleEl.value = chat.title || "";
  modelEl.value = normalizeStoredModel(chat.model || DEFAULT_MODEL);
  workModeEl.value = state.workMode || "chat";
  memoryEl.value = state.memoryMode || "context";
  renderSidebar();
  renderThread();
  refreshStatus();
}

function newChat() {
  const chat = blankChat();
  state.chats.unshift(chat);
  state.activeId = chat.id;
  save();
  renderActive();
  closeSidebar();
  promptEl.focus();
}

function selectChat(id) {
  state.activeId = id;
  save();
  renderActive();
  closeSidebar();
}

function deleteChat(id) {
  const index = state.chats.findIndex(chat => chat.id === id);
  if (index < 0) return;
  state.chats.splice(index, 1);
  if (!state.chats.length) {
    const chat = blankChat();
    state.chats.push(chat);
    state.activeId = chat.id;
  } else if (state.activeId === id) {
    state.activeId = state.chats[Math.max(0, index - 1)].id;
  }
  save();
  renderActive();
}

function buildMessages(chat) {
  const useContext = state.memoryMode === "context" || state.memoryMode === "server";
  const source = useContext ? chat.messages : chat.messages.slice(-1);
  const messages = [];
  let budget = 16000;
  for (let i = source.length - 1; i >= 0; i--) {
    const item = source[i];
    if (item.error || !item.text) continue;
    const role = item.role === "bot" ? "assistant" : "user";
    const content = String(item.text);
    budget -= content.length + role.length + 8;
    if (budget < 0 && messages.length) break;
    messages.unshift({ role, content });
  }
  return messages.length ? messages : [{ role: "user", content: "" }];
}

function autosize() {
  promptEl.style.height = "auto";
  promptEl.style.height = Math.min(promptEl.scrollHeight, 220) + "px";
}

async function send() {
  if (busy) return;
  const text = promptEl.value.trim();
  const chat = activeChat();
  const model = (modelEl.value.trim() || DEFAULT_MODEL);
  if (!text) {
    promptEl.focus();
    return;
  }

  chat.model = model;
  state.lastModel = model;
  if (!chat.title) {
    chat.title = text.slice(0, 44);
    titleEl.value = chat.title;
  }
  const userMessage = { role: "user", text, ts: Date.now() };
  chat.messages.push(userMessage);
  promptEl.value = "";
  autosize();
  save();
  renderSidebar();
  const empty = thread.querySelector(".litellm-empty");
  if (empty) empty.remove();
  thread.append(messageNode(userMessage));
  const pending = pendingNode(model);
  thread.append(pending);
  scrollBottom();

  busy = true;
  sendBtn.disabled = true;
  const isAnalysis = state.workMode === "analysis";
  setStatus(isAnalysis ? "анализ" : "отправка", "busy");
  const payload = { mode: state.workMode, text, model, memory: state.memoryMode };
  if (isAnalysis) payload.dashboard_filters = readDashboardFilters();
  if (!isAnalysis) payload.messages = buildMessages(chat);
  if (!isAnalysis && state.memoryMode === "server" && chat.dialogueUuid) payload.dialogue_uuid = chat.dialogueUuid;
  const started = performance.now();

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 45000);

  try {
    const response = await fetch("/litellm-console/api", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal
    });
    const elapsed = Math.round(performance.now() - started);
    let data;
    try { data = await response.json(); } catch (_) { data = { error: "Некорректный ответ прокси" }; }
    if (!response.ok || data.error) {
      const message = data.error || ("HTTP " + response.status);
      pending.replaceWith(messageNode({ role: "bot", error: true, text: message, ts: Date.now(), model }));
      chat.messages.push({ role: "bot", error: true, text: message, ts: Date.now(), model });
      setStatus(data.kind === "ssl" ? "SSL" : "ошибка", "err");
    } else if (data.kind === "analysis") {
      const message = data.message || "Анализ готов.";
      pending.replaceWith(messageNode({ role: "bot", text: message, ts: Date.now(), model: "Анализ данных", analysis: data.analysis }));
      chat.messages.push({ role: "bot", text: message, ts: Date.now(), model: "Анализ данных", analysis: data.analysis });
      setStatus("анализ готов · " + elapsed + " мс", "ok");
    } else if (data.upstream_status && (data.upstream_status < 200 || data.upstream_status >= 300)) {
      const message = "Сервер вернул код " + data.upstream_status + (data.body ? ": " + data.body.slice(0, 400) : "");
      pending.replaceWith(messageNode({ role: "bot", error: true, text: message, ts: Date.now(), model }));
      chat.messages.push({ role: "bot", error: true, text: message, ts: Date.now(), model });
      setStatus("ошибка " + data.upstream_status, "err");
    } else {
      const parsed = parseResult(data.body || "");
      if (parsed.error) {
        pending.replaceWith(messageNode({ role: "bot", error: true, text: parsed.error, ts: Date.now(), model }));
        chat.messages.push({ role: "bot", error: true, text: parsed.error, ts: Date.now(), model });
        setStatus("ошибка модели", "err");
      } else {
        if (parsed.dialogueUuid) chat.dialogueUuid = parsed.dialogueUuid;
        const message = parsed.message || "";
        pending.replaceWith(messageNode({ role: "bot", text: message, ts: Date.now(), model }));
        chat.messages.push({ role: "bot", text: message, ts: Date.now(), model });
        setStatus("получено · " + elapsed + " мс", "ok");
      }
    }
  } catch (error) {
    const message = error && error.name === "AbortError"
      ? "Превышено время ожидания ответа LiteLLM-прокси"
      : "Не удалось связаться с прокси: " + (error && error.message ? error.message : error);
    pending.replaceWith(messageNode({ role: "bot", error: true, text: message, ts: Date.now(), model }));
    chat.messages.push({ role: "bot", error: true, text: message, ts: Date.now(), model });
    setStatus("прокси", "err");
  } finally {
    clearTimeout(timeoutId);
    busy = false;
    sendBtn.disabled = false;
    save();
    scrollBottom();
    promptEl.focus();
  }
}

function closeSidebar() {
  shell.classList.remove("sidebar-open");
}

$("#newChatBtn").addEventListener("click", newChat);
$("#sidebarToggle").addEventListener("click", () => shell.classList.toggle("sidebar-open"));
$("#backdrop").addEventListener("click", closeSidebar);
workModeEl.addEventListener("change", () => { state.workMode = workModeEl.value; save(); refreshStatus(); });
memoryEl.addEventListener("change", () => { state.memoryMode = memoryEl.value; save(); });
titleEl.addEventListener("input", () => { activeChat().title = titleEl.value; save(); renderSidebar(); });
modelEl.addEventListener("change", () => { activeChat().model = modelEl.value || DEFAULT_MODEL; state.lastModel = activeChat().model; save(); renderSidebar(); });
promptEl.addEventListener("input", autosize);
promptEl.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send();
  }
});
sendBtn.addEventListener("click", send);

load();
renderActive();
autosize();
promptEl.focus();
</script>
</body>
</html>"""


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
    ctx = ssl.create_default_context()
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
            normalized.append({"role": role, "content": content})
    if normalized:
        return normalized
    return [{"role": "user", "content": fallback_text}]


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
        is_ssl = isinstance(reason, ssl.SSLError)
        if is_ssl and VERIFY_SSL:
            try:
                status, response_text = attempt(False)
                return {
                    "upstream_status": status,
                    "body": response_text,
                    "note": "SSL-проверка отключена",
                }
            except Exception as fallback_exc:
                return {"error": "SSL: " + str(fallback_exc), "kind": "ssl"}
        return {"error": str(reason), "kind": "ssl" if is_ssl else "network"}
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
    plan_source = "fallback"
    plan = None
    plan_answer = litellm_prompt(analytics_tools.make_plan_prompt(text, dashboard_filters), model)
    if plan_answer:
        plan = analytics_tools.parse_plan(plan_answer)
        if plan:
            plan_source = "litellm"
    if not plan:
        plan = analytics_tools.fallback_plan(text)

    base_plan = plan
    plan = analytics_tools.apply_dashboard_context(plan, text, dashboard_filters)
    result = analytics_tools.execute_plan(plan)
    if analytics_tools.requires_deterministic_explanation(result) and analytics_tools.has_selected_dashboard_filters(dashboard_filters):
        fallback_result = analytics_tools.execute_plan(base_plan)
        if not analytics_tools.requires_deterministic_explanation(fallback_result):
            result = analytics_tools.with_note(
                fallback_result,
                "Фильтры текущего дашборда не дали строк; показан срез без этих фильтров, как в исходном режиме анализа.",
            )
            plan = base_plan
    explanation = None
    if not analytics_tools.requires_deterministic_explanation(result) and SERVER_TOKEN.strip():
        explanation = litellm_prompt(analytics_tools.make_explanation_prompt(text, plan, result), model)
    if not explanation:
        explanation = analytics_tools.fallback_explanation(text, result)
    return analytics_tools.result_to_payload(result, explanation, plan, plan_source)


def render_page() -> str:
    return (
        HTML_TEMPLATE
        .replace("__DEFAULT_MODEL__", json.dumps(DEFAULT_MODEL, ensure_ascii=False))
        .replace("__ALLOWED_MODELS__", json.dumps(ALLOWED_MODELS or [DEFAULT_MODEL], ensure_ascii=False))
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
        data = request.get_json(silent=True) or {}
        mode = (data.get("mode") or "chat").strip()
        token = SERVER_TOKEN.strip()
        text = data.get("text") or ""
        model = (data.get("model") or DEFAULT_MODEL).strip()
        dialogue_uuid = (data.get("dialogue_uuid") or "").strip() or None
        messages = data.get("messages")

        if not text:
            return jsonify({"error": "Пустой запрос", "kind": "client"}), 400

        if mode == "analysis":
            try:
                return jsonify(run_analysis(text, model, data.get("dashboard_filters")))
            except Exception as exc:
                return jsonify({"error": str(exc), "kind": "analysis"}), 500

        if not token:
            return jsonify({"error": "Токен LiteLLM не настроен на сервере", "kind": "config"}), 500

        result = forward(token, text, model, dialogue_uuid, messages)
        return jsonify(result), 200 if not result.get("error") else 502
