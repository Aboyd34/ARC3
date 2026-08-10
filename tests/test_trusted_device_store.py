import json
from pathlib import Path
import tempfile
import unittest

from app.connectivity.models import DeviceIdentity, TrustedDevice
from app.connectivity.trusted_devices import TrustedDeviceStore


class TrustedDeviceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "connectivity" / "trusted_devices.json"
        self.store = TrustedDeviceStore(self.path)
        identity = DeviceIdentity(
            "Office PC", {"kty": "EC", "crv": "P-256", "x": "example-x", "y": "example-y"}
        )
        self.device = TrustedDevice.from_identity(identity, ["health.read"])

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_round_trip_and_revoke(self):
        self.store.trust(self.device)
        self.assertEqual(self.device, self.store.get(self.device.device_id))
        self.assertEqual((self.device,), self.store.list())
        self.assertTrue(self.store.revoke(self.device.device_id))
        self.assertFalse(self.store.revoke(self.device.device_id))

    def test_store_contains_public_material_only(self):
        self.store.trust(self.device)
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("private", text.lower())
        self.assertEqual(1, json.loads(text)["schema_version"])

    def test_corrupt_store_fails_closed(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("not-json", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.list()


if __name__ == "__main__":
    unittest.main()
