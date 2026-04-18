"""
Channel Feed — отримує список нових відео з YouTube каналу через RSS.

YouTube надає безкоштовний RSS-фід без API ключа:
  https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID

RSS показує останні 15 відео каналу. Для щоденного моніторингу цього достатньо.
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from core.logger import get_logger

logger = get_logger(__name__)

_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
_YT_NS = "http://www.youtube.com/xml/schemas/2015"
_MEDIA_NS = "http://search.yahoo.com/mrss/"
_ATOM_NS = "http://www.w3.org/2005/Atom"

_TIMEOUT_S = 10


def get_recent_videos(channel_id: str, limit: int = 5) -> list[dict]:
    """
    Повертає останні відео з каналу через RSS.

    Args:
        channel_id: YouTube channel ID (UCxxxxxxxxxxxxxxxx)
        limit:      Максимум відео для повернення

    Returns:
        Список словників:
        [{"video_id": "...", "title": "...", "url": "...", "published": datetime}]
    """
    url = _RSS_URL.format(channel_id=channel_id)
    logger.debug("Channel Feed: запит RSS для %s", channel_id)

    _HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        xml_bytes = resp.content
    except Exception as e:
        raise RuntimeError(f"Не вдалось отримати RSS для {channel_id}: {e}") from e

    return _parse_feed(xml_bytes, limit)


def _parse_feed(xml_bytes: bytes, limit: int) -> list[dict]:
    """Розбирає XML RSS-фід і повертає список відео."""
    root = ET.fromstring(xml_bytes)

    videos = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry")[:limit]:
        video_id_el = entry.find(f"{{{_YT_NS}}}videoId")
        title_el = entry.find(f"{{{_ATOM_NS}}}title")
        published_el = entry.find(f"{{{_ATOM_NS}}}published")

        if video_id_el is None or title_el is None:
            continue

        video_id = video_id_el.text or ""
        title = title_el.text or ""
        published_str = published_el.text if published_el is not None else ""

        published = _parse_date(published_str)

        videos.append({
            "video_id": video_id,
            "title": title,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "published": published,
        })

    logger.debug("Channel Feed: знайдено %d відео", len(videos))
    return videos


def _parse_date(date_str: str) -> datetime:
    """Парсить ISO 8601 дату з RSS у datetime UTC."""
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(tz=timezone.utc)
