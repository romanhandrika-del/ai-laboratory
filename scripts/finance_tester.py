"""
Finance Module Tester — надсилає тестові питання боту і збирає відповіді.

Використовує існуючу Telethon-сесію (data/tg_session.session).
Результат зберігається у data/finance_test_result.txt

Запуск:
    python scripts/finance_tester.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

import os
from telethon import TelegramClient, events

_SESSION_PATH = str(_ROOT / "data" / "tg_session")
_OUTPUT_PATH = _ROOT / "data" / "finance_test_result.txt"

BOT_USERNAME = "@Assistant_Multiple_bot"

QUESTIONS = [
    "скільки замовлень у січні 2026?",
    "витрати на скло за квітень",
    "зарплата Влада за квітень",
    "зарплата Олександра",
    "зарплата за 2025",
    "хто заплатив повну вартість в березні?",
    "чистий прибуток за квітень",
    "звіт за квітень",
    "/refresh_finance",
]

WAIT_SECONDS = 60  # час очікування відповіді на кожне питання


async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")

    if not api_id or not api_hash:
        print("❌ TELEGRAM_API_ID / TELEGRAM_API_HASH не знайдено в .env")
        return

    client = TelegramClient(_SESSION_PATH, api_id, api_hash)
    await client.start()

    me = await client.get_me()
    print(f"✅ Підключено як {me.first_name} (@{me.username})")
    print(f"🤖 Тестуємо бота: {BOT_USERNAME}\n")

    results = []

    for i, question in enumerate(QUESTIONS, 1):
        print(f"[{i}/{len(QUESTIONS)}] Питання: {question}")

        last_response = None

        async def response_handler(event):
            nonlocal last_response
            if event.is_private:
                sender = await event.get_sender()
                if hasattr(sender, 'username') and sender.username and \
                   sender.username.lower() == BOT_USERNAME.lstrip("@").lower():
                    last_response = event.text or event.message.message or ""

        client.add_event_handler(response_handler, events.NewMessage(incoming=True))

        await client.send_message(BOT_USERNAME, question)

        await asyncio.sleep(WAIT_SECONDS)

        client.remove_event_handler(response_handler)

        answer = last_response or "(відповіді не отримано)"
        print(f"   Відповідь: {answer[:120]}{'...' if len(answer) > 120 else ''}\n")

        results.append({
            "question": question,
            "answer": answer,
        })

    # Записуємо результат
    with open(_OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(f"# Finance Module Test — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Бот: {BOT_USERNAME}\n\n")
        for i, r in enumerate(results, 1):
            f.write(f"## Q{i}: {r['question']}\n")
            f.write(f"{r['answer']}\n\n")
            f.write("---\n\n")

    print(f"✅ Результат збережено: {_OUTPUT_PATH}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
