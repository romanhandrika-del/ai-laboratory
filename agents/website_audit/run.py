"""
Website Audit Agent — scheduled entry point.

    python agents/website_audit/run.py

Читає .env, завантажує config/audit_targets.yaml, аудитує всі цілі.
"""

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

import yaml
from core.logger import get_logger
from agents.website_audit.website_audit_agent import WebsiteAuditAgent

logger = get_logger(__name__)

_CONFIG_PATH = _ROOT / "config" / "audit_targets.yaml"


async def main() -> None:
    if not _CONFIG_PATH.exists():
        logger.error("Конфіг не знайдено: %s", _CONFIG_PATH)
        return

    with open(_CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    targets = data.get("targets", [])
    if not targets:
        logger.warning("Список цілей порожній у %s", _CONFIG_PATH)
        return

    logger.info("Website Audit Agent: %d цілей для аудиту", len(targets))
    agent = WebsiteAuditAgent()
    success = await agent.audit_all(targets)
    logger.info("Готово. Успішно: %d/%d", success, len(targets))


if __name__ == "__main__":
    asyncio.run(main())
