"""Добавление расходов и доходов."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..config import Config
from ..db import Database
from ..keyboards import (
    cancel_input,
    empty_categories,
    main_menu,
    pick_category,
    transaction_saved,
)
from ..ui import safe_edit
from ..utils import esc, format_date, format_money, parse_amount

router = Router(name="transactions")

KIND_TITLES = {"expense": "Расход", "income": "Доход"}
KIND_GENITIVE = {"expense": "расход", "income": "доход"}
KIND_PLURAL = {"expense": "расходов", "income": "доходов"}


class AddTransaction(StatesGroup):
    amount = State()


def _parse_id(data: str | None) -> int | None:
    if not data:
        return None
    try:
        return int(data.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


@router.callback_query(F.data.startswith("tx:new:"))
async def choose_category(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
) -> None:
    parts = (callback.data or "").split(":", 2)
    kind = parts[2] if len(parts) == 3 else ""
    if kind not in KIND_TITLES:
        await callback.answer("Кнопка устарела, откройте меню заново.", show_alert=True)
        return

    await state.clear()
    categories = await db.list_categories(callback.from_user.id, kind)
    if callback.message is None:
        await callback.answer()
        return

    if not categories:
        await callback.answer()
        await safe_edit(
            callback.message,
            f"В категориях «{KIND_PLURAL[kind]}» пока пусто.\n\n"
            "Создайте первую категорию — и сразу можно будет записывать.",
            empty_categories(kind),
        )
        return

    await callback.answer()
    await safe_edit(
        callback.message,
        f"<b>Новый {KIND_GENITIVE[kind]}</b>\n\nВыберите категорию:",
        pick_category(categories),
    )


@router.callback_query(F.data.startswith("tx:pick:"))
async def enter_amount(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
) -> None:
    category_id = _parse_id(callback.data)
    if category_id is None:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return

    category = await db.get_category(callback.from_user.id, category_id)
    if category is None:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    await state.set_state(AddTransaction.amount)
    await state.update_data(category_id=category.id, kind=category.kind)
    await callback.answer()

    if callback.message is None:
        return
    await safe_edit(
        callback.message,
        f"<b>{esc(category.title)}</b>\n\n"
        "Введите сумму — можно сразу с комментарием:\n"
        "<code>450</code> или <code>1 200,50 обед с коллегами</code>",
        cancel_input(f"tx:new:{category.kind}"),
    )


@router.message(AddTransaction.amount)
async def save_transaction(
    message: Message,
    state: FSMContext,
    db: Database,
    config: Config,
) -> None:
    data = await state.get_data()
    category_id = data.get("category_id")
    if not isinstance(category_id, int):
        await state.clear()
        await message.answer(
            "Не получилось определить категорию. Начните заново.",
            reply_markup=main_menu(),
        )
        return

    category = await db.get_category(message.from_user.id, category_id)
    if category is None:
        await state.clear()
        await message.answer(
            "Категория больше не существует. Начните заново.",
            reply_markup=main_menu(),
        )
        return

    if not message.text:
        await message.answer("Отправьте сумму текстом, например: <code>450 такси</code>")
        return

    parsed = parse_amount(message.text)
    if parsed is None:
        await message.answer(
            "Не понял сумму 🤔\n\n"
            "Напишите число: <code>450</code>, <code>1 200,50</code> "
            "или <code>450 такси</code>."
        )
        return

    today = config.today()
    transaction_id = await db.add_transaction(
        user_id=message.from_user.id,
        category_id=category.id,
        amount_minor=parsed.amount_minor,
        comment=parsed.comment or None,
        spent_on=today,
    )
    if transaction_id is None:
        await state.clear()
        await message.answer("Не удалось сохранить операцию. Попробуйте ещё раз.")
        return

    await state.clear()
    totals = await db.totals(message.from_user.id, today, today)
    currency = config.currency

    text = (
        "✅ <b>Записано</b>\n\n"
        f"{esc(category.title)} — <b>{format_money(parsed.amount_minor, currency)}</b>\n"
    )
    if parsed.comment:
        text += f"💬 {esc(parsed.comment)}\n"
    text += (
        f"📅 {format_date(today)}\n\n"
        f"Сегодня: 🔴 {format_money(totals.expense_minor, currency)} · "
        f"🟢 {format_money(totals.income_minor, currency)}"
    )

    await message.answer(
        text,
        reply_markup=transaction_saved(transaction_id, category.kind),
    )


@router.callback_query(F.data.startswith("tx:undo:"))
async def undo_transaction(
    callback: CallbackQuery,
    db: Database,
    config: Config,
) -> None:
    transaction_id = _parse_id(callback.data)
    if transaction_id is None:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return

    transaction = await db.get_transaction(callback.from_user.id, transaction_id)
    if transaction is None:
        await callback.answer("Операция уже удалена.", show_alert=True)
        return

    deleted = await db.delete_transaction(callback.from_user.id, transaction_id)
    if not deleted:
        await callback.answer("Операция уже удалена.", show_alert=True)
        return

    await callback.answer("Удалено")
    if callback.message is None:
        return
    await safe_edit(
        callback.message,
        "🗑 <b>Удалено</b>\n\n"
        f"{esc(transaction.category.title)} — "
        f"{format_money(transaction.amount_minor, config.currency)}",
        main_menu(),
    )
