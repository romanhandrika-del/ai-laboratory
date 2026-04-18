"""
YouTube Storage — SQLite для відстеження оброблених відео.

Таблиця processed_videos: video_id (UNIQUE), channel_id, client_id, processed_at
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from core.logger import get_logger

logger = get_logger(__name__)

_DB_PATH = Path(__file__).parent.parent / "data" / "youtube_processed.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS processed_videos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id    TEXT NOT NULL DEFAULT 'default',
    channel_id   TEXT NOT NULL DEFAULT '',
    video_id     TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    UNIQUE(client_id, video_id)
);
"""


def _get_conn() -> sqlite3.Connection:
    """Відкриває з'єднання з БД оброблених відео."""
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
    logger.info("YouTube DB ініціалізована: %s", _DB_PATH)


def is_processed(client_id: str, video_id: str) -> bool:
    """
    Перевіряє чи відео вже було оброблено.

    Args:
        client_id: ID клієнта
        video_id:  YouTube video ID

    Returns:
        True якщо вже оброблено
    """
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM processed_videos WHERE client_id=? AND video_id=?",
            (client_id, video_id),
        ).fetchone()
    return row is not None


def mark_processed(client_id: str, video_id: str, channel_id: str = "") -> None:
    """
    Позначає відео як оброблене.

    Args:
        client_id:  ID клієнта
        video_id:   YouTube video ID
        channel_id: YouTube channel ID (для контексту)
    """
    now = datetime.now().isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO processed_videos (client_id, channel_id, video_id, processed_at) VALUES (?, ?, ?, ?)",
            (client_id, channel_id, video_id, now),
        )
        conn.commit()
    logger.info("Відео позначено як оброблене: %s", video_id)
