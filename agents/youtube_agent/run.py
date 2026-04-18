"""
YouTube Agent — точка входу для самостійного запуску.

    python agents/youtube_agent/run.py

Читає .env, ініціалізує БД, сканує канали з config/channels.yaml.
"""

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from core.youtube_storage import init_db
from core.logger import get_logger
from agents.youtube_agent.youtube_agent import YouTubeAgent

logger = get_logger(__name__)


async def main() -> None:
    """Запускає YouTube Agent одноразово."""
    init_db()
    agent = YouTubeAgent(client_id="etalhome")
    processed = await agent.scan_all()
    logger.info("Готово. Оброблено %d нових відео.", processed)


if __name__ == "__main__":
    asyncio.run(main())
