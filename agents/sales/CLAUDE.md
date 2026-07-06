# Sales Trainer — навігаційна карта

## Потік даних

```
/train_finance або cron
        │
        ▼
trainer.py → run_training(client_id)
        │
        ├─ db.get_dialogs_review(source='instagram')   ← тільки instagram!
        ├─ _pick_worst(rows, n=10)                      ← топ-10 за score
        ├─ db.get_agent_prompt / prompt_template.md    ← поточний промпт
        │
        ▼
Claude Sonnet — аналіз діалогів
        │
        ├─ type="Prompt"  → db.save_trainer_review()   → pending_reviews
        └─ type=інший     → db.save_trainer_suggestion() → trainer_suggestions
                                    │
                          /review approve <id>
                                    │
                                    ▼
                          patcher.py → apply_patch(review_id)
                                    │
                          guards: readonly / stale / old_text / shrink / XML
                                    │
                          db.apply_prompt_patch_multi([IG, TG?])
```

```
Особистий Telegram менеджера
        │
        ▼
agents/sales_telegram/list_private_chats.py
        │
        ├─ whitelist: config/sales_telegram_whitelist.yaml
        ▼
collector.py → formatter.py → import_to_neon.py
        │
        └─ dialogs source='tg_sales_human'
        ▼
human_trainer.py → run_human_training(client_id)
        │
        ├─ аналізує еталонні відповіді менеджера
        └─ створює trainer_suggestions / pending_reviews без auto-apply
```

---

## Файли

| Файл | Відповідальність | Ключові функції |
|---|---|---|
| `trainer.py` | Аналіз діалогів, генерація пропозицій | `run_training()`, `_pick_worst()`, `_format_dialogs()` |
| `human_trainer.py` | Аналіз живих менеджерських Telegram-діалогів | `run_human_training()` |
| `patcher.py` | Застосування патчів до промптів | `apply_patch()`, `reject_patch()`, `rollback_to_version()` |
| `sales_agent.py` | Основний агент продажів | `handle_message()`, `_call_api()` |
| `memory.py` | Haiku-компресія діалогу кожні 5 повідомлень | `maybe_compress()` |
| `knowledge_base.py` | Завантаження KB з Google Sheets при старті | `load_kb()` |
| `prompt_template.md` | Файловий промпт (fallback якщо DB порожня) | — |

---

## Типові баги

### БАГ 1 — Trainer аналізував чужі агенти
**Симптом:** Тренер пропонував правки про деплой/DNS/SEO замість sales помилок.
**Причина:** `get_dialogs_review` не фільтрував по `source`.
**Фікс:** `db.get_dialogs_review(client_id, source='instagram')` — `trainer.py:110`.

### БАГ 2 — Тренер галюцинує бізнес-параметри
**Симптом:** Пропонував "терміни: 7-14 днів" (реально 8-10 тижнів).
**Причина:** `_ANALYSIS_PROMPT_BASE` не містив поточного промпту → LLM вигадував "розумний" дефолт.
**Фікс:** `run_training` завантажує промпт і передає перші 6000 символів — `trainer.py:118-123`.

### БАГ 3 — Тренер дублює правила що вже є в промпті
**Симптом:** FAQ "Типи скла" хоча це вже є в промпті.
**Причина:** Той самий — LLM не бачив поточний промпт.
**Фікс:** Той самий + перевірка в `_ANALYSIS_PROMPT_BASE` п.1-4.

### БАГ 4 — Patch відхилено через stale
**Симптом:** `apply_patch` повертає `status: stale`.
**Причина:** Промпт змінився між моментом тренування і approval.
**Фікс:** Запустити `/train` заново, стара пропозиція застаріла.

---

## Де що міняти

| Задача | Файл | Місце |
|---|---|---|
| Змінити кількість аналізованих діалогів | `trainer.py` | `_pick_worst(rows, n=10)` |
| Додати нову секцію промпту в SECTION_SCOPE | `patcher.py` | `SECTION_SCOPE` dict |
| Змінити ліміт скорочення секції | `patcher.py` | `SECTION_DELETE_LIMITS` |
| Додати read-only секцію | `patcher.py` | `_READONLY_SECTIONS` |
| Змінити логіку скорингу діалогів | `trainer.py` | `_score_dialog()` |
| Змінити системний промпт тренера | `trainer.py` | `_ANALYSIS_PROMPT_BASE` |
| Імпорт живих Telegram-діалогів менеджера | `agents/sales_telegram/` | `list_private_chats.py`, `collector.py`, `formatter.py`, `import_to_neon.py` |
| Змінити аналіз еталонних людських діалогів | `human_trainer.py` | `_HUMAN_ANALYSIS_PROMPT` |

---

## Критичні правила

- `get_dialogs_review` — завжди `source='instagram'` для sales trainer.
- `source='tg_sales_human'` — тільки живі приватні Telegram-діалоги менеджера з клієнтами. Не змішувати з `source='telegram'`.
- Для `tg_sales_human` використовувати `human_trainer.py`, не основний `trainer.py`, бо це еталонні відповіді менеджера, а не помилки бота.
- Промпт живе в **двох місцях**: `db` (Instagram читає) + `prompt_template.md` (Telegram fallback). Зміна поведінки → обидва одночасно + `db.save_agent_prompt`.
- `apply_patch` патчить `sales_instagram` завжди, `sales_telegram` — тільки якщо `SECTION_SCOPE == "SHARED"`.
- `rollback_to_version` — створює НОВУ версію з вмістом старої, не переключає вказівник.
