"""Fail-closed administrative recovery of safe, terminal task failures."""

import re
import uuid

from moallem.domain.authorization import DenyAllPolicy, PermissionPolicy, authorize
from moallem.domain.membership import ActiveContext
from moallem.persistence.task_repository import (
    DeadLetterTask,
    IdempotentTaskResult,
    PostgresTaskRepository,
)

_REASON_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class TaskRecoveryService:
    """Expose recovery only through an explicitly granted authorization policy."""

    def __init__(
        self,
        tasks: PostgresTaskRepository,
        *,
        idempotency_hmac_key: bytes,
        idempotency_retention_seconds: int,
        policy: PermissionPolicy | None = None,
    ) -> None:
        if len(idempotency_hmac_key) < 32:
            raise ValueError("idempotency HMAC key must contain at least 32 bytes")
        if idempotency_retention_seconds < 1:
            raise ValueError("idempotency retention must be positive")
        self._tasks = tasks
        self._idempotency_hmac_key = idempotency_hmac_key
        self._idempotency_retention_seconds = idempotency_retention_seconds
        self._policy = policy if policy is not None else DenyAllPolicy()

    def list_dead_letters(self, ctx: ActiveContext, *, limit: int = 100) -> list[DeadLetterTask]:
        authorize(ctx, "task.dead_letter.list", ctx.tenant_id, self._policy)
        return self._tasks.list_dead_letters(ctx, limit=limit)

    def recover(
        self,
        ctx: ActiveContext,
        task_id: str,
        *,
        idempotency_key: str,
        reason: str,
    ) -> IdempotentTaskResult:
        authorize(ctx, "task.dead_letter.recover", ctx.tenant_id, self._policy)
        if _REASON_CONTROL_CHARS.search(reason):
            raise ValueError("recovery reason contains invalid characters")
        return self._tasks.recover_dead_letter(
            ctx,
            task_id=task_id,
            recovery_task_id=str(uuid.uuid4()),
            idempotency_key=idempotency_key,
            idempotency_hmac_key=self._idempotency_hmac_key,
            idempotency_retention_seconds=self._idempotency_retention_seconds,
            reason=reason,
        )
