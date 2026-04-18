"""
YouTube Transcript — витягує текст транскрипції з відео.

Використовує youtube-transcript-api без потреби в YouTube API ключі.
Пріоритет мов: uk → en → будь-яка доступна.
"""

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled

from core.logger import get_logger

logger = get_logger(__name__)

_LANGUAGE_PRIORITY = ["uk", "en"]
_api = YouTubeTranscriptApi()


def get_transcript(video_id: str) -> dict:
    """
    Отримує транскрипцію YouTube відео за video_id.

    Args:
        video_id: Ідентифікатор відео (11 символів, напр. "VZNzZAO7v8w")

    Returns:
        {"video_id": str, "language": str, "is_generated": bool, "text": str}

    Raises:
        ValueError: якщо транскрипція відсутня або вимкнена
    """
    logger.info("Transcript: отримую для %s", video_id)

    try:
        fetched = _api.fetch(video_id, languages=_LANGUAGE_PRIORITY)
        text = _join(fetched)
        logger.info("Transcript: %s (мова: %s, %d символів)", video_id, fetched.language_code, len(text))
        return {
            "video_id": video_id,
            "language": fetched.language_code,
            "is_generated": fetched.is_generated,
            "text": text,
        }
    except NoTranscriptFound:
        logger.warning("Transcript: uk/en не знайдено для %s — шукаю будь-яку", video_id)

    try:
        transcript_list = _api.list(video_id)
        transcript = next(iter(transcript_list))
        fetched = transcript.fetch()
        text = _join(fetched)
        logger.info("Transcript: %s (мова: %s, auto: %s, %d символів)", video_id, fetched.language_code, fetched.is_generated, len(text))
        return {
            "video_id": video_id,
            "language": fetched.language_code,
            "is_generated": fetched.is_generated,
            "text": text,
        }
    except TranscriptsDisabled:
        raise ValueError(f"Транскрипція вимкнена автором: {video_id}")
    except StopIteration:
        raise ValueError(f"Жодної транскрипції не знайдено: {video_id}")


def _join(fetched) -> str:
    """Об'єднує список сніпетів транскрипції в один рядок."""
    return " ".join(s.text.strip() for s in fetched if s.text)
