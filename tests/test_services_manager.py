from __future__ import annotations

import os
import subprocess
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import psutil
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from app.pages.windows.services_tab import ServicesTab
from app.services.services_service import ServicesService
from app.ui.phase4_enhancements import (
    install_refresh_shortcut,
    refresh_visible_page,
)


class FakeWindowsService:
    def __init__(self, details):
        self.details = details

    def as_dict(self):
        return dict(self.details)

    def name(self):
        return self.details["name"]


class MissingWindowsService:
    def as_dict(self):
        raise psutil.NoSuchProcess(pid=0)


class ServicesServiceTests(unittest.TestCase):
    def test_service_discovery_normalizes_and_sorts(self):
        discovered = [
            FakeWindowsService(
                {
                    "name": "Zulu",
                    "display_name": "Zulu Service",
                    "status": "stopped",
                    "start_type": "manual",
                    "pid": None,
                    "description": "",
                }
            ),
            FakeWindowsService(
                {
                    "name": "Alpha",
                    "display_name": "Alpha Service",
                    "status": "running",
                    "start_type": "automatic",
                    "pid": 42,
                    "description": "Example",
                }
            ),
        ]

        with patch(
            "app.services.services_service.psutil.win_service_iter",
            return_value=discovered,
        ):
            services = ServicesService().collect_services()

        self.assertEqual(
            [service["name"] for service in services],
            ["Alpha", "Zulu"],
        )
        self.assertEqual(services[0]["status"], "Running")
        self.assertEqual(services[0]["startup_type"], "Automatic")
        self.assertEqual(services[0]["pid"], 42)
        self.assertEqual(services[1]["pid"], 0)

    def test_service_discovery_skips_vanished_service(self):
        with patch(
            "app.services.services_service.psutil.win_service_iter",
            return_value=[MissingWindowsService()],
        ):
            services = ServicesService().collect_services()

        self.assertEqual(services, [])

    def test_action_dispatch_uses_sc_without_shell(self):
        service = ServicesService()

        with (
            patch.object(
                service,
                "_service_status",
                return_value="stopped",
            ),
            patch.object(
                service,
                "_run_control",
                return_value={
                    "success": True,
                    "action": "start",
                    "message": "accepted",
                    "error": "",
                },
            ) as control,
            patch.object(
                service,
                "_wait_for_status",
                return_value={
                    "success": True,
                    "action": "start",
                    "message": "running",
                    "error": "",
                },
            ),
        ):
            result = service.perform_action("ExampleSvc", "start")

        self.assertTrue(result["success"])
        control.assert_called_once_with(
            "ExampleSvc",
            "start",
            "start",
        )

    def test_permission_error_is_mapped_cleanly(self):
        result = ServicesService()._map_control_error(
            5,
            "[SC] OpenService FAILED 5: Access is denied.",
            "stop",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "access_denied")
        self.assertIn("administrator", result["message"])

    def test_control_timeout_is_reported_cleanly(self):
        service = ServicesService()

        with patch(
            "app.services.services_service.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                cmd=["sc.exe"],
                timeout=12,
            ),
        ):
            result = service._run_control(
                "ExampleSvc",
                "stop",
                "stop",
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "timeout")

    def test_missing_and_unsupported_actions_are_reported(self):
        service = ServicesService()

        unsupported = service.perform_action("ExampleSvc", "delete")
        self.assertEqual(unsupported["error"], "unsupported")

        with patch.object(
            service,
            "_service_status",
            side_effect=psutil.NoSuchProcess(pid=0),
        ):
            missing = service.perform_action("MissingSvc", "start")

        self.assertEqual(missing["error"], "missing")


class ServicesTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = ServicesTab(auto_refresh=False)

    def tearDown(self):
        deadline = time.monotonic() + 3
        while (
            self.tab.refresh_thread is not None
            or self.tab.action_thread is not None
        ) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.tab.deleteLater()
        self.app.processEvents()

    @staticmethod
    def sample_services():
        return [
            {
                "name": "AlphaSvc",
                "display_name": "Alpha Service",
                "status": "Running",
                "startup_type": "Automatic",
                "pid": 100,
                "description": "Alpha description",
            },
            {
                "name": "BetaSvc",
                "display_name": "Beta Service",
                "status": "Stopped",
                "startup_type": "Manual",
                "pid": 0,
                "description": "Beta description",
            },
        ]

    def test_search_filter_behavior(self):
        self.tab.services = self.sample_services()
        self.tab.populate_table()

        self.tab.apply_filter("beta description")

        self.assertTrue(self.tab.table.isRowHidden(0))
        self.assertFalse(self.tab.table.isRowHidden(1))
        self.assertEqual(
            self.tab.count_label.text(),
            "1 matching services",
        )

    def test_refresh_uses_worker_and_populates_table(self):
        self.tab.service.collect_services = Mock(
            return_value=self.sample_services()
        )

        self.tab.refresh()
        deadline = time.monotonic() + 5
        while (
            self.tab.refresh_thread is not None
            and time.monotonic() < deadline
        ):
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()

        self.assertIsNone(self.tab.refresh_thread)
        self.assertEqual(self.tab.table.rowCount(), 2)
        self.tab.service.collect_services.assert_called_once_with()

    def test_action_confirmation_defaults_to_no(self):
        self.tab.services = self.sample_services()
        self.tab.populate_table()
        self.tab.table.selectRow(0)
        self.app.processEvents()

        with (
            patch(
                "app.pages.windows.services_tab.QMessageBox.question",
                return_value=QMessageBox.No,
            ) as question,
            patch.object(self.tab, "_start_action") as start_action,
        ):
            self.tab.request_action("stop")

        self.assertEqual(question.call_args.args[-1], QMessageBox.No)
        start_action.assert_not_called()

    def test_f5_services_refreshes_exactly_once(self):
        calls = []
        self.tab.refresh = lambda: calls.append("refresh")
        tabs = SimpleNamespace(currentWidget=lambda: self.tab)
        workspace = SimpleNamespace(tabs=tabs)
        pages = SimpleNamespace(currentWidget=lambda: workspace)
        window = SimpleNamespace(
            pages=pages,
            show_arc3_notification=lambda *args: None,
        )

        refreshed = refresh_visible_page(window)

        self.assertTrue(refreshed)
        self.assertEqual(calls, ["refresh"])

    def test_refresh_shortcut_installation_is_idempotent(self):
        window = QMainWindow()
        window.pages = QStackedWidget()
        window.pages.addWidget(QWidget())

        first = install_refresh_shortcut(window)
        second = install_refresh_shortcut(window)

        self.assertIs(first, second)
        self.assertIs(window.arc3_refresh_shortcut, first)
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
