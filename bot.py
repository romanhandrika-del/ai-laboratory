"""
AI Laboratory — Telegram Bot
Agent #1: Sales Agent
"""

import asyncio
import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)
from core.logger import get_logger
from core.message import AgentMessage
from core.brain_archive import GoogleSheetsBrainArchive, make_brain_record
from agents.sales.sales_agent import create_sales_agent

load_dotenv()
logger = get_logger(__name__)

# Ініціалізація агента
sales_agent = create_sales_agent()

# Brain Archive (якщо є BRAIN_SHEET_ID — логуємо, якщо ні — пропускаємо)
_brain_sheet_id = os.getenv("BRAIN_SHEET_ID")
_google_creds = os.getenv("GOOGLE_CREDENTIALS_JSON")
brain_archive = (
    GoogleSheetsBrainArchive(_brain_sheet_id, _google_creds)
    if _brain_sheet_id and _google_creds
    else None
)

# Менеджер для ескалацій
MANAGER_TELEGRAM_ID = os.getenv("MANAGER_TELEGRAM_ID")

# Conversation history: {chat_id: [messages]}
_history: dict[int, list[dict]] = {}
MAX_HISTORY = 8


def _get_history(chat_id: int) -> list[dict]:
    return _history.get(chat_id, [])


def _add_to_history(chat_id: int, role: str, content: str) -> None:
    if chat_id not in _history:
        _history[chat_id] = []
    _history[chat_id].append({"role": role, "content": content})
    # Обрізаємо до MAX_HISTORY повідомлень
    if len(_history[chat_id]) > MAX_HISTORY:
        _history[chat_id] = _history[chat_id][-MAX_HISTORY:]


async def _notify_manager(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_text: str, agent_reply: str) -> None:
    """Надсилає менеджеру резюме розмови при ескалації."""
    if not MANAGER_TELEGRAM_ID:
        return
    try:
        history = _get_history(chat_id)
        history_text = "\n".join(
            f"{'Клієнт' if m['role'] == 'user' else 'Бот'}: {m['content']}"
            for m in history[-6:]
        )
        text = (
            f"🔔 *Ескалація до менеджера*\n"
            f"Chat ID: `{chat_id}`\n\n"
            f"*Останні повідомлення:*\n{history_text}\n\n"
            f"*Останнє повідомлення клієнта:* {user_text}\n"
            f"*Відповідь бота:* {agent_reply}"
        )
        await context.bot.send_message(
            chat_id=MANAGER_TELEGRAM_ID,
            text=text,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Помилка надсилання менеджеру: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_text = update.message.text or ""

    logger.info(f"[chat={chat_id}] Вхідне: {user_text[:80]}")

    # Формуємо повідомлення для агента
    message = AgentMessage(
        content=user_text,
        client_id=sales_agent.client_id,
        context=_get_history(chat_id),
        metadata={"chat_id": chat_id, "source": "telegram"},
    )

    # Запускаємо агента
    result = sales_agent.run(message)

    # Зберігаємо в history
    _add_to_history(chat_id, "user", user_text)
    _add_to_history(chat_id, "assistant", result.content)

    # Відповідаємо клієнту
    await update.message.reply_text(result.content)

    logger.info(
        f"[chat={chat_id}] confidence={result.confidence:.2f} "
        f"needs_human={result.needs_human} cost=${result.cost_usd:.4f}"
    )

    # Ескалація до менеджера
    if result.needs_human:
        await _notify_manager(context, chat_id, user_text, result.content)

    # Логуємо в Brain Archive
    if brain_archive:
        try:
            record = make_brain_record(
                result=result,
                task=user_text[:100],
                sentiment="neutral",
                prompt_version=sales_agent.prompt_version,
            )
            brain_archive.write(record)
        except Exception as e:
            logger.error(f"Brain Archive помилка: {e}")


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привіт! 👋 Я консультант компанії. Розкажіть що плануєте — підберемо рішення 🙂"
    )


async def handle_reload_kb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /reload_kb — оновлює Knowledge Base з Google Sheets."""
    chat_id = update.effective_chat.id
    if str(chat_id) != MANAGER_TELEGRAM_ID:
        return
    sales_agent.reload_kb()
    await update.message.reply_text("✅ Knowledge Base оновлена")


async def handle_yt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Команда /yt <url> — аналізує YouTube відео та повертає ключові тези.

    Доступна тільки менеджеру. Приклад:
        /yt https://www.youtube.com/watch?v=VIDEO_ID
    """
    chat_id = update.effective_chat.id
    if str(chat_id) != MANAGER_TELEGRAM_ID:
        return

    url = " ".join(context.args).strip() if context.args else ""
    if not url:
        await update.message.reply_text("❌ Вкажи URL відео:\n/yt https://youtube.com/watch?v=...")
        return

    status_msg = await update.message.reply_text("⏳ Отримую транскрипцію...")

    try:
        from agents.youtube_agent.transcript import get_video_id, get_transcript
        from agents.youtube_agent.summarizer import summarize, format_telegram_message

        video_id = get_video_id(url)
        transcript_data = await asyncio.to_thread(get_transcript, video_id)

        await status_msg.edit_text("🧠 Аналізую через Claude...")

        summary = await asyncio.to_thread(summarize, transcript_data["text"], url)
        message = format_telegram_message(title=f"Відео {video_id}", url=url, summary=summary)

        await status_msg.edit_text(message, parse_mode="HTML")
        logger.info(f"[/yt] Оброблено відео {video_id}")

    except ValueError as e:
        await status_msg.edit_text(f"❌ {e}")
    except Exception as e:
        logger.error(f"[/yt] Помилка: {e}")
        await status_msg.edit_text(f"❌ Помилка при обробці відео: {e}")


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN не знайдено в .env")

    webhook_url = os.getenv("WEBHOOK_URL", "").strip()

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("reload_kb", handle_reload_kb))
    app.add_handler(CommandHandler("yt", handle_yt))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if webhook_url:
        # Продакшн (Railway) — webhook режим, без конфліктів при деплої
        port = int(os.getenv("PORT", "8080"))
        logger.info("🤖 AI Laboratory Bot запущено (webhook: %s)", webhook_url)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=f"{webhook_url}/webhook",
            drop_pending_updates=True,
        )
    else:
        # Локальна розробка — polling
        logger.info("🤖 AI Laboratory Bot запущено (polling)")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
