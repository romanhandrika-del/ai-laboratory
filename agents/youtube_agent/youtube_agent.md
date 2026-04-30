# YouTube Agent

**agent_id:** `youtube-agent-v1`  
**Номер у платформі:** Agent #2b  
**Тип:** Scheduled monitor

## Призначення

Моніторить YouTube канали за RSS-фідом, транскрибує нові відео і надсилає summary у Telegram.

## Конфігурація

Канали описуються у `config/channels.yaml`:

```yaml
youtube_channels:
  - name: "Назва каналу"
    channel_id: "UC..."
```

## Пайплайн (для кожного каналу)

```
get_recent_videos(channel_id) [RSS]
    → filter: is_processed() → нові відео
    → get_transcript(video_id) → текст субтитрів
    → summarize(text, url) → Claude summary
    → format_telegram_message()
    → bot.send_message(MANAGER_TELEGRAM_ID)
    → mark_processed(video_id)
```

## Компоненти

| Файл | Призначення |
|------|-------------|
| `channel_feed.py` | RSS парсинг YouTube каналу |
| `transcript.py` | Завантаження субтитрів через `youtube-transcript-api` |
| `summarizer.py` | Генерація summary через Claude |
| `run.py` | Точка запуску (standalone або cron) |

## Зберігання

- Оброблені відео: `core.youtube_storage` (щоб не повторювати)

## Env vars

| Змінна | Опис |
|--------|------|
| `TELEGRAM_BOT_TOKEN` | Бот для нотифікацій |
| `MANAGER_TELEGRAM_ID` | Telegram ID менеджера |

## Обмеження

- Субтитри: тільки відео з автоматичними або ручними субтитрами
- RSS-фід YouTube: максимум ~15 останніх відео на канал
- Залежить від `youtube-transcript-api` (може ламатись при змінах API YouTube)
