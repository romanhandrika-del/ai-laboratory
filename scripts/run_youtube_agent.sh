#!/bin/bash
# Локальний запуск YouTube Agent — Mac cron job
# Запускається щодня о 09:00

PROJECT="/Users/romanhandrika/Documents/Платформа агентів/ai-laboratory"
PYTHON="/Users/romanhandrika/Documents/Платформа агентів/Automatic data/.venv/bin/python3"
LOG="$PROJECT/logs/youtube_agent.log"

mkdir -p "$PROJECT/logs"

echo "$(date '+%Y-%m-%d %H:%M:%S') — YouTube Agent старт" >> "$LOG"

cd "$PROJECT" && "$PYTHON" agents/youtube_agent/run.py >> "$LOG" 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') — YouTube Agent завершено" >> "$LOG"
