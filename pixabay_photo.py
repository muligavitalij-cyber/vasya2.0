import json
import os
import re
import time
import urllib.parse
import urllib.request


_PHOTO_CACHE: dict[str, tuple[float, dict | None]] = {}
_CACHE_TTL_SECONDS = 86400  # 24 години
_PHOTO_MARKER_RE = re.compile(r"\[PHOTO:\s*([^\[\]]+?)\]", re.IGNORECASE)


def _normalize_query(query: str) -> str:
    cleaned = " ".join((query or "").strip().split())
    return cleaned[:100]


def search_pixabay_photo(query: str, per_page: int = 5) -> dict | None:
    """
    Шукає фото через Pixabay API за ключем з оточення PIXABAY_API_KEY.
    Повертає словник з даними фото або None, якщо нічого не знайдено чи сталася помилка.
    """
    api_key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not api_key:
        return None

    q = _normalize_query(query)
    if not q:
        return None

    cache_key = f"{q.lower()}::{per_page}"
    now = time.time()
    cached = _PHOTO_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    params = urllib.parse.urlencode({
        "key": api_key,
        "q": q,
        "image_type": "photo",
        "safesearch": "true",
        "per_page": max(3, min(int(per_page), 20)),
    })
    url = f"https://pixabay.com/api/?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "VasyaAI/2.1"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    hits = payload.get("hits") or []
    if not hits:
        _PHOTO_CACHE[cache_key] = (now, None)
        return None

    first = hits[0]
    image_url = first.get("webformatURL") or first.get("largeImageURL")
    if not image_url:
        _PHOTO_CACHE[cache_key] = (now, None)
        return None

    result = {
        "query": q,
        "image_url": image_url,
        "large_url": first.get("largeImageURL") or image_url,
        "page_url": first.get("pageURL") or "https://pixabay.com/",
        "tags": first.get("tags") or q,
    }
    _PHOTO_CACHE[cache_key] = (now, result)
    return result


def process_photo_markers(text: str, max_photos: int = 2) -> tuple[str, list[dict]]:
    """
    Знаходить маркери [PHOTO: ...] у тексті, підтягує фото через Pixabay,
    прибирає маркери з тексту і повертає (очищений_текст, список_фото).
    """
    if not text:
        return text, []

    photos: list[dict] = []
    seen_urls: set[str] = set()

    def _replace(match: re.Match) -> str:
        query = (match.group(1) or "").strip()
        if not query or len(photos) >= max_photos:
            return ""
        found = search_pixabay_photo(query)
        if not found:
            return ""
        img_url = (found.get("image_url") or "").strip()
        if not img_url or img_url in seen_urls:
            return ""
        seen_urls.add(img_url)
        photos.append(found)
        return ""

    cleaned_text = _PHOTO_MARKER_RE.sub(_replace, text)
    cleaned_text = re.sub(r"[ \t]{2,}", " ", cleaned_text)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()
    return cleaned_text, photos
        
