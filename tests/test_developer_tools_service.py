import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.pages.developer_page import DeveloperPage
from app.services.developer_tools_service import DeveloperTool, DeveloperToolsService


class DeveloperToolsServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_missing_tool_is_reported_without_execution(self):
        service = DeveloperToolsService(trusted_roots=("C:/Git",))
        with patch("app.services.developer_tools_service.shutil.which", return_value=None), patch(
            "app.services.developer_tools_service.subprocess.run"
        ) as run:
            tool = service._probe("Git", "git", ("--version",))
        self.assertFalse(tool.available)
        run.assert_not_called()

    def test_probe_uses_argument_list_without_shell(self):
        service = DeveloperToolsService(trusted_roots=("C:/Git",))
        completed = type("Completed", (), {"returncode": 0, "stdout": "git version 2.0\n", "stderr": ""})()
        with patch("app.services.developer_tools_service.shutil.which", return_value="C:/Git/git.exe"), patch(
            "app.services.developer_tools_service.subprocess.run", return_value=completed
        ) as run:
            tool = service._probe("Git", "git", ("--version",))
        self.assertTrue(tool.available)
        self.assertEqual("git version 2.0", tool.version)
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(["C:/Git/git.exe", "--version"], run.call_args.args[0])

    def test_untrusted_path_executable_is_not_run(self):
        service = DeveloperToolsService(trusted_roots=("C:/Program Files",))
        with patch(
            "app.services.developer_tools_service.shutil.which",
            return_value="C:/Users/test/Downloads/git.exe",
        ), patch("app.services.developer_tools_service.subprocess.run") as run:
            tool = service._probe("Git", "git", ("--version",))
        self.assertFalse(tool.available)
        self.assertIn("outside trusted", tool.version)
        run.assert_not_called()

    def test_export_report_contains_only_inventory_data(self):
        tools = (DeveloperTool("Python", "C:/Python/python.exe", True, "Python 3"),)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "report.json"
            DeveloperToolsService.export_report(tools, destination)
            report = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(1, report["schema_version"])
        self.assertEqual("Python", report["tools"][0]["name"])

    def test_export_does_not_replace_existing_report(self):
        tools = (DeveloperTool("Python", None, False, "Missing"),)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "report.json"
            destination.write_text("existing", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                DeveloperToolsService.export_report(tools, destination)
            self.assertEqual("existing", destination.read_text(encoding="utf-8"))

    def test_page_starts_without_running_commands(self):
        service = DeveloperToolsService()
        with patch.object(service, "discover") as discover:
            page = DeveloperPage(service)
        discover.assert_not_called()
        self.assertEqual(0, page.table.rowCount())
        self.assertFalse(page.export_button.isEnabled())
        page.close()
        page.deleteLater()


if __name__ == "__main__":
    unittest.main()
