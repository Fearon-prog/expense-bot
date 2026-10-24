"""Настройки пользователя: валюта отчётов."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from ..currencies import CURRENCIES, currency_label
from ..db import Database
from ..keyboards import settings_currency
from ..ui import safe_edit

router = Router(name="settings")


def _text(currency: str) -> str:
    return (
        "⚙️ <b>Настройки</b>\n\n"
        f"💱 Валюта: <b>{currency_label(currency)}</b>\n\n"
        "В этой валюте показываются суммы в отчётах, истории и экспорте.\n"
        "Уже записанные суммы не пересчитываются — меняется только обозначение."
    )


async def _show(message: Message, currency: str) -> None:
    await safe_edit(message, _text(currency), settings_currency(currency))


@router.callback_query(F.data == "set:menu")
async def show_settings(callback: CallbackQuery, currency: str) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _show(callback.message, currency)


@router.callback_query(F.data.startswith("set:cur:"))
async def set_currency(callback: CallbackQuery, db: Database) -> None:
    try:
        index = int((callback.data or "").rsplit(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Кнопка устарела.", show_alert=True)
        return

    if not 0 <= index < len(CURRENCIES):
        await callback.answer("Неизвестная валюта.", show_alert=True)
        return

    symbol = CURRENCIES[index][0]
    await db.set_user_currency(callback.from_user.id, symbol)
    await callback.answer(f"Валюта: {symbol}")
    if callback.message is None:
        return
    await _show(callback.message, symbol)
