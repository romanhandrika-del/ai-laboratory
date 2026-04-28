# Website Fix Agent

**agent_id:** `website-fix-v1`  
**Номер у платформі:** Agent #4

## Призначення

Генерує copy-paste пакет SEO-фіксів (P1-пріоритет) для сайту. Сумісний з GitHub PR flow (Фаза 2) та FTP-патчуванням.

## Вхід / Вихід

```python
await agent.fix(url: str) -> dict
```

```python
{
    "fix_count": int,          # кількість сгенерованих фіксів
    "summary_text": str,       # Telegram-повідомлення
    "fix_md_path": str,        # шлях до Markdown-пакету фіксів
    "fix_md": str,             # текст фіксів
    "fix_id": str,             # ID для відстеження
    # або
    "error": str
}
```

## Формат фіксів

```
File: /path/to/file.html
Selector: <title>
Search/Old: Стара назва
Replace/New: Оптимізована назва (ключове слово | бренд)
Why: Відсутнє основне ключове слово в title
```

## Пайплайн

1. `scraper.fetch_page(url)` → HTML
2. Паралельно: `seo_extractor.extract()` + `technical_checker.check()`
3. Опційно: `audit_storage.get_last_audit()` → попередній аудит як контекст
4. `fix_generator` → Claude генерує P1-фікси у структурованому форматі
5. Збереження у `data/fixes/{client_id}/`
6. `db.save_fix()` → PostgreSQL

## Деплой фіксів

- **FTP:** `ftp_patcher.py` — пряме патчування файлів на сервері
- **GitHub PR:** (Фаза 2) — автоматичний PR з фіксами

## Env vars

| Змінна | Опис |
|--------|------|
| `TELEGRAM_BOT_TOKEN` | Бот для нотифікацій |
| `MANAGER_TELEGRAM_ID` | Telegram ID менеджера |
| `FTP_HOST`, `FTP_USER`, `FTP_PASS` | FTP credentials для деплою |
