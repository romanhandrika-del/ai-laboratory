"""
Website Fix Agent — Agent #4 платформи AI Laboratory.

Отримує URL → scrape → seo facts → генерує пакет P1-фіксів через Claude.
Формат фіксів: File / Selector / Search/Old / Replace/New / Why
Сумісний з GitHub PR flow (Фаза 2).
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from core.logger import get_logger
from core.audit_storage import init_db, save_fix, get_last_audit, get_last_fix, update_fix_status
from agents.website_audit import scraper, seo_extractor, technical_checker
from agents.website_fix import fix_generator
from agents.website_fix import ftp_patcher

logger = get_logger(__name__)

_FIXES_DIR = Path(__file__).parent.parent.parent / "data" / "fixes"


class WebsiteFixAgent:
    """Website Fix Agent — генерує copy-paste пакет SEO-фіксів."""

    agent_id = "website-fix-v1"

    def __init__(self, client_id: str = "default"):
        self.client_id = client_id
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("MANAGER_TELEGRAM_ID", "")
        init_db()

    async def fix(self, url: str) -> dict:
        """
        Генерує fix-пакет для сайту.

        Returns dict:
            fix_count, summary_text, fix_md_path, fix_md, fix_id, error (якщо є)
        """
        logger.info("WebsiteFixAgent: починаю генерацію фіксів для %s", url)

        # 1. Scrape
        try:
            html, _ = await scraper.fetch_page(url)
        except RuntimeError as e:
            logger.error("WebsiteFixAgent: не вдалось завантажити %s: %s", url, e)
            return {"error": str(e), "summary_text": f"❌ Не вдалось завантажити сайт: {e}"}

        # 2. SEO facts + технічний стан (паралельно)
        seo_task = asyncio.to_thread(seo_extractor.extract, html, url)
        tech_task = asyncio.to_thread(technical_checker.check, url)
        seo_data, technical_data = await asyncio.gather(seo_task, tech_task)

        facts = {"seo": seo_data, "technical": technical_data}

        # 3. Score попереднього аудиту + список вже застосованих фіксів
        last_audit = get_last_audit(self.client_id, url)
        score_before = last_audit["score"] if last_audit else None
        already_applied = _get_applied_fixes(self.client_id, url)

        # 4. Генерація фіксів через Claude
        fix_md, fix_count = fix_generator.generate(
            facts, url, html_sample=html, already_applied=already_applied
        )

        # 5. Зберігаємо файл
        fix_path = _save_fix_file(self.client_id, url, fix_md)

        # 6. Зберігаємо в БД
        fix_id = save_fix(self.client_id, url, fix_count, str(fix_path), score_before)

        # 7. Summary для Telegram
        summary_text = fix_generator.format_telegram_summary(url, fix_count)

        logger.info("WebsiteFixAgent: готово. fix_count=%d, fix_id=%d, path=%s", fix_count, fix_id, fix_path)

        return {
            "fix_count": fix_count,
            "fix_id": fix_id,
            "summary_text": summary_text,
            "fix_md_path": str(fix_path),
            "fix_md": fix_md,
        }


    async def push(self, url: str) -> dict:
        """
        Фаза 2: читає останній fix-пакет і заливає PHP mu-plugin на сервер через FTP.

        Returns dict:
            ftp_path, fix_count, summary_text, error (якщо є)
        """
        last_fix = get_last_fix(self.client_id, url)
        if not last_fix:
            return {"error": f"Спочатку запусти /fix {url} — пакет фіксів не знайдено"}

        fix_path = last_fix.get("fix_path")
        if not fix_path or not Path(fix_path).exists():
            return {"error": "Файл fix-пакету не знайдено на диску"}

        fix_md = Path(fix_path).read_text(encoding="utf-8")
        result = ftp_patcher.apply_fixes(fix_md, url, client_id=self.client_id)

        if result.get("error"):
            return {"error": result["error"], "summary_text": f"❌ FTP помилка: {result['error']}"}

        update_fix_status(
            last_fix["id"],
            "pushed",
            pr_url=result["ftp_path"],
            backup_path=result.get("backup_path"),
        )

        backup_note = (
            f"\n💾 Backup: <code>{result['backup_path']}</code>"
            if result.get("backup_path") else "\n⚠️ Backup не створено (файл був відсутній)"
        )
        summary = (
            f"🚀 <b>Push успішний!</b>\n"
            f"📁 Завантажено: <code>{result['ftp_path']}</code>\n"
            f"✅ Фіксів у плагіні: {result['fix_count']}"
            f"{backup_note}\n\n"
            f"<i>WordPress завантажить mu-plugin автоматично. "
            f"Перевір сайт і запусти /audit щоб побачити новий score.</i>"
        )
        logger.info("Push завершено: %s → %s", url, result["ftp_path"])
        return {**result, "summary_text": summary}

    async def rollback(self, url: str) -> dict:
        """
        Відновлює попередню версію mu-plugin з backup.

        Returns dict:
            ftp_path, summary_text, error (якщо є)
        """
        last_fix = get_last_fix(self.client_id, url)
        if not last_fix:
            return {"error": f"Немає жодного push для {url}"}

        backup_path = last_fix.get("backup_path")
        if not backup_path:
            return {"error": "Backup відсутній — можливо push був першим і оригіналу не було"}

        try:
            ftp_path = ftp_patcher.rollback_mu_plugin(backup_path)
        except FileNotFoundError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("Rollback помилка: %s", e)
            return {"error": str(e)}

        update_fix_status(last_fix["id"], "rolled_back")

        summary = (
            f"↩️ <b>Rollback виконано!</b>\n"
            f"📁 Відновлено: <code>{ftp_path}</code>\n"
            f"💾 З backup: <code>{backup_path}</code>\n\n"
            f"<i>Попередня версія плагіну активна. Перевір сайт.</i>"
        )
        logger.info("Rollback завершено: %s → backup=%s", url, backup_path)
        return {"ftp_path": ftp_path, "summary_text": summary}


def _get_applied_fixes(client_id: str, url: str) -> list[str]:
    """Читає всі pushed/verified фікси з БД і витягує їх назви для контексту Claude."""
    from core.audit_storage import _get_conn
    from agents.website_fix.ftp_patcher import parse_fixes
    titles = []
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT fix_path FROM fix_history WHERE client_id=? AND url=? AND status IN ('pushed','verified') ORDER BY generated_at",
            (client_id, url),
        ).fetchall()
    for row in rows:
        fix_path = row["fix_path"]
        if fix_path and Path(fix_path).exists():
            try:
                md = Path(fix_path).read_text(encoding="utf-8")
                for fix in parse_fixes(md):
                    if fix.get("title"):
                        titles.append(fix["title"])
            except Exception:
                pass
    return titles


def _save_fix_file(client_id: str, url: str, fix_md: str) -> Path:
    domain = urlparse(url).netloc.replace("www.", "")
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    fix_dir = _FIXES_DIR / client_id
    fix_dir.mkdir(parents=True, exist_ok=True)
    path = fix_dir / f"{domain}-fix-{ts}.md"
    path.write_text(fix_md, encoding="utf-8")
    logger.info("Fix-пакет збережено: %s", path)
    return path
