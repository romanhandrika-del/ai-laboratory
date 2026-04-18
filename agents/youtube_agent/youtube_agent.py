"""
YouTube Agent — моніторить YouTube канали та підсумовує нові відео.

Цикл для кожного каналу:
  1. channel_feed()  → список останніх відео (RSS)
  2. is_processed()  → фільтруємо вже оброблені
  3. get_transcript()→ текст відео
  4. summarize()     → ключові тези через Claude
  5. Telegram notify + mark_processed()
"""

import asyncio
import os
from pathlib import Path

import yaml

from agents.youtube_agent.channel_feed import get_recent_videos
from agents.youtube_agent.transcript import get_transcript
from agents.youtube_agent.summarizer import summarize, format_telegram_message
from core.youtube_storage import is_processed, mark_processed
from core.logger import get_logger

logger = get_logger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "channels.yaml"


class YouTubeAgent:
    """YouTube Channel Monitor — Agent #2b платформи AI Laboratory."""

    agent_id = "youtube-agent-v1"

    def __init__(self, client_id: str = "default"):
        self.client_id = client_id
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("MANAGER_TELEGRAM_ID", "")

    def _load_channels(self) -> list[dict]:
        """Завантажує список каналів з config/channels.yaml."""
        if not _CONFIG_PATH.exists():
            logger.warning("YouTubeAgent: config/channels.yaml не знайдено")
            return []
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        channels = data.get("youtube_channels", [])
        logger.info("YouTubeAgent: завантажено %d каналів", len(channels))
        return channels

    async def scan_all(self) -> int:
        """
        Сканує всі канали з конфігу.

        Returns:
            Кількість оброблених нових відео
        """
        channels = self._load_channels()
        if not channels:
            return 0

        total_processed = 0
        for channel in channels:
            channel_id = channel.get("channel_id", "").strip()
            name = channel.get("name", channel_id)
            max_videos = channel.get("max_videos_per_run", 3)
            focus = channel.get("focus", "")

            if not channel_id:
                logger.warning("YouTubeAgent: пропускаємо канал без channel_id: %s", name)
                continue

            try:
                count = await self._scan_channel(channel_id, name, max_videos, focus)
                total_processed += count
            except Exception as e:
                logger.error("YouTubeAgent: помилка при скануванні каналу %s: %s", name, e)
                continue

        logger.info("YouTubeAgent: завершено. Оброблено %d нових відео", total_processed)
        return total_processed

    async def _scan_channel(
        self,
        channel_id: str,
        name: str,
        max_videos: int,
        focus: str,
    ) -> int:
        """
        Сканує один канал і обробляє нові відео.

        Returns:
            Кількість оброблених відео
        """
        logger.info("YouTubeAgent: сканую канал %s (%s)", name, channel_id)

        videos = await asyncio.to_thread(get_recent_videos, channel_id, 15)

        new_videos = [v for v in videos if not is_processed(self.client_id, v["video_id"])]
        new_videos = new_videos[:max_videos]

        if not new_videos:
            logger.info("YouTubeAgent: нових відео немає на каналі %s", name)
            return 0

        logger.info("YouTubeAgent: %d нових відео на каналі %s", len(new_videos), name)

        processed_count = 0
        for video in new_videos:
            try:
                await self._process_video(video, name, channel_id, focus)
                processed_count += 1
            except Exception as e:
                logger.error("YouTubeAgent: помилка при обробці %s: %s", video["video_id"], e)
                continue

        return processed_count

    async def _process_video(
        self,
        video: dict,
        channel_name: str,
        channel_id: str,
        focus: str,
    ) -> None:
        """Обробляє одне відео: транскрипція → summary → Telegram."""
        video_id = video["video_id"]
        title = video["title"]
        url = video["url"]

        logger.info("YouTubeAgent: обробляю «%s» (%s)", title, video_id)

        transcript_data = await asyncio.to_thread(get_transcript, video_id)
        summary = await asyncio.to_thread(summarize, transcript_data["text"], url, focus)

        message = format_telegram_message(title=title, url=url, summary=summary, channel_name=channel_name)

        await self._notify(message)
        mark_processed(self.client_id, video_id, channel_id)
        logger.info("YouTubeAgent: «%s» оброблено і відправлено", title)

    async def _notify(self, message: str) -> None:
        """Відправляє Telegram повідомлення."""
        if not self.bot_token or not self.chat_id:
            logger.warning("YouTubeAgent: TELEGRAM_BOT_TOKEN або MANAGER_TELEGRAM_ID не задано")
            print(message)
            return

        from telegram import Bot
        bot = Bot(token=self.bot_token)
        await bot.send_message(
            chat_id=self.chat_id,
            text=message,
            parse_mode="HTML",
        )
