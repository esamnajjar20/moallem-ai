import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from moallem.domain.tasks import TaskStatus
from moallem.persistence.idempotency_repository import PostgresIdempotencyRepository
from moallem.persistence.outbox_repository import OutboxClaim, PostgresOutboxRepository
from moallem.persistence.task_repository import PersistedTask, PostgresTaskRepository
from moallem.worker.queue import (
    PermanentTaskError,
    PostgresTaskWorker,
    RetryPolicy,
    TaskExecutionContext,
    TaskHandler,
    TaskHandlerRegistry,
    WorkerSettings,
)


class SyntheticHandler:
    async def execute(self, task: PersistedTask, context: TaskExecutionContext) -> None:
        pass


def test_retry_policy_uses_exponential_capped_backoff_and_jitter() -> None:
    policy = RetryPolicy(max_attempts=4, base_delay_seconds=2, max_delay_seconds=6)

    assert policy.delay_seconds(1, jitter=lambda: 0.0) == 1
    assert policy.delay_seconds(1, jitter=lambda: 1.0) == 2
    assert policy.delay_seconds(2, jitter=lambda: 0.0) == 2
    assert policy.delay_seconds(3, jitter=lambda: 0.0) == 3
    assert policy.delay_seconds(10, jitter=lambda: 1.0) == 6
    with pytest.raises(ValueError, match="jitter"):
        policy.delay_seconds(1, jitter=lambda: 1.1)


def test_handler_registry_requires_explicit_supported_types() -> None:
    handler = SyntheticHandler()
    registry = TaskHandlerRegistry({"CREATE_QUIZ": handler})
    assert registry.registered_types == frozenset({"CREATE_QUIZ"})
    assert registry.get("CREATE_QUIZ") is handler

    registry.register("ANOTHER_TASK", handler)
    assert registry.get("ANOTHER_TASK") is handler
    with pytest.raises(ValueError, match="already registered"):
        registry.register("CREATE_QUIZ", handler)
    with pytest.raises(ValueError, match="stable uppercase"):
        registry.register("unknown-task", handler)
    with pytest.raises(PermanentTaskError, match="HANDLER_NOT_REGISTERED"):
        registry.get("NO_HANDLER")


def test_handler_registry_rejects_missing_or_synchronous_execute_methods() -> None:
    class MissingExecute:
        pass

    class SynchronousExecute:
        def execute(self, task: PersistedTask, context: TaskExecutionContext) -> None:
            return None

    with pytest.raises(ValueError, match="async callable"):
        TaskHandlerRegistry({"MISSING": cast(TaskHandler, MissingExecute())})
    with pytest.raises(ValueError, match="async callable"):
        TaskHandlerRegistry({"SYNC": cast(TaskHandler, SynchronousExecute())})


def test_worker_graceful_shutdown_cancels_inflight_handler_without_acknowledging() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()
        task_id = str(uuid.uuid4())
        tenant_id = str(uuid.uuid4())
        timestamp = datetime.now(UTC)
        persisted_task = PersistedTask(
            task_id=task_id,
            tenant_id=tenant_id,
            actor_membership_id=str(uuid.uuid4()),
            task_type="CREATE_QUIZ",
            connection_id=str(uuid.uuid4()),
            course_id="course-1",
            prompt="test",
            request_payload={},
            status=TaskStatus.PLANNING,
            cancel_requested=False,
            external_dispatched=False,
            latest_event_sequence=1,
            created_at=timestamp,
            updated_at=timestamp,
        )
        claim = OutboxClaim(
            event_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            task_id=task_id,
            owner="shutdown-worker",
            generation=1,
            attempts=1,
            lease_expires_at=timestamp + timedelta(seconds=30),
            created_at=timestamp,
        )

        class TasksStub:
            def get_for_worker(
                self, requested_tenant_id: str, requested_task_id: str
            ) -> PersistedTask:
                assert requested_tenant_id == tenant_id
                assert requested_task_id == task_id
                return persisted_task

        class QueueStub:
            acknowledged = 0
            failed = 0

            def acknowledge(self, _claim: OutboxClaim) -> bool:
                self.acknowledged += 1
                return True

            def fail(self, *_args, **_kwargs) -> str:
                self.failed += 1
                return "PENDING"

        class HangingHandler:
            async def execute(
                self, _task: PersistedTask, _context: TaskExecutionContext
            ) -> None:
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

        queue = QueueStub()
        worker = PostgresTaskWorker(
            queue=cast(PostgresOutboxRepository, queue),
            idempotency=cast(PostgresIdempotencyRepository, object()),
            tasks=cast(PostgresTaskRepository, TasksStub()),
            handlers=TaskHandlerRegistry({"CREATE_QUIZ": HangingHandler()}),
            worker_id="shutdown-worker",
            settings=WorkerSettings(
                poll_seconds=0.01,
                batch_size=1,
                lease_seconds=30,
                lease_renew_seconds=10,
                shutdown_grace_seconds=0,
                idempotency_cleanup_interval_seconds=60,
                idempotency_cleanup_batch_size=10,
                retry_policy=RetryPolicy(
                    max_attempts=3, base_delay_seconds=1, max_delay_seconds=10
                ),
            ),
        )
        stop = asyncio.Event()
        batch = asyncio.create_task(worker._process_batch([claim], stop))
        await asyncio.wait_for(started.wait(), timeout=2)
        stop.set()
        await asyncio.wait_for(batch, timeout=2)

        assert cancelled.is_set()
        assert queue.acknowledged == 0
        assert queue.failed == 0

    asyncio.run(scenario())
