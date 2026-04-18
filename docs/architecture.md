# Архітектура AI Laboratory

## Концепція: Hub-and-Spoke

```
User Input
    │
    ▼
┌─────────────────────────┐
│   AI-Psychologist        │  ← Haiku (дешевий)
│   (фільтр + routing)    │    sentiment, токсичність
└─────────┬───────────────┘
          │
    ┌─────┴──────┐
    │  TOXIC?    │
    │  block     │
    └─────┬──────┘
          │ clean
          ▼
┌─────────────────────────┐
│   AI-Orchestrator        │  ← Sonnet (основний)
│   (центральний hub)     │    вирішує: який агент?
└──┬──────┬──────┬────────┘
   │      │      │
   ▼      ▼      ▼
Agent1  Agent2  Agent3   ← Haiku/Sonnet/Opus (за складністю)
   │      │      │
   └──────┴──────┘
          │
          ▼
┌─────────────────────────┐
│   Brain Archive          │  ← Google Sheets (v1)
│   (логування)           │    pgvector Supabase (v2)
└─────────────────────────┘
```

## Правила архітектури

1. **Агенти НЕ розмовляють напряму** — тільки через Orchestrator
2. **Mesh Network** — тільки якщо Hub є доведеним bottleneck (5+ агентів)
3. **Кожен виклик має `client_id`** — multi-tenancy з першого рядка
4. **Self-Evolution** — AI пропонує зміни промптів, Роман апрувить вручну

## Рівні агентів

### РІВЕНЬ 0 — Фільтр (Haiku)
- **AI-Psychologist** — sentiment, токсичність, routing до правильної моделі

### РІВЕНЬ 1 — Orchestrator (Sonnet)
- **AI-Orchestrator** — маршрутизація, синтез відповідей, координація

### РІВЕНЬ 2 — Internal Agents (Sonnet)
- **Universal Web Parser** — парсинг конкурентів, ринку
- **Multimodal Analyst** — аналіз фото, зображень продуктів (НЕ медицина)
- **Strategic Architect** — ТЗ, бізнес-логіка, структури
- **Google Ads Strategy** — рекламні кампанії

### РІВЕНЬ 3 — External Agents (Haiku/Sonnet)
- **Telegram Sales Agent** — продажі 24/7 (Haiku для FAQ, Sonnet для переговорів)

### РІВЕНЬ 4 — Meta (Opus)
- **Strategic Architect** (складні завдання) — Opus
- **Architect of Prompts** (Self-Evolution) — Opus

## Вибір моделі

| Задача | Модель | Орієнтовна ціна |
|--------|--------|-----------------|
| Routing, sentiment, FAQ | `claude-haiku-4-5-20251001` | ~$0.001/діалог |
| Продажі, аналіз, код | `claude-sonnet-4-6` | ~$0.015/діалог |
| Стратегія, мета-рівень | `claude-opus-4-7` | ~$0.075/діалог |

## Multi-Tenancy

Кожен API-виклик і запис у Brain Archive містить `client_id`.  
Дані між клієнтами повністю ізольовані на рівні запитів і бази даних.

```python
# Правильно
result = agent.run(message=user_input, client_id="etalhome")

# Неправильно — без ізоляції
result = agent.run(message=user_input)
```

## Brain Archive версії

- **v1 (зараз):** Google Sheets — проста, без коду інфраструктури
- **v2 (при ≥1-2k записів):** Supabase PostgreSQL + pgvector для semantic search

Інтерфейс `BrainArchive` однаковий для v1 і v2 — бекенд swappable.
