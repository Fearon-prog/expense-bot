"""Слой доступа к SQLite: пользователи, категории и операции.

Суммы хранятся в копейках (целое число), чтобы не терять деньги на
округлениях float. Даты операций хранятся как локальная дата `YYYY-MM-DD`,
поэтому отчёты за период — это обычное сравнение строк.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import aiosqlite

from .defaults import DEFAULT_EXPENSE_CATEGORIES, DEFAULT_INCOME_CATEGORIES
from .models import Category, CategoryTotal, Totals, Transaction

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    timezone   TEXT NOT NULL DEFAULT 'Europe/Moscow',
    created_at TEXT NOT NULL,
    seeded     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    name       TEXT NOT NULL,
    name_key   TEXT NOT NULL,
    emoji      TEXT NOT NULL DEFAULT '',
    position   INTEGER NOT NULL DEFAULT 1000,
    created_at TEXT NOT NULL
);

-- name_key — это casefold-версия названия: встроенный NOCASE в SQLite
-- не умеет кириллицу, поэтому сравнение делаем в Python.
CREATE UNIQUE INDEX IF NOT EXISTS ux_categories_name
    ON categories(user_id, kind, name_key);

CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    category_id  INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    kind         TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    comment      TEXT,
    spent_on     TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_transactions_user_date
    ON transactions(user_id, spent_on);
CREATE INDEX IF NOT EXISTS ix_transactions_category
    ON transactions(category_id);
"""

_TX_SELECT = """
SELECT t.id, t.kind, t.amount_minor, t.comment, t.spent_on, t.created_at,
       c.id AS cat_id, c.kind AS cat_kind, c.name AS cat_name, c.emoji AS cat_emoji
FROM transactions t
JOIN categories c ON c.id = t.category_id
"""


def _to_category(row: aiosqlite.Row) -> Category:
    return Category(
        id=row["id"],
        kind=row["kind"],
        name=row["name"],
        emoji=row["emoji"],
    )


def _to_transaction(row: aiosqlite.Row) -> Transaction:
    return Transaction(
        id=row["id"],
        kind=row["kind"],
        amount_minor=row["amount_minor"],
        comment=row["comment"],
        spent_on=date.fromisoformat(row["spent_on"]),
        created_at=row["created_at"],
        category=Category(
            id=row["cat_id"],
            kind=row["cat_kind"],
            name=row["cat_name"],
            emoji=row["cat_emoji"],
        ),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База не подключена: сначала вызовите Database.connect()")
        return self._conn

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------ users

    async def ensure_user(self, user_id: int, username: str | None, timezone_name: str) -> None:
        """Создаёт пользователя и его стартовые категории; безопасно вызывать всегда."""
        await self.conn.execute(
            """
            INSERT INTO users(user_id, username, timezone, created_at, seeded)
            VALUES(?, ?, ?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
            WHERE users.username IS NOT excluded.username
            """,
            (user_id, username, timezone_name, _now()),
        )
        await self.conn.commit()

        async with self.conn.execute(
            "SELECT seeded FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is not None and not row["seeded"]:
            await self._seed_categories(user_id)

    async def _seed_categories(self, user_id: int) -> None:
        created_at = _now()
        rows = [
            (user_id, "expense", name, name.casefold(), emoji, position, created_at)
            for position, (name, emoji) in enumerate(DEFAULT_EXPENSE_CATEGORIES)
        ]
        rows += [
            (user_id, "income", name, name.casefold(), emoji, position, created_at)
            for position, (name, emoji) in enumerate(DEFAULT_INCOME_CATEGORIES)
        ]
        await self.conn.executemany(
            """
            INSERT OR IGNORE INTO categories(
                user_id, kind, name, name_key, emoji, position, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await self.conn.execute("UPDATE users SET seeded = 1 WHERE user_id = ?", (user_id,))
        await self.conn.commit()

    # ------------------------------------------------------------- categories

    async def list_categories(self, user_id: int, kind: str) -> list[Category]:
        async with self.conn.execute(
            """
            SELECT id, kind, name, emoji FROM categories
            WHERE user_id = ? AND kind = ?
            ORDER BY position, id
            """,
            (user_id, kind),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_to_category(row) for row in rows]

    async def get_category(self, user_id: int, category_id: int) -> Category | None:
        async with self.conn.execute(
            "SELECT id, kind, name, emoji FROM categories WHERE id = ? AND user_id = ?",
            (category_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
        return _to_category(row) if row is not None else None

    async def add_category(
        self,
        user_id: int,
        kind: str,
        name: str,
        emoji: str = "🏷",
    ) -> Category | None:
        """Возвращает None, если категория с таким названием уже существует."""
        try:
            cursor = await self.conn.execute(
                """
                INSERT INTO categories(
                    user_id, kind, name, name_key, emoji, position, created_at
                ) VALUES(?, ?, ?, ?, ?, 1000, ?)
                """,
                (user_id, kind, name, name.casefold(), emoji, _now()),
            )
        except sqlite3.IntegrityError:
            return None
        await self.conn.commit()
        return Category(id=int(cursor.lastrowid), kind=kind, name=name, emoji=emoji)

    async def rename_category(self, user_id: int, category_id: int, name: str) -> bool:
        try:
            cursor = await self.conn.execute(
                "UPDATE categories SET name = ?, name_key = ? WHERE id = ? AND user_id = ?",
                (name, name.casefold(), category_id, user_id),
            )
        except sqlite3.IntegrityError:
            return False
        await self.conn.commit()
        return cursor.rowcount > 0

    async def delete_category(self, user_id: int, category_id: int) -> bool:
        """False, если категории нет или в ней есть операции (ON DELETE RESTRICT)."""
        try:
            cursor = await self.conn.execute(
                "DELETE FROM categories WHERE id = ? AND user_id = ?",
                (category_id, user_id),
            )
        except sqlite3.IntegrityError:
            return False
        await self.conn.commit()
        return cursor.rowcount > 0

    async def category_stats(self, user_id: int, category_id: int) -> tuple[int, int]:
        """(сумма в копейках, количество операций) по категории за всё время."""
        async with self.conn.execute(
            """
            SELECT COALESCE(SUM(amount_minor), 0) AS total, COUNT(*) AS cnt
            FROM transactions WHERE user_id = ? AND category_id = ?
            """,
            (user_id, category_id),
        ) as cursor:
            row = await cursor.fetchone()
        return (int(row["total"]), int(row["cnt"])) if row is not None else (0, 0)

    # ----------------------------------------------------------- transactions

    async def add_transaction(
        self,
        user_id: int,
        category_id: int,
        amount_minor: int,
        comment: str | None,
        spent_on: date,
    ) -> int | None:
        """None, если категория не найдена или принадлежит другому пользователю."""
        category = await self.get_category(user_id, category_id)
        if category is None:
            return None

        cursor = await self.conn.execute(
            """
            INSERT INTO transactions(
                user_id, category_id, kind, amount_minor, comment, spent_on, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                category.id,
                category.kind,
                amount_minor,
                comment,
                spent_on.isoformat(),
                _now(),
            ),
        )
        await self.conn.commit()
        return int(cursor.lastrowid)

    async def get_transaction(self, user_id: int, transaction_id: int) -> Transaction | None:
        async with self.conn.execute(
            _TX_SELECT + " WHERE t.user_id = ? AND t.id = ?",
            (user_id, transaction_id),
        ) as cursor:
            row = await cursor.fetchone()
        return _to_transaction(row) if row is not None else None

    async def delete_transaction(self, user_id: int, transaction_id: int) -> bool:
        cursor = await self.conn.execute(
            "DELETE FROM transactions WHERE id = ? AND user_id = ?",
            (transaction_id, user_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def list_transactions(self, user_id: int, limit: int, offset: int) -> list[Transaction]:
        async with self.conn.execute(
            _TX_SELECT + " WHERE t.user_id = ? ORDER BY t.spent_on DESC, t.id DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_to_transaction(row) for row in rows]

    async def count_transactions(self, user_id: int) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM transactions WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["cnt"]) if row is not None else 0

    async def all_transactions(self, user_id: int) -> list[Transaction]:
        async with self.conn.execute(
            _TX_SELECT + " WHERE t.user_id = ? ORDER BY t.spent_on, t.id",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_to_transaction(row) for row in rows]

    # ---------------------------------------------------------------- reports

    async def totals(self, user_id: int, start: date, end: date) -> Totals:
        async with self.conn.execute(
            """
            SELECT kind, SUM(amount_minor) AS total, COUNT(*) AS cnt
            FROM transactions
            WHERE user_id = ? AND spent_on BETWEEN ? AND ?
            GROUP BY kind
            """,
            (user_id, start.isoformat(), end.isoformat()),
        ) as cursor:
            rows = await cursor.fetchall()

        values = {
            "expense": (0, 0),
            "income": (0, 0),
        }
        for row in rows:
            values[row["kind"]] = (int(row["total"]), int(row["cnt"]))

        expense_total, expense_count = values["expense"]
        income_total, income_count = values["income"]
        return Totals(
            expense_minor=expense_total,
            expense_count=expense_count,
            income_minor=income_total,
            income_count=income_count,
        )

    async def totals_by_category(
        self,
        user_id: int,
        kind: str,
        start: date,
        end: date,
    ) -> list[CategoryTotal]:
        async with self.conn.execute(
            """
            SELECT c.id, c.kind, c.name, c.emoji,
                   SUM(t.amount_minor) AS total, COUNT(*) AS cnt
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE t.user_id = ? AND t.kind = ? AND t.spent_on BETWEEN ? AND ?
            GROUP BY c.id, c.kind, c.name, c.emoji
            ORDER BY total DESC, c.name
            """,
            (user_id, kind, start.isoformat(), end.isoformat()),
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            CategoryTotal(
                category=Category(
                    id=row["id"],
                    kind=row["kind"],
                    name=row["name"],
                    emoji=row["emoji"],
                ),
                total_minor=int(row["total"]),
                count=int(row["cnt"]),
            )
            for row in rows
        ]
