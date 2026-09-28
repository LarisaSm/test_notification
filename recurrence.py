"""Правила повторения напоминаний по дням недели (0 = Пн … 6 = Вс)."""

from datetime import datetime, time, timedelta
from typing import Iterable

WEEKDAY_NAMES = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
EVERY_DAY = frozenset(range(7))


def encode(days: Iterable[int]) -> str:
    """Множество дней → строка для БД, например {0, 2, 4} → "024"."""
    return "".join(str(d) for d in sorted(set(days)))


def decode(value: str) -> frozenset[int]:
    return frozenset(int(c) for c in value)


def describe(days: Iterable[int]) -> str:
    days = frozenset(days)
    if not days:
        return "—"
    if days == EVERY_DAY:
        return "Каждый день"
    return ", ".join(WEEKDAY_NAMES[d] for d in sorted(days))


def next_occurrence(after: datetime, at: time, days: Iterable[int]) -> datetime:
    """Ближайший момент строго позже after, приходящийся на один из days, во время at."""
    days = frozenset(days)
    if not days:
        raise ValueError("Не выбрано ни одного дня недели")
    for offset in range(8):
        candidate = datetime.combine(after.date() + timedelta(days=offset), at)
        if candidate.weekday() in days and candidate > after:
            return candidate
    raise AssertionError("unreachable")
