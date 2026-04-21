"""
Telegram Monitor Agent — моніторить Saved Messages на YouTube посилання.

Як використовувати:
  1. Запусти: python agents/telegram_monitor/run.py
  2. З телефона надішли YouTube посилання самому собі (Saved Messages)
  3. Агент знаходить посилання → transcript → Claude summary → відповідь в Telegram

Потрібен Mac бути увімкненим.
"""

import asyncio
import os
import re

from telethon import TelegramClient, events

from agents.youtube_agent.transcript import get_video_id, get_transcript
from agents.youtube_agent.summarizer import summarize, format_telegram_message
from core.logger import get_logger

logger = get_logger(__name__)

_YOUTUBE_RE = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com/watch\?[^\s]*v=|youtu\.be/)[\w\-]+"
)

_SESSION_PATH = str(
    __import__("pathlib").Path(__file__).parent.parent.parent / "data" / "tg_session"
)


class TelegramMonitorAgent:
    """Моніторить Saved Messages і обробляє YouTube посилання."""

    agent_id = "telegram-monitor-v1"

    def __init__(self):
        self.api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
        self.api_hash = os.getenv("TELEGRAM_API_HASH", "")
        self.client = TelegramClient(_SESSION_PATH, self.api_id, self.api_hash)

    async def start(self):
        """Запускає моніторинг — блокуючий виклик."""
        await self.client.start()
        me = await self.client.get_me()
        self._my_id = me.id
        logger.info("Telegram Monitor: підключено як %s (id=%s)", me.first_name, me.id)

        @self.client.on(events.NewMessage())
        async def handler(event):
            peer_id = getattr(event.peer_id, "user_id", None)
            logger.info(
                "Monitor: подія — peer=%s out=%s private=%s text=%r",
                peer_id, event.out, event.is_private, (event.text or "")[:80],
            )
            # Реагуємо тільки на Saved Messages (чат сам з собою)
            if not event.is_private:
                return
            if peer_id != self._my_id:
                return

            urls = self._extract_youtube_urls(event)
            logger.info("Monitor: повідомлення від себе, URLs: %s", urls)
            for url in urls:
                asyncio.create_task(self._process(url))

        logger.info("Telegram Monitor: слухаю Saved Messages...")
        await self.client.run_until_disconnected()

    def _extract_youtube_urls(self, event) -> list[str]:
        """Витягує YouTube URLs з тексту повідомлення і з медіа-превʼю."""
        urls = set()
        if event.text:
            urls.update(_YOUTUBE_RE.findall(event.text))
        # MessageMediaWebPage — коли шариш відео з YouTube-апки
        media = getattr(event.message, "media", None)
        if media:
            webpage = getattr(media, "webpage", None)
            if webpage:
                if getattr(webpage, "url", None):
                    if _YOUTUBE_RE.match(webpage.url):
                        urls.add(webpage.url)
                if getattr(webpage, "display_url", None):
                    candidate = "https://" + webpage.display_url
                    if _YOUTUBE_RE.match(candidate):
                        urls.add(candidate)
        return list(urls)

    async def _process(self, url: str):
        """Обробляє YouTube URL і відповідає summary в Saved Messages."""
        logger.info("Monitor: обробляю %s", url)

        try:
            await self.client.send_message("me", f"⏳ Аналізую відео...")

            video_id = get_video_id(url)
            transcript_data = await asyncio.to_thread(get_transcript, video_id)

            await self.client.send_message("me", "🧠 Claude робить summary...")

            summary = await asyncio.to_thread(summarize, transcript_data["text"], url)
            message = format_telegram_message(
                title=f"Відео {video_id}", url=url, summary=summary
            )

            await self.client.send_message("me", message, parse_mode="html")
            logger.info("Monitor: summary відправлено для %s", video_id)

        except Exception as e:
            logger.error("Monitor: помилка при обробці %s: %s", url, e)
            await self.client.send_message("me", f"❌ Помилка: {e}")
