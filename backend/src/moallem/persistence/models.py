"""PostgreSQL schema models for identity, tenant-scoped resources, and P4 reliability state."""

import uuid
from datetime import datetime
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
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    auth_issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    auth_subject: Mapped[str] = mapped_column(String(512), nullable=False)
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
