from datetime import datetime
from zoneinfo import ZoneInfo


def get_kyiv_date_info() -> dict:
    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    days_ua = [
        "понеділок", "вівторок", "середа", "четвер",
        "п'ятниця", "субота", "неділя"
    ]
    months_gen_ua = [
        "", "січня", "лютого", "березня", "квітня", "травня", "червня",
        "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"
    ]
    months_nom_ua = [
        "", "січень", "лютий", "березень", "квітень", "травень", "червень",
        "липень", "серпень", "вересень", "жовтень", "листопад", "грудень"
    ]

    return {
        "iso_date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "day": now.day,
        "weekday": days_ua[now.weekday()],
        "month_gen": months_gen_ua[now.month],
        "month_nom": months_nom_ua[now.month],
        "year": now.year,
        "week_number": now.isocalendar().week,
    }

def build_system_prompt(search_context: str = "", mode: str = "auto") -> str:
    d = get_kyiv_date_info()

    date_block = (
        f"Актуальна дата і час (Київ): {d['day']} {d['month_gen']} {d['year']} року, "
        f"{d['weekday']}, місяць — {d['month_nom']}, тиждень року — №{d['week_number']}, "
        f"час — {d['time']}."
    )

    rules_block = (
        "Ти — Вася AI, корисний і чесний мобільний асистент. "
        "Пиши грамотною, природною українською мовою без орфографічних, "
        "пунктуаційних чи граматичних помилок і без вигаданих слів. "
        "Описуй лише те, що реально бачиш на зображенні або в наданих результатах пошуку. "
        "Якщо не знаєш факту, не вистачає даних або фото розмите чи не передалося — "
        "прямо і чесно скажи про це, не вигадуй чисел, дат, імен чи посилань. "
        "Якщо нижче подані результати веб-пошуку, спирайся на них як на основне джерело."
    )

    mode_hint = {
        "fast": "Відповідай коротко, чітко і по суті.",
        "smart": "Пояснюй логічно, структуровано й уважно до деталей.",
        "pro": "Розбирай задачу максимально глибоко, перевіряй кожен висновок і не поспішай.",
    }.get(mode, "Підлаштовуй глибину відповіді під складність запиту.")

    parts = [rules_block, mode_hint, date_block]
    if search_context:
        parts.append(f"Результати веб-пошуку:\n{search_context}")

    return "\n\n".join(parts)
    import os
import requests


def needs_web_search(query: str) -> bool:
    if not query:
        return False
    q = query.lower().strip()
    triggers = [
        "новини", "сьогодні", "вчора", "завтра", "зараз", "актуальн",
        "ціна", "курс", "погода", "матч", "рахунок", "результат",
        "хто виграв", "коли вийде", "що нового", "знайди", "пошукай",
        "перевір", "останні", "2026"
    ]
    return any(word in q for word in triggers)


def web_search(query: str, max_results: int = 4) -> str:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key or not query.strip():
        return ""

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query.strip(),
                "max_results": max_results,
                "include_answer": False,
                "search_depth": "basic",
            },
            timeout=3,
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])

        formatted = []
        for item in results[:max_results]:
            title = (item.get("title") or "Без назви").strip()
            content = (item.get("content") or "").strip().replace("\n", " ")
            url = (item.get("url") or "").strip()
            if len(content) > 280:
                content = content[:277] + "..."
            formatted.append(f"- {title}: {content} (Джерело: {url})")

        return "\n".join(formatted)
    except Exception:
        return ""
    import os
import requests
from flask import Flask, jsonify, request
from prompt_builder import build_system_prompt
from web_search import needs_web_search, web_search

app = Flask(__name__)

# Впиши сюди точні ID моделей OpenRouter з твого списку
MODE_MODELS = {
    "fast": [],
    "smart": [],
    "pro": [],
}

ALL_FALLBACK_MODELS = []

# Сюди впиши моделі, які точно підтримують фото
VISION_MODELS = []


def get_candidate_models(mode: str, has_image: bool = False) -> list[str]:
    chosen = MODE_MODELS.get(mode, [])
    merged = list(chosen)
    for m in ALL_FALLBACK_MODELS:
        if m not in merged:
            merged.append(m)

    if has_image:
        vision_first = list(VISION_MODELS)
        for m in merged:
            if m not in vision_first:
                vision_first.append(m)
        return vision_first

    return merged


def build_user_content(text: str, image_data: str | None):
    if image_data:
        return [
            {"type": "text", "text": text if text else "Що зображено на цьому фото?"},
            {"type": "image_url", "image_url": {"url": image_data}},
        ]
    return text


def call_openrouter(messages: list[dict], models: list[str], api_keys: list[str]) -> str | None:
    headers_base = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://vasya2-0.vercel.app",
        "X-Title": "Vasya AI",
    }

    for model_name in models:
        for api_key in api_keys:
            if not api_key:
                continue
            try:
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        **headers_base,
                        "Authorization": f"Bearer {api_key}",
                    },
                    json={
                        "model": model_name,
                        "messages": messages,
                    },
                    timeout=12,
                )
                if resp.status_code != 200:
                    continue
                payload = resp.json()
                choices = payload.get("choices") or []
                if not choices:
                    continue
                content = (choices[0].get("message") or {}).get("content")
                if isinstance(content, list):
                    text_parts = [
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict) and part.get("type") == "text"
                    ]
                    content = "".join(text_parts).strip()
                elif isinstance(content, str):
                    content = content.strip()
                if content:
                    return content
            except Exception:
                continue
    return None


@app.post("/api/chat")
def chat_endpoint():
    data = request.get_json(silent=True) or {}

    user_text = (data.get("message") or "").strip()
    model_mode = (data.get("model_mode") or "auto").strip().lower()
    image_data = data.get("image")
    history = data.get("history") or []

    if not user_text and not image_data:
        return jsonify({"error": "Порожній запит."}), 400

    search_ctx = web_search(user_text) if (user_text and needs_web_search(user_text)) else ""
    system_prompt = build_system_prompt(search_context=search_ctx, mode=model_mode)

    messages = [{"role": "system", "content": system_prompt}]

    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content.strip()})

    messages.append({
        "role": "user",
        "content": build_user_content(user_text, image_data),
    })

    api_keys = [
        k.strip()
        for k in [
            os.getenv("OPENROUTER_API_KEY", ""),
            os.getenv("OPENROUTER_API_KEY_2", ""),
            os.getenv("OPENROUTER_API_KEY_3", ""),
        ]
        if k and k.strip()
    ]

    models_to_try = get_candidate_models(model_mode, has_image=bool(image_data))
    reply = call_openrouter(messages=messages, models=models_to_try, api_keys=api_keys)

    if not reply:
        return jsonify({"reply": "На жаль, зараз жодна модель не змогла відповісти. Спробуй ще раз."}), 502

    return jsonify({"reply": reply})
<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>Вася AI 2.1.50</title>
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f1115;
      color: #f3f4f6;
      min-height: 100dvh;
      display: flex;
      flex-direction: column;
      overflow-x: hidden;
    }

    .top-bar {
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 12px;
      background: #161920;
      border-bottom: 1px solid #262b36;
    }
    .icon-btn, .pill-btn {
      background: #222733;
      color: #f9fafb;
      border: 1px solid #343b4d;
      border-radius: 10px;
      padding: 8px 11px;
      font-size: 14px;
      cursor: pointer;
    }
    .model-select {
      flex: 1;
      max-width: 190px;
      background: #222733;
      color: #f9fafb;
      border: 1px solid #343b4d;
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 14px;
    }

    .backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.55);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.2s ease;
      z-index: 30;
    }
    .backdrop.open {
      opacity: 1;
      pointer-events: auto;
    }

    .sidebar {
      position: fixed;
      top: 0;
      left: 0;
      bottom: 0;
      width: 80%;
      max-width: 320px;
      background: #171a22;
      border-right: 1px solid #2a303d;
      transform: translateX(-100%);
      transition: transform 0.22s ease;
      z-index: 40;
      display: flex;
      flex-direction: column;
    }
    .sidebar.open {
      transform: translateX(0);
    }
    .sidebar-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 14px;
      border-bottom: 1px solid #262b36;
    }
    .chat-list {
      flex: 1;
      overflow-y: auto;
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .chat-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 12px;
      border-radius: 10px;
      background: #1e232e;
      cursor: pointer;
      font-size: 14px;
    }
    .chat-item.active {
      background: #2b354b;
      border: 1px solid #4c6494;
    }
    .chat-title {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
    }
    .del-btn {
      background: transparent;
      border: none;
      color: #9ca3af;
      font-size: 15px;
      cursor: pointer;
      padding: 0 4px;
    }

    .messages {
      flex: 1;
      padding: 14px 12px 90px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      overflow-y: auto;
    }
    .msg {
      max-width: 88%;
      padding: 10px 13px;
      border-radius: 14px;
      line-height: 1.45;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 15px;
    }
    .msg.user {
      align-self: flex-end;
      background: #26416b;
    }
    .msg.assistant {
      align-self: flex-start;
      background: #1c2029;
      border: 1px solid #2b3140;
    }
    .msg img {
      display: block;
      max-width: 220px;
      max-height: 220px;
      border-radius: 10px;
      margin-bottom: 6px;
    }

    .composer {
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      background: #161920;
      border-top: 1px solid #262b36;
      z-index: 15;
    }
    .composer input[type="text"] {
      flex: 1;
      background: #222733;
      color: #f9fafb;
      border: 1px solid #343b4d;
      border-radius: 12px;
      padding: 10px 12px;
      font-size: 15px;
      outline: none;
    }
    .send-btn {
      background: #3b66f5;
      color: #fff;
      border: none;
      border-radius: 12px;
      padding: 10px 14px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
    }
  </style>
</head>
<body>
  <header class="top-bar">
    <button id="openSidebarBtn" class="icon-btn" type="button" aria-label="Відкрити чати">☰</button>
    <select id="modelSelect" class="model-select" aria-label="Вибір режиму або моделі">
      <option value="auto">Авто (ланцюжок)</option>
      <option value="fast">Швидкий</option>
      <option value="smart">Смарт</option>
      <option value="pro">Про</option>
    </select>
    <button id="newChatBtn" class="pill-btn" type="button">+ Новий</button>
  </header>

  <div id="backdrop" class="backdrop"></div>

  <aside id="sidebar" class="sidebar" aria-label="Історія чатів">
    <div class="sidebar-header">
      <strong>Чати Васі</strong>
      <button id="closeSidebarBtn" class="icon-btn" type="button" aria-label="Закрити">✕</button>
    </div>
    <div id="chatList" class="chat-list"></div>
  </aside>

  <main id="messages" class="messages"></main>

  <form id="composerForm" class="composer">
    <label class="icon-btn" for="imageInput" title="Додати фото">+</label>
    <input id="imageInput" type="file" accept="image/*" hidden />
    <input id="messageInput" type="text" placeholder="Напиши Васі..." autocomplete="off" />
    <button id="sendBtn" class="send-btn" type="submit">Надіслати</button>
  </form>

  <script>
    const STORAGE_KEY = "vasya_ai_2_1_50_chats";

    const sidebar = document.getElementById("sidebar");
    const backdrop = document.getElementById("backdrop");
    const openSidebarBtn = document.getElementById("openSidebarBtn");
    const closeSidebarBtn = document.getElementById("closeSidebarBtn");
    const newChatBtn = document.getElementById("newChatBtn");
    const modelSelect = document.getElementById("modelSelect");
    const chatListEl = document.getElementById("chatList");
    const messagesEl = document.getElementById("messages");
    const composerForm = document.getElementById("composerForm");
    const messageInput = document.getElementById("messageInput");
    const imageInput = document.getElementById("imageInput");

    let state = loadState();
    let pendingImageBase64 = null;

    function defaultState() {
      const firstId = "chat_" + Date.now();
      return {
        activeChatId: firstId,
        mode: "auto",
        chats: {
          [firstId]: {
            id: firstId,
            title: "Новий чат",
            messages: [
              {
                role: "assistant",
                text: "Привіт! Я Вася AI 2.1.50. Знаю актуальну дату, вмію шукати в мережі, читаю фото й готовий до роботи."
              }
            ]
          }
        }
      };
    }

    function loadState() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return defaultState();
        const parsed = JSON.parse(raw);
        if (!parsed.chats || !parsed.activeChatId || !parsed.chats[parsed.activeChatId]) {
          return defaultState();
        }
        return parsed;
      } catch {
        return defaultState();
      }
    }

    function saveState() {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      } catch {}
    }

    function setSidebarOpen(isOpen) {
      sidebar.classList.toggle("open", isOpen);
      backdrop.classList.toggle("open", isOpen);
    }

    openSidebarBtn.addEventListener("click", () => setSidebarOpen(true));
    closeSidebarBtn.addEventListener("click", () => setSidebarOpen(false));
    backdrop.addEventListener("click", () => setSidebarOpen(false));

    let touchStartX = 0;
    let touchStartY = 0;

    document.addEventListener("touchstart", (e) => {
      if (!e.touches.length) return;
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
    }, { passive: true });

    document.addEventListener("touchend", (e) => {
      if (!e.changedTouches.length) return;
      const dx = e.changedTouches[0].clientX - touchStartX;
      const dy = e.changedTouches[0].clientY - touchStartY;

      if (Math.abs(dx) > 65 && Math.abs(dx) > Math.abs(dy) * 1.4) {
        if (dx > 0 && touchStartX < 55 && !sidebar.classList.contains("open")) {
          setSidebarOpen(true);
        } else if (dx < 0 && sidebar.classList.contains("open")) {
          setSidebarOpen(false);
        }
      }
    }, { passive: true });

    modelSelect.value = state.mode || "auto";
    modelSelect.addEventListener("change", () => {
      state.mode = modelSelect.value;
      saveState();
    });

    newChatBtn.addEventListener("click", () => {
      const id = "chat_" + Date.now();
      state.chats[id] = {
        id,
        title: "Новий чат",
        messages: []
      };
      state.activeChatId = id;
      saveState();
      renderAll();
      setSidebarOpen(false);
    });

    imageInput.addEventListener("change", () => {
      const file = imageInput.files && imageInput.files[0];
      if (!file) {
        pendingImageBase64 = null;
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        pendingImageBase64 = reader.result;
      };
      reader.readAsDataURL(file);
    });

    function renderChatList() {
      chatListEl.innerHTML = "";
      const ids = Object.keys(state.chats).reverse();
      for (const id of ids) {
        const chat = state.chats[id];
        const item = document.createElement("div");
        item.className = "chat-item" + (id === state.activeChatId ? " active" : "");

        const titleEl = document.createElement("span");
        titleEl.className = "chat-title";
        titleEl.textContent = chat.title || "Чат";
        titleEl.addEventListener("click", () => {
          state.activeChatId = id;
          saveState();
          renderAll();
          setSidebarOpen(false);
        });

        const delBtn = document.createElement("button");
        delBtn.className = "del-btn";
        delBtn.type = "button";
        delBtn.textContent = "🗑";
        delBtn.title = "Видалити чат";
        delBtn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          delete state.chats[id];
          const remaining = Object.keys(state.chats);
          if (remaining.length === 0) {
            state = defaultState();
          } else if (state.activeChatId === id) {
            state.activeChatId = remaining[remaining.length - 1];
          }
          saveState();
          renderAll();
        });

        item.appendChild(titleEl);
        item.appendChild(delBtn);
        chatListEl.appendChild(item);
      }
    }

    function renderMessages() {
      messagesEl.innerHTML = "";
      const activeChat = state.chats[state.activeChatId];
      if (!activeChat) return;

      for (const msg of activeChat.messages) {
        const bubble = document.createElement("div");
        bubble.className = "msg " + msg.role;

        if (msg.image) {
          const img = document.createElement("img");
          img.src = msg.image;
          img.alt = "Прикріплене фото";
          bubble.appendChild(img);
        }
        if (msg.text) {
          const span = document.createElement("span");
          span.textContent = msg.text;
          bubble.appendChild(span);
        }
        messagesEl.appendChild(bubble);
      }
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function renderAll() {
      renderChatList();
      renderMessages();
    }

    composerForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = messageInput.value.trim();
      const imageToSend = pendingImageBase64;
      if (!text && !imageToSend) return;

      const activeChat = state.chats[state.activeChatId];
      if (activeChat.title === "Новий чат" && text) {
        activeChat.title = text.slice(0, 32);
      }

      activeChat.messages.push({
        role: "user",
        text,
        image: imageToSend || null
      });

      const thinkingMsg = { role: "assistant", text: "Думаю..." };
      activeChat.messages.push(thinkingMsg);
      saveState();
      renderAll();

      messageInput.value = "";
      imageInput.value = "";
      pendingImageBase64 = null;

      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: text,
            model_mode: modelSelect.value,
            image: imageToSend,
            history: activeChat.messages.slice(-8, -1).map((m) => ({
              role: m.role,
              content: m.text || ""
            }))
          })
        });
        const data = await res.json();
        thinkingMsg.text = data.reply || data.response || data.error || "Порожня відповідь від сервера.";
      } catch {
        thinkingMsg.text = "Не вдалося з'єднатися з сервером.";
      }

      saveState();
      renderAll();
    });

    renderAll();
  </script>
</body>
</html>
