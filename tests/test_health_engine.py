import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.health_engine import HealthEngine, HealthState


class HealthEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = HealthEngine("C:\\")

    @patch("app.services.health_engine.psutil.Process")
    @patch("app.services.health_engine.psutil.boot_time", return_value=1_000)
    @patch("app.services.health_engine.datetime")
    @patch("app.services.health_engine.psutil.disk_usage")
    @patch("app.services.health_engine.psutil.virtual_memory")
    @patch("app.services.health_engine.psutil.cpu_count", return_value=8)
    @patch("app.services.health_engine.psutil.cpu_percent", return_value=25)
    def test_collects_read_only_healthy_snapshot(
        self, _cpu, _count, memory, disk, clock, _boot, process_factory
    ):
        memory.return_value = SimpleNamespace(percent=50, used=4 * 1024**3, total=8 * 1024**3)
        disk.return_value = SimpleNamespace(percent=70, used=70 * 1024**3, total=100 * 1024**3)
        clock.now.return_value.timestamp.return_value = 91_000
        clock.now.return_value.astimezone.return_value = clock.now.return_value
        process_factory.return_value.status.return_value = "running"

        snapshot = self.engine.collect(active_workers=2)

        self.assertEqual(HealthState.HEALTHY, snapshot.overall_state)
        self.assertEqual(25.0, snapshot.cpu.value)
        self.assertEqual(50.0, snapshot.memory.value)
        self.assertEqual(70.0, snapshot.storage.value)
        self.assertEqual(90_000, snapshot.uptime.value)
        self.assertIn("2 active background workers", snapshot.application.detail)
        self.assertEqual((), snapshot.warnings)
        disk.assert_called_once_with("C:\\")

    @patch("app.services.health_engine.psutil.Process")
    @patch("app.services.health_engine.psutil.boot_time", return_value=0)
    @patch("app.services.health_engine.datetime")
    @patch("app.services.health_engine.psutil.disk_usage")
    @patch("app.services.health_engine.psutil.virtual_memory")
    @patch("app.services.health_engine.psutil.cpu_count", return_value=4)
    @patch("app.services.health_engine.psutil.cpu_percent", return_value=80)
    def test_worst_metric_sets_overall_and_active_warnings(
        self, _cpu, _count, memory, disk, clock, _boot, process_factory
    ):
        memory.return_value = SimpleNamespace(percent=94.9, used=1, total=2)
        disk.return_value = SimpleNamespace(percent=95, used=1, total=2)
        clock.now.return_value.timestamp.return_value = 100
        process_factory.return_value.status.return_value = "running"

        snapshot = self.engine.collect()

        self.assertEqual(HealthState.WARNING, snapshot.cpu.state)
        self.assertEqual(HealthState.WARNING, snapshot.memory.state)
        self.assertEqual(HealthState.CRITICAL, snapshot.storage.state)
        self.assertEqual(HealthState.CRITICAL, snapshot.overall_state)
        self.assertEqual(3, len(snapshot.warnings))
        self.assertTrue(any("Primary storage: CRITICAL" in item for item in snapshot.warnings))

    def test_formatters_are_stable_at_common_boundaries(self):
        self.assertEqual("1.0 GB", self.engine.format_bytes(1024**3))
        self.assertEqual("1d 2h 3m", self.engine.format_uptime(93_780))
        self.assertEqual("0h 0m", self.engine.format_uptime(-1))


if __name__ == "__main__":
    unittest.main()
