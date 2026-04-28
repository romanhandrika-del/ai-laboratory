# Instagram DM Agent

**agent_id:** `instagram-dm-v1`  
**Тип:** Webhook handler (не BaseAgent)

## Призначення

Обробляє вхідні Instagram/Facebook DM через Sendrules webhook.  
Sendrules → `POST /instagram/webhook` → Sales Agent → `{"reply": "..."}` → Sendrules надсилає відповідь клієнту.

## Вхідний payload (від Sendrules)

```json
{
  "user_id": "string",
  "message": "string",
  "source": "instagram" | "facebook",
  "name": "string",
  "file_url": "string (optional)",
  "file_type": "string (optional)"
}
```

Header: `X-Webhook-Secret: <WEBHOOK_SECRET>`

## Логіка

1. Верифікація `X-Webhook-Secret` → `verify_secret()`
2. Завантаження останніх 20 повідомлень з БД → контекст для Sales Agent
3. `sales_agent.run(AgentMessage)` → відповідь
4. Збереження user/assistant повідомлень у БД з метаданими (confidence, needs_human, cost_usd)
5. Повернення `{"reply": "..."}` → Sendrules

## Залежності

- `sales` agent — генерує відповіді
- `core.db` — history load/save
- `agents/instagram/file_handler.py` — обробка вкладень
- `agents/instagram/ocr.py` — OCR зображень
- `agents/instagram/speech.py` — транскрипція голосових

## Env vars

| Змінна | Опис |
|--------|------|
| `WEBHOOK_SECRET` | Секрет для верифікації webhook від Sendrules |

## Обмеження

- Голосові повідомлення: API Sendrules не передає аудіо-файли напряму (відома проблема — потрібна авто-відповідь клієнту)
- MAX_HISTORY = 20 повідомлень на контекст
