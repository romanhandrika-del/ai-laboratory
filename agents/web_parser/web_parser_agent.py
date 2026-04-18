"""
Web Parser Agent — моніторить сайти та сповіщає про зміни.

Не extends BaseAgent (не conversational — це scheduled scraper).
Читає сайти з config/sites.yaml, секрети з .env.

Цикл для кожного сайту:
  1. fetch_page()    → HTML
  2. parse_items()   → список елементів
  3. detect_changes()→ diff
  4. якщо зміни → відправити Telegram + зберегти знімок
"""

import os
from pathlib import Path

import yaml

from agents.web_parser.scraper import fetch_page
from agents.web_parser.parser import parse_items
from agents.web_parser.detector import detect_changes, has_changes
from core.snapshot_storage import get_last_snapshot, save_snapshot
from core.logger import get_logger

logger = get_logger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "sites.yaml"


class WebParserAgent:
    """Universal Web Parser Agent — Agent #2 платформи AI Laboratory."""

    agent_id = "web-parser-v1"

    def __init__(self, client_id: str = "default"):
        self.client_id = client_id
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("MANAGER_TELEGRAM_ID", "")

    def _load_sites(self) -> list[dict]:
        """Завантажує список сайтів з config/sites.yaml."""
        if not _CONFIG_PATH.exists():
            logger.warning("WebParser: config/sites.yaml не знайдено")
            return []
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        sites = data.get("websites", [])
        logger.info("WebParser: завантажено %d сайтів", len(sites))
        return sites

    async def scan_all(self) -> int:
        """
        Сканує всі сайти з конфігу.

        Returns:
            Кількість сайтів з виявленими змінами
        """
        sites = self._load_sites()
        if not sites:
            return 0

        changed_count = 0
        for site in sites:
            url = site.get("url", "").strip()
            name = site.get("name", url)
            selectors = site.get("selectors", {})
            key_field = site.get("key_field", "title")

            if not url or not selectors:
                logger.warning("WebParser: пропускаємо сайт без url/selectors: %s", name)
                continue

            try:
                had_changes = await self._scan_site(url, name, selectors, key_field)
                if had_changes:
                    changed_count += 1
            except Exception as e:
                logger.error("WebParser: помилка при скануванні %s: %s", name, e)
                continue

        logger.info("WebParser: завершено. Змін на %d із %d сайтів", changed_count, len(sites))
        return changed_count

    async def _scan_site(
        self,
        url: str,
        name: str,
        selectors: dict,
        key_field: str,
    ) -> bool:
        """
        Сканує один сайт і відправляє Telegram якщо є зміни.

        Returns:
            True якщо виявлено зміни
        """
        logger.info("WebParser: сканую %s", name)

        html = await fetch_page(url)
        current_items = parse_items(html, selectors)
        logger.info("WebParser: розпарсено %d елементів з %s", len(current_items), name)

        previous_items = get_last_snapshot(self.client_id, url)
        is_first_run = previous_items is None

        diff = detect_changes(current_items, previous_items or [], key_field=key_field)

        if is_first_run:
            # Зберігаємо базовий знімок без нотифікації — це еталон для порівняння
            save_snapshot(self.client_id, url, current_items)
            logger.info("WebParser: базовий знімок збережено для %s (%d елементів)", name, len(current_items))
            return False

        if has_changes(diff):
            await self._notify(name, url, diff)
            save_snapshot(self.client_id, url, current_items)
            return True

        return False

    async def _notify(self, name: str, url: str, diff: dict) -> None:
        """Відправляє Telegram повідомлення про зміни."""
        if not self.bot_token or not self.chat_id:
            logger.warning("WebParser: TELEGRAM_BOT_TOKEN або MANAGER_TELEGRAM_ID не задано")
            return

        from telegram import Bot
        message = _format_message(name, url, diff)
        bot = Bot(token=self.bot_token)
        await bot.send_message(
            chat_id=self.chat_id,
            text=message,
            parse_mode="HTML",
        )
        logger.info("WebParser: Telegram повідомлення надіслано для %s", name)


def _format_message(name: str, url: str, diff: dict) -> str:
    """Формує HTML-повідомлення про зміни для Telegram."""
    lines = [f'🔔 Зміни на <a href="{url}">{name}</a>\n']

    for item in diff["new"]:
        title = item.get("title", "—")
        desc = item.get("description", "")
        lines.append(f"✅ <b>Новий:</b> «{title}»")
        if desc:
            lines.append(f"   📄 {desc}")
        lines.append("")

    for entry in diff["changed"]:
        old, new = entry["old"], entry["new"]
        title = new.get("title", "—")
        lines.append(f"📝 <b>Зміна:</b> «{title}»")
        if old.get("description") != new.get("description") and new.get("description"):
            lines.append(f"   📄 {new['description']}")
        _SKIP = {"title", "description"}
        for field in new:
            if field not in _SKIP and old.get(field) != new.get(field):
                lines.append(f"   {field.capitalize()}: {old.get(field, '')} → {new.get(field, '')}")
        lines.append("")

    for item in diff["removed"]:
        title = item.get("title", "—")
        lines.append(f"❌ <b>Видалено:</b> «{title}»")
        lines.append("")

    return "\n".join(lines).strip()
