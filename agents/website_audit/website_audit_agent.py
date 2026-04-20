"""
Website Audit Agent — Agent #3 платформи AI Laboratory.

Аналізує сайт за чотирма категоріями:
  1. SEO on-page (title, meta, headings, canonical, OG, JSON-LD)
  2. Google visibility (PageSpeed Insights: LCP, CLS, FCP, scores)
  3. Конверсія/UX (CTA, форми, контакти — через Claude аналіз)
  4. Технічний аудит (HTTPS, robots.txt, sitemap, статус)

Два режими запуску:
  - On-demand: bot.py /audit <url>
  - Scheduled: run.py + config/audit_targets.yaml
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from core.logger import get_logger
from core.audit_storage import init_db, save_audit
from agents.website_audit import scraper, seo_extractor, pagespeed_client, technical_checker, report_generator

logger = get_logger(__name__)

_AUDITS_DIR = Path(__file__).parent.parent.parent / "data" / "audits"


class WebsiteAuditAgent:
    """Website Audit Agent — Agent #3 платформи AI Laboratory."""

    agent_id = "website-audit-v1"

    def __init__(self, client_id: str = "default"):
        self.client_id = client_id
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("MANAGER_TELEGRAM_ID", "")
        init_db()

    async def audit(self, url: str) -> dict:
        """
        Виконує повний аудит сайту.

        Returns dict:
            score, summary_text, report_md_path, report_md, error (якщо є)
        """
        logger.info("WebsiteAuditAgent: починаю аудит %s", url)

        # 1. Завантажуємо HTML
        try:
            html, load_time = await scraper.fetch_page(url)
        except RuntimeError as e:
            logger.error("WebsiteAuditAgent: не вдалось завантажити %s: %s", url, e)
            return {"score": 0, "error": str(e), "report_md_path": None, "summary_text": f"❌ Не вдалось завантажити сайт: {e}"}

        # 2. Паралельно збираємо всі факти
        seo_task = asyncio.to_thread(seo_extractor.extract, html, url)
        tech_task = asyncio.to_thread(technical_checker.check, url)
        ps_task = asyncio.to_thread(pagespeed_client.fetch, url)

        seo_data, technical_data, pagespeed_data = await asyncio.gather(
            seo_task, tech_task, ps_task
        )

        # Додаємо load_time в технічні дані
        if technical_data.get("response_time_ms") is None:
            technical_data["playwright_load_time_ms"] = round(load_time * 1000)

        facts = {
            "seo": seo_data,
            "technical": technical_data,
            "pagespeed": pagespeed_data,
        }

        # 3. Генеруємо Claude-звіт
        report_md, score = report_generator.generate(facts, url)

        # 4. Зберігаємо звіт у файл
        report_path = _save_report(self.client_id, url, report_md)

        # 5. Зберігаємо в БД
        save_audit(self.client_id, url, score, str(report_path))

        # 6. Формуємо Telegram summary
        summary_text = report_generator.format_telegram_summary(url, score, report_md)

        logger.info("WebsiteAuditAgent: аудит завершено. score=%d, звіт=%s", score, report_path)

        return {
            "score": score,
            "summary_text": summary_text,
            "report_md_path": str(report_path),
            "report_md": report_md,
        }

    async def audit_all(self, targets: list[dict]) -> int:
        """Сканує всі цілі зі scheduled config. Повертає кількість успішних аудитів."""
        success = 0
        for target in targets:
            url = target.get("url", "").strip()
            name = target.get("name", url)
            client_id = target.get("client_id", self.client_id)

            if not url:
                continue

            self.client_id = client_id
            result = await self.audit(url)

            if result.get("error"):
                logger.error("WebsiteAuditAgent: помилка для %s: %s", name, result["error"])
                await self._notify(result["summary_text"])
                continue

            await self._notify(result["summary_text"], result.get("report_md_path"))
            success += 1

        return success

    async def _notify(self, text: str, report_path: str | None = None) -> None:
        """Надсилає Telegram повідомлення + опціонально .md файл."""
        if not self.bot_token or not self.chat_id:
            logger.warning("WebsiteAuditAgent: TELEGRAM_BOT_TOKEN або MANAGER_TELEGRAM_ID не задано")
            return
        from telegram import Bot
        bot = Bot(token=self.bot_token)
        await bot.send_message(chat_id=self.chat_id, text=text, parse_mode="HTML")
        if report_path and Path(report_path).exists():
            with open(report_path, "rb") as f:
                await bot.send_document(
                    chat_id=self.chat_id,
                    document=f,
                    filename=Path(report_path).name,
                )


def _save_report(client_id: str, url: str, report_md: str) -> Path:
    """Зберігає Markdown-звіт у data/audits/{client_id}/{domain}-{ts}.md"""
    domain = urlparse(url).netloc.replace("www.", "")
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    report_dir = _AUDITS_DIR / client_id
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{domain}-{ts}.md"
    path.write_text(report_md, encoding="utf-8")
    logger.info("Звіт збережено: %s", path)
    return path
