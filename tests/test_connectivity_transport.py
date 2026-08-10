from http.client import HTTPConnection
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid

from app.connectivity.health import RemoteHealthEndpoint
from app.connectivity.identity import P256IdentityProvider
from app.connectivity.models import TrustedDevice
from app.connectivity.protocol import SignedRequest
from app.connectivity.runtime import create_health_transport
from app.connectivity.transport import (
    ConnectivityHTTPServer, REQUEST_PATH, SignedRequestRouter, TransportConfig,
)
from app.connectivity.trusted_devices import TrustedDeviceStore


class FakeCollector:
    def collect(self):
        return {"status": "ok", "cpu": {"percent_used": 10.0}}


class ConnectivityTransportTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).parent / f".transport-trust-{uuid.uuid4().hex}.json"
        self.provider = P256IdentityProvider.generate()
        identity = self.provider.identity("Remote PC")
        self.store = TrustedDeviceStore(self.path)
        self.store.trust(TrustedDevice.from_identity(identity, ["health.read"]))
        router = SignedRequestRouter(
            self.store, RemoteHealthEndpoint(collector=FakeCollector())
        )
        self.server = ConnectivityHTTPServer(router, TransportConfig(port=0))

    def tearDown(self):
        self.server.stop()
        if self.path.exists():
            self.path.unlink()

    def request_value(self):
        return SignedRequest.create(
            self.provider, "Remote PC", "health.read", {},
        ).to_dict()

    def post(self, value, path=REQUEST_PATH, content_type="application/json"):
        if not self.server.running:
            self.server.start()
        connection = HTTPConnection("127.0.0.1", self.server.bound_port, timeout=5)
        body = json.dumps(value).encode("utf-8")
        connection.request("POST", path, body=body, headers={"Content-Type": content_type})
        response = connection.getresponse()
        result = response.status, json.loads(response.read().decode("utf-8"))
        connection.close()
        return result

    def test_signed_health_request_round_trip(self):
        status, value = self.post(self.request_value())
        self.assertEqual(200, status)
        self.assertTrue(value["ok"])
        self.assertEqual("ok", value["result"]["status"])

    def test_replay_is_rejected_without_detail_leak(self):
        value = self.request_value()
        self.assertEqual(200, self.post(value)[0])
        status, response = self.post(value)
        self.assertEqual(400, status)
        self.assertEqual({"ok": False, "error": "request_rejected"}, response)

    def test_wrong_path_and_content_type_are_rejected(self):
        self.assertEqual(404, self.post(self.request_value(), path="/wrong")[0])
        self.assertEqual(415, self.post(self.request_value(), content_type="text/plain")[0])

    def test_non_loopback_requires_explicit_private_lan_flag(self):
        with self.assertRaisesRegex(ValueError, "explicit private-LAN"):
            TransportConfig(host="0.0.0.0")
        with self.assertRaisesRegex(ValueError, "requires TLS"):
            TransportConfig(host="0.0.0.0", allow_private_lan=True)

    def test_private_lan_runtime_requires_explicit_host(self):
        service = SimpleNamespace(trusted_store=self.store)
        with self.assertRaisesRegex(ValueError, "explicit host address"):
            create_health_transport(service, allow_private_lan=True)


if __name__ == "__main__":
    unittest.main()
