"""Versioned, atomic persistence for trusted public device identities."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any

from .models import TrustedDevice


class TrustedDeviceStore:
    """Persist public trust records only; private keys never belong here."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def list(self) -> tuple[TrustedDevice, ...]:
        with self._lock:
            records = self._read_records()
        return tuple(sorted(records.values(), key=lambda item: (item.name.casefold(), item.device_id)))

    def get(self, device_id: str) -> TrustedDevice | None:
        with self._lock:
            return self._read_records().get(device_id.lower())

    def trust(self, device: TrustedDevice) -> None:
        with self._lock:
            records = self._read_records()
            existing = records.get(device.device_id)
            if existing is not None and existing.public_key_jwk != device.public_key_jwk:
                raise ValueError("refusing to replace a trusted fingerprint with different key material")
            records[device.device_id] = device
            self._write_records(records)

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            records = self._read_records()
            removed = records.pop(device_id.lower(), None)
            if removed is None:
                return False
            self._write_records(records)
            return True

    def _read_records(self) -> dict[str, TrustedDevice]:
        if not self.path.exists():
            return {}
        try:
            payload: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"trusted-device store is unreadable: {self.path}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("unsupported trusted-device store schema")
        values = payload.get("devices")
        if not isinstance(values, list):
            raise ValueError("trusted-device store devices must be a list")
        records: dict[str, TrustedDevice] = {}
        for value in values:
            device = TrustedDevice.from_dict(value)
            if device.device_id in records:
                raise ValueError(f"duplicate trusted device: {device.device_id}")
            records[device.device_id] = device
        return records

    def _write_records(self, records: dict[str, TrustedDevice]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "devices": [records[key].to_dict() for key in sorted(records)],
        }
        content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", delete=False,
                dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
