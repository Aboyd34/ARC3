from __future__ import annotations

import csv
import json
from datetime import datetime

from PySide6.QtCore import QThread, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
    QGroupBox, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from app.services.windows_device_service import WindowsDeviceService
from app.safety.device_operations import DeviceOperationPolicy
from app.workers.callable_worker import CallableWorker


class DevicesTab(QWidget):
    COLUMNS = (
        ("name", "Device"), ("class", "Class"), ("health", "Health"),
        ("status", "Status"), ("manufacturer", "Manufacturer"),
        ("driver_provider", "Driver Provider"),
        ("driver_version", "Driver Version"), ("driver_date", "Driver Date"),
        ("problem_code", "Problem Code"), ("instance_id", "Instance ID"),
    )

    def __init__(self):
        super().__init__()
        self.service = WindowsDeviceService()
        self.devices = []
        self.refresh_thread = None
        self.refresh_worker = None
        self.action_thread = None
        self.action_worker = None
        self.pending_action = None
        self.selected_details = None
        self.build_ui()
        QTimer.singleShot(0, self.refresh)

    def build_ui(self):
        heading = QLabel("Device Diagnostics")
        heading.setObjectName("tabHeading")
        description = QLabel(
            "Inspect Plug and Play health and driver metadata. Supported device "
            "state changes are reversible and require confirmation."
        )
        description.setObjectName("tabDescription")
        self.count_label = QLabel("Loading devices...")
        self.count_label.setObjectName("updatedLabel")
        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText("Search devices, classes, drivers, or IDs...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self.apply_filter)
        self.health_filter = QComboBox()
        self.health_filter.addItems(("All health states", "Healthy", "Needs attention", "Disabled"))
        self.health_filter.currentTextChanged.connect(self.apply_filter)
        self.export_csv_button = QPushButton("Export CSV")
        self.export_csv_button.setObjectName("secondaryButton")
        self.export_csv_button.clicked.connect(lambda: self.export_devices("csv"))
        self.export_json_button = QPushButton("Export JSON")
        self.export_json_button.setObjectName("secondaryButton")
        self.export_json_button.clicked.connect(lambda: self.export_devices("json"))
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.clicked.connect(self.refresh)
        self.open_manager_button = QPushButton("Open Device Manager")
        self.open_manager_button.setObjectName("secondaryButton")
        self.open_manager_button.clicked.connect(self.open_device_manager)
        controls = QHBoxLayout()
        controls.addWidget(self.search_box, 1)
        controls.addWidget(self.health_filter)
        controls.addWidget(self.export_csv_button)
        controls.addWidget(self.export_json_button)
        controls.addWidget(self.open_manager_button)
        controls.addWidget(self.refresh_button)
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _, label in self.COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.selection_label = QLabel("Select a device to enable or disable it.")
        self.details_button = QPushButton("View Details")
        self.details_button.setObjectName("secondaryButton")
        self.details_button.setEnabled(False)
        self.details_button.clicked.connect(self.show_selected_details)
        self.verify_button = QPushButton("Verify Hardware")
        self.verify_button.setObjectName("secondaryButton")
        self.verify_button.setEnabled(False)
        self.verify_button.clicked.connect(self.verify_selected_hardware)
        self.copy_ids_button = QPushButton("Copy Hardware IDs")
        self.copy_ids_button.setObjectName("secondaryButton")
        self.copy_ids_button.setEnabled(False)
        self.copy_ids_button.clicked.connect(self.copy_hardware_ids)
        self.export_driver_button = QPushButton("Export Driver")
        self.export_driver_button.setObjectName("secondaryButton")
        self.export_driver_button.setEnabled(False)
        self.export_driver_button.clicked.connect(self.export_selected_driver)
        self.enable_button = QPushButton("Enable Device")
        self.enable_button.setObjectName("primaryButton")
        self.enable_button.setEnabled(False)
        self.enable_button.clicked.connect(lambda: self.change_selected_state(True))
        self.disable_button = QPushButton("Disable Device")
        self.disable_button.setObjectName("dangerButton")
        self.disable_button.setEnabled(False)
        self.disable_button.clicked.connect(lambda: self.change_selected_state(False))
        actions = QHBoxLayout()
        actions.addWidget(self.selection_label, 1)
        actions.addWidget(self.details_button)
        actions.addWidget(self.verify_button)
        actions.addWidget(self.copy_ids_button)
        actions.addWidget(self.export_driver_button)
        actions.addWidget(self.enable_button)
        actions.addWidget(self.disable_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addWidget(self.count_label)
        layout.addLayout(controls)
        layout.addWidget(self.table, 1)
        layout.addLayout(actions)
        details_group = QGroupBox("Device Details")
        details_layout = QVBoxLayout(details_group)
        self.details_panel = QTextEdit()
        self.details_panel.setReadOnly(True)
        self.details_panel.setPlaceholderText(
            "Select a device and choose View Details to inspect identity, driver, and signature information."
        )
        details_layout.addWidget(self.details_panel)
        layout.addWidget(details_group, 1)

    def refresh(self):
        if self.refresh_thread is not None:
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Refreshing...")
        self.refresh_thread = QThread(self)
        self.refresh_worker = CallableWorker(self.service.collect_devices)
        self.refresh_worker.moveToThread(self.refresh_thread)
        self.refresh_thread.started.connect(self.refresh_worker.run)
        self.refresh_worker.succeeded.connect(self._loaded)
        self.refresh_worker.failed.connect(self._failed)
        self.refresh_worker.finished.connect(self.refresh_thread.quit)
        self.refresh_worker.finished.connect(self.refresh_worker.deleteLater)
        self.refresh_thread.finished.connect(self._finished)
        self.refresh_thread.finished.connect(self.refresh_thread.deleteLater)
        self.refresh_thread.start()

    def _loaded(self, devices):
        selected = self.selected_device()
        selected_instance_id = selected["instance_id"] if selected else None
        self.devices = devices
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for device in devices:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, (key, _) in enumerate(self.COLUMNS):
                item = QTableWidgetItem(str(device[key]))
                item.setData(Qt.UserRole, device["instance_id"])
                if key == "health":
                    item.setForeground(QColor({
                        "Healthy": "#22c55e", "Needs attention": "#f59e0b",
                        "Disabled": "#94a3b8",
                    }.get(device["health"], "#e5e7eb")))
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        if selected_instance_id:
            for row in range(self.table.rowCount()):
                if self.table.item(row, 0).data(Qt.UserRole) == selected_instance_id:
                    self.table.selectRow(row)
                    break
        self.apply_filter()

    def _failed(self, message):
        self.devices = []
        self.table.setRowCount(0)
        self.count_label.setText("Device refresh failed")
        self.update_actions()
        QMessageBox.critical(self, "Device Diagnostics Error", message)

    def _finished(self):
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("Refresh")
        self.refresh_worker = None
        self.refresh_thread = None

    def apply_filter(self, *_):
        text = self.search_box.text().strip().casefold()
        health = self.health_filter.currentText()
        visible = 0
        for row in range(self.table.rowCount()):
            values = [self.table.item(row, col).text() for col in range(self.table.columnCount())]
            matches_text = not text or any(text in value.casefold() for value in values)
            matches_health = health == "All health states" or values[2] == health
            shown = matches_text and matches_health
            self.table.setRowHidden(row, not shown)
            visible += int(shown)
        self.count_label.setText(f"{visible} of {len(self.devices)} devices")

    def selected_device(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        instance_id = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        return next((item for item in self.devices if item["instance_id"] == instance_id), None)

    def update_actions(self):
        device = self.selected_device()
        if not device or (
            self.selected_details
            and self.selected_details.get("instance_id") != device["instance_id"]
        ):
            self.selected_details = None
        idle = self.action_thread is None
        self.details_button.setEnabled(bool(device and idle))
        self.verify_button.setEnabled(bool(device and idle))
        self.copy_ids_button.setEnabled(bool(device and idle))
        self.export_driver_button.setEnabled(bool(device and idle))
        self.enable_button.setEnabled(bool(device and not device["enabled"] and idle))
        self.disable_button.setEnabled(bool(device and device["enabled"] and idle))
        self.selection_label.setText(
            f"Selected: {device['name']}" if device else "Select a device to enable or disable it."
        )

    def change_selected_state(self, enabled):
        device = self.selected_device()
        if not device:
            return
        verb = "Enable" if enabled else "Disable"
        answer = QMessageBox.question(
            self, f"{verb} Device",
            DeviceOperationPolicy.confirmation_message(device["name"], enabled),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._start_action(
            lambda: self.service.set_enabled(device["instance_id"], enabled),
            self._state_changed,
        )

    def _state_changed(self, result):
        successful, message = result
        method = QMessageBox.information if successful else QMessageBox.warning
        method(self, "Device Updated" if successful else "Device Update Failed", message)
        self.refresh()

    def show_selected_details(self):
        device = self.selected_device()
        if device:
            instance_id = device["instance_id"]
            self._start_action(
                lambda: self.service.collect_details(instance_id),
                self._for_selected_device(instance_id, self._show_details),
                instance_id,
            )

    def verify_selected_hardware(self):
        device = self.selected_device()
        if device:
            instance_id = device["instance_id"]
            self._start_action(
                lambda: self.service.verify_hardware(instance_id),
                self._for_selected_device(instance_id, self._show_verification),
                instance_id,
            )

    def _show_details(self, details):
        self.selected_details = details
        self.details_panel.setPlainText(self._format_details(details))
        self.update_actions()

    def copy_hardware_ids(self):
        device = self.selected_device()
        if not device:
            return
        if not self.selected_details:
            instance_id = device["instance_id"]
            self._start_action(
                lambda: self.service.collect_details(instance_id),
                self._for_selected_device(instance_id, self._copy_loaded_hardware_ids),
                instance_id,
            )
            return
        self._copy_loaded_hardware_ids(self.selected_details)

    def _copy_loaded_hardware_ids(self, details):
        self._show_details(details)
        hardware_ids = details.get("hardware_ids") or []
        if isinstance(hardware_ids, str):
            hardware_ids = [hardware_ids]
        if not hardware_ids:
            QMessageBox.warning(self, "Hardware IDs", "Windows did not report hardware IDs for this device.")
            return
        QApplication.clipboard().setText("\n".join(str(value) for value in hardware_ids))
        QMessageBox.information(self, "Hardware IDs", "Hardware IDs copied to the clipboard.")

    def export_selected_driver(self):
        device = self.selected_device()
        if not device:
            return
        if not self.selected_details:
            instance_id = device["instance_id"]
            self._start_action(
                lambda: self.service.collect_details(instance_id),
                self._for_selected_device(
                    instance_id,
                    lambda details: self._choose_driver_export(details, instance_id),
                ),
                instance_id,
            )
            return
        self._choose_driver_export(self.selected_details, device["instance_id"])

    def _choose_driver_export(self, details, instance_id=None):
        instance_id = instance_id or str(details.get("instance_id") or "")
        if not self._same_device_selected(instance_id):
            return
        self._show_details(details)
        driver_inf = str(details.get("driver_inf_path") or "")
        if not DeviceOperationPolicy.valid_driver_inf(driver_inf):
            QMessageBox.warning(self, "Export Driver", "Windows did not report an exportable driver INF for this device.")
            return
        destination = QFileDialog.getExistingDirectory(self, "Select Driver Export Folder")
        if destination:
            self.pending_action = (
                lambda: self.service.export_driver(driver_inf, destination),
                self._for_selected_device(instance_id, self._driver_exported),
                instance_id,
            )
            if self.action_thread is None:
                self._start_pending_action()

    def _driver_exported(self, result):
        method = QMessageBox.information if result.success else QMessageBox.warning
        method(self, "Driver Export" if result.success else "Driver Export Failed", result.message)

    def open_device_manager(self):
        result = self.service.open_device_manager()
        if not result.success:
            QMessageBox.warning(self, "Open Device Manager", result.message)

    def _show_verification(self, result):
        checks = "\n".join(
            f"{key.replace('_', ' ').title()}: {'Pass' if passed else 'Review'}"
            for key, passed in result["checks"].items()
        )
        message = (
            f"{result['message']}\n\n{checks}\n\n"
            f"{self._format_details(result['details'])}"
        )
        dialog = (
            QMessageBox.information
            if result["verification"] == "Verified" else QMessageBox.warning
        )
        dialog(self, f"Hardware Verification - {result['verification']}", message)

    def _same_device_selected(self, instance_id):
        device = self.selected_device()
        return bool(device and device["instance_id"] == instance_id)

    def _for_selected_device(self, instance_id, completed):
        def apply_if_current(result):
            if self._same_device_selected(instance_id):
                completed(result)

        return apply_if_current

    @staticmethod
    def _format_details(details):
        lines = []
        for key, value in details.items():
            if isinstance(value, list):
                value = ", ".join(value)
            display = "Not reported" if value in (None, "", []) else value
            lines.append(f"{key.replace('_', ' ').title()}: {display}")
        return "\n".join(lines)

    def _start_action(self, operation, completed, instance_id=None):
        if self.action_thread is not None:
            return
        self.action_thread = QThread(self)
        self.action_worker = CallableWorker(operation)
        self.action_worker.moveToThread(self.action_thread)
        self.action_thread.started.connect(self.action_worker.run)
        self.action_worker.succeeded.connect(completed)
        if instance_id is None:
            self.action_worker.failed.connect(self._action_failed)
        else:
            self.action_worker.failed.connect(
                self._for_selected_device(instance_id, self._action_failed)
            )
        self.action_worker.finished.connect(self.action_thread.quit)
        self.action_worker.finished.connect(self.action_worker.deleteLater)
        self.action_thread.finished.connect(self._action_finished)
        self.action_thread.finished.connect(self.action_thread.deleteLater)
        self.update_actions()
        self.action_thread.start()

    def _action_failed(self, message):
        QMessageBox.critical(self, "Device Request Failed", message)

    def _action_finished(self):
        self.action_worker = None
        self.action_thread = None
        self.update_actions()
        if self.pending_action is not None:
            QTimer.singleShot(0, self._start_pending_action)

    def _start_pending_action(self):
        if self.pending_action is None or self.action_thread is not None:
            return
        operation, completed, instance_id = self.pending_action
        self.pending_action = None
        if not self._same_device_selected(instance_id):
            self.update_actions()
            return
        self._start_action(operation, completed, instance_id)

    def export_devices(self, format_name):
        suffix = format_name.lower()
        default = f"ARC3_Devices_{datetime.now():%Y%m%d_%H%M%S}.{suffix}"
        filter_name = "CSV Files (*.csv)" if suffix == "csv" else "JSON Files (*.json)"
        path, _ = QFileDialog.getSaveFileName(self, "Export Device Diagnostics", default, filter_name)
        if not path:
            return
        if not path.lower().endswith(f".{suffix}"):
            path += f".{suffix}"
        try:
            with open(path, "w", newline="" if suffix == "csv" else None, encoding="utf-8") as output:
                if suffix == "json":
                    json.dump(self.devices, output, indent=2)
                else:
                    writer = csv.DictWriter(output, fieldnames=[key for key, _ in self.COLUMNS] + ["enabled"])
                    writer.writeheader()
                    writer.writerows(self.devices)
        except OSError as error:
            QMessageBox.critical(self, "Export Failed", str(error))
            return
        QMessageBox.information(self, "Export Complete", f"Device diagnostics saved to:\n\n{path}")
