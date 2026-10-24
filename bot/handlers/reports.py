"""Отчёты за период с разбивкой по категориям и диаграммой."""

from __future__ import annotations

from dataclasses import dataclass, field

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from ..charts import expenses_income_chart
from ..config import Config
from ..db import Database
from ..keyboards import periods
from ..models import CategoryTotal
from ..ui import clear_chart, safe_edit, send_chart
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
CHART_KEY = "personal"


@dataclass(frozen=True)
class ReportView:
    text: str
    expense: list[CategoryTotal] = field(default_factory=list)
    income: list[CategoryTotal] = field(default_factory=list)


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
    currency: str,
) -> ReportView:
    today = config.today()
    start, end = period_bounds(period, today)
    totals = await db.totals(user_id, start, end)

    lines = [f"📊 <b>Отчёт</b> · {period_title(period, today)}"]
    if period == "all":
        lines.append("<i>за всё время</i>")
    elif period != "today":
        lines.append(f"<i>{format_range(start, end)}</i>")
    lines.append("")

    expense_categories = await db.totals_by_category(user_id, "expense", start, end)
    income_categories = await db.totals_by_category(user_id, "income", start, end)

    if totals.is_empty:
        lines.append("За этот период операций нет.")
        return ReportView(text="\n".join(lines))

    lines += [
        f"🟢 Доходы: <b>{format_money(totals.income_minor, currency)}</b> · "
        f"{totals.income_count} "
        f"{plural(totals.income_count, 'операция', 'операции', 'операций')}",
        f"🔴 Расходы: <b>{format_money(totals.expense_minor, currency)}</b> · "
        f"{totals.expense_count} "
        f"{plural(totals.expense_count, 'операция', 'операции', 'операций')}",
        "⚖️ Баланс: "
        f"<b>{format_money(totals.balance_minor, currency, with_sign=True)}</b>",
    ]

    if period in {"week", "month", "year"} and totals.expense_count:
        days = (end - start).days + 1
        lines.append(
            f"📈 В среднем в день: {format_money(totals.expense_minor // days, currency)}"
        )

    if expense_categories:
        lines.append("")
        lines += category_block(
            "🔴 Расходы по категориям",
            expense_categories,
            totals.expense_minor,
            currency,
        )

    if income_categories:
        lines.append("")
        lines += category_block(
            "🟢 Доходы по категориям",
            income_categories,
            totals.income_minor,
            currency,
        )

    return ReportView(
        text="\n".join(lines),
        expense=expense_categories,
        income=income_categories,
    )


def _chart_slices(items: list[CategoryTotal]) -> list[tuple[str, int]]:
    # Без emoji: в шрифте диаграмм нет их глифов, а цвет и так различает сектора.
    return [(item.category.name, item.total_minor) for item in items]


@router.callback_query(F.data.startswith("rep:"))
async def show_report(
    callback: CallbackQuery,
    db: Database,
    config: Config,
    bot: Bot,
    currency: str,
) -> None:
    parts = (callback.data or "").split(":", 1)
    period = parts[1] if len(parts) == 2 else "month"
    if period not in PERIOD_LABELS:
        period = "month"

    view = await build_report(db, config, callback.from_user.id, period, currency)
    await callback.answer()
    if callback.message is None:
        return

    await safe_edit(callback.message, view.text, periods(period))

    png = expenses_income_chart(
        _chart_slices(view.expense),
        _chart_slices(view.income),
        currency,
    )
    chat_id = callback.message.chat.id
    if png is None:
        await clear_chart(bot, chat_id, callback.from_user.id, CHART_KEY)
        return

    await send_chart(
        bot,
        chat_id,
        callback.from_user.id,
        CHART_KEY,
        png,
        caption=f"📊 Расходы и доходы · {period_title(period, config.today())}",
    )
