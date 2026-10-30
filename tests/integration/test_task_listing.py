"""Integration tests for TaskRepository.listTasks (pagination/filtering)
and cancelTask, against real PostgreSQL.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from pulsequeue.domain.errors import InvalidStateTransitionError
from pulsequeue.domain.models import TaskStatus
from pulsequeue.persistence.database import createSessionFactory
from pulsequeue.persistence.repositories import NewTaskInput, TaskRepository


async def _createTask(
    session: AsyncSession, taskType: str = "generateReport", reportName: str = "x"
) -> object:
    payload: dict[str, object] = (
        {"reportName": reportName, "periodDays": 1}
        if taskType == "generateReport"
        else {"recipientName": reportName, "message": "hi"}
    )
    return await TaskRepository(session).createTask(
        NewTaskInput(
            taskType=taskType, payload=payload, maxAttempts=4, correlationId="corr-listing"
        )
    )


async def testListTasksReturnsEverythingOrderedByCreatedAtThenId(dbSession: AsyncSession) -> None:
    repository = TaskRepository(dbSession)
    created = {(await _createTask(dbSession, reportName=str(i))).id for i in range(3)}

    results = await repository.listTasks(limit=50)

    assert {t.id for t in results} == created
    orderingKeys = [(t.createdAt, t.id) for t in results]
    assert orderingKeys == sorted(orderingKeys)


async def testListTasksRespectsLimit(dbSession: AsyncSession) -> None:
    repository = TaskRepository(dbSession)
    for _ in range(5):
        await _createTask(dbSession)

    results = await repository.listTasks(limit=2)
    assert len(results) == 2


async def testListTasksCursorPaginationCoversEveryTaskExactlyOnce(dbSession: AsyncSession) -> None:
    """Pages must cover every task exactly once with no gaps or repeats.

    Doesn't assert listing order matches creation order: when two tasks'
    ``createdAt`` values tie (easily happens creating several in a tight
    loop), the ``id`` tie-breaker makes listing order diverge from
    creation order - that's still a *stable* order (consistent across
    pages), just not necessarily insertion order.
    """
    repository = TaskRepository(dbSession)
    created = [await _createTask(dbSession, reportName=str(i)) for i in range(5)]

    seenIds: list[object] = []
    cursor = None
    for _ in range(10):  # generous upper bound on page count
        page = await repository.listTasks(limit=2, afterCursor=cursor)
        if not page:
            break
        seenIds.extend(t.id for t in page)
        last = page[-1]
        cursor = (last.createdAt, last.id)

    assert len(seenIds) == len(set(seenIds)) == len(created)
    assert set(seenIds) == {t.id for t in created}


async def testListTasksFiltersByStatus(dbSession: AsyncSession) -> None:
    repository = TaskRepository(dbSession)
    firstTask = await _createTask(dbSession, reportName="claimed")
    secondTask = await _createTask(dbSession, reportName="stays-queued")
    claimed = await repository.claimNextTasks(workerId="worker-1", leaseSeconds=30)
    assert [t.id for t in claimed] == [firstTask.id]  # the oldest queued task

    queuedResults = await repository.listTasks(limit=50, statusFilter=TaskStatus.QUEUED.value)
    assert [t.id for t in queuedResults] == [secondTask.id]

    runningResults = await repository.listTasks(limit=50, statusFilter=TaskStatus.RUNNING.value)
    assert [t.id for t in runningResults] == [firstTask.id]


async def testListTasksFiltersByTaskType(dbSession: AsyncSession) -> None:
    repository = TaskRepository(dbSession)
    reportTask = await _createTask(dbSession, taskType="generateReport")
    await _createTask(dbSession, taskType="sendNotification")

    results = await repository.listTasks(limit=50, taskTypeFilter="generateReport")

    assert [t.id for t in results] == [reportTask.id]


async def testCancelTaskCancelsAQueuedTask(dbSession: AsyncSession) -> None:
    repository = TaskRepository(dbSession)
    task = await _createTask(dbSession)

    cancelled = await repository.cancelTask(task.id, cancelledAt=datetime.now(UTC))

    assert cancelled.status == TaskStatus.CANCELLED.value
    assert cancelled.completedAt is not None


async def testCancelTaskRejectsATaskThatIsAlreadyRunning(dbSession: AsyncSession) -> None:
    repository = TaskRepository(dbSession)
    task = await _createTask(dbSession)
    await repository.claimNextTasks(workerId="worker-1", leaseSeconds=30)

    with pytest.raises(InvalidStateTransitionError):
        await repository.cancelTask(task.id, cancelledAt=datetime.now(UTC))


async def testCancelRacingWithClaimNeverCancelsAClaimedTask(
    dbSession: AsyncSession, engine: AsyncEngine
) -> None:
    """A real race between cancelTask and claimNextTasks for the same
    row: exactly one of them must win. Before cancelTask became a
    conditional UPDATE (not a read-then-write), this could corrupt a
    task that a worker had already started running back to `cancelled`.
    """
    task = await _createTask(dbSession)
    sessionFactory = createSessionFactory(engine)

    async def tryCancel() -> bool:
        async with sessionFactory() as session:
            try:
                await TaskRepository(session).cancelTask(task.id, cancelledAt=datetime.now(UTC))
                return True
            except InvalidStateTransitionError:
                return False

    async def tryClaim() -> bool:
        async with sessionFactory() as session:
            claimed = await TaskRepository(session).claimNextTasks(
                workerId="racer", leaseSeconds=30
            )
            return len(claimed) == 1

    cancelled, claimed = await asyncio.gather(tryCancel(), tryClaim())

    # Both attempts ran; whichever committed first determines the final
    # state, but they can never both have "won".
    assert cancelled != claimed or not (cancelled and claimed)

    async with sessionFactory() as session:
        finalTask = await TaskRepository(session).getTaskById(task.id)
    if cancelled:
        assert finalTask.status == TaskStatus.CANCELLED.value
    else:
        assert claimed
        assert finalTask.status == TaskStatus.RUNNING.value


async def testListTasksPaginationIsStableWhileNewTasksAreCreated(
    dbSession: AsyncSession,
) -> None:
    """FR3: new inserts must never shift a page already handed out.

    Doesn't assert every newly-created task shows up in the second page:
    with a UUID (not a monotonic sequence) as the ordering tie-breaker,
    a new row that happens to land in the same microsecond as the
    cursor could sort before it - a known, accepted limitation of
    keyset pagination without a strictly monotonic key, not what this
    test is checking. What must always hold is the actual guarantee:
    page 1's rows never reappear, and a task that already existed
    before page 1 was issued is never lost from a later page.
    """
    repository = TaskRepository(dbSession)
    firstPageTasks = [await _createTask(dbSession, reportName=f"page1-{i}") for i in range(2)]
    thirdTask = await _createTask(dbSession, reportName="page2-original")

    firstPage = await repository.listTasks(limit=2)
    assert {t.id for t in firstPage} == {t.id for t in firstPageTasks}
    cursor = (firstPage[-1].createdAt, firstPage[-1].id)

    # Simulate new submissions arriving after the first page was handed out.
    for i in range(3):
        await _createTask(dbSession, reportName=f"new-{i}")

    secondPage = await repository.listTasks(limit=50, afterCursor=cursor)
    secondPageIds = {t.id for t in secondPage}

    assert thirdTask.id in secondPageIds
    assert secondPageIds.isdisjoint({t.id for t in firstPageTasks})
