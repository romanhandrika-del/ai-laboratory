# Web Parser Agent

**agent_id:** `web-parser-v1`  
**Тип:** Scheduled scraper (не conversational)

## Призначення

Моніторить сайти на зміни контенту. При виявленні змін — надсилає Telegram-сповіщення менеджеру.

## Конфігурація

Сайти описуються у `config/sites.yaml`:

```yaml
websites:
  - name: "Назва сайту"
    url: "https://example.com"
    selectors:
      title: "h2.product-title"
      price: ".price"
      description: ".desc"
    key_field: "title"  # поле для ідентифікації унікальних елементів
```

## Пайплайн (для кожного сайту)

```
fetch_page(url) → parse_items(html, selectors)
    → detect_changes(current, previous, key_field)
    → if changes: notify Telegram + save_snapshot()
    → else: no-op
```

## Перший запуск

При першому скануванні сайту — зберігається базовий знімок без нотифікації (еталон для порівняння).

## Типи змін

| Тип | Опис |
|-----|------|
| `new` | Нові елементи яких не було |
| `changed` | Існуючі елементи з оновленими полями |
| `removed` | Елементи що зникли |

## Збереження знімків

`core.snapshot_storage` — зберігає JSON-знімки стану сайту.

## Env vars

| Змінна | Опис |
|--------|------|
| `TELEGRAM_BOT_TOKEN` | Токен бота для нотифікацій |
| `MANAGER_TELEGRAM_ID` | Telegram ID менеджера |
