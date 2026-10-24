"""Управление категориями: список, добавление, переименование, удаление."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import Database
from ..keyboards import (
    after_category,
    cancel_input,
    categories_list,
    categories_menu,
    category_actions,
)
from ..models import Category
from ..ui import safe_edit
from ..utils import esc, format_money, plural

router = Router(name="categories")

KIND_GENITIVE = {"expense": "расходов", "income": "доходов"}
KIND_NOMINATIVE = {"expense": "расходы", "income": "доходы"}
MAX_NAME_LENGTH = 32


class CategoryForm(StatesGroup):
    name = State()


def _parse_id(data: str | None) -> int | None:
    if not data:
        return None
    try:
        return int(data.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


async def _render_list(
    message: Message,
    db: Database,
    user_id: int,
    kind: str,
) -> None:
    categories = await db.list_categories(user_id, kind)
    if categories:
        total = len(categories)
        text = (
            f"🗂 <b>Категории {KIND_GENITIVE[kind]}</b>\n\n"
            f"{total} {plural(total, 'категория', 'категории', 'категорий')}. "
            "Нажмите на категорию, чтобы переименовать или удалить её."
        )
    else:
        text = (
            f"🗂 <b>Категории {KIND_GENITIVE[kind]}</b>\n\n"
            "Пока пусто. Добавьте первую — например, «Такси» или «Кофе»."
        )
    await safe_edit(message, text, categories_list(categories, kind))


@router.callback_query(F.data == "cat:menu")
async def show_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await safe_edit(
        callback.message,
        "🗂 <b>Категории</b>\n\n"
        "Категории нужны, чтобы понимать, на что уходят деньги.\n"
        "Выберите тип:",
        categories_menu(),
    )


@router.callback_query(F.data.startswith("cat:kind:"))
async def show_categories(callback: CallbackQuery, db: Database) -> None:
    parts = (callback.data or "").split(":", 2)
    kind = parts[2] if len(parts) == 3 else ""
    if kind not in KIND_GENITIVE:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return
    await _render_list(callback.message, db, callback.from_user.id, kind)


@router.callback_query(F.data.startswith("cat:open:"))
async def open_category(callback: CallbackQuery, db: Database, currency: str) -> None:
    category_id = _parse_id(callback.data)
    if category_id is None:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return

    category = await db.get_category(callback.from_user.id, category_id)
    if category is None or callback.message is None:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    total_minor, count = await db.category_stats(callback.from_user.id, category_id)
    kind_label = "расходы" if category.is_expense else "доходы"
    text = f"<b>{esc(category.title)}</b>\n\nТип: {kind_label}\n"
    if count:
        text += (
            f"Операций: {count} "
            f"{plural(count, 'операция', 'операции', 'операций')} "
            f"на {format_money(total_minor, currency)}"
        )
    else:
        text += "Пока нет операций."
    await callback.answer()
    await safe_edit(callback.message, text, category_actions(category.id, category.kind))


@router.callback_query(F.data.startswith("cat:new:"))
async def start_add(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    parts = (callback.data or "").split(":", 2)
    kind = parts[2] if len(parts) == 3 else ""
    if kind not in KIND_GENITIVE:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return

    await state.set_state(CategoryForm.name)
    await state.update_data(mode="add", kind=kind, category_id=None)
    await callback.answer()

    if callback.message is None:
        return
    await safe_edit(
        callback.message,
        f"➕ <b>Новая категория</b>\n\n"
        f"Тип: {KIND_NOMINATIVE[kind]}\n\n"
        f"Отправьте название (до {MAX_NAME_LENGTH} символов).\n"
        "Например: «Такси», «Кофе», «Подписки».",
        cancel_input(f"cat:kind:{kind}"),
    )


@router.callback_query(F.data.startswith("cat:ren:"))
async def start_rename(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
) -> None:
    category_id = _parse_id(callback.data)
    if category_id is None:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return

    category = await db.get_category(callback.from_user.id, category_id)
    if category is None or callback.message is None:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    await state.set_state(CategoryForm.name)
    await state.update_data(mode="rename", kind=category.kind, category_id=category.id)
    await callback.answer()
    await safe_edit(
        callback.message,
        f"✏️ <b>Переименование</b>\n\n"
        f"Текущее название: «{esc(category.name)}»\n\n"
        f"Отправьте новое название (до {MAX_NAME_LENGTH} символов).",
        cancel_input(f"cat:open:{category.id}"),
    )


@router.message(CategoryForm.name)
async def save_name(
    message: Message,
    state: FSMContext,
    db: Database,
) -> None:
    data = await state.get_data()
    kind = data.get("kind", "expense")
    mode = data.get("mode", "add")
    category_id = data.get("category_id")

    if not message.text:
        await message.answer("Отправьте название текстом.")
        return

    name = " ".join(message.text.split())
    if not name:
        await message.answer("Название не может быть пустым. Попробуйте ещё раз:")
        return
    if len(name) > MAX_NAME_LENGTH:
        await message.answer(
            f"Слишком длинно: максимум {MAX_NAME_LENGTH} символов. Попробуйте короче:"
        )
        return

    if mode == "rename" and isinstance(category_id, int):
        updated = await db.rename_category(message.from_user.id, category_id, name)
        if not updated:
            await message.answer(
                "Не получилось: возможно, категория с таким названием уже есть. "
                "Введите другое:"
            )
            return
        await state.clear()
        await message.answer(
            f"✅ Категория переименована в «{esc(name)}».",
            reply_markup=after_category(kind),
        )
        return

    category = await db.add_category(message.from_user.id, kind, name)
    if category is None:
        await message.answer(
            "Такая категория уже есть. Введите другое название:"
        )
        return

    await state.clear()
    await message.answer(
        f"✅ Категория «{esc(category.title)}» создана.",
        reply_markup=after_category(kind),
    )


@router.callback_query(F.data.startswith("cat:del:"))
async def delete_category(
    callback: CallbackQuery,
    db: Database,
) -> None:
    category_id = _parse_id(callback.data)
    if category_id is None:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return

    category: Category | None = await db.get_category(callback.from_user.id, category_id)
    if category is None:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    _, count = await db.category_stats(callback.from_user.id, category_id)
    if count:
        await callback.answer(
            f"Нельзя удалить: в категории {count} "
            f"{plural(count, 'операция', 'операции', 'операций')}. "
            "Сначала удалите их в истории.",
            show_alert=True,
        )
        return

    deleted = await db.delete_category(callback.from_user.id, category_id)
    if not deleted:
        await callback.answer("Не удалось удалить категорию.", show_alert=True)
        return

    await callback.answer("Категория удалена")
    if callback.message is None:
        return
    await _render_list(callback.message, db, callback.from_user.id, category.kind)
