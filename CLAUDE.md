# AI Laboratory — Project CLAUDE.md

## Що це за проект
Платформа AI-агентів на базі Multi-Model Claude. Мета — SaaS (місячна оренда per agent).
**Клієнт #1 (MVP):** etalhome (@etalhome) — скляні перегородки, двері, дизайн.

## Де живе код
```
/Users/romanhandrika/Documents/Платформа агентів/ai-laboratory/
```
GitHub: https://github.com/romanhandrika-del/ai-laboratory.git  
Railway: `worker-production-daaa.up.railway.app` (webhook mode, `web: python bot.py`)

## AI Моделі (актуальні ID)
- **claude-sonnet-4-6** — основна логіка, генерація, суддя
- **claude-haiku-4-5-20251001** — класифікація, швидкий JSON, fallback
- Prompt caching: `cache_control: {"type": "ephemeral"}` для довгих system prompt

## Структура агентів

| # | Агент | Директорія | Де живе | Команда |
|---|-------|-----------|---------|---------|
| 1 | Sales Agent | `agents/sales/` | Railway (webhook) | авто |
| 2a | Web Parser | `agents/web_parser/` | Railway | `python agents/web_parser/run.py` |
| 2b | YouTube Monitor | `agents/youtube_agent/` | локально (cron 09:00) | `python agents/youtube_agent/run.py` |
| 2c | Telegram Monitor | `agents/telegram_monitor/` | локально | `python agents/telegram_monitor/run.py` |
| 2d | Telegram Channel Monitor | `agents/telegram_monitor/` | локально | `python agents/telegram_monitor/run_channels.py` |
| 3 | Website Audit | `agents/website_audit/` | Railway | `/audit <url>` |
| 4 | Website Fix | `agents/website_fix/` | Railway | `/fix`, `/push`, `/rollback` |
| 5 | Web Design | `agents/web_design/` | Railway | `/design <url>` |
| 6 | Multimodal Analyst | `agents/multimodal_analyst/` | Railway | `/analyze` + фото/PDF |
| 7 | Orchestrator | — | **не зроблено** | — |

## Структура директорій
- `/agents/` — кожен агент в окремій папці
- `/core/` — спільне ядро: `db.py`, `base_agent.py`, `audit_storage.py`, `logger.py`, `orchestrator.py`
- `/config/` — yaml-конфіги: `sites.yaml`, `channels.yaml`, `tg_channels.yaml`, `audit_targets.yaml`
- `/data/` — локальні артефакти: `fixes/`, `backups/`, `designs/`, `audits/`
- `/docs/` — аудити, схеми БД, інструкції
- `/scripts/` — автономні процеси

## База даних
- **Neon PostgreSQL** + `asyncpg` (пул з'єднань)
- **ПРАВИЛО:** кожен запит до БД ОБОВ'ЯЗКОВО містить `client_id`
- Таблиці: `analysis_history`, `fix_history`, `design_history`, `knowledge_base`, `yt_content`
- При пошуку для відповіді: спочатку `knowledge_base`, потім `yt_content`

## Environment variables (ключові)
```
ANTHROPIC_API_KEY
TELEGRAM_BOT_TOKEN        # @ai_lab_roman_bot
TELEGRAM_API_ID / API_HASH  # Telethon (локальні агенти)
ARCHIVE_CHANNEL_ID        # -1003701420760 (Multimodal: зберігає оригінали)
DEFAULT_CLIENT_ID
KB_SHEET_ID_ETALHOME
BRAIN_SHEET_ID
GOOGLE_PAGESPEED_API_KEY
FTP_HOST / FTP_USER / FTP_PASS / FTP_PORT / FTP_ROOT  # etalhome WordPress
GDRIVE_ARCHIVE_FOLDER_ID
OPENAI_API_KEY
ENVIRONMENT               # production / development
```

## etalhome специфіка
- Сайт: WordPress (не статичний HTML)
- FTP host: 82.198.227.245
- Фікси деплояться як mu-plugin: `/wp-content/mu-plugins/etalhome-seo-fixes.php`
- PHP nowdoc `<<<'MARKER'...MARKER;` для безпечного echo HTML
- Google Sheets KB: `1EELiSfK3tA_k3KxEjEte-VHQFPUDfMuTGEfzOBMsyC4`

## Граблі (перевірені проблеми)

**Railway 403 / YouTube Transcript API**
→ Використовуй ротацію IP або `yt-dlp` як fallback.
→ Якщо транскрипт `uk` недоступний — бери `en` і перекладай через Claude (Haiku).

**JSON Parsing**
→ Claude іноді додає текст до JSON. Завжди: `raw.find("[")` або Pydantic для валідації.

**Neon history → Anthropic API (КРИТИЧНО)**
→ Neon зберігає повідомлення з полями `ts` і `meta`. Anthropic API приймає ТІЛЬКИ `role` і `content`.
→ Фікс у `core/base_agent.py`: стрипати зайві поля перед API-викликом.
→ Симптом: перше повідомлення працює, всі наступні — "технічна помилка".

**Memory Limit 256MB (Railway)**
→ Не завантажувати великі бібліотеки у пам'ять без потреби (особливо ML-моделі).

**KB завантажується з помилкою JSON (Invalid control character)**
→ Не критично, бот працює. Фікс відкладено.

**Instagram голосові повідомлення**
→ Не підтримуються API. При `media_type: voice` відправляти шаблон:
  _"На жаль, я поки не вмію слухати аудіо — опишіть, будь ласка, ваше питання текстом."_

**bot.py guards**
→ Завжди перевіряти `update.message is None` у handlers.
→ `(text or caption or "")` — не падати на фото без тексту.

## Правило: Single Source of Truth
Локальні агенти (2b, 2c, 2d) після завершення роботи ОБОВ'ЯЗКОВО пишуть результати у Neon DB.
`/data/` — лише локальний backup, не основне сховище.

## Наступне (Orchestrator #7)
Координує всіх агентів, розподіляє задачі між ними. Ще не розпочато.

**Архітектура (Router-патерн):**
- Haiku класифікує намір (Intent) → передає контекст потрібному агенту
- Sonnet виконує логіку агента
- Neon DB: таблиця `session_state` — стан діалогу клієнта (наприклад: `awaiting_photo`, `awaiting_url`)
- НЕ робити Orchestrator монолітним — тільки маршрутизація
