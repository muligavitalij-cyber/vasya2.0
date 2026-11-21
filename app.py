import os
import hmac
import requests
from flask import Flask, request, jsonify, Response, send_from_directory

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))

# Секрети беруться з Environment у Render, у коді їх немає
API_KEY = os.environ.get("GEMINI_API_KEY")
APP_PASS = os.environ.get("APP_PASS")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

# ---- Сторінка сайту (замість окремого index.html) ----
PAGE = r'''<!doctype html>
<html lang="uk" translate="no">
<head>
  <meta charset="utf-8">
  <meta name="google" content="notranslate">
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
    .msg { padding: 10px 12px; border-radius: 8px; white-space: pre-wrap; line-height: 1.4; }
    .user { background: #1f3a5f; align-self: flex-end; max-width: 88%; }
    .assistant { background: #232323; align-self: flex-start; max-width: 88%; border: 1px solid #333; }
    .thinking { background: #1c241e; color: #9fd8ad; border-color: #2c4733; font-style: italic; }
    .who { font-size: 12px; opacity: 0.75; margin-bottom: 4px; }
    .error { background: #5a1d1d; color: #ffd6d6; padding: 10px; border-radius: 6px; margin-bottom: 12px; display: none; }
    .send-form { display: flex; gap: 8px; }
    .send-form input { flex: 1; }
    .keybox { background: #1b1b1b; border: 1px solid #333; border-radius: 8px; padding: 10px; margin-bottom: 12px; font-size: 14px; }
    .keybox input { flex: 1; min-width: 0; }
    .hint { color: #aaa; font-size: 13px; margin: 6px 0 0; }
    </style>
</head>
<body>
  <div class="wrap">
    <div class="bar">
      <strong>Вася АІ</strong>
      <button type="button" onclick="newChat()">+ Новий чат</button>
    </div>

    <div class="keybox" id="keyBox"></div>

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
      <input type="text" id="msgInput" placeholder="Напиши щось Васі..." autocomplete="off" required>
      <button type="submit" id="sendBtn">Надіслати</button>
    </form>
  </div>

  <script>
    const STORAGE_KEY = "vasya_browser_state_v1";
    const BOTS = { vasya: { name: "Вася" } };
    const MODES = {
      "default": { sfx: "дефолт", limit: null },
      "smart": { sfx: "смарт", limit: 40 },
      "pro": { sfx: "про", limit: 25 },
      "pro+": { sfx: "про+", limit: 20 }
    };
    const INSTR = {
      vasya: {
        "default": "Ти — Вася АІ. Відповідай коротко, чітко і по суті, без води, підлабузництва, зайвого пафосу та вигаданих фактів, коли не впевнений. Спілкуйся природно й по-людськи.",
        "smart": "Ти — Вася АІ у режимі Смарт. Розбирай задачу логічно, пояснюй зрозумілими словами, перевіряй кроки й не вигадуй неіснуючих деталей.",
        "pro": "Ти — Вася АІ у режимі Про. Давай глибокий, продуманий розбір, враховуй деталі, крайні випадки та практичні наслідки, без зайвої театральності.",
        "pro+": "Ти — Вася АІ у режимі Про+. Працюй максимально ретельно й структуровано: шукай слабкі місця, пропонуй сильні рішення, перевіряй логіку до дрібниць."
      }
    };

    let isThinking = false, thinkSeconds = 0, thinkTimer = null;

    const URL_KEY = "vasya_proxy_url", PASS_KEY = "vasya_proxy_pass";
    function getUrl() { try { return localStorage.getItem(URL_KEY) || ""; } catch { return ""; } }
    function getPass() { try { return localStorage.getItem(PASS_KEY) || ""; } catch { return ""; } }
    const getKey = () => getPass();
    const getModel = () => "";
    const ukey = (b, m) => m;

    function createDefaultState() {
      const id = "chat_" + Date.now() + "_" + Math.random().toString(36).slice(2, 7);
      return { usage: {}, activeChatId: id, chats: { [id]: { id, title: "Новий чат", bot: "vasya", mode: "default", messages: [] } } };
    }
    function loadState() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return createDefaultState();
        const p = JSON.parse(raw);
        if (!p.chats || !Object.keys(p.chats).length) return createDefaultState();
        if (!p.usage) p.usage = {};
        return p;
      } catch { return createDefaultState(); }
    }
    let state = loadState();
    function saveState() { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch {} }

    function getActiveChat() {
      if (!state.chats[state.activeChatId]) state.activeChatId = Object.keys(state.chats)[0];
      const c = state.chats[state.activeChatId];
      if (!BOTS[c.bot]) c.bot = "vasya";
      if (!MODES[c.mode]) c.mode = "default";
      return c;
    }
    const botName = () => BOTS[getActiveChat().bot].name;

    function showError(msg) {
      const box = document.getElementById("errorBox");
      box.style.display = msg ? "block" : "none";
      box.textContent = msg || "";
    }

    function renderKeyBox() {
      const box = document.getElementById("keyBox");
      box.innerHTML = "";
      const row = document.createElement("div");
      row.className = "bar";
      row.style.margin = "0";
      if (getPass()) {
        const t = document.createElement("span");
        t.textContent = "🔒 Пароль збережено в цьому браузері" + (getUrl() ? " · сервер: " + getUrl() : "");
        const b = document.createElement("button");
        b.type = "button"; b.className = "grey"; b.textContent = "Забути";
        b.onclick = () => { try { localStorage.removeItem(PASS_KEY); localStorage.removeItem(URL_KEY); } catch {} renderKeyBox(); };
        row.appendChild(t); row.appendChild(b); box.appendChild(row);
      } else {
        const p = document.createElement("input");
        p.type = "password"; p.placeholder = "Пароль до сервера (APP_PASS)"; p.autocomplete = "off";
        const u = document.createElement("input");
        u.type = "text"; u.placeholder = "Адреса сервера (якщо порожньо, цей сайт)"; u.value = getUrl();
        const b = document.createElement("button");
        b.type = "button"; b.textContent = "Зберегти";
        b.onclick = () => {
          const v = p.value.trim();
          if (!v) return;
          try { localStorage.setItem(PASS_KEY, v); localStorage.setItem(URL_KEY, u.value.trim()); } catch {}
          renderKeyBox();
        };
        row.appendChild(p); row.appendChild(u); row.appendChild(b); box.appendChild(row);
        const h = document.createElement("p");
        h.className = "hint";
        h.textContent = "Ключі лежать на сервері, а тут потрібен лише пароль. Він зберігається тільки в цьому браузері.";
        box.appendChild(h);
      }
    }

    function startThinking() {
      stopThinking();
      isThinking = true; thinkSeconds = 0; render();
      thinkTimer = setInterval(() => {
        thinkSeconds += 1;
        const el = document.getElementById("thinkingBubble");
        if (el) el.textContent = `${botName()} думає... (${thinkSeconds} с)`;
      }, 1000);
    }
    function stopThinking() {
      isThinking = false; thinkSeconds = 0;
      if (thinkTimer) { clearInterval(thinkTimer); thinkTimer = null; }
    }

    function newChat() {
      if (isThinking) return;
      const cur = getActiveChat();
      const id = "chat_" + Date.now() + "_" + Math.random().toString(36).slice(2, 7);
      state.chats[id] = { id, title: "Новий чат", bot: cur.bot, mode: cur.mode, messages: [] };
      state.activeChatId = id; saveState(); render();
    }
    function selectChat(id) {
      if (isThinking || !state.chats[id]) return;
      state.activeChatId = id; saveState(); render();
    }
    function changeMode(mode) {
      if (isThinking || !MODES[mode]) return;
      getActiveChat().mode = mode; saveState(); render();
    }
    function render() {
      const chat = getActiveChat(), bot = chat.bot, mode = chat.mode, mi = MODES[mode];
      document.body.setAttribute("data-bot", bot);
      document.getElementById("modeSelect").value = mode;
      document.getElementById("sendBtn").disabled = isThinking;
      renderKeyBox();

      const chatsBar = document.getElementById("chatsBar");
      chatsBar.innerHTML = "";
      Object.values(state.chats).forEach(c => {
        const chip = document.createElement("div");
        chip.className = "chat-chip" + (c.id === chat.id ? " active" : "");
        chip.textContent = `${BOTS[c.bot] ? BOTS[c.bot].name : "Вася"} · ${c.title}`;
        chip.onclick = () => selectChat(c.id);
        chatsBar.appendChild(chip);
      });

      const label = `${BOTS[bot].name} ${mi.sfx}`;
      const quotaBox = document.getElementById("quotaBox");
      if (mi.limit === null) quotaBox.textContent = `${label}: безліміт`;
      else {
        const rem = Math.max(0, mi.limit - (state.usage[ukey(bot, mode)] || 0));
        quotaBox.textContent = `${label}: залишилось ${rem}/${mi.limit}`;
      }

      const msgBox = document.getElementById("messagesBox");
      msgBox.innerHTML = "";
      (chat.messages || []).forEach(m => {
        const div = document.createElement("div");
        div.className = "msg " + m.role;
        const who = document.createElement("div");
        who.className = "who";
        who.textContent = m.role === "user" ? "Ти" : BOTS[bot].name;
        const body = document.createElement("div");
        body.textContent = m.text;
        div.appendChild(who); div.appendChild(body); msgBox.appendChild(div);
      });
      if (isThinking) {
        const t = document.createElement("div");
        t.className = "msg assistant thinking"; t.id = "thinkingBubble";
        t.textContent = `${BOTS[bot].name} думає... (${thinkSeconds} с)`;
        msgBox.appendChild(t);
      }
    }

    async function ask(bot, model, key, instruction, msgs) {
      const base = getUrl().replace(/\/+$/, "");
      const res = await fetch(base + "/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Pass": getPass() },
        body: JSON.stringify({ bot, system: instruction + " Не вказуй, яка саме модель чи компанія за тобою стоїть, якщо тебе прямо про це не питають. Ніколи не заперечуй, що ти штучний інтелект.", messages: msgs.map(m => ({ role: m.role, text: m.text })) })
      });
      let data = {};
      try { data = await res.json(); } catch {}
      if (!res.ok) throw new Error((data.error && data.error.message) || `HTTP ${res.status}`);
      return data.text || "(Порожня відповідь)";
    }

    async function handleSend(e) {
      e.preventDefault();
      if (isThinking) return;
      showError("");
      const chat = getActiveChat(), bot = chat.bot, mode = chat.mode, mi = MODES[mode];
      const key = getKey(bot);
      if (!key) { showError("Спершу встав пароль до сервера угорі й натисни «Зберегти»."); return; }
      const input = document.getElementById("msgInput");
      const text = input.value.trim();
      if (!text) return;
      if (mi.limit !== null && (state.usage[ukey(bot, mode)] || 0) >= mi.limit) {
        showError(`Ліміт для режиму «${BOTS[bot].name} ${mi.sfx}» вичерпано (${mi.limit}/${mi.limit}).`);
        return;
      }
      const firstTitle = chat.title === "Новий чат";
      chat.messages.push({ role: "user", text });
      if (firstTitle) chat.title = text.slice(0, 32) + (text.length > 32 ? "..." : "");
      input.value = "";
      saveState(); startThinking();
      try {
        const reply = await ask(bot, getModel(bot), key, INSTR[bot][mode], chat.messages);
        chat.messages.push({ role: "assistant", text: reply });
        if (mi.limit !== null) state.usage[ukey(bot, mode)] = (state.usage[ukey(bot, mode)] || 0) + 1;
        saveState(); stopThinking(); render();
      } catch (err) {
        chat.messages.pop();
        if (firstTitle && !chat.messages.length) chat.title = "Новий чат";
        input.value = text;
        saveState(); stopThinking(); render();
        const net = err instanceof TypeError;
        showError(net
          ? "Не вдалося з’єднатися з сервером. Render на безкоштовному плані «засинає»: зачекай хвилину й спробуй ще раз."
          : "Помилка запиту: " + err.message);
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
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Pass"
    return resp


def err(msg, code):
    return jsonify({"error": {"message": msg}}), code


@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html")


@app.route("/icon.png")
@app.route("/favicon.ico")
def icon():
    return send_from_directory(BASE, "icon.png", mimetype="image/png")


@app.route("/api/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return "", 204

    if not APP_PASS or not API_KEY:
        return err("Сервер не налаштований", 500)
    given = request.headers.get("X-Pass", "")
    if not hmac.compare_digest(given.encode("utf-8"), APP_PASS.encode("utf-8")):
        return err("Невірний пароль", 403)

    data = request.get_json(silent=True) or {}
    system = str(data.get("system", ""))[:4000]
    msgs = []
    for m in (data.get("messages") or [])[-30:]:
        if isinstance(m, dict):
            role = "model" if m.get("role") == "assistant" else "user"
            msgs.append({"role": role, "parts": [{"text": str(m.get("text", ""))[:8000]}]})
    if not msgs:
        return err("Порожнє повідомлення", 400)

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
        r = requests.post(
            url,
            headers={"x-goog-api-key": API_KEY},
            json={"systemInstruction": {"parts": [{"text": system}]}, "contents": msgs},
            timeout=60,
        )
        if r.status_code != 200:
            print("MODEL ERROR", r.status_code, r.text[:300])
            return err(f"Помилка сервера ({r.status_code}). Спробуй ще раз.", 502)
        parts = r.json()["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
        return jsonify({"text": text or "(Порожня відповідь)"})
    except Exception as e:
        print("SERVER ERROR", e)
        return err("Помилка сервера. Спробуй ще раз.", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
