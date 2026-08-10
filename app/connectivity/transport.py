"""Bounded HTTP transport for signed ARC3 Connectivity requests."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import socket
import ssl
import threading
from pathlib import Path
from typing import Any, Mapping

from .health import RemoteHealthEndpoint
from .protocol import ReplayGuard, SignedRequest, VerificationError
from .trusted_devices import TrustedDeviceStore


MAX_REQUEST_BYTES = 64 * 1024
REQUEST_PATH = "/api/connectivity/request"


def load_server_tls_context(certfile: str | Path, keyfile: str | Path) -> ssl.SSLContext:
    """Load a server TLS context; does not create certificates or open sockets."""
    cert_path, key_path = Path(certfile), Path(keyfile)
    if not cert_path.is_file() or not key_path.is_file():
        raise ValueError("TLS certificate and private-key files are required")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return context


def private_ipv4_interfaces() -> tuple[str, ...]:
    """Return concrete private IPv4 addresses, excluding wildcard and loopback."""
    values: set[str] = set()
    for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
        address = ipaddress.ip_address(result[4][0])
        if address.is_private and not address.is_loopback:
            values.add(str(address))
    return tuple(sorted(values))


@dataclass(frozen=True, slots=True)
class TransportConfig:
    host: str = "127.0.0.1"
    port: int = 8766
    allow_private_lan: bool = False
    request_timeout_seconds: float = 10.0
    max_connections: int = 32
    tls_context: ssl.SSLContext | None = None

    def __post_init__(self):
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if not 1.0 <= self.request_timeout_seconds <= 60.0:
            raise ValueError("request timeout must be between 1 and 60 seconds")
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError as exc:
            raise ValueError("transport host must be a literal IP address") from exc
        if not address.is_loopback:
            if not self.allow_private_lan:
                raise ValueError("non-loopback binding requires explicit private-LAN approval")
            if not address.is_private:
                raise ValueError("ARC3 transport may bind only to loopback or private LAN addresses")
            if self.tls_context is None:
                raise ValueError("private-LAN binding requires TLS")
        if self.max_connections < 1:
            raise ValueError("max_connections must be positive")


class SignedRequestRouter:
    def __init__(
        self,
        trusted_store: TrustedDeviceStore,
        health_endpoint: RemoteHealthEndpoint | None = None,
        replay_guard: ReplayGuard | None = None,
    ) -> None:
        self.trusted_store = trusted_store
        self.health_endpoint = health_endpoint or RemoteHealthEndpoint()
        self.replay_guard = replay_guard or ReplayGuard()
        self._lock = threading.Lock()

    def route(self, value: Mapping[str, Any]) -> dict[str, Any]:
        request = SignedRequest.from_dict(value)
        trusted = self.trusted_store.get(request.sender_id)
        if trusted is None:
            raise VerificationError("request sender is not trusted")
        if request.action != RemoteHealthEndpoint.ACTION:
            raise VerificationError("remote action is not available")
        # ReplayGuard is stateful; serialize check-and-record across request threads.
        with self._lock:
            result = self.health_endpoint.handle(request, trusted, self.replay_guard)
        return {"ok": True, "action": request.action, "result": result}


class ConnectivityHTTPServer:
    """Explicitly started transport; construction alone opens no socket."""

    def __init__(self, router: SignedRequestRouter, config: TransportConfig | None = None):
        self.router = router
        self.config = config or TransportConfig()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def bound_port(self) -> int | None:
        return self._server.server_address[1] if self._server is not None else None

    def start(self) -> None:
        if self.running:
            return
        router = self.router
        timeout = self.config.request_timeout_seconds

        class Handler(_ConnectivityHandler):
            pass

        Handler.router = router
        Handler.request_timeout_seconds = timeout
        try:
            self._server = _BoundedThreadingHTTPServer(
                (self.config.host, self.config.port), Handler, self.config.max_connections
            )
        except OSError as exc:
            raise RuntimeError("ARC3 Connectivity could not bind its configured address") from exc
        self._server.daemon_threads = True
        if self.config.tls_context is not None:
            self._server.socket = self.config.tls_context.wrap_socket(
                self._server.socket, server_side=True
            )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="ARC3-Connectivity-HTTP",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5)


class _ConnectivityHandler(BaseHTTPRequestHandler):
    router: SignedRequestRouter
    request_timeout_seconds: float
    server_version = "ARC3Connectivity/1"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(self.request_timeout_seconds)

    def do_POST(self):
        if self.path != REQUEST_PATH:
            self._json_response(404, {"ok": False, "error": "not_found"})
            return
        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            self._json_response(415, {"ok": False, "error": "application_json_required"})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._json_response(413, {"ok": False, "error": "invalid_request_size"})
            return
        try:
            raw = self.rfile.read(length)
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("request must be an object")
            response = self.router.route(value)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, VerificationError):
            self._json_response(400, {"ok": False, "error": "request_rejected"})
            return
        except Exception:
            self._json_response(500, {"ok": False, "error": "internal_error"})
            return
        self._json_response(200, response)

    def do_GET(self):
        self._json_response(404, {"ok": False, "error": "not_found"})

    def log_message(self, format, *args):
        # Transport logging will be routed through ARC3's redacted audit service later.
        return

    def _json_response(self, status: int, value: Mapping[str, Any]):
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)


class _BoundedThreadingHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, max_connections):
        super().__init__(server_address, handler_class)
        self._connection_slots = threading.BoundedSemaphore(max_connections)

    def process_request(self, request, client_address):
        if not self._connection_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()
