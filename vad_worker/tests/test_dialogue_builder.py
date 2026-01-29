"""Unit tests for dialogue builder."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from vad_worker.dialogue_builder import (
    SegmentInfo,
    build_dialogues_from_segments,
    segments_to_absolute,
)


class TestSegmentsToAbsolute:
    """Tests for segments_to_absolute function."""

    def test_empty_segments(self):
        """Empty segments should return empty list."""
        result = segments_to_absolute(
            uuid4(),
            datetime(2026, 1, 29, 10, 0, 0, tzinfo=timezone.utc),
            [],
        )
        assert result == []

    def test_single_segment(self):
        """Single segment should be converted correctly."""
        chunk_id = uuid4()
        start_ts = datetime(2026, 1, 29, 10, 0, 0, tzinfo=timezone.utc)

        result = segments_to_absolute(chunk_id, start_ts, [(1000, 3000)])

        assert len(result) == 1
        assert result[0].chunk_id == chunk_id
        assert result[0].start_ms == 1000
        assert result[0].end_ms == 3000
        assert result[0].abs_start == start_ts + timedelta(milliseconds=1000)
        assert result[0].abs_end == start_ts + timedelta(milliseconds=3000)

    def test_multiple_segments(self):
        """Multiple segments should all be converted."""
        chunk_id = uuid4()
        start_ts = datetime(2026, 1, 29, 10, 0, 0, tzinfo=timezone.utc)
        segments = [(0, 1000), (2000, 3000), (5000, 8000)]

        result = segments_to_absolute(chunk_id, start_ts, segments)

        assert len(result) == 3
        assert result[0].abs_start == start_ts
        assert result[1].abs_start == start_ts + timedelta(seconds=2)
        assert result[2].abs_end == start_ts + timedelta(seconds=8)


class TestBuildDialoguesFromSegments:
    """Tests for build_dialogues_from_segments function."""

    def _make_segments(
        self,
        times_ms: list[tuple[int, int]],
        base_time: datetime | None = None,
    ) -> list[SegmentInfo]:
        """Helper to create SegmentInfo list from ms timestamps."""
        if base_time is None:
            base_time = datetime(2026, 1, 29, 10, 0, 0, tzinfo=timezone.utc)

        chunk_id = uuid4()
        return [
            SegmentInfo(
                chunk_id=chunk_id,
                start_ms=start,
                end_ms=end,
                abs_start=base_time + timedelta(milliseconds=start),
                abs_end=base_time + timedelta(milliseconds=end),
            )
            for start, end in times_ms
        ]

    def test_empty_segments(self):
        """Empty segments should return empty dialogues."""
        result = build_dialogues_from_segments([], silence_gap_sec=12, max_dialogue_sec=120)
        assert result == []

    def test_single_segment_single_dialogue(self):
        """Single segment should create single dialogue."""
        segments = self._make_segments([(0, 5000)])

        result = build_dialogues_from_segments(
            segments, silence_gap_sec=12, max_dialogue_sec=120
        )

        assert len(result) == 1
        assert len(result[0]) == 1
        assert result[0][0].start_ms == 0
        assert result[0][0].end_ms == 5000

    def test_continuous_speech_single_dialogue(self):
        """Segments with small gaps should form single dialogue."""
        # Gaps of 500ms, 1s, 2s - all under 12s threshold
        segments = self._make_segments([
            (0, 2000),
            (2500, 5000),
            (6000, 8000),
            (10000, 12000),
        ])

        result = build_dialogues_from_segments(
            segments, silence_gap_sec=12, max_dialogue_sec=120
        )

        assert len(result) == 1
        assert len(result[0]) == 4

    def test_silence_gap_splits_dialogue(self):
        """Gap larger than threshold should split into multiple dialogues."""
        # 15s gap between segment 2 and 3
        segments = self._make_segments([
            (0, 2000),
            (2500, 5000),
            (20000, 22000),  # 15s gap
            (22500, 25000),
        ])

        result = build_dialogues_from_segments(
            segments, silence_gap_sec=12, max_dialogue_sec=120
        )

        assert len(result) == 2
        assert len(result[0]) == 2  # First two segments
        assert len(result[1]) == 2  # Last two segments

    def test_max_duration_splits_dialogue(self):
        """Dialogue exceeding max duration should be split."""
        # Long continuous speech - 150 seconds total
        segments = self._make_segments([
            (0, 50000),       # 0-50s
            (51000, 100000),  # 51-100s
            (101000, 150000), # 101-150s - this pushes past 120s
        ])

        result = build_dialogues_from_segments(
            segments, silence_gap_sec=12, max_dialogue_sec=120
        )

        assert len(result) == 2
        # First dialogue: 0-100s (under 120s)
        assert len(result[0]) == 2
        # Second dialogue: 101-150s (starts fresh)
        assert len(result[1]) == 1

    def test_multiple_splits(self):
        """Test both silence and duration splits."""
        segments = self._make_segments([
            (0, 30000),        # 0-30s
            (31000, 60000),    # 31-60s
            (61000, 90000),    # 61-90s
            (91000, 130000),   # 91-130s - exceeds 120s, split
            (145000, 160000),  # 145-160s - 15s gap, new dialogue
        ])

        result = build_dialogues_from_segments(
            segments, silence_gap_sec=12, max_dialogue_sec=120
        )

        assert len(result) == 3

    def test_exact_threshold_no_split(self):
        """Gap exactly at threshold should not split."""
        segments = self._make_segments([
            (0, 5000),
            (17000, 20000),  # Exactly 12s gap
        ])

        result = build_dialogues_from_segments(
            segments, silence_gap_sec=12, max_dialogue_sec=120
        )

        # 12s gap is <= 12s, so should be single dialogue
        assert len(result) == 1
        assert len(result[0]) == 2

    def test_just_over_threshold_splits(self):
        """Gap just over threshold should split."""
        segments = self._make_segments([
            (0, 5000),
            (17001, 20000),  # 12.001s gap
        ])

        result = build_dialogues_from_segments(
            segments, silence_gap_sec=12, max_dialogue_sec=120
        )

        assert len(result) == 2

    def test_custom_silence_gap(self):
        """Test with custom silence gap."""
        segments = self._make_segments([
            (0, 2000),
            (7000, 9000),  # 5s gap - over 3s threshold
        ])

        result = build_dialogues_from_segments(
            segments, silence_gap_sec=3, max_dialogue_sec=120
        )

        assert len(result) == 2

    def test_custom_max_duration(self):
        """Test with custom max duration."""
        segments = self._make_segments([
            (0, 20000),
            (21000, 40000),
            (41000, 70000),  # Total 70s - exceeds 60s
        ])

        result = build_dialogues_from_segments(
            segments, silence_gap_sec=12, max_dialogue_sec=60
        )

        assert len(result) == 2


class TestDialogueBuilderEdgeCases:
    """Edge case tests for dialogue builder."""

    def _make_segments(
        self,
        times_ms: list[tuple[int, int]],
    ) -> list[SegmentInfo]:
        base_time = datetime(2026, 1, 29, 10, 0, 0, tzinfo=timezone.utc)
        chunk_id = uuid4()
        return [
            SegmentInfo(
                chunk_id=chunk_id,
                start_ms=start,
                end_ms=end,
                abs_start=base_time + timedelta(milliseconds=start),
                abs_end=base_time + timedelta(milliseconds=end),
            )
            for start, end in times_ms
        ]

    def test_very_short_segments(self):
        """Very short segments should still be processed."""
        segments = self._make_segments([
            (0, 100),
            (200, 300),
            (400, 500),
        ])

        result = build_dialogues_from_segments(
            segments, silence_gap_sec=12, max_dialogue_sec=120
        )

        assert len(result) == 1
        assert len(result[0]) == 3

    def test_single_long_segment(self):
        """Single segment longer than max_dialogue_sec."""
        segments = self._make_segments([(0, 150000)])  # 150s segment

        result = build_dialogues_from_segments(
            segments, silence_gap_sec=12, max_dialogue_sec=120
        )

        # Single segment can't be split, so it becomes one dialogue
        assert len(result) == 1
        assert len(result[0]) == 1

    def test_alternating_speech_silence(self):
        """Alternating speech and silence pattern."""
        # Speech every 15s (gap > 12s threshold)
        segments = self._make_segments([
            (0, 2000),
            (15000, 17000),
            (30000, 32000),
            (45000, 47000),
        ])

        result = build_dialogues_from_segments(
            segments, silence_gap_sec=12, max_dialogue_sec=120
        )

        # Each segment is its own dialogue due to 13s gaps
        assert len(result) == 4

    def test_realistic_conversation(self):
        """Test realistic conversation pattern."""
        # Typical call center conversation:
        # - Customer speaks (0-5s)
        # - Agent responds (6-15s)
        # - Customer speaks (16-20s)
        # - Long pause while looking up info (35s gap)
        # - Agent responds (55-70s)
        segments = self._make_segments([
            (0, 5000),
            (6000, 15000),
            (16000, 20000),
            (55000, 70000),
        ])

        result = build_dialogues_from_segments(
            segments, silence_gap_sec=12, max_dialogue_sec=120
        )

        # Should be split after 20s mark due to 35s gap
        assert len(result) == 2
        assert len(result[0]) == 3  # First three segments
        assert len(result[1]) == 1  # Last segment
