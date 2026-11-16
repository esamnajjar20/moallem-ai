"""TEST-ONLY HS256 verifier/minter. Lives under tests/ so it can never ship in the package."""

import base64
import hashlib
import hmac
import json
from typing import Any

from moallem.domain.errors import AuthenticationRequired
from moallem.domain.identity import Claims

KEY = b"test-only-key"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mint(payload: dict[str, Any], *, alg: str = "HS256", key: bytes = KEY) -> str:
    head = _b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload).encode())
    sig = hmac.new(key, f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64(sig)}"


class HS256Verifier:
    def verify(self, token: str) -> Claims:
        try:
            head_b, body_b, sig_b = token.split(".")
            head = json.loads(_unb64(head_b))
            if head.get("alg") != "HS256":  # rejects "none" and algorithm confusion
                raise ValueError
            expect = hmac.new(KEY, f"{head_b}.{body_b}".encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(expect, _unb64(sig_b)):
                raise ValueError
            p = json.loads(_unb64(body_b))
            aud = p.get("aud", [])
            return Claims(
                issuer=p["iss"],
                subject=p["sub"],
                audience=(aud,) if isinstance(aud, str) else tuple(aud),
                expires_at=p.get("exp"),
                not_before=p.get("nbf"),
                issued_at=p.get("iat"),
            )
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise AuthenticationRequired("authentication required") from exc
