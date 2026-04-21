"""
Telegram Channel Monitor — моніторить публічні Telegram-канали і коментарі до постів.

Нові пости і коментарі фільтруються по ключових словах і пересилаються
в Saved Messages з міткою каналу. Довгі пости — скорочує Claude.
"""

import asyncio
import os
from pathlib import Path

import yaml
from telethon import TelegramClient, events
from telethon.tl.functions.channels import GetFullChannelRequest

from agents.youtube_agent.summarizer import summarize as claude_summarize
from core.logger import get_logger

logger = get_logger(__name__)

_ROOT = Path(__file__).parent.parent.parent
_SESSION_PATH = str(_ROOT / "data" / "tg_session")
_CONFIG_PATH = _ROOT / "config" / "tg_channels.yaml"

_SUMMARIZE_THRESHOLD = 500


def _load_config() -> list[dict]:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("channels", [])


class ChannelMonitorAgent:
    """Моніторить публічні Telegram-канали і коментарі, пересилає дайджест у Saved Messages."""

    agent_id = "channel-monitor-v1"

    def __init__(self):
        self.api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
        self.api_hash = os.getenv("TELEGRAM_API_HASH", "")
        self.client = TelegramClient(_SESSION_PATH, self.api_id, self.api_hash)
        self.channels = _load_config()
        # discussion_group_id → channel config
        self._discussion_map: dict[int, dict] = {}

    async def start(self):
        await self.client.start()
        me = await self.client.get_me()
        logger.info("Channel Monitor: підключено як %s", me.first_name)

        if not self.channels:
            logger.warning("Channel Monitor: список каналів порожній — додай у config/tg_channels.yaml")
            return

        usernames = [ch["username"] for ch in self.channels]
        channel_map = {ch["username"].lstrip("@").lower(): ch for ch in self.channels}

        # Знаходимо discussion-групи для кожного каналу
        discussion_ids = []
        for ch in self.channels:
            disc_id = await self._get_discussion_id(ch["username"])
            if disc_id:
                self._discussion_map[disc_id] = ch
                discussion_ids.append(disc_id)
                logger.info(
                    "Channel Monitor: «%s» має Discussion group (id=%d)",
                    ch.get("name", ch["username"]), disc_id,
                )
            else:
                logger.info(
                    "Channel Monitor: «%s» — коментарів немає",
                    ch.get("name", ch["username"]),
                )

        logger.info("Channel Monitor: моніторю %d каналів + %d discussion груп",
                    len(usernames), len(discussion_ids))

        # Слухаємо пости каналів
        @self.client.on(events.NewMessage(chats=usernames))
        async def post_handler(event):
            chat = await event.get_chat()
            username = getattr(chat, "username", "") or ""
            cfg = channel_map.get(username.lower(), {})
            asyncio.create_task(self._process_post(event, cfg))

        # Слухаємо коментарі у discussion-групах
        if discussion_ids:
            @self.client.on(events.NewMessage(chats=discussion_ids))
            async def comment_handler(event):
                # Ігноруємо повідомлення що не є відповіддю на пост каналу
                if not event.message.reply_to:
                    return
                # Ігноруємо наші власні повідомлення
                if event.out:
                    return
                chat_id = event.chat_id
                cfg = self._discussion_map.get(chat_id, {})
                asyncio.create_task(self._process_comment(event, cfg))

        await self.client.run_until_disconnected()

    async def _get_discussion_id(self, username: str) -> int | None:
        """Повертає ID discussion-групи каналу або None якщо її немає."""
        try:
            full = await self.client(GetFullChannelRequest(username))
            linked_id = getattr(full.full_chat, "linked_chat_id", None)
            return linked_id
        except Exception as e:
            logger.warning("Channel Monitor: не вдалось отримати discussion для %s: %s", username, e)
            return None

    async def _process_post(self, event, cfg: dict):
        text = event.message.text or event.message.message or ""
        if not text:
            return

        name = cfg.get("name", cfg.get("username", "Канал"))
        min_length = cfg.get("min_length", 50)
        keywords = [kw.lower() for kw in cfg.get("keywords", [])]
        do_summarize = cfg.get("summarize", True)

        if len(text) < min_length:
            return
        if keywords and not any(kw in text.lower() for kw in keywords):
            return

        logger.info("Channel Monitor: новий пост з «%s» (%d символів)", name, len(text))

        if do_summarize and len(text) > _SUMMARIZE_THRESHOLD:
            try:
                summary = await asyncio.to_thread(claude_summarize, text, "")
                body = f"<b>📢 {name}</b>\n\n{summary}"
            except Exception as e:
                logger.error("Channel Monitor: помилка summary: %s", e)
                body = f"<b>📢 {name}</b>\n\n{text[:1000]}..."
        else:
            body = f"<b>📢 {name}</b>\n\n{text}"

        await self.client.send_message("me", body, parse_mode="html")
        logger.info("Channel Monitor: переслано пост з «%s»", name)

    async def _process_comment(self, event, cfg: dict):
        text = event.message.text or event.message.message or ""
        if not text:
            return

        name = cfg.get("name", cfg.get("username", "Канал"))
        min_length = cfg.get("min_length", 30)
        keywords = [kw.lower() for kw in cfg.get("keywords", [])]

        if len(text) < min_length:
            return
        if keywords and not any(kw in text.lower() for kw in keywords):
            return

        sender = await event.get_sender()
        sender_name = getattr(sender, "first_name", "") or getattr(sender, "title", "Анонім")

        logger.info("Channel Monitor: коментар у «%s» від %s", name, sender_name)

        body = f"<b>💬 Коментар у «{name}»</b>\n<i>{sender_name}:</i>\n\n{text[:800]}"
        await self.client.send_message("me", body, parse_mode="html")
