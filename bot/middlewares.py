"""Создание пользователя и его категорий до вызова обработчиков."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from .db import Database

logger = logging.getLogger(__name__)


class UserMiddleware(BaseMiddleware):
    """Гарантирует, что к моменту работы обработчика пользователь уже в базе."""

    def __init__(self, db: Database, timezone_name: str) -> None:
        self.db = db
        self.timezone_name = timezone_name

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]):
        user = getattr(event, "from_user", None) or data.get("event_from_user")
        if user is not None:
            await self.db.ensure_user(
                user.id,
                user.username,
                self.timezone_name,
                display_name=user.full_name,
            )
        return await handler(event, data)
