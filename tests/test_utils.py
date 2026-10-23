"""Тесты чистой логики: разбор сумм, форматирование, периоды."""

from __future__ import annotations

from datetime import date

import pytest

from bot.utils import (
    format_money,
    format_range,
    parse_amount,
    period_bounds,
    plural,
    progress_bar,
)


@pytest.mark.parametrize(
    ("raw", "amount_minor", "comment"),
    [
        ("450", 45000, ""),
        ("450 такси", 45000, "такси"),
        ("такси 450", 45000, "такси"),
        ("1 200,50", 120050, ""),
        ("1\u00a0200,5", 120050, ""),
        ("1.200", 120000, ""),
        ("1,5", 150, ""),
        ("500 ₽", 50000, ""),
        ("300р", 30000, ""),
        ("1 200 руб.", 120000, ""),
        ("$20", 2000, ""),
        ("12 345 678,90", 1234567890, ""),
        ("1 200,50 кофе с собой", 120050, "кофе с собой"),
        ("  -,; 700 обед  ", 70000, "обед"),
    ],
)
def test_parse_amount_ok(raw: str, amount_minor: int, comment: str) -> None:
    parsed = parse_amount(raw)
    assert parsed is not None, raw
    assert parsed.amount_minor == amount_minor
    assert parsed.comment == comment


@pytest.mark.parametrize("raw", ["", "   ", None, "abc", "0", "0,00", "-500", "1e5"])
def test_parse_amount_invalid(raw: str | None) -> None:
    assert parse_amount(raw) is None


def test_parse_amount_limits_comment_length() -> None:
    parsed = parse_amount("100 " + "я" * 250)
    assert parsed is not None
    assert len(parsed.comment) == 200


def test_format_money() -> None:
    assert format_money(50000) == "500\u00a0₽"
    assert format_money(1234567) == "12\u202f345,67\u00a0₽"
    assert format_money(-12300) == "−123\u00a0₽"
    assert format_money(100, with_sign=True) == "+1\u00a0₽"
    assert format_money(0) == "0\u00a0₽"
    assert format_money(12345, "$") == "123,45\u00a0$"


def test_period_bounds() -> None:
    today = date(2026, 10, 23)  # пятница
    assert period_bounds("today", today) == (today, today)
    assert period_bounds("week", today) == (date(2026, 10, 19), today)
    assert period_bounds("month", today) == (date(2026, 10, 1), today)
    assert period_bounds("year", today) == (date(2026, 1, 1), today)
    assert period_bounds("all", today) == (date(1970, 1, 1), today)
    with pytest.raises(ValueError):
        period_bounds("decade", today)


def test_format_range() -> None:
    assert format_range(date(2026, 10, 23), date(2026, 10, 23)) == "23 октября 2026"
    assert format_range(date(2026, 10, 1), date(2026, 10, 23)) == "1–23 октября 2026"
    assert (
        format_range(date(2026, 9, 28), date(2026, 10, 23))
        == "28 сентября – 23 октября 2026"
    )
    assert (
        format_range(date(2025, 12, 1), date(2026, 1, 15))
        == "1 декабря 2025 – 15 января 2026"
    )


def test_plural() -> None:
    assert plural(1, "операция", "операции", "операций") == "операция"
    assert plural(2, "операция", "операции", "операций") == "операции"
    assert plural(5, "операция", "операции", "операций") == "операций"
    assert plural(11, "операция", "операции", "операций") == "операций"
    assert plural(21, "операция", "операции", "операций") == "операция"


def test_progress_bar() -> None:
    assert progress_bar(50, 100) == "█████░░░░░"
    assert progress_bar(0, 100) == "░░░░░░░░░░"
    assert progress_bar(100, 100) == "██████████"
    assert progress_bar(1, 100) == "█░░░░░░░░░"
    assert progress_bar(10, 0) == ""
