"""AES-256-GCM envelope for sensitive values using an explicitly supplied development key.

Production key custody remains blocked on a KMS/Secret Manager decision. Callers must provide
tenant and secret-reference context as associated data to prevent ciphertext relocation.
"""

import base64
import binascii
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_BYTES = 32
_NONCE_BYTES = 12
_VERSION = "m1"


class EncryptionNotConfigured(RuntimeError):
    """Raised when an encryption operation is attempted without a configured key."""


class EncryptedValueInvalid(ValueError):
    """Raised for malformed, unauthenticated, or context-mismatched ciphertext."""


def decode_aes256_key(encoded: str | None) -> bytes:
    if encoded is None:
        raise EncryptionNotConfigured("secret encryption key is not configured")
    try:
        key = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("secret encryption key must be base64 encoded") from exc
    if len(key) != _KEY_BYTES:
        raise ValueError("secret encryption key must decode to 32 bytes")
    return key


class Aes256Gcm:
    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_BYTES:
            raise ValueError("AES-256-GCM key must be 32 bytes")
        self._cipher = AESGCM(key)

    def __repr__(self) -> str:
        return "Aes256Gcm(<key-redacted>)"

    def encrypt(self, plaintext: str, *, tenant_id: str, reference_id: str) -> str:
        if not tenant_id or not reference_id:
            raise ValueError("tenant and reference context are required")
        nonce = secrets.token_bytes(_NONCE_BYTES)
        ciphertext = self._cipher.encrypt(
            nonce,
            plaintext.encode("utf-8"),
            self._associated_data(tenant_id, reference_id),
        )
        payload = base64.urlsafe_b64encode(nonce + ciphertext).rstrip(b"=").decode("ascii")
        return f"{_VERSION}.{payload}"

    def decrypt(self, envelope: str, *, tenant_id: str, reference_id: str) -> str:
        try:
            version, payload = envelope.split(".", 1)
            if version != _VERSION or not tenant_id or not reference_id:
                raise ValueError
            raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
            if len(raw) < _NONCE_BYTES + 16:
                raise ValueError
            plaintext = self._cipher.decrypt(
                raw[:_NONCE_BYTES],
                raw[_NONCE_BYTES:],
                self._associated_data(tenant_id, reference_id),
            )
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError, ValueError, binascii.Error) as exc:
            raise EncryptedValueInvalid("encrypted value is invalid") from exc

    @staticmethod
    def _associated_data(tenant_id: str, reference_id: str) -> bytes:
        return f"moallem-secret:{_VERSION}:{tenant_id}:{reference_id}".encode()
