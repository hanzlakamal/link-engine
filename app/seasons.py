"""US retail calendar so playbooks pick the right season automatically.

GPT's plan hard-coded "it's November, push Thanksgiving/Christmas". This computes it for
any date, so the same playbook works for a launch in March or August.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


@dataclass(frozen=True)
class Moment:
    key: str
    name: str
    date: date
    lead_days: int  # when to start pushing it (content + PR lead time)
    angle: str


def moments(year: int) -> list[Moment]:
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    return sorted([
        Moment("valentines", "Valentine's Day", date(year, 2, 14), 21, "couples, anti-Valentine humor, galentine"),
        Moment("st_patricks", "St. Patrick's Day", date(year, 3, 17), 21, "drinking/Irish humor"),
        Moment("mothers_day", "Mother's Day", _nth_weekday(year, 5, 6, 2), 28, "mom-life humor gifts"),
        Moment("fathers_day", "Father's Day", _nth_weekday(year, 6, 6, 3), 28, "dad jokes, grill, golf"),
        Moment("july4", "4th of July", date(year, 7, 4), 21, "patriotic + BBQ humor"),
        Moment("back_to_school", "Back to School", date(year, 8, 15), 21, "teacher + college humor"),
        Moment("halloween", "Halloween", date(year, 10, 31), 35, "spooky, costume-lazy shirts"),
        Moment("thanksgiving", "Thanksgiving", thanksgiving, 21, "family-dinner, turkey, food-coma humor"),
        Moment("bfcm", "Black Friday / Cyber Monday", thanksgiving + timedelta(days=1), 21, "biggest sale window; build list before"),
        Moment("christmas_ship", "Christmas shipping cutoff", date(year, 12, 15), 30, "gift guides, ugly-sweater alternatives, family matching"),
        Moment("christmas", "Christmas", date(year, 12, 25), 45, "gifts, family matching, white elephant"),
        Moment("new_year", "New Year", date(year + 1, 1, 1), 14, "resolution humor"),
        Moment("memorial_day", "Memorial Day", _last_weekday(year, 5, 0), 14, "summer kickoff sale"),
    ], key=lambda m: m.date)


def upcoming(today: date, horizon_days: int = 60) -> list[Moment]:
    """Moments whose push window overlaps [today, today+horizon]."""
    out = []
    for y in (today.year - 1, today.year, today.year + 1):
        for m in moments(y):
            start = m.date - timedelta(days=m.lead_days)
            if m.date >= today and start <= today + timedelta(days=horizon_days):
                out.append(m)
    seen, uniq = set(), []
    for m in sorted(out, key=lambda m: m.date):
        if (m.key, m.date) not in seen:
            seen.add((m.key, m.date))
            uniq.append(m)
    return uniq
