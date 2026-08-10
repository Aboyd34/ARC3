from pathlib import Path
import json
import unittest
import uuid

from app.connectivity.identity import P256IdentityProvider
from app.connectivity.pairing import PairingError, PairingRequest
from app.connectivity.models import TrustedDevice
from app.connectivity.pairing_service import PairingService, PendingPairingStore
from app.connectivity.trusted_devices import TrustedDeviceStore


NOW = 2_000_000_000_000


class PairingServiceTests(unittest.TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex
        self.pending_path = Path(__file__).parent / f".pending-{suffix}.json"
        self.trusted_path = Path(__file__).parent / f".trusted-{suffix}.json"
        self.pending = PendingPairingStore(self.pending_path)
        self.trusted = TrustedDeviceStore(self.trusted_path)
        self.approver = P256IdentityProvider.generate()
        self.service = PairingService(
            self.pending, self.trusted, self.approver, "Office PC", lambda: NOW
        )
        self.requester = P256IdentityProvider.generate()
        self.request = PairingRequest.create(
            self.requester, "Remote PC", clock_ms=lambda: NOW,
            nonce_factory=lambda: "MDEyMzQ1Njc4OWFiY2RlZg",
        )

    def tearDown(self):
        journal = self.pending_path.with_name("pairing_approval.journal.json")
        for path in (
            self.pending_path, self.trusted_path, journal,
            journal.with_suffix(journal.suffix + ".corrupt"),
        ):
            if path.exists():
                path.unlink()

    def test_receive_duplicate_and_explicit_approval(self):
        self.assertTrue(self.service.receive(self.request).success)
        self.assertFalse(self.service.receive(self.request).success)
        approval = self.service.approve(self.request.request_id, ("health.read",))
        self.assertEqual(self.request.request_id, approval.request_id)
        trusted = self.trusted.get(self.request.device.device_id)
        self.assertIsNotNone(trusted)
        self.assertEqual(("health.read",), trusted.permissions)
        self.assertEqual((), self.pending.list(now_ms=NOW))

    def test_only_one_pending_request_per_device(self):
        self.assertTrue(self.service.receive(self.request).success)
        second = PairingRequest.create(
            self.requester, "Remote PC", clock_ms=lambda: NOW,
            nonce_factory=lambda: "ZmVkY2JhOTg3NjU0MzIxMA",
        )
        self.assertFalse(self.service.receive(second).success)

    def test_rejection_does_not_create_trust(self):
        self.service.receive(self.request)
        self.assertTrue(self.service.reject(self.request.request_id).success)
        self.assertIsNone(self.trusted.get(self.request.device.device_id))

    def test_expired_request_is_pruned_and_cannot_be_approved(self):
        self.service.receive(self.request)
        self.service.clock_ms = lambda: NOW + 600_001
        with self.assertRaisesRegex(PairingError, "missing or expired"):
            self.service.approve(self.request.request_id, ("health.read",))
        self.assertEqual((), self.pending.list(now_ms=NOW + 600_001))

    def test_approval_journal_recovers_after_interruption(self):
        self.service.receive(self.request)
        trusted = TrustedDevice.from_identity(self.request.device, ("health.read",))
        journal = self.pending_path.with_name("pairing_approval.journal.json")
        journal.write_text(json.dumps({"schema_version": 1, "request_id": self.request.request_id, "trusted": trusted.to_dict()}), encoding="utf-8")
        recovered = PairingService(self.pending, self.trusted, self.approver, "Office PC", lambda: NOW)
        self.assertIsNotNone(recovered.trusted_store.get(self.request.device.device_id))
        self.assertIsNone(self.pending.get(self.request.request_id, now_ms=NOW))
        self.assertFalse(journal.exists())

    def test_corrupt_approval_journal_is_quarantined_without_blocking_startup(self):
        journal = self.pending_path.with_name("pairing_approval.journal.json")
        journal.write_text("not-json", encoding="utf-8")
        recovered = PairingService(
            self.pending, self.trusted, self.approver, "Office PC", lambda: NOW
        )
        self.assertIn("quarantined", recovered.recovery_error)
        self.assertFalse(journal.exists())
        self.assertTrue(journal.with_suffix(journal.suffix + ".corrupt").exists())


if __name__ == "__main__":
    unittest.main()
