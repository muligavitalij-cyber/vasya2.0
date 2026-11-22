import os
import requests
from flask import Flask, request, jsonify, Response, send_from_directory

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))

API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
ENABLE_SEARCH = os.environ.get("ENABLE_SEARCH", "1")

# ---- Сторінка сайту ----
PAGE = r'''<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Вася АІ</title>
  <link rel="icon" type="image/png" href="/icon.png">
  <link rel="apple-touch-icon" href="/icon.png">
  <style>
    body {
      font-family: sans-serif;
      margin: 0;
      background-color: #121212;
      background-image:
        linear-gradient(to right, rgba(255, 255, 255, 0.05) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(255, 255, 255, 0.05) 1px, transparent 1px);
      background-size: 22px 22px;
      color: #eee;
      min-height: 100vh;
    }
    .wrap { max-width: 720px; margin: 0 auto; padding: 12px; }
    .bar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; align-items: center; }
    select, button, input { font-size: 15px; padding: 8px 10px; border-radius: 6px; border: 1px solid #444; }
    select, input { background: #1e1e1e; color: #fff; }
    button { background: #2b5; color: #fff; border: none; cursor: pointer; }
    button.grey { background: #444; }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    .chats { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 8px; margin-bottom: 12px; }
    .chat-chip { background: #222; color: #ddd; padding: 6px 10px; border-radius: 6px; white-space: nowrap; border: 1px solid #333; cursor: pointer; }
    .chat-chip.active { background: #2b5; color: #fff; border-color: #2b5; }
    .quota { font-size: 13px; color: #bbb; margin-bottom: 10px; }
    .messages { display: flex; flex-direction: column; gap: 10px; margin-bottom: 14px; }
    .msg { padding: 10px 12px; border-radius: 8px; white-space: pre-wrap; line-height: 1.45; }
    .user { background: #1f3a5f; align-self: flex-end; max-width: 88%; }
    .assistant { background: #232323; align-self: flex-start; max-width: 88%; border: 1px solid #333; }
    .thinking { background: #1c241e; color: #9fd8ad; border-color: #2c4733; font-style: italic; }
    .who { font-size: 12px; opacity: 0.75; margin-bottom: 4px; }
    .error { background: #5a1d1d; color: #ffd6d6; padding: 10px; border-radius: 6px; margin-bottom: 12px; display: none; }
    .send-form { display: flex; gap: 8px; }
    .send-form input { flex: 1; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="bar">
      <strong>Вася АІ</strong>
      <button type="button" onclick="newChat()">+ Новий чат</button>
    </div>

    <div class="chats" id="chatsBar"></div>
    <div class="error" id="errorBox"></div>

    <div class="bar">
      <label for="modeSelect">Режим:</label>
      <select id="modeSelect" onchange="changeMode(this.value)">
        <option value="default">Дефолт</option>
        <option value="smart">Смарт</option>
        <option value="pro">Про</option>
        <option value="pro+">Про+</option>
      </select>
    </div>

    <div class="quota" id="quotaBox"></div>
    <div class="messages" id="messagesBox"></div>

    <form class="send-form" onsubmit="handleSend(event)">
      <input type="text" id="msgInput" placeholder="Напиши завдання, тему есе чи питання..." autocomplete="off" required>
      <button type="submit" id="sendBtn">Надіслати</button>
    </form>
  </div>

  <script>
    const STORAGE_KEY = "vasya_browser_state_v2";
    const BOTS = { vasya: { name: "Вася" } };
    const MODES = {
      "default": { sfx: "дефолт", limit: null },
      "smart": { sfx: "смарт", limit: 40 },
      "pro": { sfx: "про", limit: 25 },
      "pro+": { sfx: "про+", limit: 20 }
    };

    const BASE_HW_RULES =
      " Допомагай зі шкільними завданнями (географія, історія, мова, література, математика, фізика, хімія, біологія та ін.). " +
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

    let isThinking = false, thinkSeconds = 0, thinkTimer = null;
    const ukey = (b, m) => m;

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

    function getActiveChat() {
      if (!state.chats[state.activeChatId]) {
        state.activeChatId = Object.keys(state.chats)[0];
      }
      const c = state.chats[state.activeChatId];
      if (!MODES[c.mode]) c.mode = "default";
      return c;
    }

    function showError(msg) {
      const box = document.getElementById("errorBox");
      if (!msg) {
        box.style.display = "none";
        box.textContent = "";
        return;
      }
      box.style.display = "block";
      box.textContent = msg;
    }

    function startThinking() {
      stopThinking();
      isThinking = true;
      thinkSeconds = 0;
      thinkTimer = setInterval(() => {
        thinkSeconds += 1;
        const el = document.getElementById("thinkingBubble");
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
        function render() {
      const chat = getActiveChat();
      const m = MODES[chat.mode] || MODES.default;
      document.getElementById("modeSelect").value = chat.mode;
      document.getElementById("sendBtn").disabled = isThinking;

      const chatsBar = document.getElementById("chatsBar");
      chatsBar.innerHTML = "";
      Object.values(state.chats).forEach((c) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chat-chip" + (c.id === chat.id ? " active" : "");
        chip.textContent = `Вася · ${c.title}`;
        chip.onclick = () => selectChat(c.id);
        chatsBar.appendChild(chip);
      });

      const quotaBox = document.getElementById("quotaBox");
      const k = ukey("vasya", chat.mode);
      if (m.limit == null) {
        quotaBox.textContent = `Вася ${m.sfx}: безліміт`;
      } else {
        const used = state.usage[k] || 0;
        const rem = Math.max(0, m.limit - used);
        quotaBox.textContent = `Вася ${m.sfx}: залишилось ${rem}/${m.limit}`;
      }

      const msgBox = document.getElementById("messagesBox");
      msgBox.innerHTML = "";
      (chat.messages || []).forEach((item) => {
        const div = document.createElement("div");
        div.className = "msg " + (item.role === "user" ? "user" : "assistant");
        const who = document.createElement("div");
        who.className = "who";
        who.textContent = item.role === "user" ? "Ти" : "Вася";
        const body = document.createElement("div");
        body.textContent = item.text;
        div.appendChild(who);
        div.appendChild(body);
        msgBox.appendChild(div);
      });

      if (isThinking) {
        const t = document.createElement("div");
        t.id = "thinkingBubble";
        t.className = "msg assistant thinking";
        t.textContent = `Вася думає... (${thinkSeconds} сек)`;
        msgBox.appendChild(t);
      }
      msgBox.scrollTop = msgBox.scrollHeight;
    }

    async function askInstruction(instruction, messages) {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          system: instruction,
          messages: messages.map((m) => ({ role: m.role, text: m.text }))
        })
      });
      let data = {};
      try { data = await res.json(); } catch (e) {}
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      return data.reply || data.text || "Порожня відповідь";
    }

    async function handleSend(e) {
      e.preventDefault();
      if (isThinking) return;
      showError("");

      const chat = getActiveChat();
      const m = MODES[chat.mode] || MODES.default;
      const input = document.getElementById("msgInput");
      const text = input.value.trim();
      if (!text) return;

      const k = ukey("vasya", chat.mode);
      if (m.limit != null && (state.usage[k] || 0) >= m.limit) {
        showError(`Ліміт для режиму ${m.sfx} вичерпано.`);
        return;
      }

      const firstTitle = chat.title === "Новий чат";
      chat.messages.push({ role: "user", text });
      if (firstTitle) chat.title = text.slice(0, 32) || "Чат";
      input.value = "";
      saveState();
      startThinking();
      render();

      try {
        const sys = (INSTR.vasya && INSTR.vasya[chat.mode]) || INSTR.vasya.default;
        const reply = await askInstruction(sys, chat.messages);
        chat.messages.push({ role: "assistant", text: reply });
        if (m.limit != null) state.usage[k] = (state.usage[k] || 0) + 1;
        saveState();
      } catch (err) {
        chat.messages.pop();
        if (firstTitle && !chat.messages.length) chat.title = "Новий чат";
        input.value = text;
        saveState();
        showError("Помилка запиту: " + err.message);
      } finally {
        stopThinking();
        render();
      }
    }

    render();
  </script>
</body>
</html>
'''


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

    if not API_KEY:
        return err("На сервері не задано GEMINI_API_KEY", 500)

    data = request.get_json(silent=True) or {}
    system_text = str(data.get("system") or "")[:4000]
    raw_msgs = data.get("messages")
    msgs = []

    if isinstance(raw_msgs, list):
        for item in raw_msgs[-20:]:
            if isinstance(item, dict):
                role = "model" if item.get("role") == "assistant" else "user"
                text = str(item.get("text") or "")[:8000]
                if text:
                    msgs.append({"role": role, "parts": [{"text": text}]})

    if not msgs:
        return err("Порожнє повідомлення", 400)

    payload = {
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": msgs,
    }
    if ENABLE_SEARCH == "1":
        payload["tools"] = [{"google_search": {}}]

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
        r = requests.post(
            url,
            headers={"x-goog-api-key": API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=25,
        )
        if r.status_code != 200:
            return err(f"Помилка моделі ({r.status_code}). Спробуй ще раз.", 502)

        body = r.json()
        candidates = body.get("candidates") or []
        parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
        text_out = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p)
        return jsonify({"reply": text_out.strip() or "Порожня відповідь"})
    except requests.Timeout:
        return err("Відповідь зайняла забагато часу. Спробуй ще раз.", 504)
    except Exception as e:
        return err(f"Помилка сервера: {e}", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
      
