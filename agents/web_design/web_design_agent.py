"""
Web Design Agent — Agent #5 платформи AI Laboratory.

Два режими:
  - URL: scrape → extract visual styles → генерує редизайн-бриф + HTML/CSS макет
  - Brief: текстовий опис → генерує лендінг з нуля

Виводить: brief.md + mockup.html у data/designs/{client_id}/{slug}-design-{ts}/
"""

import asyncio
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from core.logger import get_logger
from core.audit_storage import init_db, save_design
from agents.website_audit import scraper, seo_extractor
from agents.web_design import design_extractor, design_generator

logger = get_logger(__name__)

_DESIGNS_DIR = Path(__file__).parent.parent.parent / "data" / "designs"


class WebDesignAgent:
    """Web Design Agent — генерує дизайн-бриф і HTML/CSS макет."""

    agent_id = "web-design-v1"

    def __init__(self, client_id: str = "default"):
        self.client_id = client_id
        init_db()

    async def design(self, url_or_brief: str) -> dict:
        """
        Генерує дизайн-пакет (brief.md + mockup.html).

        Args:
            url_or_brief: URL сайту або текстовий бриф

        Returns dict:
            brief_path, mockup_path, dir_path, summary_text, error (якщо є)
        """
        is_url = url_or_brief.startswith(("http://", "https://"))
        mode = "url" if is_url else "brief"
        logger.info("WebDesignAgent: режим=%s, вхід=%s", mode, url_or_brief[:80])

        if is_url:
            url = url_or_brief
            try:
                html, _, visual_raw = await scraper.fetch_page_with_styles(url)
            except RuntimeError as e:
                logger.error("WebDesignAgent: не вдалось завантажити %s: %s", url, e)
                return {"error": str(e), "summary_text": f"❌ Не вдалось завантажити сайт: {e}"}

            seo_task = asyncio.to_thread(seo_extractor.extract, html, url)
            visual_task = asyncio.to_thread(design_extractor.extract, html, visual_raw)
            seo_data, visual_data = await asyncio.gather(seo_task, visual_task)

            brief_md, mockup_html = design_generator.generate_from_url(visual_data, seo_data, url)
            slug = urlparse(url).netloc.replace("www.", "")
        else:
            brief_md, mockup_html = design_generator.generate_from_brief(url_or_brief)
            slug = re.sub(r"\W+", "-", url_or_brief[:40]).strip("-").lower()

        design_dir = _save_design_files(self.client_id, slug, brief_md, mockup_html)
        save_design(self.client_id, url_or_brief, mode, str(design_dir))

        summary_text = design_generator.format_telegram_summary(url_or_brief, mode)

        logger.info("WebDesignAgent: готово. dir=%s", design_dir)
        return {
            "brief_path": str(design_dir / "brief.md"),
            "mockup_path": str(design_dir / "mockup.html"),
            "dir_path": str(design_dir),
            "summary_text": summary_text,
        }


def _save_design_files(client_id: str, slug: str, brief_md: str, mockup_html: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    design_dir = _DESIGNS_DIR / client_id / f"{slug}-design-{ts}"
    design_dir.mkdir(parents=True, exist_ok=True)

    (design_dir / "brief.md").write_text(brief_md, encoding="utf-8")
    (design_dir / "mockup.html").write_text(mockup_html, encoding="utf-8")

    logger.info("Design-пакет збережено: %s", design_dir)
    return design_dir
