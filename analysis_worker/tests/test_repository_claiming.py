"""Tests for repository claiming logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone


class TestFetchPendingDialogues:
    """Tests for fetch_pending_dialogues function."""

    @pytest.mark.asyncio
    async def test_fetch_returns_correct_fields(self):
        """Fetched dialogues should have all required fields."""
        from analysis_worker.repository import fetch_pending_dialogues

        mock_session = AsyncMock()
        mock_result = MagicMock()

        dialogue_id = uuid4()
        device_id = uuid4()
        point_id = uuid4()
        register_id = uuid4()
        now = datetime.now(timezone.utc)

        mock_row = MagicMock()
        mock_row.dialogue_id = dialogue_id
        mock_row.device_id = device_id
        mock_row.point_id = point_id
        mock_row.register_id = register_id
        mock_row.start_ts = now
        mock_row.end_ts = now
        mock_row.source = "vad"
        mock_row.transcript_text = "Test transcript"
        mock_row.language = "ru"

        mock_result.fetchall.return_value = [mock_row]
        mock_session.execute.return_value = mock_result

        dialogues = await fetch_pending_dialogues(mock_session, batch_size=10)

        assert len(dialogues) == 1
        d = dialogues[0]
        assert d["dialogue_id"] == dialogue_id
        assert d["device_id"] == device_id
        assert d["point_id"] == point_id
        assert d["register_id"] == register_id
        assert d["transcript_text"] == "Test transcript"
        assert d["language"] == "ru"

    @pytest.mark.asyncio
    async def test_fetch_empty_result(self):
        """Empty result should return empty list."""
        from analysis_worker.repository import fetch_pending_dialogues

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        dialogues = await fetch_pending_dialogues(mock_session, batch_size=10)
        assert dialogues == []

    @pytest.mark.asyncio
    async def test_fetch_uses_skip_locked(self):
        """Query should use FOR UPDATE SKIP LOCKED."""
        from analysis_worker.repository import fetch_pending_dialogues

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        await fetch_pending_dialogues(mock_session, batch_size=5)

        # Check that execute was called
        mock_session.execute.assert_called_once()

        # Get the query text
        call_args = mock_session.execute.call_args
        query = call_args[0][0]
        query_text = str(query.text).upper()

        assert "FOR UPDATE" in query_text
        assert "SKIP LOCKED" in query_text


class TestUpdateDialogueAnalysisStatus:
    """Tests for update_dialogue_analysis_status function."""

    @pytest.mark.asyncio
    async def test_update_to_processing(self):
        """Update to PROCESSING should set timestamps."""
        from analysis_worker.repository import update_dialogue_analysis_status

        mock_session = AsyncMock()
        dialogue_id = uuid4()

        await update_dialogue_analysis_status(
            mock_session, dialogue_id, "PROCESSING"
        )

        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args
        params = call_args[0][1]

        assert params["dialogue_id"] == dialogue_id
        assert params["status"] == "PROCESSING"
        assert "now" in params

    @pytest.mark.asyncio
    async def test_update_to_done(self):
        """Update to DONE should set model and prompt_version."""
        from analysis_worker.repository import update_dialogue_analysis_status

        mock_session = AsyncMock()
        dialogue_id = uuid4()

        await update_dialogue_analysis_status(
            mock_session,
            dialogue_id,
            "DONE",
            model="gpt-4o-mini",
            prompt_version="v1",
        )

        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args
        params = call_args[0][1]

        assert params["dialogue_id"] == dialogue_id
        assert params["status"] == "DONE"
        assert params["model"] == "gpt-4o-mini"
        assert params["prompt_version"] == "v1"

    @pytest.mark.asyncio
    async def test_update_to_error(self):
        """Update to ERROR should set error_message."""
        from analysis_worker.repository import update_dialogue_analysis_status

        mock_session = AsyncMock()
        dialogue_id = uuid4()

        await update_dialogue_analysis_status(
            mock_session,
            dialogue_id,
            "ERROR",
            error_message="Test error",
        )

        mock_session.execute.assert_called_once()
        call_args = mock_session.execute.call_args
        params = call_args[0][1]

        assert params["dialogue_id"] == dialogue_id
        assert params["status"] == "ERROR"
        assert params["error_message"] == "Test error"


class TestUpsertDialogueAnalysis:
    """Tests for upsert_dialogue_analysis function."""

    @pytest.mark.asyncio
    async def test_upsert_with_all_fields(self):
        """Upsert should save all analysis fields."""
        from analysis_worker.repository import upsert_dialogue_analysis

        mock_session = AsyncMock()
        mock_result = MagicMock()
        analysis_id = uuid4()
        mock_result.scalar_one.return_value = analysis_id
        mock_session.execute.return_value = mock_result

        dialogue_id = uuid4()

        result = await upsert_dialogue_analysis(
            mock_session,
            dialogue_id=dialogue_id,
            attempted="yes",
            quality_score=2,
            categories=["coffee_size", "dessert"],
            closing_question=True,
            customer_reaction="accepted",
            evidence_quotes=["quote1", "quote2"],
            summary="Test summary",
            confidence=0.85,
        )

        assert result == analysis_id
        mock_session.execute.assert_called_once()


class TestRequeueStuckDialogues:
    """Tests for requeue_stuck_dialogues function."""

    @pytest.mark.asyncio
    async def test_requeue_returns_count(self):
        """Requeue should return count of requeued dialogues."""
        from analysis_worker.repository import requeue_stuck_dialogues

        mock_session = AsyncMock()
        mock_result = MagicMock()

        # Simulate 3 stuck dialogues
        mock_rows = [
            MagicMock(dialogue_id=uuid4()),
            MagicMock(dialogue_id=uuid4()),
            MagicMock(dialogue_id=uuid4()),
        ]
        mock_result.fetchall.return_value = mock_rows
        mock_session.execute.return_value = mock_result

        count = await requeue_stuck_dialogues(mock_session, stuck_timeout_sec=600.0)

        assert count == 3

    @pytest.mark.asyncio
    async def test_requeue_no_stuck(self):
        """Requeue with no stuck dialogues should return 0."""
        from analysis_worker.repository import requeue_stuck_dialogues

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        count = await requeue_stuck_dialogues(mock_session, stuck_timeout_sec=600.0)

        assert count == 0
