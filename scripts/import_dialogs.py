"""
Імпорт діалогів з формату SendPulse / Instagram копіпасти в conversations.db.

Формат вхідного тексту:
  Ім'я клієнта
  Повідомлення клієнта
  Вы отправили
  Відповідь менеджера / бота

Запуск:
  python scripts/import_dialogs.py paste    — з буферу обміну (pbpaste)
  python scripts/import_dialogs.py file.txt — з файлу
  python scripts/import_dialogs.py          — інтерактивний ввід (Ctrl+D для завершення)
"""

import sys
import re
from pathlib import Path

# Додаємо корінь проекту до шляху
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.conversation_storage import init_db, save_conversation


BOT_MARKER = "Вы отправили"
CLIENT_ID = "etalhome"


def parse_dialogs(text: str) -> list[dict]:
    """Парсить текст у список пар {user, bot}."""
    lines = [l.rstrip() for l in text.splitlines()]

    # Збираємо блоки: кожен блок — або BOT або CLIENT
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Часові мітки і системні рядки — пропускаємо
        if re.match(r'^\d{1,2}:\d{2}$', line):
            i += 1
            continue
        if re.match(r'^\d{1,2} [а-яА-ЯёЁa-zA-Z]{3} \d{4}', line):
            i += 1
            continue
        if line in ("Отредактировано", "Номер телефона"):
            i += 1
            continue
        if re.match(r'^[\d\s\+\-\(\)]{7,}$', line):  # тільки номер телефону
            i += 1
            continue

        if line == BOT_MARKER:
            # Збираємо всі рядки після "Вы отправили" до наступного маркера або клієнта
            msg_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if next_line == BOT_MARKER:
                    break
                if _is_client_name(next_line, lines, i):
                    break
                if re.match(r'^\d{1,2}:\d{2}$', next_line) or re.match(r'^\d{1,2} [а-яА-ЯёЁa-zA-Z]{3} \d{4}', next_line):
                    i += 1
                    continue
                if next_line in ("Отредактировано", "Номер телефона"):
                    i += 1
                    continue
                if next_line:
                    msg_lines.append(next_line)
                i += 1
            if msg_lines:
                blocks.append({"role": "bot", "text": "\n".join(msg_lines)})
        else:
            # Перевіряємо чи це ім'я клієнта
            if _is_client_name(line, lines, i):
                i += 1
                continue
            # Повідомлення клієнта
            msg_lines = [line]
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if next_line == BOT_MARKER or _is_client_name(next_line, lines, i):
                    break
                if re.match(r'^\d{1,2}:\d{2}$', next_line) or re.match(r'^\d{1,2} [а-яА-ЯёЁa-zA-Z]{3} \d{4}', next_line):
                    i += 1
                    continue
                if next_line in ("Отредактировано", "Номер телефона"):
                    i += 1
                    continue
                if next_line:
                    msg_lines.append(next_line)
                i += 1
            if msg_lines:
                blocks.append({"role": "client", "text": "\n".join(msg_lines)})

    # Формуємо пари client → bot
    pairs = []
    i = 0
    while i < len(blocks):
        if blocks[i]["role"] == "client":
            user_msg = blocks[i]["text"]
            bot_reply = ""
            if i + 1 < len(blocks) and blocks[i + 1]["role"] == "bot":
                bot_reply = blocks[i + 1]["text"]
                i += 2
            else:
                i += 1
            if user_msg and bot_reply:
                pairs.append({"user": user_msg, "bot": bot_reply})
        else:
            i += 1

    return pairs


def _is_client_name(line: str, lines: list, idx: int) -> bool:
    """Визначає чи рядок — це ім'я клієнта (не повідомлення)."""
    if not line:
        return False
    # Ім'я: слова з великих букв, без розділових знаків типових для повідомлень
    if re.match(r'^[А-ЯІЇЄA-Z][а-яіїєa-z]+ [А-ЯІЇЄA-Z][а-яіїєa-z]+$', line):
        return True
    if re.match(r'^[А-ЯІЇЄA-Z][а-яіїєa-z]+ [А-ЯІЇЄA-Z][а-яіїєa-z]+ \[.+\]$', line):
        return True
    return False


def import_to_db(pairs: list[dict], chat_id: int = 999999) -> int:
    """Зберігає пари в conversations.db. Повертає кількість збережених."""
    init_db()
    count = 0
    for p in pairs:
        needs_human = any(kw in p["bot"].lower() for kw in ["менеджер", "зв'яжеться", "зателефонує", "notify"])
        save_conversation(
            client_id=CLIENT_ID,
            chat_id=chat_id,
            user_msg=p["user"],
            bot_reply=p["bot"],
            confidence=0.85,
            needs_human=needs_human,
            model_used="manager_human",
            cost_usd=0.0,
        )
        count += 1
    return count


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "paste":
        import subprocess
        result = subprocess.run(["pbpaste"], capture_output=True, text=True)
        text = result.stdout
    elif len(sys.argv) > 1:
        path = Path(sys.argv[1])
        text = path.read_text(encoding="utf-8")
    else:
        print("Вставте текст діалогів (Ctrl+D для завершення):")
        text = sys.stdin.read()

    pairs = parse_dialogs(text)
    print(f"Знайдено пар діалогів: {len(pairs)}")

    for i, p in enumerate(pairs[:3], 1):
        print(f"\n--- Пара {i} ---")
        print(f"Клієнт: {p['user'][:80]}")
        print(f"Бот: {p['bot'][:80]}")

    if not pairs:
        print("Не знайдено жодної пари. Перевірте формат тексту.")
        return

    ans = input(f"\nЗавантажити {len(pairs)} пар в conversations.db? (y/n): ")
    if ans.lower() == "y":
        saved = import_to_db(pairs)
        print(f"✅ Збережено: {saved} пар")
    else:
        print("Скасовано.")


if __name__ == "__main__":
    main()
