from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.file_analysis_service import FileAnalysis, FileAnalysisService
from app.workers.callable_worker import CallableWorker


class FilesPage(QWidget):
    def __init__(self, service: FileAnalysisService | None = None):
        super().__init__()
        self.service = service or FileAnalysisService()
        self.analysis: FileAnalysis | None = None
        self.scan_thread = None
        self.scan_worker = None
        self._build_ui()

    def _build_ui(self):
        title = QLabel("File Analysis")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Build a read-only inventory and identify byte-for-byte duplicates.")
        subtitle.setObjectName("pageSubtitle")
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Choose a directory to analyze")
        self.browse_button = QPushButton("Choose Folder")
        self.browse_button.setObjectName("secondaryButton")
        self.browse_button.clicked.connect(self.choose_directory)
        self.recursive = QCheckBox("Include subfolders")
        self.recursive.setChecked(True)
        self.scan_button = QPushButton("Analyze Files")
        self.scan_button.setObjectName("primaryButton")
        self.scan_button.clicked.connect(self.scan)
        self.export_button = QPushButton("Export Report")
        self.export_button.setObjectName("secondaryButton")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_report)
        controls = QHBoxLayout()
        controls.addWidget(self.path_input, 1)
        controls.addWidget(self.browse_button)
        controls.addWidget(self.recursive)
        controls.addWidget(self.scan_button)
        controls.addWidget(self.export_button)
        self.summary = QLabel("No directory analyzed. Files are never modified.")
        self.summary.setObjectName("updatedLabel")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["File", "Folder", "Size", "Modified", "SHA-256"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(controls)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)

    def choose_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory to Analyze")
        if directory:
            self.path_input.setText(directory)

    def scan(self):
        if self.scan_thread is not None:
            return
        directory = self.path_input.text().strip()
        if not directory:
            self.summary.setText("Choose a directory first.")
            return
        recursive = self.recursive.isChecked()
        self._set_scanning(True)
        self.scan_thread = QThread(self)
        self.scan_worker = CallableWorker(lambda: self.service.analyze(directory, recursive))
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.succeeded.connect(self._scan_succeeded)
        self.scan_worker.failed.connect(self._scan_failed)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_worker.finished.connect(self.scan_worker.deleteLater)
        self.scan_thread.finished.connect(self._scan_finished)
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        self.scan_thread.start()

    def _scan_succeeded(self, analysis):
        self.analysis = analysis
        duplicate_paths = {
            record.path for group in analysis.duplicate_groups for record in group
        }
        self.table.setRowCount(len(analysis.files))
        for row, record in enumerate(analysis.files):
            values = (
                record.name, str(record.path.parent),
                self.service.format_size(record.size_bytes),
                record.modified_at.strftime("%Y-%m-%d %H:%M"), record.sha256,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if record.path in duplicate_paths:
                    item.setToolTip("Byte-for-byte duplicate")
                self.table.setItem(row, column, item)
        self.summary.setText(
            f"Analyzed {len(analysis.files)} files · "
            f"{len(analysis.duplicate_groups)} duplicate groups · no files changed."
        )
        self.export_button.setEnabled(True)

    def _scan_failed(self, message):
        self.analysis = None
        self.table.setRowCount(0)
        self.export_button.setEnabled(False)
        self.summary.setText(f"File analysis failed: {message}")

    def _scan_finished(self):
        self.scan_worker = None
        self.scan_thread = None
        self._set_scanning(False)

    def _set_scanning(self, scanning):
        for widget in (self.path_input, self.browse_button, self.recursive, self.scan_button):
            widget.setEnabled(not scanning)
        self.scan_button.setText("Analyzing…" if scanning else "Analyze Files")

    def export_report(self):
        if self.analysis is None:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Export File Analysis", "arc3-file-analysis.json", "JSON files (*.json)"
        )
        if not destination:
            return
        try:
            self.service.export_report(self.analysis, destination)
        except OSError as exc:
            self.summary.setText(f"Report export failed: {exc}")
            return
        self.summary.setText(f"Analysis report exported to {Path(destination).name}.")
