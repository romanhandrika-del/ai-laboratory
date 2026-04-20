"""
Website Fix Agent — manual entry point.

    python agents/website_fix/run.py https://etalhome.com/
"""

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from core.logger import get_logger
from agents.website_fix.website_fix_agent import WebsiteFixAgent

logger = get_logger(__name__)


async def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://etalhome.com/"
    agent = WebsiteFixAgent(client_id="default")
    result = agent.fix(url) if not asyncio.iscoroutinefunction(agent.fix) else await agent.fix(url)

    if result.get("error"):
        logger.error("Помилка: %s", result["error"])
        return

    print(f"\n✅ Фіксів згенеровано: {result['fix_count']}")
    print(f"📄 Файл: {result['fix_md_path']}")
    print(f"\n{result['fix_md']}")


if __name__ == "__main__":
    asyncio.run(main())
