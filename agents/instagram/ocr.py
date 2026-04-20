"""
OCR модуль — витягує текст із зображень через Google Cloud Vision API.
Використовує ті самі credentials що й Google Sheets.
"""

import os
import json
import logging

logger = logging.getLogger(__name__)


def _get_vision_client():
    """Створює Vision-клієнт через існуючі Google credentials проєкту"""
    from google.cloud import vision
    from google.oauth2.service_account import Credentials

    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        return vision.ImageAnnotatorClient(credentials=creds)

    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return vision.ImageAnnotatorClient(credentials=creds)


async def extract_text_from_image(image_bytes: bytes) -> str:
    """
    Витягує весь текст із зображення через Google Vision (DOCUMENT_TEXT_DETECTION).
    Добре читає: рукописні цифри, розміри на кресленнях, цифри в таблицях.
    При будь-якій помилці повертає '' — бот продовжить роботу через Claude Vision.
    """
    try:
        from google.cloud import vision
        client = _get_vision_client()
        image = vision.Image(content=image_bytes)
        response = client.document_text_detection(image=image)

        if response.error.message:
            logger.error(f"Google Vision API error: {response.error.message}")
            return ""

        text = (response.full_text_annotation.text or "").strip()
        logger.info(f"OCR: розпізнано {len(text)} символів")
        return text

    except Exception as e:
        logger.error(f"OCR exception (fallback to Claude Vision): {e}")
        return ""
