from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from moallem.ai.contracts import ProviderIdentity
from moallem.ai.usage import UsageLedgerCompletion, UsageLedgerStart
from moallem.files.contracts import (
    ExtractionProfile,
    FileUpload,
    PersistedChunkInput,
    SourceFileRegistration,
)
from moallem.persistence.ai_usage_repository import PostgresAIUsageLedgerRepository
from moallem.persistence.source_file_repository import (
    PostgresSourceFileRepository,
    SourceFileStateConflict,
)
from moallem.persistence.models import Base


def test_p5_tables_are_part_of_sqlalchemy_metadata() -> None:
    required = {
        "ai_usage_ledger",
        "source_files",
        "source_chunks",
        "ai_usage_source_refs",
    }
    assert required.issubset(Base.metadata.tables)


def test_ai_usage_ledger_is_tenant_scoped_and_has_budget_accounting() -> None:
    table = Base.metadata.tables["ai_usage_ledger"]
    assert {"tenant_id", "task_id", "invocation_id", "request_hash"}.issubset(
        table.columns.keys()
    )
    assert {"budget_reservation_ref", "budget_reserved_amount", "budget_currency"}.issubset(
        table.columns.keys()
    )
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("tenant_id", "task_id", "invocation_id") in unique_columns
    foreign_key_names = {constraint.name for constraint in table.foreign_key_constraints}
    assert "fk_ai_usage_task_course" in foreign_key_names
    assert "fk_ai_usage_actor_membership" in foreign_key_names


def test_source_chunk_fk_prevents_cross_tenant_course_file_binding() -> None:
    table = Base.metadata.tables["source_chunks"]
    provenance_fk = next(
        constraint
        for constraint in table.foreign_key_constraints
        if constraint.name == "fk_source_chunks_file_provenance"
    )
    local_columns = tuple(element.parent.name for element in provenance_fk.elements)
    remote_columns = tuple(element.column.name for element in provenance_fk.elements)
    assert local_columns == ("tenant_id", "file_id", "file_version", "course_id")
    assert remote_columns == ("tenant_id", "id", "version", "course_id")


def test_ai_usage_source_reference_fk_binds_source_and_usage_to_same_tenant() -> None:
    table = Base.metadata.tables["ai_usage_source_refs"]
    fks = {constraint.name: constraint for constraint in table.foreign_key_constraints}
    assert set(fks) == {
        "fk_ai_usage_source_refs_usage",
        "fk_ai_usage_source_refs_task_course",
        "fk_ai_usage_source_refs_chunk_course",
    }
    chunk_fk = fks["fk_ai_usage_source_refs_chunk_course"]
    assert tuple(element.parent.name for element in chunk_fk.elements) == (
        "tenant_id",
        "source_chunk_id",
        "course_id",
    )
    assert tuple(element.column.name for element in chunk_fk.elements) == (
        "tenant_id",
        "id",
        "course_id",
    )


def test_source_chunk_course_id_matches_parent_scope_width() -> None:
    column = Base.metadata.tables["source_chunks"].columns["course_id"]
    assert column.type.length == 128


def test_p5_hash_and_private_storage_constraints_exist() -> None:
    expected = {
        "ai_usage_ledger": {
            "ck_ai_usage_request_hash_hex",
            "ck_ai_usage_response_hash_hex",
        },
        "source_files": {
            "ck_source_files_sha256_hex",
            "ck_source_files_private_storage_ref",
        },
        "source_chunks": {"ck_source_chunks_content_hash_hex"},
    }
    for table_name, names in expected.items():
        actual = {constraint.name for constraint in Base.metadata.tables[table_name].constraints}
        assert names.issubset(actual)
    storage_check = next(
        constraint
        for constraint in Base.metadata.tables["source_files"].constraints
        if constraint.name == "ck_source_files_private_storage_ref"
    )
    assert "s3|gs|gcs|az|azure|r2" in str(storage_check.sqltext)
    assert "storage_ref !~ '[?#]'" in str(storage_check.sqltext)
    assert "[^/@?#]+" in str(storage_check.sqltext)


def test_p5_tables_compile_for_postgresql_dialect() -> None:
    for table_name in (
        "ai_usage_ledger",
        "source_files",
        "source_chunks",
        "ai_usage_source_refs",
    ):
        sql = str(
            CreateTable(Base.metadata.tables[table_name]).compile(
                dialect=postgresql.dialect()
            )
        )
        assert "CREATE TABLE" in sql
        assert "tenant_id" in sql


class _NoDatabaseAccess:
    def begin(self):
        raise AssertionError("repository opened a database transaction for invalid provenance")


def _source_upload() -> FileUpload:
    return FileUpload(
        file_id=uuid4(),
        tenant_id=uuid4(),
        course_id="course-1",
        uploaded_by_membership_id=uuid4(),
        task_id=None,
        version=1,
        original_filename="lesson.pdf",
        declared_mime_type="application/pdf",
        extraction_profile=ExtractionProfile.PDF_TEXT,
    )


def _chunk(*, index: int = 0, content: str = "verified text", page: int | None = 1):
    return PersistedChunkInput(
        chunk_id=uuid4(),
        chunk_index=index,
        page_number=page,
        section_path="Chapter 1",
        content=content,
        content_hash=sha256(content.encode("utf-8")).hexdigest(),
    )


@pytest.mark.parametrize(
    ("chunks", "page_count", "expected_code"),
    [
        (
            [
                PersistedChunkInput(
                    chunk_id=uuid4(),
                    chunk_index=0,
                    page_number=1,
                    section_path="Chapter 1",
                    content="tampered",
                    content_hash=sha256(b"original").hexdigest(),
                )
            ],
            1,
            "chunk content hash",
        ),
        ([_chunk(index=1)], 1, "contiguous"),
        ([_chunk(page=2)], 1, "outside extracted document"),
        ([_chunk(content="  ")], 1, "must not be empty"),
        ([], 1, "no provenance chunks"),
    ],
)
def test_repository_rejects_untrusted_extractor_provenance_before_database(
    chunks, page_count, expected_code
) -> None:
    repository = PostgresSourceFileRepository(_NoDatabaseAccess())  # type: ignore[arg-type]
    with pytest.raises(SourceFileStateConflict, match=expected_code):
        repository.persist_extracted(
            _source_upload(),
            expected_sha256="a" * 64,
            extractor_version="sandbox-v1",
            page_count=page_count,
            chunks=chunks,
        )


def test_repository_rejects_public_quarantine_url_before_database() -> None:
    upload = _source_upload()
    record = SourceFileRegistration(
        upload=upload,
        detected_mime_type="application/pdf",
        sha256=sha256(b"source").hexdigest(),
        byte_size=6,
        storage_ref="https://public.example/file.pdf?signature=secret",
    )
    repository = PostgresSourceFileRepository(_NoDatabaseAccess())  # type: ignore[arg-type]
    with pytest.raises(SourceFileStateConflict, match="private opaque"):
        repository.create_quarantined(record)


def test_repository_rejects_non_hex_source_hash_before_database() -> None:
    upload = _source_upload()
    record = SourceFileRegistration(
        upload=upload,
        detected_mime_type="application/pdf",
        sha256="z" * 64,
        byte_size=6,
        storage_ref="private-quarantine/tenant/file",
    )
    repository = PostgresSourceFileRepository(_NoDatabaseAccess())  # type: ignore[arg-type]
    with pytest.raises(SourceFileStateConflict, match="SHA-256"):
        repository.create_quarantined(record)



@pytest.mark.parametrize(
    "filename",
    ["", " lesson.pdf", "lesson.pdf ", "../lesson.pdf", "\\lesson.pdf", "bad\x00name.pdf"],
)
def test_repository_rejects_unsafe_filename_before_database(filename: str) -> None:
    upload = _source_upload()
    upload = FileUpload(
        file_id=upload.file_id,
        tenant_id=upload.tenant_id,
        course_id=upload.course_id,
        uploaded_by_membership_id=upload.uploaded_by_membership_id,
        task_id=upload.task_id,
        version=upload.version,
        original_filename=filename,
        declared_mime_type=upload.declared_mime_type,
        extraction_profile=upload.extraction_profile,
    )
    record = SourceFileRegistration(
        upload=upload,
        detected_mime_type="application/pdf",
        sha256=sha256(b"source").hexdigest(),
        byte_size=6,
        storage_ref="private-quarantine/tenant/file",
    )
    repository = PostgresSourceFileRepository(_NoDatabaseAccess())  # type: ignore[arg-type]
    with pytest.raises(SourceFileStateConflict, match="metadata"):
        repository.create_quarantined(record)

def _usage_start(request_hash: str) -> UsageLedgerStart:
    return UsageLedgerStart(
        tenant_id=uuid4(),
        task_id=uuid4(),
        course_id="course-1",
        actor_membership_id=uuid4(),
        invocation_id=uuid4(),
        provider=ProviderIdentity("provider", "model", "version", "region"),
        prompt_version="prompt-v1",
        request_hash=request_hash,
        permit_ref="permit",
        privacy_policy_ref="privacy",
        budget_reservation_ref="reservation",
        budget_reserved_amount=Decimal("1.000000000000"),
        budget_currency="USD",
        pricing_version="pricing-v1",
        source_refs=(),
    )


def test_ai_usage_repository_rejects_invalid_request_hash_before_database() -> None:
    repository = PostgresAIUsageLedgerRepository(_NoDatabaseAccess())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        repository.begin(_usage_start("g" * 64))


def test_ai_usage_repository_rejects_invalid_response_hash_before_database() -> None:
    repository = PostgresAIUsageLedgerRepository(_NoDatabaseAccess())  # type: ignore[arg-type]
    record = UsageLedgerCompletion(
        tenant_id=uuid4(),
        task_id=uuid4(),
        invocation_id=uuid4(),
        response_hash="g" * 64,
        input_tokens=1,
        output_tokens=1,
        cost_amount=Decimal("0.01"),
        currency="USD",
    )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        repository.complete(record)
