"""Точка входа: собираем зависимости, роутеры и запускаем polling."""

from __future__ import annotations

import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

from .config import Config
from .db import Database
from .handlers import (
    categories,
    common,
    export,
    family,
    history,
    reports,
    settings,
    transactions,
)
from .middlewares import UserMiddleware
from .singleton import acquire_lock

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=(os.getenv("LOG_LEVEL") or "INFO").upper(),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )


async def on_error(event: ErrorEvent) -> None:
    logger.error("Ошибка при обработке апдейта", exc_info=event.exception)
    update = event.update
    try:
        if update.callback_query is not None:
            await update.callback_query.answer(
                "Что-то пошло не так 🙈 Попробуйте ещё раз.",
                show_alert=True,
            )
        elif update.message is not None:
            await update.message.answer(
                "Что-то пошло не так 🙈 Попробуйте ещё раз или отправьте /start."
            )
    except Exception:  # pragma: no cover - защита от каскадных ошибок
        logger.exception("Не удалось сообщить пользователю об ошибке")


async def main() -> None:
    configure_logging()
    config = Config.from_env()
    lock = acquire_lock()

    db: Database | None = None
    bot: Bot | None = None
    try:
        logger.info("Файл базы данных: %s", config.db_path)

        bot = Bot(
            token=config.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        db = Database(config.db_path)
        await db.connect()
        dispatcher = build_dispatcher(db, config)

        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="help", description="Как пользоваться"),
                BotCommand(command="cancel", description="Отменить ввод"),
            ]
        )

        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Бот запущен, ожидаю сообщения")
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        if db is not None:
            await db.close()
        if bot is not None:
            await bot.session.close()
        lock.close()


def build_dispatcher(db: Database, config: Config) -> Dispatcher:
    """Собирает Dispatcher со всеми роутерами — отдельно, чтобы тестировать."""
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["db"] = db
    dispatcher["config"] = config

    middleware = UserMiddleware(db, config.default_timezone, config.currency)
    dispatcher.message.outer_middleware(middleware)
    dispatcher.callback_query.outer_middleware(middleware)

    # Семейный роутер первым: он обрабатывает /start с кодом приглашения.
    dispatcher.include_router(family.router)
    dispatcher.include_router(common.router)
    dispatcher.include_router(transactions.router)
    dispatcher.include_router(history.router)
    dispatcher.include_router(categories.router)
    dispatcher.include_router(reports.router)
    dispatcher.include_router(export.router)
    dispatcher.include_router(settings.router)
    dispatcher.errors.register(on_error)
    return dispatcher
