"""
Telegram Channel Monitor — точка входу.

    python agents/telegram_monitor/run_channels.py

Канали налаштовуються у config/tg_channels.yaml
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
from agents.telegram_monitor.channel_monitor_agent import ChannelMonitorAgent

logger = get_logger(__name__)


async def main():
    agent = ChannelMonitorAgent()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
