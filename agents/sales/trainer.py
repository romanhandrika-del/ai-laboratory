"""
Sales Agent Trainer — аналізує реальні діалоги і пише пропозиції покращення в Google Sheets.

Пропозиції → аркуш "Пропозиції" у BRAIN_SHEET_ID таблиці.
Менеджер переглядає вручну і переносить у FAQ/промпт.
"""

import json
import os
from datetime import datetime

from anthropic import Anthropic
from core.conversation_storage import get_review
from core.logger import get_logger

logger = get_logger(__name__)

_ANALYSIS_PROMPT = """Ти — тренер Sales Agent для компанії з виробництва скляних виробів (двері, перегородки, душові).
Проаналізуй діалоги нижче і дай конкретні пропозиції щодо покращення відповідей агента.

Для кожної пропозиції вкажи:
- Тип: FAQ / Prompt / Pricing / Escalation
- Проблема: що пішло не так або що можна покращити
- Пропозиція: конкретний текст або правило
- Пріоритет: High / Medium / Low

Відповідь у форматі JSON-масиву:
[
  {
    "type": "FAQ",
    "problem": "Клієнт питав про монтаж — бот не знав деталей",
    "suggestion": "Додати в FAQ: Монтаж входить у вартість, займає 1 день.",
    "priority": "High"
  },
  ...
]

Якщо все добре — верни порожній масив [].
Не вигадуй проблем якщо їх немає."""


def _format_dialogs(rows: list[dict]) -> str:
    lines = []
    for i, r in enumerate(rows, 1):
        flag = "🔴 ЕСКАЛАЦІЯ" if r["needs_human"] else (
            "🟡 НИЗЬКА ВПЕВНЕНІСТЬ" if r["confidence"] < 0.75 else "🟢"
        )
        ts = r["created_at"][:16].replace("T", " ")
        lines.append(
            f"--- Діалог {i} [{flag}] {ts} ---\n"
            f"Клієнт: {r['user_msg']}\n"
            f"Бот: {r['bot_reply']}\n"
        )
    return "\n".join(lines)


def _write_to_sheets(suggestions: list[dict], sheet_id: str, credentials_json: str) -> int:
    """Записує пропозиції в аркуш 'Пропозиції'. Повертає кількість записаних рядків."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_info(
        json.loads(credentials_json),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(sheet_id)

    try:
        ws = spreadsheet.worksheet("Пропозиції")
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="Пропозиції", rows=500, cols=6)
        ws.append_row(["Дата", "Тип", "Пріоритет", "Проблема", "Пропозиція", "Статус"])

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = [
        [ts, s.get("type", ""), s.get("priority", ""), s.get("problem", ""), s.get("suggestion", ""), "Нова"]
        for s in suggestions
    ]
    if rows:
        ws.append_rows(rows)
    return len(rows)


def run_training(client_id: str, limit: int = 30, only_low: bool = False) -> dict:
    """
    Основна функція тренування.
    Повертає {"suggestions": [...], "written": N, "error": None}.
    """
    sheet_id = os.getenv("BRAIN_SHEET_ID")
    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")

    rows = get_review(client_id, limit=limit, only_low=only_low)
    if not rows:
        return {"suggestions": [], "written": 0, "error": None, "msg": "Немає діалогів для аналізу."}

    dialogs_text = _format_dialogs(rows)

    client = Anthropic()
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=_ANALYSIS_PROMPT,
            messages=[{"role": "user", "content": f"Проаналізуй ці діалоги:\n\n{dialogs_text}"}],
        )
        raw = response.content[0].text.strip()
        # Знаходимо JSON-масив у відповіді
        start = raw.find("[")
        end = raw.rfind("]") + 1
        suggestions = json.loads(raw[start:end]) if start >= 0 else []
    except Exception as e:
        logger.error("Trainer Claude error: %s", e)
        return {"suggestions": [], "written": 0, "error": str(e)}

    written = 0
    if suggestions and sheet_id and credentials_json:
        try:
            written = _write_to_sheets(suggestions, sheet_id, credentials_json)
            logger.info("Trainer: записано %d пропозицій у Sheets", written)
        except Exception as e:
            logger.error("Trainer Sheets error: %s", e)
            return {"suggestions": suggestions, "written": 0, "error": str(e)}
    elif suggestions and (not sheet_id or not credentials_json):
        logger.warning("Trainer: BRAIN_SHEET_ID або GOOGLE_CREDENTIALS_JSON не налаштовані — пропозиції не збережено")

    return {"suggestions": suggestions, "written": written, "error": None}
