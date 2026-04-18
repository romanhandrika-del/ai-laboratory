# AI Laboratory v1.0

Платформа спеціалізованих AI-агентів для автоматизації продажів, маркетингу та операцій малого бізнесу.

## Суть

Мережа з 5-6 AI-агентів (ядро), які виконують бізнес-задачі під єдиним Orchestrator-ом.  
Модель монетизації: місячна оренда per agent.  
Перший клієнт: etalhome (запускається після готовності платформи).

## Швидкий старт

```bash
git clone <repo>
cd ai-laboratory
cp .env.example .env
# Заповни .env своїми ключами
pip install -r requirements.txt
python -m platform.orchestrator
```

## Структура

```
ai-laboratory/
├── docs/               ← архітектура, специфікації
├── platform/           ← ядро: BaseAgent, Orchestrator, BrainArchive
├── agents/             ← конкретні агенти (#1, #2, ...)
└── tests/              ← тести
```

## Моделі (Anthropic)

| Складність | Модель |
|-----------|--------|
| Проста (routing, FAQ, фільтри) | `claude-haiku-4-5-20251001` |
| Середня (продажі, аналіз, код) | `claude-sonnet-4-6` |
| Висока (стратегія, мета-рівень) | `claude-opus-4-7` |

## Документація

- [Архітектура](docs/architecture.md)
- [Специфікація BaseAgent](docs/base-agent-spec.md)
- [MessageProtocol](docs/message-protocol.md)
- [Runbook](RUNBOOK.md)
- [Backlog](BACKLOG.md)
