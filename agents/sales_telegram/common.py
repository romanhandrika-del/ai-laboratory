import argparse
import os
import re
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "data" / "sales_telegram"
RAW_DIR = DATA_DIR / "raw"
FORMATTED_DIR = DATA_DIR / "formatted"
DEFAULT_UNTIL = "2024-05-15"
SOURCE = "tg_sales_human"
SESSION_PATH = str(ROOT / "data" / "sales_tg_session")
WHITELIST_PATH = DATA_DIR / "whitelist.yaml"  # data/ — gitignored, містить PII клієнтів
KYIV_TZ = ZoneInfo("Europe/Kyiv")
UTC_TZ = ZoneInfo("UTC")

PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")


def add_date_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--until",
        default=DEFAULT_UNTIL,
        help="Inclusive Kyiv date boundary, YYYY-MM-DD. Default: 2024-05-15.",
    )
    parser.add_argument(
        "--from-date",
        default=None,
        help="Optional inclusive Kyiv start date, YYYY-MM-DD.",
    )


def parse_kyiv_day_end(value: str) -> datetime:
    day = datetime.strptime(value, "%Y-%m-%d").date()
    return datetime.combine(day, time(23, 59, 59), tzinfo=KYIV_TZ).astimezone(UTC_TZ)


def parse_kyiv_day_start(value: str | None) -> datetime | None:
    if not value:
        return None
    day = datetime.strptime(value, "%Y-%m-%d").date()
    return datetime.combine(day, time(0, 0, 0), tzinfo=KYIV_TZ).astimezone(UTC_TZ)


def telethon_offset_after(until_utc: datetime) -> datetime:
    return until_utc + timedelta(seconds=1)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC_TZ)
    return value.astimezone(UTC_TZ)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    FORMATTED_DIR.mkdir(parents=True, exist_ok=True)


def make_client():
    from telethon import TelegramClient

    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        raise RuntimeError("TELEGRAM_API_ID / TELEGRAM_API_HASH не знайдено в env")
    ensure_dirs()
    return TelegramClient(SESSION_PATH, api_id, api_hash)


def load_whitelist(path: Path = WHITELIST_PATH) -> list[int]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_chats = data.get("chats", data if isinstance(data, list) else [])
    ids: list[int] = []
    for item in raw_chats:
        if isinstance(item, int):
            ids.append(item)
        elif isinstance(item, str) and item.strip().lstrip("-").isdigit():
            ids.append(int(item.strip()))
        elif isinstance(item, dict) and item.get("chat_id") is not None:
            ids.append(int(item["chat_id"]))
    return ids


def anonymize_text(text: str) -> str:
    text = PHONE_RE.sub("[phone]", text)
    text = EMAIL_RE.sub("[email]", text)
    return text.strip()


def safe_name(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ_-]+", "_", value.strip())
    return value.strip("_")[:80] or "chat"
