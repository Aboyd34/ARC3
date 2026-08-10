"""Pure domain models for ARC3 device identity and trust.

The wire concepts reuse Conduit's P-256/JWK identity work while keeping private
key material out of the model and storage layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping


_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def canonical_public_key(public_key_jwk: Mapping[str, Any]) -> str:
    """Return stable JSON for a public JWK suitable for hashing and signing."""
    required = {"kty", "crv", "x", "y"}
    if not required.issubset(public_key_jwk):
        missing = ", ".join(sorted(required - set(public_key_jwk)))
        raise ValueError(f"public JWK is missing: {missing}")
    if public_key_jwk["kty"] != "EC" or public_key_jwk["crv"] != "P-256":
        raise ValueError("ARC3 Connectivity currently requires an EC P-256 public JWK")
    public_only = {key: public_key_jwk[key] for key in sorted(required)}
    return json.dumps(public_only, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint_public_key(public_key_jwk: Mapping[str, Any]) -> str:
    """Create a full SHA-256 fingerprint from canonical public key material."""
    return sha256(canonical_public_key(public_key_jwk).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    name: str
    public_key_jwk: Mapping[str, Any]
    device_id: str = field(init=False)

    def __post_init__(self) -> None:
        clean_name = self.name.strip()
        if not clean_name:
            raise ValueError("device name cannot be blank")
        canonical = canonical_public_key(self.public_key_jwk)
        public_key = json.loads(canonical)
        object.__setattr__(self, "name", clean_name)
        object.__setattr__(self, "public_key_jwk", public_key)
        object.__setattr__(self, "device_id", sha256(canonical.encode("utf-8")).hexdigest())

    @property
    def fingerprint(self) -> str:
        return self.device_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "public_key_jwk": dict(self.public_key_jwk),
        }


@dataclass(frozen=True, slots=True)
class TrustedDevice:
    device_id: str
    name: str
    public_key_jwk: Mapping[str, Any]
    permissions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        clean_name = self.name.strip()
        if not clean_name:
            raise ValueError("trusted device name cannot be blank")
        device_id = self.device_id.lower()
        if not _HEX_64.fullmatch(device_id):
            raise ValueError("device_id must be a 64-character SHA-256 fingerprint")
        canonical = canonical_public_key(self.public_key_jwk)
        if fingerprint_public_key(self.public_key_jwk) != device_id:
            raise ValueError("device_id does not match the supplied public key")
        permissions = _normalize_permissions(self.permissions)
        object.__setattr__(self, "device_id", device_id)
        object.__setattr__(self, "name", clean_name)
        object.__setattr__(self, "public_key_jwk", json.loads(canonical))
        object.__setattr__(self, "permissions", permissions)

    @classmethod
    def from_identity(
        cls, identity: DeviceIdentity, permissions: Iterable[str] = ()
    ) -> "TrustedDevice":
        return cls(identity.device_id, identity.name, identity.public_key_jwk, tuple(permissions))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrustedDevice":
        return cls(
            device_id=str(value["device_id"]),
            name=str(value["name"]),
            public_key_jwk=value["public_key_jwk"],
            permissions=tuple(value.get("permissions", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "public_key_jwk": dict(self.public_key_jwk),
            "permissions": list(self.permissions),
        }


def _normalize_permissions(values: Iterable[str]) -> tuple[str, ...]:
    normalized = []
    for value in values:
        permission = str(value).strip().lower()
        if not permission or not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,63}", permission):
            raise ValueError(f"invalid permission: {value!r}")
        normalized.append(permission)
    return tuple(sorted(set(normalized)))
