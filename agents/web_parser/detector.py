"""
Change Detector — порівнює поточний знімок сайту з попереднім.

Нові елементи: є зараз, не було раніше.
Змінені:       є в обох, але значення відрізняються.
Видалені:      було раніше, немає зараз.

Елементи ідентифікуються за key_field (зазвичай 'title').
"""

from core.logger import get_logger

logger = get_logger(__name__)


def detect_changes(
    current: list[dict],
    previous: list[dict],
    key_field: str = "title",
) -> dict:
    """
    Порівнює два списки елементів і повертає різницю.

    Args:
        current:   Поточний список елементів зі сторінки
        previous:  Попередній список (з бази даних)
        key_field: Поле для ідентифікації елемента

    Returns:
        {"new": [...], "changed": [...], "removed": [...]}
    """
    current_map = _build_map(current, key_field)
    previous_map = _build_map(previous, key_field)

    new_items, changed_items, removed_items = [], [], []

    for key, item in current_map.items():
        if key not in previous_map:
            new_items.append(item)
            logger.debug("Detector: новий — %s", key)
        elif item != previous_map[key]:
            changed_items.append({"old": previous_map[key], "new": item})
            logger.debug("Detector: змінений — %s", key)

    for key, item in previous_map.items():
        if key not in current_map:
            removed_items.append(item)
            logger.debug("Detector: видалений — %s", key)

    logger.info(
        "Detector: %d нових, %d змінених, %d видалених",
        len(new_items), len(changed_items), len(removed_items),
    )
    return {"new": new_items, "changed": changed_items, "removed": removed_items}


def has_changes(diff: dict) -> bool:
    """Перевіряє чи є хоч якісь зміни у diff."""
    return bool(diff["new"] or diff["changed"] or diff["removed"])


def _build_map(items: list[dict], key_field: str) -> dict:
    """Перетворює список елементів у словник {key: item}."""
    result: dict = {}
    counters: dict = {}
    for item in items:
        key = item.get(key_field, "").strip()
        if not key:
            logger.warning("Detector: елемент без '%s' — пропускаємо: %s", key_field, item)
            continue
        if key in result:
            counters[key] = counters.get(key, 1) + 1
            key = f"{key} #{counters[key]}"
        result[key] = item
    return result
