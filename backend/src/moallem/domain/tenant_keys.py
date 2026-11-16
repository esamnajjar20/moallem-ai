"""Tenant-namespaced keys for cache, object storage and queue messages (P2-03, DEC-032).

Cross-tenant isolation must hold beyond the API/DB: a cache key, a storage path or a queue
payload built without the tenant is the classic leak. These helpers make the tenant part of the
key by construction, take it ONLY from an `ActiveContext`, and verify ownership on the way out.
Backends (Redis/S3/broker) are not chosen yet (ADR-020, DEC-030); this is their contract.
"""

import re
from dataclasses import dataclass

from moallem.domain.authorization import require_tenant
from moallem.domain.membership import ActiveContext

_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.=-]{0,127}")
_RESERVED = frozenset({".", ".."})


def _seg(value: str, what: str) -> str:
    # No separators, no traversal, no empty parts: a segment can never escape its namespace.
    if value in _RESERVED or ".." in value or not _SEGMENT.fullmatch(value):
        raise ValueError(f"invalid {what} segment")
    return value


def cache_key(ctx: ActiveContext, namespace: str, *parts: str) -> str:
    if not parts:
        raise ValueError("a cache key needs at least one part")
    head = ["t", _seg(ctx.tenant_id, "tenant"), _seg(namespace, "namespace")]
    return ":".join([*head, *(_seg(p, "key") for p in parts)])


def storage_path(ctx: ActiveContext, area: str, *parts: str) -> str:
    if not parts:
        raise ValueError("a storage path needs at least one part")
    head = ["tenants", _seg(ctx.tenant_id, "tenant"), _seg(area, "area")]
    return "/".join([*head, *(_seg(p, "path") for p in parts)])


def tenant_of_cache_key(key: str) -> str | None:
    p = key.split(":")
    return p[1] if len(p) >= 4 and p[0] == "t" else None


def tenant_of_storage_path(path: str) -> str | None:
    p = path.split("/")
    return p[1] if len(p) >= 4 and p[0] == "tenants" else None


def require_cache_key(ctx: ActiveContext, key: str) -> str:
    require_tenant(ctx, tenant_of_cache_key(key))
    return key


def require_storage_path(ctx: ActiveContext, path: str) -> str:
    require_tenant(ctx, tenant_of_storage_path(path))
    return path


@dataclass(frozen=True, slots=True)
class QueueEnvelope:
    """Every queue/outbox message carries its tenant; a worker re-derives context from it."""

    tenant_id: str
    membership_id: str
    task_id: str
    payload_ref: str


def make_envelope(ctx: ActiveContext, task_id: str, payload_ref: str) -> QueueEnvelope:
    return QueueEnvelope(
        tenant_id=_seg(ctx.tenant_id, "tenant"),
        membership_id=ctx.membership_id,
        task_id=_seg(task_id, "task"),
        payload_ref=payload_ref,
    )


def require_envelope_for(ctx: ActiveContext, env: QueueEnvelope) -> QueueEnvelope:
    """Worker side: a message from another tenant is rejected as not found."""
    require_tenant(ctx, env.tenant_id)
    return env
