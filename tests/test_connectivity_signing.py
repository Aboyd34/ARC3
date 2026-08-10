import unittest

from app.connectivity.identity import P256IdentityProvider, SignatureError


class ConnectivitySigningTests(unittest.TestCase):
    def setUp(self):
        self.provider = P256IdentityProvider.generate()

    def test_generated_identity_uses_p256_public_jwk(self):
        identity = self.provider.identity("Office PC")
        self.assertEqual("EC", identity.public_key_jwk["kty"])
        self.assertEqual("P-256", identity.public_key_jwk["crv"])
        self.assertEqual(64, len(identity.device_id))

    def test_signature_is_webcrypto_compatible_raw_p256(self):
        payload = b'{"action":"health.read","nonce":"abc"}'
        signature = self.provider.sign(payload)
        self.assertEqual(64, len(signature))
        self.assertTrue(
            P256IdentityProvider.verify(payload, signature, self.provider.public_jwk())
        )
        self.assertFalse(
            P256IdentityProvider.verify(payload + b"!", signature, self.provider.public_jwk())
        )

    def test_private_key_round_trip_preserves_identity(self):
        restored = P256IdentityProvider.from_private_pkcs8(
            self.provider.export_private_pkcs8()
        )
        self.assertEqual(self.provider.public_jwk(), restored.public_jwk())

    def test_public_identity_never_contains_private_scalar(self):
        identity = self.provider.identity("Office PC")
        self.assertNotIn("d", identity.public_key_jwk)
        self.assertNotIn("PRIVATE", str(identity.to_dict()).upper())

    def test_malformed_signature_is_rejected(self):
        with self.assertRaises(SignatureError):
            P256IdentityProvider.verify(b"payload", b"short", self.provider.public_jwk())


if __name__ == "__main__":
    unittest.main()
