"""ARC3 Connectivity / Conduit Core public domain API."""

from .identity import P256IdentityProvider, SignatureError
from .health import ReadOnlyHealthCollector, RemoteHealthEndpoint
from .models import DeviceIdentity, TrustedDevice
from .pairing import PairingApproval, PairingError, PairingRequest
from .pairing_service import PairingResult, PairingService, PendingPairingStore
from .permissions import AuthorizedRequest, PermissionDenied, PermissionPolicy
from .protocol import ReplayGuard, SignedRequest, VerificationError
from .trusted_devices import TrustedDeviceStore
from .transport import ConnectivityHTTPServer, SignedRequestRouter, TransportConfig
from .windows_key_store import WindowsDPAPIKeyStore

__all__ = [
    "DeviceIdentity",
    "AuthorizedRequest",
    "PairingApproval",
    "PairingError",
    "PairingRequest",
    "PairingResult",
    "PairingService",
    "PendingPairingStore",
    "PermissionDenied",
    "PermissionPolicy",
    "P256IdentityProvider",
    "ReadOnlyHealthCollector",
    "ReplayGuard",
    "RemoteHealthEndpoint",
    "SignedRequest",
    "SignatureError",
    "TrustedDevice",
    "TrustedDeviceStore",
    "ConnectivityHTTPServer",
    "SignedRequestRouter",
    "TransportConfig",
    "VerificationError",
    "WindowsDPAPIKeyStore",
]
