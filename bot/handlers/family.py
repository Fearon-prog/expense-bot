"""Семья: приглашения по коду и общий отчёт участников."""

from __future__ import annotations

import math
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ..config import Config
from ..db import Database
from ..keyboards import (
    cancel_input,
    family_history as family_history_kb,
    family_home,
    family_invite,
    family_leave_confirm,
    family_members,
    family_not_joined,
    main_menu,
    periods,
)
from ..models import Family, FamilyMember
from ..ui import safe_edit
from ..utils import (
    PERIOD_LABELS,
    esc,
    format_day,
    format_money,
    format_range,
    period_bounds,
    period_title,
)
from .common import build_menu_text
from .reports import category_block

router = Router(name="family")

PAGE_SIZE = 6
MIN_NAME = 2
MAX_NAME = 40

NOT_JOINED_TEXT = (
    "👨‍👩‍👧 <b>Семья</b>\n\n"
    "Семья объединяет отчёты: вы видите, сколько тратите вы и близкий человек.\n\n"
    "• Создайте семью и отправьте приглашение.\n"
    "• Или введите код, который прислали вам.\n\n"
    "Записи и категории остаются личными — общими становятся только отчёты."
)


class FamilyForm(StatesGroup):
    name = State()
    code = State()


# ---------------------------------------------------------------- rendering


def _member_notes(member: FamilyMember, user_id: int) -> str:
    notes = []
    if member.is_owner:
        notes.append("владелец")
    if member.user_id == user_id:
        notes.append("вы")
    return f" — {', '.join(notes)}" if notes else ""


def _render_home(family: Family, members: list[FamilyMember], user_id: int) -> str:
    lines = [f"👨‍👩‍👧 <b>Семья «{esc(family.name)}»</b>", "", "Участники:"]
    for member in members:
        lines.append(f"• {esc(member.name)}{_member_notes(member, user_id)}")
    lines += [
        "",
        f"🔑 Код приглашения: <code>{family.invite_code}</code>",
        "",
        "Общий отчёт покажет, сколько потратил каждый.",
    ]
    return "\n".join(lines)


async def _show_home(message: Message, db: Database, user_id: int) -> None:
    family = await db.get_family(user_id)
    if family is None:
        await safe_edit(message, NOT_JOINED_TEXT, family_not_joined())
        return
    members = await db.get_family_members(family.id)
    await safe_edit(message, _render_home(family, members, user_id), family_home())


async def _show_members(message: Message, db: Database, user_id: int) -> None:
    family = await db.get_family(user_id)
    if family is None:
        await safe_edit(message, NOT_JOINED_TEXT, family_not_joined())
        return

    members = await db.get_family_members(family.id)
    is_owner = family.owner_id == user_id
    lines = ["👥 <b>Участники семьи</b>", ""]
    for member in members:
        lines.append(f"• {esc(member.name)}{_member_notes(member, user_id)}")
    if is_owner:
        lines += ["", "Нажмите ❌, чтобы исключить участника."]

    await safe_edit(
        message,
        "\n".join(lines),
        family_members(members, is_owner, family.owner_id),
    )


async def _invite_view(
    db: Database,
    bot: Bot,
    user_id: int,
) -> tuple[str, InlineKeyboardMarkup] | None:
    family = await db.get_family(user_id)
    if family is None:
        return None

    me = await bot.me()
    link = f"https://t.me/{me.username}?start=join_{family.invite_code}"
    share = (
        "https://t.me/share/url?url="
        + quote(link, safe="")
        + "&text="
        + quote(f"Присоединяйся к семейному бюджету «{family.name}»", safe="")
    )
    text = (
        "🔗 <b>Приглашение в семью</b>\n\n"
        f"Код: <code>{family.invite_code}</code>\n\n"
        "Отправьте близкому эту ссылку — он откроет бота и сразу присоединится:\n"
        f"{esc(link)}"
    )
    return text, family_invite(share)


# ------------------------------------------------------------------ reports


async def _build_report(
    db: Database,
    config: Config,
    family: Family,
    members: list[FamilyMember],
    period: str,
) -> str:
    user_ids = [member.user_id for member in members]
    today = config.today()
    start, end = period_bounds(period, today)
    totals = await db.family_totals(user_ids, start, end)

    lines = [f"📊 <b>Семья «{esc(family.name)}»</b> · {period_title(period, today)}"]
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
        f"🟢 Доходы: <b>{format_money(totals.income_minor, currency)}</b>",
        f"🔴 Расходы: <b>{format_money(totals.expense_minor, currency)}</b>",
        "⚖️ Баланс: "
        f"<b>{format_money(totals.balance_minor, currency, with_sign=True)}</b>",
        "",
        "<b>👥 По участникам</b>",
    ]

    member_totals = {
        item.user_id: item
        for item in await db.family_totals_by_member(user_ids, start, end)
    }
    for member in members:
        stats = member_totals.get(member.user_id)
        lines.append(
            f"{esc(member.name)} — "
            f"🔴 {format_money(stats.expense_minor if stats else 0, currency)} · "
            f"🟢 {format_money(stats.income_minor if stats else 0, currency)}"
        )

    expense_categories = await db.family_totals_by_category(user_ids, "expense", start, end)
    if expense_categories:
        lines.append("")
        lines += category_block(
            "🔴 Расходы по категориям",
            expense_categories,
            totals.expense_minor,
            currency,
        )

    income_categories = await db.family_totals_by_category(user_ids, "income", start, end)
    if income_categories:
        lines.append("")
        lines += category_block(
            "🟢 Доходы по категориям",
            income_categories,
            totals.income_minor,
            currency,
        )

    return "\n".join(lines)


async def _show_history(
    message: Message,
    db: Database,
    config: Config,
    family: Family,
    members: list[FamilyMember],
    page: int,
) -> None:
    user_ids = [member.user_id for member in members]
    total = await db.count_family_transactions(user_ids)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(page, 0), pages - 1)

    if total == 0:
        text = "📜 <b>История семьи</b>\n\nПока нет ни одной операции."
    else:
        items = await db.family_transactions(user_ids, PAGE_SIZE, page * PAGE_SIZE)
        lines = [
            "📜 <b>История семьи</b>",
            f"Страница {page + 1} из {pages} · всего {total}",
            "",
        ]
        for item in items:
            mark = "🔴" if item.is_expense else "🟢"
            author = esc(item.author_name or "Участник")
            lines.append(
                f"{author} · {mark} <b>{format_money(item.amount_minor, config.currency)}</b>"
                f" · {esc(item.category.title)} · {format_day(item.spent_on)}"
            )
            if item.comment:
                lines.append(f"     <i>{esc(item.comment)}</i>")
        text = "\n".join(lines)

    await safe_edit(message, text, family_history_kb(page, pages))


# --------------------------------------------------------------- navigation


@router.callback_query(F.data == "fam:menu")
async def show_menu(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _show_home(callback.message, db, callback.from_user.id)


@router.callback_query(F.data == "fam:create")
async def create_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if await db.get_family(callback.from_user.id) is not None:
        await callback.answer("Вы уже в семье.", show_alert=True)
        return

    await state.set_state(FamilyForm.name)
    await callback.answer()
    if callback.message is None:
        return
    await safe_edit(
        callback.message,
        "➕ <b>Новая семья</b>\n\n"
        "Отправьте название — например, «Ивановы» или «Дом».\n"
        f"Длина: от {MIN_NAME} до {MAX_NAME} символов.",
        cancel_input("fam:menu"),
    )


@router.message(FamilyForm.name)
async def create_finish(message: Message, state: FSMContext, db: Database) -> None:
    name = " ".join((message.text or "").split())
    if not (MIN_NAME <= len(name) <= MAX_NAME):
        await message.answer(f"Нужно от {MIN_NAME} до {MAX_NAME} символов. Попробуйте ещё раз:")
        return

    family = await db.create_family(message.from_user.id, name)
    await state.clear()
    if family is None:
        await message.answer(
            "Не получилось создать семью — возможно, вы уже в одной.",
            reply_markup=main_menu(),
        )
        return

    await message.answer(
        f"✅ Семья «{esc(family.name)}» создана.\n\n"
        f"Код приглашения: <code>{family.invite_code}</code>\n\n"
        "Отправьте код близкому — он введёт его в боте и присоединится.",
        reply_markup=family_home(),
    )


@router.callback_query(F.data == "fam:join")
async def join_start(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    if await db.get_family(callback.from_user.id) is not None:
        await callback.answer("Вы уже в семье. Сначала выйдите из текущей.", show_alert=True)
        return

    await state.set_state(FamilyForm.code)
    await callback.answer()
    if callback.message is None:
        return
    await safe_edit(
        callback.message,
        "🔑 <b>Вход по коду</b>\n\n"
        "Отправьте код приглашения, который прислали вам.",
        cancel_input("fam:menu"),
    )


async def _join_and_show(
    message: Message,
    db: Database,
    config: Config,
    code: str,
) -> None:
    if await db.get_family(message.from_user.id) is not None:
        await message.answer(
            "Вы уже состоите в семье. Сначала выйдите из текущей.",
            reply_markup=main_menu(),
        )
        return

    family = await db.join_family(message.from_user.id, code)
    if family is None:
        await message.answer(
            "Код не найден. Проверьте его и попробуйте ещё раз.",
            reply_markup=main_menu(),
        )
        return

    await message.answer(
        f"✅ Вы присоединились к семье «{esc(family.name)}».\n\n"
        "Теперь в разделе «Семья» доступен общий отчёт и история.",
        reply_markup=family_home(),
    )


@router.message(FamilyForm.code)
async def join_finish(
    message: Message,
    state: FSMContext,
    db: Database,
    config: Config,
) -> None:
    code = "".join((message.text or "").split()).upper()
    if not code:
        await message.answer("Отправьте код приглашения:")
        return

    await state.clear()
    await _join_and_show(message, db, config, code)


@router.message(CommandStart(deep_link=True))
async def start_with_payload(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    db: Database,
    config: Config,
) -> None:
    payload = (command.args or "").strip()
    await state.clear()

    if payload.lower().startswith("join_"):
        await _join_and_show(message, db, config, payload[5:])
        return

    await message.answer(
        await build_menu_text(db, config, message.from_user),
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "fam:invite")
async def show_invite(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    view = await _invite_view(db, bot, callback.from_user.id)
    if view is None:
        await callback.answer("Сначала создайте семью.", show_alert=True)
        return

    text, markup = view
    await callback.answer()
    if callback.message is None:
        return
    await safe_edit(callback.message, text, markup)


@router.callback_query(F.data == "fam:code")
async def new_code(callback: CallbackQuery, db: Database, bot: Bot) -> None:
    code = await db.regenerate_invite_code(callback.from_user.id)
    if code is None:
        await callback.answer("Менять код может только владелец семьи.", show_alert=True)
        return

    view = await _invite_view(db, bot, callback.from_user.id)
    await callback.answer("Код обновлён")
    if view is None or callback.message is None:
        return
    text, markup = view
    await safe_edit(callback.message, text, markup)


@router.callback_query(F.data == "fam:members")
async def members_screen(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    if callback.message is None:
        return
    await _show_members(callback.message, db, callback.from_user.id)


@router.callback_query(F.data.startswith("fam:kick:"))
async def kick_member(callback: CallbackQuery, db: Database) -> None:
    try:
        target_id = int((callback.data or "").rsplit(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Кнопка устарела.", show_alert=True)
        return

    if target_id == callback.from_user.id:
        await callback.answer("Нельзя исключить себя.", show_alert=True)
        return

    removed = await db.remove_member(callback.from_user.id, target_id)
    if not removed:
        await callback.answer(
            "Не получилось: вы не владелец или участник уже вышел.",
            show_alert=True,
        )
        return

    await callback.answer("Участник исключён")
    if callback.message is None:
        return
    await _show_members(callback.message, db, callback.from_user.id)


@router.callback_query(F.data == "fam:leave")
async def leave_screen(callback: CallbackQuery, db: Database) -> None:
    family = await db.get_family(callback.from_user.id)
    if family is None:
        await callback.answer("Вы не в семье.", show_alert=True)
        return

    members = await db.get_family_members(family.id)
    text = (
        "🚪 <b>Выйти из семьи?</b>\n\n"
        "Ваши записи останутся у вас, но пропадут из общего отчёта."
    )
    if family.owner_id == callback.from_user.id and len(members) > 1:
        text += "\n\nВы владелец — права перейдут следующему участнику."

    await callback.answer()
    if callback.message is None:
        return
    await safe_edit(callback.message, text, family_leave_confirm())


@router.callback_query(F.data == "fam:leave_yes")
async def leave_finish(callback: CallbackQuery, db: Database) -> None:
    left = await db.leave_family(callback.from_user.id)
    await callback.answer("Вы вышли из семьи" if left else "Вы не в семье")
    if callback.message is None:
        return

    prefix = "Вы вышли из семьи.\n\n" if left else ""
    await safe_edit(callback.message, prefix + NOT_JOINED_TEXT, family_not_joined())


@router.callback_query(F.data.startswith("fam:rep:"))
async def show_report(callback: CallbackQuery, db: Database, config: Config) -> None:
    period = (callback.data or "").rsplit(":", 1)[-1]
    if period not in PERIOD_LABELS:
        period = "month"

    family = await db.get_family(callback.from_user.id)
    if family is None:
        await callback.answer("Вы не в семье.", show_alert=True)
        return

    members = await db.get_family_members(family.id)
    text = await _build_report(db, config, family, members, period)
    await callback.answer()
    if callback.message is None:
        return
    await safe_edit(callback.message, text, periods(period, prefix="fam:rep"))


@router.callback_query(F.data.startswith("fam:history:"))
async def show_history(callback: CallbackQuery, db: Database, config: Config) -> None:
    try:
        page = int((callback.data or "").rsplit(":", 1)[1])
    except (IndexError, ValueError):
        page = 0

    family = await db.get_family(callback.from_user.id)
    if family is None:
        await callback.answer("Вы не в семье.", show_alert=True)
        return

    members = await db.get_family_members(family.id)
    await callback.answer()
    if callback.message is None:
        return
    await _show_history(callback.message, db, config, family, members, page)
