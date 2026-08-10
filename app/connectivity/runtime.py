"""Application-owned Connectivity paths and service construction."""

from __future__ import annotations

import os
from pathlib import Path
import platform

from .pairing_service import PairingService, PendingPairingStore
from .trusted_devices import TrustedDeviceStore
from .health import RemoteHealthEndpoint
from .transport import ConnectivityHTTPServer, SignedRequestRouter, TransportConfig, load_server_tls_context
from .windows_key_store import WindowsDPAPIKeyStore
from .protocol import ReplayGuard


def connectivity_data_directory() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "ARC3" / "Connectivity"


def create_pairing_service(data_directory: str | Path | None = None) -> PairingService:
    root = Path(data_directory) if data_directory is not None else connectivity_data_directory()
    provider = WindowsDPAPIKeyStore(root / "device_identity.dpapi").load_or_create()
    return PairingService(
        PendingPairingStore(root / "pending_pairings.json"),
        TrustedDeviceStore(root / "trusted_devices.json"),
        provider,
        platform.node() or "ARC3 PC",
    )


def create_health_transport(
    pairing_service: PairingService,
    *,
    allow_private_lan: bool = False,
    host: str | None = None,
    tls_certfile: str | Path | None = None,
    tls_keyfile: str | Path | None = None,
    port: int = 8766,
) -> ConnectivityHTTPServer:
    if allow_private_lan and host is None:
        raise ValueError("private-LAN binding requires an explicit host address")
    router = SignedRequestRouter(
        pairing_service.trusted_store,
        RemoteHealthEndpoint(),
        replay_guard=ReplayGuard(path=pairing_service.trusted_store.path.parent / "replay_nonces.json"),
    )
    tls_context = None
    if tls_certfile is not None or tls_keyfile is not None:
        if tls_certfile is None or tls_keyfile is None:
            raise ValueError("TLS certificate and key must be supplied together")
        tls_context = load_server_tls_context(tls_certfile, tls_keyfile)
    config = TransportConfig(
        host=host or "127.0.0.1",
        port=port,
        allow_private_lan=allow_private_lan,
        tls_context=tls_context,
    )
    return ConnectivityHTTPServer(router, config)
