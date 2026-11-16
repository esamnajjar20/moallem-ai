"""Worker process skeleton (P1-01).

Only lifecycle: start, heartbeat, graceful drain on SIGTERM/SIGINT.
No job consumption exists yet: queue semantics are DEC-030 and the task/outbox
reliability work is P4. Do not add business logic here before those gates.
"""

import asyncio
import logging
import signal
import sys

from moallem import __version__
from moallem.config import ConfigError, Settings, load_settings
from moallem.logging import configure_logging

log = logging.getLogger("moallem.worker")

HEARTBEAT_SECONDS = 30.0


async def run(settings: Settings, stop: asyncio.Event) -> None:
    log.info("worker.started", extra={"config": settings.safe_summary(), "version": __version__})
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), HEARTBEAT_SECONDS)
        except TimeoutError:
            log.info("worker.heartbeat")
    log.info("worker.draining")
    # P4: stop leasing new work, finish or release in-flight leases here.
    log.info("worker.stopped")


async def _amain(settings: Settings) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await run(settings, stop)


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)  # logging is not configured yet
        return 2
    configure_logging(settings.log_level.value, service="moallem-worker", env=settings.env.value)
    asyncio.run(_amain(settings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
