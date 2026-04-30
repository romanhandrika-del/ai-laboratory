# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Що це за проект
Платформа AI-агентів на базі Multi-Model Claude. Мета — SaaS (місячна оренда per agent).
**Клієнт #1 (MVP):** etalhome (@etalhome) — скляні перегородки, двері, душові.
**Instagram агент etalhome живе тут** — ai-laboratory є "etalhome Instagram сервером". `~/etalhome/` — окремий проект тільки для Telegram бота etalhome. Це два різних репозиторії.

## Де живе код
```
/Users/romanhandrika/Documents/Платформа агентів/ai-laboratory/
```
GitHub: https://github.com/romanhandrika-del/ai-laboratory.git
Railway: `worker-production-daaa.up.railway.app` (webhook mode, `web: python bot.py`)

## AI Моделі
- **claude-sonnet-4-6** — основна логіка, генерація, суддя
- **claude-haiku-4-5-20251001** — класифікація, швидкий JSON, memory summary
- Prompt caching: `cache_control: {"type": "ephemeral"}` для довгих system prompt

## Структура агентів

| # | Агент | Директорія | Статус |
|---|-------|-----------|--------|
| 1 | Sales Agent | `agents/sales/` | ✅ Railway + cross-session memory |
| 2a | Web Parser | `agents/web_parser/` | ✅ Railway |
| 2b | YouTube Monitor | `agents/youtube_agent/` | ✅ локально cron 09:00 |
| 2c | Telegram Monitor | `agents/telegram_monitor/` | ✅ локально |
| 3 | Website Audit | `agents/website_audit/` | ✅ Railway `/audit <url>` |
| 4 | Website Fix | `agents/website_fix/` | ✅ Railway `/fix`, `/push`, `/rollback` |
| 5 | Web Design | `agents/web_design/` | ✅ Railway `/design <url>` |
| 6 | Multimodal Analyst | `agents/multimodal_analyst/` | ✅ Railway `/analyze` + фото/PDF |
| 7 | Orchestrator | `core/orchestrator.py` | ✅ ЖИВИЙ — Sonnet + agentic loop до 8 ходів |
| 8 | Trainer | `agents/sales/trainer.py` | ✅ Railway cron |

## Ключові файли
- `bot.py` — головний entrypoint: aiohttp сервер, Telegram + Instagram webhook handlers
- `core/orchestrator.py` — Router-патерн, Sonnet + 8 інструментів (`run_audit`, `run_fix`, `run_push`, `run_rollback`, `run_design`, `run_train`, `run_review`, `get_last_url`)
- `core/base_agent.py` — базовий клас, `_call_api()` зі стрипом `ts`/`meta` перед Anthropic API
- `core/db.py` — всі DB операції, asyncpg пул max_size=4 для Neon free tier
- `agents/sales/sales_agent.py` — завантажує KB з Google Sheets при старті
- `agents/sales/memory.py` — Haiku компресія діалогу в summary кожні 5 повідомлень
- `agents/sales/prompt_template.md` — промпт Sales Agent з алгоритмами розрахунку
- `agents/instagram/instagram_agent.py` — обробка Instagram DM
- `agents/instagram/file_handler.py` — фото/PDF через Claude Vision

## База даних (Neon PostgreSQL)
**ПРАВИЛО:** кожен запит ОБОВ'ЯЗКОВО містить `client_id`.

Таблиці:
- `dialogs` — повна переписка + `summary`, `summary_msg_count`, `client_name`, `phone`, `phone_first_seen`
- `session_state` — стан діалогу менеджера TTL 30 хв (`awaiting`: url/photo)
- `agent_prompts` — промпти агентів у БД (редагуються через `/set_prompt`)
- `orchestrator_pending_review` — черга на перегляд менеджером
- `trainer_suggestions` — пропозиції тренера (не пишуться напряму у FAQ)
- `analysis_history`, `fix_history`, `design_history` — логи агентів

**КРИТИЧНО:** `load_history()` повертає поля `ts` і `meta` — стрипати перед Anthropic API (реалізовано в `base_agent.py`). Симптом: перше повідомлення ОК, наступні — "технічна помилка".

## Instagram / SendPulse
- SendPulse → POST `/instagram/webhook` → `_ig_webhook_receive()` у `bot.py`
- Payload: `{user_id, message, source, name, file_url?, file_type?}`, Header: `X-Webhook-Secret`
- `[NOTIFY_MANAGER]` у відповіді → `bot.py` надсилає сповіщення менеджерам у Telegram

## Sales Agent — правила розрахунку
Тарифи перегородок: 2–3 м²→12500, 3.1–6 м²→11000, 6.1–11 м²→10000, >11.1 м²→9500 грн/м².
Нестандартне скло (матове/тоноване/кольорове/бронза) → не рахувати, одразу `[NOTIFY_MANAGER]`.
Замір / приїхати / замовити → одразу `[NOTIFY_MANAGER]`.
Ламельні вироби → тариф × 1.4.

## Environment variables
```
ANTHROPIC_API_KEY
TELEGRAM_BOT_TOKEN           # @ai_lab_roman_bot
TELEGRAM_API_ID / API_HASH   # Telethon (локальні агенти)
ARCHIVE_CHANNEL_ID           # -1003701420760
DEFAULT_CLIENT_ID
KB_SHEET_ID_ETALHOME
GOOGLE_CREDENTIALS_JSON      # service account JSON (inline, не файл)
GOOGLE_PAGESPEED_API_KEY
WEBHOOK_SECRET               # Instagram webhook
FTP_HOST / FTP_USER / FTP_PASS / FTP_PORT / FTP_ROOT
ENVIRONMENT                  # production / development
```

## etalhome специфіка
- Сайт: WordPress. FTP: 82.198.227.245
- Фікси: mu-plugin `/wp-content/mu-plugins/etalhome-seo-fixes.php`
- PHP nowdoc `<<<'MARKER'...MARKER;` — безпечний echo HTML
- Google Sheets KB: `1EELiSfK3tA_k3KxEjEte-VHQFPUDfMuTGEfzOBMsyC4` (доступна тільки через service account з `GOOGLE_CREDENTIALS_JSON`)

## ⚠️ Читати перед роботою
`BUGS_AND_DECISIONS.md` — **25 архітектурних рішень, 45 багів, 19 уроків**.
Перед рефакторингом / новою фічею — перевір чи не вирішувалось це вже.

## Граблі

**Neon history → Anthropic API** — поля `ts`/`meta` викликають 400. Стрипати в `base_agent.py`.

**JSON Parsing** — Claude іноді додає текст навколо JSON. Використовуй `raw.find("[")` або Pydantic.

**Railway YouTube 403** — ротація IP або `yt-dlp`. Транскрипт `uk` недоступний → брати `en` + Haiku переклад.

**Instagram голосові** — API не підтримує. Відповідь: "Опишіть питання текстом".

**bot.py guards** — `update.message is None` перевірка у handlers. `(text or caption or "")` — не падати на фото без тексту.

## Команди
```bash
python bot.py                                    # локальний запуск
python agents/web_parser/run.py                  # окремий агент
railway run python -c "import asyncio; from core import db; asyncio.run(db.check_connection())"
```

## Фіналізація сесії
`.claude/commands/finalize.md` — аналізує розмову і дописує нові записи до `BUGS_AND_DECISIONS.md`.
