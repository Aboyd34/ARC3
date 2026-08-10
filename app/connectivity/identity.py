"""P-256 identity generation and WebCrypto-compatible signing.

This module intentionally owns key operations but not key persistence. A later
Windows provider can protect the serialized private key with DPAPI without
changing callers or the public identity model.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

from .models import DeviceIdentity, canonical_public_key


P256_FIELD_SIZE = 32
P256_RAW_SIGNATURE_SIZE = P256_FIELD_SIZE * 2


class SignatureError(ValueError):
    """Raised when signature or public-key input is malformed."""


@runtime_checkable
class IdentityProvider(Protocol):
    """Minimal private-key boundary used by Connectivity services."""

    def identity(self, name: str) -> DeviceIdentity: ...

    def sign(self, payload: bytes) -> bytes: ...

    def export_private_pkcs8(self) -> bytes: ...


@dataclass(slots=True)
class P256IdentityProvider:
    """An in-memory P-256 key provider with explicit persistence handoff."""

    _private_key: ec.EllipticCurvePrivateKey

    @classmethod
    def generate(cls) -> "P256IdentityProvider":
        return cls(ec.generate_private_key(ec.SECP256R1()))

    @classmethod
    def from_private_pkcs8(cls, private_key_der: bytes) -> "P256IdentityProvider":
        try:
            key = serialization.load_der_private_key(bytes(private_key_der), password=None)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid unencrypted PKCS#8 private key") from exc
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError("private key must use P-256")
        return cls(key)

    def identity(self, name: str) -> DeviceIdentity:
        return DeviceIdentity(name, self.public_jwk())

    def public_jwk(self) -> dict[str, str]:
        numbers = self._private_key.public_key().public_numbers()
        return {
            "kty": "EC",
            "crv": "P-256",
            "x": _base64url(numbers.x.to_bytes(P256_FIELD_SIZE, "big")),
            "y": _base64url(numbers.y.to_bytes(P256_FIELD_SIZE, "big")),
        }

    def sign(self, payload: bytes) -> bytes:
        """Return a 64-byte IEEE-P1363 signature matching WebCrypto ECDSA."""
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        der_signature = self._private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
        r_value, s_value = decode_dss_signature(der_signature)
        return r_value.to_bytes(P256_FIELD_SIZE, "big") + s_value.to_bytes(
            P256_FIELD_SIZE, "big"
        )

    def export_private_pkcs8(self) -> bytes:
        """Export for immediate handoff to an OS-protected key store."""
        return self._private_key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

    @staticmethod
    def verify(payload: bytes, signature: bytes, public_key_jwk: Mapping[str, Any]) -> bool:
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        if not isinstance(signature, bytes) or len(signature) != P256_RAW_SIGNATURE_SIZE:
            raise SignatureError("P-256 signature must be exactly 64 bytes")
        public_key = _public_key_from_jwk(public_key_jwk)
        r_value = int.from_bytes(signature[:P256_FIELD_SIZE], "big")
        s_value = int.from_bytes(signature[P256_FIELD_SIZE:], "big")
        try:
            public_key.verify(
                encode_dss_signature(r_value, s_value), payload, ec.ECDSA(hashes.SHA256())
            )
        except InvalidSignature:
            return False
        return True


def _public_key_from_jwk(public_key_jwk: Mapping[str, Any]) -> ec.EllipticCurvePublicKey:
    # Validate and discard unknown/private fields before decoding coordinates.
    import json

    try:
        public_only = json.loads(canonical_public_key(public_key_jwk))
        x_value = int.from_bytes(_base64url_decode(public_only["x"]), "big")
        y_value = int.from_bytes(_base64url_decode(public_only["y"]), "big")
        return ec.EllipticCurvePublicNumbers(
            x_value, y_value, ec.SECP256R1()
        ).public_key()
    except (TypeError, ValueError) as exc:
        raise SignatureError("invalid P-256 public JWK coordinates") from exc


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise SignatureError("JWK coordinate must be a base64url string")
    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise SignatureError("invalid base64url JWK coordinate") from exc
    if len(decoded) != P256_FIELD_SIZE:
        raise SignatureError("P-256 JWK coordinates must be 32 bytes")
    return decoded
