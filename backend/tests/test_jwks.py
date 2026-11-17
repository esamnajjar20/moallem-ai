import json
import urllib.request

import pytest

from moallem.api.jwks import (
    UrlJwks,
    _SameOriginHTTPSRedirectHandler,
    jwks_url_for_issuer,
)
from tests.helpers_rsa import PUB_A, PUB_B, jwk


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _doc(*pairs: tuple[str, object]) -> bytes:
    return json.dumps({"keys": [jwk(k, v) for k, v in pairs]}).encode()  # type: ignore[arg-type]


class Fetcher:
    def __init__(self, *bodies: bytes | Exception) -> None:
        self.bodies = list(bodies)
        self.calls = 0

    def __call__(self, url: str, timeout: float) -> bytes:
        self.calls += 1
        item = self.bodies[min(self.calls - 1, len(self.bodies) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


def _jwks(fetch: Fetcher, clock: Clock) -> UrlJwks:
    return UrlJwks(
        "https://t.auth0.com/.well-known/jwks.json",
        ttl_seconds=3600,
        min_refresh_interval_seconds=60,
        timeout_seconds=5,
        fetch=fetch,
        clock=clock,
    )


def test_url_is_derived_from_issuer_and_must_be_https() -> None:
    url = jwks_url_for_issuer("https://t.auth0.com/")
    assert url == "https://t.auth0.com/.well-known/jwks.json"
    with pytest.raises(ValueError):
        jwks_url_for_issuer("http://t.auth0.com/")


def test_cached_within_ttl() -> None:
    f, c = Fetcher(_doc(("kid-a", PUB_A))), Clock()
    j = _jwks(f, c)
    assert j.key_for("kid-a") == PUB_A and j.key_for("kid-a") == PUB_A
    assert f.calls == 1


def test_unknown_kid_refresh_is_rate_limited_then_finds_rotated_key() -> None:
    f = Fetcher(_doc(("kid-a", PUB_A)), _doc(("kid-a", PUB_A), ("kid-b", PUB_B)))
    c = Clock()
    j = _jwks(f, c)
    assert j.key_for("kid-a")
    c.t = 10
    assert j.key_for("kid-b") is None and f.calls == 1  # too soon: no refetch (anti-hammering)
    c.t = 61
    assert j.key_for("kid-b") == PUB_B and f.calls == 2


def test_fetch_failure_keeps_old_keys_and_does_not_hammer() -> None:
    f = Fetcher(_doc(("kid-a", PUB_A)), OSError("down"))
    c = Clock()
    j = _jwks(f, c)
    assert j.key_for("kid-a")
    c.t = 4000  # ttl expired -> refresh fails
    assert j.key_for("kid-a") == PUB_A and f.calls == 2
    assert j.key_for("kid-a") == PUB_A and f.calls == 2  # failure also stamps fetched_at


def test_first_fetch_failure_fails_closed() -> None:
    j = _jwks(Fetcher(OSError("down")), Clock())
    assert j.key_for("kid-a") is None
    assert j.has_signing_keys() is False


def test_signing_key_readiness_loads_and_caches_key_set() -> None:
    fetch = Fetcher(_doc(("kid-a", PUB_A)))
    jwks = _jwks(fetch, Clock())
    assert jwks.has_signing_keys() is True
    assert jwks.has_signing_keys() is True
    assert fetch.calls == 1


def test_issuer_url_must_be_an_exact_https_origin() -> None:
    for issuer in (
        "https://t.auth0.com",
        "https://t.auth0.com/path/",
        "https://t.auth0.com/?x=1",
        "http://t.auth0.com/",
        "https://user@t.auth0.com/",
    ):
        with pytest.raises(ValueError):
            jwks_url_for_issuer(issuer)


def test_jwks_redirect_cannot_change_https_origin() -> None:
    handler = _SameOriginHTTPSRedirectHandler()
    request = urllib.request.Request("https://t.auth0.com/.well-known/jwks.json")
    with pytest.raises(ValueError, match="configured HTTPS origin"):
        handler.redirect_request(
            request, None, 302, "Found", {}, "https://attacker.example/keys.json"
        )
    with pytest.raises(ValueError, match="configured HTTPS origin"):
        handler.redirect_request(
            request, None, 302, "Found", {}, "http://t.auth0.com/keys.json"
        )
    same_origin = handler.redirect_request(
        request, None, 302, "Found", {}, "https://t.auth0.com/rotated-jwks.json"
    )
    assert same_origin is not None
    assert same_origin.full_url == "https://t.auth0.com/rotated-jwks.json"
