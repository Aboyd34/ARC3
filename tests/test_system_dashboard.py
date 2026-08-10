import gc
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

from app.dashboard import DashboardPage
from app.services.health_engine import HealthMetric, HealthSnapshot, HealthState
from app.ui.phase4_enhancements import refresh_visible_page


def make_snapshot(overall=HealthState.WARNING):
    healthy = HealthMetric("ARC3 application", HealthState.HEALTHY, 1, "Process running")
    warning = HealthMetric("CPU", HealthState.WARNING, 82.0, "8 logical processors")
    return HealthSnapshot(
        collected_at=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        overall_state=overall,
        cpu=warning,
        memory=HealthMetric("Memory", HealthState.HEALTHY, 40.0, "4.0 GB used"),
        storage=HealthMetric("Primary storage", HealthState.HEALTHY, 50.0, "50.0 GB used"),
        uptime=HealthMetric("Windows uptime", HealthState.HEALTHY, 90061, "1d 1h 1m"),
        application=healthy,
        warnings=("CPU: WARNING - 8 logical processors",),
    )


class SystemDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        gc.collect()

    def test_snapshot_populates_summary_metrics_and_warnings(self):
        page = DashboardPage(service=Mock(), auto_refresh=False)
        page._snapshot_loaded(make_snapshot())

        self.assertEqual("WARNING", page.overall_card.value_label.text())
        self.assertEqual("82.0%", page.cpu_card.value_label.text())
        self.assertEqual("1d 1h 1m", page.uptime_card.value_label.text())
        self.assertIn("CPU: WARNING", page.warnings_label.text())
        page.deleteLater()

    def test_refresh_is_guarded_while_collection_is_active(self):
        page = DashboardPage(service=Mock(), auto_refresh=False)
        sentinel = object()
        page.refresh_thread = sentinel

        self.assertFalse(page.refresh())
        page.refresh_thread = None
        page.deleteLater()

    def test_f5_dispatches_exactly_once_to_dashboard_refresh(self):
        page = QWidget()
        page.refresh = Mock(return_value=True)
        window = QWidget()
        window.pages = QStackedWidget(window)
        window.pages.addWidget(page)
        window.show_arc3_notification = Mock()

        self.assertTrue(refresh_visible_page(window))
        page.refresh.assert_called_once_with()
        window.show_arc3_notification.assert_called_once()
        window.deleteLater()


if __name__ == "__main__":
    unittest.main()
