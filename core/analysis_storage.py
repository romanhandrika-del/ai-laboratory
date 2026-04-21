"""
Analysis Storage — зберігає історію аналізів Multimodal Analyst.
PostgreSQL якщо є DATABASE_URL, інакше SQLite.

Оригінали файлів — у Telegram Archive Channel (tg_file_id).
Звіти — як TEXT у БД.
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

_DB_PATH = Path(__file__).parent.parent / "data" / "analysis_history.db"
_DATABASE_URL = os.getenv("DATABASE_URL", "")
_USE_PG = bool(_DATABASE_URL)

_CREATE_SQLITE = """
CREATE TABLE IF NOT EXISTS analysis_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id           TEXT    NOT NULL DEFAULT 'default',
    kind                TEXT    NOT NULL,
    confidence          TEXT    NOT NULL DEFAULT 'середня',
    source_tg_file_id   TEXT,
    source_tg_msg_id    INTEGER,
    report_text         TEXT,
    created_at          TEXT    NOT NULL
);
"""

_CREATE_PG = """
CREATE TABLE IF NOT EXISTS analysis_history (
    id                  SERIAL PRIMARY KEY,
    client_id           TEXT    NOT NULL DEFAULT 'default',
    kind                TEXT    NOT NULL,
    confidence          TEXT    NOT NULL DEFAULT 'середня',
    source_tg_file_id   TEXT,
    source_tg_msg_id    BIGINT,
    report_text         TEXT,
    created_at          TEXT    NOT NULL
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_analysis_client_created
ON analysis_history(client_id, created_at DESC);
"""


def _pg_conn():
    import psycopg2
    conn = psycopg2.connect(_DATABASE_URL)
    conn.autocommit = False
    return conn


def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    if _USE_PG:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_PG)
                cur.execute(_CREATE_INDEX)
            conn.commit()
        logger.info("PostgreSQL analysis_history таблиця готова")
    else:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _sqlite_conn() as conn:
            conn.execute(_CREATE_SQLITE)
            conn.execute(_CREATE_INDEX)
        logger.info("SQLite analysis_history: %s", _DB_PATH)


def save_analysis(
    client_id: str,
    kind: str,
    confidence: str,
    report_text: str = "",
    source_tg_file_id: str = "",
    source_tg_msg_id: int = 0,
) -> None:
    ts = datetime.now().isoformat()
    if _USE_PG:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO analysis_history
                       (client_id, kind, confidence, source_tg_file_id,
                        source_tg_msg_id, report_text, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (client_id, kind, confidence, source_tg_file_id,
                     source_tg_msg_id or None, report_text, ts),
                )
            conn.commit()
    else:
        with _sqlite_conn() as conn:
            conn.execute(
                """INSERT INTO analysis_history
                   (client_id, kind, confidence, source_tg_file_id,
                    source_tg_msg_id, report_text, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (client_id, kind, confidence, source_tg_file_id,
                 source_tg_msg_id or None, report_text, ts),
            )


def get_recent(client_id: str, limit: int = 10) -> list[dict]:
    if _USE_PG:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, kind, confidence, source_tg_file_id,
                              source_tg_msg_id, created_at
                       FROM analysis_history WHERE client_id = %s
                       ORDER BY created_at DESC LIMIT %s""",
                    (client_id, limit),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    with _sqlite_conn() as conn:
        rows = conn.execute(
            """SELECT id, kind, confidence, source_tg_file_id,
                      source_tg_msg_id, created_at
               FROM analysis_history WHERE client_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (client_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]
