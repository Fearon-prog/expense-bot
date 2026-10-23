"""История операций: просмотр, подроби и удаление."""

from __future__ import annotations

import math

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from ..config import Config
from ..db import Database
from ..keyboards import history_item, history_page
from ..ui import safe_edit
from ..utils import esc, format_date, format_day, format_money, plural

router = Router(name="history")

PAGE_SIZE = 6


def _parse_page(data: str | None) -> int:
    if not data:
        return 0
    try:
        return max(0, int(data.rsplit(":", 1)[1]))
    except (IndexError, ValueError):
        return 0


def _parse_id(data: str | None) -> int | None:
    if not data:
        return None
    try:
        return int(data.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


def _render_item(transaction, currency: str) -> str:
    mark = "🔴" if transaction.is_expense else "🟢"
    line = (
        f"{mark} <b>{format_money(transaction.amount_minor, currency)}</b>"
        f" · {esc(transaction.category.title)} · {format_day(transaction.spent_on)}"
    )
    if transaction.comment:
        line += f"\n     <i>{esc(transaction.comment)}</i>"
    return line


async def render_history(
    message: Message,
    db: Database,
    config: Config,
    user_id: int,
    page: int,
) -> None:
    total = await db.count_transactions(user_id)
    if total == 0:
        await safe_edit(
            message,
            "📜 <b>История</b>\n\nПока нет ни одной операции.\n"
            "Добавьте расход или доход — и они появятся здесь.",
            history_page([], 0, 1, config.currency),
        )
        return

    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, pages - 1)
    items = await db.list_transactions(user_id, PAGE_SIZE, page * PAGE_SIZE)

    header = (
        "📜 <b>История операций</b>\n"
        f"Страница {page + 1} из {pages} · всего {total} "
        f"{plural(total, 'операция', 'операции', 'операций')}\n"
    )
    body = "\n\n".join(_render_item(item, config.currency) for item in items)

    await safe_edit(
        message,
        f"{header}\n{body}",
        history_page(items, page, pages, config.currency),
    )


@router.callback_query(F.data.startswith("hist:page:"))
async def show_page(
    callback: CallbackQuery,
    db: Database,
    config: Config,
) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await render_history(
        callback.message,
        db,
        config,
        callback.from_user.id,
        _parse_page(callback.data),
    )


@router.callback_query(F.data.startswith("hist:item:"))
async def show_item(
    callback: CallbackQuery,
    db: Database,
    config: Config,
) -> None:
    transaction_id = _parse_id(callback.data)
    if transaction_id is None:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return

    transaction = await db.get_transaction(callback.from_user.id, transaction_id)
    if transaction is None or callback.message is None:
        await callback.answer("Операция не найдена.", show_alert=True)
        return

    kind = "Расход" if transaction.is_expense else "Доход"
    text = (
        f"<b>Операция #{transaction.id}</b>\n\n"
        f"{esc(transaction.category.title)}\n"
        f"{kind}: <b>{format_money(transaction.amount_minor, config.currency)}</b>\n"
        f"📅 {format_date(transaction.spent_on)}"
    )
    if transaction.comment:
        text += f"\n💬 {esc(transaction.comment)}"

    await callback.answer()
    await safe_edit(callback.message, text, history_item(transaction.id))


@router.callback_query(F.data.startswith("hist:del:"))
async def delete_item(
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
    await callback.answer("Удалено" if deleted else "Не удалось удалить")

    if not deleted or callback.message is None:
        return

    await render_history(callback.message, db, config, callback.from_user.id, 0)
