"""Signed pairing request and explicit approval models."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from hashlib import sha256
import json
import secrets
import time
from typing import Any, Callable, Mapping

from .identity import P256IdentityProvider
from .models import DeviceIdentity, TrustedDevice


PAIRING_VERSION = 1
PAIRING_MAX_AGE_MS = 10 * 60 * 1000
MAX_DEVICE_NAME_LENGTH = 128
MAX_PERMISSION_COUNT = 32
MAX_PERMISSION_LENGTH = 96


class PairingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PairingRequest:
    device: DeviceIdentity
    timestamp_ms: int
    nonce: str
    signature: str
    version: int = PAIRING_VERSION

    @classmethod
    def create(
        cls,
        provider: P256IdentityProvider,
        device_name: str,
        *,
        clock_ms: Callable[[], int] | None = None,
        nonce_factory: Callable[[], str] | None = None,
    ) -> "PairingRequest":
        _validate_device_name(device_name)
        device = provider.identity(device_name)
        timestamp = int((clock_ms or _clock_ms)())
        nonce = (nonce_factory or _nonce)()
        unsigned = _request_unsigned(device, timestamp, nonce)
        signature = _b64(provider.sign(_canonical(unsigned)))
        return cls(device, timestamp, nonce, signature)

    @property
    def request_id(self) -> str:
        return sha256(self.canonical_unsigned()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**_request_unsigned(self.device, self.timestamp_ms, self.nonce), "signature": self.signature}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PairingRequest":
        expected = {"version", "type", "device", "timestamp_ms", "nonce", "signature"}
        if set(value) != expected or value.get("type") != "pairing.request":
            raise PairingError("invalid pairing request fields")
        device = _device_from_dict(value["device"])
        request = cls(
            device, int(value["timestamp_ms"]), str(value["nonce"]),
            str(value["signature"]), int(value["version"]),
        )
        if request.version != PAIRING_VERSION:
            raise PairingError("unsupported pairing version")
        request._validate_bounds()
        return request

    def canonical_unsigned(self) -> bytes:
        return _canonical(_request_unsigned(self.device, self.timestamp_ms, self.nonce))

    def verify(self, *, now_ms: int | None = None) -> None:
        self._validate_bounds()
        current = _clock_ms() if now_ms is None else int(now_ms)
        _validate_pairing_time(self.timestamp_ms, current)
        _validate_nonce(self.nonce)
        if not P256IdentityProvider.verify(
            self.canonical_unsigned(), _decode(self.signature), self.device.public_key_jwk
        ):
            raise PairingError("pairing request signature is invalid")

    def _validate_bounds(self) -> None:
        _validate_device_name(self.device.name)
        if len(self.signature) > 512:
            raise PairingError("pairing signature is too large")


@dataclass(frozen=True, slots=True)
class PairingApproval:
    request_id: str
    requester_id: str
    approver: DeviceIdentity
    permissions: tuple[str, ...]
    timestamp_ms: int
    nonce: str
    signature: str
    version: int = PAIRING_VERSION

    @classmethod
    def create(
        cls,
        request: PairingRequest,
        approver_provider: P256IdentityProvider,
        approver_name: str,
        permissions: tuple[str, ...],
        *,
        clock_ms: Callable[[], int] | None = None,
        nonce_factory: Callable[[], str] | None = None,
    ) -> "PairingApproval":
        request.verify(now_ms=int((clock_ms or _clock_ms)()))
        # Reuse TrustedDevice validation for normalized permission identifiers.
        _validate_permissions(permissions)
        requested = TrustedDevice.from_identity(request.device, permissions).permissions
        approver = approver_provider.identity(approver_name)
        timestamp = int((clock_ms or _clock_ms)())
        nonce = (nonce_factory or _nonce)()
        unsigned = _approval_unsigned(
            request.request_id, request.device.device_id, approver, requested, timestamp, nonce
        )
        signature = _b64(approver_provider.sign(_canonical(unsigned)))
        return cls(
            request.request_id, request.device.device_id, approver, requested,
            timestamp, nonce, signature,
        )

    def verify(self, request: PairingRequest, *, now_ms: int | None = None) -> TrustedDevice:
        current = _clock_ms() if now_ms is None else int(now_ms)
        request.verify(now_ms=current)
        _validate_pairing_time(self.timestamp_ms, current)
        _validate_nonce(self.nonce)
        if self.request_id != request.request_id or self.requester_id != request.device.device_id:
            raise PairingError("pairing approval does not match the request")
        unsigned = _approval_unsigned(
            self.request_id, self.requester_id, self.approver,
            self.permissions, self.timestamp_ms, self.nonce,
        )
        if not P256IdentityProvider.verify(
            _canonical(unsigned), _decode(self.signature), self.approver.public_key_jwk
        ):
            raise PairingError("pairing approval signature is invalid")
        return TrustedDevice.from_identity(request.device, self.permissions)

    def _validate_bounds(self) -> None:
        _validate_device_name(self.device.name)
        if len(self.signature) > 512:
            raise PairingError("pairing signature is too large")

    def to_dict(self) -> dict[str, Any]:
        unsigned = _approval_unsigned(
            self.request_id, self.requester_id, self.approver,
            self.permissions, self.timestamp_ms, self.nonce,
        )
        return {**unsigned, "signature": self.signature}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PairingApproval":
        expected = {
            "version", "type", "request_id", "requester_id", "approver",
            "permissions", "timestamp_ms", "nonce", "signature",
        }
        if set(value) != expected or value.get("type") != "pairing.approval":
            raise PairingError("invalid pairing approval fields")
        approver = _device_from_dict(value["approver"])
        approval = cls(
            str(value["request_id"]), str(value["requester_id"]), approver,
            TrustedDevice.from_identity(approver, tuple(value["permissions"])).permissions,
            int(value["timestamp_ms"]), str(value["nonce"]), str(value["signature"]),
            int(value["version"]),
        )
        _validate_permissions(approval.permissions)
        if approval.version != PAIRING_VERSION:
            raise PairingError("unsupported pairing version")
        return approval


def _request_unsigned(device: DeviceIdentity, timestamp: int, nonce: str) -> dict[str, Any]:
    return {
        "version": PAIRING_VERSION, "type": "pairing.request",
        "device": device.to_dict(), "timestamp_ms": timestamp, "nonce": nonce,
    }


def _approval_unsigned(
    request_id: str, requester_id: str, approver: DeviceIdentity,
    permissions: tuple[str, ...], timestamp: int, nonce: str,
) -> dict[str, Any]:
    return {
        "version": PAIRING_VERSION, "type": "pairing.approval",
        "request_id": request_id, "requester_id": requester_id,
        "approver": approver.to_dict(), "permissions": list(permissions),
        "timestamp_ms": timestamp, "nonce": nonce,
    }


def _device_from_dict(value: Any) -> DeviceIdentity:
    if not isinstance(value, Mapping) or set(value) != {"device_id", "name", "public_key_jwk"}:
        raise PairingError("invalid pairing device identity fields")
    device = DeviceIdentity(str(value["name"]), value["public_key_jwk"])
    _validate_device_name(device.name)
    if device.device_id != value["device_id"]:
        raise PairingError("pairing device fingerprint does not match its public key")
    return device


def _validate_device_name(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_DEVICE_NAME_LENGTH:
        raise PairingError("device name is invalid or too long")


def _validate_permissions(values: tuple[str, ...] | list[str]) -> None:
    if len(values) > MAX_PERMISSION_COUNT:
        raise PairingError("too many permissions")
    if any(not isinstance(item, str) or len(item) > MAX_PERMISSION_LENGTH for item in values):
        raise PairingError("permission is too long")


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _validate_pairing_time(timestamp: int, now: int) -> None:
    if timestamp < now - PAIRING_MAX_AGE_MS:
        raise PairingError("pairing message has expired")
    if timestamp > now + 30_000:
        raise PairingError("pairing message timestamp is too far in the future")


def _nonce() -> str:
    return _b64(secrets.token_bytes(16))


def _validate_nonce(value: str) -> None:
    if len(_decode(value)) < 16:
        raise PairingError("pairing nonce must contain at least 128 bits")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise PairingError("pairing value is not valid base64url") from exc


def _clock_ms() -> int:
    return time.time_ns() // 1_000_000
