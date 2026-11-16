"""Canonical JSON + SHA-256 (v2.4 Reliability Addendum §3; closes GAP-DATA-001 as a PROPOSAL).

Pipeline: normalize every string value AND object key to Unicode NFC -> RFC 8785 (JCS)
serialization -> SHA-256 hex.

Design decisions that go beyond the spec text (need owner sign-off, see docs/PHASE2_STATUS.md):
  * Floats are REJECTED. RFC 8785 requires ECMAScript number formatting, which Python does not
    reproduce for every double. Hashed payloads must carry integers (|n| <= 2**53-1) or decimal
    strings. This removes the cross-language number-encoding risk entirely.
  * Timestamps must be RFC 3339 UTC strings supplied by the caller; this module never formats them.
  * Keys that collide after NFC normalization are rejected (silent merge would change meaning).
"""

import hashlib
import unicodedata
from typing import Any

from moallem.domain.errors import NotCanonicalizable

MAX_SAFE_INT = 2**53 - 1
_ESC = {0x08: "\\b", 0x09: "\\t", 0x0A: "\\n", 0x0C: "\\f", 0x0D: "\\r", 0x22: '\\"', 0x5C: "\\\\"}


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _quote(s: str) -> str:
    out = ['"']
    for ch in s:
        cp = ord(ch)
        if cp in _ESC:
            out.append(_ESC[cp])
        elif cp < 0x20:
            out.append(f"\\u{cp:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INT:
            raise NotCanonicalizable("integer outside the I-JSON safe range")
        return str(value)
    if isinstance(value, float):
        raise NotCanonicalizable("floats are not allowed in hashed payloads; use int or string")
    if isinstance(value, str):
        return _quote(_nfc(value))
    if isinstance(value, list | tuple):
        return "[" + ",".join(_serialize(v) for v in value) + "]"
    if isinstance(value, dict):
        items: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise NotCanonicalizable("object keys must be strings")
            nk = _nfc(k)
            if nk in items:
                raise NotCanonicalizable("duplicate object key after NFC normalization")
            items[nk] = v
        # JCS sorts keys by UTF-16 code units; big-endian bytes compare identically.
        ordered = sorted(items, key=lambda k: k.encode("utf-16-be", "surrogatepass"))
        return "{" + ",".join(f"{_quote(k)}:{_serialize(items[k])}" for k in ordered) + "}"
    raise NotCanonicalizable(f"unsupported type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return _serialize(value)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def request_fingerprint(
    *,
    method: str,
    route: str,
    tenant_id: str,
    actor_membership_id: str,
    operation_code: str,
    payload: Any,
) -> str:
    """Idempotency request hash. Excludes request/trace IDs by construction (not parameters)."""
    return canonical_hash(
        {
            "method": method.upper(),
            "route": route,
            "tenant_id": tenant_id,
            "actor_membership_id": actor_membership_id,
            "operation_code": operation_code,
            "payload": payload,
        }
    )
