"""
Telegram Monitor — точка входу.

    python agents/telegram_monitor/run.py

Перший запуск: попросить номер телефону і код з Telegram.
Сесія зберігається в data/tg_session.session — наступні запуски без логіну.
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
from agents.telegram_monitor.telegram_monitor_agent import TelegramMonitorAgent

logger = get_logger(__name__)


async def main():
    agent = TelegramMonitorAgent()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
