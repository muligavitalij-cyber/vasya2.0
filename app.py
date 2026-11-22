import base64
import json
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple
import requests
from flask import Flask, Response, jsonify, request, send_from_directory

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))

DISABLE_GEMINI = os.environ.get("DISABLE_GEMINI", "1") == "1"
API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
RAW_MODEL = (os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash").strip()
if RAW_MODEL.startswith("models/"):
    RAW_MODEL = RAW_MODEL[len("models/"):]
if RAW_MODEL.startswith("deepseek"):
    RAW_MODEL = "gemini-2.5-flash"
MODEL = RAW_MODEL or "gemini-2.5-flash"
ENABLE_SEARCH = os.environ.get("ENABLE_SEARCH", "0") == "1"
DEBUG = os.environ.get("DEBUG", "0") == "1"

THINK = {"default": "MINIMAL", "smart": "LOW", "pro": "MEDIUM", "pro+": "HIGH"}
WAIT = {"default": 25, "smart": 30, "pro": 45, "pro+": 55}


def _load_openrouter_keys() -> List[str]:
    keys: List[str] = []
    for env_name in (
        "OPENROUTER_API_KEY",
        "OPENROUTER_API_KEY_2",
        "OPENROUTER_API_KEY_3",
        "OPENROUTER_API_KEY_4",
        "OPENROUTER_API_KEY_5",
        "OPENROUTER_API_KEYS",
    ):
        raw_val = (os.environ.get(env_name) or "").strip()
        if not raw_val:
            continue
        for part in re.split(r"[\s,;]+", raw_val):
            clean = part.strip().strip('"').strip("'")
            if clean and clean not in keys:
                keys.append(clean)
    return keys


OPENROUTER_KEYS = _load_openrouter_keys()
OPENROUTER_DEFAULT_MODEL = (os.environ.get("OPENROUTER_MODEL") or "").strip().lower()
OPENROUTER_FAST_MODEL = "google/gemma-4-26b-a4b-it:free"
OPENROUTER_SMART_MODEL = "google/gemma-4-31b-it:free"
OPENROUTER_BACKUP_MODELS: List[str] = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "qwen/qwen3-coder:free",
]

TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "geography": [
        "географія", "материк", "океан", "море", "річка", "озеро", "гора",
        "клімат", "координати", "столиця", "країна", "регіон", "зона",
        "берегова лінія", "протока", "затока", "острів", "місто", "село"
    ],
    "math_calc": [
        "обчисли", "розв'яжи", "рівняння", "інтеграл", "похідна", "дріб",
        "відсоток", "формула", "скільки буде", "порахуй"
    ],
    "space_science": [
        "космос", "планета", "зірка", "галактика", "nasa", "астрономія",
        "супутник", "орбіта", "сонце", "місяць"
    ],
    "weather": ["погода", "температура", "дощ", "сніг", "вітер", "прогноз погоди"],
    "currency": ["курс", "валюта", "долар", "євро", "гривня", "usd", "eur", "uah"],
    "news": ["новини", "актуальні новини", "що сталося", "події сьогодні"],
    "youtube": ["youtube", "ютуб", "відео", "канал", "ролик"],
    "translate": ["переклади", "переклад", "англійською", "українською", "мовою"],
    "calendar": ["календар", "дата", "день тижня", "свято", "розклад", "дедлайн"],
}


def detect_topics(query: str) -> List[str]:
    q = (query or "").lower()
    found = [t for t, words in TOPIC_KEYWORDS.items() if any(w in q for w in words)]
    return found or ["general"]


def build_source_plan(topics: List[str]) -> List[str]:
    plan: List[str] = []
    if "geography" in topics:
        plan.extend(["openstreetmap", "geonames", "wikipedia", "wikidata", "brave"])
    if "space_science" in topics:
        plan.extend(["nasa", "wikipedia", "wikidata", "brave"])
    if "math_calc" in topics:
        plan.extend(["wolfram", "wikipedia", "brave"])
    for extra in ("weather", "currency", "news", "youtube", "translate", "calendar"):
        if extra in topics:
            plan.append(extra)
            plan.append("brave")
    if "general" in topics:
        plan.extend(["wikipedia", "wikidata", "brave", "wolfram"])

    out: List[str] = []
    for item in plan:
        if item not in out:
            out.append(item)
    return out


def _get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 4.0):
    try:
        req_headers = {"User-Agent": "VasyaAI/1.0"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def collect_topic_context(query: str, max_items: int = 3) -> str:
    plan = build_source_plan(detect_topics(query))
    enc = urllib.parse.quote((query or "").strip())
    notes: List[str] = []

    for src in plan:
        if len(notes) >= max_items:
            break
        if src == "openstreetmap":
            data = _get_json(
                f"https://nominatim.openstreetmap.org/search?q={enc}&format=json&limit=1&accept-language=uk",
                timeout=4.0,
            )
            if isinstance(data, list) and data:
                p = data[0]
                notes.append(f"[OpenStreetMap] {p.get('display_name')} (lat={p.get('lat')}, lon={p.get('lon')})")
        elif src == "geonames":
            user = (os.environ.get("GEONAMES_USERNAME") or "").strip()
            if user:
                data = _get_json(
                    f"http://api.geonames.org/searchJSON?q={enc}&maxRows=1&lang=uk&username={user}",
                    timeout=4.0,
                )
                if isinstance(data, dict) and data.get("geonames"):
                    g = data["geonames"][0]
                    notes.append(f"[GeoNames] {g.get('name')} ({g.get('countryName')}): lat={g.get('lat')}, lon={g.get('lng')}")
        elif src == "wikipedia":
            for lang in ("uk", "en"):
                data = _get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{enc}", timeout=3.5)
                if isinstance(data, dict) and data.get("extract"):
                    notes.append(f"[Wikipedia/{lang}] {data.get('title')}: {data['extract']}")
                    break
        elif src == "wikidata":
            data = _get_json(
                f"https://www.wikidata.org/w/api.php?action=wbsearchentities&search={enc}&language=uk&format=json&limit=1",
                timeout=3.5,
            )
            if isinstance(data, dict) and data.get("search"):
                s = data["search"][0]
                notes.append(f"[Wikidata] {s.get('label')} ({s.get('id')}): {s.get('description', '')}")
        elif src == "brave":
            key = (os.environ.get("BRAVE_API_KEY") or "").strip()
            if key:
                data = _get_json(
                    f"https://api.search.brave.com/res/v1/web/search?q={enc}&count=3",
                    headers={"Accept": "application/json", "X-Subscription-Token": key},
                    timeout=4.5,
                )
                if isinstance(data, dict):
                    items = (data.get("web") or {}).get("results") or []
                    if items:
                        lines = [f"- {it.get('title')}: {it.get('description')}" for it in items[:3]]
                        notes.append("[Brave Search]\n" + "\n".join(lines))
        elif src == "wolfram":
            app_id = (os.environ.get("WOLFRAM_APP_ID") or "").strip()
            if app_id:
                try:
                    req = urllib.request.Request(
                        f"https://api.wolframalpha.com/v1/result?i={enc}&appid={app_id}",
                        headers={"User-Agent": "VasyaAI/1.0"},
                    )
                    with urllib.request.urlopen(req, timeout=4.5) as resp:
                        txt = resp.read().decode("utf-8", errors="replace").strip()
                        if txt and "did not understand" not in txt.lower():
                            notes.append(f"[Wolfram Alpha] {txt}")
                except Exception:
                    pass
        elif src == "nasa":
            nkey = (os.environ.get("NASA_API_KEY") or "DEMO_KEY").strip()
            data = _get_json(f"https://api.nasa.gov/planetary/apod?api_key={nkey}", timeout=4.5)
            if isinstance(data, dict) and data.get("title"):
                notes.append(f"[NASA] {data.get('title')}: {str(data.get('explanation') or '')[:300]}")
        elif src in {"weather", "currency", "news", "youtube", "translate", "calendar"}:
            env_map = {
                "weather": "WEATHER_API_KEY",
                "currency": "CURRENCY_API_KEY",
                "news": "NEWS_API_KEY",
                "youtube": "YOUTUBE_API_KEY",
                "translate": "TRANSLATE_API_KEY",
                "calendar": "CALENDAR_API_KEY",
            }
            if (os.environ.get(env_map[src]) or "").strip():
                notes.append(f"[{src.upper()}] Ключ підключено; запит: {query}")

    return "\n\n".join(notes)


def _parse_data_url(data_url: str) -> Optional[Tuple[str, str]]:
    m = re.match(r"^data:([^;]+);base64,(.+)$", data_url or "", re.DOTALL)
    if not m:
        return None
    mime = m.group(1).strip()
    b64 = m.group(2).strip()
    try:
        raw = base64.b64decode(b64, validate=False)
        if len(raw) > 4_000_000:
            return None
        return mime, base64.b64encode(raw).decode("ascii")
    except Exception:
        return None
PAGE = r'''<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Вася АІ</title>
  <link rel="icon" type="image/png" href="/icon.png">
  <link rel="apple-touch-icon" href="/icon.png">

  <script>
    window.MathJax = {
      tex: {
        inlineMath: [['$', '$'], ['\\(', '\\)']],
        displayMath: [['$$', '$$'], ['\\[', '\\]']],
        processEscapes: true
      },
      options: {
        skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
      }
    };
  </script>
  <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js" async></script>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>

  <style>
    :root {
      --bg: #121212;
      --grid: rgba(255, 255, 255, 0.05);
      --panel: #191c22;
      --card: #22262f;
      --user: #1f3a5f;
      --border: rgba(255, 255, 255, 0.12);
      --text: #f0f3f8;
      --muted: #a4aec0;
      --accent: #38a169;
    }
    * { box-sizing: border-box; }
    body {
      font-family: system-ui, -apple-system, sans-serif;
      margin: 0;
      background-color: var(--bg);
      background-image:
        linear-gradient(to right, var(--grid) 1px, transparent 1px),
        linear-gradient(to bottom, var(--grid) 1px, transparent 1px);
      background-size: 22px 22px;
      color: var(--text);
      min-height: 100vh;
    }
    .sidebar {
      position: fixed;
      top: 0;
      left: 0;
      width: 265px;
      height: 100vh;
      background: var(--panel);
      border-right: 1px solid var(--border);
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      transform: translateX(-100%);
      transition: transform 0.2s ease;
      z-index: 40;
    }
    .sidebar.open { transform: translateX(0); }
    .backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.55);
      z-index: 30;
    }
    .backdrop.show { display: block; }
    .chat-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
      overflow-y: auto;
      flex: 1;
    }
    .chat-btn {
      width: 100%;
      text-align: left;
      background: transparent;
      color: var(--text);
      border: 1px solid transparent;
      padding: 8px 10px;
      border-radius: 8px;
      cursor: pointer;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .chat-btn.active {
      background: rgba(56, 161, 105, 0.2);
      border-color: rgba(56, 161, 105, 0.45);
    }
    .wrap { max-width: 760px; margin: 0 auto; padding: 12px 12px 96px; }
    .bar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; align-items: center; }
    select, button, input { font-size: 15px; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border); }
    select, input { background: #1c1f26; color: #fff; }
    button { background: var(--accent); color: #fff; border: none; cursor: pointer; }
    button.grey { background: #363c47; }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    .quota { font-size: 13px; color: var(--muted); margin-bottom: 10px; }
    .messages { display: flex; flex-direction: column; gap: 12px; margin-bottom: 14px; }
    .msg-wrap { display: flex; flex-direction: column; max-width: 92%; }
    .msg-wrap.user { align-self: flex-end; }
    .msg-wrap.assistant, .msg-wrap.error { align-self: flex-start; }
    .msg { padding: 11px 13px; border-radius: 10px; line-height: 1.5; overflow-x: auto; word-break: break-word; }
    .user .msg { background: var(--user); }
    .assistant .msg { background: var(--card); border: 1px solid var(--border); }
    .error-msg { background: #4c1b1b; border: 1px solid #9e3434; color: #ffd9d9; }
    .retry-btn { margin-top: 8px; padding: 6px 10px; font-size: 13px; background: #7a2626; border-radius: 7px; }
    .thinking { background: #1c241e !important; color: #9fd8ad; border-color: #2c4733 !important; font-style: italic; }
    .who { font-size: 12px; opacity: 0.75; margin-bottom: 4px; }
    .ai-note { font-size: 12px; color: var(--muted); margin-top: 4px; padding-left: 4px; }
    .attach-preview { font-size: 12px; color: #b7f5c8; margin-bottom: 8px; display: none; }
    .send-form {
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(18, 18, 18, 0.94);
      border-top: 1px solid var(--border);
      padding: 10px 12px;
    }
    .send-inner { max-width: 760px; margin: 0 auto; display: flex; gap: 8px; align-items: center; }
    .send-inner input[type="text"] { flex: 1; }
    table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 14px; }
    th, td { border: 1px solid var(--border); padding: 6px 8px; text-align: left; }
  </style>
</head>
<body>
  <aside id="sidebar" class="sidebar">
    <div style="display:flex;gap:8px;align-items:center;">
      <button type="button" style="flex:1;" onclick="newChat(); toggleMenu(false);">+ Новий чат</button>
      <button type="button" class="grey" onclick="toggleMenu(false)">✕</button>
    </div>
    <div id="sidebarChats" class="chat-list"></div>
  </aside>
  <div id="backdrop" class="backdrop" onclick="toggleMenu(false)"></div>

  <div class="wrap">
    <div class="bar">
      <button type="button" class="grey" onclick="toggleMenu(true)">☰ Чати</button>
      <strong>Вася АІ</strong>
      <button type="button" onclick="newChat()">+ Новий чат</button>
      <label for="modeSelect" style="margin-left:auto;">Режим:</label>
      <select id="modeSelect" onchange="changeMode(this.value)">
        <option value="default">Дефолт</option>
        <option value="smart">Смарт</option>
        <option value="pro">Про</option>
        <option value="pro+">Про+</option>
      </select>
    </div>

    <div class="quota" id="quotaBox"></div>
    <div class="messages" id="messagesBox"></div>
  </div>

  <form class="send-form" onsubmit="handleSend(event)">
    <div class="send-inner">
      <label class="grey" style="padding:8px 11px;border-radius:8px;cursor:pointer;" title="Прикріпити графік, таблицю або файл">
        +
        <input type="file" id="fileInput" accept="image/*,.csv,.txt,.md,.json" hidden onchange="handleFileSelect(event)">
      </label>
      <input type="text" id="msgInput" placeholder="Напиши завдання, формулу, тему чи прикріпи графік/таблицю..." autocomplete="off">
      <button type="submit" id="sendBtn">Надіслати</button>
    </div>
    <div id="attachPreview" class="attach-preview" style="max-width:760px;margin:6px auto 0;"></div>
  </form>

  <script>
    const STORAGE_KEY = "vasya_browser_state_v3";
    const MODES = {
      "default": { sfx: "дефолт", limit: null },
      "smart": { sfx: "смарт", limit: 40 },
      "pro": { sfx: "про", limit: 25 },
      "pro+": { sfx: "про+", limit: 20 }
    };

    const BASE_HW_RULES =
      " Допомагай зі шкільними завданнями (географія, історія, мова, література, математика, фізика, хімія, біологія та ін.). " +
      "Записуй дроби та формули через LaTeX: вбудовані як $\\\\frac{a}{b}$ та окремі як $$\\\\frac{a}{b}$$, не залишай незакритих знаків $. " +
      "Якщо передано графік — назви тип графіка, підписи осей та одиниці вимірювання, опиши тренд і ключові точки; якщо якесь значення дрібне або нечітке — чесно скажи про це, не вигадуй чисел. " +
      "Якщо передано таблицю — розбери стовпці й рядки, порівняй показники та знайди закономірності. " +
      "Коли питають про берегову лінію, материк, країну чи регіон — давай повний, структурований перелік (океани, моря, затоки, протоки, крайні точки та миси, острови/півострови), нічого не пропускаючи. " +
      "Коли просять есе чи твір — пиши живою, грамотною українською мовою, з вступом, аргументами, прикладами й висновком, без сухої канцелярщини. " +
      "Коли розбираєш задачі — пояснюй крок за кроком.";

    const INSTR = {
      vasya: {
        "default": "Ти — Вася АІ. Відповідай чітко, повно і по суті, без зайвої води та вигаданих фактів." + BASE_HW_RULES,
        "smart": "Ти — Вася АІ у режимі Смарт. Розбирай задачу логічно й зрозуміло, перевіряй кроки та факти." + BASE_HW_RULES,
        "pro": "Ти — Вася АІ у режимі Про. Давай глибокий, структурований розбір із деталями, прикладами та поясненнями." + BASE_HW_RULES,
        "pro+": "Ти — Вася АІ у режимі Про+. Працюй максимально ретельно й детально: охоплюй усі нюанси, перевіряй логіку й подавай матеріал чітко." + BASE_HW_RULES
      }
    };

    let isThinking = false, thinkSeconds = 0, thinkTimer = null, pendingAttachment = null;

    function createDefaultState() {
      const id = "chat_" + Date.now();
      return {
        chats: { [id]: { id, title: "Новий чат", mode: "default", messages: [] } },
        usage: {},
        activeChatId: id
      };
    }

    function loadState() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return createDefaultState();
        const p = JSON.parse(raw);
        if (!p.chats || !Object.keys(p.chats).length) return createDefaultState();
        if (!p.usage) p.usage = {};
        return p;
      } catch (e) {
        return createDefaultState();
      }
    }

    let state = loadState();

    function saveState() {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (e) {}
    }

    function toggleMenu(open) {
      document.getElementById("sidebar").classList.toggle("open", open);
      document.getElementById("backdrop").classList.toggle("show", open);
    }

    function getActiveChat() {
      if (!state.chats[state.activeChatId]) {
        state.activeChatId = Object.keys(state.chats)[0];
      }
      const c = state.chats[state.activeChatId];
      if (!MODES[c.mode]) c.mode = "default";
      return c;
    }

    function handleFileSelect(ev) {
      const file = ev.target.files && ev.target.files[0];
      const prev = document.getElementById("attachPreview");
      if (!file) {
        pendingAttachment = null;
        prev.style.display = "none";
        prev.textContent = "";
        return;
      }
      if (file.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = () => {
          pendingAttachment = { name: file.name, type: file.type, dataUrl: reader.result };
          prev.style.display = "block";
          prev.textContent = "Прикріплено зображення: " + file.name;
        };
        reader.readAsDataURL(file);
      } else {
        const reader = new FileReader();
        reader.onload = () => {
          pendingAttachment = { name: file.name, type: file.type || "text/plain", textContent: String(reader.result || "") };
          prev.style.display = "block";
          prev.textContent = "Прикріплено файл: " + file.name;
        };
        reader.readAsText(file);
      }
    }

    function startThinking() {
      stopThinking();
      isThinking = true;
      thinkSeconds = 0;
      thinkTimer = setInterval(() => {
        thinkSeconds += 1;
        const el = document.getElementById("thinkingText");
        if (el) el.textContent = `Вася думає... (${thinkSeconds} сек)`;
      }, 1000);
    }

    function stopThinking() {
      isThinking = false;
      if (thinkTimer) {
        clearInterval(thinkTimer);
        thinkTimer = null;
      }
    }

    function newChat() {
      if (isThinking) return;
      const cur = getActiveChat();
      const id = "chat_" + Date.now();
      state.chats[id] = { id, title: "Новий чат", mode: cur.mode || "default", messages: [] };
      state.activeChatId = id;
      saveState();
      render();
    }

    function selectChat(id) {
      if (isThinking || !state.chats[id]) return;
      state.activeChatId = id;
      saveState();
      render();
    }

    function changeMode(mode) {
      if (isThinking || !MODES[mode]) return;
      const c = getActiveChat();
      c.mode = mode;
      saveState();
      render();
    }

    async function renderRichText(target, text) {
      if (window.marked) {
        target.innerHTML = window.marked.parse(text || "");
      } else {
        target.textContent = text || "";
      }
      if (window.MathJax && window.MathJax.typesetPromise) {
        try { await window.MathJax.typesetPromise([target]); } catch (e) {}
      }
    }

    async function render() {
      const chat = getActiveChat();
      const m = MODES[chat.mode] || MODES.default;
      document.getElementById("modeSelect").value = chat.mode;
      document.getElementById("sendBtn").disabled = isThinking;

      const sideList = document.getElementById("sidebarChats");
      sideList.innerHTML = "";
      Object.values(state.chats).forEach((c) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "chat-btn" + (c.id === chat.id ? " active" : "");
        b.textContent = c.title || "Чат";
        b.onclick = () => { selectChat(c.id); toggleMenu(false); };
        sideList.appendChild(b);
      });

      const quotaBox = document.getElementById("quotaBox");
      if (m.limit == null) {
        quotaBox.textContent = `Вася ${m.sfx}: безліміт`;
      } else {
        const used = state.usage[chat.mode] || 0;
        const rem = Math.max(0, m.limit - used);
        quotaBox.textContent = `Вася ${m.sfx}: залишилось ${rem}/${m.limit}`;
      }

      const msgBox = document.getElementById("messagesBox");
      msgBox.innerHTML = "";

      for (const item of (chat.messages || [])) {
        if (item.role === "error") {
          const wrap = document.createElement("div");
          wrap.className = "msg-wrap error";

          const div = document.createElement("div");
          div.className = "msg error-msg";

          const who = document.createElement("div");
          who.className = "who";
          who.textContent = "Вася";
          div.appendChild(who);

          const body = document.createElement("div");
          body.textContent = item.text || "Помилка запиту.";
          div.appendChild(body);

          if (item.retryText || item.retryAttachment) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "retry-btn";
            btn.textContent = "Повторити";
            btn.disabled = isThinking;
            btn.onclick = () => retryMessage(item.retryText || "", item.retryAttachment || null);
            div.appendChild(btn);
          }

          wrap.appendChild(div);
          msgBox.appendChild(wrap);
          continue;
        }

        const wrap = document.createElement("div");
        wrap.className = "msg-wrap " + (item.role === "user" ? "user" : "assistant");

        const div = document.createElement("div");
        div.className = "msg";

        const who = document.createElement("div");
        who.className = "who";
        who.textContent = item.role === "user" ? "Ти" : "Вася";
        div.appendChild(who);

        const body = document.createElement("div");
        await renderRichText(body, item.text);
        div.appendChild(body);
        wrap.appendChild(div);

        if (item.role === "assistant" && item.showMistakeNote) {
          const note = document.createElement("div");
          note.className = "ai-note";
          note.textContent = "Вася АІ — це ШІ і може помилятися.";
          wrap.appendChild(note);
        }

        msgBox.appendChild(wrap);
      }

      if (isThinking) {
        const tWrap = document.createElement("div");
        tWrap.className = "msg-wrap assistant";
        const t = document.createElement("div");
        t.className = "msg thinking";
        t.id = "thinkingText";
        t.textContent = `Вася думає... (${thinkSeconds} сек)`;
        tWrap.appendChild(t);
        msgBox.appendChild(tWrap);
      }

      window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
    }

    async function askInstruction(instruction, messages, mode) {
      const apiMessages = messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({
          role: m.role,
          text: m.text,
          attachment: m.attachment || null
        }));

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          system: instruction,
          mode: mode,
          messages: apiMessages
        })
      });
      let data = {};
      try { data = await res.json(); } catch (e) {}
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      return data.reply || data.text || "Порожня відповідь";
    }

    async function sendPrompt(text, attachment, clearInputAfter = false) {
      if (isThinking) return;
      if (!text && !attachment) return;

      const chat = getActiveChat();
      const m = MODES[chat.mode] || MODES.default;

      if (m.limit != null && (state.usage[chat.mode] || 0) >= m.limit) {
        chat.messages.push({
          role: "error",
          text: `Ліміт для режиму ${m.sfx} вичерпано.`,
          retryText: "",
          retryAttachment: null
        });
        saveState();
        await render();
        return;
      }

      const firstTitle = chat.title === "Новий чат";
      const displayText = text || (attachment ? `Файл: ${attachment.name}` : "");
      chat.messages.push({ role: "user", text: displayText, attachment: attachment || null });
      if (firstTitle) chat.title = (text || (attachment && attachment.name) || "Чат").slice(0, 32);

      if (clearInputAfter) {
        document.getElementById("msgInput").value = "";
        pendingAttachment = null;
        document.getElementById("fileInput").value = "";
        const prev = document.getElementById("attachPreview");
        prev.style.display = "none";
        prev.textContent = "";
      }

      saveState();
      startThinking();
      await render();

      try {
        const sys = (INSTR.vasya && INSTR.vasya[chat.mode]) || INSTR.vasya.default;
        const reply = await askInstruction(sys, chat.messages, chat.mode);
        chat.messages.push({ role: "assistant", text: reply, showMistakeNote: true });
        if (m.limit != null) state.usage[chat.mode] = (state.usage[chat.mode] || 0) + 1;
        saveState();
      } catch (err) {
        chat.messages.push({
          role: "error",
          text: "Помилка запиту: " + err.message,
          retryText: text,
          retryAttachment: attachment || null
        });
        saveState();
      } finally {
        stopThinking();
        await render();
      }
    }

    async function retryMessage(retryText, retryAttachment) {
      if (isThinking) return;
      const chat = getActiveChat();
      const last = chat.messages[chat.messages.length - 1];
      if (last && last.role === "error") {
        chat.messages.pop();
      }
      const prevUser = chat.messages[chat.messages.length - 1];
      if (prevUser && prevUser.role === "user") {
        chat.messages.pop();
      }
      saveState();
      await sendPrompt(retryText, retryAttachment, false);
    }

    async function handleSend(e) {
      e.preventDefault();
      if (isThinking) return;
      const input = document.getElementById("msgInput");
      const text = input.value.trim();
      const att = pendingAttachment;
      await sendPrompt(text, att, true);
    }

    render();
  </script>
</body>
</html>
'''
def _build_openrouter_messages(raw_msgs, system_text: str, context_block: str = "") -> List[dict]:
    out: List[dict] = []

    merged_sys = (system_text or "").strip()
    if context_block:
        merged_sys = (
            f"{merged_sys}\n\nДовідковий контекст із підібраних джерел:\n{context_block}\n"
            "Спирайся на цей контекст, якщо він відповідає питанню."
        ).strip()

    if merged_sys:
        out.append({"role": "system", "content": merged_sys})

    if not isinstance(raw_msgs, list):
        return out

    for item in raw_msgs[-20:]:
        if not isinstance(item, dict):
            continue
        role = "assistant" if item.get("role") == "assistant" else "user"
        text = str(item.get("text") or "")[:8000]
        parts: List[dict] = []

        if text:
            parts.append({"type": "text", "text": text})

        att = item.get("attachment")
        if isinstance(att, dict) and role == "user":
            att_name = str(att.get("name") or "file")
            att_type = str(att.get("type") or "")
            att_text = str(att.get("textContent") or "")[:12000]
            att_data_url = str(att.get("dataUrl") or "")

            if att_type.startswith("image/") and att_data_url:
                parsed = _parse_data_url(att_data_url)
                if parsed:
                    mime, clean_b64 = parsed
                    parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{clean_b64}"}
                    })
                    if not text:
                        parts.append({"type": "text", "text": f"Проаналізуй зображення/графік/таблицю: {att_name}"})
            elif att_text:
                parts.append({"type": "text", "text": f"[Вкладений файл {att_name}]\n{att_text}"})
                if not text:
                    parts.append({"type": "text", "text": f"Проаналізуй дані з файлу {att_name}"})

        if parts:
            if len(parts) == 1 and parts[0]["type"] == "text":
                out.append({"role": role, "content": parts[0]["text"]})
            else:
                out.append({"role": role, "content": parts})

    return out


def _pick_openrouter_models(mode: str, query_text: str) -> List[str]:
    q = (query_text or "").strip()
    is_complex = (
        mode in ("pro", "pro+")
        or len(q) > 220
        or any(k in q.lower() for k in (
            "рівняння", "інтеграл", "похідна", "довод", "розв'яжи", "задача",
            "поясни детально", "порівняй", "аналіз", "код", "python", "скрипт"
        ))
    )

    ordered: List[str] = []
    if OPENROUTER_DEFAULT_MODEL:
        ordered.append(OPENROUTER_DEFAULT_MODEL)

    if is_complex:
        ordered.extend([OPENROUTER_SMART_MODEL, OPENROUTER_FAST_MODEL])
    else:
        ordered.extend([OPENROUTER_FAST_MODEL, OPENROUTER_SMART_MODEL])

    ordered.extend(OPENROUTER_BACKUP_MODELS)

    final_models: List[str] = []
    for m in ordered:
        clean = (m or "").strip().lower()
        if clean and clean not in final_models:
            final_models.append(clean)
    return final_models


def call_openrouter_fallback(raw_msgs, system_text: str, mode: str, query_text: str, context_block: str = ""):
    if not OPENROUTER_KEYS:
        return None, "Не задано жодного ключа OpenRouter"

    models = _pick_openrouter_models(mode, query_text)
    if not models:
        return None, "Не задано моделей OpenRouter"

    messages = _build_openrouter_messages(raw_msgs, system_text, context_block)
    if not messages:
        return None, "Порожні повідомлення для OpenRouter"

    started_at = time.monotonic()
    max_total_budget = min(float(WAIT.get(mode, 25)) - 2.0, 20.0)
    last_err = "Усі моделі та ключі OpenRouter не відповіли"

    for model_id in models:
        for api_key in OPENROUTER_KEYS:
            elapsed = time.monotonic() - started_at
            remaining = max_total_budget - elapsed
            if remaining < 3.5:
                return None, f"Замало часу до ліміту відповіді ({last_err})"

            per_call_timeout = min(7.0, max(3.5, remaining))
            payload = {
                "model": model_id,
                "messages": messages,
                "temperature": 0.4 if mode == "default" else 0.3,
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://vasya-ai.vercel.app",
                "X-Title": "Vasya AI",
            }

            try:
                r = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=per_call_timeout,
                )
                if r.status_code == 200:
                    data = r.json()
                    choices = data.get("choices") or []
                    if choices:
                        msg = choices[0].get("message") or {}
                        content = msg.get("content")
                        if isinstance(content, list):
                            txt = "".join(
                                str(part.get("text") or "")
                                for part in content
                                if isinstance(part, dict) and part.get("type") == "text"
                            ).strip()
                        else:
                            txt = str(content or "").strip()
                        if txt:
                            return txt, None

                try:
                    detail = r.json().get("error", {}).get("message", "")
                except Exception:
                    detail = r.text[:180]
                last_err = f"[{model_id}] HTTP {r.status_code}: {detail}"

                if r.status_code in (401, 402, 403, 400, 404, 422):
                    break
                continue
            except requests.Timeout:
                last_err = f"[{model_id}] таймаут"
                continue
            except Exception as e:
                last_err = f"[{model_id}] {e}"
                continue

    return None, last_err


@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp


def err(msg, code):
    return jsonify({"error": msg}), code


@app.route("/", methods=["GET"])
def index():
    return Response(PAGE, mimetype="text/html")


@app.route("/icon.png", methods=["GET"])
@app.route("/favicon.ico", methods=["GET"])
def icon():
    return send_from_directory(BASE, "icon.png", mimetype="image/png")


@app.route("/api/index", methods=["GET", "POST", "OPTIONS"])
def index_or_chat():
    if request.method == "GET":
        return Response(PAGE, mimetype="text/html")
    return chat()


@app.route("/api/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(silent=True) or {}
    system_text = str(data.get("system") or "")[:4000]
    mode = data.get("mode") if data.get("mode") in THINK else "default"
    raw_msgs = data.get("messages")
    contents = []
    last_user_text = ""

    if isinstance(raw_msgs, list):
        for item in raw_msgs[-20:]:
            if not isinstance(item, dict):
                continue
            role = "model" if item.get("role") == "assistant" else "user"
            text = str(item.get("text") or "")[:8000]
            parts = []
            if text:
                parts.append({"text": text})
                if role == "user":
                    last_user_text = text

            att = item.get("attachment")
            if isinstance(att, dict) and role == "user":
                att_name = str(att.get("name") or "file")
                att_type = str(att.get("type") or "")
                att_text = str(att.get("textContent") or "")[:12000]
                att_data_url = str(att.get("dataUrl") or "")

                if att_type.startswith("image/") and att_data_url:
                    parsed = _parse_data_url(att_data_url)
                    if parsed:
                        mime, clean_b64 = parsed
                        parts.append({"inlineData": {"mimeType": mime, "data": clean_b64}})
                        if not text:
                            last_user_text = f"Проаналізуй зображення/графік/таблицю: {att_name}"
                elif att_text:
                    parts.append({"text": f"[Вкладений файл {att_name}]\n{att_text}"})
                    if not text:
                        last_user_text = f"Проаналізуй дані з файлу {att_name}"

            if parts:
                contents.append({"role": role, "parts": parts})

    if not any(m["role"] == "user" for m in contents):
        return err("Порожнє повідомлення", 400)

    context_block = ""
    if ENABLE_SEARCH or detect_topics(last_user_text) != ["general"]:
        context_block = collect_topic_context(last_user_text, max_items=2)

    merged_system = system_text
    if context_block:
        merged_system = (
            f"{system_text}\n\nДовідковий контекст із підібраних джерел:\n{context_block}\n"
            "Спирайся на цей контекст, якщо він відповідає питанню."
        ).strip()

    gemini_failed_reason = "Gemini вимкнено (DISABLE_GEMINI=1)"
    if not DISABLE_GEMINI and API_KEY:
        gemini_failed_reason = ""
        payload = {"contents": contents}
        if merged_system:
            payload["systemInstruction"] = {"parts": [{"text": merged_system}]}
        if ENABLE_SEARCH:
            payload["tools"] = [{"google_search": {}}]
        if MODEL.startswith("gemini-3"):
            payload["generationConfig"] = {"thinkingConfig": {"thinkingLevel": THINK[mode]}}

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
        headers = {"x-goog-api-key": API_KEY, "Content-Type": "application/json"}

        for attempt in range(2):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=min(WAIT[mode], 16))
                if r.status_code == 200:
                    body = r.json()
                    candidates = body.get("candidates") or []
                    parts = (candidates[0].get("content") or {}).get("parts") or [] if candidates else []
                    text_out = "".join(str(p.get("text") or "") for p in parts if not p.get("thought"))
                    if text_out.strip():
                        return jsonify({"reply": text_out.strip()})
                    gemini_failed_reason = "Порожня відповідь від Gemini"
                    break

                try:
                    detail = r.json().get("error", {}).get("message", "")
                except Exception:
                    detail = r.text[:200]
                gemini_failed_reason = f"Gemini HTTP {r.status_code}: {detail}"

                if r.status_code in (429, 503) and attempt == 0:
                    time.sleep(0.5)
                    continue
                break
            except requests.Timeout:
                gemini_failed_reason = "Gemini таймаут"
                if attempt == 0:
                    continue
                break
            except Exception as e:
                gemini_failed_reason = f"Gemini помилка: {e}"
                break
    elif not API_KEY:
        gemini_failed_reason = "GEMINI_API_KEY не задано"

    fb_reply, fb_err = call_openrouter_fallback(
        raw_msgs=raw_msgs,
        system_text=system_text,
        mode=mode,
        query_text=last_user_text,
        context_block=context_block,
    )
    if fb_reply:
        return jsonify({"reply": fb_reply})

    if DEBUG:
        return err(f"Основний шлях: {gemini_failed_reason} | Резерв: {fb_err}", 502)
    return err("Сервіс тимчасово перевантажений. Спробуй ще раз за кілька секунд.", 503)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
