import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from agents.sales_telegram.common import DATA_DIR  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Login to Telegram with phone code and save a separate session.")
    parser.add_argument("--session-name", required=True, help="Session file name without .session, e.g. sales_tg_ursu")
    args = parser.parse_args()

    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        raise RuntimeError("TELEGRAM_API_ID / TELEGRAM_API_HASH не знайдено в env")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    session_path = str(DATA_DIR / args.session_name)
    client = TelegramClient(session_path, api_id, api_hash)
    await client.start()
    try:
        me = await client.get_me()
        print(f"AUTHORIZED {me.id} {me.first_name or ''} {me.last_name or ''}".strip(), flush=True)
        print(f"SESSION {session_path}.session", flush=True)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
