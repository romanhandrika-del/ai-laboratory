# MessageProtocol — Специфікація

## Потік повідомлень

```
User
 │  raw input (text/image/audio)
 ▼
AI-Psychologist           AgentMessage (фільтрований)
 │  sentiment + routing
 ▼
Orchestrator              OrchestratorDecision (JSON)
 │  task_breakdown
 ▼
Agent(s)                  AgentResult (per agent)
 │
 ▼
Orchestrator              FinalResponse (синтез)
 │
 ▼
User                      str (відповідь клієнту)
 │
 ▼
Brain Archive             BrainRecord (лог)
```

## OrchestratorDecision

Відповідь Orchestrator після аналізу запиту:

```json
{
  "trace_id": "uuid-v4",
  "client_id": "etalhome",
  "selected_agents": ["sales-agent-v1"],
  "task_breakdown": {
    "sales-agent-v1": "Клієнт питає про ціну скляної перегородки 2x3м"
  },
  "priority": "high",
  "routing_reason": "Запит про ціну → Sales Agent",
  "estimated_cost_usd": 0.005
}
```

## PsychologistResult

Відповідь AI-Psychologist (завжди Haiku):

```json
{
  "sentiment": "neutral",
  "buy_intent": "HIGH",
  "is_toxic": false,
  "recommended_model": "claude-haiku-4-5-20251001",
  "escalation_required": false,
  "analysis_note": "Конкретний запит про ціну, висока зацікавленість"
}
```

**sentiment значення:** `positive` | `neutral` | `frustrated` | `toxic`  
**recommended_model:** Orchestrator використовує цю рекомендацію для вибору моделі

## BrainRecord (запис у Brain Archive)

```json
{
  "record_id": "uuid-v4",
  "trace_id": "uuid-v4",
  "client_id": "etalhome",
  "timestamp": "2026-04-18T10:00:00Z",
  "agent_id": "sales-agent-v1",
  "model_used": "claude-haiku-4-5-20251001",
  "input_tokens": 145,
  "output_tokens": 67,
  "cost_usd": 0.0023,
  "task": "Відповідь на запит про ціну перегородки",
  "result": "success",
  "confidence": 0.92,
  "needs_human": false,
  "sentiment": "neutral",
  "error": null,
  "prompt_version": "v1.0.0"
}
```

**Примітка GDPR:** `sentiment` та `content` повідомлень НЕ зберігаємо довготерміново.  
Brain Archive зберігає тільки метрики, не текст діалогів.

## Версіонування промптів

Кожна зміна system prompt = нова версія (semantic versioning):
- `v1.0.0` — початкова версія
- `v1.0.1` — дрібне виправлення
- `v1.1.0` — нова функція або правило
- `v2.0.0` — повна переробка

Версія зберігається у `BrainRecord.prompt_version` для трасування ефекту змін.

## Помилки

```json
{
  "error_type": "rate_limit | auth | overloaded | invalid_model | timeout",
  "error_message": "опис помилки",
  "retry_count": 2,
  "fallback_used": true,
  "fallback_model": "claude-haiku-4-5-20251001"
}
```
