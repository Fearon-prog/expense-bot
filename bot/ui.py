"""Мелкие помощники для работы с интерфейсом Telegram."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)

# Последняя диаграмма пользователя по каждому отчёту: при смене периода
# старую картинку удаляем, чтобы не засорять чат.
_chart_messages: dict[tuple[int, str], int] = {}


async def safe_edit(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Редактирует сообщение, не падая на «message is not modified»."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise


async def clear_chart(bot: Bot, chat_id: int, user_id: int, key: str) -> None:
    message_id = _chart_messages.pop((user_id, key), None)
    if message_id is None:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        pass


async def send_chart(
    bot: Bot,
    chat_id: int,
    user_id: int,
    key: str,
    png: bytes,
    caption: str | None = None,
) -> None:
    """Показывает диаграмму, заменяя предыдущую картинку этого отчёта."""
    await clear_chart(bot, chat_id, user_id, key)
    try:
        message = await bot.send_photo(
            chat_id,
            BufferedInputFile(png, filename="chart.png"),
            caption=caption,
        )
    except Exception:  # noqa: BLE001 - картинка не должна ломать отчёт
        logger.exception("Не удалось отправить диаграмму")
        return
    _chart_messages[(user_id, key)] = message.message_id
