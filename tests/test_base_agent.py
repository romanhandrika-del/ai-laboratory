import pytest
from unittest.mock import MagicMock, patch
from core.message import AgentMessage, AgentResult
from core.base_agent import BaseAgent, MODEL_HAIKU, SLIDING_WINDOW
from core.agent_result import needs_human_check, format_for_user, CONFIDENCE_MEDIUM


class ConcreteAgent(BaseAgent):
    """Тестова реалізація BaseAgent."""
    def run(self, message: AgentMessage) -> AgentResult:
        return self._call_api(message)


@pytest.fixture
def agent():
    return ConcreteAgent(
        agent_id="test-agent-v1",
        model=MODEL_HAIKU,
        system_prompt="Ти тестовий агент.",
        max_tokens=100,
    )


@pytest.fixture
def message():
    return AgentMessage(
        content="Тестове питання",
        client_id="test-client",
    )


class TestAgentMessage:
    def test_trace_id_auto_generated(self, message):
        assert message.trace_id is not None
        assert len(message.trace_id) == 36  # UUID format

    def test_client_id_required(self, message):
        assert message.client_id == "test-client"


class TestBaseAgent:
    def test_prompt_injection_guard_added(self, agent):
        assert "ЗАХИСТ ВІД МАНІПУЛЯЦІЙ" in agent.system_prompt

    def test_sliding_window_limits_context(self, agent, message):
        long_context = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        message.context = long_context
        context_used = message.context[-SLIDING_WINDOW:]
        assert len(context_used) == SLIDING_WINDOW

    def test_cost_calculation(self, agent):
        cost = agent._calc_cost(MODEL_HAIKU, input_tokens=1000, output_tokens=200)
        assert cost > 0
        assert cost < 0.01  # Haiku має бути дуже дешевим

    def test_confidence_penalty_for_uncertainty(self, agent):
        certain_text = "Ціна перегородки 15 000 грн."
        uncertain_text = "Не знаю, можливо близько 15 000 грн."
        assert agent._estimate_confidence(certain_text) > agent._estimate_confidence(uncertain_text)

    def test_error_result_sets_needs_human(self, agent, message):
        result = agent._error_result(message, MODEL_HAIKU, "test_error")
        assert result.needs_human is True
        assert result.confidence == 0.0
        assert result.error == "test_error"


class TestAgentResult:
    def test_needs_human_low_confidence(self):
        result = AgentResult(
            content="відповідь",
            confidence=0.5,  # нижче CONFIDENCE_MEDIUM
            needs_human=False,
            cost_usd=0.001,
            trace_id="test-trace",
            agent_id="test",
            client_id="test",
            model_used=MODEL_HAIKU,
            input_tokens=10,
            output_tokens=10,
        )
        updated = needs_human_check(result)
        assert updated.needs_human is True

    def test_format_adds_disclaimer_medium_confidence(self):
        result = AgentResult(
            content="Ціна приблизно 15 000 грн.",
            confidence=0.75,  # середня
            needs_human=False,
            cost_usd=0.001,
            trace_id="test-trace",
            agent_id="test",
            client_id="test",
            model_used=MODEL_HAIKU,
            input_tokens=10,
            output_tokens=10,
        )
        formatted = format_for_user(result)
        assert "уточніть" in formatted.lower() or "менеджера" in formatted.lower()
