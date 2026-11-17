import pytest

from moallem.persistence.task_repository import PersistedTask
from moallem.worker.queue import (
    PermanentTaskError,
    RetryPolicy,
    TaskExecutionContext,
    TaskHandlerRegistry,
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
