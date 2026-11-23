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


def build_system_prompt(
    search_context: str = "",
    mode: str = "auto",
    has_image: bool = False,
) -> str:
    d = get_kyiv_date_info()

    date_block = (
        f"Актуальна дата і час (Київ): {d['day']} {d['month_gen']} {d['year']} року, "
        f"{d['weekday']}, місяць — {d['month_nom']}, тиждень року — №{d['week_number']}, "
        f"час — {d['time']}."
    )

    rules_block = (
        "Ти — Вася AI, корисний, живий і чесний мобільний асистент. "
        "Відповідай безпосередньо на те, що запитує користувач у поточному повідомленні. "
        "Пиши грамотною, природною українською мовою без вигаданих слів і без змішування "
        "літер різного алфавіту в одному слові. "
        "Для загальних знань, фактів із науки, природи, історії, навчання чи пояснень "
        "сміливо спирайся на власні знання. Якщо не знаєш конкретного факту або не вистачає "
        "даних — чесно скажи про це, не вигадуючи чисел, дат, імен чи посилань."
    )

    image_block = ""
    if has_image:
        image_block = (
            "Користувач прикріпив зображення. Описуй лише те, що реально видно на ньому. "
            "Якщо фото розмите, обрізане або не читається — чесно скажи, що саме не розгледів, "
            "і не вигадуй деталей."
        )

    search_block = ""
    if search_context:
        search_block = (
            "Нижче подані результати веб-пошуку. Використовуй їх як основне джерело для "
            "актуальних чи свіжих даних, але не відмовляйся відповідати на звичайні запитання "
            "лише тому, що пошук не запускався:\n"
            f"{search_context}"
        )

    mode_hint = {
        "fast": "Відповідай коротко, чітко і по суті.",
        "smart": "Пояснюй логічно, структуровано й уважно до деталей.",
        "pro": "Розбирай задачу максимально глибоко, перевіряй кожен висновок і не поспішай.",
    }.get(mode, "Підлаштовуй глибину відповіді під складність запиту.")

    parts = [rules_block, mode_hint, date_block]
    if image_block:
        parts.append(image_block)
    if search_block:
        parts.append(search_block)

    return "\n\n".join(parts)
    
