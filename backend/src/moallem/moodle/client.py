"""Minimal Moodle REST web-service client (legacy External Web Service token, DEC-040 PROPOSED).

Security properties enforced here:
- the token travels in the POST body only: never in a URL, log line, exception or repr;
- the destination is resolved and pinned on EVERY call (see url_policy);
- redirects are not followed; size/time limits are passed to the transport;
- remote error messages are discarded (they may echo credentials); only a sanitised errorcode
  is kept, and mapped to the stable contract codes.

The Moodle errorcode -> contract code mapping below is an ASSUMPTION from Moodle conventions
(MDL-* evidence still BLOCKED). Unmapped codes fall through to MOODLE_UNAVAILABLE, never to a
permission or credential claim.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from moallem.moodle.errors import (
    MoodleCredentialInvalid,
    MoodleFunctionNotAvailable,
    MoodlePermissionDenied,
    MoodleResponseInvalid,
    MoodleUnavailable,
)
from moallem.moodle.url_policy import (
    PrivateNetworkProfile,
    Resolver,
    ResolvedTarget,
    SiteUrl,
    resolve_pinned,
)

REST_PATH = "/webservice/rest/server.php"
DEFAULT_TIMEOUT_S = 15.0  # tool timeout_ms in tool_registry.draft.json
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_FUNCTION_NAME = re.compile(r"[a-z][a-z0-9_]{2,127}")

_CREDENTIAL_CODES = frozenset({"invalidtoken", "expiredtoken", "tokenexpired"})
_FUNCTION_CODES = frozenset({"accessexception", "servicenotavailable", "invalidfunction"})
_PERMISSION_CODES = frozenset(
    {"nopermissions", "required_capability_exception", "cannotviewcourse"}
)


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    body: bytes


class MoodleTransport(Protocol):
    """Real implementation (urllib/httpx) lives with the hosting decision (ADR-020). It MUST:
    connect to target.ip:target.port with SNI/Host = target.host, verify TLS against target.host,
    not follow redirects, enforce timeout_s and abort once max_bytes is exceeded."""

    def post(
        self,
        *,
        target: ResolvedTarget,
        path: str,
        form: Mapping[str, str],
        timeout_s: float,
        max_bytes: int,
    ) -> TransportResponse: ...


class Token:
    """Holds the raw token; redacted everywhere except `reveal()`."""

    __slots__ = ("_v",)

    def __init__(self, value: str) -> None:
        if not value or not value.isascii() or any(c.isspace() for c in value):
            raise MoodleCredentialInvalid("invalid token format")
        self._v = value

    def reveal(self) -> str:
        return self._v

    def __repr__(self) -> str:
        return "Token(<redacted>)"

    __str__ = __repr__

    def __reduce__(self) -> Any:  # block accidental pickling / deepcopy into logs or caches
        raise TypeError("Token cannot be serialised")


def flatten_params(params: Mapping[str, Any]) -> dict[str, str]:
    """Moodle REST array syntax: list -> k[0]=v, dict -> k[0][sub]=v, bool -> 1/0, None rejected."""
    out: dict[str, str] = {}

    def walk(prefix: str, value: Any) -> None:
        if value is None:
            raise ValueError(f"None is not allowed for {prefix!r}")
        if isinstance(value, bool):
            out[prefix] = "1" if value else "0"
        elif isinstance(value, Mapping):
            for k, v in value.items():
                walk(f"{prefix}[{k}]", v)
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            for i, v in enumerate(value):
                walk(f"{prefix}[{i}]", v)
        else:
            out[prefix] = str(value)

    for key, val in params.items():
        walk(key, val)
    return out


class MoodleClient:
    def __init__(
        self,
        *,
        site: SiteUrl,
        token: Token,
        transport: MoodleTransport,
        resolver: Resolver,
        private_profile: PrivateNetworkProfile | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        self.site = site
        self._token = token
        self._transport = transport
        self._resolver = resolver
        self._private = private_profile
        self._timeout_s = timeout_s
        self._max_bytes = max_response_bytes

    def __repr__(self) -> str:
        return f"MoodleClient(site={self.site.root!r}, token=<redacted>)"

    def _post(self, path: str, form: Mapping[str, str], max_bytes: int) -> bytes:
        target = resolve_pinned(self.site, self._resolver, private=self._private)
        try:
            resp = self._transport.post(
                target=target,
                path=self.site.base_path + path,
                form=form,
                timeout_s=self._timeout_s,
                max_bytes=max_bytes,
            )
        except (TimeoutError, OSError) as exc:
            raise MoodleUnavailable("moodle request failed") from None
        if 300 <= resp.status < 400:
            raise MoodleUnavailable("unexpected redirect (not followed)")
        if resp.status in (401, 403):
            raise MoodleUnavailable("moodle rejected the request", remote_errorcode=None)
        if resp.status >= 400:
            raise MoodleUnavailable(f"moodle returned HTTP {resp.status}")
        if len(resp.body) > max_bytes:
            raise MoodleResponseInvalid("response exceeds size limit")
        return resp.body

    def call(self, function: str, params: Mapping[str, Any] | None = None) -> Any:
        if not _FUNCTION_NAME.fullmatch(function):
            raise ValueError("invalid web service function name")
        form = {
            **flatten_params(params or {}),
            "wstoken": self._token.reveal(),
            "wsfunction": function,
            "moodlewsrestformat": "json",
        }
        body = self._post(REST_PATH, form, self._max_bytes)
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise MoodleResponseInvalid("response is not valid JSON") from None
        if isinstance(data, dict) and "exception" in data:
            raise _map_remote_error(data)
        return data

    def download(self, path_under_site: str, *, max_bytes: int) -> bytes:
        """Authorised file fetch (token in POST body). `path_under_site` must already have been
        validated by `read.file_download_path`; this only moves bytes."""
        form = {"token": self._token.reveal()}
        return self._post(path_under_site, form, max_bytes)


def _map_remote_error(data: Mapping[str, Any]) -> Exception:
    raw = data.get("errorcode")
    code = raw.lower() if isinstance(raw, str) else ""
    if code in _CREDENTIAL_CODES:
        return MoodleCredentialInvalid("moodle credential rejected")
    if code in _PERMISSION_CODES:
        return MoodlePermissionDenied("moodle denied this operation")
    if code in _FUNCTION_CODES:
        return MoodleFunctionNotAvailable("function is not available on this moodle service")
    return MoodleUnavailable("moodle reported an error", remote_errorcode=code or None)
