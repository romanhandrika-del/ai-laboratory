import asyncio
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.telegram_webhook_security import (
    TELEGRAM_WEBHOOK_SECRET_HEADER,
    is_telegram_webhook_authorized,
    load_telegram_webhook_secret,
)


VALID_SECRET = "telegram_webhook_secret_32_chars_min"


def _import_bot_without_project_secrets(monkeypatch):
    monkeypatch.setenv("DEFAULT_CLIENT_ID", "test")
    monkeypatch.setenv("CLIENT_NAME_TEST", "Test")
    monkeypatch.setenv("KB_SHEET_ID_TEST", "offline-test-sheet")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-test-key")
    sys.modules.pop("bot", None)
    return importlib.import_module("bot")


def test_load_secret_rejects_missing_or_weak_values():
    for value in ("", "short", "contains spaces but is long enough"):
        with pytest.raises(RuntimeError):
            load_telegram_webhook_secret({"TELEGRAM_WEBHOOK_SECRET": value})


def test_authorization_requires_exact_secret():
    assert not is_telegram_webhook_authorized({}, VALID_SECRET)
    assert not is_telegram_webhook_authorized(
        {TELEGRAM_WEBHOOK_SECRET_HEADER: "wrong_secret_value_that_is_long_enough"},
        VALID_SECRET,
    )
    assert is_telegram_webhook_authorized(
        {TELEGRAM_WEBHOOK_SECRET_HEADER: VALID_SECRET},
        VALID_SECRET,
    )


def test_webhook_rejects_request_before_parsing(monkeypatch):
    bot = _import_bot_without_project_secrets(monkeypatch)

    request = SimpleNamespace(
        headers={},
        json=AsyncMock(side_effect=AssertionError("request body must not be parsed")),
    )
    tg_app = SimpleNamespace(bot=object(), process_update=AsyncMock())

    response = asyncio.run(bot._tg_webhook_receive(request, tg_app, VALID_SECRET))

    assert response.status == 403
    request.json.assert_not_awaited()
    tg_app.process_update.assert_not_awaited()


def test_webhook_dispatches_request_with_correct_secret(monkeypatch):
    bot = _import_bot_without_project_secrets(monkeypatch)

    request = SimpleNamespace(
        headers={TELEGRAM_WEBHOOK_SECRET_HEADER: VALID_SECRET},
        json=AsyncMock(return_value={"update_id": 1}),
    )
    tg_app = SimpleNamespace(bot=object(), process_update=AsyncMock())
    update = object()
    monkeypatch.setattr(bot.Update, "de_json", lambda data, telegram_bot: update)

    response = asyncio.run(bot._tg_webhook_receive(request, tg_app, VALID_SECRET))

    assert response.status == 200
    tg_app.process_update.assert_awaited_once_with(update)
