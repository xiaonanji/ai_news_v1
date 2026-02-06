from datetime import datetime, timezone

from src.core.time_utils import iso_week_bounds, iso_year_week


def test_iso_year_week():
    dt = datetime(2026, 2, 6, tzinfo=timezone.utc)
    year, week = iso_year_week(dt)
    assert year == 2026
    assert isinstance(week, int)


def test_iso_week_bounds():
    dt = datetime(2026, 2, 6, tzinfo=timezone.utc)
    start, end = iso_week_bounds(dt)
    assert start < end
    assert (end - start).days == 7
