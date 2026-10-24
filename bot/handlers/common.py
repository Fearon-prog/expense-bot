"""Главное меню, /start, /help, /cancel и навигация."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import Config
from ..db import Database
from ..keyboards import main_menu
from ..ui import safe_edit
from ..utils import MONTHS_NOM, esc, format_money

router = Router(name="common")

HELP_TEXT = (
    "ℹ️ <b>Как пользоваться</b>\n\n"
    "<b>➕ Записать операцию</b>\n"
    "1. Нажмите «Расход» или «Доход».\n"
    "2. Выберите категорию.\n"
    "3. Отправьте сумму одним сообщением.\n\n"
    "Сумму можно писать как угодно:\n"
    "• <code>450</code>\n"
    "• <code>1 200,50</code>\n"
    "• <code>450 такси</code> — число станет суммой, остальное комментарием\n\n"
    "<b>📊 Отчёты</b> — суммы за день, неделю, месяц, год и всё время, "
    "разбивка по категориям и баланс.\n"
    "<b>📜 История</b> — последние операции, любую можно удалить.\n"
    "<b>🗂 Категории</b> — добавить, переименовать или удалить категорию.\n"
    "<b>📤 Экспорт</b> — CSV-файл для Excel и Google Таблиц.\n\n"
    "Команды: /start, /help, /cancel"
)


async def build_menu_text(db: Database, config: Config, user, currency: str) -> str:
    today = config.today()
    totals = await db.totals(user.id, today.replace(day=1), today)
    name = esc(user.first_name or "друг")

    lines = [
        f"👋 Привет, <b>{name}</b>!",
        "",
        "Я помогаю следить за деньгами: записываю расходы и доходы "
        "по категориям и считаю отчёты.",
        "",
    ]
    if totals.is_empty:
        lines.append("В этом месяце записей пока нет — самое время добавить первую.")
    else:
        lines += [
            f"📅 <b>{MONTHS_NOM[today.month - 1]}</b>",
            f"🔴 Расходы: <b>{format_money(totals.expense_minor, currency)}</b>",
            f"🟢 Доходы: <b>{format_money(totals.income_minor, currency)}</b>",
            "⚖️ Баланс: "
            f"<b>{format_money(totals.balance_minor, currency, with_sign=True)}</b>",
        ]
    lines += ["", "Что делаем? 👇"]
    return "\n".join(lines)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    db: Database,
    config: Config,
    currency: str,
) -> None:
    await state.clear()
    await message.answer(
        await build_menu_text(db, config, message.from_user, currency),
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    had_state = await state.get_state() is not None
    await state.clear()
    text = "Действие отменено." if had_state else "Сейчас нечего отменять."
    await message.answer(text, reply_markup=main_menu())


@router.callback_query(F.data == "nav:menu")
async def back_to_menu(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    config: Config,
    currency: str,
) -> None:
    await state.clear()
    await callback.answer()
    if callback.message is None:
        return
    await safe_edit(
        callback.message,
        await build_menu_text(db, config, callback.from_user, currency),
        main_menu(),
    )


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(F.text, StateFilter(None))
async def unknown_text(message: Message) -> None:
    await message.answer(
        "Не понял 🤔 Выберите действие в меню или отправьте /help.",
        reply_markup=main_menu(),
    )
