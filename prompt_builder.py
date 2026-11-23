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
    }.get(mode, "Підлаштовуй глину відповіді під складність запиту.")

    parts = [rules_block, mode_hint, date_block]
    if search_context:
        parts.append(f"Результати веб-пошуку:\n{search_context}")

    return "\n\n".join(parts)
  
