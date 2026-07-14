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

## Власник схеми БД
Спільна Neon-база з `etalhome` (окремий репо, Telegram-бот). Owner DDL/міграцій —
**etalhome**. `core/db.py:init()` виконує `_DDL` + auto-seed тільки якщо
`RUN_MIGRATIONS=true` (дефолт вимкнено — звичайний деплой ai-lab схему НЕ чіпає).
**Нове середовище:** один запуск з `RUN_MIGRATIONS=true`, далі одразу вимкнути назад.

## Environment variables
```
RUN_MIGRATIONS               # "true" лише для одноразового запуску на новому середовищі
ANTHROPIC_API_KEY
TELEGRAM_BOT_TOKEN           # @ai_lab_roman_bot
TELEGRAM_WEBHOOK_SECRET      # Telegram setWebhook secret_token; 32-256 chars [A-Za-z0-9_-]
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

## Граблі Sales Agent — розрахунок розмірів (2026-06-12)

### Нестандартні підписи розмірів → LLM ігнорує множення
Клієнт написав "2,75 виста / 3.15 длина" → агент взяв 3.15 як площу → 34 650 грн замість 86 600 грн.
**Причина:** "виста" (неправильна Ukrainian) і "длина" (Russian) — LLM не розпізнав як два лінійних розміри.
**Правило:** у prompt_template.md є таблиця синонімів і пряма заборона: два числа = завжди множити. Якщо знову ламається — перевіряти секцію `⛔ КРИТИЧНО — розпізнавання розмірів клієнта` у `<calculation_rules>`.

---

## Граблі Sales Trainer — запобіжники (2026-05-08)

### Trainer аналізував чужі агенти (БАГ 8)
`get_dialogs_review` брав всі `dialogs` включно з `source='telegram'` від website_fix/youtube агентів → suggestions про деплой/DNS/SEO замість sales помилок.
**Правило:** `get_dialogs_review(client_id, source='instagram')` — завжди передавати source. Sales trainer = тільки instagram. `core/db.py:361`.

### Sales промпт живе в ДВОХ місцях одночасно
Instagram читає з Neon DB (`db.save_agent_prompt`). Telegram читає з файлу (`agents/sales/prompt_template.md`).
**Правило:** Будь-яка зміна поведінки sales агента → одночасно обидва файли + `db.save_agent_prompt`. Ніколи не правити тільки один.

### LLM вигадує бізнес-параметри яких немає в промпті
Термін виготовлення не був в промпті → LLM написав "7-14 днів" (реально 8-10 тижнів).
**Правило:** Терміни, гарантії, географія, ціни — все явно в промпті. Без інструкції LLM вигадає "розумний" дефолт який може бути хибним.

### Тренер не бачить поточний промпт → галюцинує і дублює (БАГ 11, 12 — 2026-05-11)
Тренер пропонував FAQ "Терміни: 10-14 робочих днів" (реально 8-10 тижнів) і "Типи скла" що вже є в промпті.
Кореневий баг: `_ANALYSIS_PROMPT` не містив поточного промпту агента → LLM не знав що вже є.
**Правило:** `run_training` ЗАВЖДИ завантажує промпт: `db.get_agent_prompt` → fallback `prompt_template.md` → stub. Передає перші 6000 символів в системний промпт тренера. `agents/sales/trainer.py:115`.

## Граблі Sales Trainer — запобіжники (2026-07-01)

### Scheduled task пише дублікати в pending_reviews
Тренер запускався щодня, аналізував ті самі 10 найгірших діалогів (без фільтру дати), і кожен день вставляв однаковий патч в `pending_reviews` голим `INSERT`.
**Правило:** Будь-який scheduled job що пише в БД — обов'язково: `days=(0,2)` у `run_daily`, `days_back=N` у запиті діалогів, `SELECT ... WHERE status='pending'` перед INSERT. `bot.py:1226`, `db.py:save_trainer_review`.

### Google Sheets KB: PermissionError з порожнім повідомленням
`logger.error(f"... {e}")` — gspread `PermissionError()` має `str(e)==""`. Агент стартував тижнями з fallback-текстом і ніхто не помічав.
**Правило:** У будь-якому `except Exception as e` — логувати `{e!r}` (не `{e}`). Після нового деплою Railway — перевіряти логи старту на `PermissionError`. Сервісний акаунт: `my-bot-sheets@steadfast-theme-491920-h1.iam.gserviceaccount.com` має бути Viewer на KB Sheet.

---

## Граблі Memory vs Local State — запобіжники (2026-05-10)

### Memory описує remote-стан що не збігається з локальним репо
Сесія записала «Фаза 2.1 завершена, commit a14938f» — коміт був на GitHub (паралельна сесія з іншою DB-схемою), але не локально і файли були відсутні. Результат: повна перереалізація + force push + 6 hotfix-комітів через конфлікт схем у Railway Postgres.
**Правило:** На початку сесії де memory каже «✅ завершено» — СПОЧАТКУ:
1. `git log --oneline | grep <hash>` — коміт є локально?
2. `ls <ключовий файл>` — файл існує?
3. Якщо НІ → `git pull --rebase origin main` до першого рядка коду.
4. Якщо Railway Postgres має стару схему → `railway run python3 -c "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name='<table>'"` → ALTER TABLE ADD COLUMN / DROP NOT NULL, не CREATE TABLE з нуля.
