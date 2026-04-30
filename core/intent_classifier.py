"""
IntentClassifier — Haiku-класифікатор намірів для Orchestrator.
Повертає список дій (actions) замість одного інтенту,
що дозволяє виконувати pipeline без додавання нових прикладів у промпт.
"""

import json
import re
from dataclasses import dataclass, field

import anthropic

from core.base_agent import MODEL_HAIKU
from core.logger import get_logger

logger = get_logger(__name__)

_URL_RE = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+', re.IGNORECASE)

_SYSTEM = """Ти — диспетчер AI-платформи. Розклади запит на список дій.

Доступні дії (виконуються у зазначеному порядку):
- audit    — SEO-аудит сайту
- fix      — генерація SEO-фіксів
- push     — деплой фіксів на сервер
- rollback — відкат змін на сервері
- design   — генерація дизайн-пакету / редизайн
- train    — аналіз якості діалогів, тренування агента
- review   — статистика і перегляд розмов
- analyze  — аналіз фото, PDF, зображення
- sales    — консультація, ціни, загальне питання

Правила:
- Для запитів типу "аудит + фікси" або "зроби все по SEO" → кілька дій у правильному порядку
- Деплой (push) іде ПІСЛЯ fix; аудит (audit) іде ДО fix
- Якщо запит незрозумілий або не стосується платформи → ["sales"]
- URL якщо є — витягни окремо, інакше ""

Відповідай ТІЛЬКИ JSON без пояснень:
{"actions": ["action1", "action2"], "url": "", "confidence": 0.0}

Приклади:
- "скільки коштує перегородка?" → {"actions": ["sales"], "url": "", "confidence": 0.97}
- "зроби аудит https://example.com" → {"actions": ["audit"], "url": "https://example.com", "confidence": 0.98}
- "згенеруй SEO-фікси" → {"actions": ["fix"], "url": "", "confidence": 0.95}
- "залий фікси на сервер" → {"actions": ["push"], "url": "", "confidence": 0.95}
- "аудит і фікси для example.com" → {"actions": ["audit", "fix"], "url": "https://example.com", "confidence": 0.96}
- "аудит + фікси + деплой" → {"actions": ["audit", "fix", "push"], "url": "", "confidence": 0.97}
- "повний SEO для etalhome" → {"actions": ["audit", "fix", "push"], "url": "https://etalhome.com", "confidence": 0.97}
- "зроби все по SEO" → {"actions": ["audit", "fix", "push"], "url": "", "confidence": 0.95}
- "SEO від А до Я" → {"actions": ["audit", "fix", "push"], "url": "", "confidence": 0.96}
- "фікси і задеплой" → {"actions": ["fix", "push"], "url": "", "confidence": 0.96}
- "редизайн etalhome.com" → {"actions": ["design"], "url": "https://etalhome.com", "confidence": 0.97}
- "відкати зміни" → {"actions": ["rollback"], "url": "", "confidence": 0.96}
- "проаналізуй діалоги агента" → {"actions": ["train"], "url": "", "confidence": 0.96}
- "покажи статистику розмов" → {"actions": ["review"], "url": "", "confidence": 0.97}
- "проаналізуй це фото" → {"actions": ["analyze"], "url": "", "confidence": 0.95}"""


@dataclass
class Intent:
    actions: list[str]      # впорядкований список дій
    confidence: float
    extracted_url: str      # URL знайдений у тексті (може бути порожній)

    @property
    def name(self) -> str:
        """Перша дія — для сумісності з існуючим роутингом."""
        return self.actions[0] if self.actions else "unknown"

    @property
    def is_pipeline(self) -> bool:
        return len(self.actions) > 1


class IntentClassifier:
    def __init__(self) -> None:
        self._client = anthropic.Anthropic()

    def classify(self, text: str) -> Intent:
        extracted_url = self._extract_url(text)

        try:
            response = self._client.messages.create(
                model=MODEL_HAIKU,
                max_tokens=80,
                system=[{
                    "type": "text",
                    "text": _SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": text[:500]}],
            )
            raw = response.content[0].text.strip()
            start = raw.find("{")
            if start != -1:
                raw = raw[start:]
            data = json.loads(raw)
            actions = data.get("actions", ["sales"])
            if not isinstance(actions, list) or not actions:
                actions = ["sales"]
            # URL з JSON має пріоритет над витягнутим з тексту
            url_from_json = data.get("url", "").strip()
            if url_from_json:
                extracted_url = url_from_json
            confidence = float(data.get("confidence", 0.5))
        except Exception as exc:
            logger.warning("IntentClassifier error: %s → fallback sales", exc)
            actions = ["sales"]
            confidence = 0.5

        return Intent(actions=actions, confidence=confidence, extracted_url=extracted_url)

    @staticmethod
    def _extract_url(text: str) -> str:
        match = _URL_RE.search(text)
        return match.group(0) if match else ""
