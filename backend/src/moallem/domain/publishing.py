"""Approval binding and publish preflight invariants for P7 (Approval & Publish).

This module contains no network calls.  A Moodle write requires an explicitly injected adapter
and a trusted, server-derived preflight result; the production default remains deny-all.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from moallem.domain.canonical import canonical_hash
from moallem.domain.errors import TaskStateConflict


class ApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class SnapshotDescriptor:
    snapshot_id: str
    task_id: str
    tenant_id: str
    version_no: int
    snapshot_hash: str
    connection_id: str
    course_id: str

    def __post_init__(self) -> None:
        if self.version_no < 1:
            raise ValueError("snapshot version must be positive")
        if not _is_sha256(self.snapshot_hash):
            raise ValueError("snapshot_hash must be lowercase SHA-256")
        for value in (
            self.snapshot_id,
            self.task_id,
            self.tenant_id,
            self.connection_id,
            self.course_id,
        ):
            if not value or value != value.strip():
                raise ValueError("snapshot identifiers must be non-empty trimmed strings")


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    approval_id: str
    tenant_id: str
    task_id: str
    snapshot_id: str
    snapshot_hash: str
    approver_membership_id: str
    decision: ApprovalDecision
    decided_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not _is_sha256(self.snapshot_hash):
            raise ValueError("approval snapshot_hash must be lowercase SHA-256")
        if self.decided_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("approval timestamps must be timezone-aware")
        if self.expires_at <= self.decided_at:
            raise ValueError("approval expiry must be after decision time")


def snapshot_hash(*, destination: dict[str, object], content: dict[str, object], schema_version: str) -> str:
    """Hash every field that can affect the Moodle side effect.

    The destination is server-resolved from the task's persisted connection/course; it is never
    accepted from an approval request.  Decimal values must be encoded as strings before hashing.
    """
    if not schema_version or schema_version != schema_version.strip():
        raise ValueError("schema_version must be non-empty trimmed text")
    return canonical_hash(
        {
            "schema_version": schema_version,
            "destination": destination,
            "content": content,
        }
    )


def approval_is_valid(
    approval: ApprovalRecord,
    snapshot: SnapshotDescriptor,
    *,
    tenant_id: str,
    approver_membership_id: str,
    now: datetime,
) -> bool:
    """Return whether an approval is usable for this exact current snapshot and actor scope."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return (
        approval.decision is ApprovalDecision.APPROVED
        and approval.tenant_id == tenant_id == snapshot.tenant_id
        and approval.task_id == snapshot.task_id
        and approval.snapshot_id == snapshot.snapshot_id
        and approval.snapshot_hash == snapshot.snapshot_hash
        and approval.approver_membership_id == approver_membership_id
        and approval.decided_at <= now < approval.expires_at
    )


class PreflightCode(StrEnum):
    MEMBERSHIP_INACTIVE = "MEMBERSHIP_INACTIVE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CONNECTION_INACTIVE = "CONNECTION_INACTIVE"
    COURSE_ACCESS_UNVERIFIED = "COURSE_ACCESS_UNVERIFIED"
    CAPABILITY_UNVERIFIED = "CAPABILITY_UNVERIFIED"
    CREDENTIAL_INVALID = "CREDENTIAL_INVALID"
    QUOTA_NOT_RESERVED = "QUOTA_NOT_RESERVED"
    SITE_PROFILE_UNAPPROVED = "SITE_PROFILE_UNAPPROVED"
    APPROVAL_INVALID = "APPROVAL_INVALID"
    SNAPSHOT_STALE = "SNAPSHOT_STALE"


@dataclass(frozen=True, slots=True)
class PublishPreflight:
    """Server-derived evidence collected immediately before any external write."""

    membership_active: bool
    permission_granted: bool
    connection_active: bool
    course_access_verified: bool
    create_capability_verified: bool
    credential_valid: bool
    quota_reserved: bool
    site_profile_approved: bool
    approval_valid: bool
    snapshot_current: bool

    @property
    def blockers(self) -> tuple[PreflightCode, ...]:
        checks = (
            (self.membership_active, PreflightCode.MEMBERSHIP_INACTIVE),
            (self.permission_granted, PreflightCode.PERMISSION_DENIED),
            (self.connection_active, PreflightCode.CONNECTION_INACTIVE),
            (self.course_access_verified, PreflightCode.COURSE_ACCESS_UNVERIFIED),
            (self.create_capability_verified, PreflightCode.CAPABILITY_UNVERIFIED),
            (self.credential_valid, PreflightCode.CREDENTIAL_INVALID),
            (self.quota_reserved, PreflightCode.QUOTA_NOT_RESERVED),
            (self.site_profile_approved, PreflightCode.SITE_PROFILE_UNAPPROVED),
            (self.approval_valid, PreflightCode.APPROVAL_INVALID),
            (self.snapshot_current, PreflightCode.SNAPSHOT_STALE),
        )
        return tuple(code for passed, code in checks if passed is not True)

    def require_ready(self) -> None:
        if self.blockers:
            raise TaskStateConflict("publish preflight blocked: " + ",".join(x.value for x in self.blockers))


class PublishAuthorizer(Protocol):
    def preflight(self, *, task_id: str, snapshot: SnapshotDescriptor) -> PublishPreflight: ...


class DenyAllPublishAuthorizer:
    """Production-safe default until DEC-027/043 and site-specific write evidence close."""

    def preflight(self, *, task_id: str, snapshot: SnapshotDescriptor) -> PublishPreflight:
        del task_id, snapshot
        return PublishPreflight(
            membership_active=False,
            permission_granted=False,
            connection_active=False,
            course_access_verified=False,
            create_capability_verified=False,
            credential_valid=False,
            quota_reserved=False,
            site_profile_approved=False,
            approval_valid=False,
            snapshot_current=False,
        )


class PublishState(StrEnum):
    PREPARED = "PREPARED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass(frozen=True, slots=True)
class PublishIntent:
    publish_intent_id: str
    task_id: str
    tenant_id: str
    snapshot_id: str
    snapshot_hash: str
    external_operation_key: str
    state: PublishState = PublishState.PREPARED

    def __post_init__(self) -> None:
        if not _is_sha256(self.snapshot_hash) or not _is_sha256(self.external_operation_key):
            raise ValueError("publish intent hashes must be lowercase SHA-256")


def derive_operation_key(publish_intent_id: str) -> str:
    if not publish_intent_id or publish_intent_id != publish_intent_id.strip():
        raise ValueError("publish_intent_id must be non-empty trimmed text")
    return hashlib.sha256(f"moallem:op:v1:{publish_intent_id}".encode("utf-8")).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)
