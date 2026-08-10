"""Durable, explicit pairing lifecycle orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Callable

from .identity import P256IdentityProvider
from .pairing import PAIRING_MAX_AGE_MS, PairingApproval, PairingError, PairingRequest
from .trusted_devices import TrustedDeviceStore


@dataclass(frozen=True, slots=True)
class PairingResult:
    success: bool
    message: str
    request_id: str


class PendingPairingStore:
    SCHEMA_VERSION = 1
    MAX_PENDING_REQUESTS = 100

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def add(self, request: PairingRequest, *, now_ms: int | None = None) -> PairingResult:
        current = _clock_ms() if now_ms is None else int(now_ms)
        request.verify(now_ms=current)
        with self._lock:
            records = self._read()
            self._prune(records, current)
            if request.request_id in records:
                return PairingResult(False, "Pairing request is already pending.", request.request_id)
            if any(item.device.device_id == request.device.device_id for item in records.values()):
                return PairingResult(False, "This device already has a pending request.", request.request_id)
            if len(records) >= self.MAX_PENDING_REQUESTS:
                return PairingResult(False, "Pending pairing capacity is full.", request.request_id)
            records[request.request_id] = request
            self._write(records)
        return PairingResult(True, "Pairing request is awaiting approval.", request.request_id)

    def get(self, request_id: str, *, now_ms: int | None = None) -> PairingRequest | None:
        current = _clock_ms() if now_ms is None else int(now_ms)
        with self._lock:
            records = self._read()
            changed = self._prune(records, current)
            if changed:
                self._write(records)
            return records.get(request_id)

    def list(self, *, now_ms: int | None = None) -> tuple[PairingRequest, ...]:
        current = _clock_ms() if now_ms is None else int(now_ms)
        with self._lock:
            records = self._read()
            changed = self._prune(records, current)
            if changed:
                self._write(records)
            return tuple(sorted(records.values(), key=lambda item: (item.timestamp_ms, item.request_id)))

    def remove(self, request_id: str) -> bool:
        with self._lock:
            records = self._read()
            removed = records.pop(request_id, None)
            if removed is None:
                return False
            self._write(records)
            return True

    def _prune(self, records: dict[str, PairingRequest], now_ms: int) -> bool:
        expired = [
            key for key, request in records.items()
            if request.timestamp_ms < now_ms - PAIRING_MAX_AGE_MS
        ]
        for key in expired:
            records.pop(key)
        return bool(expired)

    def _read(self) -> dict[str, PairingRequest]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PairingError("pending pairing store is unreadable") from exc
        if not isinstance(value, dict) or value.get("schema_version") != self.SCHEMA_VERSION:
            raise PairingError("unsupported pending pairing store schema")
        devices = value.get("requests")
        if not isinstance(devices, list):
            raise PairingError("pending pairing requests must be a list")
        records: dict[str, PairingRequest] = {}
        for item in devices:
            request = PairingRequest.from_dict(item)
            if request.request_id in records:
                raise PairingError("duplicate pending pairing request")
            records[request.request_id] = request
        return records

    def _write(self, records: dict[str, PairingRequest]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        value = {
            "schema_version": self.SCHEMA_VERSION,
            "requests": [records[key].to_dict() for key in sorted(records)],
        }
        content = json.dumps(value, indent=2, sort_keys=True) + "\n"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", delete=False,
                dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp",
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


class PairingService:
    def __init__(
        self,
        pending_store: PendingPairingStore,
        trusted_store: TrustedDeviceStore,
        approver_provider: P256IdentityProvider,
        approver_name: str,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.pending_store = pending_store
        self.trusted_store = trusted_store
        self.approver_provider = approver_provider
        self.approver_name = approver_name
        self.clock_ms = clock_ms or _clock_ms
        self._journal_path = self.pending_store.path.with_name("pairing_approval.journal.json")
        self._recover_approval()

    def receive(self, request: PairingRequest) -> PairingResult:
        return self.pending_store.add(request, now_ms=self.clock_ms())

    def approve(self, request_id: str, permissions: tuple[str, ...]) -> PairingApproval:
        current = self.clock_ms()
        request = self.pending_store.get(request_id, now_ms=current)
        if request is None:
            raise PairingError("pairing request is missing or expired")
        approval = PairingApproval.create(
            request, self.approver_provider, self.approver_name, permissions,
            clock_ms=lambda: current,
        )
        trusted = approval.verify(request, now_ms=current)
        self._write_journal(request_id, trusted.to_dict())
        self.trusted_store.trust(trusted)
        if not self.pending_store.remove(request_id):
            raise PairingError("pairing request changed during approval")
        self._clear_journal()
        return approval

    def reject(self, request_id: str) -> PairingResult:
        removed = self.pending_store.remove(request_id)
        message = "Pairing request rejected." if removed else "Pairing request was not pending."
        return PairingResult(removed, message, request_id)

    def _write_journal(self, request_id: str, trusted: dict) -> None:
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "request_id": request_id, "trusted": trusted}
        temporary = self._journal_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self._journal_path)

    def _clear_journal(self) -> None:
        try:
            self._journal_path.unlink()
        except FileNotFoundError:
            pass

    def _recover_approval(self) -> None:
        if not self._journal_path.exists():
            return
        try:
            payload = json.loads(self._journal_path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != 1:
                raise PairingError("unsupported pairing approval journal schema")
            trusted = self.trusted_store._read_records().get(str(payload["trusted"]["device_id"]))
            if trusted is None:
                from .models import TrustedDevice
                self.trusted_store.trust(TrustedDevice.from_dict(payload["trusted"]))
            self.pending_store.remove(str(payload["request_id"]))
            self._clear_journal()
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise PairingError("pairing approval recovery failed") from exc


def _clock_ms() -> int:
    return time.time_ns() // 1_000_000
