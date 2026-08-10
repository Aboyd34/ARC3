import gc
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget

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

    def test_main_window_sidebar_maps_connectivity_and_settings(self):
        from app.main_window import MainWindow

        with (
            patch("app.main_window.WindowsWorkspace", QWidget),
            patch("app.main_window.AndroidWorkspace", QWidget),
            patch("app.main_window.ConnectivityPage", QWidget),
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
