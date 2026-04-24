import json
from core.logger import get_logger
from core.message import AgentMessage, AgentResult, OrchestratorDecision
from core.base_agent import BaseAgent, MODEL_SONNET, MODEL_HAIKU

logger = get_logger(__name__)

ORCHESTRATOR_PROMPT = """
Ти — AI-Orchestrator центральної лабораторії. Твоя роль:

1. АНАЛІЗ: Прийми запит та визнач його тип (продажі / технічне / контент / аналітика).
2. МАРШРУТИЗАЦІЯ: Визнач, який агент має виконати завдання.
3. КООРДИНАЦІЯ: Передай завдання агентам у правильному порядку.
4. СИНТЕЗ: Збери результати від усіх агентів у єдину відповідь.
5. РЕФЛЕКСІЯ: Зроби коротку нотатку про рішення (brain_archive_note).

Доступні агенти: {available_agents}

Відповідай ТІЛЬКИ валідним JSON:
{{
  "selected_agents": ["назва агента"],
  "task_breakdown": {{"агент": "конкретне завдання"}},
  "priority": "high/medium/low",
  "routing_reason": "чому цей агент",
  "estimated_cost_usd": 0.005,
  "brain_archive_note": "коротка нотатка про рішення"
}}
"""


class OrchestratorAgent(BaseAgent):
    def __init__(self, registry: dict):
        self.registry = registry  # {"agent_id": agent_instance}
        self.client_id = "owner"
        agent_list = ", ".join(registry.keys())
        super().__init__(
            agent_id="orchestrator-v1",
            model=MODEL_SONNET,
            system_prompt=ORCHESTRATOR_PROMPT.format(available_agents=agent_list),
            max_tokens=500,
            prompt_version="1.0",
        )

    def run(self, message: AgentMessage) -> AgentResult:
        decision_result = self._call_api(message)

        if decision_result.error:
            logger.error(f"Orchestrator failed: {decision_result.error}")
            return decision_result

        try:
            decision_data = json.loads(decision_result.content)
        except json.JSONDecodeError:
            logger.error(f"Orchestrator returned invalid JSON: {decision_result.content}")
            return decision_result

        decision = OrchestratorDecision(
            trace_id=message.trace_id,
            client_id=message.client_id,
            selected_agents=decision_data.get("selected_agents", []),
            task_breakdown=decision_data.get("task_breakdown", {}),
            priority=decision_data.get("priority", "medium"),
            routing_reason=decision_data.get("routing_reason", ""),
            estimated_cost_usd=decision_data.get("estimated_cost_usd", 0),
        )

        results = []
        total_cost = decision_result.cost_usd

        for agent_id in decision.selected_agents:
            agent = self.registry.get(agent_id)
            if not agent:
                logger.warning(f"Agent '{agent_id}' not found in registry")
                continue

            task = decision.task_breakdown.get(agent_id, message.content)
            agent_message = AgentMessage(
                content=task,
                client_id=message.client_id,
                trace_id=message.trace_id,
                context=message.context,
                metadata=message.metadata,
            )
            result = agent.run(agent_message)
            results.append(result)
            total_cost += result.cost_usd

        if not results:
            return decision_result

        # Якщо будь-який агент потребує людини → ескалація
        needs_human = any(r.needs_human for r in results)
        min_confidence = min(r.confidence for r in results)

        final_content = results[0].content if len(results) == 1 else self._synthesize(results)

        return AgentResult(
            content=final_content,
            confidence=min_confidence,
            needs_human=needs_human,
            cost_usd=total_cost,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            client_id=message.client_id,
            model_used=self.model,
            input_tokens=decision_result.input_tokens,
            output_tokens=decision_result.output_tokens,
        )

    def _synthesize(self, results: list[AgentResult]) -> str:
        """Об'єднання відповідей кількох агентів."""
        return "\n\n".join(r.content for r in results if r.content)

    def register(self, agent: BaseAgent) -> None:
        self.registry[agent.agent_id] = agent
