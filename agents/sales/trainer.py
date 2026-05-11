"""
Sales Agent Trainer — аналізує реальні діалоги і зберігає пропозиції в Neon.

Prompt-тип → pending_reviews (потребує approval).
Інші типи (FAQ, Pricing, Escalation) → trainer_suggestions.
"""

import json
from pathlib import Path
from anthropic import AsyncAnthropic
from core import db
from core.logger import get_logger

_PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompt_template.md"

logger = get_logger(__name__)

_ANALYSIS_PROMPT_BASE = """Ти — тренер Sales Agent для компанії з виробництва скляних виробів (двері, перегородки, душові).
Проаналізуй НАЙГІРШІ діалоги нижче (відфільтровані за низькою впевненістю та ескалаціями).
Дай конкретні пропозиції щодо покращення відповідей агента.

⚠️ КРИТИЧНО ВАЖЛИВО:
1. Нижче наведено ПОТОЧНИЙ ПРОМПТ агента — перед будь-якою пропозицією перевір що цього правила/тексту ще немає в промпті.
2. НЕ пропонуй те що вже є в промпті (навіть якщо відповідь агента здається неповною).
3. НЕ вигадуй бізнес-параметри (терміни, ціни, гарантії, типи скла) яких немає в промпті — якщо LLM їх не знає, правильна порада: додати явне правило в промпт з точними значеннями.
4. Для type="FAQ": НЕ перераховуй опції які вже є в промпті. FAQ потрібен тільки якщо агент не може відповісти ВЗАГАЛІ (немає навіть загального правила).

ПОТОЧНИЙ ПРОМПТ АГЕНТА:
{current_prompt}
---

Для кожної пропозиції вкажи:
- type: FAQ / Prompt / Pricing / Escalation
- category: knowledge_gap / wrong_tone / missing_info / calculation_error / escalation_handling
- priority: High / Medium / Low
- problem: що пішло не так (1-2 речення)
- root_cause: чому це сталось (прогалина в промпті, FAQ, логіці?)
- suggestion: конкретний текст або правило для виправлення
- improvement_hypothesis: як це зміниться після правки (очікуваний ефект)
- evidence_quote: дослівна цитата з діалогу, що підтверджує проблему (до 100 символів)

Для type="Prompt" обов'язково додай поля:
- section_id: назва XML-секції (role/communication_style/dialog_rules/calculation_rules/objection_handling/escalation_rules/forbidden_actions)
- old_text: точний текст який треба замінити (або "" якщо це нова вставка в секцію)
- new_text: новий текст замість old_text

Відповідь ТІЛЬКИ у форматі JSON-масиву:
[
  {
    "type": "FAQ",
    "category": "knowledge_gap",
    "priority": "High",
    "problem": "Клієнт питав про монтаж — бот не знав деталей",
    "root_cause": "В FAQ немає розділу про монтаж",
    "suggestion": "Додати в FAQ: Монтаж входить у вартість, займає 1 день.",
    "improvement_hypothesis": "Клієнт отримає відповідь без ескалації до менеджера",
    "evidence_quote": "а монтаж окремо платний?"
  },
  {
    "type": "Prompt",
    "section_id": "escalation_rules",
    "old_text": "Питання поза компетенцією",
    "new_text": "Питання поза компетенцією або про технічну документацію",
    "category": "missing_info",
    "priority": "Medium",
    "problem": "Агент не охоплює запити документації",
    "root_cause": "Відсутнє правило в escalation_rules",
    "suggestion": "Додати документацію до тригерів ескалації",
    "improvement_hypothesis": "Менше LOW_CONFIDENCE при запитах документів",
    "evidence_quote": "де взяти технічний паспорт?"
  }
]

Якщо все добре — верни порожній масив [].
Не вигадуй проблем якщо їх немає."""

_FALLBACK_PROMPT_STUB = "(промпт недоступний — аналізуй тільки явні помилки в діалогах)"


def _score_dialog(r: dict) -> float:
    """Чим вище — тим гірший діалог. Ескалація = +1, низька впевненість = (1 - confidence)."""
    return (1.0 - r["confidence"]) + (1.0 if r["needs_human"] else 0.0)


def _pick_worst(rows: list[dict], n: int = 10) -> list[dict]:
    return sorted(rows, key=_score_dialog, reverse=True)[:n]


def _format_dialogs(rows: list[dict]) -> str:
    lines = []
    for i, r in enumerate(rows, 1):
        flag = "🔴 ЕСКАЛАЦІЯ" if r["needs_human"] else (
            "🟡 НИЗЬКА ВПЕВНЕНІСТЬ" if r["confidence"] < 0.75 else "🟢"
        )
        ts = r["created_at"][:16].replace("T", " ")
        responder = "[МЕНЕДЖЕР]" if r.get("by") == "manager" else "Бот:"
        lines.append(
            f"--- Діалог {i} [{flag}] {ts} ---\n"
            f"Клієнт: {r['user_msg']}\n"
            f"{responder} {r['bot_reply']}\n"
        )
    return "\n".join(lines)


async def run_training(client_id: str, limit: int = 50, only_low: bool = False) -> dict:
    """
    Основна функція тренування.
    Повертає {"suggestions": [...], "written": N, "error": None}.
    """
    rows = await db.get_dialogs_review(client_id, limit=limit, only_low=only_low)
    if not rows:
        return {"suggestions": [], "written": 0, "error": None, "msg": "Немає діалогів для аналізу."}

    rows = _pick_worst(rows, n=10)

    dialogs_text = _format_dialogs(rows)

    current_prompt = await db.get_agent_prompt(client_id, "sales_instagram")
    if not current_prompt and _PROMPT_TEMPLATE_PATH.exists():
        current_prompt = _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
        logger.info("Trainer: prompt loaded from file (DB empty)")
    current_prompt = current_prompt or _FALLBACK_PROMPT_STUB
    analysis_prompt = _ANALYSIS_PROMPT_BASE.replace("{current_prompt}", current_prompt[:6000])

    client = AsyncAnthropic()
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=analysis_prompt,
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
    pending_count = 0
    if suggestions:
        try:
            based_on_version_id = await db.get_prompt_current_version_id(client_id, "sales_instagram")
            for s in suggestions:
                s_type = s.get("type", "")
                if s_type == "Prompt":
                    section_id = s.get("section_id", "")
                    old_text = s.get("old_text", "")
                    new_text = s.get("new_text", "")
                    if section_id and new_text:
                        reason = s.get("suggestion", s.get("problem", ""))
                        await db.save_trainer_review(
                            client_id=client_id,
                            agent_id="sales_instagram",
                            section_id=section_id,
                            old_text=old_text,
                            new_text=new_text,
                            reason=reason,
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
            logger.info("Trainer: %d пропозицій (%d pending_reviews, %d suggestions)", written, pending_count, written - pending_count)
        except Exception as e:
            logger.error("Trainer DB error: %s", e)
            return {"suggestions": suggestions, "written": 0, "error": str(e)}

    return {"suggestions": suggestions, "written": written, "pending_count": pending_count, "error": None}
