"""
Orchestrator #7 — Router-патерн.
Haiku класифікує намір → делегує до Sales / Audit / Fix / Design / Train / Review / Multimodal.
session_state в Neon зберігає multi-turn контекст.
"""

import re
from pathlib import Path
from urllib.parse import urlparse

import anthropic
from core import db
from core.intent_classifier import IntentClassifier
from core.message import AgentMessage, AgentResult
from core.base_agent import MODEL_HAIKU
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
        from agents.website_fix.website_fix_agent import WebsiteFixAgent
        from agents.web_design.web_design_agent import WebDesignAgent
        from agents.multimodal_analyst.multimodal_agent import MultimodalAnalystAgent

        self.client_id = client_id
        self._classifier = IntentClassifier()
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
        """Головна точка входу для вільного тексту."""
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

        # ── Multi-turn: чекаємо URL для pipeline ─────────────────────────────
        if awaiting == "url_pipeline":
            url = _extract_url(user_text) or (
                user_text.strip() if user_text.strip().startswith("http") else ""
            )
            if not url and state and state.get("payload", {}).get("suggested_url"):
                confirm = ("так", "yes", "ок", "ok", "давай", "підтвердж", "звісно")
                if any(user_text.lower().strip().startswith(w) for w in confirm):
                    url = state["payload"]["suggested_url"]
            if url:
                actions = state.get("payload", {}).get("actions", ["audit", "fix", "push"])
                await db.clear_session_state(self.client_id, user_id, source)
                return await self._run_pipeline(actions, url, user_id, source)
            return _simple_result(
                'Надішліть URL сайту (https://example.com) або підтвердіть "так" 🔗',
                self.client_id,
            )

        # ── Multi-turn: чекаємо URL (audit / fix / push / rollback) ──────────
        if awaiting in ("url", "url_fix", "url_push", "url_rollback"):
            url = _extract_url(user_text) or (
                user_text.strip() if user_text.strip().startswith("http") else ""
            )
            # Підтвердження запропонованого URL ("так", "ок", "давай" тощо)
            if not url and state and state.get("payload", {}).get("suggested_url"):
                confirm = ("так", "yes", "ок", "ok", "давай", "підтвердж", "звісно")
                if any(user_text.lower().strip().startswith(w) for w in confirm):
                    url = state["payload"]["suggested_url"]
            if url:
                await db.clear_session_state(self.client_id, user_id, source)
                if awaiting == "url":
                    return await self._run_audit(url)
                elif awaiting == "url_fix":
                    return await self._run_fix(url)
                elif awaiting == "url_push":
                    return await self._run_push(url)
                elif awaiting == "url_rollback":
                    return await self._run_rollback(url)
            return _simple_result(
                'Надішліть повне посилання (https://example.com) або підтвердіть "так" 🔗',
                self.client_id,
            )

        # ── Multi-turn: чекаємо URL або бриф для дизайну ─────────────────────
        if awaiting == "url_design":
            url = _extract_url(user_text)
            if url:
                await db.clear_session_state(self.client_id, user_id, source)
                return await self._run_design(url)
            text = user_text.strip()
            if len(text) > 5:
                await db.clear_session_state(self.client_id, user_id, source)
                return await self._run_design(text)
            return _simple_result("Надішліть URL сайту або опишіть бриф 🎨", self.client_id)

        # ── Класифікуємо намір ────────────────────────────────────────────────
        intent = self._classifier.classify(user_text)
        logger.info(
            "[orchestrator] user=%s actions=%s conf=%.2f url=%s",
            user_id, intent.actions, intent.confidence, intent.extracted_url,
        )

        # ── Pipeline (кілька дій за раз) ──────────────────────────────────────
        if is_manager and intent.is_pipeline:
            url = intent.extracted_url
            if url:
                return await self._run_pipeline(intent.actions, url, user_id, source)
            suggested = await self._suggest_last_url()
            payload: dict = {"actions": intent.actions}
            if suggested:
                payload["suggested_url"] = suggested
                await db.set_session_state(
                    self.client_id, user_id, source,
                    active_agent="pipeline", awaiting="url_pipeline", payload=payload,
                )
                return _simple_result(
                    f"▶️ Pipeline: {' → '.join(intent.actions)}\n"
                    f"Для {suggested} (останній)? Підтвердіть \"так\" або надішліть інший URL 🔗",
                    self.client_id,
                )
            await db.set_session_state(
                self.client_id, user_id, source,
                active_agent="pipeline", awaiting="url_pipeline", payload=payload,
            )
            return _simple_result(
                f"▶️ Pipeline: {' → '.join(intent.actions)}\nДля якого сайту? Надішліть URL 🔗",
                self.client_id,
            )

        # ── Клієнтські інтенти ────────────────────────────────────────────────
        if intent.name == "audit":
            if intent.extracted_url:
                await db.set_session_state(
                    self.client_id, user_id, source, active_agent="audit"
                )
                return await self._run_audit(intent.extracted_url)
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

        # ── Менеджерські інтенти ──────────────────────────────────────────────
        elif is_manager and intent.name == "train":
            return await self._run_train()

        elif is_manager and intent.name == "review":
            return await self._run_review()

        elif is_manager and intent.name in ("fix", "push", "rollback"):
            url = intent.extracted_url
            awaiting_key = f"url_{intent.name}"
            labels = {"fix": "генерувати фікси", "push": "деплоїти фікси", "rollback": "відкатити зміни"}
            icons = {"fix": "🔧", "push": "📤", "rollback": "↩️"}
            if not url:
                suggested = await self._suggest_last_url()
                if suggested:
                    await db.set_session_state(
                        self.client_id, user_id, source,
                        active_agent=intent.name, awaiting=awaiting_key,
                        payload={"suggested_url": suggested},
                    )
                    return _simple_result(
                        f"{icons[intent.name]} {labels[intent.name].capitalize()} для "
                        f"{suggested} (останній)?\n"
                        f'Підтвердіть "так" або надішліть інший URL 🔗',
                        self.client_id,
                    )
                await db.set_session_state(
                    self.client_id, user_id, source,
                    active_agent=intent.name, awaiting=awaiting_key,
                )
                return _simple_result("Для якого сайту? Надішліть URL 🔗", self.client_id)
            if intent.name == "fix":
                return await self._run_fix(url)
            elif intent.name == "push":
                return await self._run_push(url)
            else:
                return await self._run_rollback(url)

        elif is_manager and intent.name == "design":
            url = intent.extracted_url
            if url:
                return await self._run_design(url)
            clean = re.sub(
                r"(?i)(зроби\s+дизайн|редизайн|дизайн\s+для|макет\s+для|зроби\s+макет)\s*",
                "", user_text,
            ).strip()
            if len(clean) > 10:
                return await self._run_design(clean)
            await db.set_session_state(
                self.client_id, user_id, source,
                active_agent="design", awaiting="url_design",
            )
            return _simple_result("Надішліть URL сайту або опишіть бриф 🎨", self.client_id)

        # ── Fallback ──────────────────────────────────────────────────────────
        else:
            await db.clear_session_state(self.client_id, user_id, source)
            if is_manager:
                return await self._run_orchestrator_llm(user_text, user_id, source)
            return await self._run_sales(user_text, user_id, source)

    # ── Адаптери ──────────────────────────────────────────────────────────────

    async def _run_orchestrator_llm(
        self, text: str, user_id: str = "", source: str = ""
    ) -> AgentResult:
        system_prompt = _load_orchestrator_prompt()
        history: list[dict] = []
        if user_id and source:
            raw = await db.load_history(self.client_id, user_id, source, limit=6)
            history = [{"role": m["role"], "content": m["content"]} for m in raw]
        messages = history + [{"role": "user", "content": text}]
        try:
            response = self._llm.messages.create(
                model=MODEL_HAIKU,
                max_tokens=512,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=messages,
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

    async def _run_pipeline(
        self,
        actions: list[str],
        url: str,
        user_id: str = "",
        source: str = "",
    ) -> AgentResult:
        """Виконує послідовність дій над одним URL.
        Зупиняється перед push і чекає підтвердження від менеджера.
        """
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        icons = {"audit": "🔍", "fix": "🔧", "push": "📤", "rollback": "↩️", "design": "🎨"}
        pre_push = [a for a in actions if a != "push"]
        has_push = "push" in actions
        total = len(pre_push) + (1 if has_push else 0)
        lines = [f"▶️ Pipeline для {url}: {' → '.join(actions)}\n"]
        step = 0

        for action in pre_push:
            step += 1
            icon = icons.get(action, "⚙️")
            lines.append(f"{icon} Крок {step}/{total} — {action}...")
            try:
                if action == "audit":
                    r = await self._audit.audit(url)
                    if r.get("error"):
                        lines.append(f"❌ {r['error']}")
                        return _simple_result("\n".join(lines), self.client_id, "pipeline")
                    score = r.get("score", "—")
                    first = (r.get("summary_text", "") or "").splitlines()[0] or "Аудит завершено."
                    lines.append(f"✅ score={score} | {first}")
                elif action == "fix":
                    r = await self._fix.fix(url)
                    if r.get("error"):
                        lines.append(f"❌ {r['error']}")
                        return _simple_result("\n".join(lines), self.client_id, "pipeline")
                    first = (r.get("summary_text", "") or "").splitlines()[0] or "Фікси готові."
                    lines.append(f"✅ {first}")
                elif action == "rollback":
                    r = await self._fix.rollback(url)
                    if r.get("error"):
                        lines.append(f"❌ {r['error']}")
                        return _simple_result("\n".join(lines), self.client_id, "pipeline")
                    lines.append(f"✅ {r.get('summary_text', 'Відкат виконано.')}")
                elif action == "design":
                    result = await self._run_design(url)
                    lines.append(f"✅ {result.content.splitlines()[0]}")
                else:
                    lines.append(f"⚠️ Невідома дія: {action}")
            except Exception as e:
                logger.error("[pipeline] action=%s error: %s", action, e)
                lines.append(f"❌ Помилка: {e}")
                return _simple_result("\n".join(lines), self.client_id, "pipeline")

        if has_push:
            # Зберігаємо стан і чекаємо підтвердження
            if user_id and source:
                await db.set_session_state(
                    self.client_id, user_id, source,
                    active_agent="pipeline", awaiting="url_push",
                    payload={"suggested_url": url},
                )
            lines.append(
                f"\n📤 Крок {total}/{total} — push готовий.\n"
                f"Деплоїти фікси на {url}?\n"
                f'Підтвердіть "так" або /push 🚀'
            )
            return _simple_result("\n".join(lines), self.client_id, "pipeline")

        lines.append("\n✅ Pipeline завершено.")
        return _simple_result("\n".join(lines), self.client_id, "pipeline")

    async def _suggest_last_url(self) -> str:
        """Повертає домен останнього fix з БД для smart URL suggestion."""
        try:
            row = await db.get_any_last_fix(self.client_id)
            if row and row.get("url"):
                return urlparse(row["url"]).netloc.replace("www.", "") or row["url"]
        except Exception:
            pass
        return ""
