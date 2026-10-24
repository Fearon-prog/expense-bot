"""Инлайн-клавиатуры бота.

Раскладка задаётся явными строками через ``builder.row(...)`` — так кнопки
навигации не «прилипают» к сетке категорий.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .currencies import CURRENCIES
from .models import Category, FamilyMember, Transaction
from .utils import PERIODS, PERIOD_LABELS, format_money

BUTTON_TEXT_LIMIT = 34


def _short(text: str, limit: int = BUTTON_TEXT_LIMIT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _button(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("➕ Расход", "tx:new:expense"),
        _button("💰 Доход", "tx:new:income"),
    )
    builder.row(
        _button("📊 Отчёты", "rep:month"),
        _button("📜 История", "hist:page:0"),
    )
    builder.row(
        _button("🗂 Категории", "cat:menu"),
        _button("👨‍👩‍👧 Семья", "fam:menu"),
    )
    builder.row(
        _button("📤 Экспорт", "exp:csv"),
        _button("⚙️ Настройки", "set:menu"),
    )
    return builder.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("🏠 В меню", "nav:menu"))
    return builder.as_markup()


def pick_category(categories: list[Category]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index in range(0, len(categories), 2):
        builder.row(
            *[
                _button(_short(category.title), f"tx:pick:{category.id}")
                for category in categories[index : index + 2]
            ]
        )
    builder.row(_button("🏠 Меню", "nav:menu"))
    return builder.as_markup()


def empty_categories(kind: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("➕ Создать категорию", f"cat:new:{kind}"))
    builder.row(_button("🏠 Меню", "nav:menu"))
    return builder.as_markup()


def cancel_input(back_data: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("⬅️ Назад", back_data),
        _button("🏠 Меню", "nav:menu"),
    )
    return builder.as_markup()


def transaction_saved(transaction_id: int, kind: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("↩️ Отменить", f"tx:undo:{transaction_id}"),
        _button("➕ Ещё", f"tx:new:{kind}"),
    )
    builder.row(_button("🏠 Меню", "nav:menu"))
    return builder.as_markup()


def history_page(
    items: list[Transaction],
    page: int,
    pages: int,
    currency: str,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    item_buttons = []
    for transaction in items:
        mark = "🔴" if transaction.is_expense else "🟢"
        label = (
            f"{mark} {format_money(transaction.amount_minor, currency)}"
            f" · {_short(transaction.category.name, 16)}"
        )
        item_buttons.append(_button(label, f"hist:item:{transaction.id}"))

    for index in range(0, len(item_buttons), 2):
        builder.row(*item_buttons[index : index + 2])

    pagination = []
    if page > 0:
        pagination.append(_button("◀️", f"hist:page:{page - 1}"))
    pagination.append(_button(f"{page + 1}/{pages}", "noop"))
    if page + 1 < pages:
        pagination.append(_button("▶️", f"hist:page:{page + 1}"))
    builder.row(*pagination)
    builder.row(_button("🏠 Меню", "nav:menu"))
    return builder.as_markup()


def history_item(transaction_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("🗑 Удалить", f"hist:del:{transaction_id}"),
        _button("⬅️ К истории", "hist:page:0"),
    )
    return builder.as_markup()


def categories_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("🔴 Расходы", "cat:kind:expense"),
        _button("🟢 Доходы", "cat:kind:income"),
    )
    builder.row(_button("🏠 Меню", "nav:menu"))
    return builder.as_markup()


def categories_list(categories: list[Category], kind: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index in range(0, len(categories), 2):
        builder.row(
            *[
                _button(_short(category.title), f"cat:open:{category.id}")
                for category in categories[index : index + 2]
            ]
        )
    builder.row(_button("➕ Добавить категорию", f"cat:new:{kind}"))
    builder.row(
        _button("⬅️ Назад", "cat:menu"),
        _button("🏠 Меню", "nav:menu"),
    )
    return builder.as_markup()


def category_actions(category_id: int, kind: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("✏️ Переименовать", f"cat:ren:{category_id}"),
        _button("🗑 Удалить", f"cat:del:{category_id}"),
    )
    builder.row(
        _button("⬅️ К категориям", f"cat:kind:{kind}"),
        _button("🏠 Меню", "nav:menu"),
    )
    return builder.as_markup()


def after_category(kind: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("⬅️ К категориям", f"cat:kind:{kind}"),
        _button("🏠 Меню", "nav:menu"),
    )
    return builder.as_markup()


def periods(active: str, prefix: str = "rep") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    buttons = [
        _button(
            ("✅ " if period == active else "") + PERIOD_LABELS[period],
            f"{prefix}:{period}",
        )
        for period in PERIODS
    ]
    builder.row(*buttons[:3])
    builder.row(*buttons[3:])
    builder.row(_button("🏠 Меню", "nav:menu"))
    return builder.as_markup()


def family_not_joined() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("➕ Создать семью", "fam:create"),
        _button("🔑 Войти по коду", "fam:join"),
    )
    builder.row(_button("🏠 Меню", "nav:menu"))
    return builder.as_markup()


def family_home() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("📊 Отчёт семьи", "fam:rep:month"),
        _button("📜 История семьи", "fam:history:0"),
    )
    builder.row(
        _button("🔗 Пригласить", "fam:invite"),
        _button("👥 Участники", "fam:members"),
    )
    builder.row(
        _button("🚪 Выйти", "fam:leave"),
        _button("🏠 Меню", "nav:menu"),
    )
    return builder.as_markup()


def family_invite(share_url: str | None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if share_url:
        builder.row(InlineKeyboardButton(text="🔗 Поделиться", url=share_url))
    builder.row(_button("🔄 Новый код", "fam:code"))
    builder.row(
        _button("⬅️ Назад", "fam:menu"),
        _button("🏠 Меню", "nav:menu"),
    )
    return builder.as_markup()


def family_members(
    members: list[FamilyMember],
    can_remove: bool,
    owner_id: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_remove:
        for member in members:
            if member.user_id == owner_id:
                continue
            builder.row(
                _button(f"❌ {_short(member.name, 24)}", f"fam:kick:{member.user_id}")
            )
    builder.row(
        _button("⬅️ Назад", "fam:menu"),
        _button("🏠 Меню", "nav:menu"),
    )
    return builder.as_markup()


def family_leave_confirm() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("🚪 Да, выйти", "fam:leave_yes"),
        _button("⬅️ Остаться", "fam:menu"),
    )
    return builder.as_markup()


def family_history(page: int, pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="◀️", callback_data=f"fam:history:{page - 1}")
    builder.button(text=f"{page + 1}/{pages}", callback_data="noop")
    if page + 1 < pages:
        builder.button(text="▶️", callback_data=f"fam:history:{page + 1}")
    builder.row(
        _button("⬅️ Назад", "fam:menu"),
        _button("🏠 Меню", "nav:menu"),
    )
    return builder.as_markup()


def settings_currency(current: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, (symbol, name) in enumerate(CURRENCIES):
        prefix = "✅ " if symbol == current else ""
        builder.button(
            text=f"{prefix}{symbol} {name}",
            callback_data=f"set:cur:{index}",
        )
    builder.adjust(2)
    builder.row(_button("🏠 Меню", "nav:menu"))
    return builder.as_markup()
