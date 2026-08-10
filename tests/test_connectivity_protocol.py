import unittest
import tempfile
import os

from app.connectivity.identity import P256IdentityProvider
from app.connectivity.models import TrustedDevice
from app.connectivity.protocol import ReplayGuard, SignedRequest, VerificationError


NOW = 2_000_000_000_000
NONCE = "MDEyMzQ1Njc4OWFiY2RlZg"  # base64url for exactly 16 bytes


class ConnectivityProtocolTests(unittest.TestCase):

    def test_replay_guard_persists_across_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "replay.json")
            first = ReplayGuard(path=path)
            first.check_and_record("a" * 64, "AQEBAQEBAQEBAQEBAQEBAQ", 1000, 1000)
            second = ReplayGuard(path=path)
            with self.assertRaises(VerificationError):
                second.check_and_record("a" * 64, "AQEBAQEBAQEBAQEBAQEBAQ", 1000, 1000)
    def setUp(self):
        self.provider = P256IdentityProvider.generate()
        identity = self.provider.identity("Office PC")
        self.trusted = TrustedDevice.from_identity(identity, ["health.read"])

    def request(self, **overrides):
        values = {
            "provider": self.provider,
            "name": "Office PC",
            "action": "health.read",
            "payload": {"sections": ["cpu", "memory"]},
            "clock_ms": lambda: NOW,
            "nonce_factory": lambda: NONCE,
        }
        values.update(overrides)
        return SignedRequest.create(**values)

    def test_canonical_round_trip_and_verification(self):
        request = self.request()
        restored = SignedRequest.from_dict(request.to_dict())
        restored.verify(self.trusted, ReplayGuard(), now_ms=NOW)
        self.assertEqual(request.canonical_unsigned(), restored.canonical_unsigned())

    def test_tampered_payload_fails_signature(self):
        request = self.request()
        tampered = SignedRequest.from_dict(
            {**request.to_dict(), "payload": {"sections": ["cpu", "secrets"]}}
        )
        with self.assertRaisesRegex(VerificationError, "signature is invalid"):
            tampered.verify(self.trusted, ReplayGuard(), now_ms=NOW)

    def test_replayed_nonce_is_rejected_after_valid_signature(self):
        request = self.request()
        guard = ReplayGuard()
        request.verify(self.trusted, guard, now_ms=NOW)
        with self.assertRaisesRegex(VerificationError, "already been used"):
            request.verify(self.trusted, guard, now_ms=NOW)

    def test_expired_and_future_requests_are_rejected(self):
        expired = self.request(clock_ms=lambda: NOW - 300_001)
        future = self.request(clock_ms=lambda: NOW + 30_001)
        with self.assertRaisesRegex(VerificationError, "expired"):
            expired.verify(self.trusted, ReplayGuard(), now_ms=NOW)
        with self.assertRaisesRegex(VerificationError, "future"):
            future.verify(self.trusted, ReplayGuard(), now_ms=NOW)

    def test_wrong_trusted_device_is_rejected(self):
        other = P256IdentityProvider.generate().identity("Other PC")
        with self.assertRaisesRegex(VerificationError, "not the supplied trusted device"):
            self.request().verify(
                TrustedDevice.from_identity(other), ReplayGuard(), now_ms=NOW
            )

    def test_unknown_fields_fail_closed(self):
        value = self.request().to_dict()
        value["unexpected"] = True
        with self.assertRaisesRegex(VerificationError, "fields"):
            SignedRequest.from_dict(value)

    def test_nonce_must_have_at_least_128_bits(self):
        with self.assertRaisesRegex(ValueError, "128 bits"):
            self.request(nonce_factory=lambda: "c2hvcnQ")


if __name__ == "__main__":
    unittest.main()
