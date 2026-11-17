"""JWKS fetching with cache (Auth0). The URL is derived from CONFIGURED issuer only, never
from a token. HTTPS only, small response cap, rate-limited refresh on unknown `kid`.
"""

import contextlib
import json
import threading
import time
import urllib.request
from collections.abc import Callable
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from moallem.domain.rs256 import RsaPublicKey, parse_jwks

_MAX_BYTES = 256 * 1024


def jwks_url_for_issuer(issuer: str) -> str:
    """Derive the JWKS URL from an exact HTTPS OIDC issuer origin."""
    parts = urlsplit(issuer)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or not issuer.endswith("/")
    ):
        raise ValueError("issuer must be an exact HTTPS issuer URL ending in /")
    return issuer.rstrip("/") + "/.well-known/jwks.json"


class _SameOriginHTTPSRedirectHandler(HTTPRedirectHandler):
    """Do not let a configured JWKS endpoint redirect trust to another origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        source = urlsplit(req.full_url)
        target = urlsplit(newurl)
        if (
            target.scheme != "https"
            or target.hostname is None
            or target.hostname.lower() != (source.hostname or "").lower()
            or target.port != source.port
            or target.username is not None
            or target.password is not None
        ):
            raise ValueError("JWKS redirect must remain on the configured HTTPS origin")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_fetch(url: str, timeout: float) -> bytes:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("https JWKS URL required")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})  # noqa: S310
    opener = build_opener(_SameOriginHTTPSRedirectHandler())
    with opener.open(req, timeout=timeout) as resp:  # noqa: S310
        data: bytes = resp.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise ValueError("jwks too large")
    return data


class UrlJwks:
    def __init__(
        self,
        url: str,
        *,
        ttl_seconds: float,
        min_refresh_interval_seconds: float,
        timeout_seconds: float,
        fetch: Callable[[str, float], bytes] = _default_fetch,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._ttl = ttl_seconds
        self._min_gap = min_refresh_interval_seconds
        self._timeout = timeout_seconds
        self._fetch = fetch
        self._clock = clock
        self._keys: dict[str, RsaPublicKey] = {}
        self._fetched_at: float | None = None
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        with contextlib.suppress(OSError, ValueError):
            self._keys = parse_jwks(json.loads(self._fetch(self._url, self._timeout)))
        self._fetched_at = self._clock()  # also on failure: bounds retry rate

    def key_for(self, kid: str) -> RsaPublicKey | None:
        with self._lock:
            now = self._clock()
            stale = self._fetched_at is None or now - self._fetched_at >= self._ttl
            if stale:
                self._refresh()
            elif kid not in self._keys and now - (self._fetched_at or 0) >= self._min_gap:
                self._refresh()  # key rotation: unknown kid, at most once per min gap
            return self._keys.get(kid)

    def has_signing_keys(self) -> bool:
        """Readiness probe: refresh the configured issuer's key set and require a usable key."""
        with self._lock:
            now = self._clock()
            stale = self._fetched_at is None or now - self._fetched_at >= self._ttl
            unavailable = not self._keys and (
                self._fetched_at is None or now - self._fetched_at >= self._min_gap
            )
            if stale or unavailable:
                self._refresh()
            return bool(self._keys)
