"""RS256 JWT verification using PyJWT and cryptography.

The verifier pins RS256, requires a known RSA signing key of at least 2048 bits, and returns
uniform authentication failures. Claim policy remains in ``identity.py`` so tests can use a
controlled clock.
"""

import base64
import binascii
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from moallem.domain.errors import AuthenticationRequired
from moallem.domain.identity import Claims

_FAIL = "authentication required"
_MIN_BITS = 2048
_MIN_EXPONENT = 65537
_MAX_TOKEN_BYTES = 128 * 1024
_B64URL = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


@dataclass(frozen=True, slots=True)
class RsaPublicKey:
    n: int
    e: int

    def to_cryptography_key(self) -> rsa.RSAPublicKey:
        return rsa.RSAPublicNumbers(self.e, self.n).public_key()


class JwksProvider(Protocol):
    def key_for(self, kid: str) -> RsaPublicKey | None: ...


class StaticJwks:
    def __init__(self, keys: Mapping[str, RsaPublicKey]) -> None:
        self._keys = dict(keys)

    def key_for(self, kid: str) -> RsaPublicKey | None:
        return self._keys.get(kid)


def _unb64(text: str) -> bytes:
    if not text or any(char not in _B64URL for char in text):
        raise ValueError("invalid base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def parse_jwks(document: object) -> dict[str, RsaPublicKey]:
    """Keep only sufficiently strong RSA signing keys with valid public parameters."""
    keys: dict[str, RsaPublicKey] = {}
    items = document.get("keys") if isinstance(document, dict) else None
    for jwk_data in items if isinstance(items, list) else []:
        if not isinstance(jwk_data, dict):
            continue
        try:
            if jwk_data.get("kty") != "RSA" or jwk_data.get("use", "sig") != "sig":
                continue
            if jwk_data.get("alg", "RS256") != "RS256":
                continue
            kid = jwk_data["kid"]
            if not isinstance(kid, str) or not kid or len(kid) > 256:
                continue
            key = RsaPublicKey(
                int.from_bytes(_unb64(jwk_data["n"]), "big"),
                int.from_bytes(_unb64(jwk_data["e"]), "big"),
            )
            if key.n.bit_length() < _MIN_BITS or key.e < _MIN_EXPONENT or key.e % 2 == 0:
                continue
            key.to_cryptography_key()
        except (ValueError, KeyError, TypeError, binascii.Error):
            continue
        keys[kid] = key
    return keys


def rsa_pkcs1_sha256_verify(key: RsaPublicKey, message: bytes, signature: bytes) -> bool:
    """Compatibility helper backed by cryptography; no hand-written RSA verification."""
    try:
        key.to_cryptography_key().verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError):
        return False
    return True


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("invalid numeric claim")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("invalid numeric claim")
    return number


class Rs256Verifier:
    def __init__(self, jwks: JwksProvider) -> None:
        self._jwks = jwks

    def verify(self, token: str) -> Claims:
        try:
            if not token or len(token.encode("utf-8")) > _MAX_TOKEN_BYTES:
                raise ValueError("invalid token size")
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or not isinstance(header.get("kid"), str)
                or not header["kid"]
                or header.get("crit") not in (None, [])
                or header.get("b64") is False
            ):
                raise ValueError("unsupported JWT header")
            key = self._jwks.key_for(header["kid"])
            if key is None:
                raise ValueError("unknown key")
            claims = jwt.decode(
                token,
                key.to_cryptography_key(),
                algorithms=["RS256"],
                options={
                    "require": ["iss", "sub"],
                    "verify_aud": False,
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                    "verify_iss": False,
                },
            )
            issuer = claims.get("iss")
            subject = claims.get("sub")
            audience = claims.get("aud", [])
            if isinstance(audience, str):
                audiences = (audience,)
            elif isinstance(audience, list) and all(isinstance(item, str) for item in audience):
                audiences = tuple(audience)
            else:
                raise ValueError("invalid audience claim")
            if not isinstance(issuer, str) or not isinstance(subject, str):
                raise ValueError("invalid identity claims")
            return Claims(
                issuer=issuer,
                subject=subject,
                audience=audiences,
                expires_at=_number(claims.get("exp")),
                not_before=_number(claims.get("nbf")),
                issued_at=_number(claims.get("iat")),
            )
        except (
            jwt.PyJWTError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
            binascii.Error,
        ) as exc:
            raise AuthenticationRequired(_FAIL) from exc
