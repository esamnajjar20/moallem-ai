"""TEST-ONLY RS256 minter (textbook RSA signing with the fixed test keys)."""

import base64
import hashlib
import json
from typing import Any

from moallem.domain.rs256 import RsaPublicKey
from tests import rsa_keys

PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
PUB_A = RsaPublicKey(rsa_keys.KEY_A_N, rsa_keys.E)
PUB_B = RsaPublicKey(rsa_keys.KEY_B_N, rsa_keys.E)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_rs256(
    payload: dict[str, Any], *, kid: str = "kid-a", signer: str = "a", alg: str = "RS256"
) -> str:
    n, d = (
        (rsa_keys.KEY_A_N, rsa_keys.KEY_A_D)
        if signer == "a"
        else (rsa_keys.KEY_B_N, rsa_keys.KEY_B_D)
    )
    head = b64(json.dumps({"alg": alg, "typ": "JWT", "kid": kid}).encode())
    body = b64(json.dumps(payload).encode())
    k = (n.bit_length() + 7) // 8
    t = PREFIX + hashlib.sha256(f"{head}.{body}".encode()).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    sig = pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")
    return f"{head}.{body}.{b64(sig)}"


def jwk(kid: str, key: RsaPublicKey) -> dict[str, str]:
    k = (key.n.bit_length() + 7) // 8
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": b64(key.n.to_bytes(k, "big")),
        "e": b64(key.e.to_bytes(3, "big")),
    }
