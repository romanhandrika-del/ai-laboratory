"""
Orchestrator #7 — Router-патерн.
Haiku класифікує намір → делегує до Sales / Audit / Multimodal.
session_state в Neon зберігає multi-turn контекст.
"""

import re
from pathlib import Path
import anthropic
from core import db
from core.intent_classifier import IntentClassifier
from core.message import AgentMessage, AgentResult
from core.base_agent import MODEL_HAIKU, MODEL_SONNET
from core.logger import get_logger

logger = get_logger(__name__)

_URL_RE = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+', re.IGNORECASE)

_ORCHESTRATOR_PROMPT_PATH = Path(__file__).parent.parent / "agents" / "orchestrator.md"


def _load_orchestrator_prompt() -> str:
    if _ORCHESTRATOR_PROMPT_PATH.exists():
        return _ORCHESTRATOR_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return "Ти — оркестрант AI Laboratory. Відповідай українською."


def _extract_url(text: str) -> str:
    match = _URL_RE.search(text)
    return match.group(0) if match else ""


def _simple_result(content: str, client_id: str, agent_id: str = "orchestrator") -> AgentResult:
    return AgentResult(
        content=content,
        confidence=1.0,
        needs_human=False,
        cost_usd=0.0,
        trace_id="",
        agent_id=agent_id,
        client_id=client_id,
        model_used="",
        input_tokens=0,
        output_tokens=0,
    )


class OrchestratorAgent:
    """
    Центральний Router AI Laboratory.
    Приймає вільний текст → класифікує Haiku → виконує відповідний агент.
    Slash-команди (/audit, /fix, /design...) обходять orchestrator через fast-path у bot.py.
    """

    def __init__(self, client_id: str, sales_agent) -> None:
        from agents.website_audit.website_audit_agent import WebsiteAuditAgent
        from agents.multimodal_analyst.multimodal_agent import MultimodalAnalystAgent

        self.client_id = client_id
        self._classifier = IntentClassifier()
        self._sales = sales_agent
        self._audit = WebsiteAuditAgent(client_id)
        self._multimodal = MultimodalAnalystAgent(client_id)
        self._llm = anthropic.Anthropic()

    async def route(
        self,
        user_text: str,
        user_id: str,
        source: str,
        is_manager: bool = False,
    ) -> AgentResult:
        """
        Головна точка входу для вільного тексту.
        Фото/PDF обробляються через fast-path handle_analyze у bot.py.
        """
        try:
            return await self._route(user_text, user_id, source, is_manager)
        except Exception as exc:
            logger.error("[orchestrator] unhandled exception: %s", exc, exc_info=True)
            return _simple_result(
                "Вибачте, сталася помилка. Спробуйте ще раз 🙏",
                self.client_id,
            )

    async def _route(
        self,
        user_text: str,
        user_id: str,
        source: str,
        is_manager: bool = False,
    ) -> AgentResult:
        state = await db.get_session_state(self.client_id, user_id, source)
        awaiting = state.get("awaiting") if state else None

        # ── Чекаємо URL після "зроби аудит" без посилання ───────────────────
        if awaiting == "url":
            url = _extract_url(user_text) or (user_text.strip() if user_text.startswith("http") else "")
            if url:
                await db.clear_session_state(self.client_id, user_id, source)
                return await self._run_audit(url)
            return _simple_result(
                "Будь ласка, надішліть повне посилання на сайт (наприклад: https://example.com)",
                self.client_id,
            )

        # ── Класифікуємо намір через Haiku ──────────────────────────────────
        intent = self._classifier.classify(user_text)
        logger.info(
            "[orchestrator] user=%s intent=%s conf=%.2f url=%s",
            user_id, intent.name, intent.confidence, intent.extracted_url,
        )

        if intent.name == "audit":
            if intent.extracted_url:
                await db.set_session_state(
                    self.client_id, user_id, source, active_agent="audit"
                )
                return await self._run_audit(intent.extracted_url)
            else:
                await db.set_session_state(
                    self.client_id, user_id, source,
                    active_agent="audit", awaiting="url",
                )
                return _simple_result("Надішліть URL сайту для аудиту 🔍", self.client_id)

        elif intent.name == "analyze":
            return _simple_result(
                "Для аналізу фото або PDF — надішліть файл разом з командою /analyze 📎",
                self.client_id,
            )

        else:  # sales або unknown
            await db.clear_session_state(self.client_id, user_id, source)
            if is_manager:
                return await self._run_orchestrator_llm(user_text)
            return await self._run_sales(user_text, user_id, source)

    # ── Адаптери ─────────────────────────────────────────────────────────────

    async def _run_orchestrator_llm(self, text: str) -> AgentResult:
        system_prompt = _load_orchestrator_prompt()
        try:
            response = self._llm.messages.create(
                model=MODEL_HAIKU,
                max_tokens=512,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": text}],
            )
            content = response.content[0].text
        except Exception as exc:
            logger.error("[orchestrator] LLM fallback error: %s", exc)
            content = "Вибачте, виникла помилка. Спробуйте ще раз."
        return _simple_result(content, self.client_id, agent_id="orchestrator")

    async def _run_sales(self, text: str, user_id: str, source: str) -> AgentResult:
        history = await db.load_history(self.client_id, str(user_id), source, limit=8)
        return self._sales.run(AgentMessage(
            content=text,
            client_id=self.client_id,
            context=history,
            metadata={"user_id": user_id, "source": source},
        ))

    async def _run_audit(self, url: str) -> AgentResult:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        result = await self._audit.audit(url)
        if result.get("error"):
            return _simple_result(
                f"❌ Помилка аудиту: {result['error']}",
                self.client_id, "website-audit-v1",
            )
        return AgentResult(
            content=result.get("summary_text", "Аудит завершено."),
            confidence=0.9,
            needs_human=False,
            cost_usd=0.0,
            trace_id="",
            agent_id="website-audit-v1",
            client_id=self.client_id,
            model_used=MODEL_HAIKU,
            input_tokens=0,
            output_tokens=0,
            metadata={
                "score": result.get("score", 0),
                "report_md_path": str(result.get("report_md_path", "")),
            },
        )
