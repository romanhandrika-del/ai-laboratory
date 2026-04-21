"""
Обробник файлів (фото, PDF, зображення) для Telegram і webhook
"""

import asyncio
import base64
import logging
import httpx
from anthropic import Anthropic, APIStatusError

logger = logging.getLogger(__name__)
client = Anthropic()

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

VISION_ADDON = """Це повідомлення — фото або креслення від клієнта. Додаткові інструкції для Vision-аналізу:

## ПРІОРИТЕТ 1 — OCR-текст
У повідомленні є блок "Текст розпізнаний OCR". Перш за все шукай в ньому:
- Явні розміри: "900×2100", "3м", "2.5м", "ширина 1200", "висота 2000", "1,2 × 2,1", цифри з "мм"/"см"/"м"
- Якщо знайшов два числа схожі на ширину і висоту — вважай що розміри є і одразу рахуй ціну
- Не питай клієнта про розміри якщо вони вже є в OCR-тексті або видно на зображенні

## ПРІОРИТЕТ 2 — Зображення
Визнач з фото:
- Тип виробу (перегородка / двері / душова / огородження)
- Тип відкривання якщо видно (розсувні / поворотні) — визначив сам = не питай
- Тип скла (прозоре / тоноване / декоративне Flutes)

## ЩОДО ЦІНИ
Використовуй прайс і всі правила розрахунку (включаючи коефіцієнти) з основного системного промпту вище.
Не вигадуй ціни, не використовуй старі значення з пам'яті.
Ціну називай з "від", коротко: "Орієнтовно від X грн — під ключ по Києву 🙂"

## ЯКЩО РОЗМІРІВ НЕМАЄ НІДЕ:
Задай ОДНЕ запитання:
"На фото — [що бачиш]. Є розміри? Ширина і висота хоча б орієнтовні 🙂"

## ЯКЩО ВИРІБ НЕСТАНДАРТНИЙ (огородження, ніша, підсвітка, незвичайна форма):
Відповідай: "Це вже до нашого спеціаліста — він знає всі нюанси 🙂 Залиште номер або він напише тут."
Додавай мітку [NOTIFY_MANAGER] в кінці відповіді (невидима клієнту, для системи).

## ЯКЩО КЛІЄНТ НЕ НАДАВ РОЗМІРИ ПІСЛЯ ЗАПИТАННЯ:
Відповідай: "Зрозуміло! Передаємо менеджеру — він зв'яжеться з вами найближчим часом 🙂"
Додавай мітку [NOTIFY_MANAGER] в кінці відповіді.

## СТИЛЬ:
- Говори як людина, коротко — 2-3 речення максимум
- Мова клієнта (українська або російська)
- 1-2 емодзі доречно
- Ніколи не починай з "Шановний клієнт" або офіційних фраз
- Клієнту — тільки загальна фінальна сума. Ніяких кроків розрахунку, формул, знижок у відсотках, розбивки по позиціях"""


async def _download_file(url: str) -> bytes:
    """Завантажує файл за URL"""
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.get(url)
        response.raise_for_status()
        return response.content


def _detect_media_type(url: str, content_type: str | None = None) -> str:
    """Визначає MIME тип файлу"""
    if content_type and content_type in SUPPORTED_IMAGE_TYPES:
        return content_type

    url_lower = url.lower().split("?")[0]
    if url_lower.endswith(".pdf"):
        return "application/pdf"
    elif url_lower.endswith(".png"):
        return "image/png"
    elif url_lower.endswith(".gif"):
        return "image/gif"
    elif url_lower.endswith(".webp"):
        return "image/webp"
    else:
        return "image/jpeg"  # за замовчуванням


async def handle_image_bytes(image_bytes: bytes, media_type: str, conversation_history: list, system_prompt: str) -> str:
    """Передає зображення в Claude Vision і повертає відповідь.
    Перед Claude запускає Google Vision OCR — передає розпізнаний текст як контекст."""
    if media_type not in SUPPORTED_IMAGE_TYPES:
        media_type = "image/jpeg"

    # OCR-попередник: витягуємо текст (розміри, підписи) з фото/креслення
    from agents.instagram.ocr import extract_text_from_image
    ocr_text = await extract_text_from_image(image_bytes)

    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    # Формуємо повідомлення: зображення + OCR-текст як окремий блок
    ocr_block = (
        f"Текст розпізнаний OCR з фото (може містити розміри, підписи, розрахунки):\n"
        f"---\n{ocr_text}\n---" if ocr_text else
        "Текст розпізнаний OCR з фото: (текст не розпізнано — аналізуй тільки зображення)"
    )

    messages = conversation_history.copy()
    messages.append({
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_b64,
                },
            },
            {
                "type": "text",
                "text": f"{ocr_block}\n\nПроаналізуй фото разом з OCR-текстом і допоможи клієнту."
            }
        ],
    })

    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
            )
            return response.content[0].text
        except APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                await asyncio.sleep(3)
                continue
            raise
    return "Сервіс тимчасово перевантажений. Спробуйте через хвилину."


async def handle_pdf_bytes(pdf_bytes: bytes, conversation_history: list, system_prompt: str) -> str:
    """Витягує текст з PDF і передає Claude"""
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as e:
        logger.error(f"Помилка читання PDF: {e}")
        text = ""

    if not text:
        return "Не вдалося прочитати PDF. Будь ласка, надішліть файл у форматі JPG або PNG, або опишіть розміри текстом."

    messages = conversation_history.copy()
    messages.append({
        "role": "user",
        "content": f"Клієнт надіслав технічне завдання (PDF):\n\n{text[:4000]}"
    })

    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
            )
            return response.content[0].text
        except APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                await asyncio.sleep(3)
                continue
            raise
    return "Сервіс тимчасово перевантажений. Спробуйте через хвилину."


async def handle_photo_with_addon(photo_bytes: bytes, conversation_history: list, system_prompt: str = "") -> str:
    """Обробник фото (Telegram та webhook) — склеює sales.md з VISION_ADDON"""
    combined = f"{system_prompt}\n\n---\n\n{VISION_ADDON}" if system_prompt else VISION_ADDON
    return await handle_image_bytes(photo_bytes, "image/jpeg", conversation_history, combined)


async def handle_pdf_with_addon(pdf_bytes: bytes, conversation_history: list, system_prompt: str = "") -> str:
    """Обробник PDF (Telegram та webhook) — склеює sales.md з VISION_ADDON"""
    combined = f"{system_prompt}\n\n---\n\n{VISION_ADDON}" if system_prompt else VISION_ADDON
    return await handle_pdf_bytes(pdf_bytes, conversation_history, combined)


AUDIO_EXTENSIONS = {".ogg", ".opus", ".mp3", ".m4a", ".mp4", ".aac", ".wav"}
AUDIO_MIME_TYPES = {"audio/ogg", "audio/mpeg", "audio/mp4", "audio/aac", "audio/wav", "audio/opus"}


def _is_audio(file_url: str, file_type: str | None) -> tuple[bool, str]:
    """Повертає (is_audio, mime_hint)."""
    # file_type від SendPulse: "audio", "voice", "audio_message"
    if file_type in ("audio", "voice", "audio_message"):
        return True, "audio/ogg"
    url_lower = file_url.lower().split("?")[0]
    for ext in AUDIO_EXTENSIONS:
        if url_lower.endswith(ext):
            mime = "audio/ogg" if ext in (".ogg", ".opus") else f"audio/{ext.lstrip('.')}"
            return True, mime
    # Ключові слова в URL (SendPulse може мати /audio/ або /voice/ в шляху)
    if any(kw in url_lower for kw in ("/audio/", "/voice/", "/sound/")):
        return True, "audio/ogg"
    return False, ""


async def handle_file_url(file_url: str, file_type: str | None, conversation_history: list, system_prompt: str = "") -> str:
    """
    Основна точка входу для webhook (Instagram/Facebook).
    file_type: 'image', 'pdf', 'audio', 'voice' або None (автовизначення)
    """
    try:
        file_bytes = await _download_file(file_url)

        # Голосове повідомлення → транскрипція → Sales Agent
        is_audio, mime_hint = _is_audio(file_url, file_type)
        if is_audio:
            return await handle_audio_bytes(file_bytes, mime_hint, conversation_history, system_prompt)

        media_type = _detect_media_type(file_url) if file_type != "pdf" else "application/pdf"

        if media_type == "application/pdf":
            return await handle_pdf_with_addon(file_bytes, conversation_history, system_prompt)
        else:
            return await handle_photo_with_addon(file_bytes, conversation_history, system_prompt)

    except httpx.HTTPError as e:
        logger.error(f"Помилка завантаження файлу {file_url}: {e}")
        return "Не вдалося завантажити файл. Спробуйте надіслати ще раз."
    except Exception as e:
        logger.error(f"Помилка обробки файлу: {e}")
        return "Помилка при обробці файлу. Спробуйте надіслати текстом або іншим форматом."


async def handle_audio_bytes(audio_bytes: bytes, mime_hint: str, conversation_history: list, system_prompt: str) -> str:
    """Транскрибує голосове через Google Speech і передає Sales Agent."""
    from agents.instagram.speech import transcribe_audio
    from core.message import AgentMessage

    text = await transcribe_audio(audio_bytes, mime_hint)

    if not text:
        return "Не вдалося розпізнати голосове повідомлення 🙂 Напишіть текстом — відповімо одразу."

    logger.info("Голосове розпізнано: %s", text[:80])

    # Обробляємо розпізнаний текст як звичайне повідомлення через Claude
    messages = conversation_history.copy()
    messages.append({"role": "user", "content": f"[Голосове повідомлення]: {text}"})

    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
            )
            return response.content[0].text
        except APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                await asyncio.sleep(3)
                continue
            raise
    return "Сервіс тимчасово перевантажений. Спробуйте через хвилину."
