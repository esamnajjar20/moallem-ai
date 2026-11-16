import ipaddress

import pytest

from moallem.moodle.errors import UnsafeMoodleUrl
from moallem.moodle.url_policy import (
    PrivateNetworkProfile,
    RedirectPolicy,
    normalize_site_url,
    resolve_pinned,
)
from tests.moodle.fakes import FakeResolver


def test_normalizes_to_canonical_https_root() -> None:
    s = normalize_site_url("https://Moodle.Example.EDU/")
    assert (s.host, s.port, s.base_path, s.root) == (
        "moodle.example.edu", 443, "", "https://moodle.example.edu"
    )
    assert normalize_site_url("https://moodle.example.edu/lms//moodle/").base_path == "/lms/moodle"


@pytest.mark.parametrize(
    "bad",
    [
        "", "http://moodle.example.edu", "ftp://moodle.example.edu", "moodle.example.edu",
        "https://user:pw@moodle.example.edu", "https://moodle.example.edu?x=1",
        "https://moodle.example.edu/#frag", "https://moodle.example.edu:8443",
        "https://moodle.example.edu:99999", "https://moodle.example.edu/a/../b",
        "https://moodle.example.edu/%2e%2e/x", "https://moodle.example.edu/a b",
        "https://moodle.example.edu\\@evil.com", "https://127.0.0.1", "https://[::1]",
        "https://2130706433", "https://0x7f.1", "https://localhost", "https://a.localhost",
        "https://metadata.google.internal", "https://svc.internal", "https://printer.local",
        "https://singlelabel", "https://-bad.example.edu", "https://" + "a" * 70 + ".edu",
        "https://169.254.169.254", "https://moodle.example.edu/" + "x" * 3000,
    ],
)
def test_malformed_or_dangerous_urls_rejected(bad: str) -> None:
    with pytest.raises(UnsafeMoodleUrl):
        normalize_site_url(bad)


def test_rejection_message_is_generic_reason_is_for_audit() -> None:
    with pytest.raises(UnsafeMoodleUrl) as ei:
        normalize_site_url("https://127.0.0.1")
    assert "127" not in str(ei.value) and ei.value.reason == "ip_literal"


def test_idn_host_is_punycoded() -> None:
    assert normalize_site_url("https://موودل.example.edu").host.startswith("xn--")


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.5", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1",
     "0.0.0.0", "224.0.0.1", "240.0.0.1", "::1", "fe80::1", "fc00::1", "ff02::1",
     "::ffff:127.0.0.1", "::ffff:10.0.0.1", "fd00:ec2::254", "100.100.100.200", "168.63.129.16"],
)
def test_non_public_destinations_denied(ip: str) -> None:
    site = normalize_site_url("https://moodle.example.edu")
    with pytest.raises(UnsafeMoodleUrl):
        resolve_pinned(site, FakeResolver({"moodle.example.edu": [ip]}))


def test_public_address_is_pinned() -> None:
    site = normalize_site_url("https://moodle.example.edu")
    t = resolve_pinned(site, FakeResolver({"moodle.example.edu": ["93.184.216.34"]}))
    assert (t.host, t.ip, t.port) == ("moodle.example.edu", "93.184.216.34", 443)


def test_mixed_public_and_private_records_denied() -> None:  # rebinding / split-horizon
    site = normalize_site_url("https://moodle.example.edu")
    r = FakeResolver({"moodle.example.edu": ["93.184.216.34", "10.0.0.5"]})
    with pytest.raises(UnsafeMoodleUrl):
        resolve_pinned(site, r)


def test_rebinding_between_calls_is_caught_because_every_call_resolves() -> None:
    site = normalize_site_url("https://moodle.example.edu")
    r = FakeResolver({"moodle.example.edu": ["93.184.216.34"]})
    resolve_pinned(site, r)
    r.mapping["moodle.example.edu"] = ["127.0.0.1"]
    with pytest.raises(UnsafeMoodleUrl):
        resolve_pinned(site, r)


@pytest.mark.parametrize("answer", [[], ["not-an-ip"]])
def test_empty_or_garbage_dns_denied(answer: list[str]) -> None:
    site = normalize_site_url("https://moodle.example.edu")
    with pytest.raises(UnsafeMoodleUrl):
        resolve_pinned(site, FakeResolver({"moodle.example.edu": answer}))


def test_dns_failure_denied() -> None:
    site = normalize_site_url("https://moodle.example.edu")
    with pytest.raises(UnsafeMoodleUrl):
        resolve_pinned(site, FakeResolver({}))


def test_private_campus_only_through_provisioned_profile() -> None:
    site = normalize_site_url("https://lms.campus.edu")
    res = FakeResolver({"lms.campus.edu": ["10.20.30.40"]})
    with pytest.raises(UnsafeMoodleUrl):  # user-supplied private URL, no connector
        resolve_pinned(site, res)
    prof = PrivateNetworkProfile(
        approved_hosts=frozenset({"lms.campus.edu"}),
        approved_networks=(ipaddress.ip_network("10.20.0.0/16"),),
    )
    assert resolve_pinned(site, res, private=prof).ip == "10.20.30.40"
    # host not approved, or address outside the approved CIDR, stays denied
    other = normalize_site_url("https://other.campus.edu")
    with pytest.raises(UnsafeMoodleUrl):
        resolve_pinned(other, FakeResolver({"other.campus.edu": ["10.20.30.40"]}), private=prof)
    with pytest.raises(UnsafeMoodleUrl):
        resolve_pinned(site, FakeResolver({"lms.campus.edu": ["10.99.0.1"]}), private=prof)


def test_metadata_blocked_even_with_private_profile() -> None:
    site = normalize_site_url("https://lms.campus.edu")
    prof = PrivateNetworkProfile(
        approved_hosts=frozenset({"lms.campus.edu"}),
        approved_networks=(ipaddress.ip_network("169.254.0.0/16"),),
    )
    with pytest.raises(UnsafeMoodleUrl):
        resolve_pinned(site, FakeResolver({"lms.campus.edu": ["169.254.169.254"]}), private=prof)


def test_redirect_policy() -> None:
    cur = normalize_site_url("https://moodle.example.edu")
    pol = RedirectPolicy(max_redirects=2)
    assert pol.check(cur, "https://moodle.example.edu/lms", 0).base_path == "/lms"
    with pytest.raises(UnsafeMoodleUrl):
        pol.check(cur, "https://evil.example.com/", 0)  # cross-host
    with pytest.raises(UnsafeMoodleUrl):
        pol.check(cur, "http://moodle.example.edu/", 0)  # downgrade
    with pytest.raises(UnsafeMoodleUrl):
        pol.check(cur, "https://127.0.0.1/", 0)  # IP literal
    with pytest.raises(UnsafeMoodleUrl):
        pol.check(cur, "https://moodle.example.edu/", 2)  # loop / too many hops
    allow = RedirectPolicy(allowlisted_hosts=frozenset({"www.example.edu"}))
    assert allow.check(cur, "https://www.example.edu/", 0).host == "www.example.edu"
