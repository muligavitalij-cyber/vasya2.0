import json
import os
import random
import re
import time
import urllib.parse
import urllib.request


_HITS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 година на список кандидатів
_RECENT_URLS: list[str] = []
_MAX_RECENT_URLS = 40

_FULL_PHOTO_MARKER_RE = re.compile(
    r"(?m)^[ \t]*\[?PHOTO:\s*([^\[\]\r\n]+?)\]?\s*$|\[PHOTO:\s*([^\[\]\r\n]+?)\]",
    re.IGNORECASE,
)
_BROKEN_TAIL_RE = re.compile(
    r"(?m)^[ \t]*[A-Za-zА-Яа-яІіЇїЄєҐґ][A-Za-zА-Яа-яІіЇїЄєҐґ0-9 _-]{1,60}\][ \t]*$"
)


def _normalize_query(query: str) -> str:
    cleaned = " ".join((query or "").strip().split())
    return cleaned[:100]


def _is_valid_pixabay_query(query: str) -> bool:
    q = _normalize_query(query)
    if len(q) < 2:
        return False
    if "]" in q or "[" in q:
        return False
    # Відсікаємо лише явно обрізані шматки слів без голосних або надто короткі уламки з дефісами/цифрами
    if re.fullmatch(r"[bcdfghjklmnpqrstvwxzбвгджзклмнпрстфхцчшщ]{2,}", q.lower()):
        return False
    return True


def _remember_url(url: str) -> None:
    if not url:
        return
    if url in _RECENT_URLS:
        _RECENT_URLS.remove(url)
    _RECENT_URLS.append(url)
    if len(_RECENT_URLS) > _MAX_RECENT_URLS:
        del _RECENT_URLS[0 : len(_RECENT_URLS) - _MAX_RECENT_URLS]


def _pick_photo_from_hits(hits: list[dict], query: str, exclude_urls: set[str] | None = None) -> dict | None:
    blocked = set(_RECENT_URLS)
    if exclude_urls:
        blocked.update(exclude_urls)

    valid_items: list[dict] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        image_url = (hit.get("webformatURL") or hit.get("largeImageURL") or "").strip()
        if not image_url:
            continue
        # Відсіюємо занадто дрібні картинки, якщо відомий розмір
        width = hit.get("imageWidth") or hit.get("webformatWidth") or 0
        if isinstance(width, (int, float)) and 0 < width < 300:
            continue
        valid_items.append({
            "query": query,
            "image_url": image_url,
            "large_url": (hit.get("largeImageURL") or image_url).strip(),
            "page_url": (hit.get("pageURL") or "https://pixabay.com/").strip(),
            "tags": (hit.get("tags") or query).strip(),
        })

    if not valid_items:
        return None

    fresh_items = [item for item in valid_items if item["image_url"] not in blocked]
    pool = fresh_items if fresh_items else valid_items
    chosen = random.choice(pool)
    _remember_url(chosen["image_url"])
    return chosen


def search_pixabay_photo(query: str, per_page: int = 15, exclude_urls: set[str] | None = None) -> dict | None:
    """
    Шукає реальні фотографії через Pixabay API та повертає різноманітний результат.
    """
    api_key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not api_key:
        return None

    q = _normalize_query(query)
    if not _is_valid_pixabay_query(q):
        return None

    fetch_count = max(8, min(int(per_page), 20))
    cache_key = f"{q.lower()}::{fetch_count}"
    now = time.time()
    cached = _HITS_CACHE.get(cache_key)

    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS and cached[1]:
        picked = _pick_photo_from_hits(cached[1], q, exclude_urls=exclude_urls)
        if picked:
            return picked

    params = urllib.parse.urlencode({
        "key": api_key,
        "q": q,
        "image_type": "photo",
        "safesearch": "true",
        "per_page": fetch_count,
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
        return None

    _HITS_CACHE[cache_key] = (now, hits)
    return _pick_photo_from_hits(hits, q, exclude_urls=exclude_urls)


def process_photo_markers(text: str, max_photos: int = 2) -> tuple[str, list[dict]]:
    """
    Знаходить маркери фото, підтягує різні фото через Pixabay, чистить маркери
    та можливі обрізані хвости з закриваючою дужкою ']' і повертає (очищений_текст, список_фото).
    """
    if not text:
        return text, []

    photos: list[dict] = []
    seen_urls: set[str] = set()

    def _replace(match: re.Match) -> str:
        raw_query = match.group(1) if match.group(1) is not None else match.group(2)
        query = _normalize_query(raw_query or "")
        if not query or len(photos) >= max_photos:
            return ""
        found = search_pixabay_photo(query, exclude_urls=seen_urls)
        if not found:
            return ""
        img_url = (found.get("image_url") or "").strip()
        if not img_url or img_url in seen_urls:
            return ""
        seen_urls.add(img_url)
        photos.append(found)
        return ""

    cleaned_text = _FULL_PHOTO_MARKER_RE.sub(_replace, text)
    cleaned_text = _BROKEN_TAIL_RE.sub("", cleaned_text)
    cleaned_text = re.sub(r"[ \t]{2,}", " ", cleaned_text)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text).strip()
    return cleaned_text, photos
    
