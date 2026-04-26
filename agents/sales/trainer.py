"""
Sales Agent Trainer — аналізує реальні діалоги і зберігає пропозиції покращення в Neon.

Пропозиції → таблиця trainer_suggestions.
Менеджер переглядає вручну і переносить у FAQ/промпт.
"""

import json
from anthropic import AsyncAnthropic
from core import db
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


async def run_training(client_id: str, limit: int = 30, only_low: bool = False) -> dict:
    """
    Основна функція тренування.
    Повертає {"suggestions": [...], "written": N, "error": None}.
    """
    rows = await db.get_dialogs_review(client_id, limit=limit, only_low=only_low)
    if not rows:
        return {"suggestions": [], "written": 0, "error": None, "msg": "Немає діалогів для аналізу."}

    dialogs_text = _format_dialogs(rows)

    client = AsyncAnthropic()
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=_ANALYSIS_PROMPT,
            messages=[{"role": "user", "content": f"Проаналізуй ці діалоги:\n\n{dialogs_text}"}],
        )
        raw = response.content[0].text.strip()
        start = raw.find("[")
        end = raw.rfind("]") + 1
        suggestions = json.loads(raw[start:end]) if start >= 0 else []
    except Exception as e:
        logger.error("Trainer Claude error: %s", e)
        return {"suggestions": [], "written": 0, "error": str(e)}

    written = 0
    if suggestions:
        try:
            for s in suggestions:
                await db.save_trainer_suggestion(
                    client_id=client_id,
                    type=s.get("type", ""),
                    priority=s.get("priority", ""),
                    problem=s.get("problem", ""),
                    suggestion=s.get("suggestion", ""),
                )
            written = len(suggestions)
            logger.info("Trainer: збережено %d пропозицій у Neon", written)
        except Exception as e:
            logger.error("Trainer DB error: %s", e)
            return {"suggestions": suggestions, "written": 0, "error": str(e)}

    return {"suggestions": suggestions, "written": written, "error": None}
