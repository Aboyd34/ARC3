from pathlib import Path
import os
import unittest
from unittest.mock import patch
import uuid

from app.connectivity.identity import P256IdentityProvider
from app.connectivity.windows_key_store import KeyStoreError, WindowsDPAPI, WindowsDPAPIKeyStore


@unittest.skipUnless(os.name == "nt", "Windows DPAPI tests require Windows")
class WindowsKeyStoreTests(unittest.TestCase):
    def test_dpapi_round_trip_is_user_bound_and_not_plaintext(self):
        dpapi = WindowsDPAPI()
        plaintext = b"private-key-test-material"
        entropy = b"ARC3 test entropy"
        protected = dpapi.protect(plaintext, entropy)
        self.assertNotEqual(plaintext, protected)
        self.assertNotIn(plaintext, protected)
        self.assertEqual(plaintext, dpapi.unprotect(protected, entropy))

    def test_store_load_or_create_preserves_identity(self):
        path = Path(__file__).parent / f".dpapi-key-{uuid.uuid4().hex}.bin"
        try:
            store = WindowsDPAPIKeyStore(path)
            created = store.load_or_create()
            self.assertTrue(path.read_bytes().startswith(b"ARC3-DPAPI-P256"))
            self.assertNotIn(created.export_private_pkcs8(), path.read_bytes())
            loaded = store.load_or_create()
            self.assertEqual(created.public_jwk(), loaded.public_jwk())
        finally:
            if path.exists():
                path.unlink()

    def test_corrupt_store_fails_closed(self):
        path = Path(__file__).parent / f".dpapi-key-{uuid.uuid4().hex}.bin"
        try:
            path.write_bytes(b"not-a-valid-store")
            with self.assertRaises(KeyStoreError):
                WindowsDPAPIKeyStore(path).load()
        finally:
            if path.exists():
                path.unlink()

    def test_load_or_create_adopts_identity_created_by_competing_process(self):
        path = Path(__file__).parent / f".dpapi-key-{uuid.uuid4().hex}.bin"
        store = WindowsDPAPIKeyStore(path)
        existing = P256IdentityProvider.generate()
        try:
            with patch.object(store, "_write_if_absent", return_value=False), patch.object(
                store, "load", return_value=existing
            ) as load:
                result = store.load_or_create()
            self.assertIs(existing, result)
            load.assert_called_once_with()
        finally:
            if path.exists():
                path.unlink()


if __name__ == "__main__":
    unittest.main()
