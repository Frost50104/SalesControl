"""Time-based recording schedule."""

from __future__ import annotations

from datetime import datetime, time


def parse_time(s: str) -> time:
    """Parse 'HH:MM' string into datetime.time."""
    parts = s.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format (expected HH:MM): {s!r}")
    return time(int(parts[0]), int(parts[1]))


def is_in_schedule(start: str, end: str, now: datetime | None = None) -> bool:
    """Check if the current local time is within [start, end) window.

    Handles overnight spans (e.g. start=22:00, end=06:00).
    """
    if now is None:
        now = datetime.now()
    t_start = parse_time(start)
    t_end = parse_time(end)
    current = now.time()

    if t_start <= t_end:
        # normal daytime span
        return t_start <= current < t_end
    else:
        # overnight span
        return current >= t_start or current < t_end
