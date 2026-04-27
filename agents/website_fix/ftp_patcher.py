"""
FTP Patcher — Фаза 2 Website Fix Agent.

Генерує WordPress mu-plugin з SEO-фіксами і заливає на Hostinger через FTP.
mu-plugins: /wp-content/mu-plugins/ — автозавантаження WordPress без активації.
"""

import ftplib
import io
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from core.logger import get_logger

logger = get_logger(__name__)

_MU_PLUGIN_PATH = "/domains/etalhome.com/public_html/wp-content/mu-plugins/"
_PLUGIN_FILENAME = "etalhome-seo-fixes.php"
_BACKUPS_DIR = Path(__file__).parent.parent.parent / "data" / "backups"


def _get_ftp() -> ftplib.FTP:
    ftp = ftplib.FTP()
    ftp.connect(
        os.getenv("FTP_HOST", ""),
        int(os.getenv("FTP_PORT", "21")),
        timeout=30,
    )
    ftp.login(os.getenv("FTP_USER", ""), os.getenv("FTP_PASS", ""))
    ftp.set_pasv(True)
    return ftp


def parse_fixes(fix_md: str) -> list[dict]:
    """
    Парсить fix-пакет у список dict:
      {title, file, selector, search_old, replace_new, why}
    """
    blocks = re.split(r"^## Fix #\d+", fix_md, flags=re.MULTILINE)
    fixes = []
    for block in blocks:
        if not block.strip():
            continue
        fix = {}
        for field, key in [
            (r"\*\*File:\*\*\s*`?(.+?)`?\s*$", "file"),
            (r"\*\*Selector:\*\*\s*`?(.+?)`?\s*$", "selector"),
            (r"\*\*Search/Old:\*\*\s*(.+?)(?=\n\*\*)", "search_old"),
            (r"\*\*Why:\*\*\s*(.+?)$", "why"),
        ]:
            m = re.search(field, block, re.MULTILINE)
            fix[key] = m.group(1).strip() if m else ""

        # Витягуємо код з ```html або ```json блоку
        code_m = re.search(r"```(?:html|json|php)?\n([\s\S]+?)```", block)
        fix["replace_new"] = code_m.group(1).strip() if code_m else ""

        # Title з першого рядка
        title_m = re.search(r"—\s*\[P\d\]\s*(.+)", block.splitlines()[0] if block.strip() else "")
        fix["title"] = title_m.group(1).strip() if title_m else "SEO Fix"

        if fix.get("replace_new"):
            fixes.append(fix)
    return fixes


def build_mu_plugin(fixes: list[dict], url: str) -> str:
    """Генерує PHP mu-plugin з фіксами через wp_head (head-теги) та wp_footer (body-теги)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    head_fixes: list[tuple[str, str]] = []
    footer_fixes: list[tuple[str, str]] = []

    for fix in fixes:
        raw_code = fix["replace_new"]
        title = fix["title"]
        # Видаляємо HTML-коментарі (developer notes), залишаємо тільки код
        code = re.sub(r"<!--.*?-->", "", raw_code, flags=re.DOTALL).strip()
        if not code:
            continue
        # Валідація JSON-LD: якщо є <script type="application/ld+json"> — перевіряємо json.loads()
        if "application/ld+json" in code:
            json_m = re.search(r"<script[^>]*application/ld\+json[^>]*>([\s\S]*?)</script>", code)
            if json_m:
                try:
                    json.loads(json_m.group(1).strip())
                except json.JSONDecodeError as e:
                    logger.error("JSON-LD validation failed у фіксі '%s': %s — пропускаємо", title, e)
                    continue
        if any(tag in code for tag in ("<link", "<meta", "<script", "<title")):
            head_fixes.append((title, code))
        else:
            footer_fixes.append((title, code))

    def _nowdoc_block(fixes_list: list[tuple[str, str]], prefix: str) -> str:
        parts = []
        for i, (title, code) in enumerate(fixes_list):
            marker = f"{prefix}_{i}"
            # Захист від Nowdoc-конфлікту: якщо код містить рядок закриття — пропускаємо
            if f"\n{marker};" in code or code.startswith(f"{marker};"):
                logger.error("Nowdoc marker conflict у фіксі '%s' (marker=%s) — пропускаємо", title, marker)
                continue
            parts.append(f"  // {title}\n  echo <<<'{marker}'\n{code}\n{marker};\n")
        return "\n".join(parts)

    head_block = _nowdoc_block(head_fixes, "H")
    footer_section = ""
    if footer_fixes:
        footer_block = _nowdoc_block(footer_fixes, "F")
        footer_section = f"""
add_action('wp_footer', 'etalhome_seo_footer_fixes', 99);
function etalhome_seo_footer_fixes() {{
{footer_block}
}}"""

    plugin = f"""\
<?php
/**
 * Plugin Name: Etalhome SEO Fixes
 * Description: Auto-generated SEO fixes by AI Laboratory Fix Agent
 * Version: {now}
 * URL: {url}
 */

if (!defined('ABSPATH')) exit;

add_action('wp_head', 'etalhome_seo_head_fixes', 1);
function etalhome_seo_head_fixes() {{
{head_block}
}}{footer_section}
"""
    return plugin


def _download_backup(ftp: ftplib.FTP, client_id: str, url: str) -> str | None:
    """Завантажує поточний плагін з FTP і зберігає як backup. Повертає локальний шлях або None."""
    domain = urlparse(url).netloc.replace("www.", "")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = _BACKUPS_DIR / client_id / domain / ts
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / _PLUGIN_FILENAME
    buf = io.BytesIO()
    try:
        ftp.retrbinary(f"RETR {_PLUGIN_FILENAME}", buf.write)
        backup_path.write_bytes(buf.getvalue())
        logger.info("FTP: backup збережено → %s (%d bytes)", backup_path, len(buf.getvalue()))
        return str(backup_path)
    except ftplib.error_perm:
        logger.info("FTP: файл %s ще не існує на сервері, backup пропущено", _PLUGIN_FILENAME)
        return None


def upload_mu_plugin(php_content: str, url: str = "", client_id: str = "default") -> tuple[str, str | None]:
    """Завантажує PHP-файл у mu-plugins. Перед STOR робить backup існуючого.

    Returns:
        (ftp_path, backup_path | None)
    """
    ftp = _get_ftp()
    try:
        ftp.cwd(_MU_PLUGIN_PATH)
        backup_path = _download_backup(ftp, client_id, url)
        content_bytes = php_content.encode("utf-8")
        ftp.storbinary(f"STOR {_PLUGIN_FILENAME}", io.BytesIO(content_bytes))
        full_path = _MU_PLUGIN_PATH + _PLUGIN_FILENAME
        logger.info("FTP: завантажено %s (%d bytes)", full_path, len(content_bytes))
        return full_path, backup_path
    finally:
        ftp.quit()


def rollback_mu_plugin(backup_path: str) -> str:
    """Відновлює mu-plugin з локального backup на FTP. Повертає FTP-шлях."""
    backup_file = Path(backup_path)
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup не знайдено: {backup_path}")
    ftp = _get_ftp()
    try:
        ftp.cwd(_MU_PLUGIN_PATH)
        content_bytes = backup_file.read_bytes()
        ftp.storbinary(f"STOR {_PLUGIN_FILENAME}", io.BytesIO(content_bytes))
        full_path = _MU_PLUGIN_PATH + _PLUGIN_FILENAME
        logger.info("FTP: rollback виконано → %s (%d bytes)", full_path, len(content_bytes))
        return full_path
    finally:
        ftp.quit()


def apply_fixes(fix_md: str, url: str, client_id: str = "default") -> dict:
    """
    Головна функція: парсить fix-md → генерує PHP → backup → заливає на сервер.

    Returns:
        {"ftp_path": str, "backup_path": str|None, "fix_count": int, "php_content": str, "error": str|None}
    """
    try:
        fixes = parse_fixes(fix_md)
        if not fixes:
            return {"error": "Не знайдено жодного фіксу в пакеті", "ftp_path": None}

        php_content = build_mu_plugin(fixes, url)
        ftp_path, backup_path = upload_mu_plugin(php_content, url=url, client_id=client_id)

        return {
            "ftp_path": ftp_path,
            "backup_path": backup_path,
            "fix_count": len(fixes),
            "php_content": php_content,
            "error": None,
        }
    except Exception as e:
        logger.error("FTP Patcher помилка: %s", e)
        return {"error": str(e), "ftp_path": None}
