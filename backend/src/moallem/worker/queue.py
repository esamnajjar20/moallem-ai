"""At-least-once PostgreSQL task worker with bounded retries and graceful shutdown."""

import asyncio
import logging
import random
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from moallem.domain.tasks import TERMINAL, TaskStatus
from moallem.persistence.idempotency_repository import PostgresIdempotencyRepository
from moallem.persistence.outbox_repository import (
    LeaseLost,
    OutboxClaim,
    PostgresOutboxRepository,
)
from moallem.persistence.task_repository import PersistedTask, PostgresTaskRepository

log = logging.getLogger("moallem.worker.queue")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_YIELDED = frozenset(
    {
        TaskStatus.AWAITING_APPROVAL,
        TaskStatus.NEEDS_INPUT,
        TaskStatus.NEEDS_REVISION,
    }
)


class PermanentTaskError(Exception):
    def __init__(self, error_code: str) -> None:
        if not _ERROR_CODE.fullmatch(error_code):
            raise ValueError("error_code must be a non-sensitive stable code")
        self.error_code = error_code


class RetryableTaskError(Exception):
    def __init__(self, error_code: str) -> None:
        if not _ERROR_CODE.fullmatch(error_code):
            raise ValueError("error_code must be a non-sensitive stable code")
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    base_delay_seconds: int
    max_delay_seconds: int

    def __post_init__(self) -> None:
        if (
            self.max_attempts < 1
            or self.base_delay_seconds < 1
            or self.max_delay_seconds < self.base_delay_seconds
        ):
            raise ValueError("invalid retry policy")

    def delay_seconds(
        self,
        attempt: int,
        *,
        jitter: Callable[[], float] = random.random,
    ) -> float:
        if attempt < 1:
            raise ValueError("attempt must be positive")
        random_fraction = jitter()
        if not 0 <= random_fraction <= 1:
            raise ValueError("jitter must be in [0, 1]")
        exponent = min(attempt - 1, 62)
        ceiling = min(self.max_delay_seconds, self.base_delay_seconds * (2**exponent))
        return float(ceiling * (0.5 + 0.5 * random_fraction))


class TaskExecutionContext:
    def __init__(self, claim: OutboxClaim, tasks: PostgresTaskRepository) -> None:
        self._claim = claim
        self._tasks = tasks

    async def transition(
        self,
        status: TaskStatus,
        *,
        event_type: str = "STATUS_CHANGED",
        message_code: str | None = None,
    ) -> PersistedTask:
        return await asyncio.to_thread(
            self._tasks.transition_for_worker,
            self._claim,
            status,
            event_type=event_type,
            message_code=message_code,
        )


class TaskHandler(Protocol):
    async def execute(self, task: PersistedTask, context: TaskExecutionContext) -> None: ...


class TaskHandlerRegistry:
    def __init__(self, handlers: Mapping[str, TaskHandler] | None = None) -> None:
        self._handlers: dict[str, TaskHandler] = {}
        for task_type, handler in (handlers or {}).items():
            self.register(task_type, handler)

    def register(self, task_type: str, handler: TaskHandler) -> None:
        if not _ERROR_CODE.fullmatch(task_type):
            raise ValueError("task_type must be a stable uppercase identifier")
        if task_type in self._handlers:
            raise ValueError(f"handler already registered for {task_type}")
        self._handlers[task_type] = handler

    def get(self, task_type: str) -> TaskHandler:
        try:
            return self._handlers[task_type]
        except KeyError:
            raise PermanentTaskError("HANDLER_NOT_REGISTERED") from None

    @property
    def registered_types(self) -> frozenset[str]:
        return frozenset(self._handlers)


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    poll_seconds: float
    batch_size: int
    lease_seconds: int
    lease_renew_seconds: int
    shutdown_grace_seconds: int
    idempotency_cleanup_interval_seconds: int
    idempotency_cleanup_batch_size: int
    retry_policy: RetryPolicy

    def __post_init__(self) -> None:
        if (
            self.poll_seconds <= 0
            or self.batch_size < 1
            or self.lease_seconds < 1
            or not 0 < self.lease_renew_seconds < self.lease_seconds
            or self.shutdown_grace_seconds < 0
            or self.idempotency_cleanup_interval_seconds < 1
            or self.idempotency_cleanup_batch_size < 1
        ):
            raise ValueError("invalid worker settings")


class PostgresTaskWorker:
    def __init__(
        self,
        *,
        queue: PostgresOutboxRepository,
        idempotency: PostgresIdempotencyRepository,
        tasks: PostgresTaskRepository,
        handlers: TaskHandlerRegistry,
        worker_id: str | None = None,
        settings: WorkerSettings,
    ) -> None:
        self._queue = queue
        self._idempotency = idempotency
        self._tasks = tasks
        self._handlers = handlers
        self._worker_id = worker_id or f"worker-{uuid.uuid4()}"
        self._settings = settings

    async def run(self, stop: asyncio.Event) -> None:
        registered_types = self._handlers.registered_types
        log.info(
            "worker.queue_started",
            extra={
                "worker_id": self._worker_id,
                "registered_task_types": sorted(registered_types),
            },
        )
        if not registered_types:
            log.warning("worker.no_handlers_registered", extra={"worker_id": self._worker_id})
        loop = asyncio.get_running_loop()
        next_cleanup = loop.time()
        last_unsupported_types: list[str] = []
        while not stop.is_set():
            if loop.time() >= next_cleanup:
                deleted = await asyncio.to_thread(
                    self._idempotency.delete_expired_batch,
                    datetime.now(UTC),
                    limit=self._settings.idempotency_cleanup_batch_size,
                )
                if deleted:
                    log.info(
                        "worker.idempotency_cleanup",
                        extra={
                            "worker_id": self._worker_id,
                            "deleted_records": deleted,
                        },
                    )
                next_cleanup = loop.time() + self._settings.idempotency_cleanup_interval_seconds
            unsupported_types = await asyncio.to_thread(
                self._queue.unhandled_task_types, registered_types
            )
            if unsupported_types and unsupported_types != last_unsupported_types:
                log.warning(
                    "worker.unsupported_task_types_pending",
                    extra={
                        "worker_id": self._worker_id,
                        "task_types": unsupported_types,
                    },
                )
            last_unsupported_types = unsupported_types
            claims = await asyncio.to_thread(
                self._queue.claim_batch,
                owner=self._worker_id,
                limit=self._settings.batch_size,
                lease=timedelta(seconds=self._settings.lease_seconds),
                supported_task_types=registered_types,
            )
            if not claims:
                try:
                    await asyncio.wait_for(stop.wait(), self._settings.poll_seconds)
                except TimeoutError:
                    continue
                break
            await self._process_batch(claims, stop)
        log.info("worker.queue_stopped", extra={"worker_id": self._worker_id})

    async def _process_batch(self, claims: list[OutboxClaim], stop: asyncio.Event) -> None:
        active = {asyncio.create_task(self._process_claim(claim)) for claim in claims}
        try:
            while active:
                done, _ = await asyncio.wait(
                    active,
                    timeout=self._settings.poll_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stop.is_set():
                    finished, pending = await asyncio.wait(
                        active, timeout=self._settings.shutdown_grace_seconds
                    )
                    for task in finished:
                        task.result()
                    for task in pending:
                        task.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                    return
                for task in done:
                    task.result()
                    active.remove(task)
        finally:
            for task in active:
                if not task.done():
                    task.cancel()
            if active:
                await asyncio.gather(*active, return_exceptions=True)

    async def _process_claim(self, claim: OutboxClaim) -> None:
        log.info(
            "worker.claimed",
            extra={
                "worker_id": self._worker_id,
                "task_id": claim.task_id,
                "event_id": claim.event_id,
                "attempt": claim.attempts,
                "queue_wait_seconds": max(
                    0.0, (datetime.now(UTC) - claim.created_at).total_seconds()
                ),
            },
        )
        if claim.attempts > self._settings.retry_policy.max_attempts:
            await self._record_failure(claim, "ATTEMPTS_EXHAUSTED", retryable=False)
            return

        try:
            task = await asyncio.to_thread(
                self._tasks.get_for_worker, claim.tenant_id, claim.task_id
            )
        except Exception as exc:
            log.error(
                "worker.task_lookup_failed",
                extra={
                    "worker_id": self._worker_id,
                    "task_id": claim.task_id,
                    "error_type": type(exc).__name__,
                },
            )
            await self._record_failure(claim, "TASK_LOOKUP_FAILED", retryable=True)
            return

        if task.status in TERMINAL or task.status in _YIELDED:
            await self._acknowledge(claim)
            return

        try:
            handler = self._handlers.get(task.task_type)
            context = TaskExecutionContext(claim, self._tasks)
            if task.status is TaskStatus.RECEIVED:
                task = await context.transition(TaskStatus.PLANNING)
            await self._execute_with_lease(claim, task, handler, context)
            current = await asyncio.to_thread(
                self._tasks.get_for_worker, claim.tenant_id, claim.task_id
            )
            if current.status not in TERMINAL and current.status not in _YIELDED:
                raise PermanentTaskError("HANDLER_DID_NOT_YIELD")
        except asyncio.CancelledError:
            raise
        except LeaseLost:
            log.warning(
                "worker.lease_lost",
                extra={"worker_id": self._worker_id, "task_id": claim.task_id},
            )
            return
        except PermanentTaskError as exc:
            await self._record_failure(claim, exc.error_code, retryable=False)
            return
        except RetryableTaskError as exc:
            await self._record_failure(claim, exc.error_code, retryable=True)
            return
        except Exception as exc:
            log.error(
                "worker.handler_failed",
                extra={
                    "worker_id": self._worker_id,
                    "task_id": claim.task_id,
                    "error_type": type(exc).__name__,
                },
            )
            await self._record_failure(claim, "HANDLER_UNEXPECTED", retryable=True)
            return
        await self._acknowledge(claim)

    async def _execute_with_lease(
        self,
        claim: OutboxClaim,
        task: PersistedTask,
        handler: TaskHandler,
        context: TaskExecutionContext,
    ) -> None:
        running = asyncio.create_task(handler.execute(task, context))
        try:
            while not running.done():
                done, _ = await asyncio.wait({running}, timeout=self._settings.lease_renew_seconds)
                if done:
                    break
                renewed = await asyncio.to_thread(
                    self._queue.renew,
                    claim,
                    lease=timedelta(seconds=self._settings.lease_seconds),
                )
                if not renewed:
                    running.cancel()
                    await asyncio.gather(running, return_exceptions=True)
                    raise LeaseLost("worker claim is no longer current")
            await running
        finally:
            if not running.done():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)

    async def _acknowledge(self, claim: OutboxClaim) -> None:
        acknowledged = await asyncio.to_thread(self._queue.acknowledge, claim)
        if not acknowledged:
            log.warning(
                "worker.acknowledgement_fenced",
                extra={"worker_id": self._worker_id, "task_id": claim.task_id},
            )
        else:
            log.info(
                "worker.acknowledged",
                extra={"worker_id": self._worker_id, "task_id": claim.task_id},
            )

    async def _record_failure(
        self, claim: OutboxClaim, error_code: str, *, retryable: bool
    ) -> None:
        delay = self._settings.retry_policy.delay_seconds(claim.attempts)
        disposition = await asyncio.to_thread(
            self._queue.fail,
            claim,
            error_code=error_code,
            retryable=retryable,
            max_attempts=self._settings.retry_policy.max_attempts,
            retry_at=datetime.now(UTC) + timedelta(seconds=delay),
        )
        log.warning(
            "worker.failure_recorded",
            extra={
                "worker_id": self._worker_id,
                "task_id": claim.task_id,
                "error_code": error_code,
                "disposition": disposition or "LEASE_LOST",
                "attempt": claim.attempts,
            },
        )
