from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFormLayout, QFrame, QHBoxLayout,
    QFileDialog, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.services.android_device_service import AndroidDeviceService
from app.services.device_models import OperationType
from app.workers.callable_worker import CallableWorker


class AndroidWorkspace(QWidget):
    def __init__(self):
        super().__init__()
        self.service = AndroidDeviceService()
        self.refresh_thread = None
        self.refresh_worker = None
        self.operation_thread = None
        self.operation_worker = None
        self.verification_thread = None
        self.verification_worker = None
        self.build_ui()
        QTimer.singleShot(0, self.refresh_devices)

    def build_ui(self):
        title = QLabel("Android Device Manager")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Detect ADB and Fastboot devices, connection state, model, and product details.")
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        self.tool_status = QLabel("Checking Android platform tools...")
        self.tool_status.setObjectName("updatedLabel")
        self.refresh_button = QPushButton("Refresh Devices")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.clicked.connect(self.refresh_devices)
        self.table = QTableWidget()
        self.table.setObjectName("deviceTable")
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Serial", "Mode", "State", "Model", "Product", "Device"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.summary = QLabel("No refresh completed yet.")
        self.summary.setObjectName("systemValue")
        self.summary.setWordWrap(True)
        self.guidance = QLabel("Select a device for connection guidance.")
        self.guidance.setObjectName("updatedLabel")
        self.guidance.setWordWrap(True)

        case_frame = QFrame()
        case_frame.setObjectName("processActionBar")
        self.case_id = QLineEdit()
        self.case_id.setPlaceholderText("Required for audited operations")
        self.technician_id = QLineEdit()
        self.technician_id.setPlaceholderText("Technician or workstation ID")
        self.ownership_confirmed = QCheckBox(
            "I verified ownership or documented service authorization"
        )
        self.case_id.textChanged.connect(self._selection_changed)
        self.technician_id.textChanged.connect(self._selection_changed)
        self.ownership_confirmed.toggled.connect(self._selection_changed)
        case_form = QFormLayout(case_frame)
        case_form.addRow("Case ID", self.case_id)
        case_form.addRow("Technician ID", self.technician_id)
        case_form.addRow("Authorization", self.ownership_confirmed)

        self.info_button = QPushButton("View Device Record")
        self.info_button.setObjectName("secondaryButton")
        self.info_button.clicked.connect(self.show_device_record)
        self.verify_button = QPushButton("Verify Hardware")
        self.verify_button.setObjectName("primaryButton")
        self.verify_button.clicked.connect(self.verify_hardware)
        self.diagnostics_button = QPushButton("Run ADB Diagnostics")
        self.diagnostics_button.setObjectName("primaryButton")
        self.diagnostics_button.clicked.connect(self.run_diagnostics)
        self.log_lines = QSpinBox()
        self.log_lines.setRange(50, 5000)
        self.log_lines.setValue(1000)
        self.log_lines.setSuffix(" lines")
        self.logcat_button = QPushButton("Export Logcat")
        self.logcat_button.setObjectName("secondaryButton")
        self.logcat_button.clicked.connect(self.export_logcat)
        self.recovery_button = QPushButton("Reboot to Recovery")
        self.recovery_button.setObjectName("secondaryButton")
        self.recovery_button.clicked.connect(
            lambda: self.request_reboot(OperationType.REBOOT_RECOVERY)
        )
        self.bootloader_button = QPushButton("Reboot to Bootloader")
        self.bootloader_button.setObjectName("secondaryButton")
        self.bootloader_button.clicked.connect(
            lambda: self.request_reboot(OperationType.REBOOT_BOOTLOADER)
        )
        action_row = QHBoxLayout()
        action_row.addWidget(self.info_button)
        action_row.addWidget(self.verify_button)
        action_row.addWidget(self.diagnostics_button)
        action_row.addWidget(self.log_lines)
        action_row.addWidget(self.logcat_button)
        action_row.addStretch()
        action_row.addWidget(self.recovery_button)
        action_row.addWidget(self.bootloader_button)
        for button in (
            self.info_button, self.verify_button, self.diagnostics_button,
            self.logcat_button, self.recovery_button, self.bootloader_button,
        ):
            button.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.setSpacing(12)
        for widget in (title, subtitle, self.tool_status, self.refresh_button, self.table, case_frame):
            layout.addWidget(widget)
        layout.addLayout(action_row)
        layout.addWidget(self.guidance)
        layout.addWidget(self.summary)
        layout.setStretchFactor(self.table, 1)

    def refresh_devices(self):
        if self.refresh_thread is not None:
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Refreshing...")
        self.refresh_thread = QThread(self)
        self.refresh_worker = CallableWorker(self.service.collect_devices)
        self.refresh_worker.moveToThread(self.refresh_thread)
        self.refresh_thread.started.connect(self.refresh_worker.run)
        self.refresh_worker.succeeded.connect(self._devices_loaded)
        self.refresh_worker.failed.connect(self._devices_failed)
        self.refresh_worker.finished.connect(self.refresh_thread.quit)
        self.refresh_worker.finished.connect(self.refresh_worker.deleteLater)
        self.refresh_thread.finished.connect(self._refresh_finished)
        self.refresh_thread.finished.connect(self.refresh_thread.deleteLater)
        self.refresh_thread.start()

    def refresh(self):
        """F5 dispatcher entry point; starts at most one device refresh."""
        self.refresh_devices()

    def _devices_loaded(self, result):
        tools = result["tools"]
        self.tool_status.setText(self.service.tool_status_message(tools))
        self.tool_status.setWordWrap(True)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for device in result["devices"]:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, key in enumerate(("serial", "mode", "state", "model", "product", "device")):
                self.table.setItem(row, column, QTableWidgetItem(device[key]))
        self.table.setSortingEnabled(True)
        self._selection_changed()
        count = len(result["devices"])
        message = f"Detected {count} device{'s' if count != 1 else ''}."
        if result["errors"]:
            message += " " + " ".join(result["errors"])
        self.summary.setText(message)

    def _devices_failed(self, error_message):
        QMessageBox.critical(self, "Android Device Manager Error", f"ARC3 could not refresh Android devices.\n\n{error_message}")

    def _refresh_finished(self):
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("Refresh Devices")
        self.refresh_worker = None
        self.refresh_thread = None

    def selected_serial(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        item = self.table.item(selected[0].row(), 0)
        return item.text() if item else None

    def selected_mode(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        item = self.table.item(selected[0].row(), 1)
        return item.text() if item else None

    def _selection_changed(self):
        selected = self.selected_serial() is not None
        identified_case = (
            bool(self.case_id.text().strip())
            and bool(self.technician_id.text().strip())
        )
        authorized_case = (
            identified_case
            and self.ownership_confirmed.isChecked()
        )
        idle = self.operation_thread is None and self.verification_thread is None
        self.info_button.setEnabled(selected and identified_case and idle)
        mode = self.selected_mode()
        state = None
        rows = self.table.selectionModel().selectedRows()
        if rows:
            item = self.table.item(rows[0].row(), 2)
            state = item.text() if item else ""
        self.guidance.setText(
            self.service.guidance(mode, state or "") if selected else
            "Select a device for connection guidance."
        )
        authorized_adb = mode == "ADB" and (state or "").casefold() == "device"
        self.verify_button.setEnabled(selected and identified_case and idle)
        self.diagnostics_button.setEnabled(authorized_adb and identified_case and idle)
        self.logcat_button.setEnabled(authorized_adb and identified_case and idle)
        self.recovery_button.setEnabled(selected and authorized_case and idle)
        self.bootloader_button.setEnabled(selected and authorized_case and idle)

    def operation_arguments(self, operation):
        return (
            self.selected_serial(), self.selected_mode(), operation, self.case_id.text().strip(),
            self.technician_id.text().strip(), self.ownership_confirmed.isChecked(),
        )

    def show_device_record(self):
        result = self.service.run_operation(*self.operation_arguments(OperationType.READ_INFO))
        if not result.success:
            QMessageBox.warning(self, "Device Record", result.message)
            return
        details = "\n".join(f"{key.replace('_', ' ').title()}: {value}" for key, value in result.data.items())
        QMessageBox.information(self, "Device Record", details)

    def verify_hardware(self):
        serial = self.selected_serial()
        mode = self.selected_mode()
        if serial is None or mode is None or self.verification_thread is not None:
            return
        self.verification_thread = QThread(self)
        self.verification_worker = CallableWorker(
            lambda: self.service.verify_hardware(
                serial, mode, self.case_id.text().strip(),
                self.technician_id.text().strip(),
            )
        )
        self.verification_worker.moveToThread(self.verification_thread)
        self.verification_thread.started.connect(self.verification_worker.run)
        self.verification_worker.succeeded.connect(self._verification_completed)
        self.verification_worker.failed.connect(self._verification_failed)
        self.verification_worker.finished.connect(self.verification_thread.quit)
        self.verification_worker.finished.connect(self.verification_worker.deleteLater)
        self.verification_thread.finished.connect(self._verification_finished)
        self.verification_thread.finished.connect(self.verification_thread.deleteLater)
        self._selection_changed()
        self.verification_thread.start()

    def _verification_completed(self, result):
        checks = result.data.get("checks", {})
        lines = []
        for key, value in result.data.items():
            if key != "checks":
                lines.append(f"{key.replace('_', ' ').title()}: {value}")
        if checks:
            lines.append("\nVerification checks:")
            lines.extend(
                f"{key.replace('_', ' ').title()}: {'Pass' if value else 'Review'}"
                for key, value in checks.items()
            )
        dialog = QMessageBox.information if result.success else QMessageBox.warning
        dialog(self, "Hardware Verification", f"{result.message}\n\n" + "\n".join(lines))

    def _verification_failed(self, error_message):
        QMessageBox.critical(
            self, "Hardware Verification Error",
            f"ARC3 could not verify the selected device.\n\n{error_message}",
        )

    def _verification_finished(self):
        self.verification_worker = None
        self.verification_thread = None
        self._selection_changed()

    def run_diagnostics(self):
        if self.operation_thread is not None:
            return
        serial, mode = self.selected_serial(), self.selected_mode()
        self._start_operation(
            lambda: self.service.collect_diagnostics(
                serial, mode, self.case_id.text().strip(),
                self.technician_id.text().strip(),
            ),
            self._diagnostics_completed,
        )

    def _diagnostics_completed(self, result):
        if not result.success:
            QMessageBox.warning(self, "ADB Diagnostics", result.message)
            return
        sections = []
        for heading, values in result.data.items():
            lines = [f"{key}: {value}" for key, value in values.items()]
            sections.append(f"{heading.upper()}\n" + "\n".join(lines))
        QMessageBox.information(
            self, "ADB Diagnostics", result.message + "\n\n" + "\n\n".join(sections),
        )

    def export_logcat(self):
        serial, mode = self.selected_serial(), self.selected_mode()
        if not serial or self.operation_thread is not None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export bounded logcat capture", f"ARC3_logcat_{serial}.txt",
            "Text files (*.txt);;All files (*)",
        )
        if not path:
            return
        answer = QMessageBox.warning(
            self, "Export Logcat",
            "Logcat can contain private application, account, and device data. "
            "Export it only to an approved case location.\n\nContinue with this bounded capture?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        line_count = self.log_lines.value()
        self._start_operation(
            lambda: self.service.capture_logcat(
                serial, mode, self.case_id.text().strip(),
                self.technician_id.text().strip(), line_count, path,
            ),
            self._logcat_completed,
        )

    def _logcat_completed(self, result):
        dialog = QMessageBox.information if result.success else QMessageBox.warning
        detail = f"\n\nSaved to: {result.data.get('export_path')}" if result.success else ""
        dialog(self, "Logcat Export", result.message + detail)

    def _start_operation(self, function, completed):
        self.operation_thread = QThread(self)
        self.operation_worker = CallableWorker(function)
        self.operation_worker.moveToThread(self.operation_thread)
        self.operation_thread.started.connect(self.operation_worker.run)
        self.operation_worker.succeeded.connect(completed)
        self.operation_worker.failed.connect(self._operation_failed)
        self.operation_worker.finished.connect(self.operation_thread.quit)
        self.operation_worker.finished.connect(self.operation_worker.deleteLater)
        self.operation_thread.finished.connect(self._operation_finished)
        self.operation_thread.finished.connect(self.operation_thread.deleteLater)
        self._selection_changed()
        self.operation_thread.start()

    def request_reboot(self, operation):
        serial = self.selected_serial()
        target = "Recovery" if operation is OperationType.REBOOT_RECOVERY else "Bootloader"
        answer = QMessageBox.question(
            self, f"Reboot to {target}",
            f"Request {serial} to reboot into {target}?\n\nThis operation will be written to the audit log.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        arguments = self.operation_arguments(operation)
        self._start_operation(
            lambda: self.service.run_operation(*arguments), self._operation_completed,
        )

    def _operation_completed(self, result):
        if result.success:
            QMessageBox.information(self, "Device Operation", result.message)
        else:
            QMessageBox.warning(self, "Device Operation Blocked", result.message)

    def _operation_failed(self, error_message):
        QMessageBox.critical(self, "Device Operation Error", error_message)

    def _operation_finished(self):
        self.operation_worker = None
        self.operation_thread = None
        self._selection_changed()
