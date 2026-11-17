"""Fail-closed quarantine → malware scan → sandbox extraction → provenance pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import AsyncIterable
from uuid import uuid4

from moallem.files.contracts import (
    ExtractionProfile,
    ExtractedDocument,
    FileIntakeError,
    FileIntakePolicy,
    FileIntakeResult,
    FileUpload,
    MalwareScanner,
    PersistedChunkInput,
    QuarantineStorage,
    ScanVerdict,
    SandboxedExtractor,
    ScanResult,
    SourceFileRegistration,
    SourceFileRepository,
    SourceFileState,
    is_private_storage_reference,
)

_PDF_MIME = "application/pdf"
_OFFICE_MIMES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
)
_EXTENSION_MIME = {
    ".pdf": _PDF_MIME,
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
_FILE_NAME_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class FileIntakeService:
    def __init__(
        self,
        *,
        storage: QuarantineStorage,
        scanner: MalwareScanner,
        extractor: SandboxedExtractor,
        repository: SourceFileRepository,
        policy: FileIntakePolicy,
    ) -> None:
        self._storage = storage
        self._scanner = scanner
        self._extractor = extractor
        self._repository = repository
        self._policy = policy

    async def ingest(self, upload: FileUpload, content: AsyncIterable[bytes]) -> FileIntakeResult:
        if len(upload.declared_mime_type) > 160:
            raise FileIntakeError("FILE_MIME_INVALID")
        declared_mime = upload.declared_mime_type.split(";", 1)[0].strip().lower()
        self._validate_metadata(upload, declared_mime)

        digest = hashlib.sha256()
        prefix = bytearray()
        total_bytes = 0
        fully_consumed = False

        async def checked_stream() -> AsyncIterable[bytes]:
            nonlocal total_bytes, fully_consumed
            async for block in content:
                if not isinstance(block, bytes):
                    raise FileIntakeError("FILE_STREAM_INVALID")
                if not block:
                    continue
                total_bytes += len(block)
                if total_bytes > self._policy.max_upload_bytes:
                    raise FileIntakeError("FILE_TOO_LARGE")
                digest.update(block)
                if len(prefix) < 16:
                    prefix.extend(block[: 16 - len(prefix)])
                yield block
            fully_consumed = True

        try:
            async with asyncio.timeout(self._policy.timeout_seconds):
                storage_ref = await self._storage.put_quarantined(
                    tenant_id=upload.tenant_id,
                    file_id=upload.file_id,
                    chunks=checked_stream(),
                )
        except TimeoutError:
            raise FileIntakeError("FILE_UPLOAD_TIMEOUT") from None
        if not fully_consumed or total_bytes < 1:
            if storage_ref:
                safe_ref = storage_ref if is_private_storage_reference(storage_ref) else None
                await self._discard_unregistered_object(upload, safe_ref)
            raise FileIntakeError("FILE_UPLOAD_INCOMPLETE")
        if not is_private_storage_reference(storage_ref):
            # Never pass a public/malformed adapter response to deletion as an object key.
            # The storage adapter must resolve the canonical key from tenant_id + file_id.
            await self._discard_unregistered_object(upload, None)
            raise FileIntakeError("QUARANTINE_STORAGE_INVALID_REF")

        detected_mime = self._detect_mime(bytes(prefix))
        registration = SourceFileRegistration(
            upload=upload,
            detected_mime_type=detected_mime,
            sha256=digest.hexdigest(),
            byte_size=total_bytes,
            storage_ref=storage_ref,
        )
        # Register before scanning so a crash cannot leave a successfully uploaded object with
        # no durable tenant/file metadata. The object itself remains private and quarantined.
        try:
            self._repository.create_quarantined(registration)
        except Exception:
            # The object is durable at this point. Compensate if metadata registration fails;
            # otherwise an untracked tenant object would remain outside retention accounting.
            await self._discard_unregistered_object(upload, storage_ref)
            raise FileIntakeError("FILE_REGISTRATION_FAILED") from None

        if not self._signature_matches(declared_mime, detected_mime):
            self._repository.reject_before_scan(upload, "FILE_SIGNATURE_MISMATCH")
            return FileIntakeResult(
                file_id=upload.file_id,
                state=SourceFileState.REJECTED,
                sha256=registration.sha256,
                byte_size=registration.byte_size,
                chunk_refs=(),
                extractor_version=None,
                safe_error_code="FILE_SIGNATURE_MISMATCH",
            )

        try:
            async with asyncio.timeout(self._policy.timeout_seconds):
                scan = await self._scanner.scan(
                    storage_ref,
                    tenant_id=upload.tenant_id,
                    file_id=upload.file_id,
                    timeout_seconds=self._policy.timeout_seconds,
                )
        except TimeoutError:
            scan = _unknown_scan("FILE_SCAN_TIMEOUT")
        except Exception:
            scan = _unknown_scan("FILE_SCAN_UNAVAILABLE")

        self._repository.record_scan_result(upload, scan)
        if scan.verdict is not ScanVerdict.CLEAN:
            state = (
                SourceFileState.REJECTED
                if scan.verdict is ScanVerdict.MALICIOUS
                else SourceFileState.QUARANTINED
            )
            return FileIntakeResult(
                file_id=upload.file_id,
                state=state,
                sha256=registration.sha256,
                byte_size=registration.byte_size,
                chunk_refs=(),
                extractor_version=None,
                safe_error_code=scan.safe_error_code,
            )

        try:
            async with asyncio.timeout(self._policy.timeout_seconds):
                extracted = await self._extractor.extract(
                    storage_ref,
                    tenant_id=upload.tenant_id,
                    file_id=upload.file_id,
                    profile=upload.extraction_profile,
                    declared_mime_type=declared_mime,
                    max_pages=self._policy.max_pages,
                    max_extracted_characters=self._policy.max_extracted_characters,
                    timeout_seconds=self._policy.timeout_seconds,
                )
            chunks = self._make_chunks(upload, extracted)
            self._repository.persist_extracted(
                upload,
                expected_sha256=registration.sha256,
                extractor_version=extracted.extractor_version,
                page_count=extracted.page_count,
                chunks=chunks,
            )
        except TimeoutError:
            self._repository.mark_failed(upload, "FILE_EXTRACTION_TIMEOUT")
            raise FileIntakeError("FILE_EXTRACTION_TIMEOUT") from None
        except FileIntakeError as exc:
            self._repository.mark_failed(upload, exc.code)
            raise
        except Exception:
            self._repository.mark_failed(upload, "FILE_EXTRACTION_FAILED")
            raise FileIntakeError("FILE_EXTRACTION_FAILED") from None

        return FileIntakeResult(
            file_id=upload.file_id,
            state=SourceFileState.EXTRACTED,
            sha256=registration.sha256,
            byte_size=registration.byte_size,
            chunk_refs=tuple(chunk.chunk_id for chunk in chunks),
            extractor_version=extracted.extractor_version,
        )

    async def _discard_unregistered_object(
        self, upload: FileUpload, storage_ref: str | None
    ) -> None:
        if storage_ref is not None and not is_private_storage_reference(storage_ref):
            raise FileIntakeError("QUARANTINE_CLEANUP_FAILED")
        try:
            await self._storage.discard_quarantined(
                tenant_id=upload.tenant_id,
                file_id=upload.file_id,
                storage_ref=storage_ref,
            )
        except Exception:
            raise FileIntakeError("QUARANTINE_CLEANUP_FAILED") from None

    def _validate_metadata(self, upload: FileUpload, declared_mime: str) -> None:
        if not upload.course_id or len(upload.course_id) > 128:
            raise FileIntakeError("FILE_COURSE_SCOPE_INVALID")
        if upload.version < 1:
            raise FileIntakeError("FILE_VERSION_INVALID")
        name = upload.original_filename
        if (
            not name
            or name != name.strip()
            or len(name) > 255
            or "/" in name
            or "\\" in name
            or _FILE_NAME_CONTROL.search(name)
            or name in {".", ".."}
        ):
            raise FileIntakeError("FILE_NAME_INVALID")
        if declared_mime not in self._policy.allowed_mime_types:
            raise FileIntakeError("FILE_MIME_NOT_ALLOWED")
        extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        expected = _EXTENSION_MIME.get(f".{extension}")
        if expected != declared_mime:
            raise FileIntakeError("FILE_EXTENSION_MIME_MISMATCH")
        if (
            upload.extraction_profile is ExtractionProfile.OCR_ALLOWED
            and not self._policy.ocr_enabled
        ):
            raise FileIntakeError("OCR_POLICY_DISABLED")
        if upload.extraction_profile is ExtractionProfile.PDF_TEXT and declared_mime != _PDF_MIME:
            raise FileIntakeError("FILE_PROFILE_MIME_MISMATCH")
        if (
            upload.extraction_profile is ExtractionProfile.OFFICE_TEXT
            and declared_mime not in _OFFICE_MIMES
        ):
            raise FileIntakeError("FILE_PROFILE_MIME_MISMATCH")

    @staticmethod
    def _detect_mime(prefix: bytes) -> str:
        if prefix.startswith(b"%PDF-"):
            return _PDF_MIME
        if prefix.startswith(b"PK\x03\x04"):
            # DOCX/PPTX are ZIP containers. The sandboxed extractor must inspect package
            # members before parsing; a ZIP signature alone never establishes Office type.
            return "application/zip"
        return "application/octet-stream"

    @staticmethod
    def _signature_matches(declared_mime: str, detected_mime: str) -> bool:
        return (declared_mime == _PDF_MIME and detected_mime == _PDF_MIME) or (
            declared_mime in _OFFICE_MIMES and detected_mime == "application/zip"
        )

    def _make_chunks(
        self,
        upload: FileUpload,
        extracted: ExtractedDocument,
    ) -> list[PersistedChunkInput]:
        if not extracted.extractor_version or len(extracted.extractor_version) > 128:
            raise FileIntakeError("FILE_EXTRACTOR_VERSION_INVALID")
        if extracted.page_count < 1 or extracted.page_count > self._policy.max_pages:
            raise FileIntakeError("FILE_PAGE_LIMIT_EXCEEDED")
        total_characters = sum(len(block.text) for block in extracted.blocks)
        if total_characters > self._policy.max_extracted_characters:
            raise FileIntakeError("FILE_EXTRACTED_TEXT_LIMIT_EXCEEDED")

        result: list[PersistedChunkInput] = []
        for block in extracted.blocks:
            text = block.text.strip()
            if not text:
                continue
            if block.page_number is not None and not 1 <= block.page_number <= extracted.page_count:
                raise FileIntakeError("FILE_PROVENANCE_PAGE_INVALID")
            if block.section_path is not None and len(block.section_path) > 1024:
                raise FileIntakeError("FILE_PROVENANCE_SECTION_INVALID")
            for offset in range(0, len(text), self._policy.max_chunk_characters):
                piece = text[offset : offset + self._policy.max_chunk_characters]
                if len(result) >= self._policy.max_chunks:
                    raise FileIntakeError("FILE_CHUNK_LIMIT_EXCEEDED")
                result.append(
                    PersistedChunkInput(
                        chunk_id=uuid4(),
                        chunk_index=len(result),
                        page_number=block.page_number,
                        section_path=block.section_path,
                        content=piece,
                        content_hash=hashlib.sha256(piece.encode("utf-8")).hexdigest(),
                    )
                )
        if not result:
            raise FileIntakeError("FILE_NO_EXTRACTABLE_TEXT")
        return result


def _unknown_scan(code: str) -> ScanResult:
    from moallem.files.contracts import ScanResult

    return ScanResult(
        verdict=ScanVerdict.UNKNOWN,
        scanner_id="unavailable",
        scanner_version="unknown",
        safe_error_code=code,
    )
