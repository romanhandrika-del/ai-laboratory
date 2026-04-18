"""
Web Parser Agent — точка входу для самостійного запуску.

    python agents/web_parser/run.py

Читає .env, ініціалізує БД, сканує всі сайти з config/sites.yaml.
"""

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from core.snapshot_storage import init_db
from core.logger import get_logger
from agents.web_parser.web_parser_agent import WebParserAgent

logger = get_logger(__name__)


async def main() -> None:
    """Запускає Web Parser Agent одноразово."""
    init_db()
    agent = WebParserAgent(client_id="etalhome")
    changed = await agent.scan_all()
    logger.info("Готово. Змін на %d сайтах.", changed)


if __name__ == "__main__":
    asyncio.run(main())
