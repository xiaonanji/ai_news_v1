from __future__ import annotations

from datetime import datetime, timedelta, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_year_week(dt: datetime) -> tuple[int, int]:
    iso = dt.isocalendar()
    return iso.year, iso.week


def iso_week_bounds(dt: datetime) -> tuple[datetime, datetime]:
    # ISO week starts Monday
    weekday = dt.isoweekday()
    start = datetime(dt.year, dt.month, dt.day, tzinfo=dt.tzinfo) - timedelta(
        days=weekday - 1
    )
    end = start + timedelta(days=7)
    return start, end


def to_iso(dt: datetime) -> str:
    return dt.isoformat()
