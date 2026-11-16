"""Opt-in stdlib HTTPS transport for pinned Moodle destinations.

This transport is deliberately not selected by the application factory. Deployments must also
enforce the approved outbound network/egress policy (ADR-020).
"""

import http.client
import socket
import ssl
import time
from collections.abc import Mapping
from urllib.parse import urlencode

from moallem.moodle.client import TransportResponse
from moallem.moodle.errors import MoodleResponseInvalid
from moallem.moodle.url_policy import ResolvedTarget

_CHUNK_SIZE = 64 * 1024


class SystemResolver:
    """Resolve all A/AAAA addresses; the caller validates and pins the returned set."""

    def resolve(self, host: str) -> list[str]:
        answers = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        addresses: list[str] = []
        for answer in answers:
            address = answer[4][0]
            if not isinstance(address, str):
                raise OSError("resolver returned an invalid address")
            addresses.append(address)
        return list(dict.fromkeys(addresses))


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        *,
        target: ResolvedTarget,
        timeout_s: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(target.host, target.port, timeout=timeout_s, context=context)
        self._pinned_ip = target.ip
        self._ssl_context = context

    def connect(self) -> None:
        raw = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        try:
            self.sock = self._ssl_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class PinnedHttpsTransport:
    """POST form data to a pinned IP while validating TLS and Host against the original host."""

    def __init__(self, context: ssl.SSLContext | None = None) -> None:
        self._context = context or ssl.create_default_context()
        if not self._context.check_hostname or self._context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("TLS context must verify certificates and hostnames")

    def post(
        self,
        *,
        target: ResolvedTarget,
        path: str,
        form: Mapping[str, str],
        timeout_s: float,
        max_bytes: int,
    ) -> TransportResponse:
        if timeout_s <= 0 or max_bytes <= 0:
            raise ValueError("timeout_s and max_bytes must be positive")
        if (
            not path.startswith("/")
            or path.startswith("//")
            or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in path)
            or "#" in path
        ):
            raise ValueError("path must be a safe origin-relative URL")

        conn = _PinnedHTTPSConnection(
            target=target,
            timeout_s=timeout_s,
            context=self._context,
        )
        deadline = time.monotonic() + timeout_s
        try:
            conn.request(
                "POST",
                path,
                body=urlencode(form),
                headers={
                    "Accept": "application/json, */*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Connection": "close",
                },
            )
            response = conn.getresponse()
            body = bytearray()
            while len(body) <= max_bytes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Moodle response timed out")
                if conn.sock is not None:
                    conn.sock.settimeout(remaining)
                chunk = response.read1(min(_CHUNK_SIZE, max_bytes + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
            if len(body) > max_bytes:
                raise MoodleResponseInvalid("response exceeds size limit")
            return TransportResponse(response.status, bytes(body))
        except http.client.HTTPException:
            raise OSError("invalid Moodle HTTP response") from None
        finally:
            conn.close()
