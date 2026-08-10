"""Canonical signed request envelopes and replay protection."""

from __future__ import annotations

import base64
from collections import OrderedDict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from typing import Any, Callable, Mapping

from .identity import IdentityProvider, P256IdentityProvider, SignatureError
from .models import TrustedDevice


PROTOCOL_VERSION = 1
DEFAULT_MAX_AGE_MS = 5 * 60 * 1000
DEFAULT_FUTURE_SKEW_MS = 30 * 1000


class VerificationError(ValueError):
    """Raised when an inbound request fails trust or protocol verification."""


@dataclass(frozen=True, slots=True)
class SignedRequest:
    sender_id: str
    timestamp_ms: int
    nonce: str
    action: str
    payload: Mapping[str, Any]
    signature: str
    version: int = PROTOCOL_VERSION

    @classmethod
    def create(
        cls,
        provider: IdentityProvider,
        name: str,
        action: str,
        payload: Mapping[str, Any],
        *,
        clock_ms: Callable[[], int] | None = None,
        nonce_factory: Callable[[], str] | None = None,
    ) -> "SignedRequest":
        clean_action = _validate_action(action)
        safe_payload = _normalize_payload(payload)
        timestamp = int((clock_ms or _system_clock_ms)())
        if timestamp < 0:
            raise ValueError("timestamp cannot be negative")
        nonce = (nonce_factory or _secure_nonce)()
        _validate_nonce(nonce)
        identity = provider.identity(name)
        unsigned = {
            "version": PROTOCOL_VERSION,
            "sender_id": identity.device_id,
            "timestamp_ms": timestamp,
            "nonce": nonce,
            "action": clean_action,
            "payload": safe_payload,
        }
        signature = _base64url(provider.sign(_canonical_json(unsigned)))
        return cls(signature=signature, **unsigned)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SignedRequest":
        required = {"version", "sender_id", "timestamp_ms", "nonce", "action", "payload", "signature"}
        if set(value) != required:
            raise VerificationError("request envelope fields do not match protocol version 1")
        try:
            request = cls(
                version=int(value["version"]), sender_id=str(value["sender_id"]),
                timestamp_ms=int(value["timestamp_ms"]), nonce=str(value["nonce"]),
                action=str(value["action"]), payload=_normalize_payload(value["payload"]),
                signature=str(value["signature"]),
            )
        except (TypeError, ValueError) as exc:
            raise VerificationError("request envelope contains invalid values") from exc
        request._validate_structure()
        return request

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "sender_id": self.sender_id,
            "timestamp_ms": self.timestamp_ms, "nonce": self.nonce,
            "action": self.action, "payload": dict(self.payload),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "signature": self.signature}

    def canonical_unsigned(self) -> bytes:
        return _canonical_json(self.unsigned_dict())

    def _validate_structure(self) -> None:
        if self.version != PROTOCOL_VERSION:
            raise VerificationError("unsupported request protocol version")
        _validate_action(self.action)
        _validate_nonce(self.nonce)
        if self.timestamp_ms < 0:
            raise VerificationError("timestamp cannot be negative")
        if len(self.sender_id) != 64 or any(c not in "0123456789abcdef" for c in self.sender_id):
            raise VerificationError("sender_id must be a lowercase SHA-256 fingerprint")
        _base64url_decode(self.signature)

    def verify(
        self,
        trusted_device: TrustedDevice,
        replay_guard: "ReplayGuard",
        *,
        now_ms: int | None = None,
        max_age_ms: int = DEFAULT_MAX_AGE_MS,
        future_skew_ms: int = DEFAULT_FUTURE_SKEW_MS,
        record_replay: bool = True,
    ) -> None:
        self._validate_structure()
        if trusted_device.device_id != self.sender_id:
            raise VerificationError("request sender is not the supplied trusted device")
        current = _system_clock_ms() if now_ms is None else int(now_ms)
        if self.timestamp_ms < current - max_age_ms:
            raise VerificationError("request has expired")
        if self.timestamp_ms > current + future_skew_ms:
            raise VerificationError("request timestamp is too far in the future")
        try:
            valid = P256IdentityProvider.verify(
                self.canonical_unsigned(), _base64url_decode(self.signature),
                trusted_device.public_key_jwk,
            )
        except SignatureError as exc:
            raise VerificationError("request signature is malformed") from exc
        if not valid:
            raise VerificationError("request signature is invalid")
        if record_replay:
            replay_guard.check_and_record(self.sender_id, self.nonce, self.timestamp_ms, current)


class ReplayGuard:
    """Replay cache with optional crash-safe persistence."""

    def __init__(self, retention_ms: int = DEFAULT_MAX_AGE_MS, max_entries: int = 10_000, *, path: str | Path | None = None) -> None:
        if retention_ms <= 0 or max_entries <= 0:
            raise ValueError("replay guard limits must be positive")
        self.retention_ms = retention_ms
        self.max_entries = max_entries
        self._seen: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._path = Path(path) if path is not None else None
        self._lock = threading.RLock()
        if self._path is not None:
            self._load()

    def check_and_record(self, sender_id: str, nonce: str, timestamp_ms: int, now_ms: int) -> None:
        with self._lock:
            cutoff = now_ms - self.retention_ms
            stale = [key for key, seen_at in self._seen.items() if seen_at < cutoff]
            for key in stale:
                self._seen.pop(key, None)
            key = (sender_id, nonce)
            if key in self._seen:
                raise VerificationError("request nonce has already been used")
            if len(self._seen) >= self.max_entries:
                raise VerificationError("replay guard capacity is exhausted")
            self._seen[key] = timestamp_ms
            if self._path is not None:
                self._save()

    def _load(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
            entries = value.get("entries", [])
            for item in entries:
                self._seen[(str(item["sender_id"]), str(item["nonce"]))] = int(item["timestamp_ms"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise VerificationError("replay store is unreadable") from exc

    def _save(self) -> None:
        assert self._path is not None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "entries": [{"sender_id": s, "nonce": n, "timestamp_ms": t} for (s, n), t in self._seen.items()]}
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, dir=self._path.parent, prefix=f".{self._path.name}.", suffix=".tmp") as handle:
                json.dump(payload, handle, sort_keys=True)
                handle.flush(); os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, self._path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must contain only canonical JSON values") from exc


def _normalize_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("payload must be an object")
    normalized = json.loads(_canonical_json(dict(value)).decode("utf-8"))
    if not isinstance(normalized, dict):
        raise ValueError("payload must be an object")
    return normalized


def _validate_action(action: str) -> str:
    clean = str(action).strip().lower()
    import re
    if not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,63}", clean):
        raise ValueError("invalid request action")
    return clean


def _validate_nonce(nonce: str) -> None:
    decoded = _base64url_decode(nonce)
    if len(decoded) < 16:
        raise ValueError("request nonce must contain at least 128 bits")


def _secure_nonce() -> str:
    return _base64url(secrets.token_bytes(16))


def _system_clock_ms() -> int:
    return time.time_ns() // 1_000_000


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("value must be non-empty base64url")
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("value is not valid base64url") from exc
