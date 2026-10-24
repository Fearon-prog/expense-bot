"""Отчёты за период с разбивкой по категориям."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from ..config import Config
from ..db import Database
from ..keyboards import periods
from ..models import CategoryTotal
from ..ui import safe_edit
from ..utils import (
    PERIOD_LABELS,
    esc,
    format_money,
    format_range,
    percent,
    period_bounds,
    period_title,
    plural,
    progress_bar,
)

router = Router(name="reports")

MAX_CATEGORIES_IN_REPORT = 8


def category_block(
    title: str,
    items: list[CategoryTotal],
    total_minor: int,
    currency: str,
) -> list[str]:
    lines = [f"<b>{title}</b>"]
    maximum = items[0].total_minor if items else 0

    for item in items[:MAX_CATEGORIES_IN_REPORT]:
        share = percent(item.total_minor, total_minor)
        share_label = f"{share}%" if share else "<1%"
        lines.append(
            f"{esc(item.category.title)} — "
            f"<b>{format_money(item.total_minor, currency)}</b> · {share_label}"
        )
        lines.append(f"<code>{progress_bar(item.total_minor, maximum)}</code>")

    rest = items[MAX_CATEGORIES_IN_REPORT:]
    if rest:
        rest_total = sum(item.total_minor for item in rest)
        lines.append(
            f"…и ещё {len(rest)} "
            f"{plural(len(rest), 'категория', 'категории', 'категорий')} "
            f"на {format_money(rest_total, currency)}"
        )
    return lines


async def build_report(
    db: Database,
    config: Config,
    user_id: int,
    period: str,
) -> str:
    today = config.today()
    start, end = period_bounds(period, today)
    totals = await db.totals(user_id, start, end)

    lines = [f"📊 <b>Отчёт</b> · {period_title(period, today)}"]
    if period == "all":
        lines.append("<i>за всё время</i>")
    elif period != "today":
        lines.append(f"<i>{format_range(start, end)}</i>")
    lines.append("")

    if totals.is_empty:
        lines.append("За этот период операций нет.")
        return "\n".join(lines)

    currency = config.currency
    lines += [
        f"🟢 Доходы: <b>{format_money(totals.income_minor, currency)}</b> · "
        f"{totals.income_count} {plural(totals.income_count, 'операция', 'операции', 'операций')}",
        f"🔴 Расходы: <b>{format_money(totals.expense_minor, currency)}</b> · "
        f"{totals.expense_count} {plural(totals.expense_count, 'операция', 'операции', 'операций')}",
        "⚖️ Баланс: "
        f"<b>{format_money(totals.balance_minor, currency, with_sign=True)}</b>",
    ]

    if period in {"week", "month", "year"} and totals.expense_count:
        days = (end - start).days + 1
        lines.append(
            f"📈 В среднем в день: {format_money(totals.expense_minor // days, currency)}"
        )

    expense_categories = await db.totals_by_category(user_id, "expense", start, end)
    if expense_categories:
        lines.append("")
        lines += category_block(
            "🔴 Расходы по категориям",
            expense_categories,
            totals.expense_minor,
            currency,
        )

    income_categories = await db.totals_by_category(user_id, "income", start, end)
    if income_categories:
        lines.append("")
        lines += category_block(
            "🟢 Доходы по категориям",
            income_categories,
            totals.income_minor,
            currency,
        )

    return "\n".join(lines)


@router.callback_query(F.data.startswith("rep:"))
async def show_report(
    callback: CallbackQuery,
    db: Database,
    config: Config,
) -> None:
    parts = (callback.data or "").split(":", 1)
    period = parts[1] if len(parts) == 2 else "month"
    if period not in PERIOD_LABELS:
        period = "month"

    text = await build_report(db, config, callback.from_user.id, period)
    await callback.answer()
    if callback.message is None:
        return
    await safe_edit(callback.message, text, periods(period))
