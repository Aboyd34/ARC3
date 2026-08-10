import unittest

from app.connectivity.identity import P256IdentityProvider
from app.connectivity.pairing import PairingApproval, PairingError, PairingRequest


NOW = 2_000_000_000_000
REQUEST_NONCE = "MDEyMzQ1Njc4OWFiY2RlZg"
APPROVAL_NONCE = "ZmVkY2JhOTg3NjU0MzIxMA"


class ConnectivityPairingTests(unittest.TestCase):
    def setUp(self):
        self.requester = P256IdentityProvider.generate()
        self.approver = P256IdentityProvider.generate()
        self.request = PairingRequest.create(
            self.requester, "Remote PC", clock_ms=lambda: NOW,
            nonce_factory=lambda: REQUEST_NONCE,
        )

    def test_request_is_self_signed_and_has_stable_id(self):
        restored = PairingRequest.from_dict(self.request.to_dict())
        restored.verify(now_ms=NOW)
        self.assertEqual(64, len(self.request.request_id))
        self.assertEqual(self.request.request_id, restored.request_id)

    def test_approval_creates_trusted_device_only_after_verification(self):
        approval = PairingApproval.create(
            self.request, self.approver, "Office PC",
            ("health.read", "health.read"), clock_ms=lambda: NOW,
            nonce_factory=lambda: APPROVAL_NONCE,
        )
        trusted = approval.verify(self.request, now_ms=NOW)
        self.assertEqual(self.request.device.device_id, trusted.device_id)
        self.assertEqual(("health.read",), trusted.permissions)
        restored = PairingApproval.from_dict(approval.to_dict())
        self.assertEqual(trusted, restored.verify(self.request, now_ms=NOW))

    def test_unknown_transport_fields_fail_closed(self):
        value = self.request.to_dict()
        value["unexpected"] = True
        with self.assertRaisesRegex(PairingError, "fields"):
            PairingRequest.from_dict(value)

    def test_tampered_request_fails_verification(self):
        tampered = PairingRequest(
            self.request.device, self.request.timestamp_ms, APPROVAL_NONCE,
            self.request.signature,
        )
        with self.assertRaisesRegex(PairingError, "signature is invalid"):
            tampered.verify(now_ms=NOW)

    def test_approval_cannot_be_applied_to_another_request(self):
        approval = PairingApproval.create(
            self.request, self.approver, "Office PC", ("health.read",),
            clock_ms=lambda: NOW, nonce_factory=lambda: APPROVAL_NONCE,
        )
        other = PairingRequest.create(
            P256IdentityProvider.generate(), "Other PC", clock_ms=lambda: NOW,
            nonce_factory=lambda: REQUEST_NONCE,
        )
        with self.assertRaisesRegex(PairingError, "does not match"):
            approval.verify(other, now_ms=NOW)

    def test_expired_request_cannot_be_approved(self):
        with self.assertRaisesRegex(PairingError, "expired"):
            PairingApproval.create(
                self.request, self.approver, "Office PC", ("health.read",),
                clock_ms=lambda: NOW + 600_001,
                nonce_factory=lambda: APPROVAL_NONCE,
            )


if __name__ == "__main__":
    unittest.main()
