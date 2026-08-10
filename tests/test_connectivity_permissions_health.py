import unittest

from app.connectivity.health import RemoteHealthEndpoint
from app.connectivity.identity import P256IdentityProvider
from app.connectivity.models import TrustedDevice
from app.connectivity.permissions import PermissionDenied, PermissionPolicy
from app.connectivity.protocol import ReplayGuard, SignedRequest


NOW = 2_000_000_000_000


class FakeCollector:
    def __init__(self):
        self.calls = 0

    def collect(self):
        self.calls += 1
        return {"status": "ok", "cpu": {"percent_used": 12.5}}


class ConnectivityPermissionHealthTests(unittest.TestCase):
    def setUp(self):
        self.provider = P256IdentityProvider.generate()
        self.identity = self.provider.identity("Office PC")

    def request(self, action="health.read"):
        return SignedRequest.create(
            self.provider, "Office PC", action, {},
            clock_ms=lambda: NOW,
            nonce_factory=lambda: "MDEyMzQ1Njc4OWFiY2RlZg",
        )

    def test_permission_policy_allows_explicit_grant(self):
        trusted = TrustedDevice.from_identity(self.identity, ["health.read"])
        result = PermissionPolicy().verify_and_authorize(
            self.request(), trusted, ReplayGuard(), now_ms=NOW
        )
        self.assertEqual("health.read", result.permission)

    def test_permission_policy_denies_missing_grant(self):
        trusted = TrustedDevice.from_identity(self.identity)
        with self.assertRaisesRegex(PermissionDenied, "lacks permission"):
            PermissionPolicy().verify_and_authorize(
                self.request(), trusted, ReplayGuard(), now_ms=NOW
            )

    def test_unknown_action_fails_closed(self):
        trusted = TrustedDevice.from_identity(self.identity, ["admin.all"])
        with self.assertRaisesRegex(PermissionDenied, "not registered"):
            PermissionPolicy().verify_and_authorize(
                self.request("admin.execute"), trusted, ReplayGuard(), now_ms=NOW
            )

    def test_health_endpoint_invokes_only_injected_read_collector(self):
        collector = FakeCollector()
        endpoint = RemoteHealthEndpoint(collector=collector)
        trusted = TrustedDevice.from_identity(self.identity, ["health.read"])
        result = endpoint.handle(self.request(), trusted, ReplayGuard(), now_ms=NOW)
        self.assertEqual("ok", result["status"])
        self.assertEqual(1, collector.calls)

    def test_health_endpoint_rejects_other_action_without_collection(self):
        collector = FakeCollector()
        endpoint = RemoteHealthEndpoint(collector=collector)
        trusted = TrustedDevice.from_identity(self.identity, ["health.read"])
        with self.assertRaisesRegex(ValueError, "only health.read"):
            endpoint.handle(
                self.request("process.list"), trusted, ReplayGuard(), now_ms=NOW
            )
        self.assertEqual(0, collector.calls)


if __name__ == "__main__":
    unittest.main()
