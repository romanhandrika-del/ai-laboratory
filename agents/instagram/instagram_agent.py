"""
Instagram DM Agent — інтеграція через SendPulse chatbot webhooks.

Флоу: SendPulse webhook → parse → Sales Agent → SendPulse API reply → conversations.db
Env: SENDPULSE_CLIENT_ID, SENDPULSE_CLIENT_SECRET
"""

import os
import time

import httpx

from core.logger import get_logger
from core.message import AgentMessage
from core.conversation_storage import save_conversation

logger = get_logger(__name__)

_SP_BASE = "https://api.sendpulse.com"
_TOKEN_URL = f"{_SP_BASE}/oauth/access_token"
_SEND_URL = f"{_SP_BASE}/instagram/contacts/send"

# Кеш токену: (access_token, expires_at)
_token_cache: tuple[str, float] = ("", 0.0)


def _get_access_token() -> str:
    global _token_cache
    token, expires_at = _token_cache
    if token and time.time() < expires_at - 60:
        return token
    resp = httpx.post(
        _TOKEN_URL,
        json={
            "grant_type": "client_credentials",
            "client_id": os.getenv("SENDPULSE_CLIENT_ID", ""),
            "client_secret": os.getenv("SENDPULSE_CLIENT_SECRET", ""),
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    expires_at = time.time() + int(data.get("expires_in", 3600))
    _token_cache = (token, expires_at)
    return token


def parse_dm_events(body: dict) -> list[dict]:
    """
    Парсить SendPulse webhook payload.
    Повертає список: [{contact_id, sender_id, text}]

    SendPulse надсилає або один об'єкт або список.
    """
    events = []
    items = body if isinstance(body, list) else [body]
    for item in items:
        if item.get("service") != "instagram":
            continue
        if item.get("title") != "incoming_message":
            continue
        info = item.get("info", {})
        msg_text = (
            info.get("message", {}).get("text", "")
            or info.get("text", "")
        ).strip()
        contact_id = (
            info.get("contact", {}).get("id", "")
            or info.get("contact_id", "")
        )
        sender_id = contact_id  # для логування
        if msg_text and contact_id:
            events.append({
                "contact_id": contact_id,
                "sender_id": sender_id,
                "text": msg_text,
            })
    return events


def send_reply(contact_id: str, text: str) -> bool:
    """Надсилає відповідь через SendPulse Instagram API."""
    try:
        token = _get_access_token()
    except Exception as e:
        logger.error("SendPulse token error: %s", e)
        return False
    try:
        resp = httpx.post(
            _SEND_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "contact_id": contact_id,
                "messages": [{"type": "text", "message": {"text": text}}],
            },
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error("SendPulse send_reply error %d: %s", resp.status_code, resp.text)
            return False
        return True
    except Exception as e:
        logger.error("SendPulse send_reply exception: %s", e)
        return False


def handle_dm(event: dict, sales_agent, history_store: dict) -> None:
    """
    Обробляє одну DM-подію:
    1. Формує контекст розмови
    2. Запускає Sales Agent
    3. Відповідає через SendPulse API
    4. Зберігає у conversations.db
    """
    contact_id = event["contact_id"]
    user_text = event["text"]

    ctx_key = f"ig_{contact_id}"
    context = history_store.get(ctx_key, [])

    message = AgentMessage(
        content=user_text,
        client_id=sales_agent.client_id,
        context=context,
        metadata={"source": "instagram", "contact_id": contact_id},
    )

    result = sales_agent.run(message)

    history_store[ctx_key] = (context + [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": result.content},
    ])[-8:]

    send_reply(contact_id, result.content)

    save_conversation(
        client_id=sales_agent.client_id,
        chat_id=hash(contact_id) & 0x7FFFFFFF,
        user_msg=user_text,
        bot_reply=result.content,
        confidence=result.confidence,
        needs_human=result.needs_human,
        model_used=result.model_used,
        cost_usd=result.cost_usd,
    )

    logger.info(
        "Instagram DM [SendPulse]: contact=%s conf=%.2f needs_human=%s",
        contact_id, result.confidence, result.needs_human,
    )
