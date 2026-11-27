from datetime import datetime
import re
from zoneinfo import ZoneInfo


SUPPORTED_REGION_LANGUAGES = (
    "українська, польська, словацька, угорська, румунська, молдовська, "
    "білоруська, болгарська, чеська, німецька, литовська, латиська, "
    "естонська, сербська, хорватська, словенська, грецька, турецька, "
    "англійська, іспанська, італійська, французька та інші європейські й "
    "сусідні мови (крім російської)"
)

NATIVE_LANGUAGE_LABELS = {
    "auto": "Авто",
    "uk": "Українська",
    "en": "English",
    "pl": "Polski",
    "de": "Deutsch",
    "es": "Español",
    "fr": "Français",
    "it": "Italiano",
}

LANGUAGE_ENFORCEMENT = {
    "uk": (
        "Користувач обрав мову відповіді: Українська. Відповідай виключно живою, "
        "природною, грамотною українською мовою незалежно від мови запиту (окрім "
        "власних назв, коду, термінів та прямого прохання перекласти іншою мовою)."
    ),
    "en": (
        "The user selected the response language: English. Respond strictly in clear, "
        "natural English throughout the entire reply (keeping code, formulas, and "
        "requested translations accurate)."
    ),
    "pl": (
        "Użytkownik wybrał język odpowiedzi: Polski. Odpowiadaj wyłącznie w naturalnym, "
        "poprawnym języku polskim w całej odpowiedzi (z zachowaniem kodu, wzorów i "
        "ewentualnych próśb o tłumaczenie)."
    ),
    "de": (
        "Der Nutzer hat die Antwortsprache gewählt: Deutsch. Antworte durchgängig auf "
        "natürlichem, korrektem Deutsch (Code, Formeln und gewünschte Übersetzungen "
        "bleiben dabei sauber erhalten)."
    ),
    "es": (
        "El usuario eligió el idioma de respuesta: Español. Responde siempre en un "
        "español natural y correcto durante toda la respuesta (respetando código, "
        "fórmulas y traducciones solicitadas)."
    ),
    "fr": (
        "L'utilisateur a choisi la langue de réponse : Français. Réponds uniquement en "
        "français naturel et correct sur toute la réponse (en conservant le code, les "
        "formules et les traductions demandées)."
    ),
    "it": (
        "L'utente ha scelto la lingua di risposta: Italiano. Rispondi sempre in un "
        "italiano naturale e corretto per tutta la risposta (mantenendo codice, "
        "formule e traduzioni richieste)."
    ),
}


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


def _strip_latex_and_math_noise(raw: str) -> str:
    if not raw:
        return ""

    text = raw

    text = re.sub(r"\$\$([\s\S]*?)\$\$", r"\1", text)
    text = re.sub(r"(?<!\\)\$([^$\n]+?)(?<!\\)\$", r"\1", text)
    text = re.sub(r"\\\[([\s\S]*?)\\\]", r"\1", text)
    text = re.sub(r"\\\(([\s\S]*?)\\\)", r"\1", text)

    for _ in range(4):
        updated = re.sub(
            r"\\(?:text|mathrm|mathbf|textbf|operatorname|mathit|mathsf)\{([^{}]*)\}",
            r"\1",
            text,
        )
        if updated == text:
            break
        text = updated

    for _ in range(3):
        text = re.sub(r"\\overline\{([^{}]+)\}", r"(\1)", text)
        text = re.sub(r"\\(?:dot|ddot|hat|tilde|vec)\{([^{}]+)\}", r"\1", text)

    for _ in range(6):
        updated = re.sub(
            r"\\d?[tf]?rac\{([^{}]+)\}\{([^{}]+)\}",
            r"(\1)/(\2)",
            text,
        )
        if updated == text:
            break
        text = updated

    text = re.sub(r"\(([0-9A-Za-zА-Яа-яІіЇїЄєҐґ.,\s]+)\)/", r"\1/", text)
    text = re.sub(r"/\(([0-9A-Za-zА-Яа-яІіЇїЄєҐґ.,\s]+)\)", r"/\1", text)

    replacements = {
        "\\times": "×",
        "\\cdot": "·",
        "\\div": "÷",
        "\\pm": "±",
        "\\mp": "∓",
        "\\neq": "≠",
        "\\approx": "≈",
        "\\simeq": "≃",
        "\\equiv": "≡",
        "\\leq": "≤",
        "\\geq": "≥",
        "\\rightarrow": "→",
        "\\leftarrow": "←",
        "\\Rightarrow": "⇒",
        "\\Leftarrow": "⇐",
        "\\%": "%",
        "*": "×",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"\\[a-zA-Z]+", "", text)
    text = re.sub(r"(?m)^[ \t]*[\[\]][ \t]*\r?\n?", "", text)
    text = re.sub(r"\\(?=[ \t\n\r0-9A-Za-zА-Яа-яІіЇїЄєҐґ()=+\-×·÷*/.,:])", "", text)
    text = text.replace("\\", "")
    text = text.replace("{", "").replace("}", "")

    text = re.sub(
        r"([А-Яа-яІіЇїЄєҐґA-Za-z0-9]+)_([А-Яа-яІіЇїЄєҐґA-Za-z0-9]+(?:_[А-Яа-яІіЇїЄєҐґA-Za-z0-9]+)+)",
        lambda m: m.group(0).replace("_", " "),
        text,
    )
    text = re.sub(
        r"(?<=[А-Яа-яІіЇїЄєҐґA-Za-z])_(?=[А-Яа-яІіЇїЄєҐґA-Za-z])",
        " ",
        text,
    )

    return text


def clean_display_text(text: str) -> str:
    if not text:
        return ""

    code_blocks: list[str] = []

    def _save_block(match: re.Match) -> str:
        code_blocks.append(match.group(0))
        return f"@@CODEBLOCK_{len(code_blocks) - 1}@@"

    text = re.sub(r"```[\s\S]*?```", _save_block, text)
    text = _strip_latex_and_math_noise(text)

    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" \n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    for idx, block in enumerate(code_blocks):
        text = text.replace(f"@@CODEBLOCK_{idx}@@", block)

    return text


def build_system_prompt(
    search_context: str = "",
    mode: str = "auto",
    has_image: bool = False,
    preferred_language: str = "auto",
) -> str:
    d = get_kyiv_date_info()

    date_block = (
        f"Актуальна дата і час (Київ): {d['day']} {d['month_gen']} {d['year']} року, "
        f"{d['weekday']}, місяць — {d['month_nom']}, тиждень року — №{d['week_number']}, "
        f"час — {d['time']}."
    )

    identity_and_tone = (
        "Ти — Вася AI, живий, чесний, розумний і уважний помічник. Говори про себе виключно "
        "в чоловічому роді («радий», «готовий», «перевірив», «пояснив», «розібрався») і не "
        "перескакуй на жіночий рід чи безособові конструкції. "
        "Пиши так, як спілкується жива, грамотна й доброзичлива людина: без роботових кліше, "
        "без надмірної сухості, але й без панібратства чи штучної награності. "
        "Відповідай строго по суті того, що питає користувач у поточному повідомленні, "
        "обов'язково враховуючи контекст розмови, попередні репліки та можливі друкарські "
        "помилки користувача."
    )

    lang_key = (preferred_language or "auto").strip().lower()
    if lang_key in LANGUAGE_ENFORCEMENT:
        selected_lang_rule = LANGUAGE_ENFORCEMENT[lang_key]
    else:
        selected_lang_rule = (
            "Обрано режим «Авто»: автоматично визначай мову поточного повідомлення "
            "користувача. Якщо він пише українською — відповідай живою, природною, "
            "грамотною українською мовою. Якщо він пише іншою підтримуваною мовою або "
            "прямо просить відповісти чи перекласти нею — тримай обрану мову протягом "
            "усієї відповіді й не змішуй її з іншими мовами. Якщо мову визначити "
            "неможливо або вона не вказана — пиши природною українською."
        )

    language_rules = (
        f"{selected_lang_rule} "
        "Уникай кальок, русизмів і кривих граматичних форм на кшталт «повз старим млині» чи "
        "«у хлопці»: завжди перевіряй відмінки, прийменники, узгодження слів і велику літеру "
        "у власних назвах та іменах. "
        "Не вставляй англійські слова там, де в українській мові є нормальний природний "
        "відповідник (виняток — терміни програмування, код, команди, посилання, а також "
        "оригінальні назви з аніме й манґи без спотворення). "
        "Ніколи не переходь на російську мову і не відповідай російською за жодних умов, "
        "навіть якщо користувач звертається російською або просить перекласти російською. "
        f"Особливу увагу приділяй точності мови під час роботи з мовами нашого регіону та "
        f"Європи ({SUPPORTED_REGION_LANGUAGES})."
    )

    formulas_and_formatting = (
        "Оформлюй відповіді охайно та зручно для читання на екрані смартфона: розділяй думки "
        "на логічні абзаци, використовуй зрозумілі підзаголовки чи списки там, де це справді "
        "полегшує сприйняття, і не ліпи суцільну стіну тексту. "
        "Ніколи не використовуй сирий LaTeX, зворотні слеші перед формулами, квадратні дужки "
        "навколо виразів або знаки долара на кшталт \\frac, \\times чи $...$. "
        "Не склеюй слова з позначеннями через нижнє підкреслення на кшталт m_солит_вода або "
        "маса_розчину — замість цього пиши формули зрозуміло й чисто: або словами та "
        "звичними позначеннями (наприклад, «масова частка = (маса солі / маса розчину) × 100%»), "
        "або короткими величинами з чітким поясненням, що кожна означає. "
        "Усі дроби записуй просто й читабельно, наприклад 50/250 або 3/4, і не розривай "
        "короткі числові ланцюжки без потреби, щоб розв'язок легко читався навіть на "
        "вузькому екрані телефона."
    )

    truthfulness_and_logic = (
        "Завжди перевіряй базову арифметику та логіку перед тим, як написати відповідь. "
        "Якщо в запитанні є хибна передумова, неможлива дія або помилка в умовах гри чи "
        "задачі — прямо і спокійно вкажи на це, не підігравай неправді. "
        "Не змішуй різні всесвіти, ігри чи поняття та одразу розмежовуй їх, якщо бачиш "
        "плутанину. "
        "Не вигадуй фактів, дат, чисел, цитат чи номерів серій, якщо не впевнений у них: "
        "краще чесно сказати, що не знаєш або не впевнений, ніж вигадувати правдоподібну "
        "нісенітницю. Якщо користувач виправляє тебе або вказує на неточність — визнай "
        "помилку прямо, без виправдань і суперечок, та одразу дай правильний варіант."
    )

    photos_block = (
        "Якщо користувач прямо просить показати фото або картинку і це доречно — постав на "
        "окремому рядку маркер строго у форматі [PHOTO: короткий запит англійською] "
        "(наприклад, [PHOTO: tiger] або [PHOTO: cute cat]). Не вигадуй посилань на зображення "
        "і не додавай маркер [PHOTO: ...], якщо користувач не просив фото чи картинку."
    )

    image_block = ""
    if has_image:
        image_block = (
            "До запиту прикріплено зображення. Описуй лише те, що реально і чітко видно на "
            "картинці чи фото. Не придумуй дрібних деталей, написів, іконок або чисел, якщо "
            "вони нечитабельні чи розмиті. Якщо на фото задача, приклад або текст — спочатку "
            "чітко запиши умову чи вираз, як ти його бачиш, а потім поясни логіку "
            "розв'язання крок за кроком. Якщо щось не розгледів — чесно скажи про це."
        )

    search_block = ""
    if search_context:
        search_block = (
            "Нижче наведені результати вебпошуку. Використовуй їх для перевірки актуальних "
            "фактів, але не відмовляйся відповідати на звичайні запитання, якщо пошук не "
            "додав нічого нового:\n"
            f"{search_context}"
        )

    mode_hint = {
        "fast": (
            "Режим «Швидкий»: давай короткі, точні й зрозумілі відповіді без зайвої води."
        ),
        "smart": (
            "Режим «Смарт»: пояснюй логічно, структуровано й уважно до деталей."
        ),
        "pro": (
            "Режим «Про»: розбирай тему глибоко, продумано й з чіткими висновками."
        ),
        "study": (
            "Режим «Навчання / ДЗ»: пояснюй крок за кроком простою і живою мовою, "
            "показуй хід думок і логіку кожного кроку, звертай увагу на типові помилки й "
            "допомагай розібратися, а не просто кидай суху готову відповідь."
        ),
    }.get(
        mode,
        "Підлаштовуй глибину й обсяг відповіді під складність запиту: на прості питання "
        "відповідай стисло й по суті, а складніші розбирай детальніше.",
    )

    parts = [
        identity_and_tone,
        language_rules,
        formulas_and_formatting,
        truthfulness_and_logic,
        photos_block,
        mode_hint,
        date_block,
    ]
    if image_block:
        parts.append(image_block)
    if search_block:
        parts.append(search_block)

    return "\n\n".join(parts)
    
