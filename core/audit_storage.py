"""
Audit Storage — SQLite для збереження історії аудитів і фіксів.

Файл БД: data/audit_history.db
Таблиці: audit_history, fix_history
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

_DB_PATH = Path(__file__).parent.parent / "data" / "audit_history.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS audit_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   TEXT    NOT NULL DEFAULT 'default',
    url         TEXT    NOT NULL,
    score       INTEGER,
    report_path TEXT,
    audited_at  TEXT    NOT NULL
);
"""


_CREATE_FIX_TABLE = """
CREATE TABLE IF NOT EXISTS fix_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id    TEXT    NOT NULL DEFAULT 'default',
    url          TEXT    NOT NULL,
    fix_count    INTEGER,
    fix_path     TEXT,
    backup_path  TEXT,
    status       TEXT    NOT NULL DEFAULT 'generated',
    pr_url       TEXT,
    score_before INTEGER,
    score_after  INTEGER,
    generated_at TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);
"""

_CREATE_DESIGN_TABLE = """
CREATE TABLE IF NOT EXISTS design_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id    TEXT    NOT NULL DEFAULT 'default',
    source       TEXT    NOT NULL,
    mode         TEXT    NOT NULL,
    dir_path     TEXT    NOT NULL,
    generated_at TEXT    NOT NULL
);
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    """Створює таблиці якщо не існують + міграція існуючих таблиць."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_FIX_TABLE)
        conn.execute(_CREATE_DESIGN_TABLE)
        # Міграція: додає backup_path якщо колонки ще немає
        cols = {row[1] for row in conn.execute("PRAGMA table_info(fix_history)")}
        if "backup_path" not in cols:
            conn.execute("ALTER TABLE fix_history ADD COLUMN backup_path TEXT")
        conn.commit()
    logger.info("Audit DB ініціалізована: %s", _DB_PATH)


def save_audit(client_id: str, url: str, score: int, report_path: str) -> None:
    """Зберігає запис аудиту в БД."""
    now = datetime.now().isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_history (client_id, url, score, report_path, audited_at) VALUES (?,?,?,?,?)",
            (client_id, url, score, report_path, now),
        )
        conn.commit()
    logger.info("Audit збережено: %s score=%d", url, score)


def get_last_audit(client_id: str, url: str) -> dict | None:
    """Повертає останній аудит для URL або None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM audit_history WHERE client_id=? AND url=? ORDER BY audited_at DESC LIMIT 1",
            (client_id, url),
        ).fetchone()
    return dict(row) if row else None


def save_fix(client_id: str, url: str, fix_count: int, fix_path: str, score_before: int | None = None) -> int:
    """Зберігає запис fix-генерації. Повертає id запису."""
    now = datetime.now().isoformat()
    with _get_conn() as conn:
        cursor = conn.execute(
            """INSERT INTO fix_history
               (client_id, url, fix_count, fix_path, status, score_before, generated_at, updated_at)
               VALUES (?,?,?,?,'generated',?,?,?)""",
            (client_id, url, fix_count, fix_path, score_before, now, now),
        )
        conn.commit()
        row_id = cursor.lastrowid
    logger.info("Fix збережено: %s fix_count=%d", url, fix_count)
    return row_id


def update_fix_status(
    fix_id: int,
    status: str,
    pr_url: str | None = None,
    score_after: int | None = None,
    backup_path: str | None = None,
) -> None:
    """Оновлює статус фіксу (generated → pushed → verified | rolled_back)."""
    now = datetime.now().isoformat()
    with _get_conn() as conn:
        conn.execute(
            """UPDATE fix_history
               SET status=?, pr_url=?, score_after=?, backup_path=COALESCE(?, backup_path), updated_at=?
               WHERE id=?""",
            (status, pr_url, score_after, backup_path, now, fix_id),
        )
        conn.commit()
    logger.info("Fix #%d статус оновлено: %s", fix_id, status)


def get_last_fix(client_id: str, url: str) -> dict | None:
    """Повертає останній fix-пакет для URL або None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM fix_history WHERE client_id=? AND url=? ORDER BY generated_at DESC LIMIT 1",
            (client_id, url),
        ).fetchone()
    return dict(row) if row else None


def save_design(client_id: str, source: str, mode: str, dir_path: str) -> int:
    """Зберігає запис design-генерації. Повертає id запису."""
    now = datetime.now().isoformat()
    with _get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO design_history (client_id, source, mode, dir_path, generated_at) VALUES (?,?,?,?,?)",
            (client_id, source, mode, dir_path, now),
        )
        conn.commit()
        row_id = cursor.lastrowid
    logger.info("Design збережено: %s mode=%s", source[:80], mode)
    return row_id


def get_last_design(client_id: str, source: str) -> dict | None:
    """Повертає останній design-пакет для source або None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM design_history WHERE client_id=? AND source=? ORDER BY generated_at DESC LIMIT 1",
            (client_id, source),
        ).fetchone()
    return dict(row) if row else None
