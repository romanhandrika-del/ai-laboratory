"""
Design Extractor — витягує візуальні характеристики сайту з HTML (selectolax).
"""

from selectolax.parser import HTMLParser
from core.logger import get_logger

logger = get_logger(__name__)


def extract(html: str, visual_data: dict | None = None) -> dict:
    """
    Збирає дизайн-метадані зі сторінки.

    Args:
        html:        повний HTML після JS-рендеру
        visual_data: результат JS getComputedStyle (з fetch_page_with_styles),
                     якщо None — визначаємо лише з HTML

    Returns dict:
        fonts, colors, bg_colors, sections_count, has_hero, has_footer,
        images_count, buttons_count, inline_styles_count
    """
    tree = HTMLParser(html)

    images_count = len(tree.css("img"))
    buttons_count = len(tree.css("button")) + len(
        [a for a in tree.css("a") if "btn" in (a.attributes.get("class") or "").lower()]
    )
    inline_styles_count = len(tree.css("[style]"))

    sections = tree.css("section, article")
    sections_count = len(sections)
    has_hero = bool(
        tree.css('[class*="hero"], [class*="banner"], [id*="hero"]')
    )
    has_footer = bool(tree.css("footer, [class*='footer']"))

    result = {
        "fonts": [],
        "colors": [],
        "bg_colors": [],
        "sections_count": sections_count,
        "has_hero": has_hero,
        "has_footer": has_footer,
        "images_count": images_count,
        "buttons_count": buttons_count,
        "inline_styles_count": inline_styles_count,
    }

    if visual_data:
        result.update({
            "fonts": visual_data.get("fonts", []),
            "colors": visual_data.get("colors", []),
            "bg_colors": visual_data.get("bg_colors", []),
            "sections_count": visual_data.get("sections_count", sections_count),
            "has_hero": visual_data.get("has_hero", has_hero),
            "has_footer": visual_data.get("has_footer", has_footer),
            "images_count": visual_data.get("images_count", images_count),
            "buttons_count": visual_data.get("buttons_count", buttons_count),
            "viewport_width": visual_data.get("viewport_width", 1280),
        })

    logger.info(
        "DesignExtractor: fonts=%s, colors=%d, sections=%d",
        result["fonts"][:2], len(result["colors"]), result["sections_count"],
    )
    return result
