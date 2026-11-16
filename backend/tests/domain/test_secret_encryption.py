import base64

import pytest

from moallem.domain.secret_encryption import (
    Aes256Gcm,
    EncryptedValueInvalid,
    EncryptionNotConfigured,
    decode_aes256_key,
)


def _key() -> bytes:
    return bytes(range(32))


def test_aes256_gcm_roundtrip_is_context_bound_and_redacted() -> None:
    key = _key()
    cipher = Aes256Gcm(key)
    encrypted = cipher.encrypt("synthetic-secret", tenant_id="tenant-1", reference_id="ref-1")

    assert cipher.decrypt(encrypted, tenant_id="tenant-1", reference_id="ref-1") == (
        "synthetic-secret"
    )
    assert encrypted != cipher.encrypt(
        "synthetic-secret", tenant_id="tenant-1", reference_id="ref-1"
    )
    assert key.hex() not in repr(cipher)
    with pytest.raises(EncryptedValueInvalid):
        cipher.decrypt(encrypted, tenant_id="tenant-2", reference_id="ref-1")


def test_aes256_gcm_rejects_tampering_and_invalid_envelopes() -> None:
    cipher = Aes256Gcm(_key())
    encrypted = cipher.encrypt("secret", tenant_id="t", reference_id="r")
    prefix, payload = encrypted.split(".", 1)
    replacement = "A" if payload[16] != "A" else "B"
    tampered = prefix + "." + payload[:16] + replacement + payload[17:]

    for candidate in (tampered, "m2.invalid", "m1."):
        with pytest.raises(EncryptedValueInvalid):
            cipher.decrypt(candidate, tenant_id="t", reference_id="r")


def test_environment_key_requires_base64_encoded_32_bytes() -> None:
    encoded = base64.b64encode(_key()).decode("ascii")
    assert decode_aes256_key(encoded) == _key()
    with pytest.raises(EncryptionNotConfigured):
        decode_aes256_key(None)
    with pytest.raises(ValueError):
        decode_aes256_key(base64.b64encode(b"short").decode("ascii"))
