"""
Instagram DM Agent — обробляє вхідні Direct Messages через Meta Webhooks.

Отримує DM → передає Sales Agent → відповідає через Graph API → логує у conversations.db.
Env: INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_VERIFY_TOKEN
"""

import hashlib
import hmac
import os

import httpx

from core.logger import get_logger
from core.message import AgentMessage
from core.conversation_storage import save_conversation

logger = get_logger(__name__)

_GRAPH_URL = "https://graph.facebook.com/v19.0"


def get_verify_token() -> str:
    return os.getenv("INSTAGRAM_VERIFY_TOKEN", "")


def get_access_token() -> str:
    return os.getenv("INSTAGRAM_ACCESS_TOKEN", "")


def verify_signature(payload: bytes, signature_header: str) -> bool:
    """Перевіряє X-Hub-Signature-256 від Meta."""
    app_secret = os.getenv("INSTAGRAM_APP_SECRET", "")
    if not app_secret:
        return True  # якщо секрет не заданий — пропускаємо перевірку
    expected = "sha256=" + hmac.new(
        app_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def parse_dm_events(body: dict) -> list[dict]:
    """
    Витягує DM-події з webhook payload.
    Повертає список: [{sender_id, recipient_id, text, mid}]
    """
    events = []
    for entry in body.get("entry", []):
        for msg_event in entry.get("messaging", []):
            msg = msg_event.get("message", {})
            text = msg.get("text", "").strip()
            if not text or msg.get("is_echo"):
                continue
            events.append({
                "sender_id": msg_event["sender"]["id"],
                "recipient_id": msg_event["recipient"]["id"],
                "text": text,
                "mid": msg.get("mid", ""),
            })
    return events


def send_reply(recipient_id: str, text: str) -> bool:
    """Надсилає відповідь через Instagram Graph API."""
    token = get_access_token()
    if not token:
        logger.error("INSTAGRAM_ACCESS_TOKEN не задано")
        return False
    try:
        resp = httpx.post(
            f"{_GRAPH_URL}/me/messages",
            params={"access_token": token},
            json={
                "recipient": {"id": recipient_id},
                "message": {"text": text},
                "messaging_type": "RESPONSE",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error("Instagram send_reply error: %s", resp.text)
            return False
        return True
    except Exception as e:
        logger.error("Instagram send_reply exception: %s", e)
        return False


def handle_dm(event: dict, sales_agent, history_store: dict) -> None:
    """
    Обробляє одну DM-подію:
    1. Формує контекст розмови
    2. Запускає Sales Agent
    3. Відповідає через Graph API
    4. Зберігає у conversations.db
    """
    sender_id = event["sender_id"]
    user_text = event["text"]

    # Контекст розмови (in-memory, аналогічно Telegram)
    ctx_key = f"ig_{sender_id}"
    context = history_store.get(ctx_key, [])

    message = AgentMessage(
        content=user_text,
        client_id=sales_agent.client_id,
        context=context,
        metadata={"source": "instagram", "sender_id": sender_id},
    )

    result = sales_agent.run(message)

    # Оновлюємо контекст
    context = context + [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": result.content},
    ]
    history_store[ctx_key] = context[-8:]  # sliding window 8

    # Відправляємо відповідь
    send_reply(sender_id, result.content)

    # Логуємо
    save_conversation(
        client_id=sales_agent.client_id,
        chat_id=hash(sender_id) & 0x7FFFFFFF,  # int для сумісності зі схемою
        user_msg=user_text,
        bot_reply=result.content,
        confidence=result.confidence,
        needs_human=result.needs_human,
        model_used=result.model_used,
        cost_usd=result.cost_usd,
    )

    logger.info(
        "Instagram DM handled: sender=%s conf=%.2f needs_human=%s",
        sender_id, result.confidence, result.needs_human,
    )
