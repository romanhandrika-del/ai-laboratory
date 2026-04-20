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
from core.conversation_storage import init_db as init_conv_db, save_conversation, get_review, get_stats
from agents.sales.sales_agent import create_sales_agent
from agents.website_audit.website_audit_agent import WebsiteAuditAgent
from agents.website_fix.website_fix_agent import WebsiteFixAgent
from agents.web_design.web_design_agent import WebDesignAgent

load_dotenv()
logger = get_logger(__name__)

init_conv_db()

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

    # Логуємо розмову в SQLite
    save_conversation(
        client_id=sales_agent.client_id,
        chat_id=chat_id,
        user_msg=user_text,
        bot_reply=result.content,
        confidence=result.confidence,
        needs_human=result.needs_human,
        model_used=result.model_used,
        cost_usd=result.cost_usd,
    )

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


async def handle_audit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /audit <url> — запускає Website Audit Agent."""
    chat_id = update.effective_chat.id
    if str(chat_id) != MANAGER_TELEGRAM_ID:
        await update.message.reply_text("⛔ Доступ заборонено")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Використання: /audit https://example.com")
        return

    url = args[0].strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    await update.message.reply_text(f"⏳ Аналізую сайт: {url}\nЦе займе ~30-90 секунд...")

    agent = WebsiteAuditAgent(client_id="default")
    result = await agent.audit(url)

    if result.get("error"):
        await update.message.reply_text(f"❌ Помилка аудиту:\n{result['error']}")
        return

    await update.message.reply_html(result["summary_text"])

    report_path = result.get("report_md_path")
    if report_path:
        from pathlib import Path
        p = Path(report_path)
        if p.exists():
            with open(p, "rb") as f:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename=p.name,
                    caption="📋 Повний звіт аудиту",
                )



async def handle_push(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /push <url> — заливає fix-пакет на сервер через FTP."""
    chat_id = update.effective_chat.id
    if str(chat_id) != MANAGER_TELEGRAM_ID:
        await update.message.reply_text("⛔ Доступ заборонено")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Використання: /push https://example.com")
        return

    url = args[0].strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    await update.message.reply_text(f"📤 Заливаю fix-пакет на сервер: {url}...")

    agent = WebsiteFixAgent(client_id="default")
    result = await agent.push(url)

    if result.get("error"):
        await update.message.reply_text(f"❌ Помилка:\n{result['error']}")
        return

    await update.message.reply_html(result["summary_text"])


async def handle_rollback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /rollback <url> — відновлює попередню версію mu-plugin з backup."""
    chat_id = update.effective_chat.id
    if str(chat_id) != MANAGER_TELEGRAM_ID:
        await update.message.reply_text("⛔ Доступ заборонено")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Використання: /rollback https://example.com")
        return

    url = args[0].strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    await update.message.reply_text(f"↩️ Виконую rollback для: {url}...")

    agent = WebsiteFixAgent(client_id="default")
    result = await agent.rollback(url)

    if result.get("error"):
        await update.message.reply_text(f"❌ Помилка:\n{result['error']}")
        return

    await update.message.reply_html(result["summary_text"])


async def handle_fix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /fix <url> — генерує пакет SEO-фіксів."""
    chat_id = update.effective_chat.id
    if str(chat_id) != MANAGER_TELEGRAM_ID:
        await update.message.reply_text("⛔ Доступ заборонено")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Використання: /fix https://example.com")
        return

    url = args[0].strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    await update.message.reply_text(f"⏳ Генерую SEO-фікси для: {url}\nЦе займе ~30-60 секунд...")

    agent = WebsiteFixAgent(client_id="default")
    result = await agent.fix(url)

    if result.get("error"):
        await update.message.reply_text(f"❌ Помилка:\n{result['error']}")
        return

    await update.message.reply_html(result["summary_text"])

    fix_path = result.get("fix_md_path")
    if fix_path:
        from pathlib import Path
        p = Path(fix_path)
        if p.exists():
            with open(p, "rb") as f:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename=p.name,
                    caption="🔧 Пакет фіксів (File/Selector/Search/Replace)",
                )


async def handle_design(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /design <url> або /design brief: <текст> — генерує дизайн-пакет."""
    chat_id = update.effective_chat.id
    if str(chat_id) != MANAGER_TELEGRAM_ID:
        await update.message.reply_text("⛔ Доступ заборонено")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Використання:\n"
            "  /design https://example.com\n"
            "  /design brief: лендінг для кав'ярні у Львові"
        )
        return

    input_text = " ".join(args).strip()
    if not input_text.startswith(("http://", "https://", "brief:")):
        input_text = "https://" + input_text

    mode_label = "сайту" if input_text.startswith("http") else "брифу"
    await update.message.reply_text(f"⏳ Генерую дизайн-пакет для {mode_label}...\nЦе займе ~60-120 секунд.")

    agent = WebDesignAgent(client_id="default")
    result = await agent.design(input_text)

    if result.get("error"):
        await update.message.reply_text(f"❌ Помилка:\n{result['error']}")
        return

    await update.message.reply_html(result["summary_text"])

    for file_key, caption in [("brief_path", "📋 Дизайн-бриф"), ("mockup_path", "🎨 HTML/CSS макет")]:
        file_path = result.get(file_key)
        if file_path:
            from pathlib import Path
            p = Path(file_path)
            if p.exists():
                with open(p, "rb") as f:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename=p.name,
                        caption=caption,
                    )


async def handle_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /review [low] — показує останні розмови Sales Agent."""
    chat_id = update.effective_chat.id
    if str(chat_id) != MANAGER_TELEGRAM_ID:
        await update.message.reply_text("⛔ Доступ заборонено")
        return

    only_low = "low" in (context.args or [])
    stats = get_stats(sales_agent.client_id)
    rows = get_review(sales_agent.client_id, limit=10, only_low=only_low)

    header = (
        f"📊 <b>Sales Agent — огляд розмов</b>\n"
        f"Всього: {stats.get('total', 0)} | "
        f"Avg confidence: {stats.get('avg_confidence', 0)} | "
        f"Ескалацій: {stats.get('escalations', 0)} | "
        f"Витрати: ${stats.get('total_cost', 0)}\n"
    )
    if only_low:
        header += "⚠️ <i>Тільки низька впевненість / ескалації</i>\n"
    header += "─" * 30 + "\n"

    if not rows:
        await update.message.reply_html(header + "Розмов поки немає.")
        return

    lines = [header]
    for r in rows:
        flag = "🔴" if r["needs_human"] else ("🟡" if r["confidence"] < 0.75 else "🟢")
        ts = r["created_at"][:16].replace("T", " ")
        lines.append(
            f"{flag} <b>{ts}</b> | conf: {r['confidence']:.2f}\n"
            f"👤 {r['user_msg'][:80]}\n"
            f"🤖 {r['bot_reply'][:120]}\n"
        )

    text = "\n".join(lines)
    # Telegram обмежує ~4096 символів
    if len(text) > 4000:
        text = text[:3950] + "\n<i>...обрізано</i>"

    await update.message.reply_html(text)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN не знайдено в .env")

    webhook_url = os.getenv("WEBHOOK_URL", "").strip()

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("reload_kb", handle_reload_kb))
    app.add_handler(CommandHandler("review", handle_review))
    app.add_handler(CommandHandler("audit", handle_audit))
    app.add_handler(CommandHandler("fix", handle_fix))
    app.add_handler(CommandHandler("push", handle_push))
    app.add_handler(CommandHandler("rollback", handle_rollback))
    app.add_handler(CommandHandler("design", handle_design))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if webhook_url:
        # Продакшн (Railway) — webhook режим, без конфліктів при деплої
        port = int(os.getenv("PORT", "8080"))
        logger.info("🤖 AI Laboratory Bot запущено (webhook: %s)", webhook_url)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="/webhook",
            webhook_url=f"{webhook_url}/webhook",
            drop_pending_updates=True,
        )
    else:
        # Локальна розробка — polling
        logger.info("🤖 AI Laboratory Bot запущено (polling)")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
