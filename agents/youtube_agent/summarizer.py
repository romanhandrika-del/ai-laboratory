"""
YouTube Summarizer — аналізує транскрипцію через Claude API.

System prompt кешується (prompt caching) — економія ~90% токенів
при повторних викликах з різними відео.
"""

import os
import anthropic

from core.logger import get_logger
from core.base_agent import MODEL_SONNET

logger = get_logger(__name__)

_MAX_TRANSCRIPT_CHARS = 100_000

_DEFAULT_FOCUS = (
    "нові інструменти та підходи AI автоматизації, "
    "практичні кейси для бізнесу з конкретними цифрами та результатами, "
    "рекомендації які можна застосувати прямо зараз"
)

_SYSTEM_TEMPLATE = """\
Ти — аналітик контенту. Твоє завдання: з транскрипції YouTube відео виділити ключові тези.

Фокус аналізу: {focus}

Правила:
- Від 3 до 8 тез, нумерований список
- Кожна теза: 1-2 речення, конкретно і по суті
- Без загальних слів, без реклами, без повторів
- Мова відповіді: українська\
"""


def summarize(transcript_text: str, video_url: str, focus: str = "") -> str:
    """
    Аналізує транскрипцію через Claude API і повертає ключові тези.

    Args:
        transcript_text: Текст транскрипції
        video_url:       URL відео (для контексту)
        focus:           Тематичний фокус аналізу (з channels.yaml або дефолтний)

    Returns:
        Текст з ключовими тезами українською мовою
    """
    if len(transcript_text) > _MAX_TRANSCRIPT_CHARS:
        logger.warning("Transcript обрізано: %d → %d символів", len(transcript_text), _MAX_TRANSCRIPT_CHARS)
        transcript_text = transcript_text[:_MAX_TRANSCRIPT_CHARS]

    system_prompt = _SYSTEM_TEMPLATE.format(focus=focus or _DEFAULT_FOCUS)
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    logger.info("Summarizer: відправляю в Claude (%d символів)...", len(transcript_text))

    response = client.messages.create(
        model=MODEL_SONNET,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Відео: {video_url}\n\nТранскрипція:\n{transcript_text}",
            }
        ],
    )

    summary = response.content[0].text
    logger.info("Summarizer: отримано %d символів відповіді", len(summary))
    return summary


def format_telegram_message(title: str, url: str, summary: str, channel_name: str = "") -> str:
    """Форматує summary у HTML-повідомлення для Telegram."""
    channel_line = f"📺 <b>{channel_name}</b>\n" if channel_name else ""
    return (
        f"🎬 {channel_line}"
        f"<b>{title}</b>\n"
        f"🔗 <a href=\"{url}\">Дивитись на YouTube</a>\n\n"
        f"📌 <b>Ключові тези:</b>\n"
        f"{summary}"
    )
