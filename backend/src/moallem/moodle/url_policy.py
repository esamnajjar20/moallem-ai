"""SSRF policy for user-supplied Moodle site URLs (Validation/Moodle_Connection_SSRF_..._v2.4.md).

Application-layer checks only: the outbound firewall / egress profile (ADR-020) is still
REQUIRED in addition. DNS is injected so rebinding can be tested; the transport MUST connect to
`ResolvedTarget.ip` (pinned) and send `host` as SNI/Host.
"""

import ipaddress
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from moallem.moodle.errors import UnsafeMoodleUrl

MAX_URL_LENGTH = 2048
_CONTROL_OR_SPACE = re.compile(r"[\x00-\x20\x7f\\]")
_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "instance-data",
        "instance-data.ec2.internal",
    }
)
_BLOCKED_SUFFIXES = (".localhost", ".internal", ".local", ".localdomain", ".home.arpa")
# Cloud metadata endpoints: blocked even when a private-campus profile is approved.
_ALWAYS_BLOCKED = tuple(
    ipaddress.ip_network(n)
    for n in (
        "169.254.0.0/16",  # link-local incl. 169.254.169.254
        "100.100.100.200/32",  # Alibaba metadata
        "168.63.129.16/32",  # Azure wire server
        "fd00:ec2::/32",  # AWS IMDS IPv6
        "fe80::/10",
    )
)

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass(frozen=True, slots=True)
class SiteUrl:
    """Normalised https site root. `base_path` has no trailing slash ('' for the domain root)."""

    host: str
    port: int
    base_path: str

    @property
    def origin(self) -> str:
        netloc = self.host if self.port == 443 else f"{self.host}:{self.port}"
        return f"https://{netloc}"

    @property
    def root(self) -> str:
        return f"{self.origin}{self.base_path}"


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    host: str
    ip: str
    port: int


@dataclass(frozen=True, slots=True)
class PrivateNetworkProfile:
    """Infrastructure-provisioned exception for private-campus Moodle (NOT user-controlled).

    Built from deployment config by operators after Security/Infrastructure approval. A user URL
    can never add to it. Metadata addresses stay blocked regardless.
    """

    approved_hosts: frozenset[str] = frozenset()
    approved_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()

    def permits(self, host: str, ip: IPAddress) -> bool:
        return host in self.approved_hosts and any(ip in n for n in self.approved_networks)


class Resolver(Protocol):
    def resolve(self, host: str) -> list[str]: ...


def normalize_site_url(raw: str, *, allowed_ports: Iterable[int] = (443,)) -> SiteUrl:
    if not isinstance(raw, str) or not raw or len(raw) > MAX_URL_LENGTH:
        raise UnsafeMoodleUrl("empty_or_too_long")
    if _CONTROL_OR_SPACE.search(raw):
        raise UnsafeMoodleUrl("control_space_or_backslash")
    scheme, sep, rest = raw.partition("://")
    if not sep or scheme.lower() != "https":
        raise UnsafeMoodleUrl("not_https")
    if "?" in rest or "#" in rest:
        raise UnsafeMoodleUrl("query_or_fragment")
    authority, slash, path = rest.partition("/")
    path = slash + path
    if "@" in authority:
        raise UnsafeMoodleUrl("embedded_credentials")
    host, port = _split_host_port(authority)
    if port not in set(allowed_ports):
        raise UnsafeMoodleUrl("port_not_allowed")
    host = _normalize_host(host)
    return SiteUrl(host=host, port=port, base_path=_normalize_path(path))


def _split_host_port(authority: str) -> tuple[str, int]:
    if authority.startswith("["):  # IPv6 literal: never acceptable
        raise UnsafeMoodleUrl("ip_literal")
    host, colon, port_s = authority.partition(":")
    if not colon:
        return host, 443
    if not port_s.isascii() or not port_s.isdigit() or not 0 < int(port_s) < 65536:
        raise UnsafeMoodleUrl("bad_port")
    return host, int(port_s)


def _normalize_host(host: str) -> str:
    if not host:
        raise UnsafeMoodleUrl("empty_host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise UnsafeMoodleUrl("ip_literal")
    # Also reject legacy numeric forms (0x7f.1, 2130706433, 017700000001) that resolvers accept.
    if re.fullmatch(r"[0-9a-fx.]+", host.lower()) and not re.search(r"[g-wyz]", host.lower()):
        raise UnsafeMoodleUrl("ip_literal")
    try:
        ascii_host = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise UnsafeMoodleUrl("bad_hostname") from exc
    labels = ascii_host.split(".")
    if len(ascii_host) > 253 or len(labels) < 2 or not all(_LABEL.fullmatch(x) for x in labels):
        raise UnsafeMoodleUrl("bad_hostname")
    if ascii_host in _BLOCKED_HOSTNAMES or ascii_host.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeMoodleUrl("blocked_hostname")
    return ascii_host


def _normalize_path(path: str) -> str:
    if path in ("", "/"):
        return ""
    if "%" in path:  # no percent-encoding tricks in a Moodle root path
        raise UnsafeMoodleUrl("encoded_path")
    segments = [s for s in path.split("/") if s]
    if any(s in (".", "..") for s in segments):
        raise UnsafeMoodleUrl("path_traversal")
    return "/" + "/".join(segments)


def ip_is_blocked(ip: IPAddress) -> bool:
    """Default-deny: only globally routable unicast addresses pass."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if any(ip in n for n in _ALWAYS_BLOCKED):
        return True
    return ip.is_multicast or not ip.is_global


def resolve_pinned(
    site: SiteUrl, resolver: Resolver, *, private: PrivateNetworkProfile | None = None
) -> ResolvedTarget:
    """Resolve and pin. EVERY returned address must be acceptable (defeats mixed A records and
    rebinding between the check and the connect, because the caller connects to the pinned IP)."""
    try:
        raw_ips = resolver.resolve(site.host)
    except OSError as exc:
        raise UnsafeMoodleUrl("dns_failure") from exc
    if not raw_ips:
        raise UnsafeMoodleUrl("dns_empty")
    parsed: list[IPAddress] = []
    for r in raw_ips:
        try:
            parsed.append(ipaddress.ip_address(r))
        except ValueError as exc:
            raise UnsafeMoodleUrl("dns_bad_address") from exc
    for ip in parsed:
        if any(ip in n for n in _ALWAYS_BLOCKED):
            raise UnsafeMoodleUrl("blocked_address")
        if ip_is_blocked(ip) and not (private is not None and private.permits(site.host, ip)):
            raise UnsafeMoodleUrl("blocked_address")
    return ResolvedTarget(host=site.host, ip=str(parsed[0]), port=site.port)


@dataclass(frozen=True, slots=True)
class RedirectPolicy:
    """Redirects are re-validated, never followed blindly. Cross-host is denied unless the target
    host is separately allowlisted (and then it still goes through resolve_pinned)."""

    max_redirects: int = 2
    allowlisted_hosts: frozenset[str] = field(default_factory=frozenset)

    def check(self, current: SiteUrl, location: str, hops_so_far: int) -> SiteUrl:
        if hops_so_far >= self.max_redirects:
            raise UnsafeMoodleUrl("too_many_redirects")
        target = normalize_site_url(location, allowed_ports=(current.port,))
        if target.host != current.host and target.host not in self.allowlisted_hosts:
            raise UnsafeMoodleUrl("cross_host_redirect")
        return target
