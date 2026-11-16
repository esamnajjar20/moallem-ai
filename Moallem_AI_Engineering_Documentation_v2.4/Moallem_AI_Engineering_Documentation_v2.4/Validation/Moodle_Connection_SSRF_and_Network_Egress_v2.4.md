# Moodle Connection SSRF and Network Egress Policy — v2.4

## Purpose
Define the planning baseline for accepting a Moodle site URL without turning the connection endpoint into an SSRF primitive.

## Default policy
- HTTPS only; normalize the URL and reject embedded credentials, query strings and fragments.
- Deny loopback, link-local, multicast, reserved, metadata-service destinations, IP literals and arbitrary private-network ranges by default.
- Resolve DNS under controlled egress, pin the resolved destination for the connection attempt, and defend against DNS rebinding. Re-check every redirect; redirects to another host are denied unless the target is separately allowlisted.
- Apply outbound firewall/egress policy in addition to application validation; DNS checks alone are insufficient.
- Limit response size, connection time, redirect count and accepted content type. Never return raw upstream errors that may contain credentials.

## Private-campus Moodle exception
Some universities host Moodle on private campus networks. A blanket private-IP ban would make those sites unreachable, but allowing user-supplied private destinations would create SSRF risk. The proposed exception is therefore **not** a user-controlled URL override. It requires an infrastructure-provisioned Network Connector or egress profile, explicit approved host/CIDR, an identified tenant/site owner, Security/Infrastructure approval, and the same DNS pinning/redirect restrictions. Metadata endpoints remain blocked in all cases.

If the deployment has no approved connector, private-campus sites are `UNSUPPORTED_NETWORK_PATH` and must not be reached from the public API worker.

## Required tests
- Loopback IPv4/IPv6, link-local, multicast, reserved and cloud metadata hostnames/IPs are denied.
- DNS rebinding from a public address to a private address is denied.
- Redirect to a different host or blocked IP is denied.
- User-provided private URL is denied without connector provisioning.
- Approved private Moodle resolves only through the provisioned connector and approved allowlist.
- Long response, redirect loop, malformed URL and oversized response fail closed.

## Status
Proposed security baseline; actual egress implementation depends on ADR-020 and the selected hosting/network topology. No live Moodle endpoint has been tested.
