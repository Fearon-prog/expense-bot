"""Тесты конфигурации: токен, часовой пояс, валюта, путь к базе."""

from __future__ import annotations

from datetime import date

import pytest

from bot.config import BASE_DIR, Config, ConfigError


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BOT_TOKEN", "TIMEZONE", "DB_PATH", "CURRENCY"):
        monkeypatch.delenv(name, raising=False)


def test_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    with pytest.raises(ConfigError, match="BOT_TOKEN"):
        Config.from_env()


def test_broken_token_format(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("BOT_TOKEN", "не-токен")
    with pytest.raises(ConfigError, match="BOT_TOKEN"):
        Config.from_env()


def test_unknown_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("TIMEZONE", "Mars/Phobos")
    with pytest.raises(ConfigError, match="часовой пояс"):
        Config.from_env()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("BOT_TOKEN", "42:TEST")
    config = Config.from_env()

    assert config.default_timezone == "Europe/Moscow"
    assert config.currency == "₽"
    assert config.db_path == BASE_DIR / "data" / "bot.db"
    assert isinstance(config.today(), date)


def test_relative_db_path_is_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("DB_PATH", "var/my.db")
    config = Config.from_env()
    assert config.db_path == (BASE_DIR / "var" / "my.db").resolve()


def test_currency_can_be_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("BOT_TOKEN", "42:TEST")
    monkeypatch.setenv("CURRENCY", "$")
    assert Config.from_env().currency == "$"
