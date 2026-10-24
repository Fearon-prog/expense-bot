"""PNG-диаграммы для отчётов: кольцевые схемы с подписями и процентами.

Подписи стоят вокруг диаграммы, от каждой секции к своей подписи идёт
стрелка. Цвет категории задаётся один раз на диаграмму и повторяется во всех
панелях — на семейном отчёте «Продукты» у всех одного цвета.
"""

from __future__ import annotations

import io
import math
import os
from pathlib import Path

from .utils import format_money, percent


def _configure_cache() -> None:
    """Кэш шрифтов matplotlib держим в проекте, а не в профиле пользователя."""
    if os.environ.get("MPLCONFIGDIR"):
        return
    try:
        cache = Path(__file__).resolve().parent.parent / ".cache" / "matplotlib"
        cache.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(cache)
    except OSError:
        pass


_configure_cache()

from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

PALETTE = (
    "#4E79A7",
    "#F28E2B",
    "#E15759",
    "#76B7B2",
    "#59A14F",
    "#EDC948",
    "#B07AA1",
    "#FF9DA7",
    "#9C755F",
    "#86BCB6",
    "#D37295",
    "#FABFD2",
    "#B6992D",
    "#499894",
    "#A0CBE8",
    "#8CD17D",
)
MUTED = "#B0B0B0"
MAX_SLICES = 7
MAX_PANELS = 6
MIN_LABEL_GAP = 0.19
LABEL_RADIUS = 1.38


def _prepare(items: list[tuple[str, int]]) -> list[tuple[str, int]]:
    clean = [(label, value) for label, value in items if value > 0]
    clean.sort(key=lambda item: (-item[1], item[0]))
    if len(clean) > MAX_SLICES:
        head = clean[: MAX_SLICES - 1]
        rest = sum(value for _, value in clean[MAX_SLICES - 1 :])
        head.append(("Остальное", rest))
        return head
    return clean


def _ordered_names(panels: list[tuple[str, list[tuple[str, int]]]]) -> list[str]:
    totals: dict[str, int] = {}
    for _, items in panels:
        for name, value in items:
            totals[name] = totals.get(name, 0) + value

    names = sorted(
        (name for name in totals if name != "Остальное"),
        key=lambda name: (-totals[name], name),
    )
    if "Остальное" in totals:
        names.append("Остальное")
    return names


def _colors_for(names: list[str]) -> dict[str, str]:
    return {
        name: (MUTED if name == "Остальное" else PALETTE[index % len(PALETTE)])
        for index, name in enumerate(names)
    }


def _spread(entries: list[dict]) -> None:
    """Раздвигает подписи по вертикали, чтобы они не наезжали друг на друга."""
    entries.sort(key=lambda entry: entry["label_y"])
    for index in range(1, len(entries)):
        gap = entries[index]["label_y"] - entries[index - 1]["label_y"]
        if gap < MIN_LABEL_GAP:
            entries[index]["label_y"] = entries[index - 1]["label_y"] + MIN_LABEL_GAP


def _label_wedges(axes, wedges, items: list[tuple[str, int]], colors: dict[str, str]) -> None:
    total = sum(value for _, value in items)
    entries: list[dict] = []

    for wedge, (name, value) in zip(wedges, items):
        angle = math.radians((wedge.theta1 + wedge.theta2) / 2.0)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        entries.append(
            {
                "name": name,
                "value": value,
                "cos": cos_a,
                "sin": sin_a,
                "side": 1 if cos_a >= 0 else -1,
                "label_y": sin_a * 1.12,
            }
        )

    _spread([entry for entry in entries if entry["side"] > 0])
    _spread([entry for entry in entries if entry["side"] < 0])

    for entry in entries:
        share = percent(entry["value"], total) if total else 0
        share_label = f"{share}%" if share else "<1%"
        axes.annotate(
            f"{entry['name']} · {share_label}",
            xy=(entry["cos"] * 1.0, entry["sin"] * 1.0),
            xytext=(entry["side"] * LABEL_RADIUS, entry["label_y"]),
            ha="left" if entry["side"] > 0 else "right",
            va="center",
            fontsize=8,
            color="#333333",
            annotation_clip=False,
            arrowprops={
                "arrowstyle": "-|>",
                "color": colors.get(entry["name"], "#888888"),
                "lw": 0.9,
                "shrinkA": 0,
                "shrinkB": 0,
                "mutation_scale": 7,
            },
        )

    ys = [entry["label_y"] for entry in entries] or [0.0]
    axes.set_xlim(-2.2, 2.2)
    axes.set_ylim(min(-1.25, min(ys) - 0.15), max(1.25, max(ys) + 0.15))


def _draw_donut(
    axes,
    items: list[tuple[str, int]],
    title: str,
    colors: dict[str, str],
    currency: str,
) -> list:
    values = [value for _, value in items]
    palette = [colors.get(name, MUTED) for name, _ in items]

    wedges, _ = axes.pie(
        values,
        colors=palette,
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 1.2},
    )
    axes.text(
        0,
        0,
        format_money(sum(values), currency),
        ha="center",
        va="center",
        fontsize=9,
        fontweight="bold",
        color="#333333",
    )
    axes.set_title(title, fontsize=10.5, fontweight="bold", color="#333333", pad=12)
    axes.set_aspect("equal")
    axes.set_anchor("N")
    return wedges


def _to_png(fig: Figure) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(
        buffer,
        format="png",
        facecolor="white",
        bbox_inches="tight",
        pad_inches=0.15,
    )
    return buffer.getvalue()


def _build_panels(
    panels: list[tuple[str, list[tuple[str, int]]]],
    currency: str,
    panel_width: float,
) -> bytes:
    names = _ordered_names(panels)
    colors = _colors_for(names)

    fig = Figure(figsize=(panel_width * len(panels), 4.4), dpi=150)
    FigureCanvasAgg(fig)

    axes_list = fig.subplots(1, len(panels), squeeze=False)[0]
    for axes, (title, items) in zip(axes_list, panels):
        wedges = _draw_donut(axes, items, title, colors, currency)
        _label_wedges(axes, wedges, items, colors)

    fig.subplots_adjust(left=0.02, right=0.98, top=0.90, bottom=0.03, wspace=0.10)
    return _to_png(fig)


def expenses_income_chart(
    expense: list[tuple[str, int]],
    income: list[tuple[str, int]],
    currency: str,
) -> bytes | None:
    """Две диаграммы рядом: расходы и доходы. None, если данных нет."""
    panels: list[tuple[str, list[tuple[str, int]]]] = []
    expense_items = _prepare(expense)
    income_items = _prepare(income)

    if expense_items:
        panels.append(("Расходы", expense_items))
    if income_items:
        panels.append(("Доходы", income_items))
    if not panels:
        return None

    return _build_panels(panels, currency, panel_width=4.6)


def family_chart(
    combined: list[tuple[str, int]],
    members: list[tuple[str, list[tuple[str, int]]]],
    currency: str,
) -> bytes | None:
    """Общая диаграмма семьи + отдельная диаграмма каждого участника."""
    combined_items = _prepare(combined)
    if not combined_items:
        return None

    panels: list[tuple[str, list[tuple[str, int]]]] = [("Вся семья", combined_items)]
    for name, items in members:
        prepared = _prepare(items)
        if prepared:
            short_name = name if len(name) <= 18 else name[:17] + "…"
            panels.append((short_name, prepared))

    panels = panels[:MAX_PANELS]
    return _build_panels(panels, currency, panel_width=4.2)
