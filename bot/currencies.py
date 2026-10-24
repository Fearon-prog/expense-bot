"""Валюты, которые можно выбрать в настройках."""

from __future__ import annotations

CURRENCIES: tuple[tuple[str, str], ...] = (
    ("₽", "Российский рубль"),
    ("$", "Доллар США"),
    ("€", "Евро"),
    ("¥", "Японская иена"),
    ("₸", "Казахский тенге"),
    ("₴", "Украинская гривна"),
    ("Br", "Белорусский рубль"),
    ("£", "Фунт стерлингов"),
    ("₾", "Грузинский лари"),
)

_NAMES = dict(CURRENCIES)


def currency_label(symbol: str) -> str:
    name = _NAMES.get(symbol)
    return f"{symbol} — {name}" if name else symbol


def currency_index(symbol: str) -> int | None:
    for index, (item, _) in enumerate(CURRENCIES):
        if item == symbol:
            return index
    return None
