"""
IntentClassifier — Haiku-класифікатор намірів для Orchestrator.
Closed-set: sales | audit | analyze | unknown
"""

import json
import re
from dataclasses import dataclass

import anthropic

from core.base_agent import MODEL_HAIKU
from core.logger import get_logger

logger = get_logger(__name__)

_URL_RE = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+', re.IGNORECASE)

_SYSTEM = """Ти — диспетчер AI-платформи. Класифікуй вхідне повідомлення.

Класи:
- sales: питання про товар, ціну, доставку, розміри, матеріали, замовлення, консультація, загальне вітання
- audit: прохання перевірити / оцінити / зробити аудит сайту (може містити URL)
- analyze: прохання проаналізувати фото, зображення, PDF, документ, файл
- train: аналіз якості діалогів агента, тренування — ПЕРСПЕКТИВА (що змінити у поведінці)
- review: перегляд статистики, огляд розмов, "останні діалоги" — РЕТРОСПЕКТИВА (що вже відбулось)
- fix: генерація SEO-фіксів для сайту (може містити URL)
- push: деплой/заливка фіксів на сервер (може містити URL)
- rollback: відкат змін, відновлення попередньої версії плагіну
- design: генерація дизайн-пакету, редизайн сайту, HTML-макет
- unknown: все що не підходить вище

Відповідай ТІЛЬКИ JSON без пояснень:
{"intent": "sales|audit|analyze|train|review|fix|push|rollback|design|unknown", "confidence": 0.0}

Приклади:
- "скільки коштує перегородка 2м?" → {"intent": "sales", "confidence": 0.97}
- "перевір мій сайт https://example.com" → {"intent": "audit", "confidence": 0.98}
- "зроби аудит сайту" → {"intent": "audit", "confidence": 0.93}
- "проаналізуй це фото" → {"intent": "analyze", "confidence": 0.95}
- "привіт" → {"intent": "sales", "confidence": 0.85}
- "що таке SEO?" → {"intent": "sales", "confidence": 0.72}
- "проаналізуй діалоги агента" → {"intent": "train", "confidence": 0.96}
- "агент відповідає грубо, виправ" → {"intent": "train", "confidence": 0.95}
- "покращ відповіді бота" → {"intent": "train", "confidence": 0.93}
- "який останній діалог?" → {"intent": "review", "confidence": 0.94}
- "покажи статистику розмов" → {"intent": "review", "confidence": 0.97}
- "скільки ескалацій сьогодні?" → {"intent": "review", "confidence": 0.95}
- "зроби фікси для etalhome.com" → {"intent": "fix", "confidence": 0.96}
- "виправ помилки на сайті" → {"intent": "fix", "confidence": 0.93}
- "згенеруй SEO-фікси" → {"intent": "fix", "confidence": 0.95}
- "залий фікси на сервер" → {"intent": "push", "confidence": 0.95}
- "задеплой зміни https://etalhome.com" → {"intent": "push", "confidence": 0.97}
- "деплой фіксів" → {"intent": "push", "confidence": 0.94}
- "відкати зміни на сайті" → {"intent": "rollback", "confidence": 0.96}
- "відновити попередню версію плагіну" → {"intent": "rollback", "confidence": 0.94}
- "зроби дизайн для сайту" → {"intent": "design", "confidence": 0.95}
- "редизайн etalhome.com" → {"intent": "design", "confidence": 0.97}
- "зроби макет лендінгу" → {"intent": "design", "confidence": 0.94}"""


@dataclass
class Intent:
    name: str           # sales | audit | analyze | train | review | fix | push | rollback | design | unknown
    confidence: float
    extracted_url: str  # URL знайдений у тексті (може бути порожній)


class IntentClassifier:
    def __init__(self) -> None:
        self._client = anthropic.Anthropic()

    def classify(self, text: str) -> Intent:
        extracted_url = self._extract_url(text)

        try:
            response = self._client.messages.create(
                model=MODEL_HAIKU,
                max_tokens=40,
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
            name = data.get("intent", "unknown")
            confidence = float(data.get("confidence", 0.5))
        except Exception as exc:
            logger.warning("IntentClassifier error: %s → fallback sales", exc)
            name = "sales"
            confidence = 0.5

        return Intent(name=name, confidence=confidence, extracted_url=extracted_url)

    @staticmethod
    def _extract_url(text: str) -> str:
        match = _URL_RE.search(text)
        return match.group(0) if match else ""
