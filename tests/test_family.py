"""Семейный доступ на уровне базы: приглашения, участники, общие итоги."""

from __future__ import annotations

import asyncio
from datetime import date

from bot.db import Database


def test_create_join_and_leave(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "bot.db")
        await db.connect()
        try:
            await db.ensure_user(1, "ivan", "Europe/Moscow", display_name="Иван")
            await db.ensure_user(2, "maria", "Europe/Moscow", display_name="Мария")

            family = await db.create_family(1, "Ивановы")
            assert family is not None
            assert family.owner_id == 1
            assert len(family.invite_code) == 8

            # Второй раз создать семью нельзя.
            assert await db.create_family(1, "Другая") is None

            # Код принимается в любом регистре.
            joined = await db.join_family(2, family.invite_code.lower())
            assert joined is not None and joined.id == family.id

            members = await db.get_family_members(family.id)
            assert [member.name for member in members] == ["Иван", "Мария"]
            assert members[0].is_owner and not members[1].is_owner

            # Чужой код не подходит.
            await db.ensure_user(3, "peter", "Europe/Moscow", display_name="Пётр")
            assert await db.join_family(3, "NOPE2345") is None

            # Второй раз в ту же семью не пускает.
            assert await db.join_family(2, family.invite_code) is None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_owner_leave_transfers_rights(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "bot.db")
        await db.connect()
        try:
            await db.ensure_user(1, None, "Europe/Moscow", display_name="Иван")
            await db.ensure_user(2, None, "Europe/Moscow", display_name="Мария")

            family = await db.create_family(1, "Ивановы")
            assert family is not None
            assert await db.join_family(2, family.invite_code) is not None

            assert await db.leave_family(1) is True
            assert await db.get_family(1) is None

            family_for_maria = await db.get_family(2)
            assert family_for_maria is not None
            assert family_for_maria.owner_id == 2

            members = await db.get_family_members(family.id)
            assert len(members) == 1
            assert members[0].user_id == 2 and members[0].is_owner

            # Последний участник закрывает семью.
            assert await db.leave_family(2) is True
            assert await db.get_family(2) is None
            assert await db.get_family_members(family.id) == []
        finally:
            await db.close()

    asyncio.run(scenario())


def test_owner_can_remove_member(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "bot.db")
        await db.connect()
        try:
            await db.ensure_user(1, None, "Europe/Moscow", display_name="Иван")
            await db.ensure_user(2, None, "Europe/Moscow", display_name="Мария")

            family = await db.create_family(1, "Ивановы")
            assert family is not None
            assert await db.join_family(2, family.invite_code) is not None

            # Участник не может исключать других и владельца.
            assert await db.remove_member(2, 1) is False
            assert await db.remove_member(1, 1) is False

            assert await db.remove_member(1, 2) is True
            assert await db.get_family(2) is None
            assert await db.remove_member(1, 2) is False
        finally:
            await db.close()

    asyncio.run(scenario())


def test_invite_code_regeneration(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "bot.db")
        await db.connect()
        try:
            await db.ensure_user(1, None, "Europe/Moscow", display_name="Иван")
            await db.ensure_user(2, None, "Europe/Moscow", display_name="Мария")
            await db.ensure_user(3, None, "Europe/Moscow", display_name="Пётр")

            family = await db.create_family(1, "Ивановы")
            assert family is not None
            assert await db.join_family(2, family.invite_code) is not None

            # Менять код может только владелец.
            assert await db.regenerate_invite_code(2) is None

            new_code = await db.regenerate_invite_code(1)
            assert new_code is not None
            assert new_code != family.invite_code

            # Старый код больше не работает, новый — работает.
            assert await db.join_family(3, family.invite_code) is None
            assert await db.join_family(3, new_code) is not None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_family_totals(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "bot.db")
        await db.connect()
        try:
            await db.ensure_user(1, None, "Europe/Moscow", display_name="Иван")
            await db.ensure_user(2, None, "Europe/Moscow", display_name="Мария")

            family = await db.create_family(1, "Ивановы")
            assert family is not None
            assert await db.join_family(2, family.invite_code) is not None

            today = date(2026, 10, 23)
            food1 = (await db.list_categories(1, "expense"))[0]
            food2 = (await db.list_categories(2, "expense"))[0]
            salary = (await db.list_categories(1, "income"))[0]

            await db.add_transaction(1, food1.id, 10000, "хлеб", today)
            await db.add_transaction(2, food2.id, 20000, "молоко", today)
            await db.add_transaction(1, salary.id, 50000, None, today)

            totals = await db.family_totals([1, 2], today, today)
            assert totals.expense_minor == 30000
            assert totals.income_minor == 50000
            assert totals.balance_minor == 20000

            # Одинаковые категории двух людей складываются в одну строку.
            by_category = await db.family_totals_by_category([1, 2], "expense", today, today)
            assert len(by_category) == 1
            assert by_category[0].category.name == "Продукты"
            assert by_category[0].total_minor == 30000

            by_member = {
                member.name: member
                for member in await db.family_totals_by_member([1, 2], today, today)
            }
            assert by_member["Иван"].expense_minor == 10000
            assert by_member["Мария"].expense_minor == 20000
            assert by_member["Иван"].income_minor == 50000

            transactions = await db.family_transactions([1, 2], limit=10, offset=0)
            assert len(transactions) == 3
            assert {item.author_name for item in transactions} == {"Иван", "Мария"}
            assert {item.comment for item in transactions} == {"хлеб", "молоко", None}

            assert await db.count_family_transactions([1, 2]) == 3
            assert await db.family_transactions([], 10, 0) == []
        finally:
            await db.close()

    asyncio.run(scenario())
