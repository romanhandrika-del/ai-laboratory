# Telegram Monitor Agent

**agent_id:** `telegram-monitor-v1`  
**Тип:** Standalone process (не Railway webhook — потребує увімкненого Mac)

## Призначення

Моніторить Saved Messages (чат сам з собою) на YouTube посилання. При виявленні — транскрибує відео і відправляє Claude summary назад у Saved Messages.

## Як використовувати

1. Запустити: `python agents/telegram_monitor/run.py`
2. Надіслати YouTube посилання самому собі у Telegram
3. Агент знаходить URL → transcript → summary → відповідь у Saved Messages

## Пайплайн

```
NewMessage (Saved Messages) → extract YouTube URLs
    → get_transcript(video_id)
    → summarize() via Claude
    → send_message("me", formatted_summary)
```

## Технічні деталі

- Використовує **Telethon** (user-mode Telegram client, не Bot API)
- Сесія зберігається у `data/tg_session`
- Паралельна обробка кількох URL через `asyncio.create_task`
- Реагує тільки на повідомлення де `peer_id == my_id` (Saved Messages)
- Відловлює також YouTube URLs з медіа-превʼю (MessageMediaWebPage)

## Env vars

| Змінна | Опис |
|--------|------|
| `TELEGRAM_API_ID` | API ID з my.telegram.org |
| `TELEGRAM_API_HASH` | API Hash з my.telegram.org |

## Обмеження

- Потребує авторизованої Telegram сесії (файл `data/tg_session`)
- Працює тільки поки Mac увімкнений (не підходить для Railway)
- Залежить від `youtube_agent` (transcript + summarizer)
