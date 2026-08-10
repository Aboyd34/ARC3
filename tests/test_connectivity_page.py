import gc
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from app.connectivity.identity import P256IdentityProvider
from app.connectivity.pairing_service import PairingService, PendingPairingStore
from app.connectivity.trusted_devices import TrustedDeviceStore
from app.pages.connectivity_page import ConnectivityPage


class ConnectivityPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        suffix = uuid.uuid4().hex
        self.paths = (
            Path(__file__).parent / f".ui-pending-{suffix}.json",
            Path(__file__).parent / f".ui-trusted-{suffix}.json",
        )
        self.service = PairingService(
            PendingPairingStore(self.paths[0]), TrustedDeviceStore(self.paths[1]),
            P256IdentityProvider.generate(), "Test ARC3 PC",
        )

    def tearDown(self):
        for path in self.paths:
            if path.exists():
                path.unlink()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        gc.collect()

    def test_page_builds_and_starts_with_safe_controls(self):
        page = ConnectivityPage(pairing_service=self.service)
        self.assertIn("Fingerprint:", page.identity_label.text())
        self.assertTrue(page.health_permission.isChecked())
        self.assertFalse(page.approve_button.isEnabled())
        self.assertFalse(page.reject_button.isEnabled())
        self.assertEqual("Start Listener", page.listener_button.text())
        self.assertFalse(page.lan_checkbox.isChecked())
        self.assertEqual(0, page.pending_list.count())
        page.close()
        page.deleteLater()

    def test_shutdown_stops_running_listener(self):
        page = ConnectivityPage(pairing_service=self.service)
        transport = Mock()
        page.transport = transport
        page.shutdown()
        transport.stop.assert_called_once_with()
        self.assertIsNone(page.transport)
        page.deleteLater()

    def test_private_lan_uses_selected_interface_and_app_data_tls(self):
        page = ConnectivityPage(pairing_service=self.service)
        page.lan_address.clear()
        page.lan_address.addItem("192.168.1.25")
        page.lan_checkbox.setChecked(True)
        transport = Mock()
        transport.running = False
        with tempfile.TemporaryDirectory() as local_app_data, patch.dict(
            os.environ, {"LOCALAPPDATA": local_app_data}
        ), patch(
            "app.pages.connectivity_page.QMessageBox.question",
            return_value=QMessageBox.Yes,
        ), patch(
            "app.pages.connectivity_page.create_health_transport",
            return_value=transport,
        ) as create_transport:
            page.toggle_listener()
        kwargs = create_transport.call_args.kwargs
        self.assertEqual("192.168.1.25", kwargs["host"])
        self.assertTrue(str(kwargs["tls_keyfile"]).startswith(local_app_data))
        transport.start.assert_called_once_with()
        page.shutdown()
        page.deleteLater()

    def test_main_window_sidebar_maps_connectivity_and_settings(self):
        from app.main_window import MainWindow

        class StubConnectivityPage(QWidget):
            def __init__(self, *_):
                super().__init__()

            def shutdown(self):
                pass

        with (
            patch("app.main_window.WindowsWorkspace", QWidget),
            patch("app.main_window.AndroidWorkspace", QWidget),
            patch("app.main_window.ConnectivityPage", StubConnectivityPage),
        ):
            window = MainWindow()

        self.assertEqual(window.pages.count(), window.sidebar.count())
        self.assertEqual(window.navigation_names, [
            window.sidebar.item(index).text()
            for index in range(window.sidebar.count())
        ])
        window.sidebar.setCurrentRow(6)
        self.assertEqual(6, window.pages.currentIndex())
        self.assertEqual("Opened Connectivity", window.statusBar().currentMessage())
        window.sidebar.setCurrentRow(7)
        self.assertEqual(7, window.pages.currentIndex())
        self.assertEqual("Opened Settings", window.statusBar().currentMessage())
        window.close()
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
