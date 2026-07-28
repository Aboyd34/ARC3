from __future__ import annotations

import csv
import json
from datetime import datetime

from PySide6.QtCore import QThread, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.startup_service import StartupService
from app.workers.callable_worker import CallableWorker


class StartupTab(QWidget):
    COLUMNS = (
        ("name", "Name"),
        ("publisher", "Publisher"),
        ("command", "Command"),
        ("location", "Startup Location"),
        ("source", "Registry Key or Folder"),
        ("enabled", "Enabled"),
        ("file_exists", "File Exists"),
        ("signature_status", "Digital Signature"),
        ("launch_type", "Launch Type"),
        ("startup_impact", "Startup Impact"),
    )

    def __init__(self):
        super().__init__()
        self.service = StartupService()
        self.entries = []
        self.refresh_thread = None
        self.refresh_worker = None
        self.build_ui()
        QTimer.singleShot(0, self.refresh)

    def build_ui(self):
        heading = QLabel("Startup Manager")
        heading.setObjectName("tabHeading")

        description = QLabel(
            "Inspect startup applications from common Registry and "
            "Startup-folder locations. Changes are reversible."
        )
        description.setObjectName("tabDescription")

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        title_layout.addWidget(heading)
        title_layout.addWidget(description)

        self.count_label = QLabel("Loading startup entries...")
        self.count_label.setObjectName("updatedLabel")

        self.export_csv_button = QPushButton("Export CSV")
        self.export_csv_button.setObjectName("secondaryButton")
        self.export_csv_button.clicked.connect(self.export_csv)

        self.export_json_button = QPushButton("Export JSON")
        self.export_json_button.setObjectName("secondaryButton")
        self.export_json_button.clicked.connect(self.export_json)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.clicked.connect(self.refresh)

        actions = QHBoxLayout()
        actions.addWidget(self.count_label)
        actions.addStretch()
        actions.addWidget(self.export_csv_button)
        actions.addWidget(self.export_json_button)
        actions.addWidget(self.refresh_button)

        heading_row = QHBoxLayout()
        heading_row.addLayout(title_layout)
        heading_row.addStretch()
        heading_row.addLayout(actions)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText(
            "Search name, publisher, command, location, signature, or impact..."
        )
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self.apply_filter)

        self.table = QTableWidget()
        self.table.setObjectName("startupTable")
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(
            [label for _, label in self.COLUMNS]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self.update_details)

        header = self.table.horizontalHeader()
        for index in range(len(self.COLUMNS)):
            header.setSectionResizeMode(index, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)

        self.details_frame = QFrame()
        self.details_frame.setObjectName("processActionBar")
        self.detail_name = QLabel("Select a startup item")
        self.detail_name.setObjectName("cardTitle")
        self.detail_command = QLabel(
            "Details and safe management actions will appear here."
        )
        self.detail_command.setObjectName("systemValue")
        self.detail_command.setWordWrap(True)
        self.detail_source = QLabel("")
        self.detail_source.setObjectName("updatedLabel")
        self.detail_source.setWordWrap(True)

        detail_text = QVBoxLayout()
        detail_text.setSpacing(3)
        detail_text.addWidget(self.detail_name)
        detail_text.addWidget(self.detail_command)
        detail_text.addWidget(self.detail_source)

        self.copy_command_button = self._action_button(
            "Copy Command",
            self.copy_command,
        )
        self.copy_path_button = self._action_button(
            "Copy Path",
            self.copy_path,
        )
        self.open_folder_button = self._action_button(
            "Open Folder",
            self.open_folder,
        )
        self.open_registry_button = self._action_button(
            "Open Registry",
            self.open_registry,
        )
        self.toggle_button = QPushButton("Disable")
        self.toggle_button.setObjectName("dangerButton")
        self.toggle_button.setEnabled(False)
        self.toggle_button.clicked.connect(self.toggle_selected)

        button_grid = QGridLayout()
        button_grid.setSpacing(6)
        button_grid.addWidget(self.copy_command_button, 0, 0)
        button_grid.addWidget(self.copy_path_button, 0, 1)
        button_grid.addWidget(self.open_folder_button, 1, 0)
        button_grid.addWidget(self.open_registry_button, 1, 1)
        button_grid.addWidget(self.toggle_button, 0, 2, 2, 1)

        details_layout = QHBoxLayout(self.details_frame)
        details_layout.setContentsMargins(14, 10, 14, 10)
        details_layout.addLayout(detail_text, 1)
        details_layout.addLayout(button_grid)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addLayout(heading_row)
        layout.addWidget(self.search_box)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.details_frame)

    def _action_button(self, text, callback):
        button = QPushButton(text)
        button.setObjectName("secondaryButton")
        button.setEnabled(False)
        button.clicked.connect(callback)
        return button

    def refresh(self):
        if self.refresh_thread is not None:
            return

        self.refresh_button.setEnabled(False)
        self.count_label.setText("Scanning startup locations...")
        self.refresh_thread = QThread(self)
        self.refresh_worker = CallableWorker(self.service.collect_entries)
        self.refresh_worker.moveToThread(self.refresh_thread)
        self.refresh_thread.started.connect(self.refresh_worker.run)
        self.refresh_worker.succeeded.connect(self._entries_loaded)
        self.refresh_worker.failed.connect(self._entries_failed)
        self.refresh_worker.finished.connect(self.refresh_thread.quit)
        self.refresh_worker.finished.connect(self.refresh_worker.deleteLater)
        self.refresh_thread.finished.connect(self._refresh_finished)
        self.refresh_thread.finished.connect(self.refresh_thread.deleteLater)
        self.refresh_thread.start()

    def refresh_data(self):
        self.refresh()

    def _entries_loaded(self, entries):
        self.entries = entries
        self.populate_table()
        self._notify(
            f"Loaded {len(entries)} startup entries.",
            "success",
        )

    def _entries_failed(self, error_message):
        QMessageBox.critical(
            self,
            "Startup Manager Error",
            f"ARC3 could not scan startup entries.\n\n{error_message}",
        )
        self.count_label.setText("Startup scan failed")

    def _refresh_finished(self):
        self.refresh_button.setEnabled(True)
        self.refresh_worker = None
        self.refresh_thread = None

    def populate_table(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        for entry in self.entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, (field, _) in enumerate(self.COLUMNS):
                value = entry.get(field, "")
                if isinstance(value, bool):
                    text = "Yes" if value else "No"
                else:
                    text = str(value)
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(Qt.UserRole, entry)
                if field == "enabled":
                    item.setForeground(
                        Qt.darkGreen if value else Qt.darkRed
                    )
                self.table.setItem(row, column, item)

        self.table.setSortingEnabled(True)
        self.apply_filter(self.search_box.text())

    def apply_filter(self, text):
        query = text.strip().casefold()
        visible = 0
        for row in range(self.table.rowCount()):
            matches = not query or any(
                query
                in (
                    self.table.item(row, column).text().casefold()
                    if self.table.item(row, column)
                    else ""
                )
                for column in range(self.table.columnCount())
            )
            self.table.setRowHidden(row, not matches)
            if matches:
                visible += 1

        self.count_label.setText(
            f"{visible} of {len(self.entries)} startup entries"
        )

    def selected_entry(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def update_details(self):
        entry = self.selected_entry()
        buttons = (
            self.copy_command_button,
            self.copy_path_button,
            self.open_folder_button,
            self.open_registry_button,
            self.toggle_button,
        )
        for button in buttons:
            button.setEnabled(entry is not None)

        if entry is None:
            self.detail_name.setText("Select a startup item")
            self.detail_command.setText(
                "Details and safe management actions will appear here."
            )
            self.detail_source.setText("")
            return

        state = "Enabled" if entry["enabled"] else "Disabled"
        self.detail_name.setText(
            f"{entry['name']}  •  {state}  •  "
            f"{entry['startup_impact']} impact"
        )
        self.detail_command.setText(entry["command"])
        self.detail_source.setText(
            f"{entry['source']}  •  Publisher: {entry['publisher']}  •  "
            f"Signature: {entry['signature_status']}"
        )
        self.copy_path_button.setEnabled(bool(entry["file_path"]))
        self.open_folder_button.setEnabled(
            bool(entry["file_path"]) and entry["file_exists"]
        )
        self.open_registry_button.setEnabled(
            entry["source_type"] == "registry"
        )
        self.toggle_button.setText(
            "Disable" if entry["enabled"] else "Enable"
        )
        self.toggle_button.setObjectName(
            "dangerButton" if entry["enabled"] else "primaryButton"
        )
        self.toggle_button.style().unpolish(self.toggle_button)
        self.toggle_button.style().polish(self.toggle_button)

    def copy_command(self):
        entry = self.selected_entry()
        if entry:
            QApplication.clipboard().setText(entry["command"])
            self._notify("Startup command copied.", "success")

    def copy_path(self):
        entry = self.selected_entry()
        if entry and entry["file_path"]:
            QApplication.clipboard().setText(entry["file_path"])
            self._notify("Startup file path copied.", "success")

    def open_folder(self):
        entry = self.selected_entry()
        if not entry:
            return
        success, message = self.service.open_containing_folder(
            entry["file_path"]
        )
        if not success:
            QMessageBox.warning(self, "Open Folder", message)

    def open_registry(self):
        entry = self.selected_entry()
        if not entry:
            return
        registry_path = f"{entry['hive']}\\{entry['registry_path']}"
        success, message = self.service.open_registry_location(registry_path)
        if not success:
            QMessageBox.warning(self, "Open Registry", message)

    def toggle_selected(self):
        entry = self.selected_entry()
        if not entry:
            return

        enable = not entry["enabled"]
        action = "enable" if enable else "disable"
        answer = QMessageBox.question(
            self,
            f"{action.title()} Startup Item",
            (
                f"Are you sure you want to {action} "
                f"“{entry['name']}”?\n\n"
                "ARC3 will preserve the entry so this change "
                "can be reversed."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        success, message = self.service.set_enabled(entry, enable)
        if success:
            self._notify(message, "success", 2800)
            self.refresh()
        else:
            QMessageBox.critical(
                self,
                "Startup Change Failed",
                message,
            )

    def visible_entries(self):
        result = []
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, 0)
            if item:
                result.append(item.data(Qt.UserRole))
        return result

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Startup Entries",
            f"ARC3_Startup_{datetime.now():%Y%m%d_%H%M%S}.csv",
            "CSV Files (*.csv)",
        )
        if not path:
            return
        fields = [field for field, _ in self.COLUMNS]
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for entry in self.visible_entries():
                writer.writerow(
                    {field: entry.get(field, "") for field in fields}
                )
        self._notify("Startup entries exported to CSV.", "success")

    def export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Startup Entries",
            f"ARC3_Startup_{datetime.now():%Y%m%d_%H%M%S}.json",
            "JSON Files (*.json)",
        )
        if not path:
            return
        fields = [field for field, _ in self.COLUMNS]
        payload = [
            {field: entry.get(field, "") for field in fields}
            for entry in self.visible_entries()
        ]
        with open(path, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
        self._notify("Startup entries exported to JSON.", "success")

    def _notify(self, message, kind="info", duration=2200):
        window = self.window()
        notification = getattr(window, "show_arc3_notification", None)
        if notification:
            notification(message, kind, duration)
