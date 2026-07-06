import asyncio
from datetime import datetime
import sys
from pathlib import Path

import qrcode
from dotenv import load_dotenv
from telethon.errors import SessionPasswordNeededError

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from agents.sales_telegram.common import DATA_DIR, make_client  # noqa: E402


async def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    client = make_client()
    await client.connect()
    try:
        if await client.is_user_authorized():
            me = await client.get_me()
            print(f"AUTHORIZED {me.id} {me.first_name or ''} {me.last_name or ''}".strip(), flush=True)
            return

        while True:
            qr_login = await client.qr_login()
            image = qrcode.make(qr_login.url)
            qr_path = DATA_DIR / f"telegram_login_qr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            image.save(qr_path)
            print(f"QR_READY {qr_path}", flush=True)
            print("SCAN: Telegram -> Settings -> Devices -> Link Desktop Device", flush=True)
            try:
                await qr_login.wait(timeout=60)
                me = await client.get_me()
                print(f"AUTHORIZED {me.id} {me.first_name or ''} {me.last_name or ''}".strip(), flush=True)
                return
            except TimeoutError:
                print("QR_EXPIRED refreshing", flush=True)
            except SessionPasswordNeededError:
                print("PASSWORD_NEEDED enter 2FA password in Telegram/terminal flow", flush=True)
                raise
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
