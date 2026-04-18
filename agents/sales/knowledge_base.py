import json
import os
import gspread
from google.oauth2.service_account import Credentials
from core.logger import get_logger

logger = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _get_sheets_client():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON не знайдено в .env")
    creds = Credentials.from_service_account_info(
        json.loads(creds_json), scopes=SCOPES
    )
    return gspread.authorize(creds)


def load_kb(client_id: str, sheet_id: str) -> str:
    """
    Завантажує Knowledge Base клієнта з Google Sheets.

    Структура таблиці:
    - Аркуш 'Info'    → загальна інформація (назва, адреса, телефон, сайт)
    - Аркуш 'Products' → список продуктів і послуг
    - Аркуш 'Prices'  → прайс-лист (таблиця)
    - Аркуш 'FAQ'     → питання та відповіді

    Повертає: відформатований текст для вставки у system prompt.
    """
    try:
        gc = _get_sheets_client()
        sh = gc.open_by_key(sheet_id)
        sections = []

        # Info — загальна інформація
        try:
            ws = sh.worksheet("Info")
            rows = ws.get_all_values()
            if rows:
                sections.append("=== ІНФОРМАЦІЯ ПРО КОМПАНІЮ ===")
                for row in rows:
                    if len(row) >= 2 and row[0] and row[1]:
                        sections.append(f"{row[0]}: {row[1]}")
        except Exception as e:
            logger.warning(f"[{client_id}] KB: аркуш Info не знайдено: {e}")

        # Products — продукти
        try:
            ws = sh.worksheet("Products")
            rows = ws.get_all_values()
            if len(rows) > 1:
                sections.append("\n=== ПРОДУКТИ / ПОСЛУГИ ===")
                for row in rows[1:]:
                    if row and row[0]:
                        line = row[0]
                        if len(row) > 1 and row[1]:
                            line += f" — {row[1]}"
                        sections.append(f"• {line}")
        except Exception as e:
            logger.warning(f"[{client_id}] KB: аркуш Products не знайдено: {e}")

        # Prices — прайс
        try:
            ws = sh.worksheet("Prices")
            rows = ws.get_all_values()
            if rows:
                sections.append("\n=== ПРАЙС-ЛИСТ ===")
                for row in rows:
                    if any(row):
                        sections.append(" | ".join(cell for cell in row if cell))
        except Exception as e:
            logger.warning(f"[{client_id}] KB: аркуш Prices не знайдено: {e}")

        # FAQ — питання та відповіді
        try:
            ws = sh.worksheet("FAQ")
            rows = ws.get_all_values()
            if len(rows) > 1:
                sections.append("\n=== ЧАСТІ ПИТАННЯ ===")
                for row in rows[1:]:
                    if len(row) >= 2 and row[0] and row[1]:
                        sections.append(f"Q: {row[0]}\nA: {row[1]}")
        except Exception as e:
            logger.warning(f"[{client_id}] KB: аркуш FAQ не знайдено: {e}")

        if not sections:
            logger.error(f"[{client_id}] KB порожня або таблиця недоступна")
            return "База знань наразі недоступна. Передавай всі нестандартні питання менеджеру."

        logger.info(f"[{client_id}] KB завантажена: {len(sections)} секцій")
        return "\n".join(sections)

    except Exception as e:
        logger.error(f"[{client_id}] Помилка завантаження KB: {e}")
        return "База знань наразі недоступна. Передавай всі нестандартні питання менеджеру."
