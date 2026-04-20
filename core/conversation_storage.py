"""
Conversation Storage — зберігає всі діалоги Sales Agent у SQLite.
Дозволяє аналізувати якість відповідей через /review.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

_DB_PATH = Path(__file__).parent.parent / "data" / "conversations.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   TEXT    NOT NULL,
    chat_id     INTEGER NOT NULL,
    user_msg    TEXT    NOT NULL,
    bot_reply   TEXT    NOT NULL,
    confidence  REAL    NOT NULL DEFAULT 0.9,
    needs_human INTEGER NOT NULL DEFAULT 0,
    model_used  TEXT,
    cost_usd    REAL    DEFAULT 0,
    created_at  TEXT    NOT NULL
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_conv_client_created
ON conversations(client_id, created_at DESC);
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_INDEX)
    logger.info("Conversations DB ініціалізована: %s", _DB_PATH)


def save_conversation(
    client_id: str,
    chat_id: int,
    user_msg: str,
    bot_reply: str,
    confidence: float,
    needs_human: bool,
    model_used: str = "",
    cost_usd: float = 0.0,
) -> None:
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO conversations
               (client_id, chat_id, user_msg, bot_reply, confidence, needs_human, model_used, cost_usd, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (client_id, chat_id, user_msg, bot_reply, confidence,
             1 if needs_human else 0, model_used, cost_usd,
             datetime.now().isoformat()),
        )


def get_review(client_id: str, limit: int = 10, only_low: bool = False) -> list[dict]:
    """
    Повертає останні розмови для /review.
    only_low=True — тільки з confidence < 0.75 або needs_human=1.
    """
    query = """
        SELECT id, chat_id, user_msg, bot_reply, confidence, needs_human, model_used, cost_usd, created_at
        FROM conversations
        WHERE client_id = ?
    """
    params: list = [client_id]
    if only_low:
        query += " AND (confidence < 0.75 OR needs_human = 1)"
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with _get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_stats(client_id: str) -> dict:
    """Загальна статистика для /review."""
    with _get_conn() as conn:
        row = conn.execute(
            """SELECT
                COUNT(*) as total,
                ROUND(AVG(confidence), 2) as avg_confidence,
                SUM(needs_human) as escalations,
                ROUND(SUM(cost_usd), 4) as total_cost
               FROM conversations WHERE client_id = ?""",
            (client_id,),
        ).fetchone()
    return dict(row) if row else {}
