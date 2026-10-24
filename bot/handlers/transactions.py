"""Добавление расходов и доходов."""

from __future__ import annotations

import uuid

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
from ..utils import esc, format_date, format_money, parse_amounts, plural

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
    currency: str,
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

    items = parse_amounts(message.text)
    if items is None:
        await message.answer(
            "Не понял сумму 🤔\n\n"
            "Можно одну трату: <code>450</code>, <code>1 200,50</code>, "
            "<code>450 такси</code>.\n"
            "Или списком: <code>обед 300 и ужин 300</code> — запишу двумя "
            "операциями на 600."
        )
        return

    today = config.today()
    batch_id = uuid.uuid4().hex if len(items) > 1 else None
    transaction_ids: list[int] = []
    for item in items:
        transaction_id = await db.add_transaction(
            user_id=message.from_user.id,
            category_id=category.id,
            amount_minor=item.amount_minor,
            comment=item.comment or None,
            spent_on=today,
            batch_id=batch_id,
        )
        if transaction_id is None:
            break
        transaction_ids.append(transaction_id)

    if len(transaction_ids) != len(items):
        if batch_id is not None:
            await db.delete_transaction_batch(message.from_user.id, batch_id)
        await state.clear()
        await message.answer("Не удалось сохранить операции. Попробуйте ещё раз.")
        return

    await state.clear()
    totals = await db.totals(message.from_user.id, today, today)
    total_minor = sum(item.amount_minor for item in items)

    if len(items) == 1:
        parsed = items[0]
        text = (
            "✅ <b>Записано</b>\n\n"
            f"{esc(category.title)} — <b>{format_money(parsed.amount_minor, currency)}</b>\n"
        )
        if parsed.comment:
            text += f"💬 {esc(parsed.comment)}\n"
    else:
        text = (
            f"✅ <b>Записано: {len(items)} "
            f"{plural(len(items), 'операция', 'операции', 'операций')}</b>\n\n"
            f"{esc(category.title)} — <b>{format_money(total_minor, currency)}</b>\n"
        )
        for item in items[:10]:
            label = esc(item.comment) if item.comment else "без комментария"
            text += f"• {label} — {format_money(item.amount_minor, currency)}\n"
        if len(items) > 10:
            text += f"…и ещё {len(items) - 10}\n"

    text += (
        f"\n📅 {format_date(today)}\n\n"
        f"Сегодня: 🔴 {format_money(totals.expense_minor, currency)} · "
        f"🟢 {format_money(totals.income_minor, currency)}"
    )

    await message.answer(
        text,
        reply_markup=transaction_saved(transaction_ids[0], category.kind),
    )


@router.callback_query(F.data.startswith("tx:undo:"))
async def undo_transaction(
    callback: CallbackQuery,
    db: Database,
    currency: str,
) -> None:
    transaction_id = _parse_id(callback.data)
    if transaction_id is None:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return

    transaction = await db.get_transaction(callback.from_user.id, transaction_id)
    if transaction is None:
        await callback.answer("Операция уже удалена.", show_alert=True)
        return

    if transaction.batch_id:
        batch = await db.batch_transactions(callback.from_user.id, transaction.batch_id)
        total_minor = sum(item.amount_minor for item in batch)
        deleted = await db.delete_transaction_batch(
            callback.from_user.id, transaction.batch_id
        )
        if not deleted:
            await callback.answer("Операции уже удалены.", show_alert=True)
            return

        await callback.answer("Удалено")
        if callback.message is None:
            return
        await safe_edit(
            callback.message,
            "🗑 <b>Удалено</b>\n\n"
            f"{deleted} {plural(deleted, 'операция', 'операции', 'операций')} "
            f"на {format_money(total_minor, currency)}",
            main_menu(),
        )
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
        f"{format_money(transaction.amount_minor, currency)}",
        main_menu(),
    )
