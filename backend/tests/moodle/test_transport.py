import shutil
import ssl
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from moallem.moodle.client import TransportResponse
from moallem.moodle.errors import MoodleResponseInvalid
from moallem.moodle.transport import PinnedHttpsTransport
from moallem.moodle.url_policy import ResolvedTarget


class _Server(ThreadingHTTPServer):
    def handle_error(self, request: object, client_address: object) -> None:
        del request, client_address


@contextmanager
def _local_tls_server(
    *, delay: float = 0
) -> Iterator[tuple[_Server, list[str], list[str], list[str], list[bytes], Path]]:
    requests: list[str] = []
    hosts: list[str] = []
    bodies: list[bytes] = []
    sni_names: list[str] = []

    with TemporaryDirectory() as temp_dir:
        certificate = Path(temp_dir) / "moodle-test.crt"
        private_key = Path(temp_dir) / "moodle-test.key"
        openssl = shutil.which("openssl")
        if openssl is None:
            pytest.skip("OpenSSL is required to generate the local TLS test certificate.")
        subprocess.run(  # noqa: S603 - fixed local TLS certificate-generation command
            [
                openssl,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-keyout",
                str(private_key),
                "-out",
                str(certificate),
                "-subj",
                "/CN=moodle.example.edu",
                "-addext",
                "subjectAltName=DNS:moodle.example.edu",
                "-addext",
                "basicConstraints=critical,CA:TRUE",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                requests.append(self.path)
                hosts.append(self.headers["Host"])
                body = self.rfile.read(int(self.headers["Content-Length"]))
                bodies.append(body)
                if delay:
                    time.sleep(delay)
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "https://other.example.edu/")
                    self.end_headers()
                    return
                payload = b"x" * 100 if self.path == "/large" else b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *args: object) -> None:
                del args

        server = _Server(("127.0.0.1", 0), Handler)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(certificate, private_key)
        server_context.set_servername_callback(
            lambda _sock, server_name, _context: sni_names.append(server_name or "")
        )
        server.socket = server_context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server, sni_names, requests, hosts, bodies, certificate
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()


def _transport(certificate: Path) -> PinnedHttpsTransport:
    context = ssl.create_default_context(cafile=str(certificate))
    return PinnedHttpsTransport(context)


def _target(server: _Server, host: str = "moodle.example.edu") -> ResolvedTarget:
    return ResolvedTarget(host=host, ip="127.0.0.1", port=server.server_port)


def test_insecure_tls_context_is_rejected() -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with pytest.raises(ValueError, match="must verify"):
        PinnedHttpsTransport(context)


def _post(
    transport: PinnedHttpsTransport,
    target: ResolvedTarget,
    path: str,
    *,
    timeout_s: float = 2.0,
    max_bytes: int = 1024,
) -> TransportResponse:
    return transport.post(
        target=target,
        path=path,
        form={"wstoken": "synthetic-test-token"},
        timeout_s=timeout_s,
        max_bytes=max_bytes,
    )


def test_local_tls_connect_uses_pinned_ip_and_original_host_for_sni_and_host() -> None:
    with _local_tls_server() as (server, sni_names, requests, hosts, bodies, certificate):
        transport = _transport(certificate)
        response = _post(transport, _target(server), "/webservice/rest/server.php")

    assert response.status == 200 and response.body == b'{"ok":true}'
    assert sni_names == ["moodle.example.edu"]
    assert requests == ["/webservice/rest/server.php"]
    assert bodies == [b"wstoken=synthetic-test-token"]
    assert hosts == [f"moodle.example.edu:{server.server_port}"]


def test_tls_certificate_is_verified_for_original_host() -> None:
    with (
        _local_tls_server() as (server, _sni_names, _requests, _hosts, _bodies, certificate),
        pytest.raises(ssl.SSLCertVerificationError),
    ):
        _post(_transport(certificate), _target(server, host="wrong.example.edu"), "/")


def test_redirect_is_returned_without_following_it() -> None:
    with _local_tls_server() as (server, _sni_names, requests, _hosts, _bodies, certificate):
        response = _post(_transport(certificate), _target(server), "/redirect")

    assert response.status == 302
    assert requests == ["/redirect"]


def test_response_size_is_limited_while_streaming() -> None:
    with (
        _local_tls_server() as (server, _sni_names, _requests, _hosts, _bodies, certificate),
        pytest.raises(MoodleResponseInvalid, match="size limit"),
    ):
        _post(_transport(certificate), _target(server), "/large", max_bytes=10)


def test_socket_timeout_is_enforced() -> None:
    with (
        _local_tls_server(delay=0.25) as (
            server,
            _sni_names,
            _requests,
            _hosts,
            _bodies,
            certificate,
        ),
        pytest.raises(TimeoutError),
    ):
        _post(_transport(certificate), _target(server), "/", timeout_s=0.05)


@pytest.mark.parametrize("path", ["", "//evil.example/", "/bad path", "/x#fragment"])
def test_only_safe_origin_relative_paths_are_sent(path: str) -> None:
    with (
        _local_tls_server() as (server, _sni_names, requests, _hosts, _bodies, certificate),
        pytest.raises(ValueError),
    ):
        _post(_transport(certificate), _target(server), path)

    assert requests == []
