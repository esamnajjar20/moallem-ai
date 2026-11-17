"""PostgreSQL-backed worker process entry point."""

import asyncio
import logging
import signal
import sys

from moallem import __version__
from moallem.config import ConfigError, Settings, load_settings
from moallem.logging import configure_logging
from moallem.persistence.database import create_database
from moallem.persistence.idempotency_repository import PostgresIdempotencyRepository
from moallem.persistence.outbox_repository import PostgresOutboxRepository
from moallem.persistence.task_repository import PostgresTaskRepository
from moallem.worker.queue import (
    PostgresTaskWorker,
    RetryPolicy,
    TaskHandlerRegistry,
    WorkerSettings,
)

log = logging.getLogger("moallem.worker")


def _required[T](name: str, value: T | None) -> T:
    if value is None:
        raise ConfigError(f"worker configuration missing: {name}")
    return value


def _worker_settings(settings: Settings) -> WorkerSettings:
    return WorkerSettings(
        poll_seconds=_required("task_queue_poll_seconds", settings.task_queue_poll_seconds),
        batch_size=_required("task_queue_batch_size", settings.task_queue_batch_size),
        lease_seconds=_required("task_queue_lease_seconds", settings.task_queue_lease_seconds),
        lease_renew_seconds=_required(
            "task_queue_lease_renew_seconds", settings.task_queue_lease_renew_seconds
        ),
        shutdown_grace_seconds=_required(
            "task_queue_shutdown_grace_seconds", settings.task_queue_shutdown_grace_seconds
        ),
        idempotency_cleanup_interval_seconds=_required(
            "task_queue_idempotency_cleanup_interval_seconds",
            settings.task_queue_idempotency_cleanup_interval_seconds,
        ),
        idempotency_cleanup_batch_size=_required(
            "task_queue_idempotency_cleanup_batch_size",
            settings.task_queue_idempotency_cleanup_batch_size,
        ),
        retry_policy=RetryPolicy(
            max_attempts=_required("task_queue_max_attempts", settings.task_queue_max_attempts),
            base_delay_seconds=_required(
                "task_queue_retry_base_seconds", settings.task_queue_retry_base_seconds
            ),
            max_delay_seconds=_required(
                "task_queue_retry_max_seconds", settings.task_queue_retry_max_seconds
            ),
        ),
    )


async def run(
    settings: Settings,
    stop: asyncio.Event,
    handlers: TaskHandlerRegistry,
) -> None:
    if settings.database_url is None:
        raise ConfigError("worker configuration missing: database_url")
    worker_settings = _worker_settings(settings)

    engine, sessions = create_database(settings.database_url.get_secret_value())
    worker = PostgresTaskWorker(
        queue=PostgresOutboxRepository(sessions),
        idempotency=PostgresIdempotencyRepository(sessions),
        tasks=PostgresTaskRepository(sessions),
        handlers=handlers,
        settings=worker_settings,
    )
    log.info("worker.started", extra={"config": settings.safe_summary(), "version": __version__})
    try:
        await worker.run(stop)
    finally:
        await asyncio.to_thread(engine.dispose)
        log.info("worker.stopped")


async def _amain(settings: Settings, handlers: TaskHandlerRegistry) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await run(settings, stop, handlers)


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    configure_logging(settings.log_level.value, service="moallem-worker", env=settings.env.value)
    try:
        asyncio.run(_amain(settings, TaskHandlerRegistry()))
    except ConfigError as exc:
        log.error("worker.configuration_failed", extra={"reason": str(exc)})
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
