"""Opaque Moodle credential reference (P2-02; DEC-029/DEC-037). No raw token outside the vault.

Only a reference ever reaches the DB, logs, API responses or the client. The vault itself
(Secret Manager choice) is OPEN: `SecretVault` is the seam; InMemoryVault is a test double.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol

from moallem.domain.authorization import require_tenant
from moallem.domain.errors import ResourceNotFound
from moallem.domain.membership import ActiveContext


@dataclass(frozen=True, slots=True)
class SecretRef:
    tenant_id: str
    ref_id: str

    def __repr__(self) -> str:
        return "SecretRef(<redacted>)"

    __str__ = __repr__


class SecretVault(Protocol):
    def put(self, ctx: ActiveContext, raw: str) -> SecretRef: ...

    def reveal(self, ctx: ActiveContext, ref: SecretRef) -> str: ...

    def delete(self, ctx: ActiveContext, ref: SecretRef) -> None: ...


class InMemoryVault:
    """Test double only. `reveal` is for the integration layer, never for API handlers."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, str]] = {}

    def put(self, ctx: ActiveContext, raw: str) -> SecretRef:
        ref = SecretRef(ctx.tenant_id, uuid.uuid4().hex)
        self._data[ref.ref_id] = (ctx.tenant_id, raw)
        return ref

    def reveal(self, ctx: ActiveContext, ref: SecretRef) -> str:
        require_tenant(ctx, ref.tenant_id)
        entry = self._data.get(ref.ref_id)
        if entry is None or entry[0] != ctx.tenant_id:
            raise ResourceNotFound("resource not found")
        return entry[1]

    def delete(self, ctx: ActiveContext, ref: SecretRef) -> None:
        self.reveal(ctx, ref)
        del self._data[ref.ref_id]
