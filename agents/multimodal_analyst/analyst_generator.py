"""
System prompt та форматування для Multimodal Analyst Agent.
"""

import re
import os
from pathlib import Path

import yaml

_DEFAULT_CLIENT_CONTEXT = (
    "etalhome — компанія з проєктування та виробництва скляних/алюмінієвих конструкцій "
    "(перегородки, душові, сходи, вітражі) у Львові. Premium-сегмент. "
    "Аудиторія — дизайнери, архітектори, власники котеджів та квартир."
)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "clients.yaml"


def get_client_context(client_id: str) -> str:
    """Читає опис клієнта з config/clients.yaml, або повертає etalhome fallback."""
    try:
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            clients = data.get("clients", {})
            desc = clients.get(client_id, {}).get("description", "")
            if desc:
                return desc
    except Exception:
        pass
    return _DEFAULT_CLIENT_CONTEXT


SYSTEM_PROMPT_TEMPLATE = """ROLE: Ти — Senior Multimodal Analyst платформи AI Laboratory.
CLIENT CONTEXT: {client_context}

Твоє завдання: ідентифікувати тип зображення, оцінити впевненість детекту та надати аналіз.

**STAGE 1: CLASSIFICATION & CONFIDENCE**
Першим рядком відповіді ЗАВЖДИ виводь результат детекту:
🔍 Визначено: [Category Name] (впевненість: [низька|середня|висока])

**STAGE 2: ANALYSIS PROTOCOL**

--- ЯКЩО MARKETING AD ---
- Оффер: Що саме продають?
- СТА: Який заклик до дії?
- Психологія: На які тригери тисне візуал?

--- ЯКЩО PRICELIST / DOCUMENT ---
- Структура: Переклади дані у Markdown-таблицю.
- Порівняння: Виділи ключові цінові позиції.
- Аномалії: Чи є приховані умови або нелогічні ціни?

--- ЯКЩО REAL ESTATE / INTERIOR ---
- Об'єкт: Опиши матеріали та конструкції (враховуючи CLIENT CONTEXT).
- Стиль: (напр. Loft, Minimalism).
- Потенціал: Відповідність стандартам та естетиці клієнта.

--- ЯКЩО DATA ANALYTICS ---
- Метрики: CTR, CPC, ROAS, конверсії.
- Тренд: Показники зростають чи падають?
- Action Plan: Що змінити в налаштуваннях?

--- ЯКЩО ІНШЕ (Uncertain) ---
🔍 Визначено: Невідомий тип (впевненість: низька)
- Опиши детально, що ти бачиш на зображенні.
- Запитай менеджера: "Це не схоже на стандартні типи аналітики. Що саме ви хочете, щоб я проаналізував у цьому файлі?"

**OUTPUT FORMAT:**
🔍 Визначено: ...
# [Назва Категорії]
## 🎯 Ключові інсайти
[пункти]
## 🛠 Рекомендації
[конкретні дії]"""


def build_system_prompt(client_id: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(client_context=get_client_context(client_id))


_DETECT_RE = re.compile(
    r"🔍\s*Визначено:\s*(.+?)\s*\(впевненість:\s*(низька|середня|висока)\)",
    re.IGNORECASE,
)


def parse_detection(text: str) -> tuple[str, str]:
    """Парсить перший рядок звіту. Повертає (kind, confidence)."""
    m = _DETECT_RE.search(text[:300])
    if m:
        return m.group(1).strip(), m.group(2).strip().lower()
    return "ІНШЕ", "низька"


_MD_B_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_H_RE = re.compile(r"^#{1,3}\s+(.+)", re.MULTILINE)
_MD_I_RE = re.compile(r"\*(.+?)\*")


def md_to_html(text: str, max_len: int = 3500) -> str:
    """Конвертує базовий Markdown у Telegram HTML. Обрізає до max_len."""
    t = text[:max_len]
    t = _MD_H_RE.sub(r"<b>\1</b>", t)
    t = _MD_B_RE.sub(r"<b>\1</b>", t)
    t = _MD_I_RE.sub(r"<i>\1</i>", t)
    # Escape залишкових < > що не є тегами
    # (мінімальний підхід — уникаємо parse error у Telegram)
    t = re.sub(r"<(?!/?(?:b|i|code|pre|a)[\s>])", "&lt;", t)
    if len(text) > max_len:
        t += "\n<i>...повний звіт у файлі вище</i>"
    return t
