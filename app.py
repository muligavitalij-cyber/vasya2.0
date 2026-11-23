import os
import requests
from flask import Flask, jsonify, request
from prompt_builder import build_system_prompt
from web_search import needs_web_search, web_search

app = Flask(__name__)

MODE_MODELS = {
    "fast": [
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-3-5-lightning:free",
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
            os.getenv("OPENROUTER_API_KEY_4", ""),
            os.getenv("OPENROUTER_API_KEY_5", ""),
            os.getenv("OPENROUTER_API_KEY_6", ""),
        ]
        if k and k.strip()
    ]

    models_to_try = get_candidate_models(model_mode, has_image=bool(image_data))
    reply = call_openrouter(messages=messages, models=models_to_try, api_keys=api_keys)

    if not reply:
        return jsonify({"reply": "На жаль, зараз жодна модель не змогла відповісти. Спробуй ще раз."}), 502

    return jsonify({"reply": reply})
    
