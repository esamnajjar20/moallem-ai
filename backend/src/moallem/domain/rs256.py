"""RS256 JWT verification, stdlib only (ADR-017 / Auth0). Public-key operations only.

Strictness: alg must be exactly RS256 (no `none`, no HS*), `kid` is required and must resolve to
a known RSA key of >= 2048 bits, and the PKCS#1 v1.5 padding is checked by comparing the WHOLE
expected encoded block (no padding parsing). Claim *policy* (iss/aud/exp...) is in identity.py.
If `PyJWT`/`cryptography` is later added to the lock, this module can be swapped behind
TokenVerifier without touching callers.
"""

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from moallem.domain.errors import AuthenticationRequired
from moallem.domain.identity import Claims

_FAIL = "authentication required"
_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
_MIN_BITS = 2048
_MIN_EXPONENT = 65537


@dataclass(frozen=True, slots=True)
class RsaPublicKey:
    n: int
    e: int


class JwksProvider(Protocol):
    def key_for(self, kid: str) -> RsaPublicKey | None: ...


class StaticJwks:
    def __init__(self, keys: Mapping[str, RsaPublicKey]) -> None:
        self._keys = dict(keys)

    def key_for(self, kid: str) -> RsaPublicKey | None:
        return self._keys.get(kid)


def _unb64(text: str) -> bytes:
    if not text or any(c not in _B64URL for c in text):
        raise ValueError("bad base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


_B64URL = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def parse_jwks(document: object) -> dict[str, RsaPublicKey]:
    """Extract usable RSA signing keys from a JWKS document; silently skip anything else."""
    keys: dict[str, RsaPublicKey] = {}
    items = document.get("keys") if isinstance(document, dict) else None
    for jwk in items if isinstance(items, list) else []:
        try:
            if jwk.get("kty") != "RSA" or jwk.get("use", "sig") != "sig":
                continue
            if jwk.get("alg", "RS256") != "RS256" or not isinstance(jwk.get("kid"), str):
                continue
            key = RsaPublicKey(
                int.from_bytes(_unb64(jwk["n"]), "big"), int.from_bytes(_unb64(jwk["e"]), "big")
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        if key.n.bit_length() >= _MIN_BITS and key.e >= _MIN_EXPONENT and key.e % 2 == 1:
            keys[jwk["kid"]] = key
    return keys


def rsa_pkcs1_sha256_verify(key: RsaPublicKey, message: bytes, signature: bytes) -> bool:
    k = (key.n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= key.n:
        return False
    encoded = pow(s, key.e, key.n).to_bytes(k, "big")
    t = _SHA256_PREFIX + hashlib.sha256(message).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(encoded, expected)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("not a number")
    return float(value)


class Rs256Verifier:
    def __init__(self, jwks: JwksProvider) -> None:
        self._jwks = jwks

    def verify(self, token: str) -> Claims:
        try:
            head_b, body_b, sig_b = token.split(".")
            head = json.loads(_unb64(head_b))
            if head.get("alg") != "RS256" or not isinstance(head.get("kid"), str):
                raise ValueError("alg/kid")
            key = self._jwks.key_for(head["kid"])
            if key is None:
                raise ValueError("unknown kid")
            if not rsa_pkcs1_sha256_verify(key, f"{head_b}.{body_b}".encode(), _unb64(sig_b)):
                raise ValueError("signature")
            p = json.loads(_unb64(body_b))
            aud = p.get("aud", [])
            aud_t = (aud,) if isinstance(aud, str) else tuple(aud)
            if not all(isinstance(a, str) for a in aud_t):
                raise ValueError("aud")
            if not isinstance(p["iss"], str) or not isinstance(p["sub"], str):
                raise ValueError("iss/sub")
            return Claims(
                issuer=p["iss"],
                subject=p["sub"],
                audience=aud_t,
                expires_at=_number(p.get("exp")),
                not_before=_number(p.get("nbf")),
                issued_at=_number(p.get("iat")),
            )
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise AuthenticationRequired(_FAIL) from exc
