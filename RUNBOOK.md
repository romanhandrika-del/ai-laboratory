# RUNBOOK — AI Laboratory

Інструкції для запуску, деплою, ролбеку та дебагу.

---

## Локальний запуск

```bash
cd ai-laboratory
pip install -r requirements.txt
cp .env.example .env
# Заповни ANTHROPIC_API_KEY та інші ключі

# Запуск orchestrator
python -m platform.orchestrator

# Запуск конкретного агента
python -m agents.sales_agent
```

## Змінні оточення (.env)

| Змінна | Опис | Де взяти |
|--------|------|----------|
| `ANTHROPIC_API_KEY` | Ключ Anthropic API | console.anthropic.com |
| `TELEGRAM_BOT_TOKEN` | Токен бота | @BotFather у Telegram |
| `GOOGLE_CREDENTIALS_JSON` | Google Service Account (JSON) | Google Cloud Console |
| `BRAIN_SHEET_ID` | Google Sheets ID для Brain Archive | URL таблиці |
| `MANAGER_TELEGRAM_ID` | Telegram ID менеджера (ескалація) | @userinfobot |
| `DEFAULT_CLIENT_ID` | Client ID за замовчуванням | придумати |

## Деплой на Railway

```bash
git add .
git commit -m "deploy: опис змін"
git push origin main
# Railway автоматично деплоїть при push у main
```

## Перевірка після деплою

1. Відкрий Railway dashboard → логи сервісу
2. Надішли тестове повідомлення боту
3. Перевір Brain Archive (Google Sheets) — чи з'явився запис
4. Перевір логи на помилки (ERROR, CRITICAL)

## Ролбек

```bash
git log --oneline -10          # знайти попередній робочий commit
git revert HEAD                # скасувати останній commit
git push origin main           # задеплоїти ролбек
```

## Частi помилки

| Помилка | Причина | Рішення |
|---------|---------|---------|
| `AuthenticationError` | Невірний ANTHROPIC_API_KEY | Перевір .env або Railway env vars |
| `RateLimitError` | Перевищено ліміт запитів | Додай `time.sleep(1)` між запитами |
| `overloaded_error` | Anthropic навантажений | Retry з exponential backoff |
| `Invalid model` | Стара назва моделі | Перевір таблицю моделей у README |
| Google Sheets 403 | Немає прав Service Account | Дай доступ до таблиці service account email |

## Моніторинг

- Логи: Railway dashboard → сервіс → Logs
- Витрати API: console.anthropic.com → Usage
- Brain Archive: Google Sheets (посилання у .env)
- Ліміт спрацював: перевір Anthropic Console → Limits
