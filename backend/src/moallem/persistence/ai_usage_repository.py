"""PostgreSQL repository for immutable AI invocation identity and metered usage."""

import hashlib
import re
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from moallem.ai.usage import (
    UsageLedgerBeginResult,
    UsageLedgerCompletion,
    UsageLedgerFailure,
    UsageLedgerStart,
)
from moallem.persistence.database import SessionFactory, session_scope
from moallem.persistence.models import (
    AIUsageLedgerModel,
    AIUsageSourceRefModel,
    SourceChunkModel,
    SourceFileModel,
)


class AIUsageSourceReferenceError(RuntimeError):
    """An invocation attempted to cite a missing, unextracted, or altered source chunk."""


class PostgresAIUsageLedgerRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def begin(self, record: UsageLedgerStart) -> UsageLedgerBeginResult:
        """Atomically create or classify a previously used invocation identity."""
        if not re.fullmatch(r"[0-9a-f]{64}", record.request_hash):
            raise ValueError("AI request hash must be a lowercase SHA-256 digest")
        if len(record.source_refs) > 256 or len(set(record.source_refs)) != len(
            record.source_refs
        ):
            raise AIUsageSourceReferenceError("AI source reference set is invalid")
        if (
            not record.budget_reserved_amount.is_finite()
            or record.budget_reserved_amount <= 0
            or record.budget_reserved_amount > Decimal("999999999999.999999999999")
            or record.budget_reserved_amount.as_tuple().exponent < -12
        ):
            raise ValueError("AI budget reservation must be positive and fit Numeric(24,12)")
        if not re.fullmatch(r"[A-Z]{3}", record.budget_currency):
            raise ValueError("AI budget currency must be a 3-letter uppercase code")
        statement = (
            insert(AIUsageLedgerModel)
            .values(
                id=uuid4(),
                tenant_id=record.tenant_id,
                task_id=record.task_id,
                course_id=record.course_id,
                actor_membership_id=record.actor_membership_id,
                invocation_id=record.invocation_id,
                provider_id=record.provider.provider_id,
                model_id=record.provider.model_id,
                model_version=record.provider.model_version,
                region=record.provider.region,
                prompt_version=record.prompt_version,
                pricing_version=record.pricing_version,
                permit_ref=record.permit_ref,
                privacy_policy_ref=record.privacy_policy_ref,
                budget_reservation_ref=record.budget_reservation_ref,
                budget_reserved_amount=record.budget_reserved_amount,
                budget_currency=record.budget_currency,
                request_hash=record.request_hash,
                state="STARTED",
            )
            .on_conflict_do_nothing(
                index_elements=[
                    AIUsageLedgerModel.tenant_id,
                    AIUsageLedgerModel.task_id,
                    AIUsageLedgerModel.invocation_id,
                ]
            )
            .returning(AIUsageLedgerModel.id)
        )
        with session_scope(self._sessions) as session:
            inserted_id = session.execute(statement).scalar_one_or_none()
            if inserted_id is not None:
                if record.source_refs:
                    source_rows = session.scalars(
                        select(SourceChunkModel)
                        .join(
                            SourceFileModel,
                            (SourceFileModel.tenant_id == SourceChunkModel.tenant_id)
                            & (SourceFileModel.id == SourceChunkModel.file_id)
                            & (SourceFileModel.version == SourceChunkModel.file_version)
                            & (SourceFileModel.course_id == SourceChunkModel.course_id),
                        )
                        .where(
                            SourceChunkModel.tenant_id == record.tenant_id,
                            SourceChunkModel.course_id == record.course_id,
                            SourceChunkModel.id.in_(record.source_refs),
                            SourceFileModel.state == "EXTRACTED",
                        )
                        .with_for_update(of=SourceFileModel)
                    ).all()
                    if len(source_rows) != len(record.source_refs):
                        raise AIUsageSourceReferenceError(
                            "AI source references must be extracted in the same tenant/course"
                        )
                    for source_row in source_rows:
                        actual_hash = hashlib.sha256(source_row.content.encode("utf-8")).hexdigest()
                        if actual_hash != source_row.content_hash:
                            raise AIUsageSourceReferenceError(
                                "AI source reference content hash does not match"
                            )
                session.add_all(
                    [
                        AIUsageSourceRefModel(
                            tenant_id=record.tenant_id,
                            task_id=record.task_id,
                            invocation_id=record.invocation_id,
                            course_id=record.course_id,
                            source_chunk_id=source_ref,
                        )
                        for source_ref in record.source_refs
                    ]
                )
                return UsageLedgerBeginResult.CREATED
            existing_hash = session.scalar(
                select(AIUsageLedgerModel.request_hash).where(
                    AIUsageLedgerModel.tenant_id == record.tenant_id,
                    AIUsageLedgerModel.task_id == record.task_id,
                    AIUsageLedgerModel.invocation_id == record.invocation_id,
                )
            )
            if existing_hash is None:
                raise RuntimeError(
                    "AI invocation conflict row was not visible after insert conflict"
                )
            if existing_hash == record.request_hash:
                return UsageLedgerBeginResult.SAME_REQUEST
            return UsageLedgerBeginResult.REQUEST_HASH_CONFLICT

    def complete(self, record: UsageLedgerCompletion) -> bool:
        if not re.fullmatch(r"[0-9a-f]{64}", record.response_hash):
            raise ValueError("AI response hash must be a lowercase SHA-256 digest")
        if record.input_tokens < 0 or record.output_tokens < 0:
            raise ValueError("AI token counts cannot be negative")
        if (
            not record.cost_amount.is_finite()
            or record.cost_amount < 0
            or record.cost_amount > Decimal("999999999999.999999999999")
            or record.cost_amount.as_tuple().exponent < -12
        ):
            raise ValueError("AI cost must be finite and fit Numeric(24,12)")
        if not re.fullmatch(r"[A-Z]{3}", record.currency):
            raise ValueError("AI currency must be a 3-letter uppercase code")
        with session_scope(self._sessions) as session:
            result = session.execute(
                update(AIUsageLedgerModel)
                .where(
                    AIUsageLedgerModel.tenant_id == record.tenant_id,
                    AIUsageLedgerModel.task_id == record.task_id,
                    AIUsageLedgerModel.invocation_id == record.invocation_id,
                    AIUsageLedgerModel.state == "STARTED",
                )
                .values(
                    state="SUCCEEDED",
                    response_hash=record.response_hash,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    cost_amount=record.cost_amount,
                    currency=record.currency,
                    finished_at=func.now(),
                    failure_code=None,
                )
            )
            return result.rowcount == 1

    def mark_unknown(self, record: UsageLedgerFailure) -> bool:
        return self._finish_failure(record, "UNKNOWN")

    def mark_failed(self, record: UsageLedgerFailure) -> bool:
        return self._finish_failure(record, "FAILED")

    def _finish_failure(self, record: UsageLedgerFailure, state: str) -> bool:
        if (
            not record.safe_error_code
            or len(record.safe_error_code) > 64
            or not record.safe_error_code.isascii()
            or record.safe_error_code.upper() != record.safe_error_code
            or not record.safe_error_code.replace("_", "").isalnum()
        ):
            raise ValueError("AI failure code must be a safe uppercase identifier")
        with session_scope(self._sessions) as session:
            result = session.execute(
                update(AIUsageLedgerModel)
                .where(
                    AIUsageLedgerModel.tenant_id == record.tenant_id,
                    AIUsageLedgerModel.task_id == record.task_id,
                    AIUsageLedgerModel.invocation_id == record.invocation_id,
                    AIUsageLedgerModel.state == "STARTED",
                )
                .values(
                    state=state,
                    failure_code=record.safe_error_code,
                    finished_at=func.now(),
                )
            )
            return result.rowcount == 1
