"""
Instagram DM Agent — інтеграція через Sendrules webhook.

Sendrules отримує Instagram/Facebook DM → POST /instagram/webhook →
Sales Agent відповідає → {"reply": "..."} → Sendrules надсилає відповідь клієнту.

Webhook payload (від Sendrules):
  {user_id, message, source, name, file_url?, file_type?}
Header: X-Webhook-Secret: <WEBHOOK_SECRET>
"""

import os
from core.logger import get_logger
from core.message import AgentMessage
from core.conversation_storage import save_conversation

logger = get_logger(__name__)

_history: dict[str, list[dict]] = {}
MAX_HISTORY = 20


def verify_secret(secret_header: str | None) -> bool:
    expected = os.getenv("WEBHOOK_SECRET", "")
    if not expected:
        return True
    return secret_header == expected


def handle_message(
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
    if user_id not in _history:
        if len(_history) >= 1000:
            del _history[next(iter(_history))]
        _history[user_id] = []

    context = _history[user_id]
    context.append({"role": "user", "content": message})
    if len(context) > MAX_HISTORY:
        context = context[-MAX_HISTORY:]
        _history[user_id] = context

    result = sales_agent.run(AgentMessage(
        content=message,
        client_id=sales_agent.client_id,
        context=context[:-1],
        metadata={"source": source, "user_id": user_id, "name": name},
    ))

    context.append({"role": "assistant", "content": result.content})

    save_conversation(
        client_id=sales_agent.client_id,
        chat_id=hash(user_id) & 0x7FFFFFFF,
        user_msg=message,
        bot_reply=result.content,
        confidence=result.confidence,
        needs_human=result.needs_human,
        model_used=result.model_used,
        cost_usd=result.cost_usd,
    )

    logger.info("[%s] %s conf=%.2f needs_human=%s", source, name, result.confidence, result.needs_human)
    return result.content
