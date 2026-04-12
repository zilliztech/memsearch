"""Unit tests for _build_date_filter (date-range search filtering)."""

from datetime import date

import pytest

from memsearch.core import _build_date_filter


def test_both_none_returns_empty():
    assert _build_date_filter(None, None) == ""


def test_single_day():
    result = _build_date_filter(date(2026, 4, 5), date(2026, 4, 5))
    assert result == '(source like "%2026-04-05.md")'


def test_partial_month_no_wildcard():
    result = _build_date_filter(date(2026, 4, 3), date(2026, 4, 5))
    assert 'source like "%2026-04-03.md"' in result
    assert 'source like "%2026-04-04.md"' in result
    assert 'source like "%2026-04-05.md"' in result
    assert result.startswith("(") and result.endswith(")")


def test_full_month_uses_wildcard():
    result = _build_date_filter(date(2026, 3, 1), date(2026, 3, 31))
    assert result == '(source like "%2026-03-%.md")'


def test_multi_month_range():
    # Jan 1 - Mar 31: three full months
    result = _build_date_filter(date(2026, 1, 1), date(2026, 3, 31))
    assert 'source like "%2026-01-%.md"' in result
    assert 'source like "%2026-02-%.md"' in result
    assert 'source like "%2026-03-%.md"' in result
    # Should have exactly 3 clauses (one per month)
    assert result.count("source like") == 3


def test_mixed_full_and_partial_months():
    # Jan 15 - Mar 31: partial Jan, full Feb, full Mar
    result = _build_date_filter(date(2026, 1, 15), date(2026, 3, 31))
    # Jan should be per-day (15th through 31st = 17 days)
    assert 'source like "%2026-01-15.md"' in result
    assert 'source like "%2026-01-31.md"' in result
    # Feb and Mar should be wildcards
    assert 'source like "%2026-02-%.md"' in result
    assert 'source like "%2026-03-%.md"' in result


def test_date_after_only():
    """date_after without date_before uses today as end."""
    result = _build_date_filter(date(2026, 4, 5), None)
    # Should produce at least one clause for that date (today)
    assert 'source like "%2026-04-05.md"' in result


def test_date_before_only():
    """date_before without date_after uses 2000-01-01 as start."""
    result = _build_date_filter(None, date(2000, 1, 2))
    assert 'source like "%2000-01-01.md"' in result
    assert 'source like "%2000-01-02.md"' in result


def test_invalid_range_raises():
    with pytest.raises(ValueError, match=r"date_after.*must be before"):
        _build_date_filter(date(2026, 5, 1), date(2026, 4, 1))


def test_february_leap_year():
    # Feb 2024 is a leap year (29 days) -- full month wildcard
    result = _build_date_filter(date(2024, 2, 1), date(2024, 2, 29))
    assert result == '(source like "%2024-02-%.md")'


def test_clauses_joined_with_or():
    result = _build_date_filter(date(2026, 4, 1), date(2026, 4, 3))
    # Partial month, 3 days
    assert " or " in result
    assert " and " not in result
