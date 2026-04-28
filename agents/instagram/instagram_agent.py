"""
Instagram DM Agent — інтеграція через Sendrules webhook.

Sendrules отримує Instagram/Facebook DM → POST /instagram/webhook →
Sales Agent відповідає → {"reply": "..."} → Sendrules надсилає відповідь клієнту.

Webhook payload (від Sendrules):
  {user_id, message, source, name, file_url?, file_type?}
Header: X-Webhook-Secret: <WEBHOOK_SECRET>
"""

import asyncio
import os
from core import db
from core.logger import get_logger
from core.message import AgentMessage

logger = get_logger(__name__)

MAX_HISTORY = 20


def verify_secret(secret_header: str | None) -> bool:
    expected = os.getenv("WEBHOOK_SECRET", "")
    if not expected:
        return True
    return secret_header == expected


async def handle_message(
    user_id: str,
    message: str,
    source: str,
    name: str,
    sales_agent,
) -> str:
    """
    Обробляє вхідне DM від Sendrules.
    Повертає reply рядок для відправки назад клієнту.
    """
    from agents.sales.memory import should_update_summary, update_summary
    client_id = sales_agent.client_id
    context = await db.load_history(client_id, user_id, source, limit=MAX_HISTORY)
    summary = await db.get_summary(client_id, user_id, source)

    result = sales_agent.run(AgentMessage(
        content=message,
        client_id=client_id,
        context=context,
        metadata={"source": source, "user_id": user_id, "name": name, "client_memory": summary},
    ))

    await db.save_message(client_id, user_id, source, "user", message)
    await db.save_message(
        client_id, user_id, source, "assistant", result.content,
        meta={
            "confidence": result.confidence,
            "needs_human": result.needs_human,
            "model_used": result.model_used,
            "cost_usd": result.cost_usd,
        },
    )

    logger.info("[%s] %s conf=%.2f needs_human=%s", source, name, result.confidence, result.needs_human)
    if await should_update_summary(client_id, user_id, source):
        asyncio.create_task(update_summary(client_id, user_id, source))
    return result.content
