"""Tests for time-based scheduling logic."""

from datetime import datetime

import pytest

from recorder_agent.scheduler import is_in_schedule, parse_time


class TestParseTime:
    def test_valid(self) -> None:
        t = parse_time("08:00")
        assert t.hour == 8
        assert t.minute == 0

    def test_valid_pm(self) -> None:
        t = parse_time("22:30")
        assert t.hour == 22
        assert t.minute == 30

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError):
            parse_time("8am")

    def test_invalid_empty(self) -> None:
        with pytest.raises(ValueError):
            parse_time("")


class TestIsInSchedule:
    def test_inside_window(self) -> None:
        now = datetime(2024, 1, 15, 12, 0, 0)
        assert is_in_schedule("08:00", "22:00", now=now) is True

    def test_at_start(self) -> None:
        now = datetime(2024, 1, 15, 8, 0, 0)
        assert is_in_schedule("08:00", "22:00", now=now) is True

    def test_before_start(self) -> None:
        now = datetime(2024, 1, 15, 7, 59, 59)
        assert is_in_schedule("08:00", "22:00", now=now) is False

    def test_at_end(self) -> None:
        # end is exclusive
        now = datetime(2024, 1, 15, 22, 0, 0)
        assert is_in_schedule("08:00", "22:00", now=now) is False

    def test_after_end(self) -> None:
        now = datetime(2024, 1, 15, 23, 0, 0)
        assert is_in_schedule("08:00", "22:00", now=now) is False

    def test_midnight_span_inside(self) -> None:
        """Overnight schedule: 22:00 -> 06:00."""
        now = datetime(2024, 1, 15, 23, 30, 0)
        assert is_in_schedule("22:00", "06:00", now=now) is True

    def test_midnight_span_inside_early(self) -> None:
        now = datetime(2024, 1, 15, 2, 0, 0)
        assert is_in_schedule("22:00", "06:00", now=now) is True

    def test_midnight_span_outside(self) -> None:
        now = datetime(2024, 1, 15, 12, 0, 0)
        assert is_in_schedule("22:00", "06:00", now=now) is False

    def test_full_day(self) -> None:
        now = datetime(2024, 1, 15, 15, 0, 0)
        assert is_in_schedule("00:00", "23:59", now=now) is True
