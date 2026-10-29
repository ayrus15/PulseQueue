"""Finds tasks whose worker lease expired and returns them to ``queued``.

Runs from the worker's own poll loop (see workers/worker.py), not as a
separate scheduled job - one code path for "new work" and "abandoned
work," per ADR 0002/0003.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from pulsequeue.persistence.repositories import TaskAttemptRepository, TaskRepository

logger = logging.getLogger(__name__)


async def recoverExpiredLeases(session: AsyncSession, now: datetime) -> list[uuid.UUID]:
    """Recover every task whose lease has expired, as of ``now``.

    Returns the recovered task IDs (empty if none were found).
    """
    taskRepository = TaskRepository(session)
    attemptRepository = TaskAttemptRepository(session)

    expiredTasks = await taskRepository.findExpiredLeaseTasks(now)
    recoveredIds: list[uuid.UUID] = []
    for task in expiredTasks:
        await attemptRepository.closeOrphanedAttempt(task.id, task.attemptCount, now)
        staleLeaseOwner = task.leaseOwner
        await taskRepository.applyLeaseExpired(task, now)
        logger.warning(
            "Recovered task with expired lease",
            extra={"task_id": str(task.id), "stale_lease_owner": staleLeaseOwner},
        )
        recoveredIds.append(task.id)
    return recoveredIds
