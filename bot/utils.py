"""Чистые функции без зависимостей от Telegram: суммы, даты, периоды.

Здесь живёт вся «математика» бота, поэтому эти функции легко тестировать
отдельно от aiogram.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MAX_AMOUNT_MINOR = 10**11  # 1 000 000 000 ₽ — верхняя граница для одной операции
MAX_COMMENT_LENGTH = 200
MAX_MESSAGE_LENGTH = 300

MONTHS_GEN = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

MONTHS_NOM = (
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)

PERIOD_LABELS: dict[str, str] = {
    "today": "Сегодня",
    "week": "Неделя",
    "month": "Месяц",
    "year": "Год",
    "all": "Всё время",
}
PERIODS = tuple(PERIOD_LABELS)

# Символы, которые пользователь может поставить по краям комментария.
_EDGE_CHARS = " \t\r\n,.;:!?—–-()[]{}\"'«»"

# «1.200» и «1,200» — это тысячные разделители, а не копейки.
_THOUSANDS = re.compile(r"(?<=\d)[.,](?=\d{3}(?!\d))")

# Первое число в строке: «1 200,50», «450», «12.5».
_NUMBER = re.compile(r"(?<!\d)(\d{1,3}(?:\s\d{3})+|\d+)(?:[.,](\d{1,2}))?(?!\d)")

# «500 ₽», «1 200 руб.», «300 р», «$20».
_CURRENCY_TAIL = re.compile(
    r"(?i)(?<=\d)\s*(?:₽|рублей|рубля|руб\.?|р\.?|rub\.?|rur\.?|usd\.?|eur\.?)(?![а-яёa-z])"
)
_CURRENCY_SYMBOL = re.compile(r"[₽$€]")


@dataclass(frozen=True, slots=True)
class ParsedAmount:
    amount_minor: int
    comment: str = ""


def esc(value: object) -> str:
    """Экранирует пользовательский текст для parse_mode=HTML."""
    return html.escape(str(value), quote=False)


def today_in(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def _normalize_amount_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ")
    text = _CURRENCY_SYMBOL.sub(" ", text)
    text = _CURRENCY_TAIL.sub(" ", text)
    text = _THOUSANDS.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_comment(value: str) -> str:
    value = re.sub(r"\s+", " ", value)
    value = value.strip(_EDGE_CHARS)
    return re.sub(r"\s+", " ", value).strip()


def parse_amount(raw: str | None) -> ParsedAmount | None:
    """Разбирает строку вида «1 200,50 обед» в копейки и комментарий.

    Возвращает None, если сумму распознать не удалось или она некорректна.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or len(text) > MAX_MESSAGE_LENGTH:
        return None
    # Отрицательные суммы не нужны: «-500» — почти наверняка опечатка.
    if re.match(r"^[−-]\s*\d", text):
        return None

    text = _normalize_amount_text(text)
    match = _NUMBER.search(text)
    if match is None:
        return None
    # «1e5» — не сумма, а случайный текст; «500 такси» при этом остаётся суммой.
    if re.match(r"[eE][+-]?\d", text[match.end() :]):
        return None

    whole = re.sub(r"\s", "", match.group(1))
    fraction = match.group(2) or ""
    try:
        amount_minor = int(whole) * 100 + (int(fraction.ljust(2, "0")) if fraction else 0)
    except ValueError:  # pragma: no cover - защитный сценарий
        return None

    if amount_minor <= 0 or amount_minor > MAX_AMOUNT_MINOR:
        return None

    comment = _normalize_comment(f"{text[: match.start()]} {text[match.end():]}")
    return ParsedAmount(amount_minor=amount_minor, comment=comment[:MAX_COMMENT_LENGTH])


def format_money(
    amount_minor: int,
    currency: str = "₽",
    *,
    with_sign: bool = False,
) -> str:
    """1 234 567 копеек -> «12 345,67 ₽»."""
    sign = ""
    if amount_minor < 0:
        sign, amount_minor = "−", -amount_minor
    elif with_sign and amount_minor > 0:
        sign = "+"

    rubles, kopecks = divmod(amount_minor, 100)
    body = f"{rubles:,}".replace(",", "\u202f")
    if kopecks:
        body = f"{body},{kopecks:02d}"
    return f"{sign}{body}\u00a0{currency}" if currency else f"{sign}{body}"


def percent(part: int, total: int) -> int:
    if total <= 0:
        return 0
    return round(part * 100 / total)


def progress_bar(value: int, maximum: int, width: int = 10) -> str:
    if maximum <= 0:
        return ""
    if value <= 0:
        return "░" * width
    filled = max(1, round(value / maximum * width))
    filled = min(filled, width)
    return "█" * filled + "░" * (width - filled)


def plural(number: int, one: str, few: str, many: str) -> str:
    number = abs(number) % 100
    if 11 <= number <= 14:
        return many
    number %= 10
    if number == 1:
        return one
    if 2 <= number <= 4:
        return few
    return many


def format_day(value: date) -> str:
    return f"{value.day} {MONTHS_GEN[value.month - 1]}"


def format_date(value: date, *, with_year: bool = True) -> str:
    base = f"{value.day} {MONTHS_GEN[value.month - 1]}"
    return f"{base} {value.year}" if with_year else base


def format_range(start: date, end: date) -> str:
    if start == end:
        return format_date(start)
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.day} {MONTHS_GEN[end.month - 1]} {end.year}"
    if start.year == end.year:
        return (
            f"{start.day} {MONTHS_GEN[start.month - 1]} – "
            f"{end.day} {MONTHS_GEN[end.month - 1]} {end.year}"
        )
    return f"{format_date(start)} – {format_date(end)}"


def period_bounds(period: str, today: date) -> tuple[date, date]:
    """Границы периода включительно. Неделя начинается с понедельника."""
    if period == "today":
        return today, today
    if period == "week":
        return today - timedelta(days=today.weekday()), today
    if period == "month":
        return today.replace(day=1), today
    if period == "year":
        return today.replace(month=1, day=1), today
    if period == "all":
        return date(1970, 1, 1), today
    raise ValueError(f"Неизвестный период: {period!r}")


def period_title(period: str, today: date) -> str:
    if period == "today":
        return f"Сегодня, {format_day(today)}"
    if period == "week":
        return "Неделя"
    if period == "month":
        return f"{MONTHS_NOM[today.month - 1]} {today.year}"
    if period == "year":
        return f"{today.year} год"
    return "Всё время"
