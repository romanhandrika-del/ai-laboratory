"""
Design Generator — генерує дизайн-бриф + HTML/CSS макет через Claude.
"""

import json
import os
import re

import anthropic

from core.logger import get_logger
from core.base_agent import MODEL_SONNET, MODEL_HAIKU

logger = get_logger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


_SYSTEM_PROMPT = """\
Ти — senior web designer і frontend-розробник.
Твоє завдання: згенерувати два артефакти — дизайн-бриф і HTML-макет.

ОБОВ'ЯЗКОВО дотримуйся такої структури відповіді (без нічого зайвого до і після):

---BRIEF---
[дизайн-бриф у Markdown]
---HTML---
[повний self-contained HTML5 документ]

=== ФОРМАТ БРИФУ (Markdown) ===
# Design Brief

## Design Tokens
- **Primary color:** #hex
- **Secondary color:** #hex
- **Accent:** #hex
- **Background:** #hex
- **Text:** #hex
- **Primary font:** назва
- **Secondary font:** назва (або sans-serif fallback)

## Page Structure
1. Hero — [опис: заголовок, підзаголовок, CTA-кнопка]
2. Features / Переваги — [3-4 блоки]
3. About / Про нас — [короткий блок]
4. CTA-секція — [заклик до дії]
5. Footer — [контакти, копірайт]

## Tone & Voice
[2-3 речення про стиль комунікації]

=== ФОРМАТ HTML ===
- Повний <!DOCTYPE html> документ, всі стилі у <style> всередині <head>
- Mobile-first responsive (breakpoint 768px)
- Шрифти: Google Fonts @import (1-2 шрифти) або system sans-serif fallback
- Без зовнішніх JS залежностей, без CDN крім Google Fonts
- Усі зображення — CSS gradients або SVG placeholders (без <img src="...">)
- Анімації: лише CSS transition/transform (без JS)
- Семантичний HTML5: header, main, section, footer
- Текст — демо-контент відповідно до теми сайту, українською або мовою бренду\
"""


def generate_from_url(visual_data: dict, seo_data: dict, url: str) -> tuple[str, str]:
    """
    Генерує редизайн на основі scraped даних сайту.

    Returns:
        (brief_md, mockup_html)
    """
    visual_json = json.dumps(visual_data, ensure_ascii=False, indent=2)
    seo_json = json.dumps(seo_data, ensure_ascii=False, indent=2)
    user_msg = (
        f"URL сайту для редизайну: {url}\n\n"
        f"Поточний дизайн (extracted):\n```json\n{visual_json}\n```\n\n"
        f"SEO/контент:\n```json\n{seo_json}\n```\n\n"
        f"Завдання: проаналізуй поточний дизайн і згенеруй ПОКРАЩЕНИЙ редизайн — "
        f"сучасний, mobile-first, з чіткою ієрархією. Збережи тематику та ключові меседжі сайту."
    )
    return _call_claude(user_msg)


def generate_from_brief(user_brief: str) -> tuple[str, str]:
    """
    Генерує лендінг з нуля за текстовим описом.

    Returns:
        (brief_md, mockup_html)
    """
    user_msg = (
        f"Бриф для нового лендінгу:\n{user_brief}\n\n"
        f"Завдання: на основі цього брифу згенеруй сучасний, конверсійний лендінг. "
        f"Вибери відповідну колірну схему та типографіку."
    )
    return _call_claude(user_msg)


def _call_claude(user_msg: str) -> tuple[str, str]:
    client = _get_client()
    logger.info("DesignGenerator: відправляю в Claude (~%d символів)...", len(user_msg))

    try:
        response = client.messages.create(
            model=MODEL_SONNET,
            max_tokens=16000,
            system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text
    except Exception as e:
        logger.warning("DesignGenerator: Sonnet недоступний, fallback на Haiku: %s", e)
        response = _get_client().messages.create(
            model=MODEL_HAIKU,
            max_tokens=12000,
            messages=[{"role": "user", "content": f"Системний промпт:\n{_SYSTEM_PROMPT}\n\n{user_msg}"}],
        )
        raw = response.content[0].text

    brief_md, mockup_html = _parse_response(raw)
    logger.info("DesignGenerator: brief=%d chars, html=%d chars", len(brief_md), len(mockup_html))
    return brief_md, mockup_html


def _parse_response(raw: str) -> tuple[str, str]:
    brief_match = re.search(r"---BRIEF---\s*(.*?)---HTML---", raw, re.DOTALL)
    html_match = re.search(r"---HTML---\s*(.*?)$", raw, re.DOTALL)

    brief_md = brief_match.group(1).strip() if brief_match else raw
    mockup_html = html_match.group(1).strip() if html_match else ""

    if not mockup_html:
        html_block = re.search(r"```html\s*(<!DOCTYPE.*?)```", raw, re.DOTALL | re.IGNORECASE)
        if html_block:
            mockup_html = html_block.group(1).strip()

    if not mockup_html:
        mockup_html = "<html><body><p>HTML не згенеровано — перезапустіть /design</p></body></html>"

    return brief_md, mockup_html


def format_telegram_summary(source: str, mode: str) -> str:
    from html import escape
    icon = "🔗" if mode == "url" else "📝"
    label = f'<a href="{source}">{escape(source)}</a>' if mode == "url" else escape(source[:80])
    return (
        f"🎨 <b>Design Package готовий!</b>\n"
        f"{icon} Джерело: {label}\n\n"
        f"📎 Прикріплено:\n"
        f"  • <code>brief.md</code> — Design tokens + структура + tone\n"
        f"  • <code>mockup.html</code> — Self-contained HTML/CSS макет\n\n"
        f"<i>Відкрий mockup.html у браузері для попереднього перегляду.</i>"
    )
