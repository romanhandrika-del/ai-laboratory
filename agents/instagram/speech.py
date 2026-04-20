"""
OpenAI Whisper — транскрипція голосових повідомлень.
Instagram надсилає голосові у форматі OGG/OPUS.
"""

import io
import logging
import os

logger = logging.getLogger(__name__)


async def transcribe_audio(audio_bytes: bytes, mime_hint: str = "") -> str:
    """
    Транскрибує аудіо через OpenAI Whisper.
    Повертає текст або "" якщо не вдалося.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY не налаштовано — транскрипція недоступна")
        return ""

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)

        ext = _mime_to_ext(mime_hint)
        file_obj = io.BytesIO(audio_bytes)
        file_obj.name = f"audio{ext}"

        transcript = await client.audio.transcriptions.create(
            model="whisper-1",
            file=file_obj,
            language="uk",  # Ukrainian — Whisper автоматично розпізнає і російську
        )
        text = transcript.text.strip()
        if text:
            logger.info("Whisper: розпізнано %d символів", len(text))
        return text

    except Exception as e:
        logger.error("Whisper помилка: %s", e)
        return ""


def _mime_to_ext(mime_hint: str) -> str:
    mime = mime_hint.lower()
    if "ogg" in mime or "opus" in mime:
        return ".ogg"
    if "mp4" in mime or "m4a" in mime or "aac" in mime:
        return ".m4a"
    if "mpeg" in mime or "mp3" in mime:
        return ".mp3"
    if "wav" in mime:
        return ".wav"
    return ".ogg"  # за замовчуванням — Instagram
