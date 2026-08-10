import unittest

from app.connectivity.models import DeviceIdentity, TrustedDevice, canonical_public_key


PUBLIC_JWK = {"kty": "EC", "crv": "P-256", "x": "example-x", "y": "example-y"}


class ConnectivityIdentityTests(unittest.TestCase):
    def test_identity_fingerprint_is_stable_for_equivalent_jwk(self):
        left = DeviceIdentity("Office PC", PUBLIC_JWK)
        right = DeviceIdentity("Renamed PC", dict(reversed(list(PUBLIC_JWK.items()))))
        self.assertEqual(left.device_id, right.device_id)
        self.assertEqual(64, len(left.device_id))

    def test_private_jwk_fields_are_not_retained(self):
        identity = DeviceIdentity("Office PC", {**PUBLIC_JWK, "d": "private-value"})
        self.assertNotIn("d", identity.public_key_jwk)
        self.assertNotIn("private-value", canonical_public_key(identity.public_key_jwk))

    def test_trusted_device_normalizes_permissions(self):
        identity = DeviceIdentity("Office PC", PUBLIC_JWK)
        trusted = TrustedDevice.from_identity(identity, ["Health.Read", "health.read", "process.list"])
        self.assertEqual(("health.read", "process.list"), trusted.permissions)

    def test_trusted_device_rejects_mismatched_fingerprint(self):
        with self.assertRaises(ValueError):
            TrustedDevice("0" * 64, "Office PC", PUBLIC_JWK)


if __name__ == "__main__":
    unittest.main()
