"""
Daily analyzer for the orchestrator prompt.
Loads last N hours of manager dialogs, sends to Claude Sonnet,
proposes issues + improved prompt, saves to orchestrator_pending_review.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from anthropic import AsyncAnthropic
from core import db

logger = logging.getLogger(__name__)
_anthropic = AsyncAnthropic()

SYSTEM_PROMPT = """\
Ти — analyzer діалогів оркестранта AI Laboratory.

═══════════════════════════════════════
ЗОЛОТІ ПРАВИЛА (НЕЗМІННІ — НЕ ВИДАЛЯТИ, НЕ ПОСЛАБЛЮВАТИ)
═══════════════════════════════════════
У будь-якій новій версії промпту ОБОВ'ЯЗКОВО збережені:
1. Мова відповіді: українська.
2. Правила підтвердження деструктивних дій (push/rollback): не послаблювати.
3. Список доступних інструментів та їх назви — не перейменовувати.
4. Правила ескалації до менеджера — зберегти повністю.
5. Заборона виконувати дії без явного підтвердження — не послаблювати.
═══════════════════════════════════════

ТВОЄ ЗАВДАННЯ:
Тобі дають поточний system prompt оркестранта + діалоги менеджера за останні N годин.
Знайди проблеми: де оркестрант не зрозумів intent, обрав не той інструмент,
дав невірну відповідь, зациклився, галюцинував.
Запропонуй ВИПРАВЛЕНИЙ промпт — зміни лише:
  • стиль і формулювання відповідей менеджеру
  • розпізнавання інтентів і контексту задач
  • приклади / few-shot патерни
НЕ ЗМІНЮЙ: технічні назви інструментів, Золоті правила вище.

ФОРМАТ ВІДПОВІДІ — тільки валідний JSON, без markdown-обгортки:
{
  "issues": ["короткий опис проблеми 1", ...],
  "change_log": ["Додано правило X", "Скорочено фразу Y", ...],
  "new_prompt": "повний текст нового промпту"
}
"""


def _get_manager_id() -> str:
    return os.environ.get("MANAGER_TELEGRAM_ID", "")


def _filter_by_hours(messages: list, hours: int) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = []
    for m in messages:
        ts_raw = m.get("ts", "")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(ts_raw)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                result.append(m)
        except ValueError:
            pass
    return result


def _format_messages(messages: list) -> str:
    return "\n".join(
        f"  {m['role']}: {str(m.get('content', ''))[:400]}"
        for m in messages
    )


async def analyze(client_id: str, hours: int = 24) -> dict:
    """
    Analyzes recent manager dialogs and proposes an improved orchestrator prompt.
    Returns dict with keys: issues, change_log, new_prompt, dialogs_count
    OR {"skip": True, "reason": "..."} if nothing to analyze.
    """
    now = datetime.now(timezone.utc)
    dialogs_from = now - timedelta(hours=hours)
    dialogs_to = now

    manager_id = _get_manager_id()
    if not manager_id:
        return {"skip": True, "reason": "MANAGER_TELEGRAM_ID not set"}

    all_msgs = await db.load_history(client_id, manager_id, "telegram", limit=100)
    recent_msgs = _filter_by_hours(all_msgs, hours)
    if not recent_msgs:
        return {"skip": True, "reason": f"no manager messages in the last {hours}h"}

    current_prompt = await db.get_agent_prompt(client_id, "orchestrator")
    if not current_prompt:
        return {"skip": True, "reason": "no orchestrator prompt in DB yet (auto-seed runs on next restart)"}

    dialogs_text = _format_messages(recent_msgs)
    user_content = (
        f"=== Поточний промпт оркестранта ===\n{current_prompt}\n\n"
        f"=== Діалоги менеджера ({len(recent_msgs)} повідомлень за {hours}h) ===\n"
        f"{dialogs_text}"
    )

    resp = await _anthropic.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    parsed = json.loads(raw)

    pending_id = await db.save_pending_review(
        client_id=client_id,
        issues=json.dumps(parsed["issues"], ensure_ascii=False),
        new_prompt=parsed["new_prompt"],
        change_log=json.dumps(parsed.get("change_log", []), ensure_ascii=False),
        dialogs_count=len(recent_msgs),
        dialogs_from=dialogs_from,
        dialogs_to=dialogs_to,
    )
    logger.info("[analyzer] pending_review saved id=%s, issues=%d", pending_id, len(parsed["issues"]))

    return {
        "pending_id": pending_id,
        "issues": parsed["issues"],
        "change_log": parsed.get("change_log", []),
        "new_prompt": parsed["new_prompt"],
        "dialogs_count": len(recent_msgs),
    }
