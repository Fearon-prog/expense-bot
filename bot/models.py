"""Простые модели данных, которыми обмениваются база и обработчики."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

EXPENSE = "expense"
INCOME = "income"


@dataclass(frozen=True, slots=True)
class Category:
    id: int
    kind: str
    name: str
    emoji: str = ""

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}".strip()

    @property
    def is_expense(self) -> bool:
        return self.kind == EXPENSE


@dataclass(frozen=True, slots=True)
class Transaction:
    id: int
    kind: str
    amount_minor: int
    comment: str | None
    spent_on: date
    created_at: str
    category: Category
    author_name: str | None = None
    batch_id: str | None = None

    @property
    def is_expense(self) -> bool:
        return self.kind == EXPENSE


@dataclass(frozen=True, slots=True)
class CategoryTotal:
    category: Category
    total_minor: int
    count: int


@dataclass(frozen=True, slots=True)
class Totals:
    expense_minor: int = 0
    expense_count: int = 0
    income_minor: int = 0
    income_count: int = 0

    @property
    def balance_minor(self) -> int:
        return self.income_minor - self.expense_minor

    @property
    def is_empty(self) -> bool:
        return self.expense_count == 0 and self.income_count == 0


@dataclass(frozen=True, slots=True)
class Family:
    id: int
    name: str
    invite_code: str
    owner_id: int


@dataclass(frozen=True, slots=True)
class FamilyMember:
    user_id: int
    name: str
    role: str
    joined_at: str

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


@dataclass(frozen=True, slots=True)
class MemberTotal:
    user_id: int
    name: str
    expense_minor: int = 0
    expense_count: int = 0
    income_minor: int = 0
    income_count: int = 0

    @property
    def balance_minor(self) -> int:
        return self.income_minor - self.expense_minor
