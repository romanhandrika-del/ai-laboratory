from core.message import AgentResult

CONFIDENCE_HIGH = 0.85
CONFIDENCE_MEDIUM = 0.70


def needs_human_check(result: AgentResult) -> AgentResult:
    """Автоматично виставляє needs_human на основі confidence."""
    if result.confidence < CONFIDENCE_MEDIUM:
        result.needs_human = True
    return result


def format_for_user(result: AgentResult) -> str:
    """Форматує відповідь для клієнта з disclaimer при середній впевненості."""
    if result.needs_human:
        return (
            f"{result.content}\n\n"
            "Для уточнення деталей — зв'яжіться з нашим менеджером."
        )
    if result.confidence < CONFIDENCE_HIGH:
        return (
            f"{result.content}\n\n"
            "_Будь ласка, уточніть актуальну інформацію у менеджера._"
        )
    return result.content
