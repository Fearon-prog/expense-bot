"""Слой доступа к SQLite: пользователи, категории и операции.

Суммы хранятся в копейках (целое число), чтобы не терять деньги на
округлениях float. Даты операций хранятся как локальная дата `YYYY-MM-DD`,
поэтому отчёты за период — это обычное сравнение строк.
"""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path

import aiosqlite

from .defaults import DEFAULT_EXPENSE_CATEGORIES, DEFAULT_INCOME_CATEGORIES
from .models import (
    Category,
    CategoryTotal,
    Family,
    FamilyMember,
    MemberTotal,
    Totals,
    Transaction,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    username     TEXT,
    display_name TEXT,
    timezone     TEXT NOT NULL DEFAULT 'Europe/Moscow',
    created_at   TEXT NOT NULL,
    seeded       INTEGER NOT NULL DEFAULT 0
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

CREATE TABLE IF NOT EXISTS families (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    invite_code TEXT NOT NULL UNIQUE,
    owner_id    INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS family_members (
    family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role      TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'member')),
    joined_at TEXT NOT NULL,
    PRIMARY KEY (family_id, user_id)
);

-- Человек может состоять только в одной семье.
CREATE UNIQUE INDEX IF NOT EXISTS ux_family_member_user
    ON family_members(user_id);
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


_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_code(length: int = 8) -> str:
    """Код приглашения без похожих символов (0/O, 1/I)."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def _to_family(row: aiosqlite.Row) -> Family:
    return Family(
        id=row["id"],
        name=row["name"],
        invite_code=row["invite_code"],
        owner_id=row["owner_id"],
    )


def _to_member(row: aiosqlite.Row) -> FamilyMember:
    return FamilyMember(
        user_id=row["user_id"],
        name=row["name"],
        role=row["role"],
        joined_at=row["joined_at"],
    )


def _placeholders(values: Sequence[int]) -> str:
    return ", ".join("?" for _ in values)


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
        await self._migrate()

    async def _migrate(self) -> None:
        """Дописывает колонки в базу, созданную прошлой версией бота."""
        async with self.conn.execute("PRAGMA table_info(users)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        if "display_name" not in columns:
            await self.conn.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
            await self.conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------ users

    async def ensure_user(
        self,
        user_id: int,
        username: str | None,
        timezone_name: str,
        display_name: str | None = None,
    ) -> None:
        """Создаёт пользователя и его стартовые категории; безопасно вызывать всегда."""
        await self.conn.execute(
            """
            INSERT INTO users(user_id, username, display_name, timezone, created_at, seeded)
            VALUES(?, ?, ?, ?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                display_name = excluded.display_name
            WHERE users.username IS NOT excluded.username
               OR users.display_name IS NOT excluded.display_name
            """,
            (user_id, username, display_name, timezone_name, _now()),
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

    # ----------------------------------------------------------------- family

    async def get_family(self, user_id: int) -> Family | None:
        async with self.conn.execute(
            """
            SELECT f.id, f.name, f.invite_code, f.owner_id
            FROM families f
            JOIN family_members m ON m.family_id = f.id
            WHERE m.user_id = ?
            """,
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return _to_family(row) if row is not None else None

    async def create_family(self, user_id: int, name: str) -> Family | None:
        """None, если пользователь уже состоит в семье."""
        if await self.get_family(user_id) is not None:
            return None

        for _ in range(10):
            code = _generate_code()
            try:
                cursor = await self.conn.execute(
                    """
                    INSERT INTO families(name, invite_code, owner_id, created_at)
                    VALUES(?, ?, ?, ?)
                    """,
                    (name, code, user_id, _now()),
                )
            except sqlite3.IntegrityError:
                continue

            family_id = int(cursor.lastrowid)
            try:
                await self.conn.execute(
                    """
                    INSERT INTO family_members(family_id, user_id, role, joined_at)
                    VALUES(?, ?, 'owner', ?)
                    """,
                    (family_id, user_id, _now()),
                )
            except sqlite3.IntegrityError:
                await self.conn.execute("DELETE FROM families WHERE id = ?", (family_id,))
                await self.conn.commit()
                return None

            await self.conn.commit()
            return Family(id=family_id, name=name, invite_code=code, owner_id=user_id)

        return None

    async def join_family(self, user_id: int, code: str) -> Family | None:
        """None, если код не найден или пользователь уже в семье."""
        normalised = code.strip().upper()
        if not normalised:
            return None

        async with self.conn.execute(
            "SELECT id, name, invite_code, owner_id FROM families WHERE invite_code = ?",
            (normalised,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None

        try:
            await self.conn.execute(
                """
                INSERT INTO family_members(family_id, user_id, role, joined_at)
                VALUES(?, ?, 'member', ?)
                """,
                (row["id"], user_id, _now()),
            )
        except sqlite3.IntegrityError:
            return None

        await self.conn.commit()
        return _to_family(row)

    async def get_family_members(self, family_id: int) -> list[FamilyMember]:
        async with self.conn.execute(
            """
            SELECT m.user_id, m.role, m.joined_at,
                   COALESCE(NULLIF(u.display_name, ''), u.username, 'Участник') AS name
            FROM family_members m
            JOIN users u ON u.user_id = m.user_id
            WHERE m.family_id = ?
            ORDER BY CASE m.role WHEN 'owner' THEN 0 ELSE 1 END, m.joined_at, m.user_id
            """,
            (family_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_to_member(row) for row in rows]

    async def leave_family(self, user_id: int) -> bool:
        """Выход из семьи. Если уходит владелец — права переходят следующему."""
        family = await self.get_family(user_id)
        if family is None:
            return False

        members = await self.get_family_members(family.id)
        others = [member for member in members if member.user_id != user_id]

        await self.conn.execute(
            "DELETE FROM family_members WHERE family_id = ? AND user_id = ?",
            (family.id, user_id),
        )

        if not others:
            await self.conn.execute("DELETE FROM families WHERE id = ?", (family.id,))
        elif family.owner_id == user_id:
            new_owner = others[0]
            await self.conn.execute(
                "UPDATE families SET owner_id = ? WHERE id = ?",
                (new_owner.user_id, family.id),
            )
            await self.conn.execute(
                "UPDATE family_members SET role = 'owner' WHERE family_id = ? AND user_id = ?",
                (family.id, new_owner.user_id),
            )

        await self.conn.commit()
        return True

    async def remove_member(self, owner_id: int, member_id: int) -> bool:
        family = await self.get_family(owner_id)
        if family is None or family.owner_id != owner_id or member_id == owner_id:
            return False

        cursor = await self.conn.execute(
            "DELETE FROM family_members WHERE family_id = ? AND user_id = ?",
            (family.id, member_id),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def regenerate_invite_code(self, user_id: int) -> str | None:
        family = await self.get_family(user_id)
        if family is None or family.owner_id != user_id:
            return None

        for _ in range(10):
            code = _generate_code()
            try:
                await self.conn.execute(
                    "UPDATE families SET invite_code = ? WHERE id = ?",
                    (code, family.id),
                )
            except sqlite3.IntegrityError:
                continue
            await self.conn.commit()
            return code
        return None

    async def family_totals(
        self,
        user_ids: Sequence[int],
        start: date,
        end: date,
    ) -> Totals:
        if not user_ids:
            return Totals()

        query = f"""
            SELECT kind, SUM(amount_minor) AS total, COUNT(*) AS cnt
            FROM transactions
            WHERE user_id IN ({_placeholders(user_ids)})
              AND spent_on BETWEEN ? AND ?
            GROUP BY kind
        """
        async with self.conn.execute(
            query,
            (*user_ids, start.isoformat(), end.isoformat()),
        ) as cursor:
            rows = await cursor.fetchall()

        values = {"expense": (0, 0), "income": (0, 0)}
        for row in rows:
            values[row["kind"]] = (int(row["total"]), int(row["cnt"]))

        return Totals(
            expense_minor=values["expense"][0],
            expense_count=values["expense"][1],
            income_minor=values["income"][0],
            income_count=values["income"][1],
        )

    async def family_totals_by_category(
        self,
        user_ids: Sequence[int],
        kind: str,
        start: date,
        end: date,
    ) -> list[CategoryTotal]:
        """Складывает одинаковые категории разных участников по названию."""
        if not user_ids:
            return []

        query = f"""
            SELECT MIN(c.name) AS name, MIN(c.emoji) AS emoji,
                   SUM(t.amount_minor) AS total, COUNT(*) AS cnt
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE t.user_id IN ({_placeholders(user_ids)})
              AND t.kind = ? AND t.spent_on BETWEEN ? AND ?
            GROUP BY c.name_key
            ORDER BY total DESC, name
        """
        async with self.conn.execute(
            query,
            (*user_ids, kind, start.isoformat(), end.isoformat()),
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            CategoryTotal(
                category=Category(
                    id=0,
                    kind=kind,
                    name=row["name"],
                    emoji=row["emoji"] or "",
                ),
                total_minor=int(row["total"]),
                count=int(row["cnt"]),
            )
            for row in rows
        ]

    async def family_totals_by_member(
        self,
        user_ids: Sequence[int],
        start: date,
        end: date,
    ) -> list[MemberTotal]:
        if not user_ids:
            return []

        query = f"""
            SELECT u.user_id,
                   COALESCE(NULLIF(u.display_name, ''), u.username, 'Участник') AS name,
                   t.kind, SUM(t.amount_minor) AS total, COUNT(*) AS cnt
            FROM transactions t
            JOIN users u ON u.user_id = t.user_id
            WHERE t.user_id IN ({_placeholders(user_ids)})
              AND t.spent_on BETWEEN ? AND ?
            GROUP BY u.user_id, t.kind
        """
        async with self.conn.execute(
            query,
            (*user_ids, start.isoformat(), end.isoformat()),
        ) as cursor:
            rows = await cursor.fetchall()

        stats: dict[int, dict] = {}
        for row in rows:
            entry = stats.setdefault(
                row["user_id"],
                {"name": row["name"], "expense": (0, 0), "income": (0, 0)},
            )
            entry[row["kind"]] = (int(row["total"]), int(row["cnt"]))

        members = [
            MemberTotal(
                user_id=user_id,
                name=entry["name"],
                expense_minor=entry["expense"][0],
                expense_count=entry["expense"][1],
                income_minor=entry["income"][0],
                income_count=entry["income"][1],
            )
            for user_id, entry in stats.items()
        ]
        members.sort(key=lambda member: (-member.expense_minor, member.name))
        return members

    async def family_transactions(
        self,
        user_ids: Sequence[int],
        limit: int,
        offset: int,
    ) -> list[Transaction]:
        if not user_ids:
            return []

        query = f"""
            SELECT t.id, t.kind, t.amount_minor, t.comment, t.spent_on, t.created_at,
                   c.id AS cat_id, c.kind AS cat_kind, c.name AS cat_name,
                   c.emoji AS cat_emoji,
                   COALESCE(NULLIF(u.display_name, ''), u.username, 'Участник') AS author_name
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            JOIN users u ON u.user_id = t.user_id
            WHERE t.user_id IN ({_placeholders(user_ids)})
            ORDER BY t.spent_on DESC, t.id DESC
            LIMIT ? OFFSET ?
        """
        async with self.conn.execute(query, (*user_ids, limit, offset)) as cursor:
            rows = await cursor.fetchall()

        return [
            Transaction(
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
                author_name=row["author_name"],
            )
            for row in rows
        ]

    async def count_family_transactions(self, user_ids: Sequence[int]) -> int:
        if not user_ids:
            return 0
        query = f"""
            SELECT COUNT(*) AS cnt FROM transactions
            WHERE user_id IN ({_placeholders(user_ids)})
        """
        async with self.conn.execute(query, tuple(user_ids)) as cursor:
            row = await cursor.fetchone()
        return int(row["cnt"]) if row is not None else 0

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
