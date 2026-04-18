import os
from pathlib import Path
from core.base_agent import BaseAgent, MODEL_HAIKU, MODEL_SONNET
from core.message import AgentMessage, AgentResult
from core.logger import get_logger
from agents.sales.knowledge_base import load_kb

logger = get_logger(__name__)

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompt_template.md"
PROMPT_VERSION = "v1.0.0"

SIMPLE_KEYWORDS = [
    "привіт", "hello", "добрий", "hi", "вітаю",
    "дякую", "дякуємо", "до побачення", "бувай",
    "так", "ні", "добре", "окей", "ок",
]


def _is_simple_message(text: str) -> bool:
    """Haiku для коротких/простих повідомлень, Sonnet для складних."""
    text_lower = text.lower().strip()
    if len(text_lower) < 30:
        return True
    return any(kw in text_lower for kw in SIMPLE_KEYWORDS)


def _parse_flags(content: str) -> tuple[str, bool, float]:
    """
    Витягує службові мітки з відповіді агента.
    Повертає: (чистий текст, needs_human, confidence)
    """
    needs_human = "[NOTIFY_MANAGER]" in content
    low_confidence = "[LOW_CONFIDENCE]" in content

    clean = (
        content
        .replace("[NOTIFY_MANAGER]", "")
        .replace("[LOW_CONFIDENCE]", "")
        .strip()
    )

    confidence = 0.65 if low_confidence else (0.75 if needs_human else 0.90)
    return clean, needs_human, confidence


class SalesAgent(BaseAgent):
    """
    Agent #1 — Telegram Sales Agent.
    Завантажує Knowledge Base з Google Sheets per client_id.
    Використовує Haiku для простих повідомлень, Sonnet для складних.
    """

    def __init__(self, client_id: str, client_name: str, kb_sheet_id: str):
        self.client_id = client_id
        self.client_name = client_name
        self.kb_sheet_id = kb_sheet_id
        self._kb_cache: str | None = None

        # Завантажуємо промпт-шаблон
        template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")

        # Завантажуємо KB і підставляємо у шаблон
        kb_data = self._load_kb()
        system_prompt = (
            template
            .replace("{{CLIENT_NAME}}", client_name)
            .replace("{{KB_DATA}}", kb_data)
        )

        super().__init__(
            agent_id=f"sales-agent-{client_id}-v1",
            model=MODEL_SONNET,
            system_prompt=system_prompt,
            max_tokens=600,
            fallback_model=MODEL_HAIKU,
            prompt_version=PROMPT_VERSION,
        )

    def _load_kb(self) -> str:
        if self._kb_cache is None:
            self._kb_cache = load_kb(self.client_id, self.kb_sheet_id)
            logger.info(f"[{self.client_id}] KB завантажена у Sales Agent")
        return self._kb_cache

    def reload_kb(self) -> None:
        """Примусове оновлення KB (наприклад після зміни таблиці)."""
        self._kb_cache = None
        self._load_kb()
        logger.info(f"[{self.client_id}] KB перезавантажена")

    def run(self, message: AgentMessage) -> AgentResult:
        # Вибір моделі залежно від складності повідомлення
        model = MODEL_HAIKU if _is_simple_message(message.content) else MODEL_SONNET

        result = self._call_api(message, model=model)

        if result.error:
            return result

        # Парсимо службові мітки з відповіді
        clean_content, needs_human, confidence = _parse_flags(result.content)

        result.content = clean_content
        result.confidence = confidence
        result.needs_human = needs_human

        if needs_human:
            logger.info(
                f"[{self.client_id}] Sales Agent: ескалація до менеджера "
                f"(trace_id={result.trace_id})"
            )

        return result


def create_sales_agent(client_id: str | None = None) -> SalesAgent:
    """
    Фабрична функція. Читає конфіг клієнта з env-змінних.
    """
    client_id = client_id or os.getenv("DEFAULT_CLIENT_ID", "dev")
    client_name = os.getenv(f"CLIENT_NAME_{client_id.upper()}", client_id)
    kb_sheet_id = os.getenv(f"KB_SHEET_ID_{client_id.upper()}")

    if not kb_sheet_id:
        raise ValueError(
            f"KB_SHEET_ID_{client_id.upper()} не знайдено в .env. "
            "Додай ID Google Sheets таблиці клієнта."
        )

    return SalesAgent(
        client_id=client_id,
        client_name=client_name,
        kb_sheet_id=kb_sheet_id,
    )
