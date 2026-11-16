import pytest

from moallem.domain.errors import AuthenticationRequired
from moallem.domain.identity import InMemorySubjectMapper, authenticate_bearer
from tests.helpers_jwt import HS256Verifier, mint

ISS, AUD, NOW = "https://idp.example", "moallem-api", 1_000_000
MAPPER = InMemorySubjectMapper({(ISS, "sub-1"): "user-1"})


def _claims(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "iss": ISS,
        "sub": "sub-1",
        "aud": AUD,
        "iat": NOW - 10,
        "exp": NOW + 600,
    }
    base.update(over)
    return base


def _auth(header: str | None, *, leeway: int = 0, max_life: int | None = 900) -> str:
    return authenticate_bearer(
        header,
        verifier=HS256Verifier(),
        mapper=MAPPER,
        issuer=ISS,
        audience=AUD,
        now=NOW,
        leeway_seconds=leeway,
        max_lifetime_seconds=max_life,
    )


def _bearer(payload: dict[str, object], **kw: object) -> str:
    return f"Bearer {mint(payload, **kw)}"  # type: ignore[arg-type]


def test_valid_token_maps_to_global_user() -> None:
    assert _auth(_bearer(_claims())) == "user-1"
    assert _auth(_bearer(_claims(aud=[AUD, "other"]))) == "user-1"


def test_every_failure_is_the_same_401() -> None:
    bad = [
        None,
        "",
        "Basic abc",
        "Bearer",
        "Bearer a b",
        "Bearer garbage",
        "Bearer a.b.c",
        _bearer(_claims(), key=b"wrong-key"),
        _bearer(_claims(), alg="none"),
        _bearer(_claims(), alg="HS512"),
        _bearer(_claims(exp=NOW - 1)),
        _bearer(_claims(nbf=NOW + 100)),
        _bearer(_claims(iss="https://evil.example")),
        _bearer(_claims(aud="someone-else")),
        _bearer(_claims(sub="unknown-subject")),
        _bearer({k: v for k, v in _claims().items() if k != "exp"}),
        _bearer(_claims(iat=NOW - 5000, exp=NOW + 600)),  # lifetime > 15 min
        _bearer({k: v for k, v in _claims().items() if k != "iat"}),  # lifetime unprovable
    ]
    seen = set()
    for h in bad:
        with pytest.raises(AuthenticationRequired) as ei:
            _auth(h)
        seen.add((ei.value.code, str(ei.value), ei.value.http_status))
    assert seen == {(ei.value.code, "authentication required", 401)}


def test_scheme_is_case_insensitive() -> None:
    assert _auth(_bearer(_claims()).replace("Bearer", "bearer")) == "user-1"


def test_leeway_tolerates_small_clock_skew_only() -> None:
    assert _auth(_bearer(_claims(exp=NOW - 5)), leeway=10) == "user-1"
    with pytest.raises(AuthenticationRequired):
        _auth(_bearer(_claims(exp=NOW - 50)), leeway=10)


def test_lifetime_cap_can_be_disabled_explicitly() -> None:
    long_lived = _bearer(_claims(iat=NOW - 5000))
    assert _auth(long_lived, max_life=None) == "user-1"
