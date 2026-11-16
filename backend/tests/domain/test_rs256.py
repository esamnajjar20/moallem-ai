import base64

import pytest

from moallem.domain.errors import AuthenticationRequired
from moallem.domain.identity import DerivedSubjectMapper, authenticate_bearer
from moallem.domain.rs256 import (
    Rs256Verifier,
    RsaPublicKey,
    StaticJwks,
    parse_jwks,
    rsa_pkcs1_sha256_verify,
)
from tests.helpers_jwt import mint
from tests.helpers_rsa import PUB_A, PUB_B, b64, jwk, sign_rs256

ISS, AUD, NOW = "https://tenant.auth0.com/", "https://api.moallem", 1_000_000
JWKS = StaticJwks({"kid-a": PUB_A})


def _p(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "iss": ISS,
        "sub": "auth0|abc123",
        "aud": [AUD, "https://tenant.auth0.com/userinfo"],
        "iat": NOW - 10,
        "exp": NOW + 600,
    }
    base.update(over)
    return base


def _auth(token: str) -> str:
    return authenticate_bearer(
        f"Bearer {token}",
        verifier=Rs256Verifier(JWKS),
        mapper=DerivedSubjectMapper(),
        issuer=ISS,
        audience=AUD,
        now=NOW,
        leeway_seconds=30,
        max_lifetime_seconds=900,
    )


def test_auth0_style_token_end_to_end() -> None:
    uid = _auth(sign_rs256(_p()))
    assert uid == _auth(sign_rs256(_p()))  # stable
    assert uid != _auth(sign_rs256(_p(sub="auth0|other")))


def test_primitive_accepts_good_and_rejects_bad_signature() -> None:
    token = sign_rs256(_p())
    head, body, sig = token.split(".")
    raw = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
    msg = f"{head}.{body}".encode()
    assert rsa_pkcs1_sha256_verify(PUB_A, msg, raw)
    assert not rsa_pkcs1_sha256_verify(PUB_B, msg, raw)
    assert not rsa_pkcs1_sha256_verify(PUB_A, msg + b"x", raw)
    assert not rsa_pkcs1_sha256_verify(PUB_A, msg, raw[:-1])
    assert not rsa_pkcs1_sha256_verify(PUB_A, msg, b"\x00" * len(raw))


def test_all_bad_tokens_are_the_same_401() -> None:
    good = sign_rs256(_p())
    head, body, sig = good.split(".")
    tampered_body = b64(b'{"iss":"https://tenant.auth0.com/","sub":"auth0|admin"}')
    bad = [
        sign_rs256(_p(), signer="b"),  # kid-a but signed by another key
        sign_rs256(_p(), kid="unknown-kid"),
        sign_rs256(_p(), alg="HS256"),
        sign_rs256(_p(), alg="none"),
        f"{head}.{tampered_body}.{sig}",
        f"{head}.{body}.",
        f"{head}.{body}",
        mint(_p()),  # HS256 token from the test minter
        sign_rs256(_p(exp=True)),  # bool is not a number
        sign_rs256(_p(aud=[1, 2])),
        sign_rs256(_p(sub=5)),
        sign_rs256(_p(exp=NOW - 100)),
        sign_rs256(_p(iss="https://evil.example/")),
        sign_rs256(_p(aud="other-api")),
        sign_rs256(_p(iat=NOW - 7200, exp=NOW + 3600)),  # 3h lifetime > 15 min cap
        "not-a-jwt",
    ]
    seen = set()
    for t in bad:
        with pytest.raises(AuthenticationRequired) as ei:
            _auth(t)
        seen.add((ei.value.code.value, str(ei.value), ei.value.http_status))
    assert seen == {("AUTHENTICATION_REQUIRED", "authentication required", 401)}


def test_missing_kid_is_rejected() -> None:
    token = sign_rs256(_p())
    head, body, sig = token.split(".")
    nokid = b64(b'{"alg":"RS256","typ":"JWT"}')
    with pytest.raises(AuthenticationRequired):
        Rs256Verifier(JWKS).verify(f"{nokid}.{body}.{sig}")


def test_parse_jwks_keeps_only_good_rsa_signing_keys() -> None:
    good = jwk("kid-a", PUB_A)
    weak_exp = jwk("weak-e", RsaPublicKey(PUB_A.n, 3))
    small = jwk("small", RsaPublicKey((1 << 1500) + 1, 65537))
    doc = {
        "keys": [
            good,
            weak_exp,
            small,
            {**jwk("enc", PUB_B), "use": "enc"},
            {**jwk("es", PUB_B), "kty": "EC"},
            {**jwk("alg", PUB_B), "alg": "RS512"},
            {"kty": "RSA", "kid": "broken", "n": "!!", "e": "AQAB"},
            "garbage",
            {"kid": 5},
        ]
    }
    assert set(parse_jwks(doc)) == {"kid-a"}
    assert parse_jwks("nope") == {}
    assert parse_jwks({"keys": "nope"}) == {}


def test_derived_user_ids_differ_by_issuer() -> None:
    m = DerivedSubjectMapper()
    assert m.user_id_for("https://a/", "s") != m.user_id_for("https://b/", "s")
