import asyncio
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from flask import Flask, jsonify, request, send_file, send_from_directory

from pixabay_photo import process_photo_markers, search_pixabay_photo
from prompt_builder import build_system_prompt, clean_display_text

try:
    import edge_tts
except Exception:
    edge_tts = None


app = Flask(__name__, static_folder=".", static_url_path="")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MODELS_BY_MODE = {
    "fast": [
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-3.5-super-vl:free",
        "google/gemma-4-31b-it:free",
        "nvidia/nemotron-3-ultra:free",
    ],
    "smart": [
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-3.5-super-vl:free",
        "nvidia/nemotron-3-ultra:free",
    ],
    "pro": [
        "google/gemma-4-31b-it:free",
        "nvidia/nemotron-3-ultra:free",
        "nvidia/nemotron-3.5-super-vl:free",
        "google/gemma-4-26b-a4b-it:free",
    ],
    "study": [
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-3.5-super-vl:free",
        "nvidia/nemotron-3-ultra:free",
    ],
}

AUTO_CHAIN = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "nvidia/nemotron-3-ultra:free",
]

_KEY_CURSOR = 0


def get_api_keys() -> list[str]:
    env_names = [
        "OPENROUTER_API_KEY",
        "OPENROUTER_API_KEY_2",
        "OPENROUTER_API_KEY_3",
        "OPENROUTER_API_KEY_4",
        "OPENROUTER_API_KEY_5",
        "OPENROUTER_API_KEY_6",
        "OPENROUTER_API_KEY_7",
        "OPENROUTER_API_KEY_8",
        # "OPENROUTER_API_KEY_9",
    ]

    keys: list[str] = []
    seen: set[str] = set()

    for name in env_names:
        val = (os.environ.get(name) or "").strip()
        if val and val not in seen:
            seen.add(val)
            keys.append(val)

    return keys


def ordered_keys_for_request() -> list[str]:
    global _KEY_CURSOR
    keys = get_api_keys()
    if not keys:
        return []
    start = _KEY_CURSOR % len(keys)
    _KEY_CURSOR = (_KEY_CURSOR + 1) % len(keys)
    return keys[start:] + keys[:start]


def build_model_candidates(mode: str) -> list[str]:
    clean_mode = (mode or "auto").strip().lower()
    candidates: list[str] = []

    if clean_mode in MODELS_BY_MODE:
        for m in MODELS_BY_MODE[clean_mode]:
            if m and m not in candidates:
                candidates.append(m)

    for m in AUTO_CHAIN:
        if m and m not in candidates:
            candidates.append(m)

    return candidates


def _extract_message_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
        return "\n".join(p.strip() for p in parts if p and p.strip()).strip()
    return ""


def _call_openrouter(
    api_key: str,
    model: str,
    messages: list[dict],
    timeout: int = 16,
) -> tuple[str, str | None]:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.65,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("APP_URL", "https://vasya-ai.vercel.app"),
        "X-Title": "Vasya AI",
    }

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw_body)
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        return "", f"HTTP {exc.code}: {err_body or exc.reason}"
    except Exception as exc:
        return "", str(exc)

    choices = data.get("choices") or []
    if not choices:
        return "", "No choices in response"

    msg = choices[0].get("message") or {}
    text = _extract_message_text(msg.get("content"))
    if not text:
        reasoning = _extract_message_text(msg.get("reasoning_content") or msg.get("reasoning"))
        if reasoning:
            text = reasoning
    if not text:
        return "", "Empty model content"

    return text, None


def _build_api_messages(
    system_prompt: str,
    history: list[dict],
    user_text: str,
    image_data_url: str = "",
) -> list[dict]:
    api_messages: list[dict] = [{"role": "system", "content": system_prompt}]

    if isinstance(history, list):
        for item in history[-10:]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            if role not in ("user", "assistant"):
                continue
            txt = str(item.get("text") or "").strip()
            if not txt:
                continue
            api_messages.append({"role": role, "content": txt[:2500]})

    clean_user = (user_text or "").strip()
    if image_data_url:
        content_parts: list[dict] = []
        if clean_user:
            content_parts.append({"type": "text", "text": clean_user})
        else:
            content_parts.append({"type": "text", "text": "Розглянь це фото та розкажи, що на ньому."})
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": image_data_url},
        })
        api_messages.append({"role": "user", "content": content_parts})
    else:
        api_messages.append({"role": "user", "content": clean_user or "Привіт!"})

    return api_messages


def _fallback_photo_query_if_requested(user_text: str) -> str:
    low = (user_text or "").lower()
    if not re.search(r"\b(фото|картинк|зображен|покаж|скин|photo|image)\b", low):
        return ""
    mapping = {
        "собак": "dog",
        "пес": "dog",
        "цуцен": "puppy",
        "кіт": "cat",
        "кота": "cat",
        "кошен": "kitten",
        "тигр": "tiger",
        "лев": "lion",
        "вовк": "wolf",
        "лисиц": "fox",
        "ведмед": "bear",
        "захід сонц": "sunset",
        "гори": "mountains",
        "море": "sea ocean",
        "ліс": "forest",
        "машин": "car",
        "авто": "car",
        "космос": "space galaxy",
        "сніг": "winter snow",
        "ялинк": "christmas tree",
    }
    for ru_uk_stem, en_q in mapping.items():
        if ru_uk_stem in low:
            return en_q
    return ""


async def _synth_edge_tts(text: str, voice: str) -> bytes:
    communicator = edge_tts.Communicate(text, voice)
    buf = io.BytesIO()
    async for chunk in communicator.stream():
        if chunk.get("type") == "audio" and chunk.get("data"):
            buf.write(chunk["data"])
    return buf.getvalue()


@app.get("/")
def index():
    return send_from_directory(".", "index.html")


@app.get("/api/health")
def health():
    keys = get_api_keys()
    return jsonify({
        "ok": True,
        "keys_loaded": len(keys),
        "tts_available": edge_tts is not None,
    })


@app.post("/api/chat")
def api_chat():
    try:
        data = request.get_json(silent=True) or {}
        user_text = str(data.get("message") or "").strip()
        mode = str(data.get("mode") or "auto").strip().lower()
        preferred_language = str(data.get("language") or "auto").strip().lower()
        history = data.get("history") or []
        image_data_url = str(data.get("image") or data.get("image_base64") or "").strip()

        if not user_text and not image_data_url:
            return jsonify({"error": "Порожній запит"}), 400

        keys = ordered_keys_for_request()
        if not keys:
            return jsonify({
                "reply": "Не знайдено жодного ключа OPENROUTER_API_KEY у налаштуваннях сервера.",
                "error": "Missing API keys",
            }), 200

        system_prompt = build_system_prompt(
            search_context="",
            mode=mode,
            has_image=bool(image_data_url),
            preferred_language=preferred_language,
        )
        api_messages = _build_api_messages(
            system_prompt=system_prompt,
            history=history,
            user_text=user_text,
            image_data_url=image_data_url,
        )

        models = build_model_candidates(mode)
        raw_reply = ""
        last_err = ""
        start_ts = time.time()

        for model_idx, model in enumerate(models):
            if time.time() - start_ts > 42:
                break
            keys_to_try = keys[: min(3, len(keys))]
            if model_idx > 0 and len(keys) > 1:
                rotated = keys[model_idx % len(keys) :] + keys[: model_idx % len(keys)]
                keys_to_try = rotated[: min(2, len(rotated))]

            for key in keys_to_try:
                if time.time() - start_ts > 42:
                    break
                text, err = _call_openrouter(key, model, api_messages, timeout=14)
                if text:
                    raw_reply = text
                    break
                last_err = err or "Unknown error"

            if raw_reply:
                break

        cleaned_text, photos = process_photo_markers(raw_reply, max_photos=2)
        cleaned_text = clean_display_text(cleaned_text)

        if not photos:
            fallback_q = _fallback_photo_query_if_requested(user_text)
            if fallback_q:
                found_photo = search_pixabay_photo(fallback_q)
                if found_photo:
                    photos = [found_photo]

        if not cleaned_text:
            if photos:
                cleaned_text = "Тримай фото, яке вдалося знайти."
            else:
                cleaned_text = (
                    "Моделі зараз не повернули текст. "
                    "Спробуй надіслати запит ще раз за кілька секунд."
                )

        return jsonify({
            "reply": cleaned_text,
            "photos": photos,
            "language": preferred_language,
            "debug_error": last_err if not raw_reply else None,
        })

    except Exception as exc:
        return jsonify({
            "reply": "Стався тимчасовий збій під час обробки запиту. Спробуй ще раз за кілька секунд.",
            "photos": [],
            "error": str(exc),
        }), 200


@app.post("/api/tts")
def api_tts():
    if edge_tts is None:
        return jsonify({"error": "TTS unavailable"}), 503

    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "").strip()[:1200]
    voice = str(data.get("voice") or "uk-UA-OstapNeural").strip()

    if not text:
        return jsonify({"error": "Empty text"}), 400

    try:
        audio_bytes = asyncio.run(_synth_edge_tts(text, voice))
        if not audio_bytes:
            return jsonify({"error": "Empty audio"}), 502
        return send_file(
            io.BytesIO(audio_bytes),
            mimetype="audio/mpeg",
            as_attachment=False,
            download_name="vasya_speech.mp3",
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
