from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.developer_tools_service import DeveloperTool, DeveloperToolsService
from app.workers.callable_worker import CallableWorker


class DeveloperPage(QWidget):
    def __init__(self, service: DeveloperToolsService | None = None):
        super().__init__()
        self.service = service or DeveloperToolsService()
        self.tools: tuple[DeveloperTool, ...] = ()
        self.refresh_thread = None
        self.refresh_worker = None
        self._build_ui()

    def _build_ui(self):
        title = QLabel("Developer Environment")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Inspect allowlisted developer tools and versions without running arbitrary commands."
        )
        subtitle.setObjectName("pageSubtitle")
        self.status = QLabel("Environment has not been inspected.")
        self.status.setObjectName("updatedLabel")
        self.refresh_button = QPushButton("Inspect Environment")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button = QPushButton("Export Report")
        self.export_button.setObjectName("secondaryButton")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_report)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Tool", "Status", "Version", "Executable"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.status)
        layout.addWidget(self.refresh_button, 0)
        layout.addWidget(self.export_button, 0)
        layout.addWidget(self.table, 1)

    def refresh(self):
        if self.refresh_thread is not None:
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Inspecting…")
        self.refresh_thread = QThread(self)
        self.refresh_worker = CallableWorker(self.service.discover)
        self.refresh_worker.moveToThread(self.refresh_thread)
        self.refresh_thread.started.connect(self.refresh_worker.run)
        self.refresh_worker.succeeded.connect(self._refresh_succeeded)
        self.refresh_worker.failed.connect(self._refresh_failed)
        self.refresh_worker.finished.connect(self.refresh_thread.quit)
        self.refresh_worker.finished.connect(self.refresh_worker.deleteLater)
        self.refresh_thread.finished.connect(self._refresh_finished)
        self.refresh_thread.finished.connect(self.refresh_thread.deleteLater)
        self.refresh_thread.start()

    def _refresh_succeeded(self, tools):
        self.tools = tuple(tools)
        self.table.setRowCount(len(self.tools))
        for row, tool in enumerate(self.tools):
            values = (tool.name, "Available" if tool.available else "Unavailable", tool.version, tool.executable or "—")
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        available = sum(tool.available for tool in self.tools)
        self.status.setText(f"{available} of {len(self.tools)} allowlisted tools are available.")
        self.export_button.setEnabled(True)

    def _refresh_failed(self, message):
        self.tools = ()
        self.table.setRowCount(0)
        self.export_button.setEnabled(False)
        self.status.setText(f"Environment inspection failed: {message}")

    def _refresh_finished(self):
        self.refresh_worker = None
        self.refresh_thread = None
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("Inspect Environment")

    def export_report(self):
        if not self.tools:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Export Developer Environment", "arc3-developer-environment.json",
            "JSON files (*.json)",
        )
        if not destination:
            return
        try:
            self.service.export_report(self.tools, destination)
        except OSError as exc:
            self.status.setText(f"Report export failed: {exc}")
            return
        self.status.setText(f"Environment report exported to {Path(destination).name}.")
