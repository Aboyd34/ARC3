from __future__ import annotations

from PySide6.QtCore import QThread, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
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

from app.services.services_service import ServicesService
from app.workers.callable_worker import CallableWorker


class NumericTableItem(QTableWidgetItem):
    def __init__(self, display_text: str, numeric_value: int):
        super().__init__(display_text)
        self.numeric_value = numeric_value

    def __lt__(self, other):
        if isinstance(other, NumericTableItem):
            return self.numeric_value < other.numeric_value
        return super().__lt__(other)


class ServicesTab(QWidget):
    COLUMNS = (
        ("name", "Service Name"),
        ("display_name", "Display Name"),
        ("status", "Status"),
        ("startup_type", "Startup Type"),
        ("pid", "Process ID"),
        ("description", "Description"),
    )

    def __init__(self, auto_refresh: bool = True):
        super().__init__()
        self.service = ServicesService()
        self.services = []
        self.refresh_thread = None
        self.refresh_worker = None
        self.action_thread = None
        self.action_worker = None
        self.pending_service_name = None
        self.refresh_after_action = False
        self.build_ui()

        if auto_refresh:
            QTimer.singleShot(0, self.refresh)

    def build_ui(self):
        heading = QLabel("Services Manager")
        heading.setObjectName("tabHeading")

        description = QLabel(
            "Inspect Windows services and safely control supported "
            "service states."
        )
        description.setObjectName("tabDescription")

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)
        title_layout.addWidget(heading)
        title_layout.addWidget(description)

        self.count_label = QLabel("0 services")
        self.count_label.setObjectName("updatedLabel")

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryButton")
        self.refresh_button.clicked.connect(self.refresh)

        heading_row = QHBoxLayout()
        heading_row.addLayout(title_layout)
        heading_row.addStretch()
        heading_row.addWidget(self.count_label)
        heading_row.addWidget(self.refresh_button)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText(
            "Search service name, display name, status, startup type, "
            "PID, or description..."
        )
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self.apply_filter)

        self.table = QTableWidget()
        self.table.setObjectName("servicesTable")
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
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)

        details_frame = QFrame()
        details_frame.setObjectName("processActionBar")

        self.detail_name = QLabel(
            "Select a service to view details and available actions."
        )
        self.detail_name.setObjectName("cardTitle")
        self.detail_status = QLabel("")
        self.detail_status.setObjectName("systemValue")
        self.detail_description = QLabel("")
        self.detail_description.setObjectName("updatedLabel")
        self.detail_description.setWordWrap(True)

        detail_text = QVBoxLayout()
        detail_text.setSpacing(3)
        detail_text.addWidget(self.detail_name)
        detail_text.addWidget(self.detail_status)
        detail_text.addWidget(self.detail_description)

        self.start_button = self._action_button(
            "Start",
            "primaryButton",
            "start",
        )
        self.stop_button = self._action_button(
            "Stop",
            "dangerButton",
            "stop",
        )
        self.pause_button = self._action_button(
            "Pause",
            "secondaryButton",
            "pause",
        )
        self.resume_button = self._action_button(
            "Resume",
            "secondaryButton",
            "resume",
        )
        self.restart_button = self._action_button(
            "Restart",
            "secondaryButton",
            "restart",
        )
        self.action_buttons = {
            "start": self.start_button,
            "stop": self.stop_button,
            "pause": self.pause_button,
            "resume": self.resume_button,
            "restart": self.restart_button,
        }

        action_layout = QHBoxLayout()
        action_layout.setSpacing(6)
        action_layout.addWidget(self.start_button)
        action_layout.addWidget(self.stop_button)
        action_layout.addWidget(self.pause_button)
        action_layout.addWidget(self.resume_button)
        action_layout.addWidget(self.restart_button)

        details_layout = QHBoxLayout(details_frame)
        details_layout.setContentsMargins(14, 10, 14, 10)
        details_layout.addLayout(detail_text, 1)
        details_layout.addLayout(action_layout)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addLayout(heading_row)
        layout.addWidget(self.search_box)
        layout.addWidget(self.table, 1)
        layout.addWidget(details_frame)

    def _action_button(
        self,
        text: str,
        object_name: str,
        action: str,
    ) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setEnabled(False)
        button.clicked.connect(
            lambda checked=False, selected_action=action: (
                self.request_action(selected_action)
            )
        )
        return button

    def refresh(self):
        if self.refresh_thread is not None or self.action_thread is not None:
            return

        selected = self.selected_service()
        self.pending_service_name = (
            selected["name"] if selected is not None else None
        )
        self.refresh_button.setEnabled(False)
        self.count_label.setText("Loading Windows services...")

        self.refresh_thread = QThread(self)
        self.refresh_worker = CallableWorker(
            self.service.collect_services
        )
        self.refresh_worker.moveToThread(self.refresh_thread)
        self.refresh_thread.started.connect(self.refresh_worker.run)
        self.refresh_worker.succeeded.connect(self._services_loaded)
        self.refresh_worker.failed.connect(self._services_failed)
        self.refresh_worker.finished.connect(self.refresh_thread.quit)
        self.refresh_worker.finished.connect(
            self.refresh_worker.deleteLater
        )
        self.refresh_thread.finished.connect(self._refresh_finished)
        self.refresh_thread.finished.connect(
            self.refresh_thread.deleteLater
        )
        self.refresh_thread.start()

    def refresh_data(self):
        self.refresh()

    def _services_loaded(self, services):
        self.services = services
        self.populate_table()
        self._notify(
            f"Loaded {len(services)} Windows services.",
            "success",
        )

    def _services_failed(self, error_message):
        QMessageBox.critical(
            self,
            "Services Manager Error",
            f"ARC3 could not load Windows services.\n\n{error_message}",
        )
        self.count_label.setText("Service discovery failed")

    def _refresh_finished(self):
        self.refresh_button.setEnabled(True)
        self.refresh_worker = None
        self.refresh_thread = None

    def populate_table(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        selected_row = None

        for service in self.services:
            row = self.table.rowCount()
            self.table.insertRow(row)

            for column, (field, _) in enumerate(self.COLUMNS):
                value = service.get(field, "")
                if field == "pid":
                    numeric_value = int(value or 0)
                    text = str(numeric_value) if numeric_value else "—"
                    item = NumericTableItem(text, numeric_value)
                else:
                    item = QTableWidgetItem(str(value))

                if column == 0:
                    item.setData(Qt.UserRole, service)
                self.table.setItem(row, column, item)

            if service["name"] == self.pending_service_name:
                selected_row = row

        self.table.setSortingEnabled(True)
        self.apply_filter(self.search_box.text())

        if selected_row is not None:
            self.table.selectRow(selected_row)
        else:
            self.update_details()

    def apply_filter(self, text):
        query = text.strip().casefold()
        visible_count = 0

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
                visible_count += 1

        if query:
            self.count_label.setText(
                f"{visible_count} matching services"
            )
        else:
            self.count_label.setText(f"{len(self.services)} services")

    def selected_service(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def update_details(self):
        service = self.selected_service()

        if service is None:
            self.detail_name.setText(
                "Select a service to view details and available actions."
            )
            self.detail_status.setText("")
            self.detail_description.setText("")
            self._set_action_buttons()
            return

        pid = service["pid"] or "Not running"
        self.detail_name.setText(
            f"{service['display_name']} ({service['name']})"
        )
        self.detail_status.setText(
            f"Status: {service['status']}  •  "
            f"Startup: {service['startup_type']}  •  PID: {pid}"
        )
        self.detail_description.setText(
            service["description"] or "No description is available."
        )
        self._set_action_buttons(service["status"])

    def _set_action_buttons(self, status: str = ""):
        busy = self.action_thread is not None
        normalized = status.casefold()
        enabled = {
            "start": normalized == "stopped",
            "stop": normalized in {"running", "paused"},
            "pause": normalized == "running",
            "resume": normalized == "paused",
            "restart": normalized in {"running", "paused"},
        }

        for action, button in self.action_buttons.items():
            button.setEnabled(not busy and enabled[action])

    def request_action(self, action: str):
        service = self.selected_service()
        if service is None or self.action_thread is not None:
            return

        answer = QMessageBox.question(
            self,
            f"{action.title()} Service",
            (
                f"Are you sure you want to {action} "
                f"“{service['display_name']}”?\n\n"
                f"Service name: {service['name']}"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self._start_action(service["name"], action)

    def _start_action(self, service_name: str, action: str):
        self.refresh_button.setEnabled(False)
        self.refresh_after_action = False

        self.action_thread = QThread(self)
        self._set_action_buttons()
        self.action_worker = CallableWorker(
            lambda: self.service.perform_action(
                service_name,
                action,
            )
        )
        self.action_worker.moveToThread(self.action_thread)
        self.action_thread.started.connect(self.action_worker.run)
        self.action_worker.succeeded.connect(self._action_completed)
        self.action_worker.failed.connect(self._action_failed)
        self.action_worker.finished.connect(self.action_thread.quit)
        self.action_worker.finished.connect(
            self.action_worker.deleteLater
        )
        self.action_thread.finished.connect(self._action_finished)
        self.action_thread.finished.connect(
            self.action_thread.deleteLater
        )
        self.action_thread.start()

    def _action_completed(self, result):
        if result["success"]:
            self._notify(result["message"], "success", 3000)
            self.refresh_after_action = True
        else:
            QMessageBox.warning(
                self,
                "Service Action Failed",
                result["message"],
            )

    def _action_failed(self, error_message):
        QMessageBox.critical(
            self,
            "Service Action Failed",
            (
                "ARC3 could not complete the service action.\n\n"
                f"{error_message}"
            ),
        )

    def _action_finished(self):
        should_refresh = self.refresh_after_action
        self.action_worker = None
        self.action_thread = None
        self.refresh_button.setEnabled(True)
        self.update_details()

        if should_refresh:
            self.refresh_after_action = False
            self.refresh()

    def _notify(self, message, kind="info", duration=2200):
        notification = getattr(
            self.window(),
            "show_arc3_notification",
            None,
        )
        if notification:
            notification(message, kind, duration)
