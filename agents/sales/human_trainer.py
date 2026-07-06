"""
Human Sales Trainer — аналізує живі відповіді менеджера з tg_sales_human.

На відміну від trainer.py, цей режим не шукає помилки бота за confidence.
Він витягує еталонні патерни менеджера і створює пропозиції для approval.
"""

import json
from pathlib import Path

from anthropic import AsyncAnthropic

from agents.sales_telegram.common import SOURCE as HUMAN_SOURCE
from core import db
from core.logger import get_logger

_PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompt_template.md"
logger = get_logger(__name__)

_HUMAN_ANALYSIS_PROMPT = """Ти — тренер Sales Agent для компанії з виробництва скляних виробів.
Нижче наведені ЖИВІ діалоги менеджера з клієнтами з особистого Telegram.
Це не діалоги бота. Менеджерські відповіді є прикладами реального стилю, технічної логіки і продажів.

Завдання:
1. Витягни корисні патерни для Sales Agent:
   - стиль спілкування;
   - уточнення розмірів і технічних деталей;
   - формування ціни;
   - правила розрахунку;
   - відповіді на заперечення;
   - причини ескалації до менеджера;
   - технічну базу, яку варто явно додати в промпт.
2. Перед пропозицією перевір ПОТОЧНИЙ ПРОМПТ нижче. Не дублюй дослівні правила, які вже є.
   Якщо живий діалог уточнює, конкретизує або посилює наявне правило — створи пропозицію.
3. Не вигадуй терміни, ціни, гарантії або технологічні правила. Пропонуй тільки те, що підтверджено діалогами.
4. Не перенось одноразові домовленості конкретного клієнта як загальне правило.
5. Prompt-зміни мають бути короткими, конкретними і придатними для approval менеджером.
6. Поверни 3-8 найсильніших пропозицій, якщо у вибірці є підтверджені патерни.

ПОТОЧНИЙ ПРОМПТ АГЕНТА:
{current_prompt}
---

Формат відповіді — тільки JSON-масив.

Для кожної пропозиції:
- type: FAQ / Prompt / Pricing / Escalation
- category: style_pattern / pricing_logic / objection_handling / technical_knowledge / escalation_handling
- priority: High / Medium / Low
- problem: що зараз агенту бракує
- root_cause: чому це треба додати
- suggestion: конкретне правило або текст
- improvement_hypothesis: як це покращить Sales Agent
- evidence_quote: коротка цитата з живого діалогу до 100 символів

Для type="Prompt" додай:
- section_id: role/communication_style/dialog_rules/calculation_rules/objection_handling/escalation_rules/forbidden_actions
- old_text: "" якщо це нова вставка
- new_text: точний текст правила

Якщо корисних висновків справді немає — поверни [].
"""

_SUGGESTIONS_TOOL = {
    "name": "record_human_sales_suggestions",
    "description": "Записати структуровані пропозиції для Sales Agent на основі живих діалогів менеджера.",
    "input_schema": {
        "type": "object",
        "properties": {
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["FAQ", "Prompt", "Pricing", "Escalation"]},
                        "category": {
                            "type": "string",
                            "enum": [
                                "style_pattern",
                                "pricing_logic",
                                "objection_handling",
                                "technical_knowledge",
                                "escalation_handling",
                            ],
                        },
                        "priority": {"type": "string", "enum": ["High", "Medium", "Low"]},
                        "problem": {"type": "string"},
                        "root_cause": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "improvement_hypothesis": {"type": "string"},
                        "evidence_quote": {"type": "string"},
                        "section_id": {
                            "type": "string",
                            "enum": [
                                "",
                                "role",
                                "communication_style",
                                "dialog_rules",
                                "calculation_rules",
                                "objection_handling",
                                "escalation_rules",
                                "forbidden_actions",
                            ],
                        },
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                    "required": [
                        "type",
                        "category",
                        "priority",
                        "problem",
                        "root_cause",
                        "suggestion",
                        "improvement_hypothesis",
                        "evidence_quote",
                    ],
                },
            }
        },
        "required": ["suggestions"],
    },
}

_FALLBACK_PROMPT_STUB = "(промпт недоступний — аналізуй тільки явні патерни з діалогів)"


def _format_human_dialogs(rows: list[dict]) -> str:
    lines = []
    for i, r in enumerate(rows, 1):
        ts = (r.get("created_at") or "")[:16].replace("T", " ")
        lines.append(
            f"--- Живий діалог {i} {ts} ---\n"
            f"Клієнт: {r['user_msg']}\n"
            f"Менеджер: {r['bot_reply']}\n"
        )
    return "\n".join(lines)


async def run_human_training(client_id: str, limit: int = 80, source: str = HUMAN_SOURCE) -> dict:
    rows = await db.get_dialogs_review(client_id, limit=limit, only_low=False, source=source)
    if not rows:
        return {"suggestions": [], "written": 0, "pending_count": 0, "error": None, "msg": "Немає живих Telegram-діалогів."}

    current_prompt = await db.get_agent_prompt(client_id, "sales_instagram")
    if not current_prompt and _PROMPT_TEMPLATE_PATH.exists():
        current_prompt = _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    current_prompt = current_prompt or _FALLBACK_PROMPT_STUB

    analysis_prompt = _HUMAN_ANALYSIS_PROMPT.replace("{current_prompt}", current_prompt[:7000])
    dialogs_text = _format_human_dialogs(rows)

    client = AsyncAnthropic()
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=analysis_prompt,
            tools=[_SUGGESTIONS_TOOL],
            tool_choice={"type": "tool", "name": "record_human_sales_suggestions"},
            messages=[{"role": "user", "content": f"Проаналізуй живі діалоги менеджера:\n\n{dialogs_text}"}],
        )
        tool_block = next((b for b in response.content if getattr(b, "type", "") == "tool_use"), None)
        if tool_block is not None:
            suggestions = tool_block.input.get("suggestions", [])
        else:
            raw = response.content[0].text.strip()
            start = raw.find("[")
            end = raw.rfind("]") + 1
            suggestions = json.loads(raw[start:end]) if start >= 0 else []
    except Exception as e:
        logger.error("Human trainer Claude error: %s", e)
        return {"suggestions": [], "written": 0, "pending_count": 0, "error": str(e)}

    written = 0
    pending_count = 0
    try:
        based_on_version_id = await db.get_prompt_current_version_id(client_id, "sales_instagram")
        for s in suggestions:
            s_type = s.get("type", "")
            if s_type == "Prompt":
                section_id = s.get("section_id", "")
                new_text = s.get("new_text", "")
                if section_id and new_text:
                    await db.save_trainer_review(
                        client_id=client_id,
                        agent_id="sales_instagram",
                        section_id=section_id,
                        old_text=s.get("old_text", ""),
                        new_text=new_text,
                        reason=s.get("suggestion", s.get("problem", "")),
                        based_on_version_id=based_on_version_id,
                    )
                    pending_count += 1
            else:
                await db.save_trainer_suggestion(
                    client_id=client_id,
                    type=s_type,
                    priority=s.get("priority", ""),
                    problem=s.get("problem", ""),
                    suggestion=s.get("suggestion", ""),
                    category=s.get("category", ""),
                    root_cause=s.get("root_cause", ""),
                    improvement_hypothesis=s.get("improvement_hypothesis", ""),
                    evidence_quote=s.get("evidence_quote", ""),
                )
        written = len(suggestions)
    except Exception as e:
        logger.error("Human trainer DB error: %s", e)
        return {"suggestions": suggestions, "written": 0, "pending_count": 0, "error": str(e)}

    logger.info("Human trainer: %d suggestions (%d pending_reviews)", written, pending_count)
    return {"suggestions": suggestions, "written": written, "pending_count": pending_count, "error": None}
