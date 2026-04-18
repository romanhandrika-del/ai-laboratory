"""
Snapshot Storage — SQLite для збереження знімків сайтів.

Файл БД: data/web_snapshots.db
Таблиця web_snapshots: url (UNIQUE), data_json, snapshot_at, client_id
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

_DB_PATH = Path(__file__).parent.parent / "data" / "web_snapshots.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS web_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   TEXT    NOT NULL DEFAULT 'default',
    url         TEXT    NOT NULL,
    data_json   TEXT    NOT NULL,
    snapshot_at TEXT    NOT NULL,
    UNIQUE(client_id, url)
);
"""


def _get_conn() -> sqlite3.Connection:
    """Відкриває з'єднання з БД знімків."""
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    """Створює таблицю якщо не існує. Викликати один раз при старті."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute(_CREATE_TABLE)
        conn.commit()
    logger.info("Snapshot DB ініціалізована: %s", _DB_PATH)


def get_last_snapshot(client_id: str, site_url: str) -> list[dict] | None:
    """
    Повертає останній збережений знімок сайту або None (перший запуск).

    Args:
        client_id: ID клієнта (multi-tenancy)
        site_url:  URL сторінки

    Returns:
        Список елементів або None
    """
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT data_json FROM web_snapshots WHERE client_id=? AND url=?",
            (client_id, site_url),
        ).fetchone()

    if row is None:
        logger.info("Знімок для %s/%s не знайдено — перший запуск", client_id, site_url)
        return None
    return json.loads(row["data_json"])


def save_snapshot(client_id: str, site_url: str, items: list[dict]) -> None:
    """
    Зберігає (або оновлює) знімок сайту.

    Args:
        client_id: ID клієнта
        site_url:  URL сторінки
        items:     Список елементів від parser.py
    """
    now = datetime.now().isoformat()
    data_json = json.dumps(items, ensure_ascii=False)
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO web_snapshots (client_id, url, data_json, snapshot_at)
            VALUES (?, ?, ?, ?)
            """,
            (client_id, site_url, data_json, now),
        )
        conn.commit()
    logger.info("Знімок збережено: %s/%s (%d елементів)", client_id, site_url, len(items))
