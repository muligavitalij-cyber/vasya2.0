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
      
