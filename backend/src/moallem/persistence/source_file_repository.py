"""Tenant/course-scoped PostgreSQL persistence for quarantined files and provenance chunks."""

import hashlib
import re
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select, update

from moallem.files.contracts import (
    FileUpload,
    PersistedChunkInput,
    ScanResult,
    ScanVerdict,
    SourceChunk,
    SourceFileRegistration,
    SourceFileState,
    is_private_storage_reference,
)
from moallem.persistence.database import SessionFactory, session_scope
from moallem.persistence.models import SourceChunkModel, SourceFileModel


class SourceFileStateConflict(RuntimeError):
    """A file's durable scan/extraction state did not allow the requested transition."""


class PostgresSourceFileRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def create_quarantined(self, record: SourceFileRegistration) -> None:
        upload = record.upload
        declared_mime = upload.declared_mime_type.split(";", 1)[0].strip().lower()
        if declared_mime not in {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }:
            raise SourceFileStateConflict("declared MIME type is not supported")
        expected_detected = (
            "application/pdf" if declared_mime == "application/pdf" else "application/zip"
        )
        if record.detected_mime_type != expected_detected:
            raise SourceFileStateConflict(
                "detected MIME type does not match the declared file family"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", record.sha256):
            raise SourceFileStateConflict("source SHA-256 is invalid")
        if record.byte_size < 1:
            raise SourceFileStateConflict("source byte size must be positive")
        if not is_private_storage_reference(record.storage_ref):
            raise SourceFileStateConflict("storage reference must be a private opaque identifier")
        if not upload.course_id or len(upload.course_id) > 128:
            raise SourceFileStateConflict("course scope is invalid")
        name = upload.original_filename
        if (
            upload.version < 1
            or not name
            or name != name.strip()
            or len(name) > 255
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in name)
        ):
            raise SourceFileStateConflict("source file metadata is invalid")
        expected_extension = {
            "application/pdf": ".pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        }[declared_mime]
        if not name.lower().endswith(expected_extension):
            raise SourceFileStateConflict("filename extension does not match declared MIME")
        with session_scope(self._sessions) as session:
            session.add(
                SourceFileModel(
                    id=upload.file_id,
                    tenant_id=upload.tenant_id,
                    course_id=upload.course_id,
                    task_id=upload.task_id,
                    uploaded_by_membership_id=upload.uploaded_by_membership_id,
                    version=upload.version,
                    original_filename=upload.original_filename,
                    declared_mime_type=declared_mime,
                    detected_mime_type=record.detected_mime_type,
                    sha256=record.sha256,
                    byte_size=record.byte_size,
                    storage_ref=record.storage_ref,
                    extraction_profile=upload.extraction_profile.value,
                    state=SourceFileState.QUARANTINED.value,
                )
            )

    def reject_before_scan(self, upload: FileUpload, safe_error_code: str) -> None:
        with session_scope(self._sessions) as session:
            updated = session.execute(
                update(SourceFileModel)
                .where(
                    SourceFileModel.id == upload.file_id,
                    SourceFileModel.tenant_id == upload.tenant_id,
                    SourceFileModel.course_id == upload.course_id,
                    SourceFileModel.state == SourceFileState.QUARANTINED.value,
                )
                .values(
                    state=SourceFileState.REJECTED.value,
                    last_error_code=safe_error_code,
                )
            )
            if updated.rowcount != 1:
                raise SourceFileStateConflict("file is not in QUARANTINED state")

    def record_scan_result(self, upload: FileUpload, result: ScanResult) -> None:
        if result.verdict is ScanVerdict.CLEAN:
            state = SourceFileState.CLEAN.value
        elif result.verdict is ScanVerdict.MALICIOUS:
            state = SourceFileState.REJECTED.value
        else:
            state = SourceFileState.QUARANTINED.value
        with session_scope(self._sessions) as session:
            updated = session.execute(
                update(SourceFileModel)
                .where(
                    SourceFileModel.id == upload.file_id,
                    SourceFileModel.tenant_id == upload.tenant_id,
                    SourceFileModel.course_id == upload.course_id,
                    SourceFileModel.state == SourceFileState.QUARANTINED.value,
                )
                .values(
                    state=state,
                    scanner_id=result.scanner_id[:128],
                    scanner_version=result.scanner_version[:128],
                    scan_completed_at=func.now(),
                    last_error_code=result.safe_error_code,
                )
            )
            if updated.rowcount != 1:
                raise SourceFileStateConflict("file is not in QUARANTINED state")

    def mark_failed(self, upload: FileUpload, safe_error_code: str) -> None:
        with session_scope(self._sessions) as session:
            updated = session.execute(
                update(SourceFileModel)
                .where(
                    SourceFileModel.id == upload.file_id,
                    SourceFileModel.tenant_id == upload.tenant_id,
                    SourceFileModel.course_id == upload.course_id,
                    SourceFileModel.state.in_(
                        [SourceFileState.CLEAN.value, SourceFileState.QUARANTINED.value]
                    ),
                )
                .values(state=SourceFileState.FAILED.value, last_error_code=safe_error_code)
            )
            if updated.rowcount != 1:
                raise SourceFileStateConflict("file cannot transition to FAILED")

    def persist_extracted(
        self,
        upload: FileUpload,
        *,
        expected_sha256: str,
        extractor_version: str,
        page_count: int,
        chunks: Sequence[PersistedChunkInput],
    ) -> None:
        # Revalidate sandbox output at the persistence boundary. This protects provenance even
        # when a future caller bypasses FileIntakeService or the parser adapter is replaced.
        if not extractor_version or len(extractor_version) > 128:
            raise SourceFileStateConflict("extractor version is invalid")
        if page_count < 1:
            raise SourceFileStateConflict("page count must be positive")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise SourceFileStateConflict("expected source hash is invalid")
        if not chunks:
            raise SourceFileStateConflict("no provenance chunks were supplied")
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise SourceFileStateConflict("chunk identifiers must be unique")
        for expected_index, chunk in enumerate(chunks):
            if chunk.chunk_index != expected_index:
                raise SourceFileStateConflict("chunk indices must be contiguous from zero")
            if not chunk.content or not chunk.content.strip():
                raise SourceFileStateConflict("chunk content must not be empty")
            actual_hash = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
            if actual_hash != chunk.content_hash:
                raise SourceFileStateConflict("chunk content hash does not match content")
            if chunk.page_number is not None and not 1 <= chunk.page_number <= page_count:
                raise SourceFileStateConflict("chunk page is outside extracted document")
            if chunk.section_path is not None and len(chunk.section_path) > 1024:
                raise SourceFileStateConflict("chunk section path is too long")

        with session_scope(self._sessions) as session:
            source_file = session.scalar(
                select(SourceFileModel)
                .where(
                    SourceFileModel.id == upload.file_id,
                    SourceFileModel.tenant_id == upload.tenant_id,
                    SourceFileModel.course_id == upload.course_id,
                )
                .with_for_update()
            )
            if source_file is None:
                raise SourceFileStateConflict("source file not found in this tenant/course")
            if source_file.state != SourceFileState.CLEAN.value:
                raise SourceFileStateConflict("only CLEAN files can be extracted")
            if source_file.sha256 != expected_sha256 or source_file.version != upload.version:
                raise SourceFileStateConflict("source file version/hash changed before extraction")
            session.add_all(
                [
                    SourceChunkModel(
                        id=chunk.chunk_id,
                        tenant_id=upload.tenant_id,
                        course_id=upload.course_id,
                        file_id=upload.file_id,
                        file_version=upload.version,
                        chunk_index=chunk.chunk_index,
                        page_number=chunk.page_number,
                        section_path=chunk.section_path,
                        content=chunk.content,
                        content_hash=chunk.content_hash,
                    )
                    for chunk in chunks
                ]
            )
            source_file.state = SourceFileState.EXTRACTED.value
            source_file.extractor_version = extractor_version
            source_file.page_count = page_count
            source_file.chunk_count = len(chunks)
            source_file.last_error_code = None

    def get_chunks(
        self,
        *,
        tenant_id: UUID,
        course_id: str,
        chunk_ids: Sequence[UUID],
    ) -> tuple[SourceChunk, ...]:
        if not chunk_ids:
            return ()
        with session_scope(self._sessions) as session:
            rows = session.scalars(
                select(SourceChunkModel)
                .join(
                    SourceFileModel,
                    (SourceFileModel.tenant_id == SourceChunkModel.tenant_id)
                    & (SourceFileModel.id == SourceChunkModel.file_id)
                    & (SourceFileModel.version == SourceChunkModel.file_version)
                    & (SourceFileModel.course_id == SourceChunkModel.course_id),
                )
                .where(
                    SourceChunkModel.tenant_id == tenant_id,
                    SourceChunkModel.course_id == course_id,
                    SourceChunkModel.id.in_(chunk_ids),
                    SourceFileModel.state == SourceFileState.EXTRACTED.value,
                )
                .order_by(SourceChunkModel.chunk_index.asc())
            ).all()
            return tuple(
                SourceChunk(
                    chunk_id=row.id,
                    tenant_id=row.tenant_id,
                    course_id=row.course_id,
                    file_id=row.file_id,
                    file_version=row.file_version,
                    chunk_index=row.chunk_index,
                    page_number=row.page_number,
                    section_path=row.section_path,
                    content=row.content,
                    content_hash=row.content_hash,
                )
                for row in rows
            )
