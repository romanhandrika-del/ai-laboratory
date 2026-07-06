# Sales Telegram Import

Окремий потік для живих діалогів менеджера з клієнтами в особистому Telegram.

## Потік

```
Telethon user session
    -> list_private_chats.py
    -> data/sales_telegram/whitelist.yaml
    -> collector.py
    -> formatter.py
    -> import_to_neon.py
    -> dialogs source='tg_sales_human'
```

## Правила

- Не змішувати з `source='telegram'`: це службовий Telegram-бот.
- Не змішувати з `source='instagram'`: це діалоги Instagram Sales Agent.
- Історичний імпорт для старту: до `2024-05-15` включно.
- Prompt не змінюється автоматично. Trainer створює тільки пропозиції/reviews.

## Команди

1. Отримати список приватних чатів:

```bash
python3 agents/sales_telegram/list_private_chats.py --until 2024-05-15
```

2. Заповнити `data/sales_telegram/whitelist.yaml`.

3. Тестовий прогін без запису в Neon:

```bash
python3 agents/sales_telegram/run_historical_import.py --until 2024-05-15 --dry-run
```

4. Імпорт у Neon:

```bash
python3 agents/sales_telegram/run_historical_import.py --until 2024-05-15
```

5. Аналіз живих менеджерських діалогів:

```bash
python3 agents/sales_telegram/run_human_training.py --client-id etalhome --limit 80
```
