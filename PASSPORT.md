# PASSPORT — AI Laboratory v1.0
Дата: 18 квітня 2026 | Сесія: #1

---

## North Star (кінцеве бачення)

Мережа з 13 спеціалізованих AI-агентів, які автоматизують продажі, маркетинг та операції малого бізнесу. Продаємо як SaaS (місячна оренда per agent) та франшизу.

---

## NOW — Наступні 14 днів

**Єдина мета: запустити Agent #1 (Telegram Sales Agent)**

- [x] Крок 0: Структура репозиторію + BaseAgent spec
- [ ] Крок 1: Реалізація BaseAgent + тести
- [ ] Крок 2: Agent #1 Telegram Sales Agent (etalhome Knowledge Base)
- [ ] Крок 3: Тест з 5-10 реальними людьми

**Feature Freeze:** нові ідеї → тільки BACKLOG.md

---

## NEXT — Місяць 2

- Agent #2: Universal Web Parser
- Orchestrator: роутинг між Agent #1 і #2
- Brain Archive v1 (Google Sheets) → аналітика якості
- AI-Psychologist як фільтр перед Orchestrator

---

## LATER — Місяць 3+

- Agent #3: Multimodal Analyst
- Google Ads Strategy Agent
- Self-Evolution loop (Observer → Architect of Prompts, human-approved)
- Brain Archive v2 (Supabase pgvector) при ≥1-2k записів

---

## Ядро агентів (5-6 з 13)

| # | Агент | Модель | Пріоритет |
|---|-------|--------|-----------|
| 1 | Telegram Sales Agent | Haiku (FAQ) / Sonnet (переговори) | 🔴 Зараз |
| 2 | Universal Web Parser | Sonnet | 🟠 Місяць 2 |
| 3 | Multimodal Analyst | Sonnet | 🟠 Місяць 3 |
| 4 | Google Ads Strategy | Sonnet | 🟡 Місяць 4 |
| 5 | AI-Orchestrator | Sonnet | 🟠 Місяць 2 |
| 6 | Strategic Architect | Sonnet / Opus | 🟡 Місяць 4 |

Решта 7 агентів → [BACKLOG.md](BACKLOG.md)

---

## Зафіксована архітектура

- **Hub-and-spoke:** Orchestrator у центрі, агенти не розмовляють напряму
- **Mesh:** тільки після 5+ агентів і доведеного bottleneck
- **Self-Evolution:** AI пропонує → Роман апрувить → deploy
- **Multi-tenancy:** `client_id` скрізь з першого рядка
- **Моделі:** Haiku (routing/FAQ) → Sonnet (аналіз/продажі) → Opus (стратегія)
- **FastAPI-first:** без Make.com
- **Railway:** хостинг (Fly.io при 10+ клієнтах)

---

## Бізнес-модель

- Цінова модель: місячна оренда per agent
- Юрисдикція: Україна + ЄС
- Перший клієнт: etalhome (після запуску платформи)
- White-label reseller: після 10+ платних клієнтів

---

## Ролі

- **Роман** = Product Owner, тестування, Knowledge Base
- **Claude** = Technical Executor, код, архітектура

---

## Статус-маркери

- ✅ Архітектура зафіксована
- ✅ BaseAgent + spec написані
- ⏳ Agent #1 у розробці
- 🔒 Feature Freeze активний

---

Наступний перегляд: після запуску Agent #1 з реальними клієнтами.
