"""Экспорт всех операций в CSV."""

from __future__ import annotations

import csv
import io

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery

from ..config import Config
from ..db import Database
from ..utils import plural

router = Router(name="export")


@router.callback_query(F.data == "exp:csv")
async def export_csv(
    callback: CallbackQuery,
    db: Database,
    config: Config,
) -> None:
    transactions = await db.all_transactions(callback.from_user.id)
    if not transactions:
        await callback.answer("Пока нечего экспортировать.", show_alert=True)
        return

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(["ID", "Дата", "Тип", "Категория", "Сумма", "Валюта", "Комментарий"])
    for transaction in transactions:
        writer.writerow(
            [
                transaction.id,
                transaction.spent_on.strftime("%d.%m.%Y"),
                "Доход" if not transaction.is_expense else "Расход",
                transaction.category.name,
                f"{transaction.amount_minor / 100:.2f}".replace(".", ","),
                config.currency,
                transaction.comment or "",
            ]
        )

    payload = buffer.getvalue().encode("utf-8-sig")
    today = config.today()
    document = BufferedInputFile(
        payload,
        filename=f"operations_{today:%Y-%m-%d}.csv",
    )

    await callback.answer()
    if callback.message is None:
        return

    count = len(transactions)
    await callback.message.answer_document(
        document,
        caption=(
            f"📤 Экспорт: {count} "
            f"{plural(count, 'операция', 'операции', 'операций')}.\n"
            "Файл открывается в Excel и Google Таблицах."
        ),
    )
