"""
Fix Generator — генерує пакет SEO-фіксів через Claude.

Формат кожного фіксу сумісний з Фазою 2 (GitHub PR):
  File / Selector / Search-Old / Replace-New / Why
"""

import json
import re
import os

import anthropic

from core.logger import get_logger
from core.base_agent import MODEL_SONNET, MODEL_HAIKU

logger = get_logger(__name__)

MAX_FIXES = 5

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client

_SYSTEM_PROMPT = """\
Ти — SEO-інженер. На вхід отримуєш технічні дані сайту (SEO facts зі scraped HTML).
Твоє завдання: згенерувати МАКСИМУМ 5 найкритичніших фіксів (лише P1 — критичні для індексації).

Для кожного фіксу ОБОВ'ЯЗКОВО дотримуйся цього формату (Markdown):

## Fix #N — [P1] Назва фіксу

**File:** назва файлу або шаблону (наприклад `index.html`, `header.php`, `layout.html`)
**Selector:** CSS-селектор або місце вставки (наприклад `head`, `перед </head>`, `після <body>`)
**Search/Old:** унікальний рядок або тег зі scraped HTML який треба замінити (або `(відсутній — вставити новий)` якщо тег ще не існує)
**Replace/New:**
```html
← готовий HTML-код для вставки ›
```
**Why:** одне речення — очікуваний ефект для SEO/индексації

---

Правила:
- Максимум 5 фіксів — лише P1 (критичні). Зупинись на 5-му навіть якщо є більше проблем.
- Search/Old — ТОЧНИЙ рядок зі scraped HTML (щоб можна було зробити grep у репо). Без інтерпретацій.
- Replace/New — валідний HTML або JSON-LD, готовий до вставки. Для JSON-LD — у тегу `<script type="application/ld+json">`.
- Якщо тег відсутній — Search/Old = `(відсутній — вставити новий)`.
- Мова: українська (тільки для поля Why, решта — технічний код).
- НЕ виводь нічого поза форматом (без вступів, без резюме в кінці).\
"""


def generate(
    facts: dict,
    url: str,
    html_sample: str = "",
    already_applied: list[str] | None = None,
) -> tuple[str, int]:
    """
    Генерує fix-пакет через Claude.

    Args:
        facts:           seo_data + technical_data зі scraper
        url:             URL сайту
        html_sample:     перші ~3000 символів raw HTML (для точного Search/Old)
        already_applied: список фіксів що вже залито на сервер (Claude їх пропустить)

    Returns:
        (fix_md, fix_count)
    """
    client = _get_client()

    facts_json = json.dumps(facts, ensure_ascii=False, indent=2)
    applied_block = ""
    if already_applied:
        items = "\n".join(f"  - {x}" for x in already_applied)
        applied_block = f"\nВже застосовано (НЕ генеруй ці фікси знову):\n{items}\n"
    user_msg = (
        f"URL: {url}\n"
        f"{applied_block}\n"
        f"SEO та технічні дані:\n```json\n{facts_json}\n```\n\n"
        f"Фрагмент scraped HTML (для точних Search/Old рядків):\n```html\n{html_sample[:3000]}\n```"
    )

    logger.info("FixGenerator: відправляю в Claude (~%d символів)...", len(user_msg))

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=4000,
            system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_msg}],
        )
        fix_md = response.content[0].text
    except Exception as e:
        logger.warning("FixGenerator: Sonnet недоступний, fallback на Haiku: %s", e)
        response = _get_client().messages.create(
            model=MODEL_HAIKU,
            max_tokens=3000,
            messages=[{"role": "user", "content": f"Системний промпт:\n{_SYSTEM_PROMPT}\n\n{user_msg}"}],
        )
        fix_md = response.content[0].text

    fix_count = _count_fixes(fix_md)
    if fix_count > MAX_FIXES:
        fix_md = _trim_to_max(fix_md, MAX_FIXES)
        fix_count = MAX_FIXES

    logger.info("FixGenerator: %d фіксів, %d символів", fix_count, len(fix_md))
    return fix_md, fix_count


def _count_fixes(md: str) -> int:
    return len(re.findall(r"^## Fix #\d+", md, re.MULTILINE))


def _trim_to_max(md: str, max_n: int) -> str:
    """Обрізає markdown до перших max_n фіксів."""
    pattern = r"(^## Fix #\d+.*?)(?=^## Fix #\d+|\Z)"
    blocks = re.findall(pattern, md, re.MULTILINE | re.DOTALL)
    return "\n".join(blocks[:max_n]).strip()


def format_telegram_summary(url: str, fix_count: int) -> str:
    from html import escape
    return (
        f"🔧 <b>Fix Package:</b> <a href=\"{url}\">{escape(url)}</a>\n"
        f"✅ <b>Згенеровано фіксів P1:</b> {fix_count}\n\n"
        f"📎 Пакет фіксів — у прикріпленому файлі\n"
        f"<i>Статус: generated → вставте код → pushed → verified</i>"
    )
