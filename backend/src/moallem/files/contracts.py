"""Provider-neutral contracts for quarantined files and source provenance."""

from __future__ import annotations

from collections.abc import AsyncIterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID


_PRIVATE_STORAGE_SCHEMES = frozenset({"s3", "gs", "gcs", "az", "azure", "r2"})


class ExtractionProfile(StrEnum):
    PDF_TEXT = "PDF_TEXT"
    OFFICE_TEXT = "OFFICE_TEXT"
    OCR_ALLOWED = "OCR_ALLOWED"
    AUTO_SAFE = "AUTO_SAFE"


class ScanVerdict(StrEnum):
    CLEAN = "CLEAN"
    MALICIOUS = "MALICIOUS"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class SourceFileState(StrEnum):
    QUARANTINED = "QUARANTINED"
    CLEAN = "CLEAN"
    REJECTED = "REJECTED"
    EXTRACTED = "EXTRACTED"
    FAILED = "FAILED"


def is_private_storage_reference(value: str) -> bool:
    """Reject public/signed URLs and malformed values at the storage boundary.

    Storage references are opaque identifiers, not user-facing URLs. Vendor-specific
    private schemes (for example ``s3://``) remain possible; the adapter must still
    enforce private ACLs, encryption, and tenant/file binding.
    """
    if not isinstance(value, str) or not value or len(value) > 512:
        return False
    if value != value.strip() or any(char.isspace() for char in value):
        return False
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    scheme = parts.scheme.lower()
    if parts.query or parts.fragment or parts.username or parts.password:
        return False
    if scheme and (scheme not in _PRIVATE_STORAGE_SCHEMES or not parts.netloc):
        return False
    if not scheme and parts.netloc:
        return False
    return True


@dataclass(frozen=True, slots=True)
class FileIntakePolicy:
    """Explicit per-environment bounds; no implicit file size/page/time defaults."""

    max_upload_bytes: int
    max_pages: int
    max_extracted_characters: int
    max_chunk_characters: int
    max_chunks: int
    timeout_seconds: float
    allowed_mime_types: frozenset[str]
    ocr_enabled: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("max_upload_bytes", self.max_upload_bytes),
            ("max_pages", self.max_pages),
            ("max_extracted_characters", self.max_extracted_characters),
            ("max_chunk_characters", self.max_chunk_characters),
            ("max_chunks", self.max_chunks),
        ):
            if value < 1:
                raise ValueError(f"{name} must be positive")
        if self.timeout_seconds <= 0 or not float(self.timeout_seconds) < float("inf"):
            raise ValueError("timeout_seconds must be finite and positive")
        supported_mime_types = {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        if not self.allowed_mime_types or not self.allowed_mime_types.issubset(
            supported_mime_types
        ):
            raise ValueError("allowed_mime_types must contain only explicitly supported MIME types")
        if self.max_chunk_characters > self.max_extracted_characters:
            raise ValueError("max_chunk_characters cannot exceed max_extracted_characters")


@dataclass(frozen=True, slots=True)
class FileUpload:
    file_id: UUID
    tenant_id: UUID
    course_id: str
    uploaded_by_membership_id: UUID
    task_id: UUID | None
    version: int
    original_filename: str
    declared_mime_type: str
    extraction_profile: ExtractionProfile


@dataclass(frozen=True, slots=True)
class ScanResult:
    verdict: ScanVerdict
    scanner_id: str
    scanner_version: str
    safe_error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.scanner_id or len(self.scanner_id) > 128:
            raise ValueError("scanner_id must be 1..128 characters")
        if not self.scanner_version or len(self.scanner_version) > 128:
            raise ValueError("scanner_version must be 1..128 characters")
        if self.safe_error_code is not None and (
            not self.safe_error_code
            or len(self.safe_error_code) > 64
            or not self.safe_error_code.replace("_", "").isalnum()
            or not self.safe_error_code.isascii()
            or self.safe_error_code.upper() != self.safe_error_code
        ):
            raise ValueError("safe_error_code must be uppercase alphanumeric")


@dataclass(frozen=True, slots=True)
class ExtractedBlock:
    text: str
    page_number: int | None
    section_path: str | None


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    extractor_version: str
    page_count: int
    blocks: tuple[ExtractedBlock, ...]


@dataclass(frozen=True, slots=True)
class SourceFileRegistration:
    upload: FileUpload
    detected_mime_type: str
    sha256: str
    byte_size: int
    storage_ref: str


@dataclass(frozen=True, slots=True)
class PersistedChunkInput:
    chunk_id: UUID
    chunk_index: int
    page_number: int | None
    section_path: str | None
    content: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class SourceChunk:
    chunk_id: UUID
    tenant_id: UUID
    course_id: str
    file_id: UUID
    file_version: int
    chunk_index: int
    page_number: int | None
    section_path: str | None
    content: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class FileIntakeResult:
    file_id: UUID
    state: SourceFileState
    sha256: str
    byte_size: int
    chunk_refs: tuple[UUID, ...]
    extractor_version: str | None
    safe_error_code: str | None = None


class QuarantineStorage(Protocol):
    async def put_quarantined(
        self,
        *,
        tenant_id: UUID,
        file_id: UUID,
        chunks: AsyncIterable[bytes],
    ) -> str:
        """Atomically write a private quarantine object; abort partial multipart writes.

        The implementation must use a non-public bucket/prefix, encryption at rest, and
        object-level tenant binding. The returned reference must not be a public URL.
        Incomplete multipart uploads must be aborted on any exception or cancellation.
        """

    async def discard_quarantined(
        self, *, tenant_id: UUID, file_id: UUID, storage_ref: str | None
    ) -> None:
        """Idempotently remove a completed quarantine object that could not be registered.

        When ``storage_ref`` is ``None``, the adapter must resolve the object's canonical
        key from its own tenant/file mapping. This is the only permitted cleanup path for
        an invalid or untrusted reference returned by ``put_quarantined``. Implementations
        must verify the tenant/file binding before deletion and must never treat a supplied
        public URL as an object key. A failed deletion must be surfaced for orphan
        reconciliation; it must not silently report success.
        """


class MalwareScanner(Protocol):
    """Scan only after authorizing the object against the supplied tenant/file identity."""

    async def scan(
        self,
        storage_ref: str,
        *,
        tenant_id: UUID,
        file_id: UUID,
        timeout_seconds: float,
    ) -> ScanResult: ...


class SandboxedExtractor(Protocol):
    async def extract(
        self,
        storage_ref: str,
        *,
        tenant_id: UUID,
        file_id: UUID,
        profile: ExtractionProfile,
        declared_mime_type: str,
        max_pages: int,
        max_extracted_characters: int,
        timeout_seconds: float,
    ) -> ExtractedDocument:
        """Parse in a network-isolated, resource-limited sandbox.

        The sandbox service must independently verify that ``storage_ref`` resolves to the
        object registered for the supplied ``tenant_id`` and ``file_id`` before reading it.
        A storage reference alone is not an authorization token. The implementation must
        validate the complete container, not just its magic bytes:
        for OOXML this includes `[Content_Types].xml`, the expected document/presentation
        relationship parts, path traversal rejection, symlink rejection, entry-count and
        decompression-ratio limits, and bounded total uncompressed bytes. PDF structure and
        embedded object limits must also be checked inside the sandbox. Network and shell
        access must be disabled. OCR is permitted only when the caller selected OCR_ALLOWED
        and the deployment's explicit OCR policy is enabled.
        """


class SourceFileRepository(Protocol):
    def create_quarantined(self, record: SourceFileRegistration) -> None: ...

    def reject_before_scan(self, upload: FileUpload, safe_error_code: str) -> None: ...

    def record_scan_result(self, upload: FileUpload, result: ScanResult) -> None: ...

    def mark_failed(self, upload: FileUpload, safe_error_code: str) -> None: ...

    def persist_extracted(
        self,
        upload: FileUpload,
        *,
        expected_sha256: str,
        extractor_version: str,
        page_count: int,
        chunks: Sequence[PersistedChunkInput],
    ) -> None: ...


class FileIntakeError(RuntimeError):
    def __init__(self, code: str) -> None:
        if (
            not code
            or len(code) > 64
            or not code.isascii()
            or not code.replace("_", "").isalnum()
        ):
            raise ValueError("file intake errors require a safe error code")
        super().__init__(code)
        self.code = code
