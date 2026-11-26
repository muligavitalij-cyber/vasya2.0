import asyncio
import io
import os
import re
import time
import edge_tts
import requests
from flask import Flask, jsonify, request, send_file, send_from_directory
from pixabay_photo import process_photo_markers, search_pixabay_photo
from prompt_builder import build_system_prompt, clean_display_text
from web_search import needs_web_search, web_search

app = Flask(__name__)

BASE_DAILY_LIMIT = 250
BONUS_PER_EXTRA_KEY = 0

REQUEST_COSTS = {
    "small": 1,
    "medium": 3,
    "large": 10,
}

LARGE_KEYWORDS = [
    "великий код",
    "напиши код",
    "напиши програму",
    "напиши сайт",
    "напиши скрипт",
    "твір",
    "есе",
    "велике есе",
    "доповідь",
    "реферат",
    "з нуля",
    "архітектур",
    "детальний розбір",
    "повний код",
    "багато коду",
]

MEDIUM_KEYWORDS = [
    "поясни",
    "інформац",
    "порівняй",
    "приклади",
    "як працює",
    "зроби план",
    "короткий код",
    "фрагмент коду",
    "виправ помилку",
    "чому",
    "навіщо",
]

MODE_MODELS = {
    "fast": [
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-3-5-lightning:free",
    ],
    "study": [
        "google/gemma-4-31b-it:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "google/gemma-4-26b-a4b-it:free",
    ],
    "smart": [
        "google/gemma-4-31b-it:free",
        "recursive/flint-v1:0:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    ],
    "pro": [
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "google/gemma-4-31b-it:free",
    ],
}

ALL_FALLBACK_MODELS = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-5-lightning:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "recursive/flint-v1:0:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
]

VISION_MODELS = [
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
]

USAGE_STORE: dict[str, dict] = {}
KEY_CURSOR = 0


def get_api_keys() -> list[str]:
    return [
        k.strip()
        for k in [
            os.getenv("OPENROUTER_API_KEY", ""),
            os.getenv("OPENROUTER_API_KEY_2", ""),
            os.getenv("OPENROUTER_API_KEY_3", ""),
            os.getenv("OPENROUTER_API_KEY_4", ""),
            os.getenv("OPENROUTER_API_KEY_5", ""),
            os.getenv("OPENROUTER_API_KEY_6", ""),
        ]
        if k and k.strip()
    ]


def get_effective_daily_limit(keys_count: int) -> int:
    extra_keys = max(0, keys_count - 1)
    return BASE_DAILY_LIMIT + (extra_keys * BONUS_PER_EXTRA_KEY)


def classify_request(text: str, has_image: bool = False) -> tuple[str, int]:
    clean = (text or "").strip()
    lower = clean.lower()
    length = len(clean)

    if any(kw in lower for kw in LARGE_KEYWORDS) or length >= 450:
        return "large", REQUEST_COSTS["large"]

    if has_image or any(kw in lower for kw in MEDIUM_KEYWORDS) or length >= 90:
        return "medium", REQUEST_COSTS["medium"]

    return "small", REQUEST_COSTS["small"]


def get_day_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def get_client_bucket(client_id: str, daily_limit: int) -> dict:
    safe_id = (client_id or "anon").strip()[:64] or "anon"
    today = get_day_key()
    entry = USAGE_STORE.get(safe_id)
    if not entry or entry.get("day") != today:
        entry = {"day": today, "used": 0, "limit": daily_limit}
        USAGE_STORE[safe_id] = entry
    entry["limit"] = daily_limit
    return entry


@app.get("/")
def home():
    return send_from_directory(".", "index.html")


@app.get("/icon.png")
def favicon():
    return send_from_directory(".", "icon.png")


@app.get("/api/limit-status")
def limit_status():
    client_id = (request.args.get("client_id") or "anon").strip()
    keys = get_api_keys()
    daily_limit = get_effective_daily_limit(len(keys))
    bucket = get_client_bucket(client_id, daily_limit)
    remaining = max(0, bucket["limit"] - bucket["used"])
    return jsonify({
        "used": bucket["used"],
        "limit": bucket["limit"],
        "remaining": remaining,
        "costs": REQUEST_COSTS,
    })


@app.post("/api/tts")
def tts_endpoint():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    voice = (data.get("voice") or "uk-UA-OstapNeural").strip()

    if voice not in ("uk-UA-OstapNeural", "uk-UA-PolinaNeural"):
        voice = "uk-UA-OstapNeural"

    if not text:
        return jsonify({"error": "Немає тексту для озвучування."}), 400

    safe_text = text[:1200]

    async def _synth():
        communicate = edge_tts.Communicate(safe_text, voice=voice)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                buf.write(chunk.get("data", b""))
        buf.seek(0)
        return buf

    try:
        audio_buf = asyncio.run(_synth())
        if audio_buf.getbuffer().nbytes == 0:
            return jsonify({"error": "Не вдалося згенерувати голос."}), 502
        return send_file(audio_buf, mimetype="audio/mpeg")
    except Exception as exc:
        print(f"[TTS] error={exc}")
        return jsonify({"error": "Помилка озвучування."}), 500


def get_candidate_models(mode: str, has_image: bool = False) -> list[str]:
    if has_image:
        return list(VISION_MODELS)

    chosen = MODE_MODELS.get(mode, [])
    merged = list(chosen)
    for m in ALL_FALLBACK_MODELS:
        if m not in merged:
            merged.append(m)
    return merged[:4]


def build_user_content(text: str, image_data: str | None):
    if image_data:
        return [
            {"type": "text", "text": text if text else "Що зображено на цьому фото?"},
            {"type": "image_url", "image_url": {"url": image_data}},
        ]
    return text


def _extract_reasoning_from_text(raw: str) -> tuple[str, str]:
    if not raw:
        return "", ""
    reasons = []
    for match in re.finditer(r"<think>([\s\S]*?)</think>", raw, flags=re.IGNORECASE):
        chunk = (match.group(1) or "").strip()
        if chunk:
            reasons.append(chunk)
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    return cleaned, "\n\n".join(reasons).strip()


def call_openrouter(
    messages: list[dict],
    models: list[str],
    api_keys: list[str],
) -> tuple[str | None, str]:
    global KEY_CURSOR

    if not api_keys:
        return None, ""

    headers_base = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://vasya2-0.vercel.app",
        "X-Title": "Vasya AI",
    }

    keys_count = len(api_keys)

    for step_idx, model_name in enumerate(models):
        key_slot = (KEY_CURSOR + step_idx) % keys_count
        api_key = api_keys[key_slot]
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
                timeout=11,
            )

            if resp.status_code == 429 and keys_count > 1:
                alt_slot = (key_slot + 1) % keys_count
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        **headers_base,
                        "Authorization": f"Bearer {api_keys[alt_slot]}",
                    },
                    json={
                        "model": model_name,
                        "messages": messages,
                    },
                    timeout=11,
                )

            if resp.status_code != 200:
                print(f"[OpenRouter] {model_name} status={resp.status_code}")
                continue

            payload = resp.json()
            choices = payload.get("choices") or []
            if not choices:
                continue

            msg_obj = choices[0].get("message") or {}
            raw_content = msg_obj.get("content")
            if isinstance(raw_content, list):
                text_parts = [
                    part.get("text", "")
                    for part in raw_content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                raw_text = "".join(text_parts).strip()
            elif isinstance(raw_content, str):
                raw_text = raw_content.strip()
            else:
                raw_text = ""

            cleaned_text, _ = _extract_reasoning_from_text(raw_text)

            if cleaned_text:
                KEY_CURSOR = (key_slot + 1) % keys_count
                return cleaned_text, model_name
        except Exception as exc:
            print(f"[OpenRouter] {model_name} error={exc}")
            continue

    return None, ""


def _extract_fallback_photo_query(user_text: str) -> str:
    lower = (user_text or "").lower().strip()
    if not lower:
        return ""
    if not any(word in lower for word in ("фото", "картинк", "зображен", "покаж", "скин", "photo", "image")):
        return ""

    quick_map = {
        "тигр": "tiger",
        "кота": "cute cat",
        "кіт": "cute cat",
        "кішка": "cute cat",
        "собаки": "happy dog",
        "собака": "happy dog",
        "пес": "happy dog",
        "жаби": "green frog",
        "жаба": "green frog",
        "людини": "person portrait",
        "людина": "person portrait",
        "вовка": "wolf",
        "вовк": "wolf",
        "ведмедя": "bear",
        "ведмідь": "bear",
        "лисиці": "fox",
        "лисиця": "fox",
        "машини": "car",
        "машина": "car",
        "авто": "car",
        "робота": "robot",
        "робот": "robot",
        "природи": "nature landscape",
        "природа": "nature landscape",
    }
    for uk_key, en_val in quick_map.items():
        if re.search(rf"\b{re.escape(uk_key)}\b", lower):
            return en_val

    cleaned = re.sub(r"\b(скинь|покажи|дай|знайди|фото|картинку|зображення|мені|будь ласка)\b", "", lower)
    cleaned = re.sub(r"[^a-zа-яіїєґ0-9\s-]", " ", cleaned)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned[:60]


@app.post("/api/chat")
def chat_endpoint():
    data = request.get_json(silent=True) or {}

    user_text = (data.get("message") or "").strip()
    model_mode = (data.get("model_mode") or "auto").strip().lower()
    image_data = data.get("image")
    history = data.get("history") or []
    client_id = (data.get("client_id") or "anon").strip()

    if not user_text and not image_data:
        return jsonify({"error": "Порожній запит."}), 400

    api_keys = get_api_keys()
    daily_limit = get_effective_daily_limit(len(api_keys))
    bucket = get_client_bucket(client_id, daily_limit)

    size_tier, cost = classify_request(user_text, has_image=bool(image_data))
    remaining = max(0, bucket["limit"] - bucket["used"])

    if cost > remaining:
        return jsonify({
            "reply": (
                f"Не вистачає ліміту на сьогодні: цей запит оцінено як {size_tier} ({cost} од.), "
                f"а залишилось {remaining} з {bucket['limit']} од."
            ),
            "photos": [],
            "thoughts": f"• Ліміт вичерпано: потрібно {cost} од., залишилось {remaining} од.",
            "limit_exceeded": True,
            "size_tier": size_tier,
            "cost": cost,
            "used": bucket["used"],
            "limit": bucket["limit"],
            "remaining": remaining,
        }), 429

    trace: list[str] = [f"• Режим: {model_mode} • Оцінка: {size_tier} ({cost} од.)"]
    has_image = bool(image_data)
    if has_image:
        trace.append("• Розглядаю прикріплене фото")

    search_ctx = ""
    if user_text and needs_web_search(user_text):
        trace.append(f"• Шукаю в інтернеті: «{user_text[:70]}»")
        search_ctx = web_search(user_text)
        trace.append("• Дані вебпошуку отримано" if search_ctx else "• Вебпошук не дав додаткових результатів")

    system_prompt = build_system_prompt(
        search_context=search_ctx,
        mode=model_mode,
        has_image=has_image,
    )

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

    models_to_try = get_candidate_models(model_mode, has_image=has_image)
    reply, _ = call_openrouter(
        messages=messages,
        models=models_to_try,
        api_keys=api_keys,
    )

    if not reply:
        fallback_q = _extract_fallback_photo_query(user_text)
        if fallback_q:
            trace.append(f"• Шукаю фото на Pixabay: «{fallback_q}»")
            fallback_photo = search_pixabay_photo(fallback_q)
            if fallback_photo:
                trace.append("• Фото на Pixabay знайдено")
                bucket["used"] += cost
                new_remaining = max(0, bucket["limit"] - bucket["used"])
                return jsonify({
                    "reply": "Тримай фото за твоїм запитом:",
                    "photos": [fallback_photo],
                    "thoughts": "\n".join(trace),
                    "size_tier": size_tier,
                    "cost": cost,
                    "used": bucket["used"],
                    "limit": bucket["limit"],
                    "remaining": new_remaining,
                })
            trace.append("• На Pixabay фото за цим запитом не знайдено")

        trace.append("• Не вдалося сформувати відповідь з першої спроби")
        return jsonify({
            "reply": "На жаль, зараз не вдалося відповісти. Спробуй ще раз.",
            "photos": [],
            "thoughts": "\n".join(trace),
            "size_tier": size_tier,
            "cost": cost,
            "used": bucket["used"],
            "limit": bucket["limit"],
            "remaining": remaining,
        }), 502

    reply, photos = process_photo_markers(reply)
    if photos:
        trace.append(f"• Підтягнуто фото з Pixabay: {len(photos)}")
    reply = clean_display_text(reply)

    if photos and (not reply or "порожня відповідь від сервера" in reply.lower()):
        reply = "Тримай фото за твоїм запитом!"

    trace.append("• Розібрався із запитом і підготував відповідь")

    bucket["used"] += cost
    new_remaining = max(0, bucket["limit"] - bucket["used"])

    return jsonify({
        "reply": reply,
        "photos": photos,
        "thoughts": "\n".join(trace),
        "size_tier": size_tier,
        "cost": cost,
        "used": bucket["used"],
        "limit": bucket["limit"],
        "remaining": new_remaining,
    })
