"""Security contract for Telegram Bot API webhook requests."""

from __future__ import annotations

import hmac
import re
from collections.abc import Mapping


TELEGRAM_WEBHOOK_SECRET_ENV = "TELEGRAM_WEBHOOK_SECRET"
TELEGRAM_WEBHOOK_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


def load_telegram_webhook_secret(env: Mapping[str, str]) -> str:
    """Load a strong Telegram webhook secret or fail closed."""
    secret = env.get(TELEGRAM_WEBHOOK_SECRET_ENV, "").strip()
    if not _SECRET_RE.fullmatch(secret):
        raise RuntimeError(
            f"{TELEGRAM_WEBHOOK_SECRET_ENV} must contain 32-256 characters "
            "using only A-Z, a-z, 0-9, underscore, or hyphen"
        )
    return secret


def is_telegram_webhook_authorized(
    headers: Mapping[str, str],
    expected_secret: str,
) -> bool:
    """Return True only for the exact secret configured with Telegram."""
    supplied_secret = headers.get(TELEGRAM_WEBHOOK_SECRET_HEADER, "")
    return bool(supplied_secret) and hmac.compare_digest(
        supplied_secret,
        expected_secret,
    )
