"""Opt-in HTTPS adapters for private quarantine storage, malware scanning, and extraction.

These adapters talk only to deployment-owned internal services. They do not implement an
antivirus engine or a parser sandbox in-process. The storage service must enforce private
bucket ACLs, KMS encryption and tenant/file binding; scanner/parser services must be deployed
with restricted network and resource policies. No adapter is enabled by default.
"""

from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import AsyncIterable
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from moallem.files.contracts import (
    ExtractedBlock,
    ExtractedDocument,
    ExtractionProfile,
    FileIntakeError,
    QuarantineStorage,
    ScanResult,
    ScanVerdict,
    SandboxedExtractor,
    is_private_storage_reference,
)

_MAX_SERVICE_RESPONSE_BYTES = 8 * 1024 * 1024


def _validate_service_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("internal service URL must be 1..2048 characters")
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "\\" in value
        or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError("internal service URL must be HTTPS without embedded credentials")
    return value.rstrip("/")


def build_mtls_client(
    *,
    ca_file: str,
    client_certificate: str,
    client_key: str,
    timeout_seconds: float,
) -> httpx.AsyncClient:
    """Create the required mTLS client for internal file services."""
    if not 0 < timeout_seconds <= 300:
        raise ValueError("service timeout must be > 0 and <= 300 seconds")
    context = ssl.create_default_context(cafile=ca_file)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(client_certificate, client_key)
    return httpx.AsyncClient(
        verify=context,
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=False,
        trust_env=False,
    )


async def _read_bounded(response: httpx.Response, maximum: int) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > maximum:
            raise FileIntakeError("FILE_SERVICE_RESPONSE_TOO_LARGE")
        body.extend(chunk)
    return bytes(body)


def _allowed_storage_reference(value: str, buckets: frozenset[str]) -> bool:
    if not is_private_storage_reference(value):
        return False
    parts = urlsplit(value)
    return parts.scheme in {"s3", "r2", "gs", "gcs", "az", "azure"} and parts.netloc in buckets


class HTTPQuarantineStorage(QuarantineStorage):
    """Private object-storage gateway adapter with canonical-key cleanup.

    The storage gateway contract is:
      PUT    /v1/quarantine/{tenant_id}/{file_id}  (streamed body)
      DELETE /v1/quarantine/{tenant_id}/{file_id}  (idempotent; resolves canonical key)
    A successful PUT returns JSON ``{"storage_ref":"s3://private-bucket/key"}``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient,
        allowed_buckets: frozenset[str],
        allowed_schemes: frozenset[str] = frozenset({"s3", "r2", "gs", "gcs", "az", "azure"}),
        timeout_seconds: float = 120.0,
    ) -> None:
        if not 0 < timeout_seconds <= 900:
            raise ValueError("storage timeout must be > 0 and <= 900 seconds")
        if not allowed_buckets or any(
            not bucket or bucket != bucket.strip() or "/" in bucket or ":" in bucket
            for bucket in allowed_buckets
        ):
            raise ValueError("an explicit non-empty private bucket allow-list is required")
        if not allowed_schemes or not allowed_schemes.issubset(
            {"s3", "r2", "gs", "gcs", "az", "azure"}
        ):
            raise ValueError("storage schemes must be explicitly selected from private schemes")
        self._base_url = _validate_service_url(base_url)
        self._client = client
        self._allowed_buckets = allowed_buckets
        self._allowed_schemes = allowed_schemes
        self._timeout_seconds = timeout_seconds

    def _allowed_reference(self, value: str) -> bool:
        if not _allowed_storage_reference(value, self._allowed_buckets):
            return False
        return urlsplit(value).scheme in self._allowed_schemes

    @staticmethod
    def _path(tenant_id: UUID, file_id: UUID) -> str:
        return f"/v1/quarantine/{tenant_id}/{file_id}"

    async def put_quarantined(
        self,
        *,
        tenant_id: UUID,
        file_id: UUID,
        chunks: AsyncIterable[bytes],
    ) -> str:
        async def checked() -> AsyncIterable[bytes]:
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise FileIntakeError("FILE_STREAM_INVALID")
                if chunk:
                    yield chunk

        try:
            async with self._client.stream(
                "PUT",
                f"{self._base_url}{self._path(tenant_id, file_id)}",
                content=checked(),
                headers={"Content-Type": "application/octet-stream"},
                timeout=self._timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code not in {200, 201, 202}:
                    raise FileIntakeError("QUARANTINE_STORAGE_WRITE_FAILED")
                raw = await _read_bounded(response, 16 * 1024)
            data = json.loads(raw)
            storage_ref = data.get("storage_ref") if isinstance(data, dict) else None
            if not isinstance(storage_ref, str) or not self._allowed_reference(storage_ref):
                raise FileIntakeError("QUARANTINE_STORAGE_INVALID_REF")
            return storage_ref
        except asyncio.CancelledError:
            try:
                await asyncio.shield(
                    self.discard_quarantined(
                        tenant_id=tenant_id, file_id=file_id, storage_ref=None
                    )
                )
            except Exception:
                # A cleanup failure is more actionable than hiding an orphan behind cancellation.
                raise FileIntakeError("QUARANTINE_CLEANUP_FAILED") from None
            raise
        except FileIntakeError:
            try:
                await self.discard_quarantined(
                    tenant_id=tenant_id, file_id=file_id, storage_ref=None
                )
            except Exception:
                raise FileIntakeError("QUARANTINE_CLEANUP_FAILED") from None
            raise
        except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
            try:
                await self.discard_quarantined(
                    tenant_id=tenant_id, file_id=file_id, storage_ref=None
                )
            except Exception:
                raise FileIntakeError("QUARANTINE_CLEANUP_FAILED") from None
            raise FileIntakeError("QUARANTINE_STORAGE_UNAVAILABLE") from None

    async def discard_quarantined(
        self, *, tenant_id: UUID, file_id: UUID, storage_ref: str | None
    ) -> None:
        if storage_ref is not None and not self._allowed_reference(storage_ref):
            raise FileIntakeError("QUARANTINE_STORAGE_INVALID_REF")
        try:
            async with self._client.stream(
                "DELETE",
                f"{self._base_url}{self._path(tenant_id, file_id)}",
                headers=(
                    {"X-Expected-Storage-Ref": storage_ref} if storage_ref is not None else {}
                ),
                timeout=self._timeout_seconds,
                follow_redirects=False,
            ) as response:
                status = response.status_code
        except httpx.HTTPError:
            raise FileIntakeError("QUARANTINE_CLEANUP_FAILED") from None
        if status not in {200, 202, 204, 404}:
            raise FileIntakeError("QUARANTINE_CLEANUP_FAILED")


class HTTPMalwareScanner:
    """Adapter to an internal scanner service (for example a ClamAV-backed service)."""

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient,
        expected_scanner_id: str,
        allowed_buckets: frozenset[str],
    ) -> None:
        if not expected_scanner_id or len(expected_scanner_id) > 128:
            raise ValueError("expected scanner ID must be 1..128 characters")
        if not allowed_buckets:
            raise ValueError("scanner requires an explicit storage bucket allow-list")
        self._base_url = _validate_service_url(base_url)
        self._client = client
        self._expected_scanner_id = expected_scanner_id
        self._allowed_buckets = allowed_buckets

    async def scan(
        self,
        storage_ref: str,
        *,
        tenant_id: UUID,
        file_id: UUID,
        timeout_seconds: float,
    ) -> ScanResult:
        if not _allowed_storage_reference(storage_ref, self._allowed_buckets):
            raise FileIntakeError("FILE_SCAN_STORAGE_REF_INVALID")
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/v1/scan",
                json={
                    "tenant_id": str(tenant_id),
                    "file_id": str(file_id),
                    "storage_ref": storage_ref,
                },
                headers={"Content-Type": "application/json"},
                timeout=timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise FileIntakeError("FILE_SCAN_UNAVAILABLE")
                raw = await _read_bounded(response, 16 * 1024)
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("invalid scanner response")
            result = ScanResult(
                verdict=ScanVerdict(data["verdict"]),
                scanner_id=data["scanner_id"],
                scanner_version=data["scanner_version"],
                safe_error_code=data.get("safe_error_code"),
            )
            if result.scanner_id != self._expected_scanner_id:
                return ScanResult(
                    verdict=ScanVerdict.UNKNOWN,
                    scanner_id=self._expected_scanner_id,
                    scanner_version="unknown",
                    safe_error_code="FILE_SCANNER_ID_MISMATCH",
                )
            return result
        except (httpx.HTTPError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return ScanResult(
                verdict=ScanVerdict.UNKNOWN,
                scanner_id="internal-scanner",
                scanner_version="unknown",
                safe_error_code="FILE_SCAN_UNAVAILABLE",
            )


class HTTPSandboxedExtractor(SandboxedExtractor):
    """Adapter to a separately deployed, network-restricted parser sandbox."""

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient,
        sandbox_policy_id: str,
        allowed_buckets: frozenset[str],
        ocr_enabled: bool = False,
    ) -> None:
        if not sandbox_policy_id or len(sandbox_policy_id) > 128:
            raise ValueError("sandbox policy ID must be 1..128 characters")
        if not allowed_buckets:
            raise ValueError("sandbox extractor requires an explicit storage bucket allow-list")
        self._base_url = _validate_service_url(base_url)
        self._client = client
        self._sandbox_policy_id = sandbox_policy_id
        self._allowed_buckets = allowed_buckets
        self._ocr_enabled = ocr_enabled

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
        if not _allowed_storage_reference(storage_ref, self._allowed_buckets):
            raise FileIntakeError("FILE_EXTRACT_STORAGE_REF_INVALID")
        allowed_mime_profiles = {
            ExtractionProfile.PDF_TEXT: {"application/pdf"},
            ExtractionProfile.OFFICE_TEXT: {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            },
            ExtractionProfile.OCR_ALLOWED: {
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            },
            ExtractionProfile.AUTO_SAFE: {
                "application/pdf",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            },
        }
        if declared_mime_type not in allowed_mime_profiles.get(profile, set()):
            raise FileIntakeError("FILE_PROFILE_MIME_MISMATCH")
        if profile is ExtractionProfile.OCR_ALLOWED and not self._ocr_enabled:
            raise FileIntakeError("OCR_POLICY_DISABLED")
        max_response = min(
            _MAX_SERVICE_RESPONSE_BYTES,
            max(64 * 1024, max_extracted_characters * 5 + max_pages * 512),
        )
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/v1/extract",
                json={
                    "tenant_id": str(tenant_id),
                    "file_id": str(file_id),
                    "storage_ref": storage_ref,
                    "profile": profile.value,
                    "declared_mime_type": declared_mime_type,
                    "max_pages": max_pages,
                    "max_extracted_characters": max_extracted_characters,
                    "sandbox_policy_id": self._sandbox_policy_id,
                    "network_access": False,
                    "shell_access": False,
                    "resource_limits_required": True,
                    "validate_pdf_structure": declared_mime_type == "application/pdf",
                    "validate_ooxml_package": declared_mime_type in {
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    },
                    "reject_archive_path_traversal": True,
                    "ocr_allowed": profile is ExtractionProfile.OCR_ALLOWED and self._ocr_enabled,
                },
                headers={"Content-Type": "application/json"},
                timeout=timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise FileIntakeError("FILE_EXTRACTION_SERVICE_FAILED")
                raw = await _read_bounded(response, max_response)
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get("blocks"), list):
                raise ValueError("invalid extraction response")
            blocks: list[ExtractedBlock] = []
            for block in data["blocks"]:
                if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                    raise ValueError("invalid extraction block")
                page_number = block.get("page_number")
                section_path = block.get("section_path")
                if page_number is not None and (
                    isinstance(page_number, bool) or not isinstance(page_number, int)
                ):
                    raise ValueError("invalid page number")
                if section_path is not None and not isinstance(section_path, str):
                    raise ValueError("invalid section path")
                blocks.append(
                    ExtractedBlock(
                        text=block["text"],
                        page_number=page_number,
                        section_path=section_path,
                    )
                )
            page_count = data.get("page_count")
            version = data.get("extractor_version")
            returned_policy_id = data.get("sandbox_policy_id")
            if (
                isinstance(page_count, bool)
                or not isinstance(page_count, int)
                or not isinstance(version, str)
                or returned_policy_id != self._sandbox_policy_id
            ):
                raise ValueError("invalid extraction metadata or sandbox policy mismatch")
            if page_count < 1 or page_count > max_pages:
                raise FileIntakeError("FILE_PAGE_LIMIT_EXCEEDED")
            if sum(len(block.text) for block in blocks) > max_extracted_characters:
                raise FileIntakeError("FILE_EXTRACTED_TEXT_LIMIT_EXCEEDED")
            return ExtractedDocument(
                extractor_version=version,
                page_count=page_count,
                blocks=tuple(blocks),
            )
        except FileIntakeError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            raise FileIntakeError("FILE_EXTRACTION_SERVICE_UNAVAILABLE") from None
