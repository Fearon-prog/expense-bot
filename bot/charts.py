"""PNG-диаграммы для отчётов: кольцевые схемы по категориям.

Цвет каждой категории задаётся один раз на диаграмму и повторяется во всех
панелях — так на семейном отчёте видно, что «Продукты» у всех одного цвета.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

from .utils import format_money


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
from matplotlib.patches import Patch  # noqa: E402

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


def _draw_donut(
    axes,
    items: list[tuple[str, int]],
    title: str,
    colors: dict[str, str],
    currency: str,
) -> None:
    values = [value for _, value in items]
    palette = [colors.get(name, MUTED) for name, _ in items]

    axes.pie(
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
    axes.set_title(title, fontsize=10.5, fontweight="bold", color="#333333", pad=10)
    axes.set_aspect("equal")
    axes.set_anchor("N")


def _add_legend(fig: Figure, names: list[str], colors: dict[str, str]) -> int:
    columns = min(4, max(1, len(names)))
    handles = [
        Patch(facecolor=colors[name], edgecolor="white", label=name) for name in names
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.0),
        ncol=columns,
        frameon=False,
        fontsize=8,
        handlelength=1.2,
        columnspacing=1.4,
    )
    return max(1, (len(names) + columns - 1) // columns)


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

    fig = Figure(figsize=(panel_width * len(panels), 4.5), dpi=150)
    FigureCanvasAgg(fig)

    axes_list = fig.subplots(1, len(panels), squeeze=False)[0]
    for axes, (title, items) in zip(axes_list, panels):
        _draw_donut(axes, items, title, colors, currency)

    rows = _add_legend(fig, names, colors)
    fig.subplots_adjust(
        left=0.02,
        right=0.98,
        top=0.93,
        bottom=0.04 + 0.055 * rows,
        wspace=0.06,
    )
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

    return _build_panels(panels, currency, panel_width=4.4)


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
    return _build_panels(panels, currency, panel_width=3.9)
