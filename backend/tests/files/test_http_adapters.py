from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import httpx
import pytest

from moallem.files.contracts import (
    ExtractionProfile,
    FileIntakeError,
    ScanVerdict,
)
from moallem.files.http_adapters import (
    HTTPMalwareScanner,
    HTTPQuarantineStorage,
    HTTPSandboxedExtractor,
)

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
FILE_ID = UUID("22222222-2222-4222-8222-222222222222")


def test_quarantine_storage_streams_bytes_and_returns_private_reference() -> None:
    received = bytearray()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            received.extend(request.content)
            return httpx.Response(201, json={"storage_ref": "s3://private-bucket/tenant/file"})
        raise AssertionError("unexpected request")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    storage = HTTPQuarantineStorage(
        base_url="https://storage.internal",
        client=client,
        allowed_buckets=frozenset({"private-bucket"}),
    )

    async def chunks():
        yield b"chunk-one"
        yield b"-chunk-two"

    ref = asyncio.run(
        storage.put_quarantined(tenant_id=uuid4(), file_id=uuid4(), chunks=chunks())
    )
    assert ref == "s3://private-bucket/tenant/file"
    assert bytes(received) == b"chunk-one-chunk-two"
    asyncio.run(client.aclose())


def test_invalid_storage_ref_triggers_canonical_cleanup_without_ref_header() -> None:
    calls: list[tuple[str, str, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            (
                request.method,
                request.url.path,
                request.headers.get("x-expected-storage-ref"),
            )
        )
        if request.method == "PUT":
            return httpx.Response(201, json={"storage_ref": "https://public.example/file"})
        return httpx.Response(204)

    tenant_id = uuid4()
    file_id = uuid4()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    storage = HTTPQuarantineStorage(
        base_url="https://storage.internal",
        client=client,
        allowed_buckets=frozenset({"private-bucket"}),
    )
    async def chunks():
        yield b"bytes"

    with pytest.raises(FileIntakeError) as exc:
        asyncio.run(
            storage.put_quarantined(tenant_id=tenant_id, file_id=file_id, chunks=chunks())
        )
    assert exc.value.code == "QUARANTINE_STORAGE_INVALID_REF"
    assert calls[1] == (
        "DELETE",
        f"/v1/quarantine/{tenant_id}/{file_id}",
        None,
    )
    asyncio.run(client.aclose())


def test_storage_transport_error_uses_canonical_cleanup() -> None:
    methods: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "PUT":
            raise httpx.ConnectError("secret network details", request=request)
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    storage = HTTPQuarantineStorage(
        base_url="https://storage.internal",
        client=client,
        allowed_buckets=frozenset({"private-bucket"}),
    )
    async def chunks():
        yield b"bytes"

    with pytest.raises(FileIntakeError) as exc:
        asyncio.run(storage.put_quarantined(tenant_id=uuid4(), file_id=uuid4(), chunks=chunks()))
    assert exc.value.code == "QUARANTINE_STORAGE_UNAVAILABLE"
    assert methods == ["PUT", "DELETE"]
    asyncio.run(client.aclose())


def test_http_scanner_maps_clean_verdict_and_invalid_service_response_to_unknown() -> None:
    responses = [
        httpx.Response(
            200,
            json={
                "verdict": "CLEAN",
                "scanner_id": "clamav-service",
                "scanner_version": "1.2.3",
            },
        ),
        httpx.Response(200, json={"verdict": "NOT_A_VERDICT", "scanner_id": "bad"}),
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tenant_id"] == str(TENANT_ID)
        assert payload["file_id"] == str(FILE_ID)
        assert payload["storage_ref"] == "s3://private-bucket/key"
        return responses.pop(0)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    scanner = HTTPMalwareScanner(
        base_url="https://scanner.internal",
        client=client,
        expected_scanner_id="clamav-service",
        allowed_buckets=frozenset({"private-bucket"}),
    )
    clean = asyncio.run(
        scanner.scan(
            "s3://private-bucket/key",
            tenant_id=TENANT_ID,
            file_id=FILE_ID,
            timeout_seconds=5,
        )
    )
    unknown = asyncio.run(
        scanner.scan(
            "s3://private-bucket/key",
            tenant_id=TENANT_ID,
            file_id=FILE_ID,
            timeout_seconds=5,
        )
    )
    assert clean.verdict is ScanVerdict.CLEAN
    assert unknown.verdict is ScanVerdict.UNKNOWN
    asyncio.run(client.aclose())


def test_sandbox_extractor_enforces_declared_limits_on_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tenant_id"] == str(TENANT_ID)
        assert payload["file_id"] == str(FILE_ID)
        assert payload["storage_ref"] == "s3://private-bucket/key"
        assert payload["network_access"] is False
        assert payload["max_pages"] == 2
        assert payload["shell_access"] is False
        assert payload["reject_archive_path_traversal"] is True
        assert payload["sandbox_policy_id"] == "pdf-ooxml-sandbox-v1"
        return httpx.Response(
            200,
            json={
                "extractor_version": "sandbox-2.0",
                "sandbox_policy_id": "pdf-ooxml-sandbox-v1",
                "page_count": 2,
                "blocks": [
                    {"text": "A short extracted block", "page_number": 1, "section_path": "1"}
                ],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    extractor = HTTPSandboxedExtractor(
        base_url="https://extractor.internal",
        client=client,
        sandbox_policy_id="pdf-ooxml-sandbox-v1",
        allowed_buckets=frozenset({"private-bucket"}),
    )
    result = asyncio.run(
        extractor.extract(
            "s3://private-bucket/key",
            tenant_id=TENANT_ID,
            file_id=FILE_ID,
            profile=ExtractionProfile.PDF_TEXT,
            declared_mime_type="application/pdf",
            max_pages=2,
            max_extracted_characters=100,
            timeout_seconds=5,
        )
    )
    assert result.page_count == 2
    assert result.extractor_version == "sandbox-2.0"
    assert result.blocks[0].text == "A short extracted block"
    asyncio.run(client.aclose())


def test_sandbox_extractor_rejects_output_above_character_limit() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "extractor_version": "sandbox-2.0",
                "sandbox_policy_id": "pdf-ooxml-sandbox-v1",
                "page_count": 1,
                "blocks": [{"text": "x" * 101, "page_number": 1, "section_path": None}],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    extractor = HTTPSandboxedExtractor(
        base_url="https://extractor.internal",
        client=client,
        sandbox_policy_id="pdf-ooxml-sandbox-v1",
        allowed_buckets=frozenset({"private-bucket"}),
    )
    with pytest.raises(FileIntakeError) as exc:
        asyncio.run(
            extractor.extract(
                "s3://private-bucket/key",
                tenant_id=TENANT_ID,
                file_id=FILE_ID,
                profile=ExtractionProfile.PDF_TEXT,
                declared_mime_type="application/pdf",
                max_pages=1,
                max_extracted_characters=100,
                timeout_seconds=5,
            )
        )
    assert exc.value.code == "FILE_EXTRACTED_TEXT_LIMIT_EXCEEDED"
    asyncio.run(client.aclose())


def test_file_service_endpoints_must_be_https() -> None:
    with pytest.raises(ValueError):
        HTTPQuarantineStorage(
            base_url="http://storage.internal",
            client=httpx.AsyncClient(),
            allowed_buckets=frozenset({"private-bucket"}),
        )


def test_scanner_and_extractor_reject_references_outside_the_approved_bucket() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    scanner = HTTPMalwareScanner(
        base_url="https://scanner.internal",
        client=client,
        expected_scanner_id="clamav-service",
        allowed_buckets=frozenset({"private-bucket"}),
    )
    extractor = HTTPSandboxedExtractor(
        base_url="https://extractor.internal",
        client=client,
        sandbox_policy_id="pdf-ooxml-sandbox-v1",
        allowed_buckets=frozenset({"private-bucket"}),
    )
    with pytest.raises(FileIntakeError):
        asyncio.run(
            scanner.scan(
                "s3://other-bucket/key",
                tenant_id=TENANT_ID,
                file_id=FILE_ID,
                timeout_seconds=5,
            )
        )
    with pytest.raises(FileIntakeError):
        asyncio.run(
            extractor.extract(
                "s3://other-bucket/key",
                tenant_id=TENANT_ID,
                file_id=FILE_ID,
                profile=ExtractionProfile.PDF_TEXT,
                declared_mime_type="application/pdf",
                max_pages=1,
                max_extracted_characters=100,
                timeout_seconds=5,
            )
        )
    assert calls == 0
    asyncio.run(client.aclose())


def test_scanner_id_mismatch_is_unknown_not_clean() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "verdict": "CLEAN",
                "scanner_id": "unapproved-scanner",
                "scanner_version": "1.0",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    scanner = HTTPMalwareScanner(
        base_url="https://scanner.internal",
        client=client,
        expected_scanner_id="clamav-approved",
        allowed_buckets=frozenset({"private-bucket"}),
    )
    result = asyncio.run(
        scanner.scan(
            "s3://private-bucket/key",
            tenant_id=TENANT_ID,
            file_id=FILE_ID,
            timeout_seconds=5,
        )
    )
    assert result.verdict is ScanVerdict.UNKNOWN
    assert result.safe_error_code == "FILE_SCANNER_ID_MISMATCH"
    asyncio.run(client.aclose())


def test_ocr_profile_is_rejected_by_default_extractor_adapter() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("OCR must be rejected before network dispatch")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    extractor = HTTPSandboxedExtractor(
        base_url="https://extractor.internal",
        client=client,
        sandbox_policy_id="pdf-ooxml-sandbox-v1",
        allowed_buckets=frozenset({"private-bucket"}),
    )
    with pytest.raises(FileIntakeError) as exc:
        asyncio.run(
            extractor.extract(
                "s3://private-bucket/key",
                tenant_id=TENANT_ID,
                file_id=FILE_ID,
                profile=ExtractionProfile.OCR_ALLOWED,
                declared_mime_type="application/pdf",
                max_pages=1,
                max_extracted_characters=100,
                timeout_seconds=5,
            )
        )
    assert exc.value.code == "OCR_POLICY_DISABLED"
    asyncio.run(client.aclose())
