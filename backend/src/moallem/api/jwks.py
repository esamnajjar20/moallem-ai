"""JWKS fetching with cache (Auth0). The URL is derived from CONFIGURED issuer only, never
from a token. HTTPS only, small response cap, rate-limited refresh on unknown `kid`.
"""

import json
import threading
import time
import urllib.request
from collections.abc import Callable
from urllib.parse import urlsplit

from moallem.domain.rs256 import RsaPublicKey, parse_jwks

_MAX_BYTES = 256 * 1024


def jwks_url_for_issuer(issuer: str) -> str:
    """Auth0 issuer is `https://<tenant>.auth0.com/` (trailing slash is part of the value)."""
    if urlsplit(issuer).scheme != "https":
        raise ValueError("issuer must be https")
    return issuer.rstrip("/") + "/.well-known/jwks.json"


def _default_fetch(url: str, timeout: float) -> bytes:
    if urlsplit(url).scheme != "https":
        raise ValueError("https only")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
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
        try:
            self._keys = parse_jwks(json.loads(self._fetch(self._url, self._timeout)))
        except (OSError, ValueError):
            pass  # keep the previous keys; verification fails closed if there are none
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
