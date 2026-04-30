"""Витяг і нормалізація українського номера телефону з тексту."""

import re

_PHONE_RE = re.compile(
    r"""
    (?<!\d)               # не цифра перед
    (\+?380|0)            # початок: +380, 380 або 0
    [\s\-\(]*
    ([3456789]\d)         # код оператора (67, 50, 63 тощо)
    [\s\-\)]*
    (\d{3})
    [\s\-]*
    (\d{2})
    [\s\-]*
    (\d{2})
    (?!\d)                # не цифра після
    """,
    re.VERBOSE,
)


def extract_phone(text: str) -> str | None:
    """Повертає перший знайдений номер у форматі +380XXXXXXXXX або None."""
    if not text:
        return None
    m = _PHONE_RE.search(text)
    if not m:
        return None
    prefix, op, p1, p2, p3 = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    if prefix.startswith("0"):
        digits = op + p1 + p2 + p3
    else:
        digits = op + p1 + p2 + p3
    return f"+380{digits}"
