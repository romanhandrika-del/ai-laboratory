"""
Conversation Storage — зберігає всі діалоги Sales Agent.
PostgreSQL якщо є DATABASE_URL, інакше SQLite.
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

_DB_PATH = Path(__file__).parent.parent / "data" / "conversations.db"
_DATABASE_URL = os.getenv("DATABASE_URL", "")
_USE_PG = bool(_DATABASE_URL)

_CREATE_TABLE_SQLITE = """
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

_CREATE_TABLE_PG = """
CREATE TABLE IF NOT EXISTS conversations (
    id          SERIAL PRIMARY KEY,
    client_id   TEXT    NOT NULL,
    chat_id     BIGINT  NOT NULL,
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


# ── PostgreSQL ────────────────────────────────────────────────────────────────

def _pg_conn():
    import psycopg2
    import psycopg2.extras
    conn = psycopg2.connect(_DATABASE_URL)
    conn.autocommit = False
    return conn


def _init_pg() -> None:
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLE_PG)
            cur.execute(_CREATE_INDEX)
        conn.commit()
    logger.info("PostgreSQL conversations таблиця готова")


def _save_pg(client_id, chat_id, user_msg, bot_reply, confidence, needs_human, model_used, cost_usd) -> None:
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO conversations
                   (client_id, chat_id, user_msg, bot_reply, confidence, needs_human, model_used, cost_usd, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (client_id, chat_id, user_msg, bot_reply, confidence,
                 1 if needs_human else 0, model_used, cost_usd,
                 datetime.now().isoformat()),
            )
        conn.commit()


def _review_pg(client_id, limit, only_low) -> list[dict]:
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            q = """SELECT id, chat_id, user_msg, bot_reply, confidence, needs_human,
                          model_used, cost_usd, created_at
                   FROM conversations WHERE client_id = %s"""
            params = [client_id]
            if only_low:
                q += " AND (confidence < 0.75 OR needs_human = 1)"
            q += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)
            cur.execute(q, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def _stats_pg(client_id) -> dict:
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) as total,
                          ROUND(AVG(confidence)::numeric, 2) as avg_confidence,
                          SUM(needs_human) as escalations,
                          ROUND(SUM(cost_usd)::numeric, 4) as total_cost
                   FROM conversations WHERE client_id = %s""",
                (client_id,),
            )
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else {}


# ── SQLite ────────────────────────────────────────────────────────────────────

def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _init_sqlite() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _sqlite_conn() as conn:
        conn.execute(_CREATE_TABLE_SQLITE)
        conn.execute(_CREATE_INDEX)
    logger.info("SQLite conversations DB: %s", _DB_PATH)


# ── Публічний API ─────────────────────────────────────────────────────────────

def init_db() -> None:
    if _USE_PG:
        _init_pg()
    else:
        _init_sqlite()


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
    if _USE_PG:
        _save_pg(client_id, chat_id, user_msg, bot_reply, confidence, needs_human, model_used, cost_usd)
    else:
        with _sqlite_conn() as conn:
            conn.execute(
                """INSERT INTO conversations
                   (client_id, chat_id, user_msg, bot_reply, confidence, needs_human, model_used, cost_usd, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (client_id, chat_id, user_msg, bot_reply, confidence,
                 1 if needs_human else 0, model_used, cost_usd,
                 datetime.now().isoformat()),
            )


def get_review(client_id: str, limit: int = 10, only_low: bool = False) -> list[dict]:
    if _USE_PG:
        return _review_pg(client_id, limit, only_low)
    query = """
        SELECT id, chat_id, user_msg, bot_reply, confidence, needs_human, model_used, cost_usd, created_at
        FROM conversations WHERE client_id = ?
    """
    params: list = [client_id]
    if only_low:
        query += " AND (confidence < 0.75 OR needs_human = 1)"
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _sqlite_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_stats(client_id: str) -> dict:
    if _USE_PG:
        return _stats_pg(client_id)
    with _sqlite_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) as total,
                      ROUND(AVG(confidence), 2) as avg_confidence,
                      SUM(needs_human) as escalations,
                      ROUND(SUM(cost_usd), 4) as total_cost
               FROM conversations WHERE client_id = ?""",
            (client_id,),
        ).fetchone()
    return dict(row) if row else {}
