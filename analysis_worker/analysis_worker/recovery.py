"""Recovery module for handling stuck PROCESSING dialogues."""

import logging

from .db import get_session
from .repository import requeue_stuck_dialogues
from .settings import get_settings

logger = logging.getLogger(__name__)


async def recover_stuck_dialogues() -> int:
    """
    Find and requeue dialogues stuck in PROCESSING state.

    Dialogues are considered stuck if:
    - analysis_status = 'PROCESSING'
    - analysis_processing_started_at < now() - ANALYSIS_STUCK_TIMEOUT_SEC

    Returns count of requeued dialogues.
    """
    settings = get_settings()

    async with get_session() as session:
        requeued = await requeue_stuck_dialogues(
            session,
            settings.analysis_stuck_timeout_sec,
        )

        if requeued > 0:
            logger.warning(
                f"Recovered {requeued} stuck dialogues",
                extra={"requeued_count": requeued},
            )

        return requeued
