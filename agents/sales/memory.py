"""
Client memory module — компресує діалог в summary через Haiku і зберігає в dialogs.summary.
Оновлюється кожні SUMMARY_TRIGGER_THRESHOLD нових повідомлень.
"""

import anthropic
from core import db
from core.logger import get_logger

logger = get_logger(__name__)

SUMMARY_TRIGGER_THRESHOLD = 5

_MEMORY_PROMPT = """Ти — система збереження пам'яті для Sales Agent компанії з виробництва скляних виробів (двері, перегородки, душові кабіни).

Проаналізуй діалог між клієнтом і менеджером. Витягни ключові факти:
1. Продукти що обговорювались (тип, серія, розміри, кількість)
2. Ціни що називались (конкретні суми у гривнях)
3. Місто або регіон клієнта якщо згадувався
4. Статус: цікавиться / активно обговорює / замовив / відмовився / відклав
5. Ім'я клієнта якщо відоме
6. Будь-які важливі деталі (матеріал, колір, монтаж, терміни)

Відповідай коротко — максимум 200 слів, маркований список.
Якщо клієнт ще нічого не обговорював — напиши "Новий клієнт, конкретних запитів не було."
Не вигадуй деталі яких немає в діалозі."""


def _format_messages(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        role = "Клієнт" if m["role"] == "user" else "Менеджер"
        content = m["content"]
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def should_update_summary(client_id: str, user_id: str, source: str) -> bool:
    total, last_count = await db.get_summary_msg_count(client_id, user_id, source)
    return (total - last_count) >= SUMMARY_TRIGGER_THRESHOLD


async def update_summary(client_id: str, user_id: str, source: str) -> None:
    try:
        messages = await db.get_all_messages(client_id, user_id, source)
        if not messages:
            return

        dialog_text = _format_messages(messages)
        client = anthropic.AsyncAnthropic()
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=_MEMORY_PROMPT,
            messages=[{"role": "user", "content": f"Діалог:\n\n{dialog_text}"}],
        )
        summary = response.content[0].text.strip()
        cost = (response.usage.input_tokens * 0.80 + response.usage.output_tokens * 4.00) / 1_000_000

        await db.save_summary(client_id, user_id, source, summary, len(messages))
        logger.info(
            "[memory] updated summary for %s/%s/%s — %d msgs, cost=$%.5f",
            client_id, user_id, source, len(messages), cost,
        )
    except Exception as e:
        logger.error("[memory] update_summary error for %s/%s/%s: %s", client_id, user_id, source, e)
