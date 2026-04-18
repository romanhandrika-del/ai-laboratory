"""
Web Parser — витягує структуровані дані з HTML через Selectolax.

Кожен сайт має свої CSS-селектори, описані в config/sites.yaml.
Якщо є ключ 'container' — парсимо повторювані блоки (картки, тарифи).
Якщо немає — витягуємо одиничні поля зі всієї сторінки.
"""

from selectolax.parser import HTMLParser
from core.logger import get_logger

logger = get_logger(__name__)


def parse_items(html: str, selectors: dict) -> list[dict]:
    """
    Витягує список елементів зі сторінки за CSS-селекторами.

    Args:
        html:      HTML сторінки
        selectors: Словник {поле: css_selector} з sites.yaml

    Returns:
        Список словників — кожен є одним елементом зі сторінки.
    """
    tree = HTMLParser(html)
    container_selector = selectors.get("container")
    field_selectors = {k: v for k, v in selectors.items() if k != "container"}

    if not field_selectors:
        logger.warning("Parser: немає полів для парсингу")
        return []

    if container_selector:
        containers = tree.css(container_selector)
        logger.debug("Parser: знайдено %d контейнерів за '%s'", len(containers), container_selector)
        items = []
        for node in containers:
            item = _extract_fields(node, field_selectors)
            if any(v for v in item.values()):
                items.append(item)
        logger.debug("Parser: розпарсено %d елементів", len(items))
        return items
    else:
        item = _extract_fields(tree, field_selectors)
        if any(v for v in item.values()):
            logger.debug("Parser: розпарсено 1 елемент (single-page режим)")
            return [item]
        logger.warning("Parser: жоден селектор нічого не знайшов")
        return []


def _extract_fields(node, field_selectors: dict) -> dict:
    """Витягує значення кожного поля з вузла HTML."""
    result = {}
    for field, selector in field_selectors.items():
        found = node.css_first(selector)
        result[field] = found.text(strip=True) if found else ""
    return result
