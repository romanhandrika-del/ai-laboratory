"""
Одноразовий скрипт: переносить дані зі старої таблиці conversations → dialogs (JSONB).

Запускати один раз після деплою core/db.py:
    DATABASE_URL=<neon-pooler-url> python scripts/migrate_conversations_to_dialogs.py
"""

import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import timezone

import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL не задано")
    sys.exit(1)


async def main() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )

    # Перевіряємо чи існує стара таблиця
    exists = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'conversations')"
    )
    if not exists:
        print("Таблиця conversations не знайдена — нічого переносити.")
        await conn.close()
        return

    rows = await conn.fetch(
        "SELECT client_id, chat_id, user_msg, bot_reply, confidence, needs_human, "
        "model_used, cost_usd, created_at FROM conversations ORDER BY created_at ASC"
    )
    print(f"Знайдено {len(rows)} рядків у conversations")

    # Групуємо по (client_id, user_id, source)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (r["client_id"], str(r["chat_id"]), "telegram")
        ts = str(r["created_at"])
        groups[key].append({"role": "user", "content": r["user_msg"], "ts": ts, "meta": {}})
        groups[key].append({
            "role": "assistant",
            "content": r["bot_reply"],
            "ts": ts,
            "meta": {
                "confidence": float(r["confidence"] or 0.9),
                "needs_human": bool(r["needs_human"]),
                "model_used": r["model_used"] or "",
                "cost_usd": float(r["cost_usd"] or 0.0),
            },
        })

    # Переносимо у dialogs
    inserted = 0
    async with conn.transaction():
        for (client_id, user_id, source), messages in groups.items():
            if len(messages) > 50:
                messages = messages[-50:]
            await conn.execute(
                """INSERT INTO dialogs (client_id, user_id, source, messages)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (client_id, user_id, source) DO UPDATE SET
                       messages = EXCLUDED.messages,
                       updated_at = NOW()""",
                client_id, user_id, source, messages,
            )
            inserted += 1

    print(f"Перенесено {inserted} діалогів у таблицю dialogs")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
