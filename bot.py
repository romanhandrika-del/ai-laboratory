"""
AI Laboratory — Telegram Bot
Agent #1: Sales Agent
"""

import asyncio
import json
import os
import logging
from dotenv import load_dotenv
from aiohttp import web
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)
from core import db
from core.logger import get_logger
from core.message import AgentMessage
from core.brain_archive import GoogleSheetsBrainArchive, make_brain_record
from agents.sales.sales_agent import create_sales_agent
from core.orchestrator import OrchestratorAgent
from agents.website_audit.website_audit_agent import WebsiteAuditAgent
from agents.website_fix.website_fix_agent import WebsiteFixAgent
from agents.web_design.web_design_agent import WebDesignAgent
from agents.multimodal_analyst.multimodal_agent import MultimodalAnalystAgent
from agents.instagram.instagram_agent import verify_secret, handle_message as ig_handle_message

load_dotenv()
logger = get_logger(__name__)

# Ініціалізація агентів
sales_agent = create_sales_agent()
orchestrator = OrchestratorAgent(client_id=sales_agent.client_id, sales_agent=sales_agent)

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
ARCHIVE_CHANNEL_ID = os.getenv("ARCHIVE_CHANNEL_ID", "")

TG_HISTORY_LIMIT = 8


async def _notify_manager(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_text: str,
    agent_reply: str,
    history: list[dict],
) -> None:
    """Надсилає менеджеру резюме розмови при ескалації."""
    if not MANAGER_TELEGRAM_ID:
        return
    try:
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


_HEAVY_KEYWORDS = (
    "аудит", "audit", "фікс", "fix", "push", "деплой", "дизайн", "design",
    "rollback", "відкат", "pipeline", "під ключ", "аутсорс", "повний цикл",
)


def _is_heavy_request(text: str, is_manager: bool) -> bool:
    if not is_manager:
        return False
    t = text.lower()
    return any(k in t for k in _HEAVY_KEYWORDS)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    chat_id = update.effective_chat.id
    user_text = (update.message.text or update.message.caption or "").strip()
    if not user_text:
        return

    logger.info(f"[chat={chat_id}] Вхідне: {user_text[:80]}")

    is_manager = bool(MANAGER_TELEGRAM_ID and str(chat_id) == str(MANAGER_TELEGRAM_ID))

    # Trainer approval: перехоплюємо "так/ні/diff" якщо є pending review
    if is_manager:
        pending = await db.get_pending_review(sales_agent.client_id)
        if pending:
            from core.orchestrator import invalidate_orchestrator_prompt_cache
            cmd = user_text.strip().lower()
            if cmd in ("так", "yes", "ок", "затверди"):
                v = await db.save_agent_prompt(
                    sales_agent.client_id, "orchestrator",
                    pending["new_prompt"], "auto-trainer",
                )
                await db.clear_pending_review(sales_agent.client_id)
                invalidate_orchestrator_prompt_cache()
                await update.message.reply_text(f"✅ Промпт оновлено до версії {v}")
                return
            elif cmd in ("ні", "no", "пропусти", "skip"):
                await db.clear_pending_review(sales_agent.client_id)
                await update.message.reply_text("Пропущено. Промпт без змін.")
                return
            elif cmd in ("diff", "деталі"):
                try:
                    issues_list = json.loads(pending["issues_summary"])
                    cl_list = json.loads(pending["change_log"])
                except Exception:
                    issues_list = [pending["issues_summary"]]
                    cl_list = []
                current = await db.get_agent_prompt(sales_agent.client_id, "orchestrator") or ""
                issues_text = "\n".join(f"• {i}" for i in issues_list[:5])
                cl_text = "\n".join(f"• {c}" for c in cl_list[:5])
                msg = (
                    f"<b>Знайдені проблеми:</b>\n{issues_text}\n\n"
                    f"<b>Зміни:</b>\n{cl_text}\n\n"
                    f"<b>Було (початок):</b>\n<code>{current[:400]}</code>\n\n"
                    f"<b>Стане (початок):</b>\n<code>{pending['new_prompt'][:400]}</code>"
                )
                await update.message.reply_html(msg)
                return

    if _is_heavy_request(user_text, is_manager):
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    result = await orchestrator.route(
        user_text=user_text,
        user_id=str(chat_id),
        source="telegram",
        is_manager=is_manager,
    )

    is_sales = result.agent_id.startswith("sales")
    await db.save_message(sales_agent.client_id, str(chat_id), "telegram", "user", user_text)
    await db.save_message(
        sales_agent.client_id, str(chat_id), "telegram", "assistant", result.content,
        meta={
            "agent_id": result.agent_id,
            "confidence": result.confidence,
            "needs_human": result.needs_human,
            "model_used": result.model_used,
            "cost_usd": result.cost_usd,
        },
    )

    if is_sales:
        await update.message.reply_text(result.content)
    else:
        await update.message.reply_html(result.content)

    logger.info(
        f"[chat={chat_id}] agent={result.agent_id} confidence={result.confidence:.2f} "
        f"needs_human={result.needs_human} cost=${result.cost_usd:.4f}"
    )

    if result.needs_human:
        history = await db.load_history(sales_agent.client_id, str(chat_id), "telegram", limit=6)
        await _notify_manager(context, chat_id, user_text, result.content, history)

    if brain_archive and is_sales:
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


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Голосові повідомлення Telegram → Whisper → Sales Agent."""
    if not update.message:
        return
    chat_id = update.effective_chat.id
    voice = update.message.voice

    try:
        tg_file = await context.bot.get_file(voice.file_id)
        audio_bytes = await tg_file.download_as_bytearray()
    except Exception as e:
        logger.error("Помилка завантаження голосового: %s", e)
        await update.message.reply_text("Не вдалося отримати голосове. Спробуйте текстом 🙂")
        return

    from agents.instagram.speech import transcribe_audio
    user_text = await transcribe_audio(bytes(audio_bytes), "audio/ogg")

    if not user_text:
        await update.message.reply_text(
            "Не вдалося розпізнати голосове 🙂 Напишіть текстом — відповімо одразу."
        )
        return

    logger.info("[chat=%d] Голосове розпізнано: %s", chat_id, user_text[:80])

    result = await orchestrator.route(
        user_text=user_text,
        user_id=str(chat_id),
        source="telegram_voice",
        is_manager=bool(MANAGER_TELEGRAM_ID and str(chat_id) == str(MANAGER_TELEGRAM_ID)),
    )

    is_sales = result.agent_id.startswith("sales")
    if is_sales:
        await db.save_message(sales_agent.client_id, str(chat_id), "telegram", "user", f"[voice] {user_text}")
        await db.save_message(
            sales_agent.client_id, str(chat_id), "telegram", "assistant", result.content,
            meta={
                "confidence": result.confidence,
                "needs_human": result.needs_human,
                "model_used": result.model_used,
                "cost_usd": result.cost_usd,
            },
        )

    await update.message.reply_text(result.content)

    if result.needs_human:
        history = await db.load_history(sales_agent.client_id, str(chat_id), "telegram", limit=6)
        await _notify_manager(context, chat_id, user_text, result.content, history)


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

    # Очищаємо session_state щоб не конфліктував з orchestrator-діалогом
    await db.clear_session_state(sales_agent.client_id, str(chat_id), "telegram")

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


async def handle_train(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /train [low] — аналізує діалоги і пише пропозиції в Google Sheets."""
    chat_id = update.effective_chat.id
    if str(chat_id) != MANAGER_TELEGRAM_ID:
        await update.message.reply_text("⛔ Доступ заборонено")
        return

    only_low = "low" in (context.args or [])
    await update.message.reply_text("⏳ Аналізую діалоги...")

    from agents.sales.trainer import run_training
    result = await run_training(sales_agent.client_id, 30, only_low)

    if result.get("error"):
        await update.message.reply_text(f"❌ Помилка тренування:\n{result['error']}")
        return

    suggestions = result.get("suggestions", [])
    written = result.get("written", 0)

    if not suggestions:
        await update.message.reply_text(result.get("msg", "✅ Все добре — пропозицій немає."))
        return

    lines = [f"🧠 <b>Тренування завершено</b>\nЗаписано у Sheets: {written} пропозицій\n"]
    for i, s in enumerate(suggestions[:8], 1):
        prio = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(s.get("priority", ""), "⚪")
        lines.append(
            f"{prio} <b>{s.get('type', '')} — {s.get('priority', '')}</b>\n"
            f"Проблема: {s.get('problem', '')}\n"
            f"Пропозиція: {s.get('suggestion', '')}\n"
        )
    if len(suggestions) > 8:
        lines.append(f"<i>...та ще {len(suggestions) - 8} пропозицій у Sheets</i>")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n<i>...обрізано</i>"
    await update.message.reply_html(text)


async def handle_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /review [low] — показує останні розмови Sales Agent."""
    chat_id = update.effective_chat.id
    if str(chat_id) != MANAGER_TELEGRAM_ID:
        await update.message.reply_text("⛔ Доступ заборонено")
        return

    only_low = "low" in (context.args or [])
    stats = await db.get_dialogs_stats(sales_agent.client_id)
    rows = await db.get_dialogs_review(sales_agent.client_id, limit=10, only_low=only_low)

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


async def _archive_file(context: ContextTypes.DEFAULT_TYPE, msg) -> tuple[str, int]:
    """Пересилає фото/документ у Archive Channel. Повертає (file_id, message_id)."""
    if not ARCHIVE_CHANNEL_ID:
        return "", 0
    try:
        if msg.photo:
            sent = await context.bot.send_photo(
                chat_id=ARCHIVE_CHANNEL_ID,
                photo=msg.photo[-1].file_id,
                caption=f"📥 Аналіз | chat={msg.chat_id} | {msg.date.isoformat()}",
            )
            return sent.photo[-1].file_id, sent.message_id
        elif msg.document:
            sent = await context.bot.send_document(
                chat_id=ARCHIVE_CHANNEL_ID,
                document=msg.document.file_id,
                caption=f"📥 Аналіз | chat={msg.chat_id} | {msg.date.isoformat()}",
            )
            return sent.document.file_id, sent.message_id
    except Exception as e:
        logger.error("Archive Channel forward помилка: %s", e)
    return "", 0


async def handle_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /analyze або фото/документ з caption /analyze — Multimodal Analyst."""
    if update.message is None:
        return
    chat_id = update.effective_chat.id
    if str(chat_id) != MANAGER_TELEGRAM_ID:
        await update.message.reply_text("⛔ Доступ заборонено")
        return

    msg = update.message
    photo = msg.photo
    document = msg.document
    caption = (msg.text or msg.caption or "").strip()

    # Парсимо override з caption: /analyze pricelist або /analyze ad
    override_kind = ""
    for word in caption.lower().split():
        if word in ("pricelist", "ad", "realty", "analytics"):
            override_kind = word
            break

    if not photo and not document:
        await msg.reply_text(
            "Надішліть фото або PDF разом з командою /analyze.\n"
            "Приклади:\n"
            "  • /analyze (авто-визначення типу)\n"
            "  • /analyze pricelist (для прайс-листу)\n"
            "  • /analyze ad (для реклами)\n"
            "  • /analyze realty (для нерухомості)\n"
            "  • /analyze analytics (для дашборду)"
        )
        return

    await msg.reply_text("⏳ Аналізую файл... (~15-30 секунд)")

    # 1. Архівуємо оригінал у канал-архів (паралельно з завантаженням)
    archive_task = asyncio.create_task(_archive_file(context, msg))

    try:
        if photo:
            tg_file = await context.bot.get_file(photo[-1].file_id)
            file_bytes = bytes(await tg_file.download_as_bytearray())
            media_type = "image/jpeg"
        else:
            tg_file = await context.bot.get_file(document.file_id)
            file_bytes = bytes(await tg_file.download_as_bytearray())
            mime = document.mime_type or ""
            media_type = mime if mime else "application/octet-stream"
    except Exception as e:
        logger.error("handle_analyze: завантаження файлу: %s", e)
        await msg.reply_text("❌ Не вдалося завантажити файл. Спробуйте ще раз.")
        archive_task.cancel()
        return

    source_tg_file_id, source_tg_msg_id = await archive_task

    # 2. Аналізуємо
    agent = MultimodalAnalystAgent(client_id="default")
    result = await agent.analyze(
        file_bytes, media_type, override_kind,
        source_tg_file_id=source_tg_file_id,
        source_tg_msg_id=source_tg_msg_id,
    )

    if result.get("error"):
        await msg.reply_text(f"❌ {result['error']}")
        return

    # 3. Відповідь менеджеру
    await msg.reply_html(result["summary_html"])

    report_md = result.get("report_md", "")
    if report_md:
        import io
        await context.bot.send_document(
            chat_id=chat_id,
            document=io.BytesIO(report_md.encode()),
            filename=f"analysis-{result.get('kind','report').lower().replace(' ','_')}.md",
            caption="📊 Повний звіт Multimodal Analyst",
        )

    # Підказка при низькій впевненості
    if result.get("confidence") == "низька":
        await msg.reply_text(
            "💡 Якщо тип визначено невірно — надішліть файл знову з caption:\n"
            "`/analyze pricelist` · `/analyze ad` · `/analyze realty` · `/analyze analytics`",
            parse_mode="Markdown",
        )


async def _ig_webhook_receive(request: web.Request) -> web.Response:
    """POST /instagram/webhook — вхідні DM від Sendrules."""
    secret = request.headers.get("X-Webhook-Secret")
    if not verify_secret(secret):
        return web.Response(status=403)
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400)

    # Логуємо повний сирий payload — щоб побачити що SendPulse надсилає для фото
    import json as _json
    logger.warning("IG RAW PAYLOAD: %s", _json.dumps(body, ensure_ascii=False)[:1000])

    user_id = body.get("user_id", "")
    message = body.get("message", "").strip()
    source = body.get("source", "instagram")
    name = body.get("name", "Клієнт")
    file_url = body.get("file_url")
    file_type = body.get("file_type")

    # Логуємо сирий payload для діагностики типів файлів
    logger.info("IG webhook payload: user=%s file_url=%s file_type=%s message=%s",
                user_id, file_url, file_type, message[:50] if message else "")

    if not user_id:
        return web.json_response({"reply": ""})

    try:
        # Якщо прийшло фото/PDF — обробляємо через Claude Vision + Google OCR
        # file_url може прийти як {{last_message}} — перевіряємо що це справжній URL
        if file_url and file_url.startswith("http") and file_type != "text":
            from agents.instagram.file_handler import handle_file_url
            from agents.instagram.instagram_agent import MAX_HISTORY
            context = await db.load_history(sales_agent.client_id, user_id, source, limit=MAX_HISTORY)
            reply = await handle_file_url(
                file_url, file_type, context, sales_agent.system_prompt
            )
            if file_type in ("audio", "voice"):
                label = "[voice]"
            elif file_type == "pdf":
                label = "[pdf]"
            else:
                label = "[photo]"
            ctx_msg = f"{label} {message}".strip() if message else label
            needs_human = "[NOTIFY_MANAGER]" in reply
            await db.save_message(sales_agent.client_id, user_id, source, "user", ctx_msg)
            await db.save_message(
                sales_agent.client_id, user_id, source, "assistant", reply,
                meta={"confidence": 0.9, "needs_human": needs_human, "model_used": "claude-sonnet-4-6", "cost_usd": 0.0},
            )
        else:
            if not message:
                return web.json_response({"reply": ""})
            reply = await ig_handle_message(user_id, message, source, name, sales_agent)
    except Exception as e:
        logger.error("Instagram handle error: %s", e)
        return web.json_response({"reply": "Вибачте, виникла помилка. Спробуйте ще раз."})

    return web.json_response({"reply": reply})


async def _tg_webhook_receive(request: web.Request, tg_app) -> web.Response:
    """POST /webhook — вхідні оновлення від Telegram."""
    try:
        data = await request.json()
        update = Update.de_json(data, tg_app.bot)
        await tg_app.process_update(update)
    except Exception as e:
        logger.error("Telegram webhook error: %s", e)
    return web.Response(text="OK")


async def _run_aiohttp(tg_app, port: int) -> None:
    aio_app = web.Application()
    aio_app.router.add_post("/instagram/webhook", _ig_webhook_receive)
    aio_app.router.add_post("/webhook", lambda r: _tg_webhook_receive(r, tg_app))
    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("aiohttp сервер запущено на порту %d", port)
    await asyncio.Event().wait()


async def daily_trainer_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """08:00 Kyiv (05:00 UTC): analyze manager dialogs, propose improved orchestrator prompt."""
    if not MANAGER_TELEGRAM_ID:
        return
    try:
        from agents.orchestrator_trainer.analyzer import analyze
        r = await analyze(sales_agent.client_id, hours=24)
        if r.get("skip"):
            logger.info("[trainer] skip: %s", r.get("reason"))
            return
        issues_text = "\n".join(f"• {i}" for i in r["issues"][:5])
        change_text = "\n".join(f"• {c}" for c in r.get("change_log", [])[:5])
        text = (
            f"🌅 <b>Ранковий аудит оркестранта</b>\n"
            f"Проаналізовано: {r['dialogs_count']} повідомлень\n\n"
            f"<b>Знайдено проблем: {len(r['issues'])}</b>\n{issues_text}\n\n"
            f"<b>Зміни:</b>\n{change_text}\n\n"
            f"Затвердити нову версію промпту? <b>так / ні / diff</b>"
        )
        await context.bot.send_message(
            chat_id=MANAGER_TELEGRAM_ID, text=text, parse_mode="HTML"
        )
    except Exception as e:
        logger.error("[daily_trainer] failed: %s", e, exc_info=True)


async def handle_test_trainer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /test_trainer — вручну запускає аналіз оркестранта."""
    if str(update.effective_chat.id) != MANAGER_TELEGRAM_ID:
        return
    await update.message.reply_text("⏳ Запускаю аналіз діалогів оркестранта...")
    await daily_trainer_job(context)


async def handle_prompt_rollback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /prompt_rollback — відкочує промпт оркестранта до попередньої версії."""
    if str(update.effective_chat.id) != MANAGER_TELEGRAM_ID:
        return
    from core.orchestrator import invalidate_orchestrator_prompt_cache
    v = await db.rollback_agent_prompt(sales_agent.client_id, "orchestrator")
    if v is None:
        await update.message.reply_text("Попередня версія відсутня — відкотити нема куди.")
        return
    invalidate_orchestrator_prompt_cache()
    await update.message.reply_text(f"↩️ Промпт оркестранта відкочено до версії {v}")


async def handle_ack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /ack — підтвердження перегляду (використовується в approval flow)."""
    if str(update.effective_chat.id) != MANAGER_TELEGRAM_ID:
        return
    await update.message.reply_text("ℹ️ Щоб затвердити новий промпт, відповідайте 'так' або 'ні' на звіт тренера.")


async def scheduled_train(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Автоматичний запуск тренування щодня о 9:00 Київ (06:00 UTC)."""
    if not MANAGER_TELEGRAM_ID:
        return
    try:
        from agents.sales.trainer import run_training
        result = await run_training(sales_agent.client_id, 30, only_low=False)
        if result.get("error"):
            await context.bot.send_message(
                chat_id=MANAGER_TELEGRAM_ID,
                text=f"⚠️ Авто-тренування: помилка\n{result['error']}",
            )
            return
        suggestions = result.get("suggestions", [])
        written = result.get("written", 0)
        if not suggestions:
            return
        lines = [f"🧠 <b>Авто-тренування завершено</b>\nЗаписано: {written} пропозицій\n"]
        for s in suggestions[:5]:
            prio = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(s.get("priority", ""), "⚪")
            lines.append(
                f"{prio} <b>{s.get('type', '')} — {s.get('priority', '')}</b>\n"
                f"{s.get('suggestion', '')}\n"
            )
        if len(suggestions) > 5:
            lines.append(f"<i>...ще {len(suggestions) - 5} пропозицій у Sheets</i>")
        await context.bot.send_message(
            chat_id=MANAGER_TELEGRAM_ID,
            text="\n".join(lines),
            parse_mode="HTML",
        )
        logger.info("Авто-тренування завершено: %d пропозицій", len(suggestions))
    except Exception as e:
        logger.error("scheduled_train error: %s", e)


def _build_tg_app(token: str):
    tg_app = ApplicationBuilder().token(token).build()
    from datetime import time as dt_time
    tg_app.job_queue.run_daily(scheduled_train, time=dt_time(hour=6, minute=0))
    # Daily orchestrator trainer: 08:00 Kyiv = 05:00 UTC
    tg_app.job_queue.run_daily(daily_trainer_job, time=dt_time(hour=5, minute=0))
    tg_app.add_handler(CommandHandler("start", handle_start))
    tg_app.add_handler(CommandHandler("reload_kb", handle_reload_kb))
    tg_app.add_handler(CommandHandler("review", handle_review))
    tg_app.add_handler(CommandHandler("audit", handle_audit))
    tg_app.add_handler(CommandHandler("fix", handle_fix))
    tg_app.add_handler(CommandHandler("push", handle_push))
    tg_app.add_handler(CommandHandler("rollback", handle_rollback))
    tg_app.add_handler(CommandHandler("design", handle_design))
    tg_app.add_handler(CommandHandler("train", handle_train))
    tg_app.add_handler(CommandHandler("analyze", handle_analyze))
    tg_app.add_handler(CommandHandler("test_trainer", handle_test_trainer))
    tg_app.add_handler(CommandHandler("prompt_rollback", handle_prompt_rollback))
    tg_app.add_handler(CommandHandler("ack", handle_ack))
    tg_app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    # Фото або документ з caption /analyze → Multimodal Analyst
    tg_app.add_handler(MessageHandler(
        (filters.PHOTO | filters.Document.ALL) & filters.CaptionRegex(r"(?i)^/analyze"),
        handle_analyze,
    ))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return tg_app


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN не знайдено в .env")

    webhook_url = os.getenv("WEBHOOK_URL", "").strip()
    tg_app = _build_tg_app(token)

    if webhook_url:
        port = int(os.getenv("PORT", "8080"))
        logger.info("🤖 AI Laboratory Bot запущено (aiohttp: %s)", webhook_url)

        async def _start():
            await db.init()
            await db.check_connection()
            await tg_app.initialize()
            await tg_app.start()
            await tg_app.bot.set_webhook(
                url=f"{webhook_url}/webhook",
                drop_pending_updates=True,
            )
            await _run_aiohttp(tg_app, port)

        asyncio.run(_start())
    else:
        logger.info("🤖 AI Laboratory Bot запущено (polling)")

        async def _polling_start():
            await db.init()
            await db.check_connection()
            await tg_app.initialize()
            await tg_app.start()
            await tg_app.updater.start_polling(drop_pending_updates=True)
            await asyncio.Event().wait()

        asyncio.run(_polling_start())


if __name__ == "__main__":
    main()
