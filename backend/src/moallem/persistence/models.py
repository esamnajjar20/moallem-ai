"""PostgreSQL schema models for identity, tenant-scoped resources, and P4 reliability state."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantModel(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserModel(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("auth_issuer", "auth_subject", name="uq_users_auth_identity"),
        CheckConstraint(
            "auth_status IN ('ACTIVE', 'SUSPENDED', 'REVOKED')",
            name="ck_users_auth_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    auth_issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    auth_subject: Mapped[str] = mapped_column(String(512), nullable=False)
    auth_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="ACTIVE"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MembershipModel(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_memberships_tenant_id_id"),
        Index("ix_memberships_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SecretVaultEntryModel(Base):
    __tablename__ = "secret_vault_entries"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    reference_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_version: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MoodleConnectionModel(Base):
    __tablename__ = "moodle_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_moodle_connections_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "secret_reference_id"],
            ["secret_vault_entries.tenant_id", "secret_vault_entries.reference_id"],
            name="fk_moodle_connections_secret",
            ondelete="RESTRICT",
        ),
        Index("ix_moodle_connections_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    site_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret_reference_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    moodle_user_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TaskModel(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tasks_tenant_id_id"),
        UniqueConstraint("tenant_id", "id", "course_id", name="uq_tasks_tenant_id_course"),
        UniqueConstraint("tenant_id", "retry_of_task_id", name="uq_tasks_tenant_retry_parent"),
        ForeignKeyConstraint(
            ["tenant_id", "actor_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_tasks_actor_membership",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "connection_id"],
            ["moodle_connections.tenant_id", "moodle_connections.id"],
            name="fk_tasks_connection",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "retry_of_task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_tasks_retry_parent",
            ondelete="RESTRICT",
        ),
        Index("ix_tasks_tenant_status_updated", "tenant_id", "status", "updated_at"),
        CheckConstraint("latest_event_sequence >= 0", name="ck_tasks_event_sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    retry_of_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    external_dispatched: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    latest_event_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class TaskEventModel(Base):
    __tablename__ = "task_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_task_events_task",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "task_id", "sequence", name="uq_task_events_sequence"),
        Index("ix_task_events_task_sequence", "task_id", "sequence"),
        CheckConstraint("sequence > 0", name="ck_task_events_sequence"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    message_code: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IdempotencyRecordModel(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "actor_membership_id",
            "operation_code",
            "key_hash",
            name="uq_idempotency_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_idempotency_membership",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "operation_ref"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_idempotency_operation_task",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_idempotency_expires", "expires_at"),
        Index("ix_idempotency_operation", "tenant_id", "operation_ref"),
        CheckConstraint("octet_length(key_hash) = 64", name="ck_idempotency_hash_length"),
        CheckConstraint(
            "octet_length(request_hash) = 64", name="ck_idempotency_request_hash_length"
        ),
        CheckConstraint(
            "state IN ('IN_PROGRESS', 'COMPLETED', 'FAILED_FINAL')",
            name="ck_idempotency_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation_code: Mapped[str] = mapped_column(String(128), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    operation_ref: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_ref: Mapped[str | None] = mapped_column(String(512))
    external_unresolved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_outbox_task",
            ondelete="CASCADE",
        ),
        Index("ix_outbox_due", "status", "next_attempt_at"),
        Index(
            "ix_outbox_lease_expiry",
            "lease_expires_at",
            postgresql_where=text("status = 'LEASED'"),
        ),
        Index("ix_outbox_task", "tenant_id", "task_id"),
        CheckConstraint(
            "status IN ('PENDING', 'LEASED', 'PUBLISHED', 'DEAD_LETTER')",
            name="ck_outbox_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_outbox_attempts"),
        CheckConstraint("lease_generation >= 0", name="ck_outbox_lease_generation"),
        CheckConstraint(
            "(status = 'LEASED' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'LEASED' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_outbox_lease",
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InboxReceiptModel(Base):
    __tablename__ = "inbox_receipts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "consumer",
            "message_id",
            name="uq_inbox_tenant_consumer_message",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_inbox_receipt_tenant",
            ondelete="RESTRICT",
        ),
        Index("ix_inbox_created", "created_at"),
        Index("ix_inbox_retry_due", "state", "next_attempt_at"),
        Index(
            "uq_inbox_legacy_unscoped_dedup",
            "consumer",
            "message_id",
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
        CheckConstraint(
            "state IN ('RECEIVED', 'PROCESSING', 'PROCESSED', 'FAILED')",
            name="ck_inbox_receipt_state",
        ),
        CheckConstraint("attempts >= 0", name="ck_inbox_receipt_attempts"),
        CheckConstraint("lease_generation >= 0", name="ck_inbox_lease_generation"),
        CheckConstraint(
            "(state = 'PROCESSING' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (state <> 'PROCESSING' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_inbox_receipt_lease",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    consumer: Mapped[str] = mapped_column(String(128), nullable=False)
    message_id: Mapped[str] = mapped_column(String(256), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="RECEIVED")
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    processed_result_ref: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIUsageLedgerModel(Base):
    """Append-only AI accounting identity; lifecycle fields are finalized once."""

    __tablename__ = "ai_usage_ledger"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "task_id", "invocation_id", name="uq_ai_usage_task_invocation"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "task_id", "course_id"],
            ["tasks.tenant_id", "tasks.id", "tasks.course_id"],
            name="fk_ai_usage_task_course",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_ai_usage_actor_membership",
            ondelete="RESTRICT",
        ),
        Index("ix_ai_usage_tenant_started", "tenant_id", "started_at"),
        Index("ix_ai_usage_tenant_task", "tenant_id", "task_id"),
        CheckConstraint(
            "state IN ('STARTED', 'SUCCEEDED', 'FAILED', 'UNKNOWN')",
            name="ck_ai_usage_state",
        ),
        CheckConstraint("octet_length(request_hash) = 64", name="ck_ai_usage_request_hash"),
        CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'", name="ck_ai_usage_request_hash_hex"
        ),
        CheckConstraint(
            "response_hash IS NULL OR octet_length(response_hash) = 64",
            name="ck_ai_usage_response_hash",
        ),
        CheckConstraint(
            "response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$'",
            name="ck_ai_usage_response_hash_hex",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="ck_ai_usage_input_tokens"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="ck_ai_usage_output_tokens"
        ),
        CheckConstraint("cost_amount IS NULL OR cost_amount >= 0", name="ck_ai_usage_cost"),
        CheckConstraint("budget_reserved_amount > 0", name="ck_ai_usage_budget_reserved"),
        CheckConstraint("budget_currency ~ '^[A-Z]{3}$'", name="ck_ai_usage_budget_currency"),
        CheckConstraint(
            "(cost_amount IS NULL AND currency IS NULL) OR "
            "(cost_amount IS NOT NULL AND currency ~ '^[A-Z]{3}$')",
            name="ck_ai_usage_currency",
        ),
        CheckConstraint(
            "(state = 'STARTED' AND finished_at IS NULL) OR "
            "(state <> 'STARTED' AND finished_at IS NOT NULL)",
            name="ck_ai_usage_finished_state",
        ),
        CheckConstraint(
            "state <> 'SUCCEEDED' OR "
            "(input_tokens IS NOT NULL AND output_tokens IS NOT NULL "
            "AND cost_amount IS NOT NULL AND currency IS NOT NULL "
            "AND response_hash IS NOT NULL)",
            name="ck_ai_usage_success_complete",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    invocation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(128), nullable=False)
    pricing_version: Mapped[str] = mapped_column(String(128), nullable=False)
    permit_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    privacy_policy_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    budget_reservation_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    budget_reserved_amount: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    budget_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_hash: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="STARTED")
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 12))
    currency: Mapped[str | None] = mapped_column(String(3))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceFileModel(Base):
    """Tenant/course-scoped file metadata; bytes remain in private quarantine storage."""

    __tablename__ = "source_files"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_source_files_tenant_id"),
        UniqueConstraint(
            "tenant_id", "id", "version", "course_id", name="uq_source_files_provenance_scope"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "uploaded_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_source_files_uploader_membership",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "task_id", "course_id"],
            ["tasks.tenant_id", "tasks.id", "tasks.course_id"],
            name="fk_source_files_task_course",
            ondelete="RESTRICT",
        ),
        Index("ix_source_files_tenant_course_state", "tenant_id", "course_id", "state"),
        Index("ix_source_files_tenant_hash", "tenant_id", "sha256"),
        CheckConstraint("version >= 1", name="ck_source_files_version"),
        CheckConstraint("byte_size > 0", name="ck_source_files_byte_size"),
        CheckConstraint("octet_length(sha256) = 64", name="ck_source_files_sha256"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_source_files_sha256_hex"),
        CheckConstraint(
            "length(storage_ref) > 0 AND storage_ref = btrim(storage_ref) "
            "AND storage_ref !~ '[[:space:]]' AND storage_ref !~ '[[:cntrl:]]' "
            "AND storage_ref !~ '[?#]' AND storage_ref !~ '^//' "
            "AND (storage_ref !~* '^[a-z][a-z0-9+.-]*:' "
            "OR storage_ref ~* '^(s3|gs|gcs|az|azure|r2)://[^/@?#]+(/[^?#]*)?$')",
            name="ck_source_files_private_storage_ref",
        ),
        CheckConstraint(
            "state IN ('QUARANTINED', 'CLEAN', 'REJECTED', 'EXTRACTED', 'FAILED')",
            name="ck_source_files_state",
        ),
        CheckConstraint("page_count IS NULL OR page_count >= 0", name="ck_source_files_pages"),
        CheckConstraint("chunk_count >= 0", name="ck_source_files_chunks"),
        CheckConstraint(
            "state <> 'EXTRACTED' OR (extractor_version IS NOT NULL AND chunk_count > 0)",
            name="ck_source_files_extracted_complete",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    uploaded_by_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    detected_mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    extraction_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="QUARANTINED")
    scanner_id: Mapped[str | None] = mapped_column(String(128))
    scanner_version: Mapped[str | None] = mapped_column(String(128))
    scan_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extractor_version: Mapped[str | None] = mapped_column(String(128))
    page_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SourceChunkModel(Base):
    """Extracted text with stable file/page/section/hash provenance."""

    __tablename__ = "source_chunks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "file_id", "file_version", "chunk_index", name="uq_source_chunk_order"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_source_chunks_tenant_id"),
        UniqueConstraint("tenant_id", "id", "course_id", name="uq_source_chunks_tenant_course"),
        ForeignKeyConstraint(
            ["tenant_id", "file_id", "file_version", "course_id"],
            [
                "source_files.tenant_id",
                "source_files.id",
                "source_files.version",
                "source_files.course_id",
            ],
            name="fk_source_chunks_file_provenance",
            ondelete="CASCADE",
        ),
        Index("ix_source_chunks_tenant_course_file", "tenant_id", "course_id", "file_id"),
        CheckConstraint("chunk_index >= 0", name="ck_source_chunks_index"),
        CheckConstraint("page_number IS NULL OR page_number >= 1", name="ck_source_chunks_page"),
        CheckConstraint("length(content) > 0", name="ck_source_chunks_content"),
        CheckConstraint("octet_length(content_hash) = 64", name="ck_source_chunks_hash"),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="ck_source_chunks_content_hash_hex"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    file_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    file_version: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_path: Mapped[str | None] = mapped_column(String(1024))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AIUsageSourceRefModel(Base):
    """Tenant-safe many-to-many link from one AI invocation to evidence chunks."""

    __tablename__ = "ai_usage_source_refs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "task_id", "invocation_id"],
            [
                "ai_usage_ledger.tenant_id",
                "ai_usage_ledger.task_id",
                "ai_usage_ledger.invocation_id",
            ],
            name="fk_ai_usage_source_refs_usage",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "task_id", "course_id"],
            ["tasks.tenant_id", "tasks.id", "tasks.course_id"],
            name="fk_ai_usage_source_refs_task_course",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_chunk_id", "course_id"],
            ["source_chunks.tenant_id", "source_chunks.id", "source_chunks.course_id"],
            name="fk_ai_usage_source_refs_chunk_course",
            ondelete="RESTRICT",
        ),
        Index("ix_ai_usage_source_refs_source", "tenant_id", "source_chunk_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    invocation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    course_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_chunk_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)


class QuizDraftSnapshotModel(Base):
    """Append-only server-owned preview snapshot bound to one task and destination."""

    __tablename__ = "quiz_draft_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_quiz_draft_snapshots_tenant_id"),
        UniqueConstraint(
            "tenant_id", "task_id", "version_no", name="uq_quiz_draft_snapshots_version"
        ),
        UniqueConstraint(
            "tenant_id", "task_id", "snapshot_hash", name="uq_quiz_draft_snapshots_hash"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_quiz_draft_snapshots_task",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_quiz_draft_snapshots_membership",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version_no >= 1", name="ck_quiz_draft_snapshots_version"),
        CheckConstraint(
            "snapshot_hash ~ '^[0-9a-f]{64}$'", name="ck_quiz_draft_snapshots_hash"
        ),
        Index("ix_quiz_draft_snapshots_task_version", "tenant_id", "task_id", "version_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(128), nullable=False)
    destination: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    quality_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QuizApprovalModel(Base):
    """Append-only approval decision for exactly one immutable snapshot hash."""

    __tablename__ = "quiz_approvals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_quiz_approvals_tenant_id"),
        UniqueConstraint(
            "tenant_id", "task_id", "snapshot_id", "approver_membership_id",
            name="uq_quiz_approvals_actor_snapshot",
        ),
        UniqueConstraint(
            "tenant_id", "approver_membership_id", "idempotency_key_hash",
            name="uq_quiz_approvals_idempotency",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_quiz_approvals_task",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"],
            ["quiz_draft_snapshots.tenant_id", "quiz_draft_snapshots.id"],
            name="fk_quiz_approvals_snapshot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "approver_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_quiz_approvals_membership",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "decision IN ('APPROVED', 'REJECTED')", name="ck_quiz_approvals_decision"
        ),
        CheckConstraint(
            "snapshot_hash ~ '^[0-9a-f]{64}$'", name="ck_quiz_approvals_snapshot_hash"
        ),
        CheckConstraint(
            "idempotency_key_hash ~ '^[0-9a-f]{64}$'", name="ck_quiz_approvals_idempotency_hash"
        ),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="ck_quiz_approvals_request_hash"),
        CheckConstraint("expires_at > decided_at", name="ck_quiz_approvals_expiry"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approver_membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(2000))
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PublishIntentModel(Base):
    """Durable single logical publish attempt tied to an approved snapshot."""

    __tablename__ = "publish_intents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_publish_intents_tenant_id"),
        UniqueConstraint(
            "tenant_id", "task_id", "snapshot_id", name="uq_publish_intents_task_snapshot"
        ),
        UniqueConstraint(
            "tenant_id", "external_operation_key", name="uq_publish_intents_operation_key"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["tasks.tenant_id", "tasks.id"],
            name="fk_publish_intents_task",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"],
            ["quiz_draft_snapshots.tenant_id", "quiz_draft_snapshots.id"],
            name="fk_publish_intents_snapshot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "approval_id"],
            ["quiz_approvals.tenant_id", "quiz_approvals.id"],
            name="fk_publish_intents_approval",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "state IN ('PREPARED', 'EXECUTING', 'VERIFYING', 'COMPLETED', "
            "'NEEDS_RECONCILIATION', 'FAILED', 'MANUAL_REVIEW')",
            name="ck_publish_intents_state",
        ),
        CheckConstraint(
            "snapshot_hash ~ '^[0-9a-f]{64}$'", name="ck_publish_intents_snapshot_hash"
        ),
        CheckConstraint(
            "external_operation_key ~ '^[0-9a-f]{64}$'", name="ck_publish_intents_operation_key"
        ),
        Index("ix_publish_intents_state_created", "state", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    approval_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    external_operation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default="PREPARED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ToolInvocationModel(Base):
    """Durable external-step ledger; attempt_no is not part of step identity."""

    __tablename__ = "tool_invocations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "publish_intent_id", "external_step_key",
            name="uq_tool_invocations_step_key",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "publish_intent_id"],
            ["publish_intents.tenant_id", "publish_intents.id"],
            name="fk_tool_invocations_publish_intent",
            ondelete="RESTRICT",
        ),
        CheckConstraint("ordinal >= 0", name="ck_tool_invocations_ordinal"),
        CheckConstraint("attempt_no >= 0", name="ck_tool_invocations_attempt"),
        CheckConstraint(
            "state IN ('PLANNED', 'DISPATCHED', 'SUCCEEDED', 'FAILED_DEFINITE', 'UNKNOWN', "
            "'RECONCILED_PRESENT', 'RECONCILED_ABSENT', 'MANUAL_REVIEW')",
            name="ck_tool_invocations_state",
        ),
        CheckConstraint(
            "external_step_key ~ '^[0-9a-f]{64}$'", name="ck_tool_invocations_step_key"
        ),
        CheckConstraint(
            "request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_tool_invocations_request_hash",
        ),
        CheckConstraint(
            "response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$'",
            name="ck_tool_invocations_response_hash",
        ),
        Index("ix_tool_invocations_intent_state", "tenant_id", "publish_intent_id", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    publish_intent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    external_step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    step_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    request_hash: Mapped[str | None] = mapped_column(String(64))
    response_hash: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), nullable=False, server_default="PLANNED")
    external_ref: Mapped[str | None] = mapped_column(String(512))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
