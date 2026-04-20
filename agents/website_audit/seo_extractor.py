"""
SEO Extractor — витягує on-page SEO дані з HTML через selectolax.
"""

import json
import re
from urllib.parse import urlparse
from selectolax.parser import HTMLParser
from core.logger import get_logger

logger = get_logger(__name__)


def _text_with_br(node) -> str:
    """Витягує текст з HTML-вузла, замінюючи <br> на пробіл."""
    raw = node.html or ""
    text = re.sub(r"<br\s*/?>", " ", raw, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())


def extract(html: str, url: str) -> dict:
    """
    Витягує SEO-метадані зі сторінки.

    Returns dict:
        title, meta_description, h1_list, h2_list, canonical, robots_meta,
        og_title, og_description, og_image, json_ld_types,
        images_total, images_no_alt, internal_links, external_links,
        page_size_kb
    """
    tree = HTMLParser(html)
    domain = urlparse(url).netloc

    # Title
    title_node = tree.css_first("title")
    title = title_node.text(strip=True) if title_node else ""

    # Meta description
    meta_desc = ""
    for node in tree.css('meta[name="description"]'):
        meta_desc = node.attributes.get("content", "")
        break

    h1_list = [t for n in tree.css("h1") if (t := _text_with_br(n))]
    h2_list = [t for n in tree.css("h2") if (t := _text_with_br(n))]

    # Canonical
    canonical = ""
    for node in tree.css('link[rel="canonical"]'):
        canonical = node.attributes.get("href", "")
        break

    # Robots meta
    robots_meta = ""
    for node in tree.css('meta[name="robots"]'):
        robots_meta = node.attributes.get("content", "")
        break

    # Open Graph
    og = {}
    for node in tree.css("meta[property]"):
        prop = node.attributes.get("property", "")
        content = node.attributes.get("content", "")
        if prop.startswith("og:"):
            og[prop[3:]] = content

    # JSON-LD structured data types
    json_ld_types = []
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text())
            if isinstance(data, dict):
                t = data.get("@type", "")
                if t:
                    json_ld_types.append(t)
            elif isinstance(data, list):
                json_ld_types.extend(d.get("@type", "") for d in data if isinstance(d, dict) and d.get("@type"))
        except Exception:
            pass

    # Images
    images = tree.css("img")
    images_no_alt = sum(1 for img in images if not (img.attributes.get("alt") or "").strip())

    # Links
    internal_links, external_links = 0, 0
    for a in tree.css("a[href]"):
        href = a.attributes.get("href", "")
        if href.startswith("http") and domain not in href:
            external_links += 1
        elif href and not href.startswith(("mailto:", "tel:", "#", "javascript:")):
            internal_links += 1

    page_size_kb = round(len(html.encode("utf-8")) / 1024, 1)

    result = {
        "title": title,
        "title_length": len(title),
        "meta_description": meta_desc,
        "meta_description_length": len(meta_desc),
        "h1_list": h1_list[:5],
        "h1_count": len(h1_list),
        "h2_list": h2_list[:10],
        "h2_count": len(h2_list),
        "canonical": canonical,
        "robots_meta": robots_meta,
        "og_title": og.get("title", ""),
        "og_description": og.get("description", ""),
        "og_image": og.get("image", ""),
        "json_ld_types": json_ld_types,
        "images_total": len(images),
        "images_no_alt": images_no_alt,
        "internal_links": internal_links,
        "external_links": external_links,
        "page_size_kb": page_size_kb,
    }

    logger.info("SEOExtractor: title=%r, h1=%d, images=%d, no_alt=%d",
                title[:50], len(h1_list), len(images), images_no_alt)
    return result
