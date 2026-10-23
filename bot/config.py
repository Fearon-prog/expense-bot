"""Конфигурация приложения: токен, путь к базе, часовой пояс, валюта."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class ConfigError(RuntimeError):
    """Конфигурация неполная или некорректная — бот не может запуститься."""


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    db_path: Path
    default_timezone: str = "Europe/Moscow"
    currency: str = "₽"

    @classmethod
    def from_env(cls) -> "Config":
        token = (os.getenv("BOT_TOKEN") or "").strip()
        if not token:
            raise ConfigError(
                "Не найден BOT_TOKEN. Скопируйте .env.example в .env и вставьте токен, "
                "который выдал @BotFather."
            )
        if ":" not in token:
            raise ConfigError(
                "BOT_TOKEN выглядит некорректно: ожидается строка вида 123456789:AA..."
            )

        timezone_name = (os.getenv("TIMEZONE") or "Europe/Moscow").strip()
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError(f"Неизвестный часовой пояс: {timezone_name!r}") from exc

        raw_path = (os.getenv("DB_PATH") or "").strip()
        db_path = Path(raw_path).expanduser() if raw_path else BASE_DIR / "data" / "bot.db"
        if not db_path.is_absolute():
            db_path = (BASE_DIR / db_path).resolve()

        currency = (os.getenv("CURRENCY") or "₽").strip() or "₽"
        return cls(
            bot_token=token,
            db_path=db_path,
            default_timezone=timezone_name,
            currency=currency,
        )

    def today(self) -> date:
        """Сегодняшняя дата в часовом поясе бота."""
        return datetime.now(ZoneInfo(self.default_timezone)).date()
