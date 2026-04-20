"""
Report Generator — генерує Markdown-звіт аудиту через Claude Sonnet.
"""

import json
import os
import anthropic
from core.logger import get_logger
from core.base_agent import MODEL_SONNET, MODEL_HAIKU

logger = get_logger(__name__)

_SYSTEM_PROMPT = """\
Ти — експерт з SEO, UX та технічного аудиту сайтів.
Твоє завдання: на основі зібраних технічних даних сайту написати структурований звіт аудиту.

Формат звіту (строго Markdown):

# Аудит сайту: {url}
**Загальний score: X/100**

## Резюме
(2-3 речення: головні сильні сторони та критичні проблеми)

## SEO On-Page (X/25 балів)
### ✅ Добре
- ...
### ⚠️ Проблеми
- **P1 [Критично]:** ...
- **P2 [Важливо]:** ...
- **P3 [Бажано]:** ...

## Google Visibility (X/25 балів)
### ✅ Добре
- ...
### ⚠️ Проблеми
- ...

## Конверсія та UX (X/25 балів)
### ✅ Добре
- ...
### ⚠️ Проблеми
- ...

## Технічний стан (X/25 балів)
### ✅ Добре
- ...
### ⚠️ Проблеми
- ...

## Топ-5 пріоритетних дій
1. **[P1]** Конкретна дія — очікуваний ефект
2. ...

---
*Звіт згенеровано AI Laboratory Website Audit Agent*

Правила:
- Score кожної категорії — ціле число 0-25, загальний score — сума 0-100
- P1 = критично для індексації/конверсії, P2 = важливо, P3 = бажано
- Рекомендації конкретні, без водички (не "покращити контент" а "додати meta description 120-160 символів")
- Якщо даних PageSpeed немає — вкажи це в Google Visibility і не виставляй штраф
- Мова: українська\
"""


def generate(facts: dict, url: str) -> tuple[str, int]:
    """
    Генерує повний Markdown-звіт через Claude.

    Args:
        facts: dict з seo_data, technical_data, pagespeed_data
        url:   URL сайту

    Returns:
        (markdown_report, overall_score)
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    facts_json = json.dumps(facts, ensure_ascii=False, indent=2)

    user_msg = f"URL: {url}\n\nЗібрані дані:\n```json\n{facts_json}\n```"

    logger.info("ReportGenerator: відправляю в Claude (%d символів даних)...", len(facts_json))

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=3000,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_msg}],
        )
        report_md = response.content[0].text
    except Exception as e:
        logger.warning("ReportGenerator: Sonnet недоступний, fallback на Haiku: %s", e)
        response = client.messages.create(
            model=MODEL_HAIKU,
            max_tokens=2000,
            messages=[
                {"role": "user", "content": f"Системний промпт:\n{_SYSTEM_PROMPT}\n\n{user_msg}"}
            ],
        )
        report_md = response.content[0].text

    # Витягуємо score з першого рядка "**Загальний score: X/100**"
    score = _parse_score(report_md)
    logger.info("ReportGenerator: звіт %d символів, score=%d", len(report_md), score)
    return report_md, score


def _parse_score(markdown: str) -> int:
    """Витягує загальний score з тексту звіту."""
    import re
    match = re.search(r"score[:\s]+(\d{1,3})\s*/\s*100", markdown, re.IGNORECASE)
    if match:
        return min(100, int(match.group(1)))
    return 0


def format_telegram_summary(url: str, score: int, report_md: str) -> str:
    """Форматує короткий HTML-summary для Telegram."""
    import re
    from html import escape

    # Топ-5 пріоритетних дій
    actions_block = ""
    m = re.search(r"## Топ-5 пріоритетних дій\n([\s\S]+?)(?:\n---|\Z)", report_md)
    if m:
        actions_raw = m.group(1).strip()
        lines = [l.strip() for l in actions_raw.splitlines() if l.strip()][:5]
        # Екрануємо HTML-символи щоб Telegram не плутав з тегами
        lines = [escape(l) for l in lines]
        actions_block = "\n".join(f"  {l}" for l in lines)

    score_emoji = "🟢" if score >= 70 else ("🟡" if score >= 45 else "🔴")

    text = (
        f'🔍 <b>Аудит сайту:</b> <a href="{url}">{url}</a>\n'
        f"{score_emoji} <b>Score: {score}/100</b>\n\n"
    )
    if actions_block:
        text += f"<b>Топ пріоритетних дій:</b>\n<code>{actions_block}</code>\n\n"
    text += "📎 Повний звіт — у прикріпленому файлі"
    return text
