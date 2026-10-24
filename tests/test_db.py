"""Интеграционные тесты базы данных (SQLite + aiosqlite)."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import date

from bot.db import Database

OLD_SCHEMA = """
CREATE TABLE users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    timezone   TEXT NOT NULL DEFAULT 'Europe/Moscow',
    created_at TEXT NOT NULL,
    seeded     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    name       TEXT NOT NULL,
    name_key   TEXT NOT NULL,
    emoji      TEXT NOT NULL DEFAULT '',
    position   INTEGER NOT NULL DEFAULT 1000,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ux_categories_name ON categories(user_id, kind, name_key);

CREATE TABLE transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    category_id  INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    kind         TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    comment      TEXT,
    spent_on     TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
"""


def test_migration_from_old_schema(tmp_path) -> None:
    """База прошлой версии получает display_name и таблицы семьи."""

    async def scenario() -> None:
        path = tmp_path / "old.db"
        connection = sqlite3.connect(path)
        connection.executescript(OLD_SCHEMA)
        connection.commit()
        connection.close()

        db = Database(path)
        await db.connect()
        try:
            async with db.conn.execute("PRAGMA table_info(users)") as cursor:
                columns = {row["name"] for row in await cursor.fetchall()}
            assert "display_name" in columns
            assert "currency" in columns

            await db.ensure_user(1, "ivan", "Europe/Moscow", display_name="Иван")
            family = await db.create_family(1, "Семья")
            assert family is not None
            members = await db.get_family_members(family.id)
            assert members[0].name == "Иван"
        finally:
            await db.close()

    asyncio.run(scenario())


def test_user_currency(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "bot.db")
        await db.connect()
        try:
            # По умолчанию валюта не выбрана — используется значение из .env.
            assert await db.ensure_user(1, "ivan", "Europe/Moscow") is None

            await db.set_user_currency(1, "€")
            currency = await db.ensure_user(1, "ivan", "Europe/Moscow")
            assert currency == "€"

            # У второго пользователя всё ещё валюта по умолчанию.
            assert await db.ensure_user(2, "maria", "Europe/Moscow") is None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_seed_categories_once(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "bot.db")
        await db.connect()
        try:
            await db.ensure_user(1, "tester", "Europe/Moscow")
            expenses = await db.list_categories(1, "expense")
            incomes = await db.list_categories(1, "income")
            assert len(expenses) == 12
            assert len(incomes) == 5
            assert expenses[0].name == "Продукты"

            # Повторный вызов не дублирует категории.
            await db.ensure_user(1, "tester", "Europe/Moscow")
            assert len(await db.list_categories(1, "expense")) == 12

            # Удалённую категорию повторная инициализация не возвращает.
            assert await db.delete_category(1, expenses[-1].id) is True
            await db.ensure_user(1, "tester", "Europe/Moscow")
            assert len(await db.list_categories(1, "expense")) == 11
        finally:
            await db.close()

    asyncio.run(scenario())


def test_add_and_delete_categories(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "bot.db")
        await db.connect()
        try:
            await db.ensure_user(2, None, "Europe/Moscow")

            added = await db.add_category(2, "expense", "Такси")
            assert added is not None
            assert added.title == "🏷 Такси"

            # Дубликат в другом регистре не создаётся.
            assert await db.add_category(2, "expense", "такси") is None

            assert await db.rename_category(2, added.id, "Такси и каршеринг") is True
            renamed = await db.get_category(2, added.id)
            assert renamed is not None and renamed.name == "Такси и каршеринг"

            # Чужой пользователь не видит и не меняет категорию.
            await db.ensure_user(3, None, "Europe/Moscow")
            assert await db.get_category(3, added.id) is None
            assert await db.rename_category(3, added.id, "Взлом") is False

            assert await db.delete_category(2, added.id) is True
            assert await db.get_category(2, added.id) is None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_transactions_totals_and_reports(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "bot.db")
        await db.connect()
        try:
            await db.ensure_user(7, "user", "Europe/Moscow")
            food = (await db.list_categories(7, "expense"))[0]
            salary = (await db.list_categories(7, "income"))[0]
            today = date(2026, 10, 23)

            first = await db.add_transaction(7, food.id, 12345, "обед", today)
            assert first is not None
            await db.add_transaction(7, food.id, 50000, None, today)
            await db.add_transaction(7, salary.id, 1000000, "оклад", today)
            await db.add_transaction(7, food.id, 99900, "вчера", date(2026, 10, 22))

            totals = await db.totals(7, today, today)
            assert totals.expense_minor == 62345
            assert totals.expense_count == 2
            assert totals.income_minor == 1000000
            assert totals.balance_minor == 937655
            assert totals.is_empty is False

            empty = await db.totals(7, date(2026, 1, 1), date(2026, 1, 31))
            assert empty.is_empty is True

            by_category = await db.totals_by_category(7, "expense", today, today)
            assert len(by_category) == 1
            assert by_category[0].total_minor == 62345
            assert by_category[0].count == 2

            # Категорию с операциями удалить нельзя.
            assert await db.delete_category(7, food.id) is False

            transaction = await db.get_transaction(7, first)
            assert transaction is not None
            assert transaction.category.name == "Продукты"
            assert transaction.spent_on == today

            # Чужой пользователь не видит операцию.
            await db.ensure_user(8, None, "Europe/Moscow")
            assert await db.get_transaction(8, first) is None

            assert await db.count_transactions(7) == 4
            page = await db.list_transactions(7, limit=2, offset=0)
            assert [item.id for item in page] == [3, 2]
            assert len(await db.all_transactions(7)) == 4

            assert await db.delete_transaction(7, first) is True
            assert await db.delete_transaction(7, first) is False
            assert await db.count_transactions(7) == 3

            # После удаления операций категорию уже можно удалить.
            assert await db.delete_transaction(7, 2) is True
            assert await db.delete_transaction(7, 4) is True
            assert await db.delete_category(7, food.id) is True
        finally:
            await db.close()

    asyncio.run(scenario())


def test_add_transaction_rejects_foreign_category(tmp_path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "bot.db")
        await db.connect()
        try:
            await db.ensure_user(1, None, "Europe/Moscow")
            await db.ensure_user(2, None, "Europe/Moscow")
            foreign = (await db.list_categories(2, "expense"))[0]

            result = await db.add_transaction(1, foreign.id, 1000, None, date(2026, 10, 23))
            assert result is None
        finally:
            await db.close()

    asyncio.run(scenario())
