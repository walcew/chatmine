import time
from datetime import UTC, datetime, timedelta

import pytest

from chatmine.window import resolve_window

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def sao_paulo(monkeypatch):
    monkeypatch.setenv("TZ", "America/Sao_Paulo")  # UTC-3, sem horário de verão em 2026
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_default_is_last_seven_days():
    start, end = resolve_window(None, None, None, NOW)
    assert (start, end) == (NOW - timedelta(days=7), NOW)


def test_days_only():
    start, end = resolve_window(None, None, 2, NOW)
    assert (start, end) == (NOW - timedelta(days=2), NOW)


def test_since_and_days_conflict():
    with pytest.raises(ValueError, match="--since"):
        resolve_window("2026-10-01", None, 3, NOW)


def test_date_only_uses_local_zone_and_until_goes_to_end_of_day(sao_paulo):
    start, end = resolve_window("2026-10-01", "2026-10-02", None, NOW)
    assert start == datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 3, 2, 59, 59, 999999, tzinfo=UTC)


def test_explicit_zone_is_respected(sao_paulo):
    start, end = resolve_window("2026-10-01T10:00:00+00:00", "2026-10-02T23:00:00Z", None, NOW)
    assert start == datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 2, 23, 0, tzinfo=UTC)


def test_until_without_since_counts_days_back_from_until():
    start, end = resolve_window(None, "2026-10-05T12:00:00Z", 1, NOW)
    assert start == datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def test_invalid_date_has_clear_error():
    with pytest.raises(ValueError, match="--since"):
        resolve_window("ontem", None, None, NOW)


def test_until_before_since_is_error():
    with pytest.raises(ValueError, match="--until"):
        resolve_window("2026-10-05", "2026-10-01", None, NOW)
