"""
Multimodal Analyst Agent — Agent #6 платформи AI Laboratory.

Приймає байти фото або PDF, аналізує через Claude Vision,
повертає структурований Markdown-звіт.

Зберігання:
  - Оригінал → Telegram Archive Channel (handle_analyze у bot.py)
  - Звіт     → TEXT у Postgres/SQLite (analysis_history)
"""

import asyncio
import base64
import os

import anthropic
from anthropic import APIStatusError

from core import db
from core.logger import get_logger
from agents.multimodal_analyst.analyst_generator import (
    build_system_prompt,
    parse_detection,
    md_to_html,
)

logger = get_logger(__name__)

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


class MultimodalAnalystAgent:
    """Multimodal Analyst — класифікує і аналізує зображення/PDF."""

    agent_id = "multimodal-analyst-v1"

    def __init__(self, client_id: str = "default"):
        self.client_id = client_id

    async def analyze(
        self,
        file_bytes: bytes,
        media_type: str,
        override_kind: str = "",
        source_tg_file_id: str = "",
        source_tg_msg_id: int = 0,
    ) -> dict:
        """
        Аналізує фото або PDF.

        Args:
            file_bytes:        байти файлу
            media_type:        MIME ('image/jpeg', 'application/pdf', тощо)
            override_kind:     якщо менеджер вказав тип ('pricelist','ad','realty','analytics')
            source_tg_file_id: file_id повідомлення у Archive Channel
            source_tg_msg_id:  message_id у Archive Channel

        Returns dict:
            summary_html, report_md, kind, confidence, error (якщо є)
        """
        is_image = media_type in SUPPORTED_IMAGE_TYPES
        is_pdf = "pdf" in media_type

        if not is_image and not is_pdf:
            is_image = True
            media_type = "image/jpeg"

        try:
            if is_pdf:
                report_md = await self._analyze_pdf(file_bytes, override_kind)
            else:
                report_md = await self._analyze_image(file_bytes, media_type, override_kind)
        except Exception as e:
            logger.error("MultimodalAnalystAgent помилка: %s", e)
            return {"error": str(e)}

        if isinstance(report_md, dict):
            return report_md

        kind, confidence = parse_detection(report_md)

        await db.save_analysis(
            client_id=self.client_id,
            kind=kind,
            confidence=confidence,
            report_text=report_md,
            source_tg_file_id=source_tg_file_id,
            source_tg_msg_id=source_tg_msg_id,
        )

        return {
            "kind": kind,
            "confidence": confidence,
            "report_md": report_md,
            "summary_html": md_to_html(report_md),
        }

    async def _analyze_image(
        self, image_bytes: bytes, media_type: str, override_kind: str
    ) -> str:
        system_prompt = build_system_prompt(self.client_id)

        from agents.instagram.ocr import extract_text_from_image
        ocr_text = await extract_text_from_image(image_bytes)
        ocr_block = (
            f"Текст розпізнаний OCR (назви, цифри, підписи):\n---\n{ocr_text}\n---"
            if ocr_text
            else "OCR: текст не розпізнано — аналізуй тільки зображення."
        )

        override_note = (
            f"\n\nМенеджер вказав тип: `{override_kind}`. "
            "Використовуй цей тип замість автоматичної класифікації."
            if override_kind else ""
        )

        image_b64 = base64.standard_b64encode(image_bytes).decode()
        messages = [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                },
                {"type": "text", "text": f"{ocr_block}{override_note}"},
            ],
        }]

        return await self._call_claude(system_prompt, messages)

    async def _analyze_pdf(self, pdf_bytes: bytes, override_kind: str) -> str | dict:
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(pdf_bytes))
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception as e:
            return {"error": f"Не вдалося прочитати PDF: {e}"}

        if len(text.strip()) < 100:
            return {
                "error": (
                    "PDF схоже сканований — текстового шару немає. "
                    "Надішліть як фото або зробіть скріншот сторінки."
                )
            }

        system_prompt = build_system_prompt(self.client_id)
        override_note = (
            f"\n\nМенеджер вказав тип: `{override_kind}`. "
            "Використовуй цей тип замість автоматичної класифікації."
            if override_kind else ""
        )

        messages = [{
            "role": "user",
            "content": f"Текст з PDF-документу:\n---\n{text[:4000]}\n---{override_note}",
        }]

        return await self._call_claude(system_prompt, messages)

    async def _call_claude(self, system_prompt: str, messages: list) -> str:
        cl = _get_client()
        for attempt in range(3):
            try:
                response = cl.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=2048,
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
