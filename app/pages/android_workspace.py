from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFormLayout, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
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
        action_row.addStretch()
        action_row.addWidget(self.recovery_button)
        action_row.addWidget(self.bootloader_button)
        for button in (self.info_button, self.recovery_button, self.bootloader_button):
            button.setEnabled(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 22)
        layout.setSpacing(12)
        for widget in (title, subtitle, self.tool_status, self.refresh_button, self.table, case_frame):
            layout.addWidget(widget)
        layout.addLayout(action_row)
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

    def _devices_loaded(self, result):
        tools = result["tools"]
        self.tool_status.setText(
            f"ADB: {'available' if tools['adb'] else 'not found'}  |  "
            f"Fastboot: {'available' if tools['fastboot'] else 'not found'}"
        )
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
        idle = self.operation_thread is None
        self.info_button.setEnabled(selected and identified_case and idle)
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
        self.operation_thread = QThread(self)
        self.operation_worker = CallableWorker(lambda: self.service.run_operation(*arguments))
        self.operation_worker.moveToThread(self.operation_thread)
        self.operation_thread.started.connect(self.operation_worker.run)
        self.operation_worker.succeeded.connect(self._operation_completed)
        self.operation_worker.failed.connect(self._operation_failed)
        self.operation_worker.finished.connect(self.operation_thread.quit)
        self.operation_worker.finished.connect(self.operation_worker.deleteLater)
        self.operation_thread.finished.connect(self._operation_finished)
        self.operation_thread.finished.connect(self.operation_thread.deleteLater)
        self._selection_changed()
        self.operation_thread.start()

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
