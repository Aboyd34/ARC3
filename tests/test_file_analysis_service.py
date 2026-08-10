import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.pages.files_page import FilesPage
from app.services.file_analysis_service import FileAnalysisService


class FileAnalysisServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_analysis_detects_only_byte_identical_duplicates(self):
        service = FileAnalysisService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.bin").write_bytes(b"same")
            (root / "two.bin").write_bytes(b"same")
            (root / "other.bin").write_bytes(b"different")
            analysis = service.analyze(root)
        self.assertEqual(3, len(analysis.files))
        self.assertEqual(1, len(analysis.duplicate_groups))
        self.assertEqual({"one.bin", "two.bin"}, {item.name for item in analysis.duplicate_groups[0]})

    def test_non_recursive_scan_does_not_enter_subfolders(self):
        service = FileAnalysisService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "top.txt").write_text("top", encoding="utf-8")
            child = root / "child"
            child.mkdir()
            (child / "nested.txt").write_text("nested", encoding="utf-8")
            analysis = service.analyze(root, recursive=False)
        self.assertEqual(["top.txt"], [record.name for record in analysis.files])

    def test_file_limit_fails_closed(self):
        service = FileAnalysisService()
        service.MAX_FILES = 1
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a").write_bytes(b"a")
            (root / "b").write_bytes(b"b")
            with self.assertRaisesRegex(ValueError, "safety limit"):
                service.analyze(root)

    def test_report_contains_hash_and_duplicate_evidence(self):
        service = FileAnalysisService()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"same"
            (root / "a").write_bytes(payload)
            (root / "b").write_bytes(payload)
            analysis = service.analyze(root)
            report_path = root / "report.json"
            service.export_report(analysis, report_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(1, report["duplicate_group_count"])
        self.assertEqual(hashlib.sha256(payload).hexdigest(), report["files"][0]["sha256"])
        self.assertTrue(report["files"][0]["duplicate"])

    def test_page_starts_read_only_and_empty(self):
        page = FilesPage(FileAnalysisService())
        self.assertIn("never modified", page.summary.text())
        self.assertEqual(0, page.table.rowCount())
        self.assertFalse(page.export_button.isEnabled())
        page.close()
        page.deleteLater()


if __name__ == "__main__":
    unittest.main()
