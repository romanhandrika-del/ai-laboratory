"""
Orchestrator #7 — Agentic loop.
Sonnet з 8 інструментами самостійно вирішує що викликати → agentic loop.
Для менеджера: agentic loop. Для клієнта: Sales Agent.
"""

import json
import time
import re
from pathlib import Path
from urllib.parse import urlparse

import anthropic
from core import db
from core.message import AgentMessage, AgentResult
from core.logger import get_logger

# ── Prompt cache ──────────────────────────────────────────────────────────────
_CACHED_PROMPT: str | None = None
_CACHE_TS: float = 0.0
_CACHE_TTL: int = 600  # 10 хвилин


def invalidate_orchestrator_prompt_cache() -> None:
    global _CACHED_PROMPT, _CACHE_TS
    _CACHED_PROMPT = None
    _CACHE_TS = 0.0

logger = get_logger(__name__)

MODEL_SONNET = "claude-sonnet-4-6"

_ORCHESTRATOR_PROMPT_PATH = Path(__file__).parent.parent / "agents" / "orchestrator.md"

_PUSH_TRIGGERS = ("задеплой", "залий", "пушимо", "деплой", "deploy", "/push")
_ROLLBACK_TRIGGERS = ("відкати", "rollback", "відкат", "скасуй деплой", "/rollback")
_CONFIRM_WORDS = ("так", "yes", "ок", "ok", "давай", "підтвердж", "звісно")

MAX_TURNS = 8

_MANAGER_TOOLS = [
    {
        "name": "run_audit",
        "description": "SEO-аудит сайту. Повертає score та список проблем.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL сайту (https://...)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "run_fix",
        "description": "Генерує SEO-фікси для сайту (не деплоїть, тільки готує файл).",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL сайту"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "run_push",
        "description": (
            "Деплоїть готові SEO-фікси на сайт. ДЕСТРУКТИВНА дія. "
            "Викликати ТІЛЬКИ після явного підтвердження менеджера "
            "('задеплой', 'залий', 'пушимо') або відповіді 'так' на твоє запитання."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL сайту"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "run_rollback",
        "description": (
            "Відкатує останній деплой. ДЕСТРУКТИВНА дія. "
            "Викликати ТІЛЬКИ після явного підтвердження менеджера "
            "('відкати', 'rollback') або відповіді 'так' на твоє запитання."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL сайту"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "run_design",
        "description": "Генерує дизайн-пакет для сайту або за текстовим брифом.",
        "input_schema": {
            "type": "object",
            "properties": {
                "input_text": {
                    "type": "string",
                    "description": "URL сайту або текстовий бриф",
                },
            },
            "required": ["input_text"],
        },
    },
    {
        "name": "run_train",
        "description": "Тренування Sales Agent — аналізує діалоги, записує пропозиції у Sheets.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "run_review",
        "description": "Огляд статистики та останніх розмов Sales Agent.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_last_url",
        "description": "Повертає URL останнього сайту з яким працювали (з БД).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def _load_orchestrator_prompt() -> str:
    if _ORCHESTRATOR_PROMPT_PATH.exists():
        return _ORCHESTRATOR_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return "Ти — оркестрант AI Laboratory. Відповідай українською."


async def _load_orchestrator_prompt_cached(client_id: str) -> str:
    """DB-first with 10-min cache; falls back to file."""
    global _CACHED_PROMPT, _CACHE_TS
    if _CACHED_PROMPT and (time.monotonic() - _CACHE_TS) < _CACHE_TTL:
        return _CACHED_PROMPT
    try:
        prompt = await db.get_agent_prompt(client_id, "orchestrator")
        if prompt:
            _CACHED_PROMPT = prompt
            _CACHE_TS = time.monotonic()
            return prompt
    except Exception as e:
        logger.warning("[orchestrator] DB prompt lookup failed: %s", e)
    return _load_orchestrator_prompt()


def _extract_text_from_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                parts.append(b.get("text", ""))
            elif hasattr(b, "text"):
                parts.append(b.text)
        return " ".join(filter(None, parts))
    return ""


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
    Центральний агент AI Laboratory.
    Менеджер: Sonnet agentic loop з 8 інструментами.
    Клієнт: Sales Agent.
    """

    def __init__(self, client_id: str, sales_agent) -> None:
        from agents.website_audit.website_audit_agent import WebsiteAuditAgent
        from agents.website_fix.website_fix_agent import WebsiteFixAgent
        from agents.web_design.web_design_agent import WebDesignAgent
        from agents.multimodal_analyst.multimodal_agent import MultimodalAnalystAgent

        self.client_id = client_id
        self._sales = sales_agent
        self._audit = WebsiteAuditAgent(client_id)
        self._fix = WebsiteFixAgent(client_id)
        self._design = WebDesignAgent(client_id)
        self._multimodal = MultimodalAnalystAgent(client_id)
        self._llm = anthropic.Anthropic()

    async def route(
        self,
        user_text: str,
        user_id: str,
        source: str,
        is_manager: bool = False,
    ) -> AgentResult:
        try:
            if is_manager:
                return await self._run_manager_loop(user_text, user_id, source)
            return await self._run_sales(user_text, user_id, source)
        except Exception as exc:
            logger.error("[orchestrator] unhandled exception: %s", exc, exc_info=True)
            return _simple_result(
                "Вибачте, сталася помилка. Спробуйте ще раз 🙏",
                self.client_id,
            )

    async def _run_manager_loop(
        self,
        user_text: str,
        user_id: str,
        source: str,
    ) -> AgentResult:
        system_prompt = await _load_orchestrator_prompt_cached(self.client_id)
        raw_history = await db.load_history(self.client_id, user_id, source, limit=6)
        messages = [{"role": m["role"], "content": m["content"]} for m in raw_history]
        messages.append({"role": "user", "content": user_text})

        loop_start = time.monotonic()
        all_tool_names: list[str] = []

        for turn in range(MAX_TURNS):
            response = self._llm.messages.create(
                model=MODEL_SONNET,
                max_tokens=1024,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                tools=_MANAGER_TOOLS,
                messages=messages,
            )

            if response.stop_reason == "end_turn":
                text = next(
                    (b.text for b in response.content if hasattr(b, "text")), ""
                )
                logger.info(
                    "[orchestrator] DONE user=%s turns=%d stop=%s tools=%s total=%.1fs",
                    user_id, turn + 1, response.stop_reason,
                    all_tool_names, time.monotonic() - loop_start,
                )
                return _simple_result(text, self.client_id)

            if response.stop_reason != "tool_use":
                break

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []

            for block in response.content:
                if block.type != "tool_use":
                    continue

                name = block.name
                args = block.input
                all_tool_names.append(name)

                t0 = time.monotonic()
                result_text = await self._execute_tool(name, args, user_text, messages)
                elapsed = time.monotonic() - t0

                logger.info(
                    "[orchestrator] manager_loop user=%s turn=%d/%d tool=%s args=%s → %d chars, %.1fs",
                    user_id, turn + 1, MAX_TURNS, name,
                    json.dumps(args)[:120], len(result_text), elapsed,
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })

            messages.append({"role": "user", "content": tool_results})

        logger.warning("[orchestrator] loop exhausted user=%s", user_id)
        return _simple_result(
            "Не вдалося завершити задачу. Спробуйте ще раз.",
            self.client_id,
        )

    async def _execute_tool(
        self,
        name: str,
        args: dict,
        user_text: str,
        messages: list,
    ) -> str:
        try:
            if name == "run_audit":
                r = await self._run_audit(args.get("url", ""))
                return r.content
            elif name == "run_fix":
                r = await self._run_fix(args.get("url", ""))
                return r.content
            elif name == "run_push":
                if not self._is_destructive_confirmed(user_text, "push", messages):
                    return "⚠️ Для деплою потрібне явне підтвердження: скажіть 'задеплой' або 'залий'."
                r = await self._run_push(args.get("url", ""))
                return r.content
            elif name == "run_rollback":
                if not self._is_destructive_confirmed(user_text, "rollback", messages):
                    return "⚠️ Для відкату потрібне явне підтвердження: скажіть 'відкати'."
                r = await self._run_rollback(args.get("url", ""))
                return r.content
            elif name == "run_design":
                r = await self._run_design(args.get("input_text", ""))
                return r.content
            elif name == "run_train":
                r = await self._run_train()
                return r.content
            elif name == "run_review":
                r = await self._run_review()
                return r.content
            elif name == "get_last_url":
                url = await self._suggest_last_url()
                return url if url else "URL не знайдено в БД."
            else:
                return f"Невідомий інструмент: {name}"
        except Exception as e:
            logger.error("[orchestrator] _execute_tool name=%s error: %s", name, e)
            return f"❌ Помилка {name}: {e}"

    def _is_destructive_confirmed(
        self, user_text: str, action: str, messages: list
    ) -> bool:
        text_lower = user_text.lower()
        triggers = _PUSH_TRIGGERS if action == "push" else _ROLLBACK_TRIGGERS

        if any(kw in text_lower for kw in triggers):
            return True

        # Перевіряємо, чи user підтверджує попереднє запитання асистента
        if any(w in text_lower for w in _CONFIRM_WORDS):
            push_kws = ("деплої", "push", "залит", "залий", "задеплоїти")
            rollback_kws = ("відкат", "rollback")
            question_kws = push_kws if action == "push" else rollback_kws

            for msg in reversed(messages):
                if msg.get("role") != "assistant":
                    continue
                content_text = _extract_text_from_content(msg.get("content", ""))
                if not content_text.strip():
                    continue  # пропускаємо tool-only блоки
                if any(kw in content_text.lower() for kw in question_kws):
                    return True
                break

        return False

    # ── Адаптери ──────────────────────────────────────────────────────────────

    async def _run_sales(self, text: str, user_id: str, source: str) -> AgentResult:
        import asyncio
        from agents.sales.memory import should_update_summary, update_summary
        history = await db.load_history(self.client_id, str(user_id), source, limit=8)
        summary = await db.get_summary(self.client_id, str(user_id), source)
        result = self._sales.run(AgentMessage(
            content=text,
            client_id=self.client_id,
            context=history,
            metadata={"user_id": user_id, "source": source, "client_memory": summary},
        ))
        if await should_update_summary(self.client_id, str(user_id), source):
            asyncio.create_task(update_summary(self.client_id, str(user_id), source))
        return result

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
            model_used=MODEL_SONNET,
            input_tokens=0,
            output_tokens=0,
            metadata={
                "score": result.get("score", 0),
                "report_md_path": str(result.get("report_md_path", "")),
            },
        )

    async def _run_fix(self, url: str) -> AgentResult:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            result = await self._fix.fix(url)
            if result.get("error"):
                return _simple_result(f"❌ {result['error']}", self.client_id, "website-fix-v1")
            return _simple_result(
                result.get("summary_text", "✅ Фікси згенеровано."),
                self.client_id, "website-fix-v1",
            )
        except Exception as e:
            logger.error("[orchestrator] _run_fix error: %s", e)
            return _simple_result(f"❌ Помилка: {e}", self.client_id, "website-fix-v1")

    async def _run_push(self, url: str) -> AgentResult:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            result = await self._fix.push(url)
            if result.get("error"):
                return _simple_result(f"❌ {result['error']}", self.client_id, "website-fix-v1")
            return _simple_result(
                result.get("summary_text", "✅ Деплой завершено."),
                self.client_id, "website-fix-v1",
            )
        except Exception as e:
            logger.error("[orchestrator] _run_push error: %s", e)
            return _simple_result(f"❌ Помилка: {e}", self.client_id, "website-fix-v1")

    async def _run_rollback(self, url: str) -> AgentResult:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            result = await self._fix.rollback(url)
            if result.get("error"):
                return _simple_result(f"❌ {result['error']}", self.client_id, "website-fix-v1")
            return _simple_result(
                result.get("summary_text", "✅ Rollback виконано."),
                self.client_id, "website-fix-v1",
            )
        except Exception as e:
            logger.error("[orchestrator] _run_rollback error: %s", e)
            return _simple_result(f"❌ Помилка: {e}", self.client_id, "website-fix-v1")

    async def _run_design(self, input_text: str) -> AgentResult:
        if (
            not input_text.startswith(("http://", "https://"))
            and not input_text.startswith("brief:")
            and "." in input_text
            and " " not in input_text
            and len(input_text) < 50
        ):
            input_text = "https://" + input_text
        try:
            result = await self._design.design(input_text)
            if result.get("error"):
                return _simple_result(f"❌ {result['error']}", self.client_id, "web-design-v1")
            return _simple_result(
                result.get("summary_text", "✅ Дизайн-пакет готово."),
                self.client_id, "web-design-v1",
            )
        except Exception as e:
            logger.error("[orchestrator] _run_design error: %s", e)
            return _simple_result(f"❌ Помилка: {e}", self.client_id, "web-design-v1")

    async def _run_train(self) -> AgentResult:
        from agents.sales.trainer import run_training
        try:
            result = await run_training(self.client_id, 30, only_low=False)
            if result.get("error"):
                return _simple_result(
                    f"❌ Помилка тренування: {result['error']}", self.client_id, "trainer"
                )
            suggestions = result.get("suggestions", [])
            written = result.get("written", 0)
            if not suggestions:
                return _simple_result(
                    result.get("msg", "✅ Все добре — пропозицій немає."),
                    self.client_id, "trainer",
                )
            lines = [f"🧠 Тренування завершено\nЗаписано у Sheets: {written} пропозицій\n"]
            for s in suggestions[:8]:
                prio = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(s.get("priority", ""), "⚪")
                lines.append(
                    f"{prio} {s.get('type', '')} — {s.get('priority', '')}\n"
                    f"Проблема: {s.get('problem', '')}\n"
                    f"Пропозиція: {s.get('suggestion', '')}\n"
                )
            if len(suggestions) > 8:
                lines.append(f"...та ще {len(suggestions) - 8} пропозицій у Sheets")
            text = "\n".join(lines)
            if len(text) > 4000:
                text = text[:3950] + "\n...обрізано"
            return _simple_result(text, self.client_id, "trainer")
        except Exception as e:
            logger.error("[orchestrator] _run_train error: %s", e)
            return _simple_result(f"❌ Помилка тренування: {e}", self.client_id, "trainer")

    async def _run_review(self) -> AgentResult:
        try:
            stats = await db.get_dialogs_stats(self.client_id)
            rows = await db.get_dialogs_review(self.client_id, limit=10, only_low=False)
            header = (
                f"📊 Sales Agent — огляд розмов\n"
                f"Всього: {stats.get('total', 0)} | "
                f"Avg confidence: {stats.get('avg_confidence', 0)} | "
                f"Ескалацій: {stats.get('escalations', 0)} | "
                f"Витрати: ${stats.get('total_cost', 0)}\n"
                + "─" * 30 + "\n"
            )
            if not rows:
                return _simple_result(header + "Розмов поки немає.", self.client_id, "review")
            lines = [header]
            for r in rows:
                flag = "🔴" if r["needs_human"] else ("🟡" if r["confidence"] < 0.75 else "🟢")
                ts = r["created_at"][:16].replace("T", " ")
                lines.append(
                    f"{flag} {ts} | conf: {r['confidence']:.2f}\n"
                    f"👤 {r['user_msg'][:80]}\n"
                    f"🤖 {r['bot_reply'][:120]}\n"
                )
            text = "\n".join(lines)
            if len(text) > 4000:
                text = text[:3950] + "\n...обрізано"
            return _simple_result(text, self.client_id, "review")
        except Exception as e:
            logger.error("[orchestrator] _run_review error: %s", e)
            return _simple_result(f"❌ Помилка: {e}", self.client_id, "review")

    async def _suggest_last_url(self) -> str:
        try:
            row = await db.get_any_last_fix(self.client_id)
            if row and row.get("url"):
                return urlparse(row["url"]).netloc.replace("www.", "") or row["url"]
        except Exception:
            pass
        return ""
